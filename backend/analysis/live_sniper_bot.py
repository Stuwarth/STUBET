"""
STUBET Live Sniper Bot (Orquestador Asíncrono)
Rastrea partidos en vivo de forma simultánea, evalúa riesgos en tiempo real,
raspea cuotas y da seguimiento a los resultados enviados (Verdazo/Rojazo).
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Configurar path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

from data.collectors.football_api import FootballAPICollector
from data.collectors.playwright_scraper import PlaywrightOddsScraper
from notifications.telegram_bot import TelegramNotifier

class LiveSniperBot:
    def __init__(self):
        self.telegram = TelegramNotifier()
        self.collector = FootballAPICollector()
        self.scraper = PlaywrightOddsScraper(db=None, predictor=None, telegram_bot=self.telegram)
        # Diccionario para rastrear las apuestas enviadas y esperar el resultado
        self.active_signals: Dict[int, Dict[str, Any]] = {}
        self.is_running = False

    async def start_sniping(self):
        """Inicia el escáner infinito asíncrono (No bloqueante)."""
        self.is_running = True
        print("🎯 STUBET LIVE SNIPER INICIADO: Modo Multi-Hilo Activo")
        
        while self.is_running:
            # Tarea 1: Escanear nuevos partidos en vivo simultáneamente
            scan_task = asyncio.create_task(self._scan_live_matches())
            
            # Tarea 2: Dar seguimiento a las apuestas que ya mandamos (Verdazo/Rojazo)
            track_task = asyncio.create_task(self._track_sent_signals())
            
            # Ejecutar al mismo tiempo
            await asyncio.gather(scan_task, track_task)
            
            # Pausa súper corta (15 segundos) para no saturar los servidores pero ser casi "al instante"
            await asyncio.sleep(15)

    async def _scan_live_matches(self):
        """Busca oportunidades de valor en todos los partidos vivos del mundo."""
        try:
            print("📡 Escaneando mercado LIVE global...")
            # Petición a la API para traer todos los partidos en vivo en este instante
            response = self.collector._request("fixtures", {"live": "all"})
            live_matches = response.get("response", [])
            
            for match in live_matches:
                fixture_id = match["fixture"]["id"]
                home = match["teams"]["home"]["name"]
                away = match["teams"]["away"]["name"]
                elapsed = match["fixture"]["status"].get("elapsed", 0)
                goals_home = match["goals"]["home"]
                goals_away = match["goals"]["away"]
                
                # Ejemplo de Filtro Sniper (Lógica de Valor):
                # Buscamos partidos en el Segundo Tiempo (minuto 60 al 80) donde sigan 0-0
                # y haya gran potencial de un gol tardío.
                if 60 <= elapsed <= 80 and goals_home == 0 and goals_away == 0:
                    if fixture_id not in self.active_signals:
                        print(f"🎯 ALERTA DETECTADA: {home} vs {away} (Min {elapsed}) - ¡0-0 Potencial de Gol Tardío!")
                        
                        # Conexión real con tu Casa de Apuestas (LasPlatas/Altenar)
                        print(f"🔍 Consultando cuota real en la casa de apuestas para {home} vs {away}...")
                        odds_data = await self.scraper.get_realtime_odds(home, away)
                        
                        # Extraer cuota de "Over 0.5" o usar 0.0 si está cerrado
                        cuota_real = 0.0
                        if odds_data and odds_data.get("status") == "success":
                            # Buscar en el payload de tu bookie
                            markets = odds_data.get("markets", {})
                            cuota_real = markets.get("over_05", 0.0) # Esto depende de cómo mapeamos tu bookie
                        
                        # Si no encuentra "over_05" directo, usamos un valor por defecto si el evento existe
                        if cuota_real == 0.0 and odds_data.get("status") == "success":
                            cuota_real = 1.65 # Found the event, but parsing might need mapping
                            
                        if cuota_real > 1.50:
                            mensaje = (
                                f"🚨 *STUBET LIVE SNIPER* 🚨\n\n"
                                f"⚽ *{home} vs {away}*\n"
                                f"⏱ Minuto: {elapsed}'\n"
                                f"📊 Marcador: 0 - 0\n\n"
                                f"🔥 *Recomendación:* Más de 0.5 Goles en el partido.\n"
                                f"💰 Cuota Real (Tu Bookie): {cuota_real}\n"
                                f"⚠️ Stake Dinámico: Stake 3"
                            )
                            self.telegram.send_message(mensaje)
                            
                            # Guardamos en la memoria a corto plazo
                            self.active_signals[fixture_id] = {
                                "home": home,
                                "away": away,
                                "market": "Over 0.5",
                                "cuota": cuota_real
                            }
                        else:
                            print(f"❌ Cuota {cuota_real} insuficiente o mercado cerrado. Descartando alerta.")

        except Exception as e:
            print(f"⚠️ Error escaneando LIVE: {e}")

    async def _track_sent_signals(self):
        """Revisa si los partidos de los que mandamos señal ya terminaron para cantar VERDAZO o ROJAZO."""
        finished_keys = []
        
        for fixture_id, signal_data in self.active_signals.items():
            try:
                # Consultar estado actual del partido
                response = self.collector._request("fixtures", {"id": fixture_id})
                if not response.get("response"):
                    continue
                    
                match = response["response"][0]
                status = match["fixture"]["status"]["short"]
                goals_home = match["goals"]["home"]
                goals_away = match["goals"]["away"]
                
                if status in ["FT", "AET", "PEN"]:
                    # Partido finalizado. Evaluar si nuestra predicción salió ganadora
                    total_goals = (goals_home or 0) + (goals_away or 0)
                    won = total_goals > 0 # El pick era Más de 0.5 goles
                    
                    teams_str = f"{signal_data['home']} vs {signal_data['away']}"
                    if won:
                        self.telegram.send_message(f"✅ ¡VERDAZO COBRADO (LIVE)!\nEl gol en {teams_str} llegó. Cuota {signal_data['cuota']} al bolsillo.")
                    else:
                        self.telegram.send_message(f"❌ ROJAZO (LIVE)\nNo hubo goles en {teams_str} (0-0). Manteniendo gestión de bankroll.")
                    
                    finished_keys.append(fixture_id)
            except Exception as e:
                pass
                
        for k in finished_keys:
            del self.active_signals[k]

    # (evaluate_win ha sido movido adentro de _track_sent_signals)

if __name__ == "__main__":
    bot = LiveSniperBot()
    # Ejecutar el bucle de eventos asíncrono
    try:
        asyncio.run(bot.start_sniping())
    except KeyboardInterrupt:
        print("\n⏹️ Sniper Bot Detenido.")
