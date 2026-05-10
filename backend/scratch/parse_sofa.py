import json

def parse():
    with open('sofa_stats.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    def extract_stats(events, team_name):
        matches = []
        for ev in events:
            match_name = ev['match']
            # Find which team is home or away
            is_home = False
            parts = match_name.split(' vs ')
            if len(parts) == 2 and team_name in parts[0]:
                is_home = True
            
            stats = ev['stats']
            period = next((p for p in stats.get('statistics', []) if p['period'] == 'ALL'), None)
            if not period: continue
            
            groups = period.get('groups', [])
            
            match_data = {'match': match_name, 'corners': 0, 'cards': 0, 'shots': 0, 'sot': 0, 'fouls': 0, 'offsides': 0}
            
            for g in groups:
                for stat in g.get('statisticsItems', []):
                    name = stat['name']
                    home_val = int(stat.get('home', 0))
                    away_val = int(stat.get('away', 0))
                    val = home_val if is_home else away_val
                    
                    if name == 'Corner kicks': match_data['corners'] = val
                    elif name == 'Yellow cards': match_data['cards'] += val
                    elif name == 'Red cards': match_data['cards'] += val
                    elif name == 'Total shots': match_data['shots'] = val
                    elif name == 'Shots on target': match_data['sot'] = val
                    elif name == 'Fouls': match_data['fouls'] = val
                    elif name == 'Offsides': match_data['offsides'] = val
            matches.append(match_data)
        return matches

    eve = extract_stats(data.get('EVE', []), 'Everton')
    mci = extract_stats(data.get('MCI', []), 'Man City')
    
    # H2H - we want to show both teams. So let's extract raw stats for both.
    h2h_matches = []
    for ev in data.get('H2H', []):
        match_name = ev['match']
        stats = ev['stats']
        period = next((p for p in stats.get('statistics', []) if p['period'] == 'ALL'), None)
        if not period: continue
        groups = period.get('groups', [])
        
        match_data = {'match': match_name, 'corners': [0,0], 'cards': [0,0], 'shots': [0,0], 'sot': [0,0], 'fouls': [0,0], 'offsides': [0,0]}
        for g in groups:
            for stat in g.get('statisticsItems', []):
                name = stat['name']
                h_val = int(stat.get('home', 0))
                a_val = int(stat.get('away', 0))
                if name == 'Corner kicks': match_data['corners'] = [h_val, a_val]
                elif name == 'Yellow cards': match_data['cards'][0] += h_val; match_data['cards'][1] += a_val
                elif name == 'Red cards': match_data['cards'][0] += h_val; match_data['cards'][1] += a_val
                elif name == 'Total shots': match_data['shots'] = [h_val, a_val]
                elif name == 'Shots on target': match_data['sot'] = [h_val, a_val]
                elif name == 'Fouls': match_data['fouls'] = [h_val, a_val]
                elif name == 'Offsides': match_data['offsides'] = [h_val, a_val]
        h2h_matches.append(match_data)
        
    print("EVERTON:", json.dumps(eve))
    print("MAN CITY:", json.dumps(mci))
    print("H2H:", json.dumps(h2h_matches))

if __name__ == '__main__':
    parse()
