"""
Football API Collector - Integrates with API-Football (api-sports.io)
Collects: matches, team stats, H2H, standings, fixtures, and detailed match statistics.
"""
import httpx
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config import FOOTBALL_API_BASE, SUPPORTED_LEAGUES, RAW_DATA_DIR, get_setting, is_configured
from data.database import DatabaseManager


class FootballAPICollector:
    """Collects football data from API-Football."""
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.base_url = FOOTBALL_API_BASE
        self.headers = {}
        self._refresh_headers()
        
        self.db = db or DatabaseManager()
        self.rate_limit_remaining = 100
        self.cache_dir = RAW_DATA_DIR / "api_cache"
        self.cache_dir.mkdir(exist_ok=True)

    def _refresh_headers(self):
        api_key = get_setting("FOOTBALL_API_KEY", "")
        self.headers = {
            "x-apisports-key": api_key,
            "x-apisports-host": "v3.football.api-sports.io"
        }

    def _is_ready(self) -> bool:
        self._refresh_headers()
        return is_configured(self.headers.get("x-apisports-key", ""))
    
    def _request(self, endpoint: str, params: dict = None) -> dict:
        """Make API request with rate limiting and caching."""
        if not self._is_ready():
            print("[API Error] FOOTBALL_API_KEY is not configured")
            return {"response": [], "errors": "FOOTBALL_API_KEY is not configured"}

        cache_key = f"{endpoint}_{json.dumps(params or {}, sort_keys=True)}"
        cache_file = self.cache_dir / f"{hash(cache_key)}.json"
        
        # Check cache (valid for 1 hour)
        if cache_file.exists():
            cache_age = time.time() - cache_file.stat().st_mtime
            if cache_age < 3600:  # 1 hour cache
                with open(cache_file) as f:
                    return json.load(f)
        
        # Rate limiting
        if self.rate_limit_remaining <= 0:
            print("⚠️ Rate limit reached. Waiting 60 seconds...")
            time.sleep(60)
        
        url = f"{self.base_url}/{endpoint}"
        
        try:
            response = httpx.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Update rate limit
            self.rate_limit_remaining = int(response.headers.get("x-ratelimit-requests-remaining", 100))
            
            # Cache response
            with open(cache_file, 'w') as f:
                json.dump(data, f)
            
            return data
            
        except httpx.HTTPError as e:
            print(f"[API Error] {e}")
            return {"response": [], "errors": str(e)}
    
    def collect_fixtures(self, league_id: int, season: int, from_date: str = None, to_date: str = None):
        """Collect fixtures/matches for a league and season."""
        params = {"league": league_id, "season": season}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        
        data = self._request("fixtures", params)
        fixtures = data.get("response", [])
        
        for fixture in fixtures:
            self._process_fixture(fixture, league_id, season)
        
        print(f"✅ Collected {len(fixtures)} fixtures for league {league_id}")
        return fixtures
    
    def collect_fixture_stats(self, fixture_id: int):
        """Collect detailed statistics for a specific match."""
        data = self._request("fixtures/statistics", {"fixture": fixture_id})
        stats_list = data.get("response", [])
        
        if not stats_list:
            # Prevent infinite re-fetching if API has no stats for this match
            conn = self.db.get_connection()
            match = conn.execute("SELECT home_team_id, away_team_id FROM matches WHERE api_id = ?", (fixture_id,)).fetchone()
            conn.close()
            if match:
                for t_id in [match[0], match[1]]:
                    self.db.upsert_match_stats({"match_id": fixture_id, "team_id": t_id, "shots_total": 0, "shots_on_target": 0, "corners": 0, "yellow_cards": 0})
            return []

        for team_stats in stats_list:
            self._process_match_stats(fixture_id, team_stats)

        return stats_list

    def collect_h2h(self, team1_id: int, team2_id: int, last: int = 10):
        """Collect head-to-head data between two teams."""
        h2h_str = f"{team1_id}-{team2_id}"
        data = self._request("fixtures/headtohead", {"h2h": h2h_str})
        h2h_fixtures = self._sort_fixtures(data.get("response", []))[:last]
        
        for fixture in h2h_fixtures:
            league_id = fixture.get("league", {}).get("id")
            season = fixture.get("league", {}).get("season")
            self._process_fixture(fixture, league_id, season)
        
        # Cache H2H data
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO h2h_cache (team1_id, team2_id, data)
            VALUES (?, ?, ?)
            ON CONFLICT(team1_id, team2_id) DO UPDATE SET
                data=excluded.data,
                updated_at=CURRENT_TIMESTAMP
        """, (team1_id, team2_id, json.dumps([f.get("fixture", {}).get("id") for f in h2h_fixtures])))
        conn.commit()
        conn.close()
        
        print(f"[SUCCESS] Collected {len(h2h_fixtures)} H2H matches")
        return h2h_fixtures
        
    def get_fixture_by_id(self, fixture_id: int) -> dict:
        """Fetch a specific fixture by its ID."""
        data = self._request("fixtures", {"id": fixture_id})
        return data
    
    def collect_team_stats(self, team_id: int, league_id: int, season: int):
        """Collect aggregated team statistics for a season."""
        data = self._request("teams/statistics", {
            "team": team_id, "league": league_id, "season": season
        })
        return data.get("response", {})
    
    def collect_standings(self, league_id: int, season: int):
        """Collect league standings."""
        data = self._request("standings", {"league": league_id, "season": season})
        return data.get("response", [])
    
    def collect_odds(self, fixture_id: int):
        """Collect pre-match odds from API-Football."""
        data = self._request("odds", {"fixture": fixture_id})
        odds_data = data.get("response", [])
        
        for odds_entry in odds_data:
            bookmakers = odds_entry.get("bookmakers", [])
            for bookmaker in bookmakers:
                bk_name = bookmaker.get("name", "Unknown")
                for bet in bookmaker.get("bets", []):
                    market = bet.get("name", "")
                    for value in bet.get("values", []):
                        self.db.insert_odds({
                            "match_id": fixture_id,
                            "bookmaker": bk_name,
                            "market": market,
                            "selection": str(value.get("value", "")),
                            "odds_value": float(value.get("odd", 0)),
                        })
        
        return odds_data
    
    def collect_all_league_data(self, league_id: int, season: int):
        """Collect all data for a league season."""
        print(f"\n🏟️ Collecting data for {SUPPORTED_LEAGUES.get(league_id, 'Unknown')} - Season {season}")
        
        # 1. Fixtures
        fixtures = self.collect_fixtures(league_id, season)
        
        # 2. Match stats for finished matches
        finished = [f for f in fixtures if f.get("fixture", {}).get("status", {}).get("short") == "FT"]
        print(f"📊 Collecting stats for {len(finished)} finished matches...")
        
        for i, fixture in enumerate(finished):
            fixture_id = fixture["fixture"]["id"]
            self.collect_fixture_stats(fixture_id)
            
            if (i + 1) % 10 == 0:
                print(f"   Progress: {i+1}/{len(finished)}")
                time.sleep(0.5)  # Respect rate limits
        
        # 3. Standings
        self.collect_standings(league_id, season)
        
        print(f"✅ Completed data collection for league {league_id}")
    
    def collect_upcoming_with_analysis(self, league_id: int, season: int, days_ahead: int = 7):
        """Collect upcoming fixtures and prepare for analysis."""
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        fixtures = self.collect_fixtures(league_id, season, from_date=today, to_date=future)
        upcoming = [f for f in fixtures if f.get("fixture", {}).get("status", {}).get("short") == "NS"]
        
        print(f"\n📅 {len(upcoming)} upcoming matches found")
        
        for fixture in upcoming:
            home_id = fixture["teams"]["home"]["id"]
            away_id = fixture["teams"]["away"]["id"]
            fixture_id = fixture["fixture"]["id"]
            
            # Collect H2H
            self.collect_h2h(home_id, away_id)
            
            # Collect odds
            self.collect_odds(fixture_id)
            
            time.sleep(0.3)
        
        return upcoming

    def collect_team_recent_fixtures(
        self,
        team_id: int,
        last: int = 10,
        seasons: Optional[List[int]] = None,
    ):
        """Collect recent finished fixtures for a team using seasons allowed by the API plan."""
        candidate_seasons = seasons or self._historical_seasons()
        collected: Dict[int, Dict] = {}

        for season in candidate_seasons:
            data = self._request("fixtures", {"team": team_id, "season": season, "status": "FT"})
            for fixture in data.get("response", []):
                fixture_id = fixture.get("fixture", {}).get("id")
                if fixture_id:
                    collected[int(fixture_id)] = fixture
            if len(collected) >= last:
                break

        fixtures = self._sort_fixtures(collected.values())[:last]
        for fixture in fixtures:
            league_id = fixture.get("league", {}).get("id")
            season = fixture.get("league", {}).get("season")
            self._process_fixture(fixture, league_id, season)
        return fixtures

    def search_team(self, team_name: str) -> Optional[Dict]:
        """Resolve a club by name and cache the result locally."""
        if not team_name:
            return None

        data = self._request("teams", {"search": team_name})
        candidates = data.get("response", [])
        if not candidates:
            return None

        normalized_target = self._normalize_name(team_name)
        best_match = candidates[0]
        for item in candidates:
            team = item.get("team", {})
            if self._normalize_name(team.get("name", "")) == normalized_target:
                best_match = item
                break

        team = best_match.get("team", {})
        venue = best_match.get("venue", {})
        if team.get("id"):
            self.db.upsert_team({
                "api_id": team.get("id"),
                "name": team.get("name"),
                "short_name": team.get("code"),
                "country": team.get("country"),
                "logo_url": team.get("logo"),
                "venue_name": venue.get("name"),
                "venue_capacity": venue.get("capacity"),
            })

        return {
            "api_id": team.get("id"),
            "name": team.get("name"),
            "short_name": team.get("code"),
            "country": team.get("country"),
            "logo_url": team.get("logo"),
            "venue_name": venue.get("name"),
            "venue_capacity": venue.get("capacity"),
        }

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(
            "".join(ch.lower() if ch.isalnum() else " " for ch in (name or "")).split()
        )

    @staticmethod
    def _sort_fixtures(fixtures) -> List[Dict]:
        return sorted(
            list(fixtures),
            key=lambda fixture: fixture.get("fixture", {}).get("timestamp", 0) or 0,
            reverse=True,
        )

    @staticmethod
    def _historical_seasons() -> List[int]:
        current_year = datetime.now().year
        newest = min(current_year - 1, 2024)
        oldest = 2022
        return [season for season in range(newest, oldest - 1, -1)]
    
    def _process_fixture(self, fixture: dict, league_id: int, season: int):
        """Process and store a fixture."""
        fx = fixture.get("fixture", {})
        teams = fixture.get("teams", {})
        goals = fixture.get("goals", {})
        score = fixture.get("score", {})
        league = fixture.get("league", {})

        if league_id:
            self.db.upsert_league({
                "api_id": league_id,
                "name": league.get("name"),
                "country": league.get("country"),
                "logo_url": league.get("logo"),
                "season": season,
            })

        # Upsert teams
        for side in ["home", "away"]:
            team = teams.get(side, {})
            self.db.upsert_team({
                "api_id": team.get("id"),
                "name": team.get("name"),
                "country": team.get("country"),
                "logo_url": team.get("logo"),
            })
        
        # Upsert match
        ht_score = score.get("halftime", {})
        self.db.upsert_match({
            "api_id": fx.get("id"),
            "league_id": league_id,
            "season": season,
            "round": fixture.get("league", {}).get("round"),
            "match_date": fx.get("date"),
            "status": fx.get("status", {}).get("short", "NS"),
            "home_team_id": teams.get("home", {}).get("id"),
            "away_team_id": teams.get("away", {}).get("id"),
            "home_goals": goals.get("home"),
            "away_goals": goals.get("away"),
            "home_goals_ht": ht_score.get("home"),
            "away_goals_ht": ht_score.get("away"),
            "referee": fx.get("referee"),
            "venue": fx.get("venue", {}).get("name"),
        })
    
    def _process_match_stats(self, match_id: int, team_stats: dict):
        """Process and store match statistics."""
        team = team_stats.get("team", {})
        stats = team_stats.get("statistics", [])
        
        # Convert stats list to dict
        stats_dict = {}
        for stat in stats:
            key = stat.get("type", "").lower().replace(" ", "_")
            value = stat.get("value")
            if value is not None:
                if isinstance(value, str) and value.endswith("%"):
                    value = float(value.replace("%", ""))
                elif isinstance(value, str):
                    try:
                        value = int(value)
                    except ValueError:
                        try:
                            value = float(value)
                        except ValueError:
                            pass
            stats_dict[key] = value
        
        self.db.upsert_match_stats({
            "match_id": match_id,
            "team_id": team.get("id"),
            "shots_total": stats_dict.get("total_shots", 0) or stats_dict.get("shots_on_goal", 0),
            "shots_on_target": stats_dict.get("shots_on_goal", 0),
            "shots_off_target": stats_dict.get("shots_off_goal", 0),
            "shots_blocked": stats_dict.get("blocked_shots", 0),
            "possession": stats_dict.get("ball_possession", 0),
            "corners": stats_dict.get("corner_kicks", 0),
            "offsides": stats_dict.get("offsides", 0),
            "fouls": stats_dict.get("fouls", 0),
            "yellow_cards": stats_dict.get("yellow_cards", 0),
            "red_cards": stats_dict.get("red_cards", 0),
            "goalkeeper_saves": stats_dict.get("goalkeeper_saves", 0),
            "total_passes": stats_dict.get("total_passes", 0),
            "passes_accurate": stats_dict.get("passes_accurate", 0),
            "pass_accuracy": stats_dict.get("passes_%", 0) or stats_dict.get("pass_accuracy", 0),
            "expected_goals": stats_dict.get("expected_goals"),
            "ball_possession": stats_dict.get("ball_possession", 0),
        })
