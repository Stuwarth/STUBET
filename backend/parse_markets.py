import json

def calculate_ev(prob, odds):
    return (prob * odds) - 1

try:
    with open('raw_markets.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    markets = data.get('markets', [])
    
    # Create odds lookup dictionary
    odds_dict = {}
    if isinstance(data.get('odds'), dict):
        odds_dict = data['odds']
    elif isinstance(data.get('odds'), list):
        for o in data['odds']:
            odds_dict[str(o.get('id', ''))] = o
            
    with open('scratch/edge.md', 'w', encoding='utf-8') as out:
        out.write("### 🔍 ESCÁNER DE MERCADOS: LAS PLATAS\n")
        out.write("| Mercado de Interés | Línea Ofrecida | Cuota LasPlatas | Probabilidad STUBET | Expected Value (Edge) |\n")
        out.write("| :--- | :---: | :---: | :---: | :---: |\n")
        
        for m in markets:
            name = m.get('name', '').lower()
            
            # Extract runners from new structure
            runners = []
            for item in m.get('desktopOddIds', []):
                if isinstance(item, list):
                    for oid in item:
                        runners.append(odds_dict.get(str(oid), {}))
                else:
                    runners.append(odds_dict.get(str(item), {}))
                    
            # 1. Corners Handicap
            if 'córner' in name and 'hándicap' in name:
                for r in runners:
                    sv = r.get('sv', '')
                    if 'manchester city' in r.get('name', '').lower() and sv in ['-1.5', '-2.5']:
                        odds = r.get('price', r.get('oddsDecimal', 0))
                        prob = 0.90
                        ev = calculate_ev(prob, odds)
                        icon = "🟢 VALUE" if ev > 0.1 else "🟡 OK"
                        out.write(f"| Córners: City {sv} | {sv} | @{odds} | 90% | **+{ev:.2f}** {icon} |\n")
            
            # 2. Cards Match Bet (More cards)
            if 'tarjeta' in name and ('más' in name or 'ganador' in name or 'recibirá' in name):
                for r in runners:
                    if 'everton' in r.get('name', '').lower():
                        odds = r.get('price', r.get('oddsDecimal', 0))
                        prob = 0.85
                        ev = calculate_ev(prob, odds)
                        icon = "🟢 VALUE" if ev > 0.1 else "🟡 OK"
                        out.write(f"| Tarjetas: Everton recibe más | - | @{odds} | 85% | **+{ev:.2f}** {icon} |\n")
                        
            # 3. Shots on Target (City)
            if 'remate' in name and 'puerta' in name and 'manchester city' in name:
                for r in runners:
                    sv = r.get('sv', '')
                    if r.get('name', '').lower() == 'más de' and sv == '5.5':
                        odds = r.get('price', r.get('oddsDecimal', 0))
                        prob = 0.80
                        ev = calculate_ev(prob, odds)
                        icon = "🟢 VALUE" if ev > 0.1 else "🟡 OK"
                        out.write(f"| Remates a Puerta City | >5.5 | @{odds} | 80% | **+{ev:.2f}** {icon} |\n")

except Exception as e:
    print("Error:", e)
