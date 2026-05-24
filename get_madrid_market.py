import json

with open('backend/raw_markets.json', 'r', encoding='utf-8') as f:
    jdata = json.load(f)

o_dict = {o['id']: o for o in jdata.get('odds',[]) if not isinstance(o['id'], list)}
m_dict = {m['id']: m for m in jdata.get('markets',[]) + jdata.get('childMarkets', [])}

for m in m_dict.values():
    mname = m.get('name', '').lower()
    if 'madrid' in mname and ('mitad' in mname or 'tiempo' in mname) and 'marca' in mname:
        for oid in m.get('desktopOddIds', []):
            if isinstance(oid, list):
                for sub in oid:
                    if sub in o_dict:
                        print(f"Mercado: {m.get('name')} | Selección: {o_dict[sub].get('name')} | Cuota: {o_dict[sub].get('price')}")
            else:
                if oid in o_dict:
                    print(f"Mercado: {m.get('name')} | Selección: {o_dict[oid].get('name')} | Cuota: {o_dict[oid].get('price')}")
