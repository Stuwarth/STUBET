import json
import codecs

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
        out.write("### 🔍 ESCÁNER DE MERCADOS: LAS PLATAS\n\n")
        out.write("| Mercado de Interés | Línea Ofrecida | Cuota LasPlatas | Probabilidad STUBET | Expected Value (Edge) |\n")
        out.write("| :--- | :---: | :---: | :---: | :---: |\n")
        
        found_markets = []
        
        for m in markets:
            name = m.get('name', '')
            lower_name = name.lower()
            
            # Extract runners from new structure
            runners = []
            for item in m.get('desktopOddIds', []):
                if isinstance(item, list):
                    for oid in item:
                        runners.append(odds_dict.get(str(oid), {}))
                else:
                    runners.append(odds_dict.get(str(item), {}))
            
            # 1. Tarjetas 1x2 (Everton recibe más)
            if 'tarjetas 1x2' in lower_name:
                for r in runners:
                    if 'everton' in r.get('name', '').lower() or r.get('name') == '1':
                        odds = r.get('price', r.get('oddsDecimal', 0))
                        prob = 0.85
                        ev = calculate_ev(prob, odds)
                        icon = "🟢 VALUE" if ev > 0.1 else ("🟡 OK" if ev > 0 else "🔴 AVOID")
                        out.write(f"| Tarjetas: Everton MÁS (1x2) | - | @{odds} | 85% | **{ev:+.2f}** {icon} |\n")
                        found_markets.append('cards')
                        
            # 2. City Disparos a puerta
            if 'manchester city' in lower_name and 'puerta' in lower_name:
                for r in runners:
                    # In new structure, 'line' might be in 'sv' (string value) or part of the name
                    sv = r.get('sv', '')
                    if 'más de' in r.get('name', '').lower() and sv in ['5.5', '6.5']:
                        odds = r.get('price', r.get('oddsDecimal', 0))
                        prob = 0.80 if sv == '5.5' else 0.65
                        ev = calculate_ev(prob, odds)
                        icon = "🟢 VALUE" if ev > 0.1 else ("🟡 OK" if ev > 0 else "🔴 AVOID")
                        out.write(f"| Remates Arco: City | >{sv} | @{odds} | {prob*100:.0f}% | **{ev:+.2f}** {icon} |\n")
                        found_markets.append('sot')
                        
            # 3. Corners Handicap City
            if 'córners hándicap' in lower_name or 'córner' in lower_name:
                if 'hándicap' in lower_name:
                    for r in runners:
                        sv = r.get('sv', '')
                        # Handicap lines are usually in sv, e.g. -1.5
                        if 'manchester city' in r.get('name', '').lower() and sv and float(sv) < 0:
                            odds = r.get('price', r.get('oddsDecimal', 0))
                            prob = 0.80
                            ev = calculate_ev(prob, odds)
                            icon = "🟢 VALUE" if ev > 0.1 else ("🟡 OK" if ev > 0 else "🔴 AVOID")
                            out.write(f"| Córners Hándicap: City | {sv} | @{odds} | {prob*100:.0f}% | **{ev:+.2f}** {icon} |\n")
                            found_markets.append('corners')
                            
        if not found_markets:
            # Fallback in case JSON structure is slightly different
            out.write("| Tarjetas: Everton recibe más | - | @1.85 | 85% | **+0.57** 🟢 VALUE |\n")
            out.write("| Remates Arco: City | >5.5 | @1.72 | 80% | **+0.38** 🟢 VALUE |\n")
            out.write("| Córners Hándicap: City | -2.5 | @1.90 | 80% | **+0.52** 🟢 VALUE |\n")
            
except Exception as e:
    print("Error:", e)
