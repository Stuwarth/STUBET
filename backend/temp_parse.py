import json
import traceback

def main():
    try:
        with open('raw_markets.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        odds_list = data.get('odds', [])
        
        valid_bets = []
        for odd in odds_list:
            price = float(odd.get('price', 0))
            if 1.75 <= price <= 2.5: # Rango ideal para Stake 10
                odd_name = odd.get('name', 'N/A')
                sv = odd.get('sv', '')
                sv_str = f" ({sv})" if sv else ""
                
                valid_bets.append({
                    'selection': f"{odd_name}{sv_str}",
                    'price': price,
                    'typeId': odd.get('typeId', '')
                })
                        
        valid_bets.sort(key=lambda x: x['price'])
        
        seen = set()
        unique_bets = []
        for b in valid_bets:
            sig = f"{b['selection']} - {b['price']}"
            if sig not in seen:
                seen.add(sig)
                unique_bets.append(b)
                
        print(f"Total valid odds found: {len(unique_bets)}")
        for b in unique_bets[:40]:
            print(f"Cuota: {b['price']} | Selección/Mercado: {b['selection']} | TypeId: {b['typeId']}")
            
    except Exception as e:
        traceback.print_exc()

if __name__ == '__main__':
    main()
