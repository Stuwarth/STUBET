import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import sys

# Ensure backend imports work
sys.path.append(str(Path(__file__).parent.parent.parent))

from config import SUPPORTED_LEAGUES
from data.collectors.football_api import FootballAPICollector
from data.collectors.sofascore_collector import SofaScoreCollector
from data.collectors.news_scraper import NewsInjuryScraper
from data.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TOP_LEAGUES = {39, 140, 135, 78, 61, 2, 3, 71, 128}
ESPN_LEAGUE_MAP = {
    39: {"key": "eng.1", "country": "England"},
    140: {"key": "esp.1", "country": "Spain"},
    135: {"key": "ita.1", "country": "Italy"},
    78: {"key": "ger.1", "country": "Germany"},
    61: {"key": "fra.1", "country": "France"},
    2: {"key": "uefa.champions", "country": "Europe"},
    3: {"key": "uefa.europa", "country": "Europe"},
    71: {"key": "bra.1", "country": "Brazil"},
    128: {"key": "arg.1", "country": "Argentina"},
}
SOFASCORE_LEAGUE_MAP = {
    "premier league": 39,
    "laliga": 140,
    "serie a": 135,
    "bundesliga": 78,
    "ligue 1": 61,
    "champions league": 2,
    "europa league": 3,
    "brasileirao": 71,
    "liga profesional": 128,
}
FINISHED_STATUSES = {"FT", "AET", "PEN"}


def _normalize_text(value: str) -> str:
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in (value or "")).split()
    )


def _safe_int(value) -> Optional[int]:
    if value in (None, "", "-"):
        return None
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _season_for_match(match_date: str) -> int:
    try:
        parsed = datetime.fromisoformat(str(match_date).replace("Z", "+00:00"))
    except Exception:
        parsed = datetime.now()
    return parsed.year if parsed.month >= 7 else parsed.year - 1


def _status_to_short(status_text: str) -> str:
    text = (status_text or "").lower()
    if "final" in text or "finished" in text:
        return "FT"
    if "halftime" in text:
        return "HT"
    if "extra time" in text:
        return "ET"
    if any(token in text for token in ("in progress", "live", "1st", "2nd", "3rd", "4th", "period", "quarter")):
        return "LIVE"
    if any(token in text for token in ("postponed", "canceled", "cancelled")):
        return "PST"
    return "NS"


def _synthetic_match_id(source_id, home_id: int, away_id: int) -> int:
    digits = "".join(ch for ch in str(source_id or "") if ch.isdigit())
    if digits:
        return -int(digits[:12])
    digest = hashlib.md5(f"{home_id}:{away_id}:{source_id}".encode("utf-8")).hexdigest()
    return -int(digest[:12], 16)


def _resolve_team(db: DatabaseManager, api: FootballAPICollector, team_name: str) -> Optional[Dict]:
    team = db.find_team(team_name)
    if team:
        return team

    team = api.search_team(team_name)
    if team:
        return team

    normalized = _normalize_text(team_name)
    fallback_name = " ".join(part for part in normalized.split() if part not in {"fc", "cf", "sc", "ac", "club"})
    if fallback_name and fallback_name != normalized:
        return db.find_team(fallback_name) or api.search_team(fallback_name)
    return None


def _normalize_free_fixture(
    match: Dict,
    league_id: int,
    db: DatabaseManager,
    api: FootballAPICollector,
) -> Optional[Dict]:
    home_name = match.get("home_team", {}).get("name")
    away_name = match.get("away_team", {}).get("name")
    if not home_name or not away_name:
        return None

    home_team = _resolve_team(db, api, home_name)
    away_team = _resolve_team(db, api, away_name)
    if not home_team or not away_team:
        logger.warning("No se pudo mapear %s vs %s a IDs API-Football.", home_name, away_name)
        return None

    existing = db.get_active_match_by_teams(int(home_team["api_id"]), int(away_team["api_id"]))
    match_id = existing["api_id"] if existing else _synthetic_match_id(
        match.get("id"),
        int(home_team["api_id"]),
        int(away_team["api_id"]),
    )
    status = _status_to_short(match.get("status", ""))
    match_date = match.get("date") or match.get("utc_date") or datetime.now().isoformat()
    season = _season_for_match(match_date)

    home_score = _safe_int(match.get("home_team", {}).get("score"))
    away_score = _safe_int(match.get("away_team", {}).get("score"))

    return {
        "fixture": {
            "id": match_id,
            "date": match_date,
            "status": {
                "short": status,
                "elapsed": None,
            },
            "referee": None,
            "venue": {
                "name": match.get("venue", ""),
            },
        },
        "league": {
            "id": league_id,
            "name": SUPPORTED_LEAGUES.get(league_id, f"League {league_id}"),
            "country": ESPN_LEAGUE_MAP.get(league_id, {}).get("country"),
            "logo": None,
            "season": season,
            "round": None,
            "standings": True,
        },
        "teams": {
            "home": {
                "id": int(home_team["api_id"]),
                "name": home_team.get("name") or home_name,
                "logo": home_team.get("logo_url") or match.get("home_team", {}).get("logo"),
            },
            "away": {
                "id": int(away_team["api_id"]),
                "name": away_team.get("name") or away_name,
                "logo": away_team.get("logo_url") or match.get("away_team", {}).get("logo"),
            },
        },
        "goals": {
            "home": home_score,
            "away": away_score,
        },
        "score": {
            "halftime": {
                "home": None,
                "away": None,
            },
        },
    }


async def _load_today_fixtures(
    today: str,
    db: DatabaseManager,
    api: FootballAPICollector,
    news_scraper: NewsInjuryScraper,
) -> list[Dict]:
    fixtures_response = api._request("fixtures", {"date": today})
    fixtures = fixtures_response.get("response", [])
    fixtures = [
        fixture for fixture in fixtures
        if fixture.get("league", {}).get("id") in TOP_LEAGUES
        and fixture.get("fixture", {}).get("status", {}).get("short") not in {"PST", "CANC"}
    ]
    if fixtures:
        logger.info("Fixtures actuales obtenidos desde API-Football/cache: %s", len(fixtures))
        return fixtures

    logger.warning("API-Football no devolvio fixtures actuales. Activando fallback ESPN/Sofascore.")
    normalized: Dict[tuple[int, int], Dict] = {}
    compact_date = today.replace("-", "")

    for league_id, meta in ESPN_LEAGUE_MAP.items():
        matches = news_scraper.get_espn_scoreboard(meta["key"], date_str=compact_date)
        for match in matches:
            parsed = _normalize_free_fixture(match, league_id, db, api)
            if not parsed:
                continue
            pair_key = (
                parsed["teams"]["home"]["id"],
                parsed["teams"]["away"]["id"],
            )
            normalized[pair_key] = parsed

    if normalized:
        return list(normalized.values())

    sofascore_matches = await news_scraper.get_sofascore_schedule(today)
    for match in sofascore_matches:
        league_text = _normalize_text(match.get("league", ""))
        league_id = next(
            (mapped_id for token, mapped_id in SOFASCORE_LEAGUE_MAP.items() if token in league_text),
            None,
        )
        if not league_id:
            continue
        parsed = _normalize_free_fixture(match, league_id, db, api)
        if not parsed:
            continue
        pair_key = (
            parsed["teams"]["home"]["id"],
            parsed["teams"]["away"]["id"],
        )
        normalized[pair_key] = parsed

    return list(normalized.values())


async def run_daily_pipeline():
    """
    Populate the local DB with today's real fixtures plus enough historical context
    to power market-aware analysis.
    """
    logger.info("Iniciando STUBET Stats Pipeline...")

    db = DatabaseManager()
    api = FootballAPICollector(db)
    sofa_collector = SofaScoreCollector(db)
    news_scraper = NewsInjuryScraper(db)
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        sofa_summary = await sofa_collector.sync_recent_finished(days_back=1)
        logger.info(
            "SofaScore sync ok | eventos procesados: %s | payloads guardados: %s",
            sofa_summary.get("events_processed", 0),
            sofa_summary.get("payloads_saved", 0),
        )
    except Exception as e:
        logger.warning("SofaScore historical sync failed: %s", e)

    fixtures = await _load_today_fixtures(today, db, api, news_scraper)
    if not fixtures:
        logger.warning("No se encontraron partidos para %s.", today)
        return

    logger.info("Se encontraron %s partidos relevantes para poblar el motor.", len(fixtures))

    unique_team_ids = set()
    h2h_pairs = []
    processed_stat_fixtures = set()

    for fixture in fixtures:
        league = fixture.get("league", {})
        fx = fixture.get("fixture", {})
        teams = fixture.get("teams", {})

        league_id = league.get("id", 0)
        season = league.get("season", _season_for_match(fx.get("date", today)))
        home_id = teams.get("home", {}).get("id")
        away_id = teams.get("away", {}).get("id")

        conn = db.get_connection()
        try:
            conn.execute(
                """
                INSERT INTO leagues (api_id, name, country, logo_url, season)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(api_id) DO UPDATE SET
                    name=excluded.name,
                    country=excluded.country,
                    logo_url=excluded.logo_url,
                    season=excluded.season,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    league_id,
                    league.get("name"),
                    league.get("country"),
                    league.get("logo"),
                    season,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        api._process_fixture(fixture, league_id, season)
        unique_team_ids.update(team_id for team_id in (home_id, away_id) if team_id)
        if home_id and away_id:
            h2h_pairs.append((home_id, away_id))

        logger.info(
            "[%s] %s vs %s",
            fx.get("status", {}).get("short", "NS"),
            teams.get("home", {}).get("name", "Local"),
            teams.get("away", {}).get("name", "Visitante"),
        )

    team_ids = list(unique_team_ids)[:24]
    team_histories: Dict[int, list[Dict]] = {}
    stat_candidates: list[int] = []

    # First capture recent fixture history for every team so the engine gets form/context,
    # even if later stat-detail calls hit the plan rate limit.
    for team_id in team_ids:
        recent_fixtures = api.collect_team_recent_fixtures(team_id, last=8)
        team_histories[team_id] = recent_fixtures
        for recent in recent_fixtures:
            status = recent.get("fixture", {}).get("status", {}).get("short")
            fixture_id = recent.get("fixture", {}).get("id")
            league_id = recent.get("league", {}).get("id")
            season = recent.get("league", {}).get("season")
            api._process_fixture(recent, league_id, season)
            if status in FINISHED_STATUSES and fixture_id:
                stat_candidates.append(fixture_id)
        await asyncio.sleep(0.2)

    for home_id, away_id in h2h_pairs[:12]:
        h2h_matches = api.collect_h2h(home_id, away_id, last=5)
        for match in h2h_matches:
            fixture_id = match.get("fixture", {}).get("id")
            status = match.get("fixture", {}).get("status", {}).get("short")
            if status in FINISHED_STATUSES and fixture_id:
                stat_candidates.append(fixture_id)
        await asyncio.sleep(0.2)

    # Pull a capped, deduped slice of detailed stats after history is already stored.
    # This keeps the pipeline useful under free-plan limits instead of exhausting quota on one team.
    unique_stat_candidates = []
    seen_fixture_ids = set()
    for fixture_id in stat_candidates:
        if fixture_id in seen_fixture_ids:
            continue
        seen_fixture_ids.add(fixture_id)
        unique_stat_candidates.append(fixture_id)
        if len(unique_stat_candidates) >= 18:
            break

    for fixture_id in unique_stat_candidates:
        if fixture_id in processed_stat_fixtures:
            continue
        api.collect_fixture_stats(fixture_id)
        processed_stat_fixtures.add(fixture_id)
        await asyncio.sleep(0.6)

    logger.info(
        "Pipeline finalizado. Equipos auditados: %s | Stats cargadas: %s",
        len(team_ids),
        len(processed_stat_fixtures),
    )


if __name__ == "__main__":
    asyncio.run(run_daily_pipeline())
