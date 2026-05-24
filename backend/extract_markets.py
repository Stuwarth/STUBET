import json

with open(r'c:\Users\stuwa\Desktop\SportsAI-Predictor\backend\raw_markets.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

markets = data.get('markets', [])
odds_list = data.get('odds', [])

# Build odds lookup by id
odds_map = {o['id']: o for o in odds_list}

# Now let's extract ALL markets with their odds
all_markets = {}
for m in markets:
    name = m.get('name', '')
    odd_ids = m.get('desktopOddIds', [])
    resolved = []
    for group in odd_ids:
        for oid in group:
            o = odds_map.get(oid)
            if o:
                resolved.append({
                    'name': o.get('name',''), 
                    'price': o.get('price'), 
                    'specialValue': o.get('specialValue','')
                })
    if resolved:
        all_markets[name] = resolved

# Write ALL extracted markets to a readable file
with open(r'c:\Users\stuwa\Desktop\SportsAI-Predictor\backend\extracted_odds.txt', 'w', encoding='utf-8') as out:
    for mk, odds in all_markets.items():
        out.write(f'\n=== {mk} ===\n')
        for o in odds:
            sv = f' [{o["specialValue"]}]' if o['specialValue'] else ''
            out.write(f'  {o["name"]}{sv}: {o["price"]}\n')

print(f'Total markets with odds: {len(all_markets)}')
print('Written to extracted_odds.txt')

# Also print the key ones to stdout
interesting = ['1x2', 'Total de goles', 'Ambos equipos marcan', 'Doble oportunidad',
               'Total Tiros De Esquina', 'FC Barcelona total de goles', 'Real Madrid total de goles',
               'Remates', 'Remates a puerta', 'Multigoles', 'FC Barcelona multigoles', 'Real Madrid multigoles',
               'Hándicap', 'TOTAL TIROS DE ESQUINA FC Barcelona', 'TOTAL TIROS DE ESQUINA Real Madrid']

for mk in interesting:
    if mk in all_markets:
        print(f'\n=== {mk} ===')
        for o in all_markets[mk]:
            sv = f' [{o["specialValue"]}]' if o['specialValue'] else ''
            print(f'  {o["name"]}{sv}: {o["price"]}')
