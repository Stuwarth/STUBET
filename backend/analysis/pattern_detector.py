"""
Pattern Detector — Discovers and validates statistical patterns in match data.
Finds recurring patterns like:
- Teams with injuries tend to concede more cards
- Certain referee + team combos produce more corners
- Teams breaking form after X losses
- Weather/schedule factors 
- H2H patterns that hold across seasons
"""
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import json
import sys

sys.path.append(str(Path(__file__).parent.parent))


class Pattern:
    """Represents a discovered pattern."""
    
    def __init__(self, name: str, description: str, category: str,
                 confidence: float, sample_size: int, hit_rate: float,
                 conditions: Dict, prediction: Dict):
        self.name = name
        self.description = description
        self.category = category  # team, league, statistical, situational
        self.confidence = confidence  # 0-1
        self.sample_size = sample_size
        self.hit_rate = hit_rate  # 0-1
        self.conditions = conditions
        self.prediction = prediction
        self.discovered_at = datetime.now().isoformat()
        self.last_validated = datetime.now().isoformat()
        self.times_triggered = 0
        self.times_correct = 0
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "confidence": round(self.confidence, 3),
            "sample_size": self.sample_size,
            "hit_rate": round(self.hit_rate, 3),
            "conditions": self.conditions,
            "prediction": self.prediction,
            "discovered_at": self.discovered_at,
            "last_validated": self.last_validated,
            "times_triggered": self.times_triggered,
            "times_correct": self.times_correct,
            "live_accuracy": round(self.times_correct / max(1, self.times_triggered), 3),
        }


class PatternDetector:
    """
    Discovers and validates recurring statistical patterns from match data.
    Runs pattern detection algorithms on historical data and continuously
    validates patterns against new match results.
    """
    
    MIN_SAMPLE_SIZE = 10
    MIN_CONFIDENCE = 0.60
    MIN_HIT_RATE = 0.55
    
    def __init__(self, db):
        self.db = db
        self.patterns: List[Pattern] = []
        self.pattern_store_path = Path(__file__).parent.parent.parent / "data" / "patterns.json"
        self._load_patterns()
    
    def discover_all_patterns(self) -> List[Dict]:
        """Run all pattern discovery algorithms and return discovered patterns."""
        self.patterns = []
        
        # Get all finished matches with stats
        conn = self.db.get_connection()
        
        matches = conn.execute("""
            SELECT m.*, ht.name as home_team_name, at.name as away_team_name,
                   l.name as league_name
            FROM matches m
            JOIN teams ht ON m.home_team_id = ht.api_id
            JOIN teams at ON m.away_team_id = at.api_id
            LEFT JOIN leagues l ON m.league_id = l.api_id
            WHERE m.status = 'FT' AND m.home_goals IS NOT NULL
            ORDER BY m.match_date ASC
        """).fetchall()
        matches = [dict(m) for m in matches]
        
        # Get all stats
        all_stats = conn.execute("""
            SELECT ms.*, m.match_date, m.home_team_id, m.away_team_id,
                   m.home_goals, m.away_goals, m.referee
            FROM match_stats ms
            JOIN matches m ON ms.match_id = m.api_id
            WHERE m.status = 'FT'
            ORDER BY m.match_date ASC
        """).fetchall()
        all_stats = [dict(s) for s in all_stats]
        conn.close()
        
        if len(matches) < self.MIN_SAMPLE_SIZE:
            return []
        
        # Build team stats index
        team_stats = defaultdict(list)
        for stat in all_stats:
            team_stats[stat["team_id"]].append(stat)
        
        # Run pattern detectors
        self._detect_team_form_patterns(matches, team_stats)
        self._detect_statistical_thresholds(matches, team_stats)
        self._detect_h2h_patterns(matches, team_stats)
        self._detect_league_patterns(matches, team_stats)
        self._detect_scoring_patterns(matches, team_stats)
        self._detect_corner_patterns(matches, team_stats)
        self._detect_card_patterns(matches, team_stats)
        self._detect_comeback_patterns(matches)
        self._detect_defensive_patterns(matches, team_stats)
        self._detect_home_away_dominance(matches, team_stats)
        
        # Filter by minimum confidence and hit rate
        valid_patterns = [
            p for p in self.patterns
            if p.confidence >= self.MIN_CONFIDENCE
            and p.hit_rate >= self.MIN_HIT_RATE
            and p.sample_size >= self.MIN_SAMPLE_SIZE
        ]
        
        self.patterns = valid_patterns
        self._save_patterns()
        
        return [p.to_dict() for p in valid_patterns]
    
    # ===================== PATTERN DETECTORS =====================
    
    def _detect_team_form_patterns(self, matches: List[Dict], team_stats: Dict):
        """Detect patterns related to team form and streaks."""
        team_results = defaultdict(list)
        
        for match in matches:
            home_id = match["home_team_id"]
            away_id = match["away_team_id"]
            hg = match["home_goals"] or 0
            ag = match["away_goals"] or 0
            
            team_results[home_id].append({
                "date": match["match_date"],
                "is_home": True,
                "goals_for": hg,
                "goals_against": ag,
                "result": "W" if hg > ag else ("D" if hg == ag else "L"),
                "opponent": away_id,
            })
            team_results[away_id].append({
                "date": match["match_date"],
                "is_home": False,
                "goals_for": ag,
                "goals_against": hg,
                "result": "W" if ag > hg else ("D" if ag == hg else "L"),
                "opponent": home_id,
            })
        
        # Pattern: Teams on 3+ game losing streak tend to bounce back
        bounce_back_total = 0
        bounce_back_wins = 0
        
        for team_id, results in team_results.items():
            for i in range(3, len(results)):
                # Check if last 3 were losses
                if all(results[j]["result"] == "L" for j in range(i-3, i)):
                    bounce_back_total += 1
                    if results[i]["result"] in ["W", "D"]:
                        bounce_back_wins += 1
        
        if bounce_back_total >= self.MIN_SAMPLE_SIZE:
            hit_rate = bounce_back_wins / bounce_back_total
            self.patterns.append(Pattern(
                name="Bounce Back After 3 Losses",
                description="Equipos que perdieron 3 partidos seguidos tienden a NO perder el siguiente",
                category="form",
                confidence=min(0.95, hit_rate + 0.05),
                sample_size=bounce_back_total,
                hit_rate=hit_rate,
                conditions={"consecutive_losses": 3},
                prediction={"expected": "Win or Draw", "market": "double_chance"}
            ))
        
        # Pattern: Teams on 4+ game winning streak - momentum continuation
        streak_cont_total = 0
        streak_cont_wins = 0
        
        for team_id, results in team_results.items():
            for i in range(4, len(results)):
                if all(results[j]["result"] == "W" for j in range(i-4, i)):
                    streak_cont_total += 1
                    if results[i]["result"] == "W":
                        streak_cont_wins += 1
        
        if streak_cont_total >= self.MIN_SAMPLE_SIZE:
            hit_rate = streak_cont_wins / streak_cont_total
            self.patterns.append(Pattern(
                name="Hot Streak Continuation",
                description="Equipos con 4+ victorias seguidas tienden a seguir ganando",
                category="form",
                confidence=min(0.90, hit_rate),
                sample_size=streak_cont_total,
                hit_rate=hit_rate,
                conditions={"consecutive_wins": 4},
                prediction={"expected": "Win", "market": "match_result"}
            ))
        
        # Pattern: Unbeaten home runs
        home_unbeaten_total = 0
        home_unbeaten_cont = 0
        
        for team_id, results in team_results.items():
            home_results = [r for r in results if r["is_home"]]
            for i in range(5, len(home_results)):
                if all(home_results[j]["result"] in ["W", "D"] for j in range(i-5, i)):
                    home_unbeaten_total += 1
                    if home_results[i]["result"] in ["W", "D"]:
                        home_unbeaten_cont += 1
        
        if home_unbeaten_total >= self.MIN_SAMPLE_SIZE:
            hit_rate = home_unbeaten_cont / home_unbeaten_total
            self.patterns.append(Pattern(
                name="Home Fortress",
                description="Equipos invictos en casa 5+ partidos tienden a continuar sin perder",
                category="form",
                confidence=min(0.92, hit_rate + 0.03),
                sample_size=home_unbeaten_total,
                hit_rate=hit_rate,
                conditions={"home_unbeaten_streak": 5},
                prediction={"expected": "Win or Draw", "market": "double_chance"}
            ))
    
    def _detect_statistical_thresholds(self, matches: List[Dict], team_stats: Dict):
        """Detect patterns based on statistical thresholds."""
        # Pattern: Teams averaging >55% possession tend to have more corners
        high_poss_more_corners = 0
        high_poss_total = 0
        
        for team_id, stats in team_stats.items():
            for i in range(5, len(stats)):
                recent_5 = stats[i-5:i]
                avg_poss = np.mean([s.get("possession", 50) or 50 for s in recent_5])
                if avg_poss > 55:
                    high_poss_total += 1
                    if (stats[i].get("corners", 0) or 0) >= 5:
                        high_poss_more_corners += 1
        
        if high_poss_total >= self.MIN_SAMPLE_SIZE:
            hit_rate = high_poss_more_corners / high_poss_total
            self.patterns.append(Pattern(
                name="High Possession → More Corners",
                description="Equipos con >55% posesión promedio tienen 5+ corners en el siguiente partido",
                category="statistical",
                confidence=min(0.88, hit_rate),
                sample_size=high_poss_total,
                hit_rate=hit_rate,
                conditions={"avg_possession_last_5": ">55%"},
                prediction={"expected": "Over 4.5 Team Corners", "market": "corners_team"}
            ))
        
        # Pattern: High-fouling teams get more cards
        high_fouls_cards = 0
        high_fouls_total = 0
        
        for team_id, stats in team_stats.items():
            for i in range(5, len(stats)):
                recent_5 = stats[i-5:i]
                avg_fouls = np.mean([s.get("fouls", 12) or 12 for s in recent_5])
                if avg_fouls > 15:
                    high_fouls_total += 1
                    if (stats[i].get("yellow_cards", 0) or 0) >= 2:
                        high_fouls_cards += 1
        
        if high_fouls_total >= self.MIN_SAMPLE_SIZE:
            hit_rate = high_fouls_cards / high_fouls_total
            self.patterns.append(Pattern(
                name="Aggressive Teams → More Cards",
                description="Equipos con >15 faltas promedio reciben 2+ amarillas",
                category="statistical",
                confidence=min(0.90, hit_rate),
                sample_size=high_fouls_total,
                hit_rate=hit_rate,
                conditions={"avg_fouls_last_5": ">15"},
                prediction={"expected": "Over 1.5 Team Yellow Cards", "market": "yellow_cards_team"}
            ))
        
        # Pattern: Teams with high shots on target rate tend to score
        high_sot_scores = 0
        high_sot_total = 0
        
        for team_id, stats in team_stats.items():
            for i in range(5, len(stats)):
                recent_5 = stats[i-5:i]
                avg_sot = np.mean([s.get("shots_on_target", 4) or 4 for s in recent_5])
                if avg_sot > 5:
                    high_sot_total += 1
                    is_home = stats[i].get("home_team_id") == team_id
                    goals = stats[i].get("home_goals", 0) if is_home else stats[i].get("away_goals", 0)
                    if (goals or 0) >= 1:
                        high_sot_scores += 1
        
        if high_sot_total >= self.MIN_SAMPLE_SIZE:
            hit_rate = high_sot_scores / high_sot_total
            self.patterns.append(Pattern(
                name="High SOT → Team Scores",
                description="Equipos con >5 remates al arco promedio marcan al menos 1 gol",
                category="statistical",
                confidence=min(0.92, hit_rate),
                sample_size=high_sot_total,
                hit_rate=hit_rate,
                conditions={"avg_shots_on_target_last_5": ">5"},
                prediction={"expected": "Team to Score", "market": "team_goals"}
            ))
    
    def _detect_h2h_patterns(self, matches: List[Dict], team_stats: Dict):
        """Detect head-to-head patterns between team pairs."""
        h2h_data = defaultdict(list)
        
        for match in matches:
            pair = tuple(sorted([match["home_team_id"], match["away_team_id"]]))
            h2h_data[pair].append(match)
        
        for pair, pair_matches in h2h_data.items():
            if len(pair_matches) < 3:
                continue
            
            # BTTS pattern in H2H
            btts_count = sum(1 for m in pair_matches
                           if (m["home_goals"] or 0) > 0 and (m["away_goals"] or 0) > 0)
            btts_rate = btts_count / len(pair_matches)
            
            if btts_rate >= 0.80 and len(pair_matches) >= 4:
                t1_name = pair_matches[-1].get("home_team_name", str(pair[0]))
                t2_name = pair_matches[-1].get("away_team_name", str(pair[1]))
                
                self.patterns.append(Pattern(
                    name=f"H2H BTTS: {t1_name} vs {t2_name}",
                    description=f"Ambos equipos marcan en {btts_count}/{len(pair_matches)} enfrentamientos directos ({btts_rate*100:.0f}%)",
                    category="h2h",
                    confidence=min(0.90, btts_rate),
                    sample_size=len(pair_matches),
                    hit_rate=btts_rate,
                    conditions={"team_pair": list(pair), "h2h_btts_rate": btts_rate},
                    prediction={"expected": "BTTS Yes", "market": "btts"}
                ))
            
            # Over 2.5 pattern in H2H
            over25_count = sum(1 for m in pair_matches
                              if ((m["home_goals"] or 0) + (m["away_goals"] or 0)) > 2.5)
            over25_rate = over25_count / len(pair_matches)
            
            if over25_rate >= 0.75 and len(pair_matches) >= 4:
                avg_goals = np.mean([(m["home_goals"] or 0) + (m["away_goals"] or 0) for m in pair_matches])
                self.patterns.append(Pattern(
                    name=f"H2H Over 2.5: {t1_name} vs {t2_name}",
                    description=f"Más de 2.5 goles en {over25_count}/{len(pair_matches)} H2H (promedio: {avg_goals:.1f})",
                    category="h2h",
                    confidence=min(0.88, over25_rate),
                    sample_size=len(pair_matches),
                    hit_rate=over25_rate,
                    conditions={"team_pair": list(pair), "h2h_over25_rate": over25_rate},
                    prediction={"expected": "Over 2.5", "market": "over_under_25"}
                ))
    
    def _detect_league_patterns(self, matches: List[Dict], team_stats: Dict):
        """Detect league-specific patterns."""
        league_stats = defaultdict(lambda: {
            "total": 0, "over25": 0, "btts": 0, "home_wins": 0,
            "total_corners": [], "total_cards": [], "total_goals": []
        })
        
        for match in matches:
            league_id = match.get("league_id")
            if not league_id:
                continue
            
            hg = match["home_goals"] or 0
            ag = match["away_goals"] or 0
            
            ls = league_stats[league_id]
            ls["total"] += 1
            ls["total_goals"].append(hg + ag)
            if hg + ag > 2.5:
                ls["over25"] += 1
            if hg > 0 and ag > 0:
                ls["btts"] += 1
            if hg > ag:
                ls["home_wins"] += 1
        
        for league_id, ls in league_stats.items():
            if ls["total"] < 20:
                continue
            
            over25_rate = ls["over25"] / ls["total"]
            if over25_rate > 0.55:
                league_name = next((m.get("league_name", str(league_id)) 
                                   for m in matches if m.get("league_id") == league_id), str(league_id))
                
                self.patterns.append(Pattern(
                    name=f"Liga goleadora: {league_name}",
                    description=f"Más de 2.5 goles en {over25_rate*100:.0f}% de los partidos de esta liga",
                    category="league",
                    confidence=min(0.85, over25_rate),
                    sample_size=ls["total"],
                    hit_rate=over25_rate,
                    conditions={"league_id": league_id, "over25_rate": over25_rate},
                    prediction={"expected": "Over 2.5", "market": "over_under_25"}
                ))
            
            home_win_rate = ls["home_wins"] / ls["total"]
            if home_win_rate > 0.50:
                self.patterns.append(Pattern(
                    name=f"Home Advantage Strong: {league_name}",
                    description=f"Equipo local gana en {home_win_rate*100:.0f}% de los partidos",
                    category="league",
                    confidence=min(0.82, home_win_rate),
                    sample_size=ls["total"],
                    hit_rate=home_win_rate,
                    conditions={"league_id": league_id, "home_win_rate": home_win_rate},
                    prediction={"expected": "Home Win", "market": "match_result"}
                ))
    
    def _detect_scoring_patterns(self, matches: List[Dict], team_stats: Dict):
        """Detect scoring-related patterns."""
        # Teams that score early tend to win
        # (Using goal data patterns)
        team_results = defaultdict(list)
        
        for match in matches:
            hg = match["home_goals"] or 0
            ag = match["away_goals"] or 0
            
            team_results[match["home_team_id"]].append({
                "goals_for": hg, "goals_against": ag,
                "result": "W" if hg > ag else ("D" if hg == ag else "L"),
                "total_goals": hg + ag,
            })
            team_results[match["away_team_id"]].append({
                "goals_for": ag, "goals_against": hg,
                "result": "W" if ag > hg else ("D" if ag == hg else "L"),
                "total_goals": hg + ag,
            })
        
        # Clean sheet breakers
        cs_break_total = 0
        cs_break_over = 0
        
        for team_id, results in team_results.items():
            for i in range(3, len(results)):
                recent_3 = results[i-3:i]
                if all(r["goals_for"] == 0 for r in recent_3):
                    cs_break_total += 1
                    if results[i]["goals_for"] > 0:
                        cs_break_over += 1
        
        if cs_break_total >= self.MIN_SAMPLE_SIZE:
            hit_rate = cs_break_over / cs_break_total
            self.patterns.append(Pattern(
                name="Drought Breaker",
                description="Equipos que no marcaron en 3 partidos seguidos tienden a marcar en el siguiente",
                category="scoring",
                confidence=min(0.85, hit_rate),
                sample_size=cs_break_total,
                hit_rate=hit_rate,
                conditions={"consecutive_blanks": 3},
                prediction={"expected": "Team to Score", "market": "team_goals"}
            ))
    
    def _detect_corner_patterns(self, matches: List[Dict], team_stats: Dict):
        """Detect corner-specific patterns."""
        # High possession → more corners
        for team_id, stats in team_stats.items():
            if len(stats) < 10:
                continue
            
            corners = [s.get("corners", 0) or 0 for s in stats]
            possession = [s.get("possession", 50) or 50 for s in stats]
            shots = [s.get("shots_total", 10) or 10 for s in stats]
            
            if len(corners) >= 10:
                avg_corners = np.mean(corners)
                if avg_corners > 6:
                    self.patterns.append(Pattern(
                        name=f"Corner Machine (Team {team_id})",
                        description=f"Equipo consistente con {avg_corners:.1f} corners promedio por partido",
                        category="team_statistical",
                        confidence=min(0.85, 0.5 + avg_corners / 20),
                        sample_size=len(corners),
                        hit_rate=sum(1 for c in corners if c >= 5) / len(corners),
                        conditions={"team_id": team_id, "avg_corners": avg_corners},
                        prediction={"expected": "Over 4.5 Team Corners", "market": "corners_team"}
                    ))
    
    def _detect_card_patterns(self, matches: List[Dict], team_stats: Dict):
        """Detect card-related patterns."""
        for team_id, stats in team_stats.items():
            if len(stats) < 10:
                continue
            
            cards = [s.get("yellow_cards", 0) or 0 for s in stats]
            fouls = [s.get("fouls", 12) or 12 for s in stats]
            
            avg_cards = np.mean(cards)
            avg_fouls = np.mean(fouls)
            
            if avg_cards >= 2.5:
                self.patterns.append(Pattern(
                    name=f"Card Magnet (Team {team_id})",
                    description=f"Equipo agresivo: {avg_cards:.1f} amarillas y {avg_fouls:.1f} faltas promedio",
                    category="team_statistical",
                    confidence=min(0.88, 0.5 + avg_cards / 6),
                    sample_size=len(cards),
                    hit_rate=sum(1 for c in cards if c >= 2) / len(cards),
                    conditions={"team_id": team_id, "avg_yellow_cards": avg_cards, "avg_fouls": avg_fouls},
                    prediction={"expected": "Over 1.5 Team Yellow Cards", "market": "yellow_cards_team"}
                ))
    
    def _detect_comeback_patterns(self, matches: List[Dict]):
        """Detect comeback patterns (HT losing → FT winning)."""
        comeback_total = 0
        comeback_success = 0
        
        for match in matches:
            ht_home = match.get("home_goals_ht") or 0
            ht_away = match.get("away_goals_ht") or 0
            ft_home = match.get("home_goals") or 0
            ft_away = match.get("away_goals") or 0
            
            # Home team losing at HT
            if ht_home < ht_away:
                comeback_total += 1
                if ft_home >= ft_away:  # Came back to draw or win
                    comeback_success += 1
        
        if comeback_total >= self.MIN_SAMPLE_SIZE:
            hit_rate = comeback_success / comeback_total
            if hit_rate > 0.20:  # Comebacks are rare but valuable
                self.patterns.append(Pattern(
                    name="Home Comeback After Losing HT",
                    description=f"Equipo local pierde en HT pero empata/gana: {hit_rate*100:.0f}% de las veces",
                    category="situational",
                    confidence=min(0.75, hit_rate + 0.15),
                    sample_size=comeback_total,
                    hit_rate=hit_rate,
                    conditions={"home_losing_ht": True},
                    prediction={"expected": "Home Win/Draw FT", "market": "double_chance"}
                ))
    
    def _detect_defensive_patterns(self, matches: List[Dict], team_stats: Dict):
        """Detect defensive patterns — clean sheets, low goals, etc."""
        team_cs = defaultdict(list)
        
        for match in matches:
            hg = match["home_goals"] or 0
            ag = match["away_goals"] or 0
            
            team_cs[match["home_team_id"]].append(ag == 0)
            team_cs[match["away_team_id"]].append(hg == 0)
        
        for team_id, cs_list in team_cs.items():
            if len(cs_list) < 10:
                continue
            
            cs_rate = sum(cs_list) / len(cs_list)
            if cs_rate > 0.35:
                recent_cs_rate = sum(cs_list[:5]) / min(5, len(cs_list))
                self.patterns.append(Pattern(
                    name=f"Defensive Wall (Team {team_id})",
                    description=f"Equipo con {cs_rate*100:.0f}% clean sheets (reciente: {recent_cs_rate*100:.0f}%)",
                    category="team_statistical",
                    confidence=min(0.85, cs_rate + 0.1),
                    sample_size=len(cs_list),
                    hit_rate=cs_rate,
                    conditions={"team_id": team_id, "clean_sheet_rate": cs_rate},
                    prediction={"expected": "Under 0.5 opponent goals", "market": "team_clean_sheet"}
                ))
    
    def _detect_home_away_dominance(self, matches: List[Dict], team_stats: Dict):
        """Detect teams with extreme home/away performance differences."""
        team_home = defaultdict(list)
        team_away = defaultdict(list)
        
        for match in matches:
            hg = match["home_goals"] or 0
            ag = match["away_goals"] or 0
            
            home_result = "W" if hg > ag else ("D" if hg == ag else "L")
            away_result = "W" if ag > hg else ("D" if ag == hg else "L")
            
            team_home[match["home_team_id"]].append(home_result)
            team_away[match["away_team_id"]].append(away_result)
        
        for team_id in set(list(team_home.keys()) + list(team_away.keys())):
            home = team_home.get(team_id, [])
            away = team_away.get(team_id, [])
            
            if len(home) < 5 or len(away) < 5:
                continue
            
            home_win_rate = home.count("W") / len(home)
            away_win_rate = away.count("W") / len(away)
            
            if home_win_rate > 0.65 and home_win_rate - away_win_rate > 0.25:
                self.patterns.append(Pattern(
                    name=f"Home Dominant (Team {team_id})",
                    description=f"Equipo gana {home_win_rate*100:.0f}% en casa vs {away_win_rate*100:.0f}% fuera (diferencia: {(home_win_rate-away_win_rate)*100:.0f}%)",
                    category="situational",
                    confidence=min(0.88, home_win_rate),
                    sample_size=len(home),
                    hit_rate=home_win_rate,
                    conditions={"team_id": team_id, "home_win_rate": home_win_rate, "away_win_rate": away_win_rate},
                    prediction={"expected": "Home Win when playing at home", "market": "match_result"}
                ))
    
    def get_active_patterns_for_match(self, home_id: int, away_id: int) -> List[Dict]:
        """Find which active patterns apply to an upcoming match."""
        applicable = []
        
        for pattern in self.patterns:
            cond = pattern.conditions
            
            # Check team-specific conditions
            if "team_id" in cond:
                if cond["team_id"] in [home_id, away_id]:
                    applicable.append(pattern.to_dict())
            
            # Check H2H conditions
            elif "team_pair" in cond:
                pair = set(cond["team_pair"])
                if pair == {home_id, away_id}:
                    applicable.append(pattern.to_dict())
            
            # Check form conditions
            elif pattern.category == "form":
                # Check if either team meets the form criteria
                for team_id in [home_id, away_id]:
                    if self._check_form_condition(team_id, cond):
                        p_dict = pattern.to_dict()
                        p_dict["applies_to"] = team_id
                        applicable.append(p_dict)
            
            # League patterns
            elif "league_id" in cond:
                applicable.append(pattern.to_dict())
        
        # Sort by confidence
        applicable.sort(key=lambda x: x["confidence"], reverse=True)
        return applicable
    
    def _check_form_condition(self, team_id: int, conditions: Dict) -> bool:
        """Check if a team meets form-based conditions."""
        matches = self.db.get_team_matches(team_id, limit=10)
        
        if "consecutive_losses" in conditions:
            n = conditions["consecutive_losses"]
            if len(matches) >= n:
                losses = 0
                for m in matches[:n]:
                    is_home = m["home_team_id"] == team_id
                    hg = m["home_goals"] or 0
                    ag = m["away_goals"] or 0
                    if (is_home and hg < ag) or (not is_home and ag < hg):
                        losses += 1
                return losses >= n
        
        if "consecutive_wins" in conditions:
            n = conditions["consecutive_wins"]
            if len(matches) >= n:
                wins = 0
                for m in matches[:n]:
                    is_home = m["home_team_id"] == team_id
                    hg = m["home_goals"] or 0
                    ag = m["away_goals"] or 0
                    if (is_home and hg > ag) or (not is_home and ag > hg):
                        wins += 1
                return wins >= n
        
        return False
    
    def _save_patterns(self):
        """Save discovered patterns to JSON."""
        self.pattern_store_path.parent.mkdir(parents=True, exist_ok=True)
        data = [p.to_dict() for p in self.patterns]
        with open(self.pattern_store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _load_patterns(self):
        """Load previously discovered patterns."""
        if self.pattern_store_path.exists():
            try:
                with open(self.pattern_store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for p_dict in data:
                    self.patterns.append(Pattern(
                        name=p_dict["name"],
                        description=p_dict["description"],
                        category=p_dict["category"],
                        confidence=p_dict["confidence"],
                        sample_size=p_dict["sample_size"],
                        hit_rate=p_dict["hit_rate"],
                        conditions=p_dict["conditions"],
                        prediction=p_dict["prediction"],
                    ))
            except Exception:
                self.patterns = []
