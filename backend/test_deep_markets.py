import asyncio
import aiohttp
import json

# Configuraciones de Altenar (LasPlatas usa biahosted)
ALTENAR_BASE_URL = "https://sb2frontend-altenar2.biahosted.com/api/widget"
WIDGET_CONFIG = {
    "timezoneOffset": 240, # Ajusta según tu zona
    "langId": 4,           # Español
    "skinName": "lasplatas", # o el default de ellos
    "configId": 1,
    "culture": "es-ES",
    "countryCode": "BO"
}

async def fetch_all_markets(event_id: int):
    """
    Extrae ABSOLUTAMENTE TODOS los mercados de un partido específico 
    usando la API secreta de Altenar.
    """
    url = f"{ALTENAR_BASE_URL}/GetEventDetails"
    
    # Parámetros requeridos por Altenar
    params = {
        "timezoneOffset": WIDGET_CONFIG["timezoneOffset"],
        "langId": WIDGET_CONFIG["langId"],
        "skinName": WIDGET_CONFIG["skinName"],
        "configId": WIDGET_CONFIG["configId"],
        "culture": WIDGET_CONFIG["culture"],
        "countryCode": WIDGET_CONFIG["countryCode"],
        "deviceType": "Desktop",
        "eventId": event_id
    }

    print(f"🚀 Iniciando extracción profunda para el Evento ID: {event_id}...")

    async with aiohttp.ClientSession() as session:
        # Añadimos cabeceras para parecer un navegador legítimo
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://www.lasplatas.com",
            "Referer": "https://www.lasplatas.com/"
        }
        
        async with session.get(url, params=params, headers=headers) as response:
            if response.status != 200:
                print(f"❌ Error al conectar. Status: {response.status}")
                return

            data = await response.json()
            
            # Verificamos si el evento existe en la respuesta
            if "event" not in data:
                print("❌ No se encontraron datos para este evento. (¿ID incorrecto o partido ya terminó?)")
                return

            event = data["event"]
            match_name = f"{event['competitors'][0]['name']} vs {event['competitors'][1]['name']}"
            print(f"\n✅ Partido Encontrado: {match_name}")
            print("="*50)

            # La magia está aquí: Iteramos por cada mercado disponible
            markets = event.get("markets", [])
            print(f"🔥 Se encontraron {len(markets)} mercados totales para este partido.\n")

            # Filtramos solo los mercados más jugosos (SOT, Corners, Tarjetas, Goles)
            target_keywords = ["puerta", "esquina", "tarjeta", "goles", "ganador"]
            
            for market in markets:
                market_name = market.get("name", "")
                
                # Puedes quitar este 'if' si quieres imprimir LITERALMENTE los 300 mercados
                if any(kw in market_name.lower() for kw in target_keywords):
                    print(f"📊 Mercado: {market_name}")
                    for runner in market.get("runners", []):
                        # Extraer la línea (ej: 8.5) si existe
                        line = runner.get("line", "")
                        line_str = f" ({line})" if line else ""
                        
                        runner_name = runner.get("name", "")
                        price = runner.get("price", "N/A")
                        print(f"   -> {runner_name}{line_str}: Cuota @{price}")
                    print("-" * 30)

async def main():
    import sys
    
    # Extraemos el ID del URL si es necesario
    if len(sys.argv) > 1:
        # Extraer el ID si pasan el URL completo
        arg = sys.argv[1]
        if "event/" in arg:
            event_id = int(arg.split("event/")[1].split("/")[0].split("?")[0])
        else:
            event_id = int(arg)
    else:
        event_id = 4851234
        
    await fetch_all_markets(event_id)

if __name__ == "__main__":
    asyncio.run(main())
