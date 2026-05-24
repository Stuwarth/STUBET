#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, re

with open('pdf_madrid_oviedo.txt', 'r', encoding='utf-8') as f:
    text = f.read()

def get_val(text, label, side='right'):
    pattern = rf'(\d+\.?\d*)\s*\|\s*{re.escape(label)}\s*\|\s*(\d+\.?\d*)'
    m = re.search(pattern, text)
    if m: return float(m.group(1)) if side == 'left' else float(m.group(2))
    return None

def parse_matches(text, section_header):
    start = text.find(section_header)
    if start == -1: return []
    sections = ["Ultimos 10 - Real Madrid", "Ultimos 10 - Real Oviedo", "Historial H2H"]
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
            
        score_match = re.search(r'(.+?)\s+(\d+)-(\d+)\s+(.+)', result)
        if not score_match: continue
        
        hg, ag = int(score_match.group(2)), int(score_match.group(3))
        home_team = score_match.group(1).strip()
        
        stats = {
            'date': date, 'result': result,
            'total_goals': hg + ag,
            'btts': 1 if hg > 0 and ag > 0 else 0
        }
        
        madrid_home = "Madrid" in home_team
        oviedo_home = "Oviedo" in home_team
        
        stats['madrid_goals'] = hg if madrid_home else ag
        stats['oviedo_goals'] = hg if oviedo_home else ag
        
        if all_section:
            metrics = [
                ('Total shots', 'total_shots', 'madrid_shots', 'oviedo_shots'),
                ('Corner kicks', 'total_corners', 'madrid_corners', 'oviedo_corners'),
                ('Yellow cards', 'total_yellows', 'madrid_yellows', 'oviedo_yellows'),
                ('Fouls', 'total_fouls', 'madrid_fouls', 'oviedo_fouls'),
                ('Offsides', 'total_offsides', 'madrid_offsides', 'oviedo_offsides'),
                ('Shots on target', 'total_sot', 'madrid_sot', 'oviedo_sot'),
                ('Goalkeeper saves', 'total_saves', 'madrid_saves', 'oviedo_saves')
            ]
            
            for label, t_key, n_key, h_key in metrics:
                l, r = get_val(all_section, label, 'left'), get_val(all_section, label, 'right')
                if l is not None and r is not None:
                    stats[t_key] = l + r
                    if "Madrid" in section_header:
                        stats[n_key] = l if madrid_home else r
                    elif "Oviedo" in section_header:
                        stats[h_key] = l if oviedo_home else r
                    elif "H2H" in section_header:
                        stats[n_key] = l if madrid_home else r
                        stats[h_key] = r if madrid_home else l
                        
        if first_section:
            lc, rc = get_val(first_section, 'Corner kicks', 'left'), get_val(first_section, 'Corner kicks', 'right')
            if lc is not None and rc is not None:
                stats['first_half_corners'] = lc + rc
            
            ly, ry = get_val(first_section, 'Yellow cards', 'left'), get_val(first_section, 'Yellow cards', 'right')
            if ly is not None and ry is not None:
                stats['first_half_yellows'] = ly + ry

        matches.append(stats)
    return matches

madrid_last_10 = parse_matches(text, "Ultimos 10 - Real Madrid")
oviedo_last_10 = parse_matches(text, "Ultimos 10 - Real Oviedo")
h2h_10 = parse_matches(text, "Historial H2H")

def evaluate_market(stat_key, line, is_over, matches_own, matches_h2h):
    def check_val(m):
        if stat_key not in m: return None
        v = m[stat_key]
        return 1 if (v > line if is_over else v <= line) else 0

    own_res = [check_val(m) for m in matches_own]
    own_res = [r for r in own_res if r is not None]
    
    h2h_res = [check_val(m) for m in matches_h2h]
    h2h_res = [r for r in h2h_res if r is not None]
    
    own_wins = sum(own_res)
    own_total = len(own_res)
    h2h_wins = sum(h2h_res)
    h2h_total = len(h2h_res)
    
    if own_total == 0 or h2h_total == 0: return None
    
    return {
        'own_wins': own_wins, 'own_total': own_total, 'own_pr': own_wins/own_total,
        'h2h_wins': h2h_wins, 'h2h_total': h2h_total, 'h2h_pr': h2h_wins/h2h_total,
        'total_wins': own_wins + h2h_wins, 'total_games': own_total + h2h_total,
        'total_pr': (own_wins + h2h_wins) / (own_total + h2h_total)
    }

with open('backend/raw_markets.json', 'r', encoding='utf-8') as f: jdata = json.load(f)

odds_dict = {o['id']: {'name': o.get('name',''), 'price': o.get('price',0)} for o in jdata.get('odds',[]) if not isinstance(o['id'], list)}
markets_dict = {m['id']: m for m in jdata.get('markets',[])}
child_dict = {c['id']: c for c in jdata.get('childMarkets',[])}
all_markets_dict = {**markets_dict, **child_dict}

def resolve_odds(odd_ids):
    results = []
    for oid in odd_ids:
        if isinstance(oid, list):
            for sub in oid:
                if sub in odds_dict: results.append(odds_dict[sub])
        else:
            if oid in odds_dict: results.append(odds_dict[oid])
    return results

candidates = []
all_groups = jdata.get('marketGroups', []) + jdata.get('childMarketGroups', [])
seen = set()

# NO EVALUAREMOS COMBINADAS SIMPLES COMO ANTES. SOLO MERCADOS DE UNA PATA.
for mg in all_groups:
    group_name = mg.get('name', 'Unknown')
    for mid in mg.get('marketIds', []):
        m = all_markets_dict.get(mid)
        if not m: continue
        
        mname = m.get('name', '').lower()
        if 'combinación' in mname or 'y ' in mname or 'doble oportunidad' in mname:
            continue # Omitimos combinadas automáticas para evitar el bug del Clásico
            
        sv = m.get('sv', '')
        odds = resolve_odds(m.get('desktopOddIds', []))
        
        is_madrid = 'madrid' in mname
        is_oviedo = 'oviedo' in mname
        is_first_half = '1ª' in mname or '1er' in mname or 'primera' in mname
        
        stat_key = None
        
        if 'esquina' in mname or 'corners' in mname:
            if is_first_half: stat_key = 'first_half_corners'
            else: stat_key = 'madrid_corners' if is_madrid else 'oviedo_corners' if is_oviedo else 'total_corners'
        elif 'tarjetas' in mname or 'cards' in mname:
            if is_first_half: stat_key = 'first_half_yellows'
            else: stat_key = 'madrid_yellows' if is_madrid else 'oviedo_yellows' if is_oviedo else 'total_yellows'
        elif 'puerta' in mname or 'target' in mname:
            stat_key = 'madrid_sot' if is_madrid else 'oviedo_sot' if is_oviedo else 'total_sot'
        elif 'remates' in mname or 'tiros' in mname:
            if 'esquina' not in mname:
                stat_key = 'madrid_shots' if is_madrid else 'oviedo_shots' if is_oviedo else 'total_shots'
        elif 'faltas' in mname:
            stat_key = 'madrid_fouls' if is_madrid else 'oviedo_fouls' if is_oviedo else 'total_fouls'
        elif 'fueras' in mname:
            stat_key = 'madrid_offsides' if is_madrid else 'oviedo_offsides' if is_oviedo else 'total_offsides'
        elif 'paradas' in mname:
            stat_key = 'madrid_saves' if is_madrid else 'oviedo_saves' if is_oviedo else 'total_saves'
        elif 'goles' in mname or 'goals' in mname:
            if not is_first_half and 'mitad' not in mname:
                stat_key = 'madrid_goals' if is_madrid else 'oviedo_goals' if is_oviedo else 'total_goals'
                
        if not stat_key: continue
        
        for o in odds:
            if o['price'] <= 1.0: continue
            oname = o['name'].lower()
            
            line = None
            if sv:
                try: line = float(str(sv).replace(',','.'))
                except: pass
            if line is None:
                nums = re.findall(r'\d+\.\d+', oname)
                if nums: line = float(nums[0])
            
            if line is None: continue
            
            is_over = 'más' in oname or 'over' in oname
            if not is_over and 'menos' not in oname and 'under' not in oname: continue
            
            if 'madrid' in stat_key:
                matches_own = madrid_last_10
            elif 'oviedo' in stat_key:
                matches_own = oviedo_last_10
            else:
                matches_own = madrid_last_10 + oviedo_last_10
            
            res = evaluate_market(stat_key, line, is_over, matches_own, h2h_10)
            if not res: continue
            
            uid = f"{m['name']}_{o['name']}_{line}_{o['price']}"
            if uid in seen: continue
            seen.add(uid)
            
            pi = (1 / o['price'])
            value = (res['total_pr'] / pi) - 1
            
            candidates.append({
                'group': group_name, 'market': m['name'], 'sel': o['name'], 'line': line,
                'price': o['price'], 'is_over': is_over, 'stat': stat_key,
                'res': res, 'value': value
            })

for mg in all_groups:
    for mid in mg.get('marketIds', []):
        m = all_markets_dict.get(mid)
        if not m: continue
        mname = m.get('name', '').lower()
        if 'ambos' in mname and 'marcan' in mname and 'mitad' not in mname:
            odds = resolve_odds(m.get('desktopOddIds', []))
            for o in odds:
                if o['price'] <= 1.0: continue
                if 'sí' in o['name'].lower() or 'si' in o['name'].lower():
                    uid = f"{m['name']}_{o['name']}_BTTS_{o['price']}"
                    if uid in seen: continue
                    seen.add(uid)
                    own = [1 if x['btts']==1 else 0 for x in madrid_last_10 + oviedo_last_10]
                    h2h = [1 if x['btts']==1 else 0 for x in h2h_10]
                    r = {
                        'own_wins': sum(own), 'own_total': len(own), 'own_pr': sum(own)/len(own),
                        'h2h_wins': sum(h2h), 'h2h_total': len(h2h), 'h2h_pr': sum(h2h)/len(h2h),
                        'total_wins': sum(own)+sum(h2h), 'total_games': len(own)+len(h2h),
                        'total_pr': (sum(own)+sum(h2h))/(len(own)+len(h2h))
                    }
                    candidates.append({
                        'group': mg.get('name', 'Unknown'), 'market': m['name'], 'sel': o['name'], 'line': 'BTTS',
                        'price': o['price'], 'is_over': True, 'stat': 'btts',
                        'res': r, 'value': (r['total_pr'] / (1/o['price'])) - 1
                    })

candidates.sort(key=lambda x: x['res']['total_pr'], reverse=True)

gold_bricks = []
for c in candidates:
    r = c['res']
    if r['own_pr'] >= 0.80 and r['h2h_pr'] >= 0.70 and c['price'] >= 1.30:
        gold_bricks.append(c)

value_bets = []
for c in candidates:
    r = c['res']
    if c['price'] >= 1.60 and r['h2h_pr'] >= 0.60 and r['own_pr'] >= 0.60 and c['value'] > 0:
        value_bets.append(c)

value_bets.sort(key=lambda x: x['value'], reverse=True)

with open('madrid_output.txt', 'w', encoding='utf-8') as out_f:
    out_f.write("🏆 LADRILLOS DE ORO FILTRADOS (H2H >= 70%, Propios >= 80%, Cuota >= 1.30)\n")
    for b in gold_bricks[:15]:
        r = b['res']
        out_f.write(f"[{b['group']}] {b['market']} | {b['sel']} @ {b['price']}\n")
        out_f.write(f"   -> Propios: {r['own_wins']}/{r['own_total']} ({r['own_pr']*100:.1f}%) | H2H: {r['h2h_wins']}/{r['h2h_total']} ({r['h2h_pr']*100:.1f}%) | Total: {r['total_wins']}/{r['total_games']} ({r['total_pr']*100:.1f}%)\n\n")

    out_f.write("\n🚀 VALUE BETS (H2H >= 60%, Propios >= 60%, Cuota >= 1.60)\n")
    for v in value_bets[:15]:
        r = v['res']
        out_f.write(f"[{v['group']}] {v['market']} | {v['sel']} @ {v['price']} (Value: {v['value']*100:.1f}%)\n")
        out_f.write(f"   -> Propios: {r['own_wins']}/{r['own_total']} ({r['own_pr']*100:.1f}%) | H2H: {r['h2h_wins']}/{r['h2h_total']} ({r['h2h_pr']*100:.1f}%) | Total: {r['total_wins']}/{r['total_games']} ({r['total_pr']*100:.1f}%)\n\n")

