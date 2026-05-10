import json

def get_markets():
    with open('c:/Users/stuwa/Desktop/SportsAI-Predictor/backend/raw_markets.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    for k, v in data.items():
        if isinstance(v, list) and len(v) > 0 and 'price' in v[0]:
            markets = v
            break
    
    active = [m for m in markets if m.get('oddStatus') != 7]
    
    # We want over/under goals and match winner
    relevant_types = [1, 2, 3, 12, 13, 1714, 1715] # 1x2, over/under, handicap
    
    # Sort them nicely
    out = []
    for m in active:
        if m.get('typeId') in relevant_types or 'Everton' in str(m) or 'City' in str(m):
            out.append(f"{m.get('name')} {m.get('sv', '')} : {m.get('price')} (typeId: {m.get('typeId')})")
            
    with open('c:/Users/stuwa/Desktop/SportsAI-Predictor/backend/scratch/markets_utf8.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))

if __name__ == '__main__':
    get_markets()
