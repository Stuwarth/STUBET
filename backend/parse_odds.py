import json

filepath = r"c:\Users\stuwa\Desktop\SportsAI-Predictor\backend\raw_markets.json"
with open(filepath, 'r', encoding='utf-8') as f:
    data = json.load(f)

odds_dict = data.get('odds', {})
if isinstance(odds_dict, list):
    odds_dict = {str(odd['id']): odd for odd in odds_dict}
elif isinstance(odds_dict, dict):
    odds_dict = {str(k): v for k, v in odds_dict.items()}

markets = data.get('markets', [])

output = []
output.append(f"🔥 PARTIDO: {data.get('name')} 🔥\n")

# Filtramos algunos mercados interesantes para no abrumar
interesting = ["1x2", "Total de goles", "Ambos equipos marcan", "Total Tiros De Esquina", "Total de tarjetas", "Remates a puerta", "Faltas"]

for market in markets:
    m_name = market.get('name', '')
    
    # Filtro básico
    if m_name not in interesting and "Tiros de Esquina" not in m_name and "tarjetas" not in m_name.lower() and "Remates" not in m_name and "Faltas" not in m_name:
        continue
        
    sv = market.get('sv', '')
    if sv:
        m_name += f" ({sv})"
        
    desktop_odd_ids = market.get('desktopOddIds', [])
    
    found_odds = []
    for group in desktop_odd_ids:
        if isinstance(group, list):
            for oid in group:
                odd = odds_dict.get(str(oid))
                if odd:
                    found_odds.append(f"  [{odd.get('name', '?')}] -> Cuota @{odd.get('price', '?')}")
        else:
            oid = group
            odd = odds_dict.get(str(oid))
            if odd:
                found_odds.append(f"  [{odd.get('name', '?')}] -> Cuota @{odd.get('price', '?')}")
                
    if found_odds:
        output.append(f"📊 {m_name}")
        output.extend(found_odds)
        output.append("")

out_path = r"c:\Users\stuwa\Desktop\SportsAI-Predictor\backend\parsed_odds.txt"
with open(out_path, 'w', encoding='utf-8') as f:
    f.write("\n".join(output))

print("Listo!")
