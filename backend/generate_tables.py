import json

def get_stat(stats, name, home=True):
    for group in stats.get('statistics', []):
        for item in group.get('groups', []):
            for stat in item.get('statisticsItems', []):
                if stat['name'] == name:
                    return stat['home'] if home else stat['away']
    return '-'

with open('scratch/real_stats.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

def generate_table(matches, target_team_name, is_h2h=False):
    md = ''
    md += '| Partido | Córners (L-V) | Tarjetas (L-V) | Remates Arco (L-V) | Faltas (L-V) |\n'
    md += '| :--- | :---: | :---: | :---: | :---: |\n'
    for m in matches:
        if not m['stats']: continue
        match_str = m['match']
        
        c_home = get_stat(m['stats'], 'Corner kicks', home=True)
        c_away = get_stat(m['stats'], 'Corner kicks', home=False)
        y_home = get_stat(m['stats'], 'Yellow cards', home=True)
        y_away = get_stat(m['stats'], 'Yellow cards', home=False)
        s_home = get_stat(m['stats'], 'Shots on target', home=True)
        s_away = get_stat(m['stats'], 'Shots on target', home=False)
        f_home = get_stat(m['stats'], 'Fouls', home=True)
        f_away = get_stat(m['stats'], 'Fouls', home=False)
        
        md += f'| **{match_str}** | {c_home} - {c_away} | {y_home} - {y_away} | {s_home} - {s_away} | {f_home} - {f_away} |\n'
    return md

with open('scratch/tables.md', 'w', encoding='utf-8') as f:
    f.write('### 🔵 Manchester City (Últimos 10 Partidos - Desglose)\n')
    f.write(generate_table(data['MCI'], 'Man') + '\n')

    f.write('### ⚪ Everton (Últimos 10 Partidos - Desglose)\n')
    f.write(generate_table(data['EVE'], 'Everton') + '\n')

    f.write('### ⚔️ Historial Directo H2H (Últimos Partidos Disp.)\n')
    f.write(generate_table(data['H2H'], 'Man', is_h2h=True) + '\n')
