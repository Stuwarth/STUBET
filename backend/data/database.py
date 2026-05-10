"""
Database Manager - SQLite operations for storing match data, stats, odds, and predictions.
"""
import sqlite3
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional
import re
import unicodedata
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import DB_PATH


class DatabaseManager:
    """Manages all database operations for the Sports AI Predictor."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DB_PATH)
        self.init_db()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn
    
    def init_db(self):
        """Initialize database tables."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Teams table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY,
                api_id INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                short_name TEXT,
                country TEXT,
                logo_url TEXT,
                venue_name TEXT,
                venue_capacity INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Leagues table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leagues (
                id INTEGER PRIMARY KEY,
                api_id INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                country TEXT,
                logo_url TEXT,
                season INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Matches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY,
                api_id INTEGER UNIQUE NOT NULL,
                league_id INTEGER,
                season INTEGER,
                round TEXT,
                match_date TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'NS',
                home_team_id INTEGER NOT NULL,
                away_team_id INTEGER NOT NULL,
                home_goals INTEGER,
                away_goals INTEGER,
                home_goals_ht INTEGER,
                away_goals_ht INTEGER,
                referee TEXT,
                venue TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (home_team_id) REFERENCES teams(api_id),
                FOREIGN KEY (away_team_id) REFERENCES teams(api_id),
                FOREIGN KEY (league_id) REFERENCES leagues(api_id)
            )
        """)
        
        # Match Statistics table (detailed stats per match per team)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS match_stats (
                id INTEGER PRIMARY KEY,
                match_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                shots_total INTEGER DEFAULT 0,
                shots_on_target INTEGER DEFAULT 0,
                shots_off_target INTEGER DEFAULT 0,
                shots_blocked INTEGER DEFAULT 0,
                possession REAL DEFAULT 0,
                corners INTEGER DEFAULT 0,
                offsides INTEGER DEFAULT 0,
                fouls INTEGER DEFAULT 0,
                yellow_cards INTEGER DEFAULT 0,
                red_cards INTEGER DEFAULT 0,
                goalkeeper_saves INTEGER DEFAULT 0,
                total_passes INTEGER DEFAULT 0,
                passes_accurate INTEGER DEFAULT 0,
                pass_accuracy REAL DEFAULT 0,
                expected_goals REAL,
                ball_possession REAL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(match_id, team_id),
                FOREIGN KEY (match_id) REFERENCES matches(api_id),
                FOREIGN KEY (team_id) REFERENCES teams(api_id)
            )
        """)
        
        # Odds table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS odds (
                id INTEGER PRIMARY KEY,
                match_id INTEGER NOT NULL,
                bookmaker TEXT NOT NULL,
                market TEXT NOT NULL,
                selection TEXT NOT NULL,
                odds_value REAL NOT NULL,
                implied_probability REAL,
                is_opening INTEGER DEFAULT 0,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(api_id)
            )
        """)
        
        # Predictions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY,
                match_id INTEGER NOT NULL,
                market TEXT NOT NULL,
                prediction TEXT NOT NULL,
                probability REAL NOT NULL,
                confidence TEXT,
                model_version TEXT,
                is_value_bet INTEGER DEFAULT 0,
                value_edge REAL,
                recommended_stake REAL,
                rationale TEXT,
                result TEXT,
                is_correct INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settled_at TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(api_id)
            )
        """)

        # Add rationale column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE predictions ADD COLUMN rationale TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Performance tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance_log (
                id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                market TEXT NOT NULL,
                total_predictions INTEGER DEFAULT 0,
                correct_predictions INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0,
                total_value_bets INTEGER DEFAULT 0,
                value_bets_won INTEGER DEFAULT 0,
                roi REAL DEFAULT 0,
                profit_loss REAL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # H2H cache
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS h2h_cache (
                id INTEGER PRIMARY KEY,
                team1_id INTEGER NOT NULL,
                team2_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(team1_id, team2_id)
            )
        """)

        # SofaScore teams table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sofascore_teams (
                id INTEGER PRIMARY KEY,
                sofascore_id INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                short_name TEXT,
                country TEXT,
                gender TEXT,
                sport TEXT,
                raw_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # SofaScore matches table (normalized event snapshot)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sofascore_matches (
                id INTEGER PRIMARY KEY,
                event_id INTEGER UNIQUE NOT NULL,
                start_timestamp INTEGER,
                match_date TIMESTAMP,
                status_code INTEGER,
                status_type TEXT,
                status_description TEXT,
                league_name TEXT,
                league_slug TEXT,
                category_name TEXT,
                category_slug TEXT,
                season_name TEXT,
                round_info TEXT,
                home_team_id INTEGER NOT NULL,
                away_team_id INTEGER NOT NULL,
                home_team_name TEXT,
                away_team_name TEXT,
                home_score INTEGER,
                away_score INTEGER,
                home_score_ht INTEGER,
                away_score_ht INTEGER,
                winner_code INTEGER,
                has_xg INTEGER DEFAULT 0,
                has_player_stats INTEGER DEFAULT 0,
                raw_event_json TEXT,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (home_team_id) REFERENCES sofascore_teams(sofascore_id),
                FOREIGN KEY (away_team_id) REFERENCES sofascore_teams(sofascore_id)
            )
        """)

        # SofaScore payload table (lineups/incidents/statistics/graph/details)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sofascore_payloads (
                id INTEGER PRIMARY KEY,
                event_id INTEGER NOT NULL,
                payload_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_id, payload_type),
                FOREIGN KEY (event_id) REFERENCES sofascore_matches(event_id)
            )
        """)

        # SofaScore Match Lineups table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sofascore_lineups (
                match_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                player_slug TEXT,
                player_short_name TEXT,
                player_position TEXT,
                jersey_number INTEGER,
                is_substitute BOOLEAN DEFAULT FALSE,
                captain BOOLEAN DEFAULT FALSE,
                statistics JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (match_id, team_id, player_id)
            )
        """)

        # ----------------------------------------------------
        # NEW TABLES FOR STUBET BANKROLL & MANUAL PICKS
        # ----------------------------------------------------
        
        # Bankroll Monthly Settings (per bookmaker)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bankroll_months (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month_year TEXT NOT NULL, -- e.g. "2026-05"
                bookmaker TEXT NOT NULL DEFAULT 'lasplatas', -- lasplatas, metabet
                starting_bankroll REAL NOT NULL,
                current_bankroll REAL NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(month_year, bookmaker)
            )
        """)

        # Manual Picks (Cupón & Formulario)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month_year TEXT NOT NULL, -- Link to bankroll_months
                bookmaker TEXT NOT NULL DEFAULT 'lasplatas', -- lasplatas, metabet
                ticket_id TEXT, -- Si vino de un cupón/link
                match_name TEXT NOT NULL,
                market TEXT NOT NULL,
                odds REAL NOT NULL,
                stake REAL NOT NULL,
                result TEXT DEFAULT 'PENDING', -- PENDING, WON, LOST
                profit REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Rebuild bankroll_months with proper UNIQUE(month_year, bookmaker)
        # SQLite doesn't support ALTER TABLE to change constraints, so we rebuild
        try:
            # Check the actual table schema SQL to see if UNIQUE includes bookmaker
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bankroll_months'")
            row = cursor.fetchone()
            needs_rebuild = False
            
            if row:
                create_sql = row[0] or ""
                # If the schema doesn't have UNIQUE(month_year, bookmaker), rebuild
                if "bookmaker" not in create_sql or "UNIQUE(month_year, bookmaker)" not in create_sql.replace(" ", ""):
                    needs_rebuild = True
            
            if needs_rebuild and row:
                cursor.execute("ALTER TABLE bankroll_months RENAME TO bankroll_months_old")
                cursor.execute("""
                    CREATE TABLE bankroll_months (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        month_year TEXT NOT NULL,
                        bookmaker TEXT NOT NULL DEFAULT 'lasplatas',
                        starting_bankroll REAL NOT NULL,
                        current_bankroll REAL NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(month_year, bookmaker)
                    )
                """)
                # Check if old table had bookmaker column
                cursor.execute("PRAGMA table_info(bankroll_months_old)")
                old_cols = [col[1] for col in cursor.fetchall()]
                
                if 'bookmaker' in old_cols:
                    cursor.execute("""
                        INSERT OR IGNORE INTO bankroll_months (month_year, bookmaker, starting_bankroll, current_bankroll, updated_at)
                        SELECT month_year, COALESCE(bookmaker, 'lasplatas'), starting_bankroll, current_bankroll, updated_at
                        FROM bankroll_months_old
                    """)
                else:
                    cursor.execute("""
                        INSERT INTO bankroll_months (month_year, bookmaker, starting_bankroll, current_bankroll, updated_at)
                        SELECT month_year, 'lasplatas', starting_bankroll, current_bankroll, updated_at
                        FROM bankroll_months_old
                    """)
                cursor.execute("DROP TABLE bankroll_months_old")
                conn.commit()
                print("[DB Migration] bankroll_months rebuilt with UNIQUE(month_year, bookmaker)")
        except Exception as e:
            print(f"[DB Migration] bankroll_months: {e}")
        
        # Migration: add bookmaker column to manual_picks if missing
        try:
            cursor.execute("PRAGMA table_info(manual_picks)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'bookmaker' not in columns:
                cursor.execute("ALTER TABLE manual_picks ADD COLUMN bookmaker TEXT DEFAULT 'lasplatas'")
                conn.commit()
                print("[DB Migration] manual_picks: added bookmaker column")
        except Exception as e:
            print(f"[DB Migration] manual_picks: {e}")
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(home_team_id, away_team_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league_id, season)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_match_stats_match ON match_stats(match_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_odds_match ON odds(match_id, market)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sofascore_matches_date ON sofascore_matches(start_timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sofascore_matches_teams ON sofascore_matches(home_team_id, away_team_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sofascore_matches_status ON sofascore_matches(status_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sofascore_payloads_event_type ON sofascore_payloads(event_id, payload_type)")
        
        conn.commit()
        conn.close()
    
    # ==================== TEAM OPERATIONS ====================
    
    def upsert_team(self, team_data: dict):
        """Insert or update a team."""
        conn = self.get_connection()
        conn.execute("""
            INSERT INTO teams (api_id, name, short_name, country, logo_url, venue_name, venue_capacity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(api_id) DO UPDATE SET
                name=excluded.name,
                short_name=excluded.short_name,
                country=excluded.country,
                logo_url=excluded.logo_url,
                venue_name=excluded.venue_name,
                venue_capacity=excluded.venue_capacity,
                updated_at=CURRENT_TIMESTAMP
        """, (
            team_data.get("api_id"),
            team_data.get("name"),
            team_data.get("short_name"),
            team_data.get("country"),
            team_data.get("logo_url"),
            team_data.get("venue_name"),
            team_data.get("venue_capacity"),
        ))
        conn.commit()
        conn.close()

    def upsert_league(self, league_data: dict):
        """Insert or update a league."""
        conn = self.get_connection()
        conn.execute("""
            INSERT INTO leagues (api_id, name, country, logo_url, season)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(api_id) DO UPDATE SET
                name=excluded.name,
                country=excluded.country,
                logo_url=excluded.logo_url,
                season=excluded.season,
                updated_at=CURRENT_TIMESTAMP
        """, (
            league_data.get("api_id"),
            league_data.get("name"),
            league_data.get("country"),
            league_data.get("logo_url"),
            league_data.get("season"),
        ))
        conn.commit()
        conn.close()
    
    # ==================== MATCH OPERATIONS ====================
    
    def upsert_match(self, match_data: dict):
        """Insert or update a match."""
        conn = self.get_connection()
        conn.execute("""
            INSERT INTO matches (api_id, league_id, season, round, match_date, status,
                home_team_id, away_team_id, home_goals, away_goals,
                home_goals_ht, away_goals_ht, referee, venue)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(api_id) DO UPDATE SET
                status=excluded.status,
                home_goals=excluded.home_goals,
                away_goals=excluded.away_goals,
                home_goals_ht=excluded.home_goals_ht,
                away_goals_ht=excluded.away_goals_ht,
                referee=excluded.referee,
                updated_at=CURRENT_TIMESTAMP
        """, (
            match_data.get("api_id"),
            match_data.get("league_id"),
            match_data.get("season"),
            match_data.get("round"),
            match_data.get("match_date"),
            match_data.get("status"),
            match_data.get("home_team_id"),
            match_data.get("away_team_id"),
            match_data.get("home_goals"),
            match_data.get("away_goals"),
            match_data.get("home_goals_ht"),
            match_data.get("away_goals_ht"),
            match_data.get("referee"),
            match_data.get("venue"),
        ))
        conn.commit()
        conn.close()
    
    def upsert_match_stats(self, stats_data: dict):
        """Insert or update match statistics."""
        conn = self.get_connection()
        conn.execute("""
            INSERT INTO match_stats (match_id, team_id, shots_total, shots_on_target,
                shots_off_target, shots_blocked, possession, corners, offsides, fouls,
                yellow_cards, red_cards, goalkeeper_saves, total_passes, passes_accurate,
                pass_accuracy, expected_goals, ball_possession)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id, team_id) DO UPDATE SET
                shots_total=excluded.shots_total,
                shots_on_target=excluded.shots_on_target,
                shots_off_target=excluded.shots_off_target,
                shots_blocked=excluded.shots_blocked,
                possession=excluded.possession,
                corners=excluded.corners,
                offsides=excluded.offsides,
                fouls=excluded.fouls,
                yellow_cards=excluded.yellow_cards,
                red_cards=excluded.red_cards,
                goalkeeper_saves=excluded.goalkeeper_saves,
                total_passes=excluded.total_passes,
                passes_accurate=excluded.passes_accurate,
                pass_accuracy=excluded.pass_accuracy,
                expected_goals=excluded.expected_goals,
                ball_possession=excluded.ball_possession,
                updated_at=CURRENT_TIMESTAMP
        """, (
            stats_data.get("match_id"),
            stats_data.get("team_id"),
            stats_data.get("shots_total", 0),
            stats_data.get("shots_on_target", 0),
            stats_data.get("shots_off_target", 0),
            stats_data.get("shots_blocked", 0),
            stats_data.get("possession", 0),
            stats_data.get("corners", 0),
            stats_data.get("offsides", 0),
            stats_data.get("fouls", 0),
            stats_data.get("yellow_cards", 0),
            stats_data.get("red_cards", 0),
            stats_data.get("goalkeeper_saves", 0),
            stats_data.get("total_passes", 0),
            stats_data.get("passes_accurate", 0),
            stats_data.get("pass_accuracy", 0),
            stats_data.get("expected_goals"),
            stats_data.get("ball_possession", 0),
        ))
        conn.commit()
        conn.close()

    # ==================== SOFASCORE HISTORICAL OPS ====================

    def upsert_sofascore_team(self, team_data: dict):
        """Insert or update a SofaScore team snapshot."""
        raw_team = team_data.get("raw_json", {})
        raw_team_json = raw_team if isinstance(raw_team, str) else json.dumps(raw_team)

        conn = self.get_connection()
        conn.execute("""
            INSERT INTO sofascore_teams (sofascore_id, name, short_name, country, gender, sport, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sofascore_id) DO UPDATE SET
                name=excluded.name,
                short_name=excluded.short_name,
                country=excluded.country,
                gender=excluded.gender,
                sport=excluded.sport,
                raw_json=excluded.raw_json,
                updated_at=CURRENT_TIMESTAMP
        """, (
            team_data.get("sofascore_id"),
            team_data.get("name"),
            team_data.get("short_name"),
            team_data.get("country"),
            team_data.get("gender"),
            team_data.get("sport"),
            raw_team_json,
        ))
        conn.commit()
        conn.close()

    def upsert_sofascore_match(self, match_data: dict):
        """Insert or update a normalized SofaScore event snapshot."""
        raw_event = match_data.get("raw_event_json", {})
        raw_event_json = raw_event if isinstance(raw_event, str) else json.dumps(raw_event)

        conn = self.get_connection()
        conn.execute("""
            INSERT INTO sofascore_matches (
                event_id, start_timestamp, match_date, status_code, status_type, status_description,
                league_name, league_slug, category_name, category_slug, season_name, round_info,
                home_team_id, away_team_id, home_team_name, away_team_name,
                home_score, away_score, home_score_ht, away_score_ht,
                winner_code, has_xg, has_player_stats, raw_event_json, collected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(event_id) DO UPDATE SET
                start_timestamp=excluded.start_timestamp,
                match_date=excluded.match_date,
                status_code=excluded.status_code,
                status_type=excluded.status_type,
                status_description=excluded.status_description,
                league_name=excluded.league_name,
                league_slug=excluded.league_slug,
                category_name=excluded.category_name,
                category_slug=excluded.category_slug,
                season_name=excluded.season_name,
                round_info=excluded.round_info,
                home_team_id=excluded.home_team_id,
                away_team_id=excluded.away_team_id,
                home_team_name=excluded.home_team_name,
                away_team_name=excluded.away_team_name,
                home_score=excluded.home_score,
                away_score=excluded.away_score,
                home_score_ht=excluded.home_score_ht,
                away_score_ht=excluded.away_score_ht,
                winner_code=excluded.winner_code,
                has_xg=excluded.has_xg,
                has_player_stats=excluded.has_player_stats,
                raw_event_json=excluded.raw_event_json,
                updated_at=CURRENT_TIMESTAMP
        """, (
            match_data.get("event_id"),
            match_data.get("start_timestamp"),
            match_data.get("match_date"),
            match_data.get("status_code"),
            match_data.get("status_type"),
            match_data.get("status_description"),
            match_data.get("league_name"),
            match_data.get("league_slug"),
            match_data.get("category_name"),
            match_data.get("category_slug"),
            match_data.get("season_name"),
            match_data.get("round_info"),
            match_data.get("home_team_id"),
            match_data.get("away_team_id"),
            match_data.get("home_team_name"),
            match_data.get("away_team_name"),
            match_data.get("home_score"),
            match_data.get("away_score"),
            match_data.get("home_score_ht"),
            match_data.get("away_score_ht"),
            match_data.get("winner_code"),
            1 if match_data.get("has_xg") else 0,
            1 if match_data.get("has_player_stats") else 0,
            raw_event_json,
        ))
        conn.commit()
        conn.close()

    def upsert_sofascore_payload(self, event_id: int, payload_type: str, payload: dict):
        """Insert or update raw SofaScore payloads per event and payload type."""
        payload_json = payload if isinstance(payload, str) else json.dumps(payload)
        payload_hash = hashlib.md5(payload_json.encode("utf-8")).hexdigest()

        conn = self.get_connection()
        conn.execute("""
            INSERT INTO sofascore_payloads (event_id, payload_type, payload_json, payload_hash)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(event_id, payload_type) DO UPDATE SET
                payload_json=excluded.payload_json,
                payload_hash=excluded.payload_hash,
                fetched_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
        """, (event_id, payload_type, payload_json, payload_hash))
        conn.commit()
        conn.close()

    def get_sofascore_team_matches(self, team_id: int, limit: int = 10):
        """Get last finished SofaScore matches for a team."""
        conn = self.get_connection()
        rows = conn.execute("""
            SELECT event_id, start_timestamp, match_date, status_code, status_type, status_description,
                   league_name, season_name, round_info,
                   home_team_id, away_team_id, home_team_name, away_team_name,
                   home_score, away_score, home_score_ht, away_score_ht,
                   winner_code, has_xg, has_player_stats
            FROM sofascore_matches
            WHERE LOWER(COALESCE(status_type, '')) = 'finished'
              AND (home_team_id = ? OR away_team_id = ?)
            ORDER BY COALESCE(start_timestamp, 0) DESC
            LIMIT ?
        """, (team_id, team_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_sofascore_h2h_matches(self, team1_id: int, team2_id: int, limit: int = 10):
        """Get last finished SofaScore H2H matches for two teams."""
        conn = self.get_connection()
        rows = conn.execute("""
            SELECT event_id, start_timestamp, match_date, status_code, status_type, status_description,
                   league_name, season_name, round_info,
                   home_team_id, away_team_id, home_team_name, away_team_name,
                   home_score, away_score, home_score_ht, away_score_ht,
                   winner_code, has_xg, has_player_stats
            FROM sofascore_matches
            WHERE LOWER(COALESCE(status_type, '')) = 'finished'
              AND ((home_team_id = ? AND away_team_id = ?) OR
                   (home_team_id = ? AND away_team_id = ?))
            ORDER BY COALESCE(start_timestamp, 0) DESC
            LIMIT ?
        """, (team1_id, team2_id, team2_id, team1_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_sofascore_payload(self, event_id: int, payload_type: Optional[str] = None):
        """Get stored SofaScore payloads for an event."""
        conn = self.get_connection()
        if payload_type:
            rows = conn.execute("""
                SELECT event_id, payload_type, payload_json, payload_hash, fetched_at
                FROM sofascore_payloads
                WHERE event_id = ? AND payload_type = ?
                ORDER BY fetched_at DESC
            """, (event_id, payload_type)).fetchall()
        else:
            rows = conn.execute("""
                SELECT event_id, payload_type, payload_json, payload_hash, fetched_at
                FROM sofascore_payloads
                WHERE event_id = ?
                ORDER BY payload_type ASC
            """, (event_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    # ==================== ODDS OPERATIONS ====================
    
    def insert_odds(self, odds_data: dict):
        """Insert odds data."""
        conn = self.get_connection()
        implied_prob = 1.0 / odds_data.get("odds_value", 1) if odds_data.get("odds_value", 0) > 0 else 0
        conn.execute("""
            INSERT INTO odds (match_id, bookmaker, market, selection, odds_value, implied_probability, is_opening)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            odds_data.get("match_id"),
            odds_data.get("bookmaker"),
            odds_data.get("market"),
            odds_data.get("selection"),
            odds_data.get("odds_value"),
            implied_prob,
            odds_data.get("is_opening", 0),
        ))
        conn.commit()
        conn.close()
    
    # ==================== PREDICTION OPERATIONS ====================
    
    def save_prediction(self, pred_data: dict):
        """Save a prediction."""
        conn = self.get_connection()
        conn.execute("""
            INSERT INTO predictions (match_id, market, prediction, probability, confidence,
                model_version, is_value_bet, value_edge, recommended_stake, rationale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pred_data.get("match_id"),
            pred_data.get("market"),
            pred_data.get("prediction"),
            pred_data.get("probability"),
            pred_data.get("confidence"),
            pred_data.get("model_version"),
            pred_data.get("is_value_bet", 0),
            pred_data.get("value_edge", 0),
            pred_data.get("recommended_stake", 0),
            pred_data.get("rationale", ""),
        ))
        conn.commit()
        conn.close()
    
    def settle_prediction(self, prediction_id: int, result: str, is_correct: bool):
        """Settle a prediction with its result."""
        conn = self.get_connection()
        conn.execute("""
            UPDATE predictions SET result=?, is_correct=?, settled_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (result, 1 if is_correct else 0, prediction_id))
        conn.commit()
        conn.close()
    
    # ==================== QUERY OPERATIONS ====================
    
    def get_team_matches(self, team_id: int, limit: int = 20, home_only: bool = False, away_only: bool = False):
        """Get recent matches for a team."""
        conn = self.get_connection()
        query = """
            SELECT m.*, 
                   ht.name as home_team_name, at.name as away_team_name
            FROM matches m
            JOIN teams ht ON m.home_team_id = ht.api_id
            JOIN teams at ON m.away_team_id = at.api_id
            WHERE m.status IN ('FT', 'AET', 'PEN')
        """
        params = []
        
        if home_only:
            query += " AND m.home_team_id = ?"
            params.append(team_id)
        elif away_only:
            query += " AND m.away_team_id = ?"
            params.append(team_id)
        else:
            query += " AND (m.home_team_id = ? OR m.away_team_id = ?)"
            params.extend([team_id, team_id])
        
        query += " ORDER BY m.match_date DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_h2h_matches(self, team1_id: int, team2_id: int, limit: int = 10):
        """Get head-to-head matches between two teams."""
        conn = self.get_connection()
        rows = conn.execute("""
            SELECT m.*, ht.name as home_team_name, at.name as away_team_name
            FROM matches m
            JOIN teams ht ON m.home_team_id = ht.api_id
            JOIN teams at ON m.away_team_id = at.api_id
            WHERE m.status IN ('FT', 'AET', 'PEN')
            AND ((m.home_team_id = ? AND m.away_team_id = ?) OR 
                 (m.home_team_id = ? AND m.away_team_id = ?))
            ORDER BY m.match_date DESC LIMIT ?
        """, (team1_id, team2_id, team2_id, team1_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_match_stats_for_team(self, team_id: int, limit: int = 20):
        """Get match stats for a team's recent matches."""
        conn = self.get_connection()
        rows = conn.execute("""
            SELECT ms.*, m.match_date, m.home_team_id, m.away_team_id,
                   m.home_goals, m.away_goals
            FROM match_stats ms
            JOIN matches m ON ms.match_id = m.api_id
            WHERE ms.team_id = ? AND m.status IN ('FT', 'AET', 'PEN')
            ORDER BY m.match_date DESC LIMIT ?
        """, (team_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_upcoming_matches(self, league_id: Optional[int] = None, days_ahead: int = 7):
        """Get upcoming matches."""
        conn = self.get_connection()
        query = """
            SELECT m.*, l.name as league_name, l.country as league_country,
                   ht.name as home_team_name, ht.logo_url as home_logo,
                   at.name as away_team_name, at.logo_url as away_logo
            FROM matches m
            JOIN teams ht ON m.home_team_id = ht.api_id
            JOIN teams at ON m.away_team_id = at.api_id
            LEFT JOIN leagues l ON m.league_id = l.api_id
            WHERE m.status = 'NS'
            AND date(m.match_date, 'localtime') BETWEEN date('now', 'localtime') AND date('now', 'localtime', '+' || ? || ' days')
        """
        params = [days_ahead]
        
        if league_id:
            query += " AND m.league_id = ?"
            params.append(league_id)
        
        query += " ORDER BY m.match_date ASC"
        
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def find_team(self, team_name: str):
        """Find a team by exact or fuzzy-normalized name."""
        def normalize_name(value: str) -> str:
            ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
            return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()

        normalized = normalize_name(team_name)
        if not normalized:
            return None

        variants = {normalized}
        without_common_tokens = re.sub(r"\b(fc|cf|ac|cd|sc|club)\b", " ", normalized)
        without_common_tokens = re.sub(r"\s+", " ", without_common_tokens).strip()
        if without_common_tokens:
            variants.add(without_common_tokens)

        for token in ("fc ", "cf ", "ac ", "cd ", "sc "):
            if normalized.startswith(token):
                variants.add(normalized[len(token):].strip())

        conn = self.get_connection()
        rows = conn.execute("""
            SELECT api_id, name, short_name, country, logo_url
            FROM teams
        """).fetchall()
        conn.close()

        candidates = [dict(row) for row in rows]
        for row in candidates:
            row_name = normalize_name(row.get("name") or "")
            short_name = normalize_name(row.get("short_name") or "")
            if row_name in variants or (short_name and short_name in variants):
                return row

        for row in candidates:
            row_name = normalize_name(row.get("name") or "")
            short_name = normalize_name(row.get("short_name") or "")
            if any(v and (v in row_name or row_name in v or (short_name and (v in short_name or short_name in v))) for v in variants):
                return row
        return None

    def get_active_match_by_teams(self, home_team_id: int, away_team_id: int):
        """Return the live or next match for a pair of teams."""
        conn = self.get_connection()
        row = conn.execute("""
            SELECT *
            FROM matches
            WHERE home_team_id = ? AND away_team_id = ?
              AND status NOT IN ('FT', 'AET', 'PEN', 'CANC', 'PST')
            ORDER BY CASE
                WHEN status IN ('1H', 'HT', '2H', 'ET', 'LIVE') THEN 0
                ELSE 1
            END,
            match_date ASC
            LIMIT 1
        """, (home_team_id, away_team_id)).fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_predictions_with_matches(self, market: Optional[str] = None, only_value: bool = False,
                                      only_unsettled: bool = True, date_filter: Optional[str] = None):
        """Get predictions with match info."""
        conn = self.get_connection()
        query = """
            SELECT p.*, m.match_date, m.home_goals, m.away_goals, m.status,
                   ht.name as home_team_name, at.name as away_team_name,
                   l.name as league_name
            FROM predictions p
            JOIN matches m ON p.match_id = m.api_id
            JOIN teams ht ON m.home_team_id = ht.api_id
            JOIN teams at ON m.away_team_id = at.api_id
            LEFT JOIN leagues l ON m.league_id = l.api_id
            WHERE 1=1
        """
        params = []
        
        if market:
            query += " AND p.market = ?"
            params.append(market)
        
        if only_value:
            query += " AND p.is_value_bet = 1"
        
        if only_unsettled:
            query += " AND p.is_correct IS NULL"
            
        if date_filter:
            query += " AND date(m.match_date, 'localtime') = ?"
            params.append(date_filter)
        
        query += " ORDER BY m.match_date ASC"
        
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_performance_summary(self):
        """Get overall prediction performance."""
        conn = self.get_connection()
        rows = conn.execute("""
            SELECT market,
                   COUNT(*) as total,
                   SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct,
                   ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN is_correct END) * 100, 1) as accuracy,
                   SUM(CASE WHEN is_value_bet = 1 THEN 1 ELSE 0 END) as value_bets,
                   SUM(CASE WHEN is_value_bet = 1 AND is_correct = 1 THEN 1 ELSE 0 END) as value_wins
            FROM predictions
            WHERE is_correct IS NOT NULL
            GROUP BY market
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_stats_summary(self):
        """Get database statistics summary."""
        conn = self.get_connection()
        result = {}
        result["total_teams"] = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
        result["total_matches"] = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        result["finished_matches"] = conn.execute("SELECT COUNT(*) FROM matches WHERE status IN ('FT', 'AET', 'PEN')").fetchone()[0]
        result["upcoming_matches"] = conn.execute("SELECT COUNT(*) FROM matches WHERE status='NS'").fetchone()[0]
        result["total_predictions"] = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        result["settled_predictions"] = conn.execute("SELECT COUNT(*) FROM predictions WHERE is_correct IS NOT NULL").fetchone()[0]
        result["total_odds"] = conn.execute("SELECT COUNT(*) FROM odds").fetchone()[0]
        result["total_stats"] = conn.execute("SELECT COUNT(*) FROM match_stats").fetchone()[0]
        result["sofascore_teams"] = conn.execute("SELECT COUNT(*) FROM sofascore_teams").fetchone()[0]
        result["sofascore_matches"] = conn.execute("SELECT COUNT(*) FROM sofascore_matches").fetchone()[0]
        result["sofascore_payloads"] = conn.execute("SELECT COUNT(*) FROM sofascore_payloads").fetchone()[0]
        conn.close()
        return result
    
    def get_all_teams(self):
        """Returns all teams in the database for fuzzy matching."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT api_id, name, short_name, country, logo_url
                    FROM teams
                """)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error getting all teams: {e}")
            return []

    # ----------------------------------------------------
    # BANKROLL & MANUAL PICKS API
    # ----------------------------------------------------
    
    def set_bankroll(self, month_year: str, starting_bank: float, bookmaker: str = 'lasplatas'):
        """Sets the initial bankroll for a specific month and bookmaker."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Check if exists
        cursor.execute("SELECT starting_bankroll FROM bankroll_months WHERE month_year = ? AND bookmaker = ?", (month_year, bookmaker))
        row = cursor.fetchone()
        
        if row:
            cursor.execute("UPDATE bankroll_months SET starting_bankroll = ?, current_bankroll = ?, updated_at = CURRENT_TIMESTAMP WHERE month_year = ? AND bookmaker = ?", (starting_bank, starting_bank, month_year, bookmaker))
        else:
            cursor.execute("INSERT INTO bankroll_months (month_year, bookmaker, starting_bankroll, current_bankroll) VALUES (?, ?, ?, ?)", (month_year, bookmaker, starting_bank, starting_bank))
        
        conn.commit()
        return True

    def get_bankroll(self, month_year: str, bookmaker: str = None) -> dict:
        """Get bankroll details for a specific month. If bookmaker is None, returns all."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if bookmaker:
            cursor.execute("SELECT starting_bankroll, current_bankroll, bookmaker FROM bankroll_months WHERE month_year = ? AND bookmaker = ?", (month_year, bookmaker))
            row = cursor.fetchone()
            if row:
                return {"starting": row[0], "current": row[1], "bookmaker": row[2]}
            return {"starting": 0, "current": 0, "bookmaker": bookmaker}
        else:
            # Return all bookmakers for this month
            cursor.execute("SELECT starting_bankroll, current_bankroll, bookmaker FROM bankroll_months WHERE month_year = ? ORDER BY bookmaker", (month_year,))
            rows = cursor.fetchall()
            result = {}
            for r in rows:
                result[r[2]] = {"starting": r[0], "current": r[1]}
            return result

    def add_manual_pick(self, pick_data: dict) -> int:
        """Adds a manual pick or ticket to the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        bk = pick_data.get('bookmaker', 'lasplatas')
        placed_at = pick_data.get('placed_at')
        
        if placed_at:
            cursor.execute("""
                INSERT INTO manual_picks (month_year, bookmaker, ticket_id, match_name, market, odds, stake, result, profit, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 0.0, ?)
            """, (
                pick_data.get('month_year'),
                bk,
                pick_data.get('ticket_id'),
                pick_data.get('match_name'),
                pick_data.get('market'),
                pick_data.get('odds'),
                pick_data.get('stake'),
                placed_at
            ))
        else:
            cursor.execute("""
                INSERT INTO manual_picks (month_year, bookmaker, ticket_id, match_name, market, odds, stake, result, profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 0.0)
            """, (
                pick_data.get('month_year'),
                bk,
                pick_data.get('ticket_id'),
                pick_data.get('match_name'),
                pick_data.get('market'),
                pick_data.get('odds'),
                pick_data.get('stake')
            ))
        conn.commit()
        
        # Deduct stake from the correct bookmaker's bankroll
        cursor.execute("""
            UPDATE bankroll_months 
            SET current_bankroll = current_bankroll - ? 
            WHERE month_year = ? AND bookmaker = ?
        """, (pick_data.get('stake'), pick_data.get('month_year'), bk))
        conn.commit()
        
        return cursor.lastrowid

    def get_manual_picks(self, month_year: str, bookmaker: str = None) -> list:
        """Get manual picks for a month, optionally filtered by bookmaker."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if bookmaker:
            cursor.execute("SELECT id, match_name, market, odds, stake, result, profit, created_at, ticket_id, bookmaker FROM manual_picks WHERE month_year = ? AND bookmaker = ? ORDER BY created_at DESC", (month_year, bookmaker))
        else:
            cursor.execute("SELECT id, match_name, market, odds, stake, result, profit, created_at, ticket_id, bookmaker FROM manual_picks WHERE month_year = ? ORDER BY created_at DESC", (month_year,))
        rows = cursor.fetchall()
        
        picks = []
        for r in rows:
            picks.append({
                "id": r[0],
                "match": r[1],
                "market": r[2],
                "odds": r[3],
                "stake": r[4],
                "result": r[5],
                "profit": r[6],
                "date": r[7],
                "ticket_id": r[8],
                "bookmaker": r[9] if len(r) > 9 else 'lasplatas'
            })
        return picks

    def get_manual_picks_by_date(self, date_str: str, bookmaker: str = None) -> list:
        """Get manual picks for a specific day (created_at like 'YYYY-MM-DD%')."""
        conn = self.get_connection()
        cursor = conn.cursor()
        date_pattern = f"{date_str}%"
        if bookmaker:
            cursor.execute("SELECT id, match_name, market, odds, stake, result, profit, created_at, ticket_id, bookmaker FROM manual_picks WHERE created_at LIKE ? AND bookmaker = ? ORDER BY created_at DESC", (date_pattern, bookmaker))
        else:
            cursor.execute("SELECT id, match_name, market, odds, stake, result, profit, created_at, ticket_id, bookmaker FROM manual_picks WHERE created_at LIKE ? ORDER BY created_at DESC", (date_pattern,))
        rows = cursor.fetchall()
        
        picks = []
        for r in rows:
            picks.append({
                "id": r[0], "match": r[1], "market": r[2], "odds": r[3], "stake": r[4],
                "result": r[5], "profit": r[6], "date": r[7], "ticket_id": r[8],
                "bookmaker": r[9] if len(r) > 9 else 'lasplatas'
            })
        return picks

    def get_pending_picks(self) -> list:
        """Returns all pending manual picks."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, match_name, market, created_at, odds, stake, bookmaker FROM manual_picks WHERE result = 'PENDING'")
        rows = cursor.fetchall()
        return [{
            "id": r[0], "match": r[1], "market": r[2], "date": r[3],
            "odds": r[4], "stake": r[5], "bookmaker": r[6]
        } for r in rows]

    def settle_manual_pick(self, pick_id: int, result: str) -> bool:
        """Settles a manual pick as WON or LOST and updates the bankroll."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT stake, odds, month_year, result, bookmaker FROM manual_picks WHERE id = ?", (pick_id,))
        row = cursor.fetchone()
        if not row:
            return False
            
        stake, odds, month_year, current_result = row[0], row[1], row[2], row[3]
        bk = row[4] if len(row) > 4 else 'lasplatas'
        
        if current_result != 'PENDING':
            return False # Already settled
            
        profit = 0.0
        if result == 'WON':
            profit = stake * odds - stake
            # Add stake back + profit
            cursor.execute("UPDATE bankroll_months SET current_bankroll = current_bankroll + ? + ? WHERE month_year = ? AND bookmaker = ?", (stake, profit, month_year, bk))
        elif result == 'LOST':
            profit = -stake
            # Bankroll already deducted stake when bet was placed, so no bankroll change on loss
        else:
            return False
            
        cursor.execute("UPDATE manual_picks SET result = ?, profit = ? WHERE id = ?", (result, profit, pick_id))
        conn.commit()
        return True

    def delete_manual_pick(self, pick_id: int) -> bool:
        """Deletes a manual pick and refunds the stake to the correct bookmaker's bankroll."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Obtener el stake, mes y bookmaker para reembolsarlo
        cursor.execute("SELECT stake, month_year, result, profit, bookmaker FROM manual_picks WHERE id = ?", (pick_id,))
        row = cursor.fetchone()
        if not row:
            return False
            
        stake, month_year, result, profit = row[0], row[1], row[2], row[3]
        bk = row[4] if len(row) > 4 else 'lasplatas'
        
        # Devolver el stake al bankroll correcto
        if result == 'PENDING':
            refund = stake
        elif result == 'WON':
            refund = -profit - stake
        else:
            refund = stake
            
        cursor.execute("UPDATE bankroll_months SET current_bankroll = current_bankroll + ? WHERE month_year = ? AND bookmaker = ?", (refund, month_year, bk))
        
        # Borrar el pick
        cursor.execute("DELETE FROM manual_picks WHERE id = ?", (pick_id,))
        conn.commit()
        return True

    def get_manual_pick(self, pick_id: int) -> dict:
        """Get a single manual pick by ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, match_name, market, odds, stake, result, profit, created_at, ticket_id, bookmaker FROM manual_picks WHERE id = ?", (pick_id,))
        r = cursor.fetchone()
        if not r:
            return None
        return {
            "id": r[0],
            "match": r[1],
            "market": r[2],
            "odds": r[3],
            "stake": r[4],
            "result": r[5],
            "profit": r[6],
            "date": r[7],
            "ticket_id": r[8],
            "bookmaker": r[9] if len(r) > 9 else 'lasplatas'
        }

    def update_manual_pick(self, pick_id: int, pick_data: dict) -> bool:
        """Updates a manual pick and adjusts bankroll if stake or bookmaker changed."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get old data
        cursor.execute("SELECT stake, month_year, bookmaker, result FROM manual_picks WHERE id = ?", (pick_id,))
        row = cursor.fetchone()
        if not row:
            return False
            
        old_stake, month_year, old_bk, result = row
        
        if result != 'PENDING':
            return False # Cannot edit settled picks for now
            
        new_stake = pick_data.get('stake', old_stake)
        new_bk = pick_data.get('bookmaker', old_bk)
        
        # Adjust bankroll
        if old_bk == new_bk:
            if float(old_stake) != float(new_stake):
                diff = float(old_stake) - float(new_stake)
                cursor.execute("UPDATE bankroll_months SET current_bankroll = current_bankroll + ? WHERE month_year = ? AND bookmaker = ?", (diff, month_year, old_bk))
        else:
            # Refund old, deduct new
            cursor.execute("UPDATE bankroll_months SET current_bankroll = current_bankroll + ? WHERE month_year = ? AND bookmaker = ?", (float(old_stake), month_year, old_bk))
            cursor.execute("UPDATE bankroll_months SET current_bankroll = current_bankroll - ? WHERE month_year = ? AND bookmaker = ?", (float(new_stake), month_year, new_bk))
            
        # Update pick
        cursor.execute("""
            UPDATE manual_picks 
            SET match_name = ?, market = ?, odds = ?, stake = ?, created_at = ?, bookmaker = ?
            WHERE id = ?
        """, (
            pick_data.get('match_name'),
            pick_data.get('market'),
            pick_data.get('odds'),
            new_stake,
            pick_data.get('placed_at'),
            new_bk,
            pick_id
        ))
        
        conn.commit()
        return True
