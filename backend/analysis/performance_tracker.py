"""
Performance Tracker - Tracks prediction accuracy, ROI, and betting performance over time.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))
from data.database import DatabaseManager


class PerformanceTracker:
    """Tracks and analyzes prediction and betting performance."""
    
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
    
    def settle_finished_matches(self):
        """Auto-settle predictions for matches that have finished."""
        conn = self.db.get_connection()
        
        # Get unsettled predictions for finished matches
        unsettled = conn.execute("""
            SELECT p.id, p.match_id, p.market, p.prediction,
                   m.home_goals, m.away_goals, m.status
            FROM predictions p
            JOIN matches m ON p.match_id = m.api_id
            WHERE p.is_correct IS NULL AND m.status = 'FT'
        """).fetchall()
        
        settled_count = 0
        for pred in unsettled:
            pred = dict(pred)
            hg = pred["home_goals"] or 0
            ag = pred["away_goals"] or 0
            
            is_correct = self._check_prediction(
                pred["market"],
                pred["prediction"],
                hg, ag
            )
            
            if is_correct is not None:
                result_str = f"{hg}-{ag}"
                self.db.settle_prediction(pred["id"], result_str, is_correct)
                settled_count += 1
        
        conn.close()
        print(f"✅ Settled {settled_count} predictions")
        return settled_count
    
    def get_dashboard_stats(self, date_filter: Optional[str] = None) -> dict:
        """Get comprehensive stats for the dashboard, optionally filtered by date."""
        conn = self.db.get_connection()
        
        stats = {
            "overview": self._get_overview_stats(conn, date_filter),
            "by_market": self._get_market_stats(conn, date_filter),
            "recent_predictions": self._get_recent_predictions(conn, date_filter=date_filter),
            "value_bet_performance": self._get_value_bet_stats(conn, date_filter),
            "daily_performance": self._get_daily_performance(conn),
            "streak": self._get_current_streak(conn),
            "roi": self._calculate_roi(conn),
        }
        
        conn.close()
        return stats
    
    def _get_overview_stats(self, conn, date_filter: Optional[str] = None) -> dict:
        """Overall prediction statistics."""
        where_clause = "WHERE 1=1"
        params = []
        if date_filter:
            where_clause = "JOIN matches m ON p.match_id = m.api_id WHERE date(m.match_date) = ?"
            params.append(date_filter)

        row = conn.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN is_correct IS NULL THEN 1 ELSE 0 END) as pending,
                ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN CAST(is_correct AS REAL) END) * 100, 1) as accuracy
            FROM predictions p
            {where_clause}
        """, params).fetchone()
        
        return dict(row) if row else {}
    
    def _get_market_stats(self, conn, date_filter: Optional[str] = None) -> List[dict]:
        """Stats broken down by market."""
        rows = conn.execute("""
            SELECT market,
                COUNT(*) as total,
                SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) as losses,
                ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN CAST(is_correct AS REAL) END) * 100, 1) as accuracy,
                SUM(CASE WHEN is_value_bet = 1 THEN 1 ELSE 0 END) as value_bets,
                AVG(probability) as avg_confidence
            FROM predictions
            GROUP BY market
            ORDER BY accuracy DESC
        """).fetchall()
        
        return [dict(r) for r in rows]
    
    def _get_recent_predictions(self, conn, limit: int = 50, date_filter: Optional[str] = None) -> List[dict]:
        """Get the most recent predictions, optionally filtered by date."""
        where_clause = "WHERE 1=1"
        params = []
        if date_filter:
            where_clause = "WHERE date(m.match_date) = ?"
            params.append(date_filter)
        params.append(limit)

        rows = conn.execute(f"""
            SELECT p.*, m.match_date, m.status,
                   ht.name as home_team, at.name as away_team,
                   m.home_goals, m.away_goals,
                   l.name as league
            FROM predictions p
            JOIN matches m ON p.match_id = m.api_id
            JOIN teams ht ON m.home_team_id = ht.api_id
            JOIN teams at ON m.away_team_id = at.api_id
            LEFT JOIN leagues l ON m.league_id = l.api_id
            {where_clause}
            ORDER BY m.match_date ASC
            LIMIT ?
        """, params).fetchall()
        
        return [dict(r) for r in rows]
    
    def _get_value_bet_stats(self, conn, date_filter: Optional[str] = None) -> dict:
        """Value bet specific performance."""
        row = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) as losses,
                ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN CAST(is_correct AS REAL) END) * 100, 1) as accuracy,
                AVG(value_edge) as avg_edge,
                AVG(recommended_stake) as avg_stake
            FROM predictions
            WHERE is_value_bet = 1
        """).fetchone()
        
        return dict(row) if row else {}
    
    def _get_daily_performance(self, conn, days: int = 30) -> List[dict]:
        """Daily performance for charts."""
        rows = conn.execute("""
            SELECT DATE(p.created_at) as date,
                COUNT(*) as total,
                SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as wins,
                ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN CAST(is_correct AS REAL) END) * 100, 1) as accuracy
            FROM predictions p
            WHERE p.created_at >= datetime('now', '-' || ? || ' days')
            AND p.is_correct IS NOT NULL
            GROUP BY DATE(p.created_at)
            ORDER BY date ASC
        """, (days,)).fetchall()
        
        return [dict(r) for r in rows]
    
    def _get_current_streak(self, conn) -> dict:
        """Calculate current winning/losing streak."""
        rows = conn.execute("""
            SELECT is_correct
            FROM predictions
            WHERE is_correct IS NOT NULL
            ORDER BY settled_at DESC
            LIMIT 50
        """).fetchall()
        
        if not rows:
            return {"type": "none", "count": 0}
        
        first_result = rows[0]["is_correct"]
        streak = 0
        for row in rows:
            if row["is_correct"] == first_result:
                streak += 1
            else:
                break
        
        return {
            "type": "winning" if first_result else "losing",
            "count": streak
        }
    
    def _calculate_roi(self, conn, initial_bankroll: float = 1000) -> dict:
        """Calculate Return on Investment."""
        rows = conn.execute("""
            SELECT is_correct, recommended_stake, value_edge
            FROM predictions
            WHERE is_correct IS NOT NULL AND is_value_bet = 1
            ORDER BY settled_at ASC
        """).fetchall()
        
        if not rows:
            return {"roi": 0, "profit": 0, "bankroll": initial_bankroll}
        
        bankroll = initial_bankroll
        total_staked = 0
        
        for row in rows:
            stake_pct = row["recommended_stake"] or 0.02
            stake = bankroll * stake_pct
            total_staked += stake
            
            if row["is_correct"]:
                # Approximate profit using value edge
                profit = stake * (1 + (row["value_edge"] or 0.1))
                bankroll += profit - stake  # Net profit
            else:
                bankroll -= stake
        
        net_profit = bankroll - initial_bankroll
        roi = (net_profit / total_staked * 100) if total_staked > 0 else 0
        
        return {
            "roi": round(roi, 2),
            "profit": round(net_profit, 2),
            "bankroll": round(bankroll, 2),
            "total_staked": round(total_staked, 2),
            "initial_bankroll": initial_bankroll,
        }
    
    def _check_prediction(self, market: str, prediction: str, home_goals: int, away_goals: int) -> Optional[bool]:
        """Check if a prediction was correct."""
        total = home_goals + away_goals
        
        if market == "match_result":
            actual = "Home Win" if home_goals > away_goals else ("Draw" if home_goals == away_goals else "Away Win")
            return prediction == actual
        
        elif market == "over_under_25":
            actual = "Over 2.5" if total > 2.5 else "Under 2.5"
            return prediction == actual
        
        elif market == "btts":
            actual = "BTTS Yes" if home_goals > 0 and away_goals > 0 else "BTTS No"
            return prediction == actual
        
        return None
