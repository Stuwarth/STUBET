"""
Advanced Markets Predictor — Covers ALL statistical betting markets.
Generates predictions for: corners, shots, cards, goalkeeper saves, 
possession, fouls, offsides, and combination markets.
"""
import numpy as np
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import sys
import json
import joblib
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))
from config import MODEL_DIR


class AdvancedMarketPredictor:
    """
    Predicts ALL statistical markets:
    - Total Corners (Over/Under lines)
    - Team Corners (Over/Under per team)  
    - Total Shots on Target
    - Team Shots on Target
    - Total Shots
    - Yellow Cards (Over/Under)
    - Red Cards
    - Goalkeeper Saves
    - Fouls
    - Offsides
    - Possession ranges
    - Combined markets (e.g., corners + cards combos)
    """
    
    # All markets with their typical Over/Under lines
    MARKET_LINES = {
        "corners_total": [7.5, 8.5, 9.5, 10.5, 11.5],
        "corners_home": [3.5, 4.5, 5.5],
        "corners_away": [3.5, 4.5, 5.5],
        "shots_on_target_total": [6.5, 7.5, 8.5, 9.5],
        "shots_on_target_home": [2.5, 3.5, 4.5],
        "shots_on_target_away": [2.5, 3.5, 4.5],
        "shots_total": [18.5, 20.5, 22.5, 24.5],
        "shots_home": [8.5, 10.5, 12.5],
        "shots_away": [8.5, 10.5, 12.5],
        "yellow_cards_total": [2.5, 3.5, 4.5, 5.5],
        "yellow_cards_home": [1.5, 2.5],
        "yellow_cards_away": [1.5, 2.5],
        "fouls_total": [18.5, 20.5, 22.5, 24.5],
        "goalkeeper_saves_total": [6.5, 7.5, 8.5],
        "offsides_total": [3.5, 4.5, 5.5],
    }
    
    def __init__(self, db):
        self.db = db
        self.statistical_models = {}
        self.pattern_cache = {}
    
    def get_team_stat_profile(self, team_id: int, last_n: int = 15) -> Dict:
        """
        Build a comprehensive statistical profile for a team.
        Returns averages, medians, std devs for ALL statistical categories.
        """
        stats = self.db.get_match_stats_for_team(team_id, limit=last_n)
        
        if not stats:
            return self._empty_profile()
        
        profile = {}
        stat_fields = [
            "shots_total", "shots_on_target", "shots_off_target", "shots_blocked",
            "corners", "fouls", "yellow_cards", "red_cards",
            "goalkeeper_saves", "offsides", "possession", "ball_possession",
            "total_passes", "passes_accurate", "pass_accuracy", "expected_goals"
        ]
        
        for field in stat_fields:
            values = [s.get(field, 0) or 0 for s in stats]
            if values:
                profile[f"{field}_avg"] = np.mean(values)
                profile[f"{field}_median"] = np.median(values)
                profile[f"{field}_std"] = np.std(values) if len(values) > 1 else 0
                profile[f"{field}_min"] = min(values)
                profile[f"{field}_max"] = max(values)
                
                # Trend: compare last 5 vs overall
                if len(values) >= 5:
                    recent = values[:5]  # Most recent 5
                    profile[f"{field}_trend"] = np.mean(recent) - np.mean(values)
                    profile[f"{field}_recent_avg"] = np.mean(recent)
                else:
                    profile[f"{field}_trend"] = 0
                    profile[f"{field}_recent_avg"] = np.mean(values)
                
                # Consistency score (lower std/mean = more consistent)
                if np.mean(values) > 0:
                    profile[f"{field}_consistency"] = 1 - min(1, np.std(values) / np.mean(values))
                else:
                    profile[f"{field}_consistency"] = 0
            else:
                for suffix in ["_avg", "_median", "_std", "_min", "_max", "_trend", "_recent_avg", "_consistency"]:
                    profile[f"{field}{suffix}"] = 0
        
        # Calculate over/under rates for each market line
        for market, lines in self.MARKET_LINES.items():
            field = self._market_to_field(market)
            values = [s.get(field, 0) or 0 for s in stats]
            
            for line in lines:
                over_rate = sum(1 for v in values if v > line) / len(values) if values else 0
                profile[f"{market}_over_{line}_rate"] = over_rate
        
        # Home/Away split
        home_stats = [s for s in stats if s.get("home_team_id") == team_id]
        away_stats = [s for s in stats if s.get("away_team_id") == team_id]
        
        for location, loc_stats in [("home", home_stats), ("away", away_stats)]:
            for field in stat_fields:
                values = [s.get(field, 0) or 0 for s in loc_stats]
                profile[f"{field}_{location}_avg"] = np.mean(values) if values else 0
        
        return profile
    
    def predict_match_stats(self, home_id: int, away_id: int) -> Dict:
        """
        Predict ALL statistical markets for a match.
        Uses team profiles, opponent adjustments, and trend analysis.
        """
        home_profile = self.get_team_stat_profile(home_id)
        away_profile = self.get_team_stat_profile(away_id)
        
        # H2H adjustment factor
        h2h_factor = self._get_h2h_stat_factor(home_id, away_id)
        
        predictions = {}
        
        # ============ CORNERS ============
        corners_pred = self._predict_corners(home_profile, away_profile, h2h_factor)
        predictions["corners"] = corners_pred
        
        # ============ SHOTS ============
        shots_pred = self._predict_shots(home_profile, away_profile, h2h_factor)
        predictions["shots"] = shots_pred
        
        # ============ CARDS ============
        cards_pred = self._predict_cards(home_profile, away_profile, h2h_factor)
        predictions["cards"] = cards_pred
        
        # ============ GOALKEEPER SAVES ============
        saves_pred = self._predict_saves(home_profile, away_profile, h2h_factor)
        predictions["goalkeeper_saves"] = saves_pred
        
        # ============ FOULS & OFFSIDES ============
        misc_pred = self._predict_misc(home_profile, away_profile, h2h_factor)
        predictions["miscellaneous"] = misc_pred
        
        # ============ COMBINED MARKETS ============
        combo_pred = self._predict_combos(predictions)
        predictions["combinations"] = combo_pred
        
        return predictions
    
    def _predict_corners(self, home_p: Dict, away_p: Dict, h2h: Dict) -> Dict:
        """Predict corner-related markets."""
        # Base predictions using weighted average (recent form weighted more)
        home_corners_avg = (
            home_p.get("corners_recent_avg", 5) * 0.6 +
            home_p.get("corners_home_avg", 5) * 0.25 +
            home_p.get("corners_avg", 5) * 0.15
        )
        
        away_corners_avg = (
            away_p.get("corners_recent_avg", 4) * 0.6 +
            away_p.get("corners_away_avg", 4) * 0.25 +
            away_p.get("corners_avg", 4) * 0.15
        )
        
        # Opponent adjustment: strong attacking team → more corners conceded
        home_adj = 1 + (away_p.get("shots_total_avg", 12) - 12) * 0.02
        away_adj = 1 + (home_p.get("shots_total_avg", 12) - 12) * 0.02
        
        home_corners_pred = home_corners_avg * home_adj
        away_corners_pred = away_corners_avg * away_adj
        total_corners_pred = home_corners_pred + away_corners_pred
        
        # H2H adjustment
        if h2h.get("corners_avg"):
            total_corners_pred = total_corners_pred * 0.7 + h2h["corners_avg"] * 0.3
        
        result = {
            "home_corners_predicted": round(home_corners_pred, 1),
            "away_corners_predicted": round(away_corners_pred, 1),
            "total_corners_predicted": round(total_corners_pred, 1),
            "over_under_lines": {},
        }
        
        # Calculate probabilities for each line
        std = max(1.5, (home_p.get("corners_std", 2) + away_p.get("corners_std", 2)))
        for line in self.MARKET_LINES["corners_total"]:
            z_score = (line - total_corners_pred) / std
            prob_over = 1 - self._normal_cdf(z_score)
            result["over_under_lines"][f"total_{line}"] = {
                "over_prob": round(prob_over, 3),
                "under_prob": round(1 - prob_over, 3),
                "recommended": "Over" if prob_over > 0.55 else ("Under" if prob_over < 0.45 else "Skip"),
                "confidence": self._prob_to_confidence(max(prob_over, 1 - prob_over)),
            }
        
        # Per-team lines
        for line in self.MARKET_LINES["corners_home"]:
            z_home = (line - home_corners_pred) / max(1, home_p.get("corners_std", 1.5))
            prob_over = 1 - self._normal_cdf(z_home)
            result["over_under_lines"][f"home_{line}"] = {
                "over_prob": round(prob_over, 3),
                "under_prob": round(1 - prob_over, 3),
                "recommended": "Over" if prob_over > 0.55 else ("Under" if prob_over < 0.45 else "Skip"),
            }
        
        for line in self.MARKET_LINES["corners_away"]:
            z_away = (line - away_corners_pred) / max(1, away_p.get("corners_std", 1.5))
            prob_over = 1 - self._normal_cdf(z_away)
            result["over_under_lines"][f"away_{line}"] = {
                "over_prob": round(prob_over, 3),
                "under_prob": round(1 - prob_over, 3),
                "recommended": "Over" if prob_over > 0.55 else ("Under" if prob_over < 0.45 else "Skip"),
            }
        
        return result
    
    def _predict_shots(self, home_p: Dict, away_p: Dict, h2h: Dict) -> Dict:
        """Predict shot-related markets."""
        # Shots on target prediction
        home_sot_avg = home_p.get("shots_on_target_recent_avg", 4) * 0.6 + home_p.get("shots_on_target_avg", 4) * 0.4
        away_sot_avg = away_p.get("shots_on_target_recent_avg", 3) * 0.6 + away_p.get("shots_on_target_avg", 3) * 0.4
        
        # Defensive factor
        home_sot_pred = home_sot_avg * (1 + (50 - away_p.get("possession_avg", 50)) * 0.01)
        away_sot_pred = away_sot_avg * (1 + (50 - home_p.get("possession_avg", 50)) * 0.01)
        
        # Total shots
        home_shots_total = home_p.get("shots_total_recent_avg", 12) * 0.6 + home_p.get("shots_total_avg", 12) * 0.4
        away_shots_total = away_p.get("shots_total_recent_avg", 10) * 0.6 + away_p.get("shots_total_avg", 10) * 0.4
        
        result = {
            "home_shots_on_target_predicted": round(home_sot_pred, 1),
            "away_shots_on_target_predicted": round(away_sot_pred, 1),
            "total_shots_on_target_predicted": round(home_sot_pred + away_sot_pred, 1),
            "home_shots_total_predicted": round(home_shots_total, 1),
            "away_shots_total_predicted": round(away_shots_total, 1),
            "total_shots_predicted": round(home_shots_total + away_shots_total, 1),
            "over_under_lines": {},
        }
        
        # SOT lines
        std_sot = max(1, home_p.get("shots_on_target_std", 1.5) + away_p.get("shots_on_target_std", 1.5))
        total_sot = home_sot_pred + away_sot_pred
        for line in self.MARKET_LINES["shots_on_target_total"]:
            z = (line - total_sot) / std_sot
            prob_over = 1 - self._normal_cdf(z)
            result["over_under_lines"][f"sot_total_{line}"] = {
                "over_prob": round(prob_over, 3),
                "under_prob": round(1 - prob_over, 3),
                "recommended": "Over" if prob_over > 0.55 else ("Under" if prob_over < 0.45 else "Skip"),
            }
        
        # Per-team SOT lines
        for prefix, pred, profile in [("home", home_sot_pred, home_p), ("away", away_sot_pred, away_p)]:
            std = max(0.8, profile.get("shots_on_target_std", 1.2))
            for line in self.MARKET_LINES[f"shots_on_target_{prefix}"]:
                z = (line - pred) / std
                prob_over = 1 - self._normal_cdf(z)
                result["over_under_lines"][f"sot_{prefix}_{line}"] = {
                    "over_prob": round(prob_over, 3),
                    "under_prob": round(1 - prob_over, 3),
                    "recommended": "Over" if prob_over > 0.55 else ("Under" if prob_over < 0.45 else "Skip"),
                }
        
        return result
    
    def _predict_cards(self, home_p: Dict, away_p: Dict, h2h: Dict) -> Dict:
        """Predict card-related markets."""
        home_yc = home_p.get("yellow_cards_recent_avg", 2) * 0.6 + home_p.get("yellow_cards_avg", 2) * 0.4
        away_yc = away_p.get("yellow_cards_recent_avg", 2) * 0.6 + away_p.get("yellow_cards_avg", 2) * 0.4
        
        # Rivalry/intensity adjustment via fouls
        foul_intensity = (home_p.get("fouls_avg", 13) + away_p.get("fouls_avg", 13)) / 26
        home_yc_pred = home_yc * foul_intensity
        away_yc_pred = away_yc * foul_intensity
        
        total_yc = home_yc_pred + away_yc_pred
        
        result = {
            "home_yellow_cards_predicted": round(home_yc_pred, 1),
            "away_yellow_cards_predicted": round(away_yc_pred, 1),
            "total_yellow_cards_predicted": round(total_yc, 1),
            "red_card_probability": min(0.3, (home_p.get("red_cards_avg", 0.05) + away_p.get("red_cards_avg", 0.05))),
            "over_under_lines": {},
        }
        
        std_yc = max(0.8, home_p.get("yellow_cards_std", 1) + away_p.get("yellow_cards_std", 1))
        for line in self.MARKET_LINES["yellow_cards_total"]:
            z = (line - total_yc) / std_yc
            prob_over = 1 - self._normal_cdf(z)
            result["over_under_lines"][f"yc_total_{line}"] = {
                "over_prob": round(prob_over, 3),
                "under_prob": round(1 - prob_over, 3),
                "recommended": "Over" if prob_over > 0.55 else ("Under" if prob_over < 0.45 else "Skip"),
            }
        
        return result
    
    def _predict_saves(self, home_p: Dict, away_p: Dict, h2h: Dict) -> Dict:
        """Predict goalkeeper saves markets."""
        # GK saves correlate with opponent's shots on target
        home_saves = away_p.get("shots_on_target_avg", 4) * 0.7  # ~70% of SOT become saves
        away_saves = home_p.get("shots_on_target_avg", 4) * 0.7
        
        # Adjust for GK quality (historical saves)
        home_gk_factor = home_p.get("goalkeeper_saves_avg", 3) / max(1, home_saves)
        away_gk_factor = away_p.get("goalkeeper_saves_avg", 3) / max(1, away_saves)
        
        home_saves_pred = home_saves * min(1.5, max(0.5, home_gk_factor))
        away_saves_pred = away_saves * min(1.5, max(0.5, away_gk_factor))
        
        result = {
            "home_saves_predicted": round(home_saves_pred, 1),
            "away_saves_predicted": round(away_saves_pred, 1),
            "total_saves_predicted": round(home_saves_pred + away_saves_pred, 1),
            "over_under_lines": {},
        }
        
        total_saves = home_saves_pred + away_saves_pred
        std = max(1, home_p.get("goalkeeper_saves_std", 1.5) + away_p.get("goalkeeper_saves_std", 1.5))
        for line in self.MARKET_LINES["goalkeeper_saves_total"]:
            z = (line - total_saves) / std
            prob_over = 1 - self._normal_cdf(z)
            result["over_under_lines"][f"saves_total_{line}"] = {
                "over_prob": round(prob_over, 3),
                "under_prob": round(1 - prob_over, 3),
                "recommended": "Over" if prob_over > 0.55 else ("Under" if prob_over < 0.45 else "Skip"),
            }
        
        return result
    
    def _predict_misc(self, home_p: Dict, away_p: Dict, h2h: Dict) -> Dict:
        """Predict fouls, offsides, and other markets."""
        home_fouls = home_p.get("fouls_recent_avg", 13) * 0.6 + home_p.get("fouls_avg", 13) * 0.4
        away_fouls = away_p.get("fouls_recent_avg", 13) * 0.6 + away_p.get("fouls_avg", 13) * 0.4
        
        home_offsides = home_p.get("offsides_recent_avg", 2) * 0.6 + home_p.get("offsides_avg", 2) * 0.4
        away_offsides = away_p.get("offsides_recent_avg", 2) * 0.6 + away_p.get("offsides_avg", 2) * 0.4
        
        return {
            "total_fouls_predicted": round(home_fouls + away_fouls, 1),
            "total_offsides_predicted": round(home_offsides + away_offsides, 1),
            "home_possession_predicted": round(
                home_p.get("possession_avg", 50) * 0.5 +
                (100 - away_p.get("possession_avg", 50)) * 0.5, 1
            ),
        }
    
    def _predict_combos(self, predictions: Dict) -> Dict:
        """Generate combined market predictions."""
        corners = predictions.get("corners", {})
        cards = predictions.get("cards", {})
        shots = predictions.get("shots", {})
        
        total_corners = corners.get("total_corners_predicted", 9)
        total_cards = cards.get("total_yellow_cards_predicted", 4)
        total_sot = shots.get("total_shots_on_target_predicted", 7)
        
        return {
            "corners_plus_cards": {
                "total_predicted": round(total_corners + total_cards, 1),
                "over_14_5_prob": round(self._combo_over_prob(total_corners + total_cards, 14.5, 3), 3),
                "over_16_5_prob": round(self._combo_over_prob(total_corners + total_cards, 16.5, 3), 3),
            },
            "corners_plus_shots_on_target": {
                "total_predicted": round(total_corners + total_sot, 1),
            },
            "high_action_game": {
                "probability": round(min(0.95,
                    (1 if total_corners > 10 else 0) * 0.3 +
                    (1 if total_cards > 4 else 0) * 0.2 +
                    (1 if total_sot > 8 else 0) * 0.3 +
                    0.2
                ), 3),
            }
        }
    
    def _get_h2h_stat_factor(self, team1_id: int, team2_id: int) -> Dict:
        """Get H2H statistical factors from previous encounters."""
        h2h_matches = self.db.get_h2h_matches(team1_id, team2_id, limit=5)
        if not h2h_matches:
            return {}
        
        factors = {}
        # Get stats for H2H matches
        corners_total = []
        for match in h2h_matches:
            match_stats = []
            conn = self.db.get_connection()
            rows = conn.execute(
                "SELECT * FROM match_stats WHERE match_id = ?",
                (match["api_id"],)
            ).fetchall()
            conn.close()
            
            total_corners = sum(dict(r).get("corners", 0) for r in rows)
            corners_total.append(total_corners)
        
        if corners_total:
            factors["corners_avg"] = np.mean(corners_total)
        
        return factors
    
    def _market_to_field(self, market: str) -> str:
        """Map market name to database field."""
        mapping = {
            "corners_total": "corners", "corners_home": "corners", "corners_away": "corners",
            "shots_on_target_total": "shots_on_target", "shots_on_target_home": "shots_on_target",
            "shots_on_target_away": "shots_on_target",
            "shots_total": "shots_total", "shots_home": "shots_total", "shots_away": "shots_total",
            "yellow_cards_total": "yellow_cards", "yellow_cards_home": "yellow_cards",
            "yellow_cards_away": "yellow_cards",
            "fouls_total": "fouls",
            "goalkeeper_saves_total": "goalkeeper_saves",
            "offsides_total": "offsides",
        }
        return mapping.get(market, market)
    
    @staticmethod
    def _normal_cdf(z: float) -> float:
        """Approximate the normal CDF."""
        import math
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))
    
    @staticmethod
    def _prob_to_confidence(prob: float) -> str:
        if prob >= 0.70:
            return "HIGH"
        elif prob >= 0.58:
            return "MEDIUM"
        return "LOW"
    
    @staticmethod
    def _combo_over_prob(predicted: float, line: float, std: float) -> float:
        import math
        z = (line - predicted) / max(0.5, std)
        return 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
    
    @staticmethod
    def _empty_profile() -> Dict:
        return {}
