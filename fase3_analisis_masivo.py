#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 3+4: Análisis Estadístico Masivo (Todos los grupos)
Busca bloques de construcción de alta probabilidad (Stake 10)
"""
import json, re

# ============ PARSE PDF DATA ============
with open('pdf_full_text.txt', 'r', encoding='utf-8') as f:
    text = f.read()

def parse_matches(text, section_header):
    start = text.find(section_header)
    if start == -1: return []
    sections = ["Ultimos 10 - Al-Nassr", "Ultimos 10 - Al-Hilal", "Historial H2H"]
    end = len(text)
    for s in sections:
        idx = text.find(s, start + len(section_header))
        if idx != -1 and idx < end: end = idx
    
    section = text[start:end]
    match_pattern = r'(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)(?:\n|$)'
    matches_raw = re.finditer(match_pattern, section)
    
    matches, positions = [], []
    for m in matches_raw: positions.append((m.start(), m.group(1), m.group(2).strip(), m.group(3).strip()))
    
    for i, (pos, date, comp, result) in enumerate(positions):
        end_pos = positions[i+1][0] if i+1 < len(positions) else len(section)
        match_text = section[pos:end_pos]
        
        all_section = ""
        all_start = match_text.find("--- ALL ---")
        if all_start != -1:
            first_half = match_text.find("--- 1ST ---")
            all_section = match_text[all_start:first_half] if first_half != -1 else match_text[all_start:]
        
        first_section = ""
        fst = match_text.find("--- 1ST ---")
        if fst != -1:
            snd = match_text.find("--- 2ND ---")
            first_section = match_text[fst:snd] if snd != -1 else match_text[fst:]
            
        stats = extract_stats(all_section, first_section, result, section_header)
        stats['date'] = date; stats['result'] = result
        matches.append(stats)
    return matches

def get_val(text, label, side='right'):
    pattern = rf'(\d+\.?\d*)\s*\|\s*{re.escape(label)}\s*\|\s*(\d+\.?\d*)'
    m = re.search(pattern, text)
    if m: return float(m.group(1)) if side == 'left' else float(m.group(2))
    return None

def extract_stats(all_text, first_text, result, section_header):
    stats = {}
    score_match = re.search(r'(.+?)\s+(\d+)-(\d+)\s+(.+)', result)
    if not score_match: return stats
    
    hg, ag = int(score_match.group(2)), int(score_match.group(3))
    stats['total_goals'] = hg + ag
    stats['btts'] = 1 if hg > 0 and ag > 0 else 0
    
    # Team specific goals
    home_team = score_match.group(1).strip()
    if "Al-Nassr" in section_header:
        stats['team_goals'] = hg if "Nassr" in home_team else ag
        stats['team_name'] = "Al-Nassr"
        side = 'left' if "Nassr" in home_team else 'right'
    elif "Al-Hilal" in section_header:
        stats['team_goals'] = hg if "Hilal" in home_team else ag
        stats['team_name'] = "Al-Hilal"
        side = 'left' if "Hilal" in home_team else 'right'
    else: # H2H
        nassr_home = "Nassr" in home_team
        stats['nassr_goals'] = hg if nassr_home else ag
        stats['hilal_goals'] = ag if nassr_home else hg
        side = 'both'
        
    if all_text:
        ls, rs = get_val(all_text, 'Total shots', 'left'), get_val(all_text, 'Total shots', 'right')
        if ls is not None and rs is not None:
            stats['total_shots'] = ls + rs
            if side == 'left': stats['team_shots'] = ls
            elif side == 'right': stats['team_shots'] = rs
            elif side == 'both':
                stats['nassr_shots'] = ls if "Nassr" in home_team else rs
                stats['hilal_shots'] = rs if "Nassr" in home_team else ls

        lc, rc = get_val(all_text, 'Corner kicks', 'left'), get_val(all_text, 'Corner kicks', 'right')
        if lc is not None and rc is not None: 
            stats['total_corners'] = lc + rc
            if side == 'left': stats['team_corners'] = lc
            elif side == 'right': stats['team_corners'] = rc
            elif side == 'both':
                stats['nassr_corners'] = lc if "Nassr" in home_team else rc
                stats['hilal_corners'] = rc if "Nassr" in home_team else lc

        ly, ry = get_val(all_text, 'Yellow cards', 'left'), get_val(all_text, 'Yellow cards', 'right')
        if ly is not None and ry is not None: 
            stats['total_yellows'] = ly + ry
            if side == 'left': stats['team_yellows'] = ly
            elif side == 'right': stats['team_yellows'] = ry
            elif side == 'both':
                stats['nassr_yellows'] = ly if "Nassr" in home_team else ry
                stats['hilal_yellows'] = ry if "Nassr" in home_team else ly

        lf, rf = get_val(all_text, 'Fouls', 'left'), get_val(all_text, 'Fouls', 'right')
        if lf is not None and rf is not None: stats['total_fouls'] = lf + rf
        
        lo, ro = get_val(all_text, 'Offsides', 'left'), get_val(all_text, 'Offsides', 'right')
        if lo is not None and ro is not None: stats['total_offsides'] = lo + ro
        
        lst, rst = get_val(all_text, 'Shots on target', 'left'), get_val(all_text, 'Shots on target', 'right')
        if lst is not None and rst is not None: 
            stats['total_sot'] = lst + rst
            if side == 'left': stats['team_sot'] = lst
            elif side == 'right': stats['team_sot'] = rst
            elif side == 'both':
                stats['nassr_sot'] = lst if "Nassr" in home_team else rst
                stats['hilal_sot'] = rst if "Nassr" in home_team else lst
                
        lsaves, rsaves = get_val(all_text, 'Goalkeeper saves', 'left'), get_val(all_text, 'Goalkeeper saves', 'right')
        if lsaves is not None and rsaves is not None: stats['total_saves'] = lsaves + rsaves

    return stats

nm = parse_matches(text, "Ultimos 10 - Al-Nassr")
hm = parse_matches(text, "Ultimos 10 - Al-Hilal")
h2h = parse_matches(text, "Historial H2H")
all_m = nm + hm + h2h

def calc_cm(matches):
    keys = ['total_goals', 'btts', 'total_corners', 'total_yellows', 'total_fouls', 
            'total_offsides', 'total_shots', 'total_sot', 'total_saves']
    res = {}
    for k in keys:
        v = [m[k] for m in matches if k in m and m[k] is not None]
        if v: res[k] = {'values': v, 'avg': sum(v)/len(v)}
    
    # Team specific combined (10 own + 10 H2H)
    nassr_all = []
    for m in nm:
        if 'team_corners' in m: nassr_all.append({'corners': m['team_corners'], 'yellows': m.get('team_yellows',0), 'sot': m.get('team_sot',0)})
    for m in h2h:
        if 'nassr_corners' in m: nassr_all.append({'corners': m['nassr_corners'], 'yellows': m.get('nassr_yellows',0), 'sot': m.get('nassr_sot',0)})
        
    res['nassr_corners'] = {'values': [x['corners'] for x in nassr_all]}
    res['nassr_yellows'] = {'values': [x['yellows'] for x in nassr_all]}
    res['nassr_sot'] = {'values': [x['sot'] for x in nassr_all]}
    
    hilal_all = []
    for m in hm:
        if 'team_corners' in m: hilal_all.append({'corners': m['team_corners'], 'yellows': m.get('team_yellows',0), 'sot': m.get('team_sot',0)})
    for m in h2h:
        if 'hilal_corners' in m: hilal_all.append({'corners': m['hilal_corners'], 'yellows': m.get('hilal_yellows',0), 'sot': m.get('hilal_sot',0)})
        
    res['hilal_corners'] = {'values': [x['corners'] for x in hilal_all]}
    res['hilal_yellows'] = {'values': [x['yellows'] for x in hilal_all]}
    res['hilal_sot'] = {'values': [x['sot'] for x in hilal_all]}
        
    return res

cm = calc_cm(all_m)

# ============ JSON MAPPING ============
with open('backend/raw_markets.json', 'r', encoding='utf-8') as f: jdata = json.load(f)

odds_dict = {o['id']: {'name': o.get('name',''), 'price': o.get('price',0)} for o in jdata.get('odds',[]) if not isinstance(o['id'], list)}
markets_dict = {m['id']: m for m in jdata.get('markets',[])}
child_dict = {c['id']: c for c in jdata.get('childMarkets',[])}

# Combinar diccionarios de mercados
all_markets_dict = {**markets_dict, **child_dict}

def resolve_odds(odd_ids):
    results = []
    for oid in odd_ids:
        if isinstance(oid, list):
            for sub in oid:
                o = odds_dict.get(sub, {})
                if o: results.append(o)
        else:
            o = odds_dict.get(oid, {})
            if o: results.append(o)
    return results

# Map of ALL possible metrics to check
metric_map = {
    'total_goals': [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
    'total_corners': [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5],
    'total_yellows': [2.5, 3.5, 4.5, 5.5, 6.5, 7.5],
    'total_fouls': [18.5, 19.5, 20.5, 21.5, 22.5, 23.5, 24.5, 25.5, 26.5],
    'total_offsides': [2.5, 3.5, 4.5, 5.5, 6.5],
    'total_shots': [19.5, 20.5, 21.5, 22.5, 23.5, 24.5, 25.5, 26.5, 27.5],
    'total_sot': [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5],
    'total_saves': [3.5, 4.5, 5.5, 6.5, 7.5],
    'nassr_corners': [2.5, 3.5, 4.5, 5.5, 6.5],
    'hilal_corners': [2.5, 3.5, 4.5, 5.5, 6.5],
    'nassr_yellows': [1.5, 2.5, 3.5, 4.5],
    'hilal_yellows': [1.5, 2.5, 3.5, 4.5],
    'nassr_sot': [2.5, 3.5, 4.5, 5.5],
    'hilal_sot': [2.5, 3.5, 4.5, 5.5],
}

keyword_map = {
    'goles': 'total_goals', 'goals': 'total_goals',
    'esquina': 'total_corners', 'corners': 'total_corners',
    'tarjetas': 'total_yellows', 'cards': 'total_yellows',
    'faltas': 'total_fouls', 'fouls': 'total_fouls',
    'fueras': 'total_offsides', 'offsides': 'total_offsides',
    'remates': 'total_shots', 'tiros': 'total_shots', 'shots': 'total_shots',
    'remates a puerta': 'total_sot', 'tiros a puerta': 'total_sot', 'shots on target': 'total_sot',
    'paradas': 'total_saves', 'atajadas': 'total_saves', 'saves': 'total_saves'
}

candidates = []

# Explorar ABSOLUTAMENTE TODOS LOS GRUPOS (marketGroups y childMarketGroups)
all_groups = jdata.get('marketGroups', []) + jdata.get('childMarketGroups', [])

for mg in all_groups:
    group_name = mg.get('name', 'Unknown')
    for mid in mg.get('marketIds', []):
        m = all_markets_dict.get(mid)
        if not m: continue
        
        mname = m.get('name', '')
        sv = m.get('sv', '')
        odds = resolve_odds(m.get('desktopOddIds', []))
        
        # Determine which stat this might be
        stat_key = None
        mname_lower = mname.lower()
        
        # Check team specific
        is_nassr = 'nassr' in mname_lower
        is_hilal = 'hilal' in mname_lower
        
        if 'esquina' in mname_lower or 'corners' in mname_lower:
            stat_key = 'nassr_corners' if is_nassr else 'hilal_corners' if is_hilal else 'total_corners'
        elif 'tarjetas' in mname_lower or 'cards' in mname_lower:
            stat_key = 'nassr_yellows' if is_nassr else 'hilal_yellows' if is_hilal else 'total_yellows'
        elif 'puerta' in mname_lower or 'target' in mname_lower:
            stat_key = 'nassr_sot' if is_nassr else 'hilal_sot' if is_hilal else 'total_sot'
        else:
            for kw, key in keyword_map.items():
                if kw in mname_lower:
                    stat_key = key
                    break
                    
        # Check BTTS
        if 'ambos' in mname_lower and 'marcan' in mname_lower and 'mitad' not in mname_lower:
            for o in odds:
                if o['price'] <= 1.0: continue
                if 'sí' in o['name'].lower() or 'si' in o['name'].lower():
                    vals = cm.get('btts', {}).get('values', [])
                    if vals:
                        pr = sum(1 for v in vals if v == 1) / len(vals) * 100
                        candidates.append({
                            'group': group_name, 'market': mname, 'sel': o['name'], 'line': 'BTTS',
                            'price': o['price'], 'pr': pr, 'stat': 'btts'
                        })
        
        if stat_key and stat_key in cm:
            lines_to_check = metric_map.get(stat_key, [])
            for o in odds:
                if o['price'] <= 1.0: continue
                oname = o['name'].lower()
                
                # Intentar deducir la línea del sv o del nombre de la selección
                matched_line = None
                
                # Check SV first
                if sv:
                    try:
                        sv_float = float(str(sv).replace(',','.'))
                        matched_line = sv_float
                    except: pass
                
                # If no SV, extract from selection name (e.g. "Más de 2.5")
                if matched_line is None:
                    nums = re.findall(r'\d+\.\d+', oname)
                    if nums: matched_line = float(nums[0])
                
                if matched_line is None or matched_line not in lines_to_check:
                    # Let's check all possible lines for this metric if we couldn't parse
                    lines = [matched_line] if matched_line is not None else lines_to_check
                else:
                    lines = [matched_line]
                    
                for line in lines:
                    if line is None: continue
                    vals = cm[stat_key]['values']
                    if not vals: continue
                    
                    if 'más' in oname or 'over' in oname:
                        pr = sum(1 for v in vals if v > line) / len(vals) * 100
                        candidates.append({
                            'group': group_name, 'market': mname, 'sel': o['name'], 'line': line,
                            'price': o['price'], 'pr': pr, 'stat': stat_key, 'type': 'OVER'
                        })
                    elif 'menos' in oname or 'under' in oname:
                        pr = sum(1 for v in vals if v <= line) / len(vals) * 100
                        candidates.append({
                            'group': group_name, 'market': mname, 'sel': o['name'], 'line': line,
                            'price': o['price'], 'pr': pr, 'stat': stat_key, 'type': 'UNDER'
                        })

# Filtro: Buscar "Ladrillos de Oro" (PR > 85%, cuota entre 1.10 y 1.70)
gold_bricks = []
# Buscar Value Bets puros
value_bets = []

seen = set() # Evitar duplicados exactos (a veces aparecen en Principal y Crear Apuesta)

for c in candidates:
    # Generar hash único
    uid = f"{c['market']}_{c['sel']}_{c['line']}_{c['price']}"
    if uid in seen: continue
    seen.add(uid)
    
    pi = (1 / c['price']) * 100
    val = (c['pr'] / pi) - 1
    c['value'] = val
    c['pi'] = pi
    
    # Ladrillos de oro para armar combinada (Stake 10)
    if c['pr'] >= 85 and 1.10 <= c['price'] <= 1.70:
        gold_bricks.append(c)
        
    # Value bets agresivos
    if val > 0.15 and c['pr'] >= 60:
        value_bets.append(c)

gold_bricks.sort(key=lambda x: x['pr'], reverse=True)
value_bets.sort(key=lambda x: x['value'], reverse=True)

print(f"Total candidatos procesados: {len(seen)}")

print("\n" + "="*80)
print("🏆 LADRILLOS DE ORO (Alta Probabilidad PR > 85% para combinar)")
print("="*80)
for b in gold_bricks[:30]:
    print(f"  [{b['group']}] {b['market']} | {b['sel']} (Línea: {b['line']})")
    print(f"  Cuota: {b['price']} | PR: {b['pr']:.1f}% | PI: {b['pi']:.1f}% | Value: {b['value']*100:.1f}%\n")

print("\n" + "="*80)
print("🚀 VALUE BETS AGRESIVOS (Value > 15%, PR > 60%)")
print("="*80)
for v in value_bets[:30]:
    print(f"  [{v['group']}] {v['market']} | {v['sel']} (Línea: {v['line']})")
    print(f"  Cuota: {v['price']} | PR: {v['pr']:.1f}% | PI: {v['pi']:.1f}% | Value: {v['value']*100:.1f}%\n")

