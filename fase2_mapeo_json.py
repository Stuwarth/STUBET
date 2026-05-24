#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 2 — MAPEO TOTAL DEL JSON (raw_markets.json)
"""

import json

with open('backend/raw_markets.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# PASO 2.1 — Diccionarios base
odds_dict = {}
if 'odds' in data:
    for odd in data['odds']:
        oid = odd['id']
        if isinstance(oid, list):
            continue
        odds_dict[oid] = {'name': odd.get('name', ''), 'price': odd.get('price', 0)}

markets_dict = {}
if 'markets' in data:
    for m in data['markets']:
        markets_dict[m['id']] = m

child_dict = {}
if 'childMarkets' in data:
    for c in data['childMarkets']:
        child_dict[c['id']] = c

def resolve_odds(odd_ids):
    results = []
    if not odd_ids:
        return results
    for oid in odd_ids:
        if isinstance(oid, list):
            for sub_oid in oid:
                o = odds_dict.get(sub_oid, {})
                if o:
                    results.append(f"{o.get('name','?')}={o.get('price','?')}")
        else:
            o = odds_dict.get(oid, {})
            if o:
                results.append(f"{o.get('name','?')}={o.get('price','?')}")
    return results

# Inventario
print("=" * 80)
print("INVENTARIO DE GRUPOS")
print("=" * 80)

market_groups = data.get('marketGroups', [])
for mg in market_groups:
    mids = mg.get('marketIds', [])
    print(f"  ID: {mg.get('id')} | Nombre: {mg.get('name', 'N/A')} | Markets: {len(mids)}")
print(f"\nTotal marketGroups: {len(market_groups)}")

child_groups = data.get('childMarketGroups', [])
print("\n--- childMarketGroups ---")
for cg in child_groups:
    mids = cg.get('marketIds', [])
    print(f"  ID: {cg.get('id')} | Nombre: {cg.get('name', 'N/A')} | Markets: {len(mids)}")
print(f"\nTotal childMarketGroups: {len(child_groups)}")

# DETALLE marketGroups
print("\n" + "=" * 80)
print("DETALLE DE MERCADOS POR GRUPO (marketGroups)")
print("=" * 80)

dynamic_markets = []
all_market_ids_in_groups = set()

for mg in market_groups:
    group_name = mg.get('name', 'N/A')
    print(f"\n--- GRUPO: {group_name} (ID: {mg.get('id')}) ---")
    
    for mid in mg.get('marketIds', []):
        all_market_ids_in_groups.add(mid)
        market = markets_dict.get(mid)
        if not market:
            continue
        
        mname = market.get('name', 'N/A')
        sv = market.get('sv', '')
        
        if sv and ('ws:player' in str(sv) or 'dst:player' in str(sv)):
            dynamic_markets.append({'group': group_name, 'market': mname, 'sv': sv, 'id': mid})
            continue
        
        odd_ids = market.get('desktopOddIds', [])
        odds_str = resolve_odds(odd_ids)
        if not odds_str:
            print(f"  {mname} | sv: {sv} | SIN CUOTAS")
        else:
            print(f"  {mname} | sv: {sv} | {' | '.join(odds_str)}")

# DETALLE childMarketGroups
print("\n" + "=" * 80)
print("DETALLE DE MERCADOS POR GRUPO (childMarketGroups)")
print("=" * 80)

all_child_ids_in_groups = set()

for cg in child_groups:
    group_name = cg.get('name', 'N/A')
    print(f"\n--- CHILD GRUPO: {group_name} (ID: {cg.get('id')}) ---")
    
    for mid in cg.get('marketIds', []):
        all_child_ids_in_groups.add(mid)
        child = child_dict.get(mid)
        if not child:
            continue
        
        mname = child.get('name', 'N/A')
        sv = child.get('sv', '')
        
        if sv and ('ws:player' in str(sv) or 'dst:player' in str(sv)):
            dynamic_markets.append({'group': group_name, 'market': mname, 'sv': sv, 'id': mid})
            continue
        
        odd_ids = child.get('desktopOddIds', [])
        odds_str = resolve_odds(odd_ids)
        if not odds_str:
            print(f"  {mname} | sv: {sv} | SIN CUOTAS")
        else:
            print(f"  {mname} | sv: {sv} | {' | '.join(odds_str)}")

# Dynamic
print(f"\n--- MERCADOS DINAMICOS ({len(dynamic_markets)}) ---")
for dm in dynamic_markets[:20]:
    print(f"  Grupo: {dm['group']} | {dm['market']} | sv: {dm['sv']}")

# Summary
print("\n" + "=" * 80)
print("RESUMEN")
print("=" * 80)
print(f"Total odds: {len(odds_dict)}")
print(f"Total markets: {len(markets_dict)}")
print(f"Total childMarkets: {len(child_dict)}")
print(f"marketGroups: {len(market_groups)}")
print(f"childMarketGroups: {len(child_groups)}")
print(f"Dinamicos: {len(dynamic_markets)}")
