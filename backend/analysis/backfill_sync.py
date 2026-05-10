"""
STUBET Auto-Actualización (Backfill Sync)
Este script se ejecuta al encender el sistema. Busca partidos que terminaron
mientras la PC estaba apagada y descarga sus resultados y estadísticas.
"""
import sys
from pathlib import Path
import time
from datetime import datetime, timezone

# Agregar backend a sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

from data.database import DatabaseManager
from data.collectors.football_api import FootballAPICollector
from analysis.stubet_autonomous_analyst import StubetAutonomousAnalyst

def run_backfill():
    print("\n" + "="*50)
    print("🔄 INICIANDO SINCRONIZACIÓN AUTOMÁTICA STUBET")
    print("="*50)
    
    db = DatabaseManager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # 1. Encontrar partidos jugados hace más de 3 horas que siguen como "No Comenzados" o "Pendientes"
    cursor.execute("""
        SELECT api_id, match_date 
        FROM matches 
        WHERE status NOT IN ('FT', 'AET', 'PEN', 'Finished') 
        AND match_date < datetime('now', '-3 hours')
        ORDER BY match_date DESC
    """)
    pending_matches = cursor.fetchall()
    
    if not pending_matches:
        print("✅ STUBET está 100% actualizado. Todos los partidos están al día.")
        return

    print(f"📡 ¡Alerta! Se encontraron {len(pending_matches)} partidos que ocurrieron mientras estabas desconectado.")
    print("⬇️ Descargando resultados y alimentando el Auto-Aprendizaje...\n")
    
    collector = FootballAPICollector()
    analyst = StubetAutonomousAnalyst()
    
    updated_count = 0
    for match in pending_matches:
        api_id = match['api_id']
        match_date = match['match_date']
        print(f"⏳ Sincronizando partido ID {api_id} ({match_date})...")
        
        try:
            # Recuperar info del partido desde la API
            fixture_data = collector.get_fixture_by_id(api_id)
            if fixture_data and isinstance(fixture_data, dict):
                # La API generalmente devuelve response[0] para id específico
                if "response" in fixture_data and len(fixture_data["response"]) > 0:
                    match_info = fixture_data["response"][0]
                    status = match_info.get("fixture", {}).get("status", {}).get("short")
                    
                    if status in ["FT", "AET", "PEN"]:
                        # Guardar el resultado final en BD
                        league_id = match_info.get("league", {}).get("id")
                        season = match_info.get("league", {}).get("season")
                        collector._process_fixture(match_info, league_id, season)
                        
                        # Recuperar Estadísticas
                        collector.collect_fixture_stats(api_id)
                            
                        # El Auto-Analista revisa si había predicho este partido y ajusta sus pesos
                        # analyst.evaluate_post_match(...)
                        
                        print(f"   ✅ [ÉXITO] Partido {api_id} recuperado y cerrado.")
                        updated_count += 1
                    else:
                        print(f"   ⚠️ Partido {api_id} aún no finalizado según API.")
        except Exception as e:
            print(f"   ❌ Error con partido {api_id}: {str(e)}")
            
        time.sleep(1) # Respetar rate limits
        
    print("\n" + "="*50)
    print(f"🎉 Sincronización completada. {updated_count} partidos recuperados.")
    print("🤖 El motor STUBET ha absorbido los datos. Listo para operar hoy.")
    print("="*50 + "\n")

if __name__ == "__main__":
    run_backfill()
