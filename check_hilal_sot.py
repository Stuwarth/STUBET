#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re

with open('pdf_full_text.txt', 'r', encoding='utf-8') as f:
    text = f.read()

def parse_sot(text, section_header, target_team):
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
        
        score_match = re.search(r'(.+?)\s+(\d+)-(\d+)\s+(.+)', result)
        if not score_match: continue
        
        home_team = score_match.group(1).strip()
        is_target_home = target_team.lower() in home_team.lower()
        
        lst, rst = None, None
        pattern = rf'(\d+\.?\d*)\s*\|\s*Shots on target\s*\|\s*(\d+\.?\d*)'
        m = re.search(pattern, all_section)
        if m:
            lst, rst = float(m.group(1)), float(m.group(2))
        
        if lst is not None and rst is not None:
            target_sot = lst if is_target_home else rst
            matches.append({'date': date, 'result': result, 'sot': target_sot})
            
    return matches

hilal_last_10 = parse_sot(text, "Ultimos 10 - Al-Hilal", "Al-Hilal")
h2h_10 = parse_sot(text, "Historial H2H", "Al-Hilal")

print("=== AL HILAL: ÚLTIMOS 10 PARTIDOS PROPIOS ===")
h_over = 0
for m in hilal_last_10:
    over = "✅" if m['sot'] > 4.5 else "❌"
    if m['sot'] > 4.5: h_over += 1
    print(f"{over} {m['date']} | {m['result']} | Remates a puerta: {m['sot']}")
print(f"Total Over 4.5 en propios: {h_over}/10\n")

print("=== HISTORIAL H2H: ÚLTIMOS 10 ENFRENTAMIENTOS ===")
h2h_over = 0
for m in h2h_10:
    over = "✅" if m['sot'] > 4.5 else "❌"
    if m['sot'] > 4.5: h2h_over += 1
    print(f"{over} {m['date']} | {m['result']} | Remates a puerta: {m['sot']}")
print(f"Total Over 4.5 en H2H: {h2h_over}/10\n")

print("=== RESUMEN GLOBAL (20 PARTIDOS) ===")
print(f"Total Over 4.5 Remates al Arco (Al-Hilal): {h_over + h2h_over}/20 ({(h_over + h2h_over)/20*100:.1f}%)")
