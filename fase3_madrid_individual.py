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
            
        score_match = re.search(r'(.+?)\s+(\d+)-(\d+)\s+(.+)', result)
        if not score_match: continue
        hg, ag = int(score_match.group(2)), int(score_match.group(3))
        home_team = score_match.group(1).strip()
        
        stats = {}
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
                    if "Madrid" in section_header:
                        stats[n_key] = l if madrid_home else r
                    elif "Oviedo" in section_header:
                        stats[h_key] = l if oviedo_home else r
        matches.append(stats)
    return matches

madrid_last_10 = parse_matches(text, "Ultimos 10 - Real Madrid")
oviedo_last_10 = parse_matches(text, "Ultimos 10 - Real Oviedo")

def evaluate_market(stat_key, line, is_over, matches_own):
    def check_val(m):
        if stat_key not in m: return None
        v = m[stat_key]
        return 1 if (v > line if is_over else v <= line) else 0

    own_res = [check_val(m) for m in matches_own]
    own_res = [r for r in own_res if r is not None]
    
    own_wins = sum(own_res)
    own_total = len(own_res)
    
    if own_total == 0: return None
    
    return {'own_wins': own_wins, 'own_total': own_total, 'own_pr': own_wins/own_total}

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

for mg in all_groups:
    group_name = mg.get('name', 'Unknown')
    for mid in mg.get('marketIds', []):
        m = all_markets_dict.get(mid)
        if not m: continue
        
        mname = m.get('name', '').lower()
        if 'combinación' in mname or 'y ' in mname or 'doble oportunidad' in mname:
            continue
            
        sv = m.get('sv', '')
        odds = resolve_odds(m.get('desktopOddIds', []))
        
        is_madrid = 'madrid' in mname
        is_oviedo = 'oviedo' in mname
        
        # Solo queremos mercados individuales de equipo
        if not is_madrid and not is_oviedo: continue
        
        stat_key = None
        if 'esquina' in mname or 'corners' in mname:
            stat_key = 'madrid_corners' if is_madrid else 'oviedo_corners'
        elif 'tarjetas' in mname or 'cards' in mname:
            stat_key = 'madrid_yellows' if is_madrid else 'oviedo_yellows'
        elif 'puerta' in mname or 'target' in mname:
            stat_key = 'madrid_sot' if is_madrid else 'oviedo_sot'
        elif 'remates' in mname or 'tiros' in mname:
            if 'esquina' not in mname:
                stat_key = 'madrid_shots' if is_madrid else 'oviedo_shots'
        elif 'faltas' in mname:
            stat_key = 'madrid_fouls' if is_madrid else 'oviedo_fouls'
        elif 'fueras' in mname:
            stat_key = 'madrid_offsides' if is_madrid else 'oviedo_offsides'
        elif 'paradas' in mname:
            stat_key = 'madrid_saves' if is_madrid else 'oviedo_saves'
        elif 'goles' in mname or 'goals' in mname:
            stat_key = 'madrid_goals' if is_madrid else 'oviedo_goals'
                
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
            
            matches_own = madrid_last_10 if is_madrid else oviedo_last_10
            
            res = evaluate_market(stat_key, line, is_over, matches_own)
            if not res: continue
            
            uid = f"{m['name']}_{o['name']}_{line}_{o['price']}"
            if uid in seen: continue
            seen.add(uid)
            
            candidates.append({
                'group': group_name, 'market': m['name'], 'sel': o['name'], 'line': line,
                'price': o['price'], 'is_over': is_over, 'stat': stat_key,
                'res': res
            })

candidates.sort(key=lambda x: (x['res']['own_pr'], x['price']), reverse=True)

with open('madrid_individual_output.txt', 'w', encoding='utf-8') as out_f:
    out_f.write("🎯 MERCADOS INDIVIDUALES DESTACADOS (Ignorando H2H, Propios >= 80%)\n\n")
    for c in candidates:
        r = c['res']
        if r['own_pr'] >= 0.80 and c['price'] >= 1.40:
            out_f.write(f"[{c['group']}] {c['market']} | {c['sel']} @ {c['price']}\n")
            out_f.write(f"   -> Rendimiento Propio (Últ. 10): {r['own_wins']}/{r['own_total']} ({r['own_pr']*100:.1f}%)\n\n")
