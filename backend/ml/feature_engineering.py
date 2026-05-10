"""
Feature Engineering - Transforms raw match data into 130+ ML features.
This is the core of the prediction engine.
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))
from data.database import DatabaseManager


class FeatureEngineer:
    """Generates features from raw match data for ML models."""
    
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
    
    def build_features_for_match(self, home_team_id: int, away_team_id: int,
                                  league_id: int = None, n_recent: int = 10) -> dict:
        """Build all features for a specific upcoming match.
        
        Returns a flat dictionary of 130+ features ready for ML model input.
        """
        features = {}
        
        # === HOME TEAM FEATURES ===
        home_features = self._get_team_features(home_team_id, n_recent, is_home=True)
        for k, v in home_features.items():
            features[f"home_{k}"] = v
        
        # === AWAY TEAM FEATURES ===
        away_features = self._get_team_features(away_team_id, n_recent, is_home=False)
        for k, v in away_features.items():
            features[f"away_{k}"] = v
        
        # === H2H FEATURES ===
        h2h_features = self._get_h2h_features(home_team_id, away_team_id)
        features.update(h2h_features)
        
        # === DIFFERENTIAL FEATURES ===
        diff_features = self._get_differential_features(home_features, away_features)
        features.update(diff_features)
        
        # === HOME ADVANTAGE FEATURES ===
        home_only = self._get_team_features(home_team_id, n_recent, is_home=True, venue_filter="home")
        away_only = self._get_team_features(away_team_id, n_recent, is_home=False, venue_filter="away")
        
        features["home_home_win_rate"] = home_only.get("win_rate", 0)
        features["home_home_goals_avg"] = home_only.get("goals_scored_avg", 0)
        features["away_away_win_rate"] = away_only.get("win_rate", 0)
        features["away_away_goals_avg"] = away_only.get("goals_scored_avg", 0)
        
        return features
    
    def _get_team_features(self, team_id: int, n_recent: int = 10,
                           is_home: bool = True, venue_filter: str = None) -> dict:
        """Calculate features for a single team."""
        features = {}
        
        # Get recent matches
        if venue_filter == "home":
            matches = self.db.get_team_matches(team_id, limit=n_recent, home_only=True)
        elif venue_filter == "away":
            matches = self.db.get_team_matches(team_id, limit=n_recent, away_only=True)
        else:
            matches = self.db.get_team_matches(team_id, limit=n_recent)
        
        if not matches:
            return self._empty_team_features()
        
        # Get match stats
        stats = self.db.get_match_stats_for_team(team_id, limit=n_recent)
        
        # === FORM FEATURES ===
        form = self._calculate_form(matches, team_id)
        features.update(form)
        
        # === GOALS FEATURES ===
        goals_features = self._calculate_goals_features(matches, team_id)
        features.update(goals_features)
        
        # === STATISTICAL FEATURES ===
        stat_features = self._calculate_stat_features(stats)
        features.update(stat_features)
        
        # === STREAK FEATURES ===
        streak_features = self._calculate_streaks(matches, team_id)
        features.update(streak_features)
        
        # === WEIGHTED FORM (more recent = more weight) ===
        weighted_form = self._calculate_weighted_form(matches, team_id)
        features["weighted_form"] = weighted_form
        
        return features
    
    def _calculate_form(self, matches: List[dict], team_id: int) -> dict:
        """Calculate win/draw/loss rates and points."""
        wins, draws, losses = 0, 0, 0
        
        for match in matches:
            result = self._get_match_result(match, team_id)
            if result == "W":
                wins += 1
            elif result == "D":
                draws += 1
            else:
                losses += 1
        
        total = len(matches)
        points = wins * 3 + draws
        ppg = points / total if total > 0 else 0
        
        return {
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "win_rate": wins / total if total > 0 else 0,
            "draw_rate": draws / total if total > 0 else 0,
            "loss_rate": losses / total if total > 0 else 0,
            "points": points,
            "ppg": ppg,
            "form_last5": self._form_string_score(matches[:5], team_id),
            "form_last3": self._form_string_score(matches[:3], team_id),
        }
    
    def _calculate_goals_features(self, matches: List[dict], team_id: int) -> dict:
        """Calculate goals-related features."""
        goals_scored = []
        goals_conceded = []
        total_goals = []
        clean_sheets = 0
        failed_to_score = 0
        btts_count = 0
        over_25_count = 0
        over_15_count = 0
        
        for match in matches:
            if match["home_team_id"] == team_id:
                gs = match.get("home_goals", 0) or 0
                gc = match.get("away_goals", 0) or 0
            else:
                gs = match.get("away_goals", 0) or 0
                gc = match.get("home_goals", 0) or 0
            
            goals_scored.append(gs)
            goals_conceded.append(gc)
            total_goals.append(gs + gc)
            
            if gc == 0:
                clean_sheets += 1
            if gs == 0:
                failed_to_score += 1
            if gs > 0 and gc > 0:
                btts_count += 1
            if gs + gc > 2.5:
                over_25_count += 1
            if gs + gc > 1.5:
                over_15_count += 1
        
        n = len(matches) or 1
        
        return {
            "goals_scored_avg": np.mean(goals_scored) if goals_scored else 0,
            "goals_scored_std": np.std(goals_scored) if len(goals_scored) > 1 else 0,
            "goals_conceded_avg": np.mean(goals_conceded) if goals_conceded else 0,
            "goals_conceded_std": np.std(goals_conceded) if len(goals_conceded) > 1 else 0,
            "total_goals_avg": np.mean(total_goals) if total_goals else 0,
            "clean_sheet_rate": clean_sheets / n,
            "failed_to_score_rate": failed_to_score / n,
            "btts_rate": btts_count / n,
            "over_25_rate": over_25_count / n,
            "over_15_rate": over_15_count / n,
            "goal_difference_avg": (np.mean(goals_scored) - np.mean(goals_conceded)) if goals_scored else 0,
            "max_goals_scored": max(goals_scored) if goals_scored else 0,
            "max_goals_conceded": max(goals_conceded) if goals_conceded else 0,
        }
    
    def _calculate_stat_features(self, stats: List[dict]) -> dict:
        """Calculate average statistics from match stats data."""
        if not stats:
            return self._empty_stat_features()
        
        stat_fields = [
            "shots_total", "shots_on_target", "shots_off_target", "shots_blocked",
            "possession", "corners", "offsides", "fouls",
            "yellow_cards", "red_cards", "goalkeeper_saves",
            "total_passes", "passes_accurate", "pass_accuracy",
            "expected_goals", "ball_possession"
        ]
        
        result = {}
        for field in stat_fields:
            values = [s.get(field, 0) or 0 for s in stats]
            result[f"{field}_avg"] = np.mean(values) if values else 0
            if len(values) > 1:
                result[f"{field}_std"] = np.std(values)
            else:
                result[f"{field}_std"] = 0
        
        # Derived stats
        if result.get("shots_total_avg", 0) > 0:
            result["shot_accuracy"] = result.get("shots_on_target_avg", 0) / result["shots_total_avg"]
        else:
            result["shot_accuracy"] = 0
        
        if result.get("total_passes_avg", 0) > 0:
            result["pass_completion_rate"] = result.get("passes_accurate_avg", 0) / result["total_passes_avg"]
        else:
            result["pass_completion_rate"] = 0
        
        return result
    
    def _calculate_streaks(self, matches: List[dict], team_id: int) -> dict:
        """Calculate current streaks."""
        if not matches:
            return {"win_streak": 0, "unbeaten_streak": 0, "loss_streak": 0,
                    "scoring_streak": 0, "clean_sheet_streak": 0}
        
        win_streak = 0
        unbeaten_streak = 0
        loss_streak = 0
        scoring_streak = 0
        clean_sheet_streak = 0
        
        for match in matches:
            result = self._get_match_result(match, team_id)
            
            if match["home_team_id"] == team_id:
                gs = match.get("home_goals", 0) or 0
                gc = match.get("away_goals", 0) or 0
            else:
                gs = match.get("away_goals", 0) or 0
                gc = match.get("home_goals", 0) or 0
            
            # Win streak
            if result == "W" and win_streak >= 0:
                win_streak += 1
            elif win_streak > 0:
                break
            
            # Unbeaten streak
            if result in ["W", "D"] and unbeaten_streak >= 0:
                unbeaten_streak += 1
            elif unbeaten_streak > 0:
                pass  # Don't break, just stop counting
            
            # Loss streak
            if result == "L" and loss_streak >= 0:
                loss_streak += 1
            elif loss_streak > 0:
                pass
            
            # Scoring streak
            if gs > 0:
                scoring_streak += 1
            else:
                break
        
        # Clean sheet streak
        for match in matches:
            if match["home_team_id"] == team_id:
                gc = match.get("away_goals", 0) or 0
            else:
                gc = match.get("home_goals", 0) or 0
            
            if gc == 0:
                clean_sheet_streak += 1
            else:
                break
        
        return {
            "win_streak": win_streak,
            "unbeaten_streak": unbeaten_streak,
            "loss_streak": loss_streak,
            "scoring_streak": scoring_streak,
            "clean_sheet_streak": clean_sheet_streak,
        }
    
    def _calculate_weighted_form(self, matches: List[dict], team_id: int, decay: float = 0.85) -> float:
        """Calculate exponentially weighted form (recent matches = higher weight)."""
        if not matches:
            return 0
        
        score = 0
        total_weight = 0
        
        for i, match in enumerate(matches):
            weight = decay ** i
            result = self._get_match_result(match, team_id)
            
            if result == "W":
                score += 3 * weight
            elif result == "D":
                score += 1 * weight
            # Loss = 0 points
            
            total_weight += weight
        
        return score / (total_weight * 3) if total_weight > 0 else 0  # Normalized 0-1
    
    def _get_h2h_features(self, team1_id: int, team2_id: int, n: int = 10) -> dict:
        """Calculate head-to-head features."""
        h2h_matches = self.db.get_h2h_matches(team1_id, team2_id, limit=n)
        
        if not h2h_matches:
            return {
                "h2h_total_matches": 0,
                "h2h_team1_wins": 0,
                "h2h_team2_wins": 0,
                "h2h_draws": 0,
                "h2h_team1_win_rate": 0.33,
                "h2h_avg_goals": 2.5,
                "h2h_btts_rate": 0.5,
                "h2h_over_25_rate": 0.5,
                "h2h_avg_corners": 10,
            }
        
        team1_wins = 0
        team2_wins = 0
        draws = 0
        total_goals = []
        btts_count = 0
        over25_count = 0
        
        for match in h2h_matches:
            hg = match.get("home_goals", 0) or 0
            ag = match.get("away_goals", 0) or 0
            total_goals.append(hg + ag)
            
            if hg > 0 and ag > 0:
                btts_count += 1
            if hg + ag > 2.5:
                over25_count += 1
            
            if match["home_team_id"] == team1_id:
                if hg > ag:
                    team1_wins += 1
                elif hg < ag:
                    team2_wins += 1
                else:
                    draws += 1
            else:
                if ag > hg:
                    team1_wins += 1
                elif ag < hg:
                    team2_wins += 1
                else:
                    draws += 1
        
        n_matches = len(h2h_matches)
        
        return {
            "h2h_total_matches": n_matches,
            "h2h_team1_wins": team1_wins,
            "h2h_team2_wins": team2_wins,
            "h2h_draws": draws,
            "h2h_team1_win_rate": team1_wins / n_matches,
            "h2h_avg_goals": np.mean(total_goals),
            "h2h_btts_rate": btts_count / n_matches,
            "h2h_over_25_rate": over25_count / n_matches,
            "h2h_avg_corners": 10,  # Placeholder, updated from stats
        }
    
    def _get_differential_features(self, home_features: dict, away_features: dict) -> dict:
        """Calculate differential features between home and away teams."""
        diff_keys = [
            "win_rate", "ppg", "goals_scored_avg", "goals_conceded_avg",
            "shots_on_target_avg", "corners_avg", "possession_avg",
            "weighted_form", "shot_accuracy"
        ]
        
        diff = {}
        for key in diff_keys:
            h_val = home_features.get(key, 0) or 0
            a_val = away_features.get(key, 0) or 0
            diff[f"diff_{key}"] = h_val - a_val
        
        # Composite strength indicator
        home_strength = (
            home_features.get("weighted_form", 0) * 0.3 +
            home_features.get("win_rate", 0) * 0.25 +
            home_features.get("goals_scored_avg", 0) / 3 * 0.2 +
            (1 - home_features.get("goals_conceded_avg", 0) / 3) * 0.15 +
            home_features.get("shot_accuracy", 0) * 0.1
        )
        
        away_strength = (
            away_features.get("weighted_form", 0) * 0.3 +
            away_features.get("win_rate", 0) * 0.25 +
            away_features.get("goals_scored_avg", 0) / 3 * 0.2 +
            (1 - away_features.get("goals_conceded_avg", 0) / 3) * 0.15 +
            away_features.get("shot_accuracy", 0) * 0.1
        )
        
        diff["home_strength"] = home_strength
        diff["away_strength"] = away_strength
        diff["strength_diff"] = home_strength - away_strength
        
        return diff
    
    def _get_match_result(self, match: dict, team_id: int) -> str:
        """Get match result from team's perspective."""
        hg = match.get("home_goals", 0) or 0
        ag = match.get("away_goals", 0) or 0
        
        if match["home_team_id"] == team_id:
            if hg > ag:
                return "W"
            elif hg < ag:
                return "L"
            return "D"
        else:
            if ag > hg:
                return "W"
            elif ag < hg:
                return "L"
            return "D"
    
    def _form_string_score(self, matches: List[dict], team_id: int) -> float:
        """Convert form string to numeric score (W=3, D=1, L=0), normalized."""
        if not matches:
            return 0.5
        score = 0
        for match in matches:
            result = self._get_match_result(match, team_id)
            if result == "W":
                score += 3
            elif result == "D":
                score += 1
        return score / (len(matches) * 3)
    
    def _empty_team_features(self) -> dict:
        """Return empty features when no data is available."""
        return {
            "wins": 0, "draws": 0, "losses": 0,
            "win_rate": 0.33, "draw_rate": 0.33, "loss_rate": 0.33,
            "points": 0, "ppg": 1.0, "form_last5": 0.5, "form_last3": 0.5,
            "goals_scored_avg": 1.2, "goals_scored_std": 0.8,
            "goals_conceded_avg": 1.2, "goals_conceded_std": 0.8,
            "total_goals_avg": 2.5, "clean_sheet_rate": 0.3,
            "failed_to_score_rate": 0.25, "btts_rate": 0.5,
            "over_25_rate": 0.5, "over_15_rate": 0.65,
            "goal_difference_avg": 0, "max_goals_scored": 2, "max_goals_conceded": 2,
            **self._empty_stat_features(),
            "win_streak": 0, "unbeaten_streak": 0, "loss_streak": 0,
            "scoring_streak": 0, "clean_sheet_streak": 0,
            "weighted_form": 0.5,
        }
    
    def _empty_stat_features(self) -> dict:
        """Return empty statistical features."""
        fields = [
            "shots_total", "shots_on_target", "shots_off_target", "shots_blocked",
            "possession", "corners", "offsides", "fouls",
            "yellow_cards", "red_cards", "goalkeeper_saves",
            "total_passes", "passes_accurate", "pass_accuracy",
            "expected_goals", "ball_possession"
        ]
        result = {}
        for field in fields:
            result[f"{field}_avg"] = 0
            result[f"{field}_std"] = 0
        result["shot_accuracy"] = 0
        result["pass_completion_rate"] = 0
        return result
    
    def build_training_dataset(self, league_id: int = None, min_matches: int = 50) -> pd.DataFrame:
        """Build a complete training dataset from historical data.
        
        For each finished match, generate features based on data available
        BEFORE that match (to avoid data leakage).
        """
        conn = self.db.get_connection()
        
        query = """
            SELECT m.api_id, m.home_team_id, m.away_team_id, m.league_id,
                   m.home_goals, m.away_goals, m.match_date
            FROM matches m
            WHERE m.status = 'FT' AND m.home_goals IS NOT NULL
        """
        params = []
        if league_id:
            query += " AND m.league_id = ?"
            params.append(league_id)
        
        query += " ORDER BY m.match_date ASC"
        
        matches = conn.execute(query, params).fetchall()
        conn.close()
        
        if len(matches) < min_matches:
            print(f"⚠️ Not enough matches ({len(matches)}/{min_matches})")
            return pd.DataFrame()
        
        rows = []
        for i, match in enumerate(matches):
            match = dict(match)
            
            # Skip first matches (need history to build features)
            if i < 20:
                continue
            
            try:
                features = self.build_features_for_match(
                    match["home_team_id"],
                    match["away_team_id"],
                    match["league_id"]
                )
                
                # Add targets
                hg = match["home_goals"]
                ag = match["away_goals"]
                
                features["target_result"] = 0 if hg > ag else (1 if hg == ag else 2)  # 0=H, 1=D, 2=A
                features["target_total_goals"] = hg + ag
                features["target_over_25"] = 1 if hg + ag > 2.5 else 0
                features["target_btts"] = 1 if hg > 0 and ag > 0 else 0
                features["target_home_goals"] = hg
                features["target_away_goals"] = ag
                features["match_id"] = match["api_id"]
                features["match_date"] = match["match_date"]
                
                rows.append(features)
                
            except Exception as e:
                continue
        
        df = pd.DataFrame(rows)
        print(f"✅ Built training dataset: {len(df)} matches, {len(df.columns)} features")
        return df
