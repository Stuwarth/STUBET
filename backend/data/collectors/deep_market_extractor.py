import asyncio
import json
from playwright.async_api import async_playwright
import os

async def extract_match_markets(match_url: str, output_file: str = "current_match_markets.json"):
    print(f"🚀 Iniciando extracción profunda con navegador oculto para: {match_url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        captured_data = None

        # Interceptamos la respuesta de Altenar que contiene todos los mercados
        async def handle_response(response):
            nonlocal captured_data
            if "json" in response.headers.get("content-type", "").lower() and response.status == 200:
                try:
                    json_data = await response.json()
                    # Check if this JSON contains event -> markets
                    if "event" in json_data and "markets" in json_data["event"]:
                        captured_data = json_data
                        print(f"✅ ¡JSON masivo capturado desde: {response.url}!")
                    elif "events" in json_data and len(json_data["events"]) > 0 and "markets" in json_data["events"][0]:
                        captured_data = json_data
                        print(f"✅ ¡JSON masivo capturado desde: {response.url}!")
                except Exception:
                    pass

        page.on("response", handle_response)
        
        print("⏳ Navegando a la casa de apuestas y burlando la seguridad...")
        await page.goto(match_url, wait_until="networkidle", timeout=45000)
        
        # Esperamos unos segundos adicionales por si la API de Altenar demora en cargar
        await asyncio.sleep(5)
        
        if captured_data:
            # Filtramos un poco para no guardar basura, solo mercados
            event = captured_data.get('event', captured_data.get('events', [{}])[0])
            markets = event.get("markets", [])
            
            structured_data = {
                "match": f"{event.get('competitors', [{'name': 'A'}])[0].get('name')} vs {event.get('competitors', [{'name': 'A'}, {'name': 'B'}])[1].get('name')}",
                "markets": []
            }
            
            for m in markets:
                runners = []
                for r in m.get("runners", []):
                    runners.append({
                        "name": r.get("name"),
                        "line": r.get("line"),
                        "price": r.get("price")
                    })
                structured_data["markets"].append({
                    "market_name": m.get("name"),
                    "options": runners
                })

            # Guardar el JSON
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(structured_data, f, indent=4, ensure_ascii=False)
            print(f"🎯 Extraídos {len(markets)} mercados y guardados en {output_file}")
        else:
            print("❌ No se pudo capturar el JSON. Revisa la URL.")

        await browser.close()

if __name__ == "__main__":
    import sys
    
    # URL de prueba (Reemplazar con la URL real del partido en LasPlatas)
    match_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.lasplatas.com/es/sports/match/EJEMPLO"
    
    # Crea la ruta absoluta para el JSON de salida
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    output_path = os.path.join(base_dir, "data", "current_match_markets.json")
    
    asyncio.run(extract_match_markets(match_url, output_path))
    print("Script listo para integrarse a STUBET.")
