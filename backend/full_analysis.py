import re
from collections import defaultdict

with open(r'c:\Users\stuwa\Desktop\SportsAI-Predictor\backend\pdf_analysis_text.txt', 'r', encoding='utf-8') as f:
    text = f.read()

# Split into sections
barca_section = text.split('Ultimos 10 - Real Madrid')[0]
madrid_section = text.split('Ultimos 10 - Real Madrid')[1].split('Historial H2H')[0]
h2h_section = text.split('Historial H2H')[1] if 'Historial H2H' in text else ''

def parse_matches(section_text):
    """Parse matches and extract ALL period stats from a section."""
    matches = []
    # Split by match headers
    headers = list(re.finditer(r'(\d{4}-\d{2}-\d{2}) \| (.+?) \| (.+)', section_text))
    
    for i, h in enumerate(headers):
        start = h.start()
        end = headers[i+1].start() if i+1 < len(headers) else len(section_text)
        match_text = section_text[start:end]
        
        date = h.group(1)
        comp = h.group(2).strip()
        result = h.group(3).strip()
        
        # Extract ALL period stats (only use --- ALL --- for analysis)
        all_section = ''
        all_match = re.search(r'--- ALL ---(.+?)(?:--- 1ST ---|$)', match_text, re.DOTALL)
        if all_match:
            all_section = all_match.group(1)
        
        # Parse key stats from ALL section
        stats = {}
        stat_patterns = {
            'possession_home': r'(\d+)% \| Ball possession',
            'possession_away': r'Ball possession \| (\d+)%',
            'xg_home': r'([\d.]+) \| Expected goals',
            'xg_away': r'Expected goals \| ([\d.]+)',
            'total_shots_home': r'(\d+) \| Total shots',
            'total_shots_away': r'Total shots \| (\d+)',
            'shots_on_target_home': r'(\d+) \| Shots on target',
            'shots_on_target_away': r'Shots on target \| (\d+)',
            'corners_home': r'(\d+) \| Corner kicks',
            'corners_away': r'Corner kicks \| (\d+)',
            'fouls_home': r'(\d+) \| Fouls',
            'fouls_away': r'Fouls \| (\d+)',
            'yellow_home': r'(\d+) \| Yellow cards',
            'yellow_away': r'Yellow cards \| (\d+)',
            'big_chances_home': r'(\d+) \| Big chances \|',
            'big_chances_away': r'Big chances \| (\d+)',
            'offsides_home': r'(\d+) \| Offsides',
            'offsides_away': r'Offsides \| (\d+)',
        }
        
        for key, pattern in stat_patterns.items():
            m = re.search(pattern, all_section)
            if m:
                try:
                    stats[key] = float(m.group(1))
                except:
                    stats[key] = 0
        
        # Parse score from result
        score_match = re.search(r'(\d+)-(\d+)', result)
        if score_match:
            stats['score_left'] = int(score_match.group(1))
            stats['score_right'] = int(score_match.group(2))
        
        matches.append({
            'date': date,
            'comp': comp,
            'result': result,
            'stats': stats
        })
    
    return matches

barca_matches = parse_matches(barca_section)
madrid_matches = parse_matches(madrid_section)
h2h_matches = parse_matches(h2h_section)

print(f"Barcelona matches parsed: {len(barca_matches)}")
print(f"Real Madrid matches parsed: {len(madrid_matches)}")
print(f"H2H matches parsed: {len(h2h_matches)}")

def analyze_team(team_name, matches, is_home_team):
    """Analyze a team's stats across their last 10 matches."""
    print(f"\n{'='*60}")
    print(f"ANÁLISIS ESTADÍSTICO — {team_name} (Últimos {len(matches)} partidos)")
    print(f"{'='*60}")
    
    # Determine which side stats to use
    # For Barcelona section, Barcelona is sometimes home (right) sometimes away (left)
    # We need to check each match
    
    total_shots = []
    shots_on_target = []
    corners = []
    fouls = []
    yellows = []
    goals_scored = []
    goals_conceded = []
    total_goals = []
    xg = []
    
    for m in matches:
        s = m['stats']
        result = m['result']
        
        # Determine if team is home or away in this specific match
        if team_name.lower() in result.lower().split(' ')[0:3]:
            # Team name appears before the score typically
            pass
        
        # Since the PDF format is "Home X-Y Away", we check if team is on left or right
        parts = result.split(' ')
        score_idx = None
        for pi, p in enumerate(parts):
            if re.match(r'\d+-\d+', p):
                score_idx = pi
                break
        
        if score_idx is not None:
            home_name = ' '.join(parts[:score_idx])
            away_name = ' '.join(parts[score_idx+1:])
            score_parts = parts[score_idx].split('-')
            home_goals = int(score_parts[0])
            away_goals = int(score_parts[1])
            
            is_team_home = team_name.lower()[:6] in home_name.lower()
            
            if is_team_home:
                team_goals = home_goals
                opp_goals = away_goals
                t_shots = s.get('total_shots_home', 0)
                t_sot = s.get('shots_on_target_home', 0)
                t_corners = s.get('corners_home', 0)
                t_fouls = s.get('fouls_home', 0)
                t_yellows = s.get('yellow_home', 0)
                t_xg = s.get('xg_home', 0)
            else:
                team_goals = away_goals
                opp_goals = home_goals
                t_shots = s.get('total_shots_away', 0)
                t_sot = s.get('shots_on_target_away', 0)
                t_corners = s.get('corners_away', 0)
                t_fouls = s.get('fouls_away', 0)
                t_yellows = s.get('yellow_away', 0)
                t_xg = s.get('xg_away', 0)
            
            total_shots.append(t_shots)
            shots_on_target.append(t_sot)
            corners.append(t_corners)
            fouls.append(t_fouls)
            yellows.append(t_yellows)
            goals_scored.append(team_goals)
            goals_conceded.append(opp_goals)
            total_goals.append(home_goals + away_goals)
            xg.append(t_xg)
            
            # Also get opponent stats for "both" metrics
            opp_corners = s.get('corners_away' if is_team_home else 'corners_home', 0)
            total_corners_match = t_corners + opp_corners
    
    n = len(matches)
    
    # Print match-by-match
    print(f"\n--- Detalle Partido a Partido ---")
    for i, m in enumerate(matches):
        s = m['stats']
        print(f"  {m['date']} | {m['result']}")
        print(f"    Shots: {total_shots[i]}, SOT: {shots_on_target[i]}, Corners: {corners[i]}, Fouls: {fouls[i]}, Yellows: {yellows[i]}, Goals: {goals_scored[i]}, xG: {xg[i]}")
    
    # Calculate thresholds
    print(f"\n--- Frecuencias y Probabilidades ---")
    
    # Total shots thresholds
    for threshold in [8.5, 9.5, 10.5, 11.5, 12.5]:
        count = sum(1 for x in total_shots if x > threshold)
        print(f"  Remates totales +{threshold}: {count}/{n} = {count/n*100:.0f}%")
    
    # SOT thresholds
    for threshold in [2.5, 3.5, 4.5, 5.5]:
        count = sum(1 for x in shots_on_target if x > threshold)
        print(f"  Remates a puerta +{threshold}: {count}/{n} = {count/n*100:.0f}%")
    
    # Corners thresholds
    for threshold in [3.5, 4.5, 5.5, 6.5, 7.5]:
        count = sum(1 for x in corners if x > threshold)
        print(f"  Córners equipo +{threshold}: {count}/{n} = {count/n*100:.0f}%")
    
    # Fouls thresholds
    for threshold in [10.5, 11.5, 12.5, 13.5]:
        count = sum(1 for x in fouls if x > threshold)
        print(f"  Faltas +{threshold}: {count}/{n} = {count/n*100:.0f}%")
    
    # Yellow cards
    for threshold in [1.5, 2.5, 3.5]:
        count = sum(1 for x in yellows if x > threshold)
        print(f"  Amarillas +{threshold}: {count}/{n} = {count/n*100:.0f}%")
    
    # Goals scored
    for threshold in [0.5, 1.5, 2.5, 3.5]:
        count = sum(1 for x in goals_scored if x > threshold)
        print(f"  Goles anotados +{threshold}: {count}/{n} = {count/n*100:.0f}%")
    
    # Total match goals
    for threshold in [1.5, 2.5, 3.5, 4.5]:
        count = sum(1 for x in total_goals if x > threshold)
        print(f"  Total goles partido +{threshold}: {count}/{n} = {count/n*100:.0f}%")
    
    # BTTS
    btts = sum(1 for i in range(n) if goals_scored[i] > 0 and goals_conceded[i] > 0)
    print(f"  BTTS (ambos marcan): {btts}/{n} = {btts/n*100:.0f}%")
    
    # Averages
    print(f"\n--- Promedios ---")
    print(f"  Remates totales: {sum(total_shots)/n:.1f}")
    print(f"  Remates a puerta: {sum(shots_on_target)/n:.1f}")
    print(f"  Córners: {sum(corners)/n:.1f}")
    print(f"  Faltas: {sum(fouls)/n:.1f}")
    print(f"  Amarillas: {sum(yellows)/n:.1f}")
    print(f"  Goles anotados: {sum(goals_scored)/n:.1f}")
    print(f"  Goles recibidos: {sum(goals_conceded)/n:.1f}")
    print(f"  xG: {sum(xg)/n:.2f}")
    
    return {
        'total_shots': total_shots,
        'shots_on_target': shots_on_target,
        'corners': corners,
        'fouls': fouls,
        'yellows': yellows,
        'goals_scored': goals_scored,
        'goals_conceded': goals_conceded,
        'total_goals': total_goals,
        'xg': xg
    }

barca_stats = analyze_team("FC Barcelona", barca_matches, True)
madrid_stats = analyze_team("Real Madrid", madrid_matches, False)

# H2H Analysis
print(f"\n{'='*60}")
print(f"ANÁLISIS H2H — Últimos {len(h2h_matches)} enfrentamientos")
print(f"{'='*60}")

h2h_total_goals = []
h2h_corners = []
h2h_fouls = []
h2h_yellows = []
h2h_btts = 0

for m in h2h_matches:
    s = m['stats']
    score = re.search(r'(\d+)-(\d+)', m['result'])
    if score:
        g1, g2 = int(score.group(1)), int(score.group(2))
        h2h_total_goals.append(g1 + g2)
        if g1 > 0 and g2 > 0:
            h2h_btts += 1
        
        c1 = s.get('corners_home', 0)
        c2 = s.get('corners_away', 0)
        h2h_corners.append(c1 + c2)
        
        f1 = s.get('fouls_home', 0)
        f2 = s.get('fouls_away', 0)
        h2h_fouls.append(f1 + f2)
        
        y1 = s.get('yellow_home', 0)
        y2 = s.get('yellow_away', 0)
        h2h_yellows.append(y1 + y2)
        
        print(f"  {m['date']} | {m['result']} | Goals: {g1+g2} | Corners: {c1+c2} | Fouls: {f1+f2} | Yellows: {y1+y2}")

n_h2h = len(h2h_total_goals)
if n_h2h > 0:
    print(f"\n--- H2H Frecuencias ---")
    for t in [1.5, 2.5, 3.5, 4.5, 5.5]:
        c = sum(1 for x in h2h_total_goals if x > t)
        print(f"  Total goles +{t}: {c}/{n_h2h} = {c/n_h2h*100:.0f}%")
    
    print(f"  BTTS: {h2h_btts}/{n_h2h} = {h2h_btts/n_h2h*100:.0f}%")
    
    for t in [8.5, 9.5, 10.5, 11.5]:
        c = sum(1 for x in h2h_corners if x > t)
        print(f"  Córners totales +{t}: {c}/{n_h2h} = {c/n_h2h*100:.0f}%")
    
    for t in [20.5, 25.5, 30.5]:
        c = sum(1 for x in h2h_fouls if x > t)
        print(f"  Faltas totales +{t}: {c}/{n_h2h} = {c/n_h2h*100:.0f}%")
    
    for t in [3.5, 4.5, 5.5, 6.5]:
        c = sum(1 for x in h2h_yellows if x > t)
        print(f"  Amarillas totales +{t}: {c}/{n_h2h} = {c/n_h2h*100:.0f}%")
    
    print(f"\n--- H2H Promedios ---")
    print(f"  Goles: {sum(h2h_total_goals)/n_h2h:.1f}")
    print(f"  Córners: {sum(h2h_corners)/n_h2h:.1f}")
    print(f"  Faltas: {sum(h2h_fouls)/n_h2h:.1f}")
    print(f"  Amarillas: {sum(h2h_yellows)/n_h2h:.1f}")

# VALUE BET CALCULATION
print(f"\n{'='*60}")
print(f"CÁLCULO DE VALUE BETS — Probabilidad vs Cuotas")
print(f"{'='*60}")

def calc_value(prob_pct, odds):
    """Calcula el value: (prob * odds) - 1. Si > 0, hay value."""
    prob = prob_pct / 100
    ev = prob * odds - 1
    return ev

# Define the odds from the bookmaker
odds_data = {
    'Over 2.5 goals': 1.35,
    'Over 3.5 goals': 1.8889,
    'Over 4.5 goals': 2.9,
    'Under 3.5 goals': 1.9412,
    'BTTS Si': 1.4167,
    'BTTS No': 2.7,
    'Corners Over 8.5': 1.2858,
    'Corners Over 9.5': 1.5264,
    'Corners Over 10.5': 1.8334,
    'Corners Over 11.5': 2.4,
    'Barca Corners Over 5.5': 1.4546,
    'Barca Corners Over 6.5': 1.95,
    'Madrid Corners Over 3.5': 1.5556,
    'Madrid Corners Over 4.5': 2.2,
    'Cards Over 4.5': 1.3334,
    'Cards Over 5.5': 1.6667,
    'Cards Over 6.5': 2.2,
    'Barca Cards Over 2.5': 1.6,
    'Madrid Cards Over 3.5': 2.2,
    'Fouls Over 25.5': 1.76,
    'Barca total goals Over 1.5': 1.4,
    'Barca total goals Over 2.5': 2.2,
    'Madrid total goals Over 0.5': 1.2858,
    'Madrid total goals Over 1.5': 2.3,
    'Barca Win': 1.6154,
    'Draw': 5.0,
    'Madrid Win': 4.3334,
}

# Combine Barca + Madrid stats for combined metrics
n_b = len(barca_stats['total_goals'])
n_m = len(madrid_stats['total_goals'])

# Combined total goals probability (average of both team perspectives)
for threshold, key in [(2.5, 'Over 2.5 goals'), (3.5, 'Over 3.5 goals'), (4.5, 'Over 4.5 goals')]:
    b_pct = sum(1 for x in barca_stats['total_goals'] if x > threshold) / n_b * 100
    m_pct = sum(1 for x in madrid_stats['total_goals'] if x > threshold) / n_m * 100
    h2h_pct = sum(1 for x in h2h_total_goals if x > threshold) / n_h2h * 100 if n_h2h > 0 else 50
    # Weighted: 35% barca, 35% madrid, 30% h2h
    combined_pct = b_pct * 0.35 + m_pct * 0.35 + h2h_pct * 0.30
    ev = calc_value(combined_pct, odds_data[key])
    marker = "✅ VALUE" if ev > 0 else "❌"
    print(f"  {key}: Prob={combined_pct:.1f}% | Cuota={odds_data[key]} | EV={ev*100:.1f}% {marker}")

# BTTS
b_btts = sum(1 for i in range(n_b) if barca_stats['goals_scored'][i] > 0 and barca_stats['goals_conceded'][i] > 0) / n_b * 100
m_btts = sum(1 for i in range(n_m) if madrid_stats['goals_scored'][i] > 0 and madrid_stats['goals_conceded'][i] > 0) / n_m * 100
h2h_btts_pct = h2h_btts / n_h2h * 100 if n_h2h > 0 else 50
btts_pct = b_btts * 0.35 + m_btts * 0.35 + h2h_btts_pct * 0.30
ev = calc_value(btts_pct, odds_data['BTTS Si'])
marker = "✅ VALUE" if ev > 0 else "❌"
print(f"  BTTS Si: Prob={btts_pct:.1f}% | Cuota={odds_data['BTTS Si']} | EV={ev*100:.1f}% {marker}")

# Barca goals
for threshold, key in [(1.5, 'Barca total goals Over 1.5'), (2.5, 'Barca total goals Over 2.5')]:
    pct = sum(1 for x in barca_stats['goals_scored'] if x > threshold) / n_b * 100
    ev = calc_value(pct, odds_data[key])
    marker = "✅ VALUE" if ev > 0 else "❌"
    print(f"  {key}: Prob={pct:.1f}% | Cuota={odds_data[key]} | EV={ev*100:.1f}% {marker}")

# Madrid goals
for threshold, key in [(0.5, 'Madrid total goals Over 0.5'), (1.5, 'Madrid total goals Over 1.5')]:
    pct = sum(1 for x in madrid_stats['goals_scored'] if x > threshold) / n_m * 100
    ev = calc_value(pct, odds_data[key])
    marker = "✅ VALUE" if ev > 0 else "❌"
    print(f"  {key}: Prob={pct:.1f}% | Cuota={odds_data[key]} | EV={ev*100:.1f}% {marker}")

# Corners
for threshold, key in [(8.5, 'Corners Over 8.5'), (9.5, 'Corners Over 9.5'), (10.5, 'Corners Over 10.5'), (11.5, 'Corners Over 11.5')]:
    h2h_pct = sum(1 for x in h2h_corners if x > threshold) / n_h2h * 100 if n_h2h > 0 else 50
    # Use H2H corners primarily + team averages
    b_avg = sum(barca_stats['corners']) / n_b
    m_avg = sum(madrid_stats['corners']) / n_m
    est_total = b_avg + m_avg
    # Simple probability based on combined averages vs threshold
    # Use H2H data weight higher for combined metrics
    combined_pct = h2h_pct
    ev = calc_value(combined_pct, odds_data[key])
    marker = "✅ VALUE" if ev > 0 else "❌"
    print(f"  {key}: H2H Prob={combined_pct:.1f}% (avg team combined={est_total:.1f}) | Cuota={odds_data[key]} | EV={ev*100:.1f}% {marker}")

# Barca corners
for threshold, key in [(5.5, 'Barca Corners Over 5.5'), (6.5, 'Barca Corners Over 6.5')]:
    pct = sum(1 for x in barca_stats['corners'] if x > threshold) / n_b * 100
    ev = calc_value(pct, odds_data[key])
    marker = "✅ VALUE" if ev > 0 else "❌"
    print(f"  {key}: Prob={pct:.1f}% | Cuota={odds_data[key]} | EV={ev*100:.1f}% {marker}")

# Madrid corners
for threshold, key in [(3.5, 'Madrid Corners Over 3.5'), (4.5, 'Madrid Corners Over 4.5')]:
    pct = sum(1 for x in madrid_stats['corners'] if x > threshold) / n_m * 100
    ev = calc_value(pct, odds_data[key])
    marker = "✅ VALUE" if ev > 0 else "❌"
    print(f"  {key}: Prob={pct:.1f}% | Cuota={odds_data[key]} | EV={ev*100:.1f}% {marker}")

# Cards
b_yellows_avg = sum(barca_stats['yellows']) / n_b
m_yellows_avg = sum(madrid_stats['yellows']) / n_m
for threshold, key in [(4.5, 'Cards Over 4.5'), (5.5, 'Cards Over 5.5'), (6.5, 'Cards Over 6.5')]:
    h2h_pct = sum(1 for x in h2h_yellows if x > threshold) / n_h2h * 100 if n_h2h > 0 else 50
    ev = calc_value(h2h_pct, odds_data[key])
    marker = "✅ VALUE" if ev > 0 else "❌"
    print(f"  {key}: H2H Prob={h2h_pct:.1f}% (avg team combined={b_yellows_avg + m_yellows_avg:.1f}) | Cuota={odds_data[key]} | EV={ev*100:.1f}% {marker}")

# Fouls
for threshold, key in [(25.5, 'Fouls Over 25.5')]:
    h2h_pct = sum(1 for x in h2h_fouls if x > threshold) / n_h2h * 100 if n_h2h > 0 else 50
    ev = calc_value(h2h_pct, odds_data[key])
    marker = "✅ VALUE" if ev > 0 else "❌"
    print(f"  {key}: H2H Prob={h2h_pct:.1f}% | Cuota={odds_data[key]} | EV={ev*100:.1f}% {marker}")

print(f"\n{'='*60}")
print(f"CONTEXTO LESIONES y NOTICIAS")
print(f"{'='*60}")
print("""
FC BARCELONA — Bajas:
  ❌ Andreas Christensen — Lesionado (Ligamento cruzado)
  ❌ Lamine Yamal — Lesionado (Muslo)

  → Christensen no afecta mucho (suplente habitual con Araujo/Cubarsí titulares)
  → Lamine Yamal es BAJA CRÍTICA: mejor extremo derecho, top en regates,
    asistencias y remates. Su ausencia reduce el potencial ofensivo del Barça
    en la banda derecha. Probable sustituto: Ferrán Torres o Dani Olmo desplazado.

REAL MADRID — Bajas (MASIVAS):
  ⚠️ Federico Valverde — Decisión del club (problema de vestuario/disciplinario)
  ❌ Arda Güler — Lesionado (Muslo)
  ❌ Dani Carvajal — Lesionado (Pierna)
  ❌ Dani Ceballos — Lesionado (Muslo)
  ❌ Ferland Mendy — Lesionado (Ligamento)
  ❌ Kylian Mbappé — Lesionado
  ❌ Rodrygo — Lesionado (Ligamento cruzado)
  ❌ Éder Militão — Lesionado (Muslo)

  → CRISIS TOTAL: Sin Mbappé, Rodrygo ni Valverde, el Madrid pierde
    a sus 3 principales generadores ofensivos. Sin Carvajal ni Mendy,
    los laterales serán Vázquez y Fran García (menor nivel defensivo).
    Sin Militão, la defensa depende de Rüdiger + Alaba/Asencio.
    ENTRENADOR: Álvaro Arbeloa (no Ancelotti) — otro factor de inestabilidad.

  → IMPACTO EN MERCADOS:
    - Menos remates del Madrid (pierden a Mbappé+Rodrygo = ~12 shots/partido)
    - Más corners para Barcelona (dominio territorial esperado)
    - Posiblemente más faltas del Madrid (equipo inferior tratando de frenar)
    - Valverde fuera por problemas internos = moral baja en vestuario
""")
