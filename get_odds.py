import json

with open('backend/raw_markets.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

odds_map = {}
for odd in data.get('odds', []):
    odds_map[odd['id']] = odd

with open('odds_output.txt', 'w', encoding='utf-8') as out:
    def print_market(name):
        for m in data.get('markets', []):
            if name.lower() in m.get('name', '').lower() or m.get('id') == name:
                out.write(f"--- Market: {m.get('name')} ---\n")
                for odd_group in m.get('desktopOddIds', []):
                    if isinstance(odd_group, list):
                        for odd_id in odd_group:
                            if odd_id in odds_map:
                                odd = odds_map[odd_id]
                                out.write(f"  {odd.get('name', 'N/A')}: {odd.get('price', 'N/A')}\n")
                    else:
                        if odd_group in odds_map:
                            odd = odds_map[odd_group]
                            out.write(f"  {odd.get('name', 'N/A')}: {odd.get('price', 'N/A')}\n")

    print_market('1x2')
    print_market('se clasifica')
    print_market('Total de goles')
    print_market('Total Tiros De Esquina')
