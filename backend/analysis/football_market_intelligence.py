import math
import re
from statistics import mean
from typing import Any, Dict, List, Optional

from ml.advanced_markets import AdvancedMarketPredictor


class FootballMarketIntelligence:
    """Select football picks from real LasPlatas lines plus real statistical context."""

    MARKET_PRIORITY = {
        "live_next_goal": 3.0,
        "live_dnb": 2.5,
        "live_over_0_5": 2.5,
        "live_corners_over": 2.4,
        "live_shots_on_target": 2.4,
        "live_cards_over": 2.3,
        "corners_total": 1.0,
        "corners_home": 0.96,
        "corners_away": 0.96,
        "shots_on_target_total": 0.95,
        "shots_on_target_home": 0.93,
        "shots_on_target_away": 0.93,
        "cards_total": 0.92,
        "cards_home": 0.9,
        "cards_away": 0.9,
        "shots_total": 0.88,
        "shots_home": 0.86,
        "shots_away": 0.86,
        "goalkeeper_saves_total": 0.82,
        "fouls_total": 0.8,
        "offsides_total": 0.78,
        "over_under_25": 0.76,
        "btts": 0.72,
        "match_result": 0.55,
        "draw_no_bet": 0.5,
        "double_chance": 0.48,
    }

    def __init__(self, db, predictor):
        self.db = db
        self.predictor = predictor
        self.advanced_predictor = AdvancedMarketPredictor(db)

    def analyze_matchup(
        self,
        home_id: int,
        away_id: int,
        home_name: str,
        away_name: str,
        scraped_odds: Optional[Dict[str, Any]] = None,
        is_live: bool = False,
        minute: int = 0,
        score_home: int = 0,
        score_away: int = 0,
        live_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        scraped_odds = scraped_odds or {}
        base_predictions = self._build_base_predictions(home_id, away_id)
        advanced_predictions = self.advanced_predictor.predict_match_stats(home_id, away_id)

        home_overall = self._build_team_snapshot(home_id)
        away_overall = self._build_team_snapshot(away_id)
        home_home = self._build_team_snapshot(home_id, home_only=True)
        away_away = self._build_team_snapshot(away_id, away_only=True)
        h2h = self._build_h2h_snapshot(home_id, away_id)

        candidates: List[Dict[str, Any]] = []
        candidates.extend(
            self._evaluate_core_markets(
                base_predictions=base_predictions,
                scraped_odds=scraped_odds,
                home_name=home_name,
                away_name=away_name,
                score_home=score_home,
                score_away=score_away,
                minute=minute,
            )
        )
        candidates.extend(
            self._evaluate_extended_markets(
                advanced_predictions=advanced_predictions,
                scraped_odds=scraped_odds,
                home_name=home_name,
                away_name=away_name,
                home_snapshot=home_home or home_overall,
                away_snapshot=away_away or away_overall,
                h2h=h2h,
                is_live=is_live,
                minute=minute,
                live_stats=live_stats or {},
            )
        )
        
        # --- NEW LIVE DYNAMIC LOGIC ---
        if is_live and (minute > 0):
            candidates.extend(
                self._evaluate_live_dynamic_markets(
                    base_predictions=base_predictions,
                    advanced_predictions=advanced_predictions,
                    scraped_odds=scraped_odds,
                    home_name=home_name,
                    away_name=away_name,
                    score_home=score_home,
                    score_away=score_away,
                    minute=minute,
                    live_stats=live_stats or {}
                )
            )

        filtered_candidates = [
            candidate for candidate in candidates
            if candidate["probability"] >= 0.55 and candidate["edge"] >= 0.04
        ]
        filtered_candidates.sort(
            key=lambda c: (
                c["score"],
                c["edge"],
                c["probability"],
                c["odds"],
            ),
            reverse=True,
        )

        best_pick = filtered_candidates[0] if filtered_candidates else None
        return {
            "match_id": self._get_match_id(home_id, away_id),
            "best_pick": best_pick,
            "candidates": filtered_candidates[:8],
            "core_predictions": base_predictions,
            "advanced_predictions": advanced_predictions,
            "team_context": {
                "home_recent_form": home_overall,
                "away_recent_form": away_overall,
                "home_at_home": home_home,
                "away_away": away_away,
                "h2h": h2h,
            },
            "live_context": {
                "is_live": is_live,
                "minute": minute,
                "score_home": score_home,
                "score_away": score_away,
                "live_stats": live_stats or {},
            },
        }

    def _build_base_predictions(self, home_id: int, away_id: int) -> Dict[str, Any]:
        try:
            return self.predictor.predict_match(home_id, away_id, None)
        except Exception:
            return self._fallback_predictions(home_id, away_id)

    def _fallback_predictions(self, home_id: int, away_id: int) -> Dict[str, Any]:
        home_form = self._build_team_snapshot(home_id)
        away_form = self._build_team_snapshot(away_id)
        h2h = self._build_h2h_snapshot(home_id, away_id)

        home_goal_rate = home_form.get("goals_for_avg", 1.2)
        away_goal_rate = away_form.get("goals_for_avg", 1.0)
        home_concede = home_form.get("goals_against_avg", 1.1)
        away_concede = away_form.get("goals_against_avg", 1.2)
        h2h_goals = h2h.get("goals_total_avg", 2.4)

        total_goals_mean = max(
            1.2,
            (
                home_goal_rate
                + away_goal_rate
                + away_concede
                + home_concede
                + h2h_goals
            ) / 3.0,
        )
        over_25 = self._tail_probability(total_goals_mean, 2.5, std=1.15)
        btts_yes = min(
            0.9,
            max(
                0.1,
                (
                    home_form.get("btts_rate", 0.5)
                    + away_form.get("btts_rate", 0.5)
                    + h2h.get("btts_rate", 0.5)
                ) / 3.0,
            ),
        )

        home_strength = (
            home_form.get("points_per_game", 1.4)
            + home_form.get("goals_for_avg", 1.2)
            - home_form.get("goals_against_avg", 1.1)
        )
        away_strength = (
            away_form.get("points_per_game", 1.3)
            + away_form.get("goals_for_avg", 1.0)
            - away_form.get("goals_against_avg", 1.2)
        )
        draw_prob = max(0.16, min(0.32, 0.26 - abs(home_strength - away_strength) * 0.04))
        home_win = max(0.2, min(0.68, 0.42 + (home_strength - away_strength) * 0.11))
        away_win = max(0.14, 1.0 - draw_prob - home_win)
        total = home_win + draw_prob + away_win
        home_win, draw_prob, away_win = home_win / total, draw_prob / total, away_win / total

        return {
            "match_result": {
                "prediction": "Home Win" if home_win >= away_win else "Away Win",
                "probabilities": {
                    "Home Win": round(home_win * 100, 1),
                    "Draw": round(draw_prob * 100, 1),
                    "Away Win": round(away_win * 100, 1),
                },
                "confidence": self._prob_to_confidence(max(home_win, away_win, draw_prob)),
            },
            "over_under_25": {
                "prediction": "Over 2.5" if over_25 >= 0.5 else "Under 2.5",
                "probabilities": {
                    "Over 2.5": round(over_25 * 100, 1),
                    "Under 2.5": round((1 - over_25) * 100, 1),
                },
                "confidence": self._prob_to_confidence(max(over_25, 1 - over_25)),
            },
            "btts": {
                "prediction": "BTTS Yes" if btts_yes >= 0.5 else "BTTS No",
                "probabilities": {
                    "BTTS Yes": round(btts_yes * 100, 1),
                    "BTTS No": round((1 - btts_yes) * 100, 1),
                },
                "confidence": self._prob_to_confidence(max(btts_yes, 1 - btts_yes)),
            },
        }

    def _build_team_snapshot(
        self,
        team_id: int,
        home_only: bool = False,
        away_only: bool = False,
        limit: int = 10,
    ) -> Dict[str, Any]:
        matches = self.db.get_team_matches(team_id, limit=limit, home_only=home_only, away_only=away_only)
        if not matches:
            from data.collectors.football_api import FootballAPICollector
            api = FootballAPICollector(self.db)
            api.collect_team_recent_fixtures(team_id, last=limit * 2)
            matches = self.db.get_team_matches(team_id, limit=limit, home_only=home_only, away_only=away_only)

        stats = self.db.get_match_stats_for_team(team_id, limit=max(limit * 4, 40))
        match_ids = {match["api_id"] for match in matches}
        filtered_stats = [row for row in stats if row.get("match_id") in match_ids]

        if len(filtered_stats) < len(matches):
            try:
                from data.collectors.football_api import FootballAPICollector
                api = FootballAPICollector(self.db)
                cached_stat_ids = {row.get("match_id") for row in filtered_stats}
                missing_ids = match_ids - cached_stat_ids
                for m_id in list(missing_ids)[:limit]:
                    api.collect_fixture_stats(m_id)
                # Refresh stats after fetching missing ones
                stats = self.db.get_match_stats_for_team(team_id, limit=max(limit * 4, 40))
                filtered_stats = [row for row in stats if row.get("match_id") in match_ids]
            except Exception as e:
                print(f"[WARN] Error backfilling stats for team {team_id}: {e}")

        snapshot = {
            "sample_size": len(matches),
            "goals_for_avg": 0.0,
            "goals_against_avg": 0.0,
            "points_per_game": 0.0,
            "btts_rate": 0.0,
            "over_25_rate": 0.0,
            "avg_corners": 0.0,
            "avg_shots_total": 0.0,
            "avg_shots_on_target": 0.0,
            "avg_cards": 0.0,
            "avg_offsides": 0.0,
            "avg_fouls": 0.0,
            "avg_possession": 0.0,
        }
        if not matches:
            return snapshot

        goals_for: List[float] = []
        goals_against: List[float] = []
        points: List[float] = []
        btts_hits = 0
        over_hits = 0
        clean_sheets = 0

        for match in matches:
            is_home = match.get("home_team_id") == team_id
            team_goals = match.get("home_goals", 0) if is_home else match.get("away_goals", 0)
            opp_goals = match.get("away_goals", 0) if is_home else match.get("home_goals", 0)
            goals_for.append(float(team_goals or 0))
            goals_against.append(float(opp_goals or 0))
            if (team_goals or 0) > (opp_goals or 0):
                points.append(3.0)
            elif (team_goals or 0) == (opp_goals or 0):
                points.append(1.0)
            else:
                points.append(0.0)
            if (team_goals or 0) > 0 and (opp_goals or 0) > 0:
                btts_hits += 1
            if ((team_goals or 0) + (opp_goals or 0)) > 2:
                over_hits += 1
            if (opp_goals or 0) == 0:
                clean_sheets += 1

        snapshot.update({
            "goals_for_avg": round(mean(goals_for), 2),
            "goals_against_avg": round(mean(goals_against), 2),
            "points_per_game": round(mean(points), 2),
            "btts_rate": round(btts_hits / len(matches), 3),
            "over_25_rate": round(over_hits / len(matches), 3),
            "clean_sheets": clean_sheets,
        })

        if filtered_stats:
            snapshot.update({
                "avg_corners": round(mean(float(row.get("corners", 0) or 0) for row in filtered_stats), 2),
                "avg_shots_total": round(mean(float(row.get("shots_total", 0) or 0) for row in filtered_stats), 2),
                "avg_shots_on_target": round(mean(float(row.get("shots_on_target", 0) or 0) for row in filtered_stats), 2),
                "avg_cards": round(mean(float(row.get("yellow_cards", 0) or 0) for row in filtered_stats), 2),
                "avg_offsides": round(mean(float(row.get("offsides", 0) or 0) for row in filtered_stats), 2),
                "avg_fouls": round(mean(float(row.get("fouls", 0) or 0) for row in filtered_stats), 2),
                "avg_possession": round(mean(float(row.get("possession", 0) or 0) for row in filtered_stats), 2),
            })

        return snapshot

    def _build_h2h_snapshot(self, home_id: int, away_id: int, limit: int = 10) -> Dict[str, Any]:
        matches = self.db.get_h2h_matches(home_id, away_id, limit=limit)
        if not matches:
            from data.collectors.football_api import FootballAPICollector
            api = FootballAPICollector(self.db)
            api.collect_h2h(home_id, away_id, last=limit)
            matches = self.db.get_h2h_matches(home_id, away_id, limit=limit)

        if not matches:
            return {
                "sample_size": 0,
                "home_wins": 0,
                "away_wins": 0,
                "draws": 0,
                "goals_total_avg": 0.0,
                "btts_rate": 0.0,
                "corners_total_avg": 0.0,
                "cards_total_avg": 0.0,
            }

        # Lazy load stats for H2H matches
        try:
            from data.collectors.football_api import FootballAPICollector
            api = FootballAPICollector(self.db)
            conn = self.db.get_connection()
            for match in matches:
                m_id = match["api_id"]
                row = conn.execute("SELECT 1 FROM match_stats WHERE match_id = ? LIMIT 1", (m_id,)).fetchone()
                if not row:
                    api.collect_fixture_stats(m_id)
            conn.close()
        except Exception as e:
            print(f"[WARN] Error backfilling stats for H2H {home_id} vs {away_id}: {e}")

        home_wins = away_wins = draws = btts_hits = over_hits = 0
        total_goals: List[float] = []
        total_corners: List[float] = []
        total_cards: List[float] = []

        conn = self.db.get_connection()
        try:
            for match in matches:
                home_goals = float(match.get("home_goals", 0) or 0)
                away_goals = float(match.get("away_goals", 0) or 0)
                total_goals.append(home_goals + away_goals)
                if home_goals > away_goals:
                    winner = match.get("home_team_id")
                elif away_goals > home_goals:
                    winner = match.get("away_team_id")
                else:
                    winner = None

                if winner == home_id:
                    home_wins += 1
                elif winner == away_id:
                    away_wins += 1
                else:
                    draws += 1
                if home_goals > 0 and away_goals > 0:
                    btts_hits += 1
                if home_goals + away_goals > 2:
                    over_hits += 1

                rows = conn.execute(
                    "SELECT corners, yellow_cards FROM match_stats WHERE match_id = ?",
                    (match["api_id"],),
                ).fetchall()
                if rows:
                    total_corners.append(sum(float(dict(row).get("corners", 0) or 0) for row in rows))
                    total_cards.append(sum(float(dict(row).get("yellow_cards", 0) or 0) for row in rows))
        finally:
            conn.close()

        sample = len(matches)
        return {
            "sample_size": sample,
            "home_wins": home_wins,
            "away_wins": away_wins,
            "draws": draws,
            "goals_total_avg": round(mean(total_goals), 2) if total_goals else 0.0,
            "btts_rate": round(btts_hits / sample, 3),
            "over_25_rate": round(over_hits / sample, 3),
            "corners_total_avg": round(mean(total_corners), 2) if total_corners else 0.0,
            "cards_total_avg": round(mean(total_cards), 2) if total_cards else 0.0,
        }

    def _evaluate_core_markets(
        self,
        base_predictions: Dict[str, Any],
        scraped_odds: Dict[str, Any],
        home_name: str,
        away_name: str,
        score_home: int,
        score_away: int,
        minute: int,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        mapping = {
            "match_result": {
                "market_label": "1X2",
                "outcomes": {
                    "Home Win": f"Gana {home_name}",
                    "Draw": "Empate",
                    "Away Win": f"Gana {away_name}",
                },
            },
            "over_under_25": {
                "market_label": "Over/Under 2.5",
                "outcomes": {
                    "Over 2.5": "Over 2.5",
                    "Under 2.5": "Under 2.5",
                },
            },
            "btts": {
                "market_label": "BTTS",
                "outcomes": {
                    "BTTS Yes": "BTTS Sí",
                    "BTTS No": "BTTS No",
                },
            },
        }

        for market_key, config in mapping.items():
            book_market = scraped_odds.get(market_key, {})
            prediction = base_predictions.get(market_key, {})
            probabilities = prediction.get("probabilities", {})
            if not isinstance(book_market, dict) or not probabilities:
                continue
            for outcome, odd in book_market.items():
                if odd is None or outcome not in probabilities:
                    continue
                probability = float(probabilities[outcome]) / 100.0
                
                # ADAPTACIÓN VITAL: Si estamos en LIVE, la predicción estática pre-partido
                # se tiene que derribar o penalizar, porque los odds en vivo son de margin.
                if minute > 0:
                    margin = score_home - score_away
                    total_goals = score_home + score_away
                    
                    if market_key == "match_result":
                        if outcome == "Draw":
                            if abs(margin) >= 2: probability *= 0.01  # Pierde por 2, imposible empatar
                            elif abs(margin) == 1: probability *= 0.25 # Pierde por 1, castigar empate
                        elif outcome == "Home Win":
                            if margin <= -2: probability *= 0.01
                            elif margin == -1: probability *= 0.35
                            elif margin > 0: probability = min(0.99, probability * 1.5)
                        elif outcome == "Away Win":
                            if margin >= 2: probability *= 0.01
                            elif margin == 1: probability *= 0.35
                            elif margin < 0: probability = min(0.99, probability * 1.5)
                    
                    elif market_key == "over_under_25":
                        if total_goals >= 3:
                            if outcome == "Under 2.5": probability = 0.0
                            if outcome == "Over 2.5": probability = 1.0
                        elif total_goals == 2 and minute > 75:
                            if outcome == "Over 2.5": probability *= 0.5  # Se apaga el over
                    
                    elif market_key == "btts":
                        if score_home > 0 and score_away > 0:
                            if outcome == "BTTS Yes": probability = 1.0
                            if outcome == "BTTS No": probability = 0.0
                        elif minute > 75:
                            if outcome == "BTTS Yes": probability *= 0.3
                            
                # Omitir picks donde ya no hay probabilidad real en live
                if probability < 0.10: continue
                
                if minute > 0:
                    margin = score_home - score_away
                    if market_key == 'match_result':
                        if abs(margin) >= 2 and outcome == 'Draw': probability *= 0.01
                        elif margin <= -2 and outcome == 'Home Win': probability *= 0.01
                        elif margin >= 2 and outcome == 'Away Win': probability *= 0.01
                        elif margin == -1 and outcome == 'Home Win': probability *= 0.3
                        elif margin == 1 and outcome == 'Away Win': probability *= 0.3
                        elif outcome == 'Draw' and abs(margin) == 1: probability *= 0.4
                    elif market_key == 'over_under_25':
                        total = score_home + score_away
                        if total >= 3 and outcome == 'Under 2.5': probability = 0.0
                        elif total >= 3 and outcome == 'Over 2.5': probability = 1.0
                        elif total == 2 and minute > 70 and outcome == 'Over 2.5': probability *= 0.5
                    elif market_key == 'btts':
                        if score_home > 0 and score_away > 0:
                            if outcome == 'BTTS Yes': probability = 1.0
                            if outcome == 'BTTS No': probability = 0.0
                
                if probability < 0.05: continue
                candidates.append(self._candidate(
                    market_key=market_key,
                    market_label=config["market_label"],
                    selection=config["outcomes"].get(outcome, outcome),
                    odds=float(odd),
                    probability=probability,
                    rationale=self._build_core_rationale(
                        market_key,
                        outcome,
                        probability,
                        score_home,
                        score_away,
                        minute,
                    ),
                ))
        return candidates

    def _evaluate_extended_markets(
        self,
        advanced_predictions: Dict[str, Any],
        scraped_odds: Dict[str, Any],
        home_name: str,
        away_name: str,
        home_snapshot: Dict[str, Any],
        away_snapshot: Dict[str, Any],
        h2h: Dict[str, Any],
        is_live: bool,
        minute: int,
        live_stats: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        extended = scraped_odds.get("extended_markets", {})
        if not isinstance(extended, dict):
            return []

        candidates: List[Dict[str, Any]] = []
        for raw_market_name, selections in extended.items():
            if not isinstance(selections, dict):
                continue
            market_text = f"{raw_market_name} {' '.join(map(str, selections.keys()))}"
            parsed = self._classify_extended_market(market_text, home_name, away_name)
            if not parsed:
                continue

            for selection_name, odd in selections.items():
                if odd is None:
                    continue
                selection_parsed = self._parse_selection(
                    raw_market_name,
                    selection_name,
                    parsed["team_scope"],
                )
                line = selection_parsed["line"]
                direction = selection_parsed["direction"]
                if line is None or direction is None:
                    continue

                probability, projected = self._estimate_probability(
                    parsed["market_key"],
                    parsed["team_scope"],
                    line,
                    direction,
                    advanced_predictions,
                    live_stats=live_stats,
                    is_live=is_live,
                    minute=minute,
                )
                if probability is None:
                    continue

                rationale = self._build_extended_rationale(
                    market_key=parsed["market_key"],
                    scope=parsed["team_scope"],
                    direction=direction,
                    line=line,
                    projected=projected,
                    home_name=home_name,
                    away_name=away_name,
                    home_snapshot=home_snapshot,
                    away_snapshot=away_snapshot,
                    h2h=h2h,
                    is_live=is_live,
                    minute=minute,
                    live_stats=live_stats,
                )
                candidates.append(self._candidate(
                    market_key=parsed["market_key"],
                    market_label=raw_market_name,
                    selection=selection_name,
                    odds=float(odd),
                    probability=probability,
                    rationale=rationale,
                ))
        return candidates

    def _evaluate_live_dynamic_markets(
        self,
        base_predictions: Dict[str, Any],
        advanced_predictions: Dict[str, Any],
        scraped_odds: Dict[str, Any],
        home_name: str,
        away_name: str,
        score_home: int,
        score_away: int,
        minute: int,
        live_stats: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        candidates = []
        
        home_prob = base_predictions.get("win_home", 0.33)
        away_prob = base_predictions.get("win_away", 0.33)

        home_attacks = int(live_stats.get("home", {}).get("total_shots", 0))
        away_attacks = int(live_stats.get("away", {}).get("total_shots", 0))

        margin = score_home - score_away
        current_total = score_home + score_away

        # Case 1: Big home favorite losing
        if margin < 0 and home_prob >= 0.50 and home_attacks >= (away_attacks - 3) and minute < 85:
            candidates.append(self._candidate(
                market_key="live_next_goal",
                market_label="Próximo Gol",
                selection=home_name,
                odds=2.00,
                probability=0.75,
                rationale=f"🚨 {home_name} era favorito ({(home_prob*100):.0f}%), va perdiendo pero mantiene presión ofensiva al minuto {minute}. Buscamos que marquen el siguiente gol."
            ))
            candidates.append(self._candidate(
                market_key="live_dnb",
                market_label="DNB - Empate No Acción",
                selection=home_name,
                odds=1.85,
                probability=0.71,
                rationale=f"⭐ Respaldamos la remontada de {home_name} cubriendo el empate."
            ))
            
        # Case 2: Big away favorite losing
        elif margin > 0 and away_prob >= 0.50 and away_attacks >= (home_attacks - 3) and minute < 85:
            candidates.append(self._candidate(
                market_key="live_next_goal",
                market_label="Próximo Gol",
                selection=away_name,
                odds=2.00,
                probability=0.75,
                rationale=f"🚨 {away_name} era favorito ({(away_prob*100):.0f}%), sorprendido {score_home}-{score_away}. Fuerte tendencia por marcar en contexto de desventaja."
            ))
            candidates.append(self._candidate(
                market_key="live_dnb",
                market_label="DNB - Empate No Acción",
                selection=away_name,
                odds=1.85,
                probability=0.71,
                rationale=f"⭐ Empuje visitante de {away_name} al 2do tiempo. Posible remontada."
            ))
            
        # Case 3: Goal fest expected but 0-0
        elif current_total == 0 and minute > 65 and base_predictions.get("btts_yes", 0.5) > 0.65:
            candidates.append(self._candidate(
                market_key="live_over_0_5",
                market_label="Over 0.5 Goles",
                selection="Over",
                odds=1.80,
                probability=0.75,
                rationale=f"📉 Encuentro 0-0 al {minute}' muy por debajo de su valor esperado. Alta propensión al gol, el partido debería abrirse."
            ))

        # Additional Dynamic Stats Markets
        expected_corners = advanced_predictions.get("corners", {}).get("total_corners_predicted", 9)
        expected_sot = advanced_predictions.get("shots", {}).get("total_shots_on_target_predicted", 8)
        
        corners_live = int(live_stats.get("total_corners", 0))
        home_sot_live = int(live_stats.get("home", {}).get("shots_on_target", 0))
        away_sot_live = int(live_stats.get("away", {}).get("shots_on_target", 0))
        home_poss = float(live_stats.get("home", {}).get("possession", 50))
        away_poss = float(live_stats.get("away", {}).get("possession", 50))

        # Case 4: Extreme pressure corners (min 50-80) missing par
        if 50 < minute < 85 and corners_live < (expected_corners * (minute/90) - 2.5) and (home_poss > 65 or away_poss > 65):
            dominator = home_name if home_poss > 65 else away_name
            candidates.append(self._candidate(
                market_key="live_corners_over",
                market_label="Over Corners (Asiático) en Vivo",
                selection="Over Corners",
                odds=1.85,
                probability=0.73,
                rationale=f"🚩 El partido tiene solo {corners_live} corners al {minute}'. La expectativa era {expected_corners:.1f}. Fuerte dominio ({max(home_poss, away_poss)}%) de {dominator}, buscamos valor en Over Corners en LasPlatas."
            ))

        # Case 5: Shots on target domination (min 45-75)
        if 45 < minute < 75:
            if home_poss > 65 and home_sot_live > (away_sot_live + 4) and score_home <= score_away:
                candidates.append(self._candidate(
                    market_key="live_shots_on_target",
                    market_label="Remates al Arco (Match)",
                    selection=f"{home_name} Over Remates al Arco",
                    odds=1.80,
                    probability=0.74,
                    rationale=f"🎯 {home_name} domina ({home_poss}% pos, {home_sot_live} remates). Ideal para atacar línea de Remates al arco (Match) en LasPlatas ya que necesita anotar."
                ))
            elif away_poss > 65 and away_sot_live > (home_sot_live + 4) and score_away <= score_home:
                candidates.append(self._candidate(
                    market_key="live_shots_on_target",
                    market_label="Remates al Arco (Match)",
                    selection=f"{away_name} Over Remates al Arco",
                    odds=1.80,
                    probability=0.74,
                    rationale=f"🎯 {away_name} domina ({away_poss}% pos, {away_sot_live} remates). Ideal para atacar línea de Remates al arco (Match) en LasPlatas ya que necesita anotar."
                ))

        # Case 6: Late Game Cards (min 70-85, tie game, tense)
        if current_total > 0 and margin == 0 and 70 <= minute <= 85:
            candidates.append(self._candidate(
                market_key="live_cards_over",
                market_label="Over Tarjetas / Amonestaciones",
                selection="Over",
                odds=1.90,
                probability=0.70,
                rationale=f"🟨 Empate {score_home}-{score_away} al minuto {minute}'. Tensión altísima, gran spot para Over de amonestaciones o próximo jugador en recibir tarjeta en LasPlatas."
            ))

        return candidates

    def _candidate(
        self,
        market_key: str,
        market_label: str,
        selection: str,
        odds: float,
        probability: float,
        rationale: str,
    ) -> Dict[str, Any]:
        implied = 1.0 / odds if odds > 0 else 0
        edge = probability - implied
        score = (
            edge * 2.4
            + probability
            + self.MARKET_PRIORITY.get(market_key, 0.5) * 0.35
        )
        return {
            "market_key": market_key,
            "market": market_label,
            "selection": selection,
            "odds": round(odds, 3),
            "probability": round(probability, 3),
            "implied_probability": round(implied, 3),
            "edge": round(edge, 3),
            "confidence": self._prob_to_confidence(probability),
            "score": round(score, 3),
            "rationale": rationale,
        }

    def _build_core_rationale(
        self,
        market_key: str,
        outcome: str,
        probability: float,
        score_home: int,
        score_away: int,
        minute: int,
    ) -> str:
        if market_key == "match_result":
            return (
                f"Modelo base proyecta {probability * 100:.1f}% para {outcome}. "
                f"Se mantiene como mercado secundario frente a estadistica avanzada."
            )
        if minute > 0:
            return (
                f"Modelo recalibrado con contexto de partido en {minute}'. "
                f"Probabilidad estimada: {probability * 100:.1f}%."
            )
        return f"Modelo pre-partido proyecta {probability * 100:.1f}% para {outcome}."

    def _build_extended_rationale(
        self,
        market_key: str,
        scope: str,
        direction: str,
        line: float,
        projected: float,
        home_name: str,
        away_name: str,
        home_snapshot: Dict[str, Any],
        away_snapshot: Dict[str, Any],
        h2h: Dict[str, Any],
        is_live: bool,
        minute: int,
        live_stats: Dict[str, Any],
    ) -> str:
        if scope == "home":
            team_text = f"{home_name} como local"
            team_snapshot = home_snapshot
        elif scope == "away":
            team_text = f"{away_name} como visitante"
            team_snapshot = away_snapshot
        else:
            team_text = f"{home_name} vs {away_name}"
            team_snapshot = {}

        parts = [
            f"Proyeccion estadistica: {projected:.1f} vs linea {line:.1f} ({direction.upper()}).",
        ]

        if market_key.startswith("corners"):
            parts.append(
                f"{team_text} promedia {team_snapshot.get('avg_corners', h2h.get('corners_total_avg', 0)):.1f} corners."
            )
            if h2h.get("corners_total_avg"):
                parts.append(f"H2H reciente: {h2h['corners_total_avg']:.1f} corners totales.")
        elif market_key.startswith("cards"):
            parts.append(
                f"Promedio disciplinario: {team_snapshot.get('avg_cards', h2h.get('cards_total_avg', 0)):.1f} tarjetas."
            )
            if h2h.get("cards_total_avg"):
                parts.append(f"H2H reciente: {h2h['cards_total_avg']:.1f} tarjetas totales.")
        elif market_key.startswith("shots_on_target"):
            parts.append(
                f"Remates al arco recientes: {team_snapshot.get('avg_shots_on_target', 0):.1f}."
            )
        elif market_key.startswith("shots_total"):
            parts.append(
                f"Volumen de remate reciente: {team_snapshot.get('avg_shots_total', 0):.1f}."
            )
        elif market_key == "fouls_total":
            parts.append(
                f"Media de faltas combinadas: {(home_snapshot.get('avg_fouls', 0) + away_snapshot.get('avg_fouls', 0)):.1f}."
            )
        elif market_key == "offsides_total":
            parts.append(
                f"Media de offsides combinados: {(home_snapshot.get('avg_offsides', 0) + away_snapshot.get('avg_offsides', 0)):.1f}."
            )

        if is_live and minute > 0 and live_stats:
            live_corner_total = live_stats.get("total_corners")
            live_shots_total = live_stats.get("total_shots")
            if live_corner_total is not None or live_shots_total is not None:
                parts.append(
                    f"Live {minute}': corners={live_corner_total or 0}, remates={live_shots_total or 0}."
                )

        return " ".join(parts)

    def _estimate_probability(
        self,
        market_key: str,
        team_scope: str,
        line: float,
        direction: str,
        advanced_predictions: Dict[str, Any],
        live_stats: Dict[str, Any],
        is_live: bool,
        minute: int,
    ) -> tuple[Optional[float], float]:
        mean_value = 0.0
        std_value = 1.6

        if market_key.startswith("corners"):
            corner_data = advanced_predictions.get("corners", {})
            if team_scope == "home":
                mean_value = float(corner_data.get("home_corners_predicted", 0))
                std_value = 1.5
            elif team_scope == "away":
                mean_value = float(corner_data.get("away_corners_predicted", 0))
                std_value = 1.5
            else:
                mean_value = float(corner_data.get("total_corners_predicted", 0))
                std_value = 2.2
            mean_value = self._blend_live_total(mean_value, market_key, live_stats, is_live, minute)
        elif market_key.startswith("cards"):
            card_data = advanced_predictions.get("cards", {})
            if team_scope == "home":
                mean_value = float(card_data.get("home_yellow_cards_predicted", 0))
                std_value = 1.0
            elif team_scope == "away":
                mean_value = float(card_data.get("away_yellow_cards_predicted", 0))
                std_value = 1.0
            else:
                mean_value = float(card_data.get("total_yellow_cards_predicted", 0))
                std_value = 1.8
        elif market_key.startswith("shots_on_target"):
            shot_data = advanced_predictions.get("shots", {})
            if team_scope == "home":
                mean_value = float(shot_data.get("home_shots_on_target_predicted", 0))
                std_value = 1.2
            elif team_scope == "away":
                mean_value = float(shot_data.get("away_shots_on_target_predicted", 0))
                std_value = 1.2
            else:
                mean_value = float(shot_data.get("total_shots_on_target_predicted", 0))
                std_value = 1.9
            mean_value = self._blend_live_total(mean_value, market_key, live_stats, is_live, minute)
        elif market_key.startswith("shots_total"):
            shot_data = advanced_predictions.get("shots", {})
            if team_scope == "home":
                mean_value = float(shot_data.get("home_shots_total_predicted", 0))
                std_value = 2.2
            elif team_scope == "away":
                mean_value = float(shot_data.get("away_shots_total_predicted", 0))
                std_value = 2.2
            else:
                mean_value = float(shot_data.get("total_shots_predicted", 0))
                std_value = 3.2
            mean_value = self._blend_live_total(mean_value, market_key, live_stats, is_live, minute)
        elif market_key == "goalkeeper_saves_total":
            save_data = advanced_predictions.get("goalkeeper_saves", {})
            mean_value = float(save_data.get("total_saves_predicted", 0))
            std_value = 1.6
        elif market_key == "fouls_total":
            misc = advanced_predictions.get("miscellaneous", {})
            mean_value = float(misc.get("total_fouls_predicted", 0))
            std_value = 3.2
        elif market_key == "offsides_total":
            misc = advanced_predictions.get("miscellaneous", {})
            mean_value = float(misc.get("total_offsides_predicted", 0))
            std_value = 1.4
        else:
            return None, 0.0

        probability = self._tail_probability(mean_value, line, std_value, direction == "over")
        return probability, mean_value

    def _blend_live_total(
        self,
        base_projection: float,
        market_key: str,
        live_stats: Dict[str, Any],
        is_live: bool,
        minute: int,
    ) -> float:
        if not is_live or minute <= 0:
            return base_projection

        if market_key.startswith("corners"):
            current_total = float(live_stats.get("total_corners", 0) or 0)
        elif market_key.startswith("shots"):
            current_total = float(live_stats.get("total_shots", 0) or 0)
        else:
            return base_projection

        if current_total <= 0:
            return base_projection

        projected_from_live = current_total / max(minute, 1) * 95
        weight = min(0.65, max(0.2, minute / 100.0))
        return round(base_projection * (1 - weight) + projected_from_live * weight, 2)

    def _classify_extended_market(
        self,
        market_text: str,
        home_name: str,
        away_name: str,
    ) -> Optional[Dict[str, str]]:
        text = self._normalize_text(market_text)
        if "corner" in text or "corne" in text:
            base_key = "corners"
        elif "tarjeta" in text or "card" in text:
            base_key = "cards"
        elif "remate a puerta" in text or "tiro a puerta" in text or "shot on target" in text:
            base_key = "shots_on_target"
        elif "remate" in text or "tiro" in text or "shot" in text:
            base_key = "shots_total"
        elif "falta" in text or "foul" in text:
            base_key = "fouls_total"
        elif "fuera de juego" in text or "offside" in text:
            base_key = "offsides_total"
        elif "ataj" in text or "save" in text:
            base_key = "goalkeeper_saves_total"
        else:
            return None

        team_scope = "total"
        if self._normalize_text(home_name) in text or "local" in text or "home" in text:
            team_scope = "home"
        elif self._normalize_text(away_name) in text or "visitante" in text or "away" in text:
            team_scope = "away"

        if base_key in ("fouls_total", "offsides_total", "goalkeeper_saves_total"):
            market_key = base_key
        else:
            market_key = f"{base_key}_{team_scope}" if team_scope != "total" else base_key
        return {"market_key": market_key, "team_scope": team_scope}

    def _parse_selection(
        self,
        market_name: str,
        selection_name: str,
        default_scope: str,
    ) -> Dict[str, Any]:
        combined = f"{market_name} {selection_name}"
        normalized = self._normalize_text(combined)

        if any(token in normalized for token in ("mas de", "más de", "over", "supera", "arriba de")):
            direction = "over"
        elif any(token in normalized for token in ("menos de", "under", "debajo de")):
            direction = "under"
        else:
            direction = None

        line = self._extract_line(combined)
        return {
            "direction": direction,
            "line": line,
            "scope": default_scope,
        }

    @staticmethod
    def _extract_line(text: str) -> Optional[float]:
        match = re.search(r"(\d+(?:[.,]\d+)?)", text)
        if not match:
            return None
        return float(match.group(1).replace(",", "."))

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = (text or "").lower()
        text = text.replace("más", "mas")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normal_cdf(z: float) -> float:
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))

    def _tail_probability(self, mean_value: float, line: float, std: float, over: bool = True) -> float:
        z = (line - mean_value) / max(std, 0.5)
        over_prob = 1 - self._normal_cdf(z)
        probability = over_prob if over else (1 - over_prob)
        return max(0.01, min(0.99, float(probability)))

    @staticmethod
    def _prob_to_confidence(probability: float) -> str:
        if probability >= 0.7:
            return "HIGH"
        if probability >= 0.58:
            return "MEDIUM"
        return "LOW"

    def _get_match_id(self, home_id: int, away_id: int) -> Optional[int]:
        match_row = self.db.get_active_match_by_teams(home_id, away_id)
        if match_row:
            return int(match_row["api_id"])
        upcoming = self.db.get_h2h_matches(home_id, away_id, limit=1)
        if upcoming:
            return int(upcoming[0]["api_id"])
        return None
