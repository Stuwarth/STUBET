#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 3+4: Análisis estadístico + Cruce de Value
Lee pdf_full_text.txt, extrae métricas, cruza con raw_markets.json
"""
import json, re

# ============ PARSE PDF DATA ============
with open('pdf_full_text.txt', 'r', encoding='utf-8') as f:
    text = f.read()

def parse_matches(text, section_header):
    """Parse matches from a section of the PDF text"""
    start = text.find(section_header)
    if start == -1:
        return []
    
    # Find next section or end
    sections = ["Ultimos 10 - Al-Nassr", "Ultimos 10 - Al-Hilal", "Historial H2H"]
    end = len(text)
    for s in sections:
        idx = text.find(s, start + len(section_header))
        if idx != -1 and idx < end:
            end = idx
    
    section = text[start:end]
    
    # Split by match headers (date | competition | result)
    match_pattern = r'(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)(?:\n|$)'
    matches_raw = re.finditer(match_pattern, section)
    
    matches = []
    positions = []
    for m in matches_raw:
        positions.append((m.start(), m.group(1), m.group(2).strip(), m.group(3).strip()))
    
    for i, (pos, date, comp, result) in enumerate(positions):
        end_pos = positions[i+1][0] if i+1 < len(positions) else len(section)
        match_text = section[pos:end_pos]
        
        # Only extract ALL section stats (not 1ST/2ND halves for main metrics)
        all_section = ""
        all_start = match_text.find("--- ALL ---")
        if all_start != -1:
            first_half = match_text.find("--- 1ST ---")
            if first_half != -1:
                all_section = match_text[all_start:first_half]
            else:
                all_section = match_text[all_start:]
        
        # Also get 1ST half stats
        first_section = ""
        fst = match_text.find("--- 1ST ---")
        if fst != -1:
            snd = match_text.find("--- 2ND ---")
            if snd != -1:
                first_section = match_text[fst:snd]
            else:
                first_section = match_text[fst:]
        
        # Determine home/away and which team is which
        # Result format: "TeamA X-Y TeamB" where TeamA is home
        result_parts = result.strip()
        
        # Determine if our team is home or away based on section
        is_nassr_section = "Al-Nassr" in section_header or "H2H" in section_header
        
        stats = extract_stats(all_section, first_section, result_parts, section_header)
        stats['date'] = date
        stats['competition'] = comp
        stats['result'] = result_parts
        matches.append(stats)
    
    return matches

def get_val(text, label, side='right'):
    """Extract a value from 'left | label | right' format"""
    pattern = rf'(\d+\.?\d*)\s*\|\s*{re.escape(label)}\s*\|\s*(\d+\.?\d*)'
    m = re.search(pattern, text)
    if m:
        if side == 'left':
            return float(m.group(1))
        return float(m.group(2))
    return None

def extract_stats(all_text, first_text, result, section_header):
    """Extract key stats. For Al-Nassr stats, data is on RIGHT side when Al-Nassr is away (left|stat|right)
    Need to determine position based on result string"""
    
    stats = {}
    
    # Parse result to determine sides
    # Format: "Home X-Y Away" - need to figure out if target team is home (left) or away (right)
    score_match = re.search(r'(.+?)\s+(\d+)-(\d+)\s+(.+)', result)
    if not score_match:
        return stats
    
    home_team = score_match.group(1).strip()
    home_goals = int(score_match.group(2))
    away_goals = int(score_match.group(3))
    away_team = score_match.group(4).strip()
    
    # In PDF format: left side = home team, right side = away team
    # We need Al-Nassr's stats for Nassr section, Al-Hilal's for Hilal section
    
    if "Al-Nassr" in section_header:
        if "Al-Nassr" in home_team or "Al Nassr" in home_team:
            side = 'left'
            team_goals = home_goals
            opp_goals = away_goals
        else:
            side = 'right'
            team_goals = away_goals
            opp_goals = home_goals
    elif "Al-Hilal" in section_header:
        if "Al-Hilal" in home_team or "Al Hilal" in home_team:
            side = 'left'
            team_goals = home_goals
            opp_goals = away_goals
        else:
            side = 'right'
            team_goals = away_goals
            opp_goals = home_goals
    else:  # H2H - get both
        # For H2H we track Al-Hilal as left team identifier
        hilal_home = "Al-Hilal" in home_team or "Al Hilal" in home_team
        side = 'both'
        team_goals = home_goals  # Hilal goals when home
        opp_goals = away_goals
    
    total_goals = home_goals + away_goals
    stats['total_goals'] = total_goals
    stats['home_goals'] = home_goals
    stats['away_goals'] = away_goals
    stats['home_team'] = home_team
    stats['away_team'] = away_team
    stats['btts'] = 1 if home_goals > 0 and away_goals > 0 else 0
    
    # Extract from ALL section
    if all_text:
        # Total shots (both teams combined from match overview)
        left_shots = get_val(all_text, 'Total shots', 'left')
        right_shots = get_val(all_text, 'Total shots', 'right')
        if left_shots is not None and right_shots is not None:
            stats['total_shots_match'] = left_shots + right_shots
        
        # Corner kicks
        left_corners = get_val(all_text, 'Corner kicks', 'left')
        right_corners = get_val(all_text, 'Corner kicks', 'right')
        if left_corners is not None and right_corners is not None:
            stats['total_corners'] = left_corners + right_corners
            stats['home_corners'] = left_corners
            stats['away_corners'] = right_corners
        
        # Yellow cards
        left_yc = get_val(all_text, 'Yellow cards', 'left')
        right_yc = get_val(all_text, 'Yellow cards', 'right')
        if left_yc is not None and right_yc is not None:
            stats['total_yellows'] = left_yc + right_yc
            stats['home_yellows'] = left_yc
            stats['away_yellows'] = right_yc
        
        # Fouls
        left_fouls = get_val(all_text, 'Fouls', 'left')
        right_fouls = get_val(all_text, 'Fouls', 'right')
        if left_fouls is not None and right_fouls is not None:
            stats['total_fouls'] = left_fouls + right_fouls
        
        # Offsides
        left_off = get_val(all_text, 'Offsides', 'left')
        right_off = get_val(all_text, 'Offsides', 'right')
        if left_off is not None and right_off is not None:
            stats['total_offsides'] = left_off + right_off
        
        # Shots on target
        left_sot = get_val(all_text, 'Shots on target', 'left')
        right_sot = get_val(all_text, 'Shots on target', 'right')
        if left_sot is not None and right_sot is not None:
            stats['total_sot'] = left_sot + right_sot
    
    # First half stats
    if first_text:
        fh_left = get_val(first_text, 'Corner kicks', 'left')
        fh_right = get_val(first_text, 'Corner kicks', 'right')
        if fh_left is not None and fh_right is not None:
            stats['first_half_corners'] = fh_left + fh_right
        
        fh_ly = get_val(first_text, 'Yellow cards', 'left')
        fh_ry = get_val(first_text, 'Yellow cards', 'right')
        if fh_ly is not None and fh_ry is not None:
            stats['first_half_yellows'] = fh_ly + fh_ry
    
    return stats

# Parse all 3 blocks
nassr_matches = parse_matches(text, "Ultimos 10 - Al-Nassr")
hilal_matches = parse_matches(text, "Ultimos 10 - Al-Hilal")
h2h_matches = parse_matches(text, "Historial H2H")

print(f"Al-Nassr matches parsed: {len(nassr_matches)}")
print(f"Al-Hilal matches parsed: {len(hilal_matches)}")
print(f"H2H matches parsed: {len(h2h_matches)}")

# ============ CALCULATE METRICS ============
def calc_metrics(matches, label):
    if not matches:
        return {}
    
    metrics = {}
    keys = ['total_goals', 'btts', 'total_corners', 'total_yellows', 'total_fouls', 
            'total_offsides', 'total_shots_match', 'total_sot', 'first_half_corners',
            'first_half_yellows', 'home_goals', 'away_goals']
    
    for key in keys:
        vals = [m[key] for m in matches if key in m and m[key] is not None]
        if vals:
            avg = sum(vals) / len(vals)
            mn = min(vals)
            mx = max(vals)
            metrics[key] = {'avg': avg, 'min': mn, 'max': mx, 'values': vals, 'count': len(vals)}
    
    return metrics

nassr_metrics = calc_metrics(nassr_matches, "Al-Nassr")
hilal_metrics = calc_metrics(hilal_matches, "Al-Hilal")
h2h_metrics = calc_metrics(h2h_matches, "H2H")

# Combined (20 matches: 10 Nassr + 10 H2H for Nassr perspective)
# For combined, use all 30 matches
all_matches = nassr_matches + hilal_matches + h2h_matches
combined_metrics = calc_metrics(all_matches, "Combined")

# ============ PRINT ANALYSIS ============
def print_analysis(metrics, label):
    print(f"\n{'='*60}")
    print(f"METRICAS: {label}")
    print(f"{'='*60}")
    
    lines = {
        'total_goals': [1.5, 2.5, 3.5, 4.5, 5.5],
        'total_corners': [6.5, 7.5, 8.5, 9.5, 10.5, 11.5],
        'total_yellows': [2.5, 3.5, 4.5, 5.5, 6.5],
        'total_fouls': [19.5, 21.5, 23.5, 25.5],
        'total_offsides': [2.5, 3.5, 4.5, 5.5],
        'total_shots_match': [19.5, 21.5, 23.5, 25.5],
        'total_sot': [5.5, 7.5, 9.5],
        'first_half_corners': [3.5, 4.5, 5.5],
        'first_half_yellows': [0.5, 1.5, 2.5],
    }
    
    for key, thresholds in lines.items():
        if key not in metrics:
            continue
        m = metrics[key]
        print(f"\n  {key}: Media={m['avg']:.2f} | Min={m['min']} | Max={m['max']} | N={m['count']}")
        for t in thresholds:
            over = sum(1 for v in m['values'] if v > t)
            pct = over / len(m['values']) * 100
            print(f"    Over {t}: {over}/{len(m['values'])} = {pct:.1f}%")
    
    # BTTS
    if 'btts' in metrics:
        btts_yes = sum(1 for m_item in metrics['btts']['values'] if m_item == 1)
        total = len(metrics['btts']['values'])
        print(f"\n  BTTS: {btts_yes}/{total} = {btts_yes/total*100:.1f}%")

print_analysis(nassr_metrics, "AL-NASSR (10 propios)")
print_analysis(hilal_metrics, "AL-HILAL (10 propios)")
print_analysis(h2h_metrics, "H2H (10 enfrentamientos)")

# Combined 30
print_analysis(combined_metrics, "COMBINADO 30 PARTIDOS")

# ============ LOAD MARKET ODDS FOR VALUE CALC ============
with open('backend/raw_markets.json', 'r', encoding='utf-8') as f:
    jdata = json.load(f)

odds_dict = {}
for odd in jdata.get('odds', []):
    if not isinstance(odd['id'], list):
        odds_dict[odd['id']] = {'name': odd.get('name', ''), 'price': odd.get('price', 0)}

markets_dict = {}
for m in jdata.get('markets', []):
    markets_dict[m['id']] = m

# ============ VALUE CALCULATION ============
print(f"\n{'='*80}")
print("FASE 4 — CRUCE Y CALCULO DE VALUE")
print(f"{'='*80}")

# Key markets to check - we'll extract from "Crear Apuesta" group (ID 23)
crear_group = None
for mg in jdata.get('marketGroups', []):
    if mg.get('id') == 23:
        crear_group = mg
        break

# Also check Principal (ID 1)
principal_group = None
for mg in jdata.get('marketGroups', []):
    if mg.get('id') == 1:
        principal_group = mg
        break

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

# Map specific markets to our stats
value_checks = []

# Use combined 30 matches for probability
cm = combined_metrics

# Check key lines
market_map = {
    'Total': {'stat': 'total_goals', 'lines': [1.5, 2.5, 3.5, 4.5]},
    'Tiros de esquina': {'stat': 'total_corners', 'lines': [7.5, 8.5, 9.5, 10.5]},
    'Tarjetas': {'stat': 'total_yellows', 'lines': [2.5, 3.5, 4.5, 5.5]},
    'Total de faltas': {'stat': 'total_fouls', 'lines': [21.5, 23.5, 25.5]},
    'Total de fueras': {'stat': 'total_offsides', 'lines': [2.5, 3.5, 4.5]},
}

# Scan all markets in Crear Apuesta for matching
if crear_group:
    for mid in crear_group.get('marketIds', []):
        market = markets_dict.get(mid)
        if not market:
            continue
        mname = market.get('name', '')
        sv = market.get('sv', '')
        odd_ids = market.get('desktopOddIds', [])
        odds_list = resolve_odds(odd_ids)
        
        # Match with our stats
        for over_odd in odds_list:
            oname = over_odd.get('name', '')
            price = over_odd.get('price', 0)
            if price <= 1.0:
                continue
            
            # Try to match over/under patterns
            for mkey, minfo in market_map.items():
                if mkey.lower() in mname.lower():
                    stat_key = minfo['stat']
                    if stat_key not in cm:
                        continue
                    
                    for line in minfo['lines']:
                        sv_val = str(line)
                        if sv_val in str(sv) or sv == str(line):
                            vals = cm[stat_key]['values']
                            
                            if 'más' in oname.lower() or 'over' in oname.lower():
                                pr = sum(1 for v in vals if v > line) / len(vals) * 100
                                pi = (1 / price) * 100
                                value = (pr / pi) - 1
                                
                                value_checks.append({
                                    'market': mname,
                                    'selection': oname,
                                    'line': line,
                                    'price': price,
                                    'PR': pr,
                                    'PI': pi,
                                    'value': value,
                                    'stat_key': stat_key,
                                    'group': 'Crear Apuesta'
                                })
                            elif 'menos' in oname.lower() or 'under' in oname.lower():
                                pr = sum(1 for v in vals if v <= line) / len(vals) * 100
                                pi = (1 / price) * 100
                                value = (pr / pi) - 1
                                
                                value_checks.append({
                                    'market': mname,
                                    'selection': oname,
                                    'line': line,
                                    'price': price,
                                    'PR': pr,
                                    'PI': pi,
                                    'value': value,
                                    'stat_key': stat_key,
                                    'group': 'Crear Apuesta'
                                })

# Also scan Principal group
if principal_group:
    for mid in principal_group.get('marketIds', []):
        market = markets_dict.get(mid)
        if not market:
            continue
        mname = market.get('name', '')
        sv = market.get('sv', '')
        odd_ids = market.get('desktopOddIds', [])
        odds_list = resolve_odds(odd_ids)
        
        for over_odd in odds_list:
            oname = over_odd.get('name', '')
            price = over_odd.get('price', 0)
            if price <= 1.0:
                continue
            
            for mkey, minfo in market_map.items():
                if mkey.lower() in mname.lower():
                    stat_key = minfo['stat']
                    if stat_key not in cm:
                        continue
                    
                    for line in minfo['lines']:
                        sv_val = str(line)
                        if sv_val in str(sv) or sv == str(line):
                            vals = cm[stat_key]['values']
                            
                            if 'más' in oname.lower() or 'over' in oname.lower():
                                pr = sum(1 for v in vals if v > line) / len(vals) * 100
                                pi = (1 / price) * 100
                                value = (pr / pi) - 1
                                
                                value_checks.append({
                                    'market': mname,
                                    'selection': oname,
                                    'line': line,
                                    'price': price,
                                    'PR': pr,
                                    'PI': pi,
                                    'value': value,
                                    'stat_key': stat_key,
                                    'group': 'Principal'
                                })

# Also manually check BTTS
for mg in jdata.get('marketGroups', []):
    for mid in mg.get('marketIds', []):
        market = markets_dict.get(mid)
        if not market:
            continue
        mname = market.get('name', '')
        if 'ambos' in mname.lower() and 'marcan' in mname.lower() and 'total' not in mname.lower() and 'mitad' not in mname.lower():
            odds_list = resolve_odds(market.get('desktopOddIds', []))
            for o in odds_list:
                if 'sí' in o['name'].lower() or 'si' in o['name'].lower() or 'yes' in o['name'].lower():
                    btts_vals = cm.get('btts', {}).get('values', [])
                    if btts_vals:
                        pr = sum(1 for v in btts_vals if v == 1) / len(btts_vals) * 100
                        pi = (1 / o['price']) * 100
                        value = (pr / pi) - 1
                        value_checks.append({
                            'market': mname,
                            'selection': o['name'],
                            'line': 'BTTS',
                            'price': o['price'],
                            'PR': pr,
                            'PI': pi,
                            'value': value,
                            'stat_key': 'btts',
                            'group': mg.get('name', 'N/A')
                        })

# Sort by value descending
value_checks.sort(key=lambda x: x['value'], reverse=True)

# Print results
print(f"\nTotal mercados evaluados: {len(value_checks)}")
print(f"\n--- MERCADOS CON VALUE POSITIVO (>10%) ---")
positive = [v for v in value_checks if v['value'] > 0.10]
for v in positive:
    stake = "1-3"
    if v['value'] > 0.30 and v['PR'] > 75 and v['price'] >= 1.75:
        stake = "10"
    elif v['value'] > 0.20 and v['PR'] > 60:
        stake = "8"
    elif v['value'] > 0.10:
        stake = "5"
    
    print(f"\n  MERCADO: {v['market']} | Seleccion: {v['selection']}")
    print(f"  Linea: {v['line']} | Cuota: {v['price']} | Grupo: {v['group']}")
    print(f"  PR: {v['PR']:.1f}% | PI: {v['PI']:.1f}% | VALUE: {v['value']*100:.1f}%")
    print(f"  Cuota justa: {100/v['PR']:.2f} | STAKE SUGERIDO: {stake}")

# Print match details for reference
print(f"\n{'='*60}")
print("DETALLE PARTIDOS AL-NASSR")
print(f"{'='*60}")
for m in nassr_matches:
    g = m.get('total_goals', '?')
    c = m.get('total_corners', '?')
    y = m.get('total_yellows', '?')
    b = 'Si' if m.get('btts') == 1 else 'No'
    f = m.get('total_fouls', '?')
    print(f"  {m['date']} | {m['result']} | Goles:{g} Corners:{c} Yellows:{y} BTTS:{b} Fouls:{f}")

print(f"\n{'='*60}")
print("DETALLE PARTIDOS AL-HILAL")
print(f"{'='*60}")
for m in hilal_matches:
    g = m.get('total_goals', '?')
    c = m.get('total_corners', '?')
    y = m.get('total_yellows', '?')
    b = 'Si' if m.get('btts') == 1 else 'No'
    f = m.get('total_fouls', '?')
    print(f"  {m['date']} | {m['result']} | Goles:{g} Corners:{c} Yellows:{y} BTTS:{b} Fouls:{f}")

print(f"\n{'='*60}")
print("DETALLE H2H")
print(f"{'='*60}")
for m in h2h_matches:
    g = m.get('total_goals', '?')
    c = m.get('total_corners', '?')
    y = m.get('total_yellows', '?')
    b = 'Si' if m.get('btts') == 1 else 'No'
    f = m.get('total_fouls', '?')
    print(f"  {m['date']} | {m['result']} | Goles:{g} Corners:{c} Yellows:{y} BTTS:{b} Fouls:{f}")
