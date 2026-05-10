"""
FastAPI Server - REST API for the Sports AI Predictor dashboard.
"""
from fastapi import FastAPI, HTTPException, Query  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore
from fastapi.responses import FileResponse, JSONResponse  # type: ignore
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
import sys
import json
import asyncio
import re
import httpx  # type: ignore

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent.parent))

from data.database import DatabaseManager  # type: ignore
from ml.predictor import SportsPredictor  # type: ignore
from ml.feature_engineering import FeatureEngineer  # type: ignore
from ml.advanced_markets import AdvancedMarketPredictor  # type: ignore
from data.collectors.news_scraper import NewsInjuryScraper  # type: ignore
from analysis.performance_tracker import PerformanceTracker  # type: ignore
from analysis.pattern_detector import PatternDetector  # type: ignore
from analysis.stubet_autonomous_analyst import StubetAutonomousAnalyst  # type: ignore
from notifications.telegram_bot import TelegramNotifier  # type: ignore
from config import SUPPORTED_LEAGUES, SERVER_HOST, SERVER_PORT  # type: ignore
from data.collectors.playwright_scraper import PlaywrightOddsScraper, sync_get_match_odds  # type: ignore
from data.collectors.sofascore_collector import SofaScoreCollector  # type: ignore
from playwright.sync_api import sync_playwright  # type: ignore

# Initialize
app = FastAPI(
    title="â½ Sports AI Predictor",
    description="Machine Learning Sports Prediction & Value Bet Detection System",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Global instances
db = DatabaseManager()
predictor = SportsPredictor(db)
tracker = PerformanceTracker(db)
advanced_predictor = AdvancedMarketPredictor(db)
pattern_detector = PatternDetector(db)
news_scraper = NewsInjuryScraper(db)
telegram = TelegramNotifier()
stealth_scraper = PlaywrightOddsScraper(db, predictor, telegram)
sofascore_collector = SofaScoreCollector(db)
autonomous_analyst = StubetAutonomousAnalyst()

SOFASCORE_BASE_URL = "https://www.sofascore.com/api/v1"
SOFASCORE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

STUBET_MIN_TELEGRAM_ODDS = 1.48
STUBET_PREMATCH_MAX_HOURS_AHEAD = 72
STUBET_STALE_MAX_HOURS_AFTER_KICKOFF = 4
STUBET_LIVE_MAX_HOURS_AFTER_KICKOFF = 4


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _sofascore_team_image(team_id: Any) -> str:
    team_int = _safe_int(team_id)
    if not team_int:
        return ""
    return f"https://api.sofascore.app/api/v1/team/{team_int}/image"


def _sofascore_player_image(player_id: Any) -> str:
    player_int = _safe_int(player_id)
    if not player_int:
        return ""
    return f"https://api.sofascore.app/api/v1/player/{player_int}/image"


async def _fetch_sofascore_json(path: str) -> Optional[Dict[str, Any]]:
    url = f"{SOFASCORE_BASE_URL}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=SOFASCORE_HEADERS,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return None
            payload = response.json()
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


async def _fetch_sofascore_payloads_playwright(
    payload_paths: Dict[str, str],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Fallback for SofaScore endpoints that sometimes reject direct HTTP clients."""
    from playwright.async_api import async_playwright  # type: ignore

    results: Dict[str, Optional[Dict[str, Any]]] = {key: None for key in payload_paths}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # 1. Clear WAF/Cloudflare by navigating to base domain first
            await page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.5)  # Pause for headers/cookies

            keys = list(payload_paths.keys())
            fetch_promises = []

            # 2. Build the inline JavaScript to fetch JSONs concurrently using the site's own origin
            for key in keys:
                path = payload_paths[key].lstrip('/')
                url = f"https://www.sofascore.com/api/v1/{path}"
                fetch_promises.append(
                    f'fetch("{url}", {{headers: {{"accept":"*/*"}} }}).then(r => r.text()).catch(e => "")'
                )

            js_script = f"""
            async () => {{
                return await Promise.all([{','.join(fetch_promises)}]);
            }}
            """

            # 3. Execute script inside the authenticated context
            fetched_texts = await page.evaluate(js_script)

            # 4. Read output texts
            for key, text in zip(keys, fetched_texts):
                if text:
                    try:
                        payload = json.loads(text)
                        if isinstance(payload, dict):
                            results[key] = payload
                    except Exception:
                        pass
        except Exception as e:
            pass  # Silent fail to avoid crashing the whole match center
        finally:
            await browser.close()

    return results

def _load_stored_sofascore_payload(event_id: int, payload_type: str) -> Optional[Dict[str, Any]]:
    try:
        rows = db.get_sofascore_payload(event_id, payload_type)
        if not rows:
            return None
        parsed_row = dict(rows[0])
        raw_payload = parsed_row.get("payload_json")
        if isinstance(raw_payload, str):
            try:
                parsed = json.loads(raw_payload)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        if isinstance(raw_payload, dict):
            return raw_payload
    except Exception:
        pass
    return None


def _classify_absence_reason(row_type: str, description: str) -> Dict[str, str]:
    text = f"{row_type} {description}".lower()
    normalized = text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")

    if any(token in normalized for token in ["doubt", "question", "gtd", "to be confirmed", "duda"]):
        return {
            "status": "Duda",
            "injury_type": description or "Duda",
            "suspension_kind": "none",
        }

    if any(token in normalized for token in ["suspend", "sanction", "ban", "tarjeta", "card", "book"]):
        if any(token in normalized for token in ["red", "roja", "straight red", "second yellow"]):
            return {
                "status": "Suspendido",
                "injury_type": "Suspension por roja",
                "suspension_kind": "red_card",
            }
        if any(token in normalized for token in ["yellow", "amarilla", "accum", "bookings", "5th", "fifth"]):
            return {
                "status": "Suspendido",
                "injury_type": "Suspension por acumulacion de amarillas",
                "suspension_kind": "yellow_accumulation",
            }
        return {
            "status": "Suspendido",
            "injury_type": "Suspension",
            "suspension_kind": "generic",
        }

    return {
        "status": "Baja",
        "injury_type": description or "No disponible",
        "suspension_kind": "none",
    }


def _compact_lineup_side(side_payload: Dict[str, Any]) -> Dict[str, Any]:
    players = side_payload.get("players", []) if isinstance(side_payload, dict) else []
    missing_players = side_payload.get("missingPlayers", []) if isinstance(side_payload, dict) else []

    starters: List[Dict[str, Any]] = []
    bench: List[Dict[str, Any]] = []
    for idx, row in enumerate(players if isinstance(players, list) else []):
        if not isinstance(row, dict):
            continue
        player = row.get("player", {}) if isinstance(row.get("player"), dict) else {}
        stats = row.get("statistics", {}) if isinstance(row.get("statistics"), dict) else {}
        player_id = player.get("id")

        raw_rating = stats.get("rating") if stats.get("rating") is not None else row.get("rating")
        rating_value: Optional[float] = None
        if raw_rating is not None:
            try:
                rating_value = float(raw_rating)
            except Exception:
                rating_value = None

        raw_avg_rating = row.get("avgRating")
        avg_rating_value: Optional[float] = None
        if raw_avg_rating is not None:
            try:
                avg_rating_value = float(raw_avg_rating)
            except Exception:
                avg_rating_value = None

        display_rating = rating_value if rating_value is not None else avg_rating_value

        explicit_player_order = _safe_int(
            row.get("order")
            or row.get("sortOrder")
            or row.get("index")
        )
        if explicit_player_order is None:
            explicit_player_order = idx + 1

        compact = {
            "id": player_id,
            "name": player.get("name") or row.get("name"),
            "short_name": player.get("shortName") or player.get("name") or row.get("name"),
            "position": row.get("position") or player.get("position"),
            "shirt_number": row.get("shirtNumber") or row.get("jerseyNumber") or player.get("jerseyNumber"),
            "formation_slot": _safe_int(
                row.get("formationPosition")
                or row.get("formationSlot")
                or row.get("formationPlace")
                or row.get("positionOrder")
            ),
            "formation_line": _safe_int(
                row.get("formationLine")
                or row.get("line")
                or row.get("lineNumber")
            ),
            "player_order": explicit_player_order,
            "captain": bool(row.get("captain")),
            "substitute": bool(row.get("substitute")),
            "photo": _sofascore_player_image(player_id),
            # Keep `rating` backward-compatible for older frontend code paths.
            "rating": display_rating,
            "live_rating": rating_value,
            "avg_rating": avg_rating_value,
            "display_rating": display_rating,
            "minutes_played": stats.get("minutesPlayed"),
            "goals": stats.get("goals"),
            "assists": stats.get("goalAssist") or stats.get("assists"),
            "yellow_cards": stats.get("yellowCards"),
            "red_cards": stats.get("redCards"),
        }
        if compact["substitute"]:
            bench.append(compact)
        else:
            starters.append(compact)

    missing: List[Dict[str, Any]] = []
    for row in missing_players if isinstance(missing_players, list) else []:
        if not isinstance(row, dict):
            continue
        player = row.get("player", {}) if isinstance(row.get("player"), dict) else {}
        row_type = str(row.get("type", "")).lower().strip()
        description = str(row.get("description") or row.get("reason") or "").strip()
        reason_meta = _classify_absence_reason(row_type, description)

        missing.append({
            "id": player.get("id"),
            "name": player.get("name"),
            "position": player.get("position"),
            "type": row_type or "missing",
            "status": reason_meta.get("status", "Baja"),
            "injury_type": reason_meta.get("injury_type", "No disponible"),
            "suspension_kind": reason_meta.get("suspension_kind", "none"),
            "description": description or "No disponible",
        })

    return {
        "formation": side_payload.get("formation") if isinstance(side_payload, dict) else None,
        "starters": starters,
        "bench": bench,
        "missing": missing,
    }


def _compact_incidents(incidents_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    incidents = incidents_payload.get("incidents", []) if isinstance(incidents_payload, dict) else []
    compact: List[Dict[str, Any]] = []
    for row in incidents if isinstance(incidents, list) else []:
        if not isinstance(row, dict):
            continue

        player = row.get("player", {}) if isinstance(row.get("player"), dict) else {}
        assist = row.get("assist1", {}) if isinstance(row.get("assist1"), dict) else {}
        player_in = row.get("playerIn", {}) if isinstance(row.get("playerIn"), dict) else {}
        player_out = row.get("playerOut", {}) if isinstance(row.get("playerOut"), dict) else {}

        compact.append({
            "time": row.get("time"),
            "added_time": row.get("addedTime"),
            "is_home": bool(row.get("isHome")),
            "incident_type": row.get("incidentType"),
            "text": row.get("text"),
            "home_score": row.get("homeScore"),
            "away_score": row.get("awayScore"),
            "player": player.get("name"),
            "assist": assist.get("name"),
            "player_in": player_in.get("name"),
            "player_out": player_out.get("name"),
        })

    return compact


def _compact_statistics(statistics_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    periods = statistics_payload.get("statistics", []) if isinstance(statistics_payload, dict) else []
    compact: List[Dict[str, Any]] = []

    for period in periods if isinstance(periods, list) else []:
        if not isinstance(period, dict):
            continue

        groups_out: List[Dict[str, Any]] = []
        groups = period.get("groups", []) if isinstance(period.get("groups"), list) else []
        for group in groups:
            if not isinstance(group, dict):
                continue

            items_out: List[Dict[str, Any]] = []
            items = group.get("statisticsItems", []) if isinstance(group.get("statisticsItems"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                items_out.append({
                    "name": item.get("name"),
                    "home": item.get("home"),
                    "away": item.get("away"),
                    "compare_code": item.get("compareCode"),
                    "value_type": item.get("valueType"),
                })

            if items_out:
                groups_out.append({
                    "group_name": group.get("groupName") or "General",
                    "items": items_out,
                })

        if groups_out:
            compact.append({
                "period": period.get("period") or "ALL",
                "groups": groups_out,
            })

    return compact


def _compact_history_events(history_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = history_payload.get("events", []) if isinstance(history_payload, dict) else []
    compact: List[Dict[str, Any]] = []

    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue

        home_team = event.get("homeTeam", {}) if isinstance(event.get("homeTeam"), dict) else {}
        away_team = event.get("awayTeam", {}) if isinstance(event.get("awayTeam"), dict) else {}
        status = event.get("status", {}) if isinstance(event.get("status"), dict) else {}
        status_type = str(status.get("type", "")).lower()
        home_score = (event.get("homeScore") or {}).get("current") if isinstance(event.get("homeScore"), dict) else None
        away_score = (event.get("awayScore") or {}).get("current") if isinstance(event.get("awayScore"), dict) else None

        if status_type not in {"finished", "afterpens", "aet"} and (home_score is None or away_score is None):
            continue

        tournament = event.get("tournament", {}) if isinstance(event.get("tournament"), dict) else {}
        start_timestamp = _safe_int(event.get("startTimestamp"))
        match_date = None
        if start_timestamp:
            match_date = datetime.fromtimestamp(start_timestamp, tz=timezone.utc).date().isoformat()

        compact.append({
            "event_id": event.get("id"),
            "start_timestamp": start_timestamp,
            "match_date": match_date,
            "status_type": status_type,
            "status_description": status.get("description"),
            "home_team_id": _safe_int(home_team.get("id")),
            "away_team_id": _safe_int(away_team.get("id")),
            "home_team_name": home_team.get("name"),
            "away_team_name": away_team.get("name"),
            "home_score": home_score,
            "away_score": away_score,
            "league_name": tournament.get("name") or "",
        })

    compact.sort(key=lambda row: row.get("start_timestamp") or 0, reverse=True)
    return compact


def _history_sort_key(row: Dict[str, Any]) -> int:
    ts = _safe_int(row.get("start_timestamp"))
    return ts if ts is not None else 0


def _history_identity_key(row: Dict[str, Any]) -> str:
    event_id = _safe_int(row.get("event_id"))
    if event_id:
        return f"event:{event_id}"

    home_id = _safe_int(row.get("home_team_id")) or 0
    away_id = _safe_int(row.get("away_team_id")) or 0
    start_ts = _safe_int(row.get("start_timestamp")) or 0
    return f"fallback:{start_ts}:{home_id}:{away_id}"


def _dedupe_history_rows(rows: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    if not rows:
        return []

    sorted_rows = sorted(rows, key=_history_sort_key, reverse=True)
    seen: Dict[str, bool] = {}
    deduped: List[Dict[str, Any]] = []

    for row in sorted_rows:
        if not isinstance(row, dict):
            continue
        key = _history_identity_key(row)
        if seen.get(key):
            continue
        seen[key] = True
        deduped.append(row)
        if len(deduped) >= limit:
            break

    return deduped


def _derive_h2h_from_team_history(
    home_team_id: Any,
    away_team_id: Any,
    home_last10: List[Dict[str, Any]],
    away_last10: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    home_id = _safe_int(home_team_id)
    away_id = _safe_int(away_team_id)
    if not home_id or not away_id:
        return []

    merged: List[Dict[str, Any]] = []
    for row in (home_last10 + away_last10):
        if not isinstance(row, dict):
            continue

        row_home = _safe_int(row.get("home_team_id"))
        row_away = _safe_int(row.get("away_team_id"))
        if row_home is None or row_away is None:
            continue

        if (row_home == home_id and row_away == away_id) or (row_home == away_id and row_away == home_id):
            merged.append(row)

    return _dedupe_history_rows(merged, limit=10)


SOFASCORE_METRIC_ALIASES: Dict[str, str] = {
    "expected goals": "expected_goals",
    "ball possession": "ball_possession",
    "total shots": "total_shots",
    "shots on target": "shots_on_target",
    "corner kicks": "corner_kicks",
    "fouls": "fouls",
    "yellow cards": "yellow_cards",
    "red cards": "red_cards",
    "big chances": "big_chances",
    "big chances scored": "big_chances_scored",
    "big chances missed": "big_chances_missed",
    "offsides": "offsides",
    "accurate passes": "accurate_passes",
    "total saves": "goalkeeper_saves",
    "goalkeeper saves": "goalkeeper_saves",
}

SOFASCORE_METRIC_LABELS: Dict[str, str] = {
    "expected_goals": "xG",
    "ball_possession": "Posesion",
    "total_shots": "Remates",
    "shots_on_target": "Remates al arco",
    "corner_kicks": "Corners",
    "fouls": "Faltas",
    "yellow_cards": "Amarillas",
    "red_cards": "Rojas",
    "big_chances": "Big chances",
    "big_chances_scored": "Big chances convertidas",
    "big_chances_missed": "Big chances falladas",
    "offsides": "Offsides",
    "accurate_passes": "Pases precisos",
    "goalkeeper_saves": "Atajadas",
}


def _normalize_lookup_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _normalize_period_name(period: Any) -> str:
    normalized = _normalize_lookup_text(period).replace(" ", "")
    if normalized in {"all", "full", "fulltime"}:
        return "ALL"
    if normalized in {"1", "1st", "first", "firsthalf", "period1", "1sthalf"}:
        return "1ST"
    if normalized in {"2", "2nd", "second", "secondhalf", "period2", "2ndhalf"}:
        return "2ND"

    raw = str(period or "").strip().upper()
    return raw or "ALL"


def _safe_stat_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text or text == "-":
        return None

    match = re.search(r"[-+]?\d+(?:[\.,]\d+)?", text)
    if not match:
        return None

    numeric = match.group(0).replace(",", ".")
    try:
        return float(numeric)
    except Exception:
        return None


def _parse_datetime_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    candidates = [text, text.replace("Z", "+00:00"), text.replace(" ", "T")]
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return None


def _prediction_is_fresh_for_telegram(pred: Dict[str, Any], now_utc: Optional[datetime] = None) -> Tuple[bool, str]:
    now = now_utc or datetime.now(tz=timezone.utc)

    status_text = str(pred.get("status") or "").strip().upper()
    if status_text in {"FT", "AET", "PEN", "FINISHED", "CANC", "PST", "ABD", "INT"}:
        return False, "finished_status"

    kickoff_dt = _parse_datetime_utc(pred.get("match_date"))
    if kickoff_dt is None:
        return False, "kickoff_unknown"

    if kickoff_dt < (now - timedelta(hours=2)):
        return False, "kickoff_too_old"
    if kickoff_dt > (now + timedelta(hours=72)):
        return False, "kickoff_too_far"

    odds_val = _safe_stat_float(pred.get("odds_value"))
    if odds_val is None:
        return False, "odds_unavailable"
    if odds_val < STUBET_MIN_TELEGRAM_ODDS:
        return False, "odds_below_floor"

    return True, "ok"


def _extract_period_metric_snapshot(
    compact_statistics: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    snapshot: Dict[str, Dict[str, Dict[str, float]]] = {}

    for period_block in compact_statistics if isinstance(compact_statistics, list) else []:
        if not isinstance(period_block, dict):
            continue

        period_key = _normalize_period_name(period_block.get("period"))
        groups = period_block.get("groups", []) if isinstance(period_block.get("groups"), list) else []

        for group in groups:
            if not isinstance(group, dict):
                continue
            items = group.get("items", []) if isinstance(group.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                metric_key = SOFASCORE_METRIC_ALIASES.get(_normalize_lookup_text(item.get("name")))
                if not metric_key:
                    continue

                home_val = _safe_stat_float(item.get("home"))
                away_val = _safe_stat_float(item.get("away"))
                if home_val is None or away_val is None:
                    continue

                period_metrics = snapshot.setdefault(period_key, {})
                period_metrics[metric_key] = {
                    "home": round(home_val, 3),
                    "away": round(away_val, 3),
                }

    return snapshot


def _to_team_period_metrics(
    period_snapshot: Dict[str, Dict[str, Dict[str, float]]],
    team_is_home: Optional[bool],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    if team_is_home is None:
        return {}

    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for period_key, metrics in period_snapshot.items():
        if not isinstance(metrics, dict):
            continue
        out_period: Dict[str, Dict[str, float]] = {}
        for metric_key, values in metrics.items():
            if not isinstance(values, dict):
                continue
            home_val = _safe_stat_float(values.get("home"))
            away_val = _safe_stat_float(values.get("away"))
            if home_val is None or away_val is None:
                continue

            own_val = home_val if team_is_home else away_val
            opp_val = away_val if team_is_home else home_val
            out_period[metric_key] = {
                "for": round(own_val, 3),
                "against": round(opp_val, 3),
            }

        if out_period:
            out[period_key] = out_period

    return out


def _avg(values: List[float]) -> Optional[float]:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 2)


def _summarize_form_from_samples(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(samples)
    wins = draws = losses = 0
    goals_for_values: List[float] = []
    goals_against_values: List[float] = []
    btts_hits = 0
    over25_hits = 0
    goals_samples = 0

    for sample in samples:
        if not isinstance(sample, dict):
            continue

        result = sample.get("result")
        if result == "W":
            wins += 1
        elif result == "D":
            draws += 1
        elif result == "L":
            losses += 1

        goals_for = _safe_stat_float(sample.get("goals_for"))
        goals_against = _safe_stat_float(sample.get("goals_against"))
        if goals_for is None or goals_against is None:
            continue

        goals_samples += 1
        goals_for_values.append(goals_for)
        goals_against_values.append(goals_against)
        if goals_for > 0 and goals_against > 0:
            btts_hits += 1
        if (goals_for + goals_against) > 2.5:
            over25_hits += 1

    return {
        "sample_size": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": round((wins / total) * 100, 1) if total else 0.0,
        "goals_for_avg": _avg(goals_for_values),
        "goals_against_avg": _avg(goals_against_values),
        "btts_rate": round((btts_hits / goals_samples) * 100, 1) if goals_samples else None,
        "over25_rate": round((over25_hits / goals_samples) * 100, 1) if goals_samples else None,
    }


def _summarize_period_averages(samples: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Optional[float]]]]:
    acc: Dict[str, Dict[str, Dict[str, List[float]]]] = {}

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        period_metrics = sample.get("period_metrics", {}) if isinstance(sample.get("period_metrics"), dict) else {}
        for period_key, metrics in period_metrics.items():
            if not isinstance(metrics, dict):
                continue
            period_acc = acc.setdefault(period_key, {})
            for metric_key, values in metrics.items():
                if not isinstance(values, dict):
                    continue
                for_val = _safe_stat_float(values.get("for"))
                against_val = _safe_stat_float(values.get("against"))
                if for_val is None or against_val is None:
                    continue
                metric_acc = period_acc.setdefault(metric_key, {"for": [], "against": []})
                metric_acc["for"].append(for_val)
                metric_acc["against"].append(against_val)

    out: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    for period_key, metrics in acc.items():
        period_out: Dict[str, Dict[str, Optional[float]]] = {}
        for metric_key, metric_values in metrics.items():
            for_avg = _avg(metric_values.get("for", []))
            against_avg = _avg(metric_values.get("against", []))
            edge = None
            if for_avg is not None and against_avg is not None:
                edge = round(for_avg - against_avg, 2)
            period_out[metric_key] = {
                "label": SOFASCORE_METRIC_LABELS.get(metric_key, metric_key),
                "for_avg": for_avg,
                "against_avg": against_avg,
                "edge": edge,
            }

        if period_out:
            out[period_key] = period_out

    return out


async def _resolve_statistics_payloads_for_events(
    event_ids: List[int],
    force_refresh: bool = False,
) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, str]]:
    payloads: Dict[int, Dict[str, Any]] = {}
    sources: Dict[int, str] = {}

    unique_event_ids: List[int] = []
    seen: Dict[int, bool] = {}
    for raw in event_ids:
        event_id = _safe_int(raw)
        if not event_id or seen.get(event_id):
            continue
        seen[event_id] = True
        unique_event_ids.append(event_id)

    unresolved: List[int] = []
    for event_id in unique_event_ids:
        if not force_refresh:
            stored = _load_stored_sofascore_payload(event_id, "statistics")
            if isinstance(stored, dict):
                payloads[event_id] = stored
                sources[event_id] = "stored"
                continue
        unresolved.append(event_id)

    if not unresolved:
        return payloads, sources

    live_paths = {event_id: f"event/{event_id}/statistics" for event_id in unresolved}
    live_tasks = [_fetch_sofascore_json(path) for path in live_paths.values()]
    live_results = await asyncio.gather(*live_tasks, return_exceptions=True)

    unresolved_playwright: Dict[str, str] = {}
    for event_id, result in zip(live_paths.keys(), live_results):
        if isinstance(result, dict):
            payloads[event_id] = result
            sources[event_id] = "live_http"
            try:
                db.upsert_sofascore_payload(event_id, "statistics", result)
            except Exception:
                pass
        else:
            unresolved_playwright[str(event_id)] = live_paths[event_id]

    if unresolved_playwright and force_refresh:
        try:
            playwright_payloads = await _fetch_sofascore_payloads_playwright(unresolved_playwright)
            for event_key, payload in playwright_payloads.items():
                event_id = _safe_int(event_key)
                if not event_id or not isinstance(payload, dict):
                    continue
                payloads[event_id] = payload
                sources[event_id] = "live_playwright"
                try:
                    db.upsert_sofascore_payload(event_id, "statistics", payload)
                except Exception:
                    pass
        except Exception:
            pass

    for event_key in unresolved_playwright.keys():
        event_id = _safe_int(event_key)
        if not event_id or event_id in payloads:
            continue
        stored = _load_stored_sofascore_payload(event_id, "statistics")
        if isinstance(stored, dict):
            payloads[event_id] = stored
            sources[event_id] = "stored"
        else:
            sources[event_id] = "missing"

    return payloads, sources


def _build_history_stat_samples(
    rows: List[Dict[str, Any]],
    team_id: Any,
    target_competition_norm: str,
    stats_payloads: Dict[int, Dict[str, Any]],
    include_statistics: bool = False,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    team_id_int = _safe_int(team_id)

    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        event_id = _safe_int(row.get("event_id"))
        if not event_id:
            continue

        row_home_id = _safe_int(row.get("home_team_id"))
        row_away_id = _safe_int(row.get("away_team_id"))

        team_is_home: Optional[bool] = None
        if team_id_int and row_home_id == team_id_int:
            team_is_home = True
        elif team_id_int and row_away_id == team_id_int:
            team_is_home = False

        raw_stats = stats_payloads.get(event_id)
        compact_stats = _compact_statistics(raw_stats) if isinstance(raw_stats, dict) else []
        period_snapshot = _extract_period_metric_snapshot(compact_stats)
        team_period_metrics = _to_team_period_metrics(period_snapshot, team_is_home)

        goals_for: Optional[float] = None
        goals_against: Optional[float] = None
        if team_is_home is not None:
            home_score = _safe_stat_float(row.get("home_score"))
            away_score = _safe_stat_float(row.get("away_score"))
            if home_score is not None and away_score is not None:
                if team_is_home:
                    goals_for, goals_against = home_score, away_score
                else:
                    goals_for, goals_against = away_score, home_score

        result = None
        if goals_for is not None and goals_against is not None:
            if goals_for > goals_against:
                result = "W"
            elif goals_for < goals_against:
                result = "L"
            else:
                result = "D"

        league_name = str(row.get("league_name") or "")
        same_competition = bool(target_competition_norm) and _normalize_lookup_text(league_name) == target_competition_norm

        sample = {
            "event_id": event_id,
            "start_timestamp": _safe_int(row.get("start_timestamp")),
            "match_date": row.get("match_date"),
            "league_name": league_name,
            "home_team_name": row.get("home_team_name"),
            "away_team_name": row.get("away_team_name"),
            "home_score": row.get("home_score"),
            "away_score": row.get("away_score"),
            "same_competition": same_competition,
            "stats_available": len(compact_stats) > 0,
            "available_periods": sorted(team_period_metrics.keys()),
            "period_metrics": team_period_metrics,
            "result": result,
            "goals_for": round(goals_for, 2) if goals_for is not None else None,
            "goals_against": round(goals_against, 2) if goals_against is not None else None,
        }

        if include_statistics:
            sample["statistics"] = compact_stats

        out.append(sample)

    return out


def _build_history_bucket_context(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    same_comp_samples = [row for row in samples if isinstance(row, dict) and row.get("same_competition")]
    stats_available = [row for row in samples if isinstance(row, dict) and row.get("stats_available")]
    return {
        "sample_count": len(samples),
        "stats_available_count": len(stats_available),
        "same_competition_count": len(same_comp_samples),
        "form": _summarize_form_from_samples(samples),
        "same_competition_form": _summarize_form_from_samples(same_comp_samples),
        "period_averages": _summarize_period_averages(samples),
        "same_competition_period_averages": _summarize_period_averages(same_comp_samples),
        "matches": samples,
    }


def _get_period_metric_avg(
    bucket_context: Dict[str, Any],
    period: str,
    metric: str,
    side: str,
) -> Optional[float]:
    period_map = bucket_context.get("period_averages", {}) if isinstance(bucket_context.get("period_averages"), dict) else {}
    period_row = period_map.get(period, {}) if isinstance(period_map.get(period), dict) else {}
    metric_row = period_row.get(metric, {}) if isinstance(period_row.get(metric), dict) else {}
    return _safe_stat_float(metric_row.get(f"{side}_avg"))


def _build_sofascore_ai_notes(
    home_context: Dict[str, Any],
    away_context: Dict[str, Any],
    h2h_context: Dict[str, Any],
    target_competition: str,
) -> List[str]:
    notes: List[str] = []

    home_form = home_context.get("form", {}) if isinstance(home_context.get("form"), dict) else {}
    away_form = away_context.get("form", {}) if isinstance(away_context.get("form"), dict) else {}
    h2h_form = h2h_context.get("form", {}) if isinstance(h2h_context.get("form"), dict) else {}

    home_over25 = _safe_stat_float(home_form.get("over25_rate"))
    away_over25 = _safe_stat_float(away_form.get("over25_rate"))
    h2h_over25 = _safe_stat_float(h2h_form.get("over25_rate"))
    if home_over25 is not None and away_over25 is not None:
        mean_over25 = (home_over25 + away_over25 + (h2h_over25 if h2h_over25 is not None else (home_over25 + away_over25) / 2.0)) / 3.0
        if mean_over25 >= 58:
            notes.append(f"Tendencia de goles alta: Over 2.5 combinado ~{round(mean_over25, 1)}%.")
        elif mean_over25 <= 42:
            notes.append(f"Tendencia de goles baja: Over 2.5 combinado ~{round(mean_over25, 1)}%.")

    home_btts = _safe_stat_float(home_form.get("btts_rate"))
    away_btts = _safe_stat_float(away_form.get("btts_rate"))
    if home_btts is not None and away_btts is not None:
        btts_mean = (home_btts + away_btts) / 2.0
        if btts_mean >= 57:
            notes.append(f"Ambos marcan con frecuencia en forma reciente (~{round(btts_mean, 1)}%).")

    home_shots = _get_period_metric_avg(home_context, "ALL", "shots_on_target", "for")
    away_shots = _get_period_metric_avg(away_context, "ALL", "shots_on_target", "for")
    if home_shots is not None and away_shots is not None:
        notes.append(
            f"Remates al arco promedio (ALL): local {round(home_shots, 2)} vs visitante {round(away_shots, 2)}."
        )

    first_half_home_xg = _get_period_metric_avg(home_context, "1ST", "expected_goals", "for")
    first_half_away_xg = _get_period_metric_avg(away_context, "1ST", "expected_goals", "for")
    if first_half_home_xg is not None and first_half_away_xg is not None:
        notes.append(
            f"Produccion ofensiva 1T (xG): local {round(first_half_home_xg, 2)} vs visitante {round(first_half_away_xg, 2)}."
        )

    home_same_comp = _safe_int(home_context.get("same_competition_count")) or 0
    away_same_comp = _safe_int(away_context.get("same_competition_count")) or 0
    if target_competition and (home_same_comp >= 4 or away_same_comp >= 4):
        notes.append(
            f"Misma competencia ({target_competition}) detectada en muestra: local {home_same_comp}, visitante {away_same_comp}."
        )

    if not notes:
        notes.append("Contexto IA disponible, pero muestra estadistica aun limitada para concluir sesgos fuertes.")

    return notes


@app.on_event("startup")
async def startup_event():
    """Start background tasks on server boot."""
    # NOTE: Playwright scraper disabled on auto-start (causes crashes on Windows)
    # User can activate via dashboard: POST /api/scraper/start
    pass

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up background tasks safely."""
    try:
        await stealth_scraper.stop()
    except Exception:
        pass


# ==================== ROUTES ====================

@app.get("/")
async def root():
    """Serve the dashboard."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Sports AI Predictor API", "status": "running"}


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    stats = db.get_stats_summary()
    return {
        "status": "healthy",
        "database": stats,
        "models_loaded": list(predictor.models.keys()),
        "version": predictor.version,
    }


@app.get("/api/leagues")
async def get_leagues():
    """Get supported leagues."""
    return {"leagues": [{"id": k, "name": v} for k, v in SUPPORTED_LEAGUES.items()]}


@app.get("/api/dashboard")
async def get_dashboard(date: Optional[str] = None):
    """Get comprehensive dashboard data."""
    try:
        stats = tracker.get_dashboard_stats(date_filter=date)
        model_info = predictor.get_model_info()
        db_stats = db.get_stats_summary()
        
        return {
            "performance": stats,
            "model_info": model_info,
            "database_stats": db_stats,
            "supported_leagues": SUPPORTED_LEAGUES,
        }
    except Exception as e:
        return {"error": str(e), "performance": {}, "model_info": {}, "database_stats": {}}


@app.get("/api/predictions")
async def get_predictions(
    market: Optional[str] = None,
    value_only: bool = False,
    upcoming_only: bool = True,
    date: Optional[str] = None
):
    """Get predictions."""
    try:
        predictions = db.get_predictions_with_matches(
            market=market,
            only_value=value_only,
            only_unsettled=upcoming_only,
            date_filter=date
        )
        return {"predictions": predictions, "count": len(predictions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/predict/match")
async def predict_match(home_team_id: int, away_team_id: int, league_id: Optional[int] = None):
    """Predict a specific match."""
    try:
        predictions = predictor.predict_match(home_team_id, away_team_id, league_id)
        return {"predictions": predictions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/predict/upcoming")
async def predict_upcoming(league_id: Optional[int] = None, days_ahead: int = 7):
    """Predict all upcoming matches."""
    try:
        results = predictor.predict_upcoming(league_id, days_ahead)
        return {"predictions": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/value-bets")
async def get_value_bets():
    """Get current value bet opportunities."""
    try:
        predictions = db.get_predictions_with_matches(only_value=True, only_unsettled=True)
        return {
            "value_bets": predictions,
            "count": len(predictions),
            "total_value_bets_found": len(predictions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/performance")
async def get_performance():
    """Get detailed performance metrics."""
    try:
        stats = tracker.get_dashboard_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/performance/by-market")
async def get_performance_by_market():
    """Get performance breakdown by market."""
    try:
        return {"markets": db.get_performance_summary()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/h2h/{team1_id}/{team2_id}")
async def get_h2h(team1_id: int, team2_id: int):
    """Get head-to-head analysis."""
    try:
        matches = db.get_h2h_matches(team1_id, team2_id)
        fe = FeatureEngineer(db)
        features = fe._get_h2h_features(team1_id, team2_id)
        return {"matches": matches, "analysis": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/team/{team_id}/stats")
async def get_team_stats(team_id: int, limit: int = 20):
    """Get team statistics."""
    try:
        matches = db.get_team_matches(team_id, limit=limit)
        stats = db.get_match_stats_for_team(team_id, limit=limit)
        
        fe = FeatureEngineer(db)
        features = fe._get_team_features(team_id, limit)
        
        return {
            "matches": matches,
            "stats": stats,
            "features": features,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/train")
async def train_models(league_id: Optional[int] = None):
    """Train/retrain ML models."""
    try:
        success = predictor.train_all_models(league_id)
        if success:
            return {"status": "success", "message": "Models trained successfully"}
        return {"status": "error", "message": "Insufficient data for training"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/collect/fixtures")
async def collect_fixtures(league_id: int, season: int):
    """Collect fixture data."""
    try:
        from data.collectors.football_api import FootballAPICollector  # type: ignore
        collector = FootballAPICollector(db)
        fixtures = collector.collect_fixtures(league_id, season)
        return {"status": "success", "fixtures_collected": len(fixtures)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/settle")
async def settle_predictions():
    """Settle predictions for finished matches."""
    try:
        count = tracker.settle_finished_matches()
        return {"status": "success", "settled": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/model/info")
async def model_info():
    """Get model information."""
    return predictor.get_model_info()


# ==================== DEMO DATA ====================

@app.post("/api/demo/generate")
async def generate_demo_data():
    """Demo data is intentionally disabled for a production-first STUBET setup."""
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Demo data is disabled. Use real pipeline data only.",
        },
    )


# ==================== ADVANCED STATS ENDPOINTS ====================

@app.post("/api/predict/stats")
async def predict_match_stats(home_team_id: int, away_team_id: int):
    """Predict ALL statistical markets for a match (corners, shots, cards, saves, etc.)."""
    try:
        predictions = advanced_predictor.predict_match_stats(home_team_id, away_team_id)
        return {"status": "success", "predictions": predictions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/patterns/discover")
async def discover_patterns():
    """Run pattern discovery on all historical data."""
    try:
        patterns = pattern_detector.discover_all_patterns()
        return {
            "status": "success",
            "patterns_found": len(patterns),
            "patterns": patterns,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patterns/match")
async def get_match_patterns(home_team_id: int, away_team_id: int):
    """Get active patterns that apply to a specific upcoming match."""
    try:
        patterns = pattern_detector.get_active_patterns_for_match(home_team_id, away_team_id)
        return {"patterns": patterns, "count": len(patterns)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news/{league_key}")
async def get_news(league_key: str = "eng.1", date: Optional[str] = None):
    """Get latest real news from ESPN for a league."""
    try:
        news = news_scraper.get_espn_news(league_key)
        scoreboard = news_scraper.get_espn_scoreboard(league_key, date_str=date)
        return {
            "news": news,
            "upcoming_matches": scoreboard,
            "source": "espn",
            "competitions": news_scraper.get_espn_competitions(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/injuries/{team_name}")
def get_injuries(team_name: str, league_key: str = "eng.1"):
    """Get current injuries for a team from real sources."""
    try:
        injuries = news_scraper.scrape_injuries(team_name, league_key=league_key)
        return {"team": team_name, "league_key": league_key, "injuries": injuries, "count": len(injuries)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/match-context")
def get_match_context(home_team: str, away_team: str, league_key: str = "eng.1"):
    """Get full match context: injuries, news, impact analysis, and live LasPlatas odds."""
    try:
        from data.collectors.playwright_scraper import sync_get_match_odds
        from data.collectors.football_api import FootballAPICollector
        import re
        import unicodedata

        def variants(team_name: str):
            ascii_name = unicodedata.normalize("NFKD", team_name or "").encode("ascii", "ignore").decode("ascii")
            base = re.sub(r"\s+", " ", team_name or "").strip()
            ascii_base = re.sub(r"\s+", " ", ascii_name).strip()
            items = [base, ascii_base]
            expanded = []
            for item in items:
                if item and item not in expanded:
                    expanded.append(item)
                stripped = re.sub(r"^(fc|cf|ac|cd|sc)\s+", "", item, flags=re.IGNORECASE).strip()
                if stripped and stripped not in expanded:
                    expanded.append(stripped)
            return expanded

        api_temp = FootballAPICollector(db)
        if not db.find_team(home_team):
            for v in variants(home_team):
                if db.find_team(v):
                    break
                api_temp.search_team(v)
        if not db.find_team(away_team):
            for v in variants(away_team):
                if db.find_team(v):
                    break
                api_temp.search_team(v)

        # Scrape LasPlatas odds safely in this threadpool worker
        market_odds = sync_get_match_odds(home_team, away_team)
        
        context = news_scraper.get_match_context(home_team, away_team, league_key, odds_data=market_odds)
        return context
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== SCRAPER CONTROL ====================

@app.post("/api/scraper/start")
async def start_scraper():
    """Start the live LasPlatas scraper for market-aware alerts."""
    try:
        await stealth_scraper.start()
        return {"status": "success", "running": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scraper/stop")
async def stop_scraper():
    """Stop the live LasPlatas scraper."""
    try:
        await stealth_scraper.stop()
        return {"status": "success", "running": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/scraper/status")
async def scraper_status():
    return {"running": stealth_scraper.is_running}


# ==================== TELEGRAM ENDPOINTS ====================

@app.post("/api/telegram/test")
async def test_telegram():
    """Test Telegram bot connection."""
    result = telegram.test_connection()
    return result


@app.get("/api/telegram/status")
async def telegram_status():
    """Get Telegram notifier status."""
    return telegram.get_status()


@app.post("/api/telegram/notify-value-bets")
async def notify_value_bets():
    """Send all current value bets via Telegram."""
    try:
        predictions = db.get_predictions_with_matches(only_value=True, only_unsettled=True)
        sent = 0  # type: ignore
        skipped = 0
        skipped_reasons: Dict[str, int] = {}
        now_utc = datetime.now(tz=timezone.utc)
        for pred in predictions:
            is_eligible, reason = _prediction_is_fresh_for_telegram(pred, now_utc=now_utc)
            if not is_eligible:
                skipped = skipped + 1
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                continue

            if str(pred.get("model_version", "")).startswith("stubet-market-aware"):
                success = telegram.send_stubet_market_alert({
                    "match": f"{pred.get('home_team_name', 'Local')} vs {pred.get('away_team_name', 'Visitante')}",
                    "selection": pred.get("prediction"),
                    "market": pred.get("market"),
                    "odds": pred.get("odds_value", "-"),
                    "probability": pred.get("probability", 0),
                    "edge": pred.get("value_edge", 0),
                    "confidence": pred.get("confidence", "LOW"),
                    "rationale": pred.get("rationale", "Sin justificación"),
                }, mode="PRE-MATCH")
            else:
                success = telegram.send_value_bet_alert(pred)
            if success:
                sent = sent + 1  # type: ignore
        return {
            "status": "success",
            "sent": sent,
            "total": len(predictions),
            "skipped": skipped,
            "skipped_reasons": skipped_reasons,
            "min_odds_floor": STUBET_MIN_TELEGRAM_ODDS,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/telegram/daily-report")
async def send_daily_report():
    """Send daily performance report via Telegram."""
    try:
        stats = tracker.get_dashboard_stats()
        success = telegram.send_daily_report(stats)
        return {"status": "success" if success else "error", "sent": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== REAL DATA ENDPOINTS ====================

@app.get("/api/live/scoreboard/{league_key}")
async def get_live_scoreboard(league_key: str = "eng.1", date: Optional[str] = None):
    """Get live scores from ESPN (REAL DATA, no API key needed).
    
    Args:
        league_key: ESPN league key (e.g. eng.1, esp.1)
        date: Optional date in YYYYMMDD format (e.g. 20260311)
    """
    try:
        if league_key == "sofascore_all":
            if not date or len(date) != 8:
                import datetime
                date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            else:
                d = str(date)
                date_str = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"  # type: ignore
            
            matches = await news_scraper.get_sofascore_schedule(date_str)
            return {"matches": matches, "count": len(matches), "source": "sofascore", "date": date_str}
            
        matches = news_scraper.get_espn_scoreboard(league_key, date_str=date)
        return {"matches": matches, "count": len(matches), "source": "espn", "date": date or "today"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/live/standings/{competition}")
async def get_standings(competition: str = "PL"):
    """Get real league standings from football-data.org."""
    try:
        standings = news_scraper.get_footballdata_standings(competition)
        return {"standings": standings, "source": "football-data.org"}
    except Exception as e:
        return {"standings": [], "error": str(e)}


# ==================== SETTINGS SAVE/LOAD (FASE 1) ====================

@app.get("/api/settings/load")
async def load_settings():
    """Load current settings from .env file."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    settings = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                # Censor sensitive values for display
                if "TOKEN" in key or "KEY" in key or "API" in key:
                    settings[key] = val[:6] + "***" + val[-4:] if len(val) > 10 else "***"
                    settings[key + "_SET"] = bool(val and val not in ("", "your_telegram_bot_token", "your_chat_id"))
                else:
                    settings[key] = val
    return {"settings": settings}


@app.post("/api/settings/save")
async def save_settings(data: dict):
    """Save settings to .env file from dashboard."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    
    # Read current env
    current = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                current[key] = val
    
    # Update with new values (only non-empty)
    for key, val in data.items():
        if val and not val.endswith("***"):  # Don't overwrite with censored value
            current[key] = val
    
    # Write back
    env_content = "\n".join(f"{k}={v}" for k, v in current.items()) + "\n"
    env_path.write_text(env_content)
    
    return {"status": "success", "message": "Settings saved. Runtime clients will reload them automatically when possible."}


@app.post("/api/pipeline/run")
async def run_pipeline():
    """Run the STUBET stats pipeline from the dashboard (no terminal needed)."""
    import subprocess
    try:
        backend_dir = str(Path(__file__).parent.parent)
        result = subprocess.run(
            [sys.executable, "-m", "data.collectors.stubet_pipeline"],
            cwd=backend_dir,
            capture_output=True, text=True, timeout=120,
            env={**dict(__import__('os').environ), "PYTHONIOENCODING": "utf-8"}
        )
        output = result.stdout + result.stderr
        return {
            "status": "success" if result.returncode == 0 else "error",
            "output": output,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "output": "Pipeline timed out after 120s"}
    except Exception as e:
        return {"status": "error", "output": str(e)}


@app.post("/api/pipeline/sofascore-sync")
async def run_sofascore_sync(
    days_back: int = Query(default=1, ge=0, le=30),
    max_events_per_day: int = Query(default=0, ge=0, le=2000),
):
    """Sync finished SofaScore events for the last N days."""
    try:
        summary = await sofascore_collector.sync_recent_finished(
            days_back=days_back,
            max_events_per_day=max_events_per_day,
        )
        return {"status": "success", "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pipeline/sofascore-backfill")
async def run_sofascore_backfill(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    max_events_per_day: int = Query(default=0, ge=0, le=2000),
):
    """Backfill finished SofaScore events for a date range."""
    try:
        summary = await sofascore_collector.backfill_finished(
            start_date=start_date,
            end_date=end_date,
            max_events_per_day=max_events_per_day,
        )
        return {"status": "success", "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sofascore/team/{team_id}/last10")
async def get_sofascore_last10(team_id: int, limit: int = Query(default=10, ge=1, le=50)):
    """Get last finished matches for a SofaScore team."""
    try:
        matches = db.get_sofascore_team_matches(team_id, limit=limit)
        return {"team_id": team_id, "matches": matches, "count": len(matches)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sofascore/h2h/{team1_id}/{team2_id}")
async def get_sofascore_h2h(team1_id: int, team2_id: int, limit: int = Query(default=10, ge=1, le=50)):
    """Get finished H2H history for two SofaScore teams."""
    try:
        matches = db.get_sofascore_h2h_matches(team1_id, team2_id, limit=limit)
        return {"team1_id": team1_id, "team2_id": team2_id, "matches": matches, "count": len(matches)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sofascore/event/{event_id}/payloads")
async def get_sofascore_event_payloads(event_id: int, payload_type: Optional[str] = None):
    """Get raw stored payloads for a SofaScore event."""
    try:
        rows = db.get_sofascore_payload(event_id, payload_type)
        payloads = []
        for row in rows:
            parsed = dict(row)
            raw_payload = parsed.pop("payload_json", None)
            if isinstance(raw_payload, str):
                try:
                    parsed["payload"] = json.loads(raw_payload)
                except Exception:
                    parsed["payload"] = raw_payload
            else:
                parsed["payload"] = raw_payload
            payloads.append(parsed)
        return {"event_id": event_id, "payloads": payloads, "count": len(payloads)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sofascore/event/{event_id}/match-center")
async def get_sofascore_match_center(
    event_id: int,
    history_limit: int = Query(default=10, ge=5, le=20),
    enrich_history_stats: bool = Query(default=True),
    refresh_history_stats: bool = Query(default=False),
    include_history_statistics: bool = Query(default=False),
    force_fresh_history: bool = Query(default=False),
):
    """Get SofaScore match-center data optimized for dashboard tabs."""
    payload_paths: Dict[str, str] = {
        "event_details": f"event/{event_id}",
        "lineups": f"event/{event_id}/lineups",
        "incidents": f"event/{event_id}/incidents",
        "statistics": f"event/{event_id}/statistics",
        "graph": f"event/{event_id}/graph",
    }

    live_tasks = [_fetch_sofascore_json(path) for path in payload_paths.values()]
    live_results = await asyncio.gather(*live_tasks, return_exceptions=True)

    payloads: Dict[str, Optional[Dict[str, Any]]] = {}
    payload_sources: Dict[str, str] = {}
    for payload_type, result in zip(payload_paths.keys(), live_results):
        if isinstance(result, dict):
            payloads[payload_type] = result
            payload_sources[payload_type] = "live_http"
        else:
            payloads[payload_type] = None

    if not payloads.get("event_details") or not payloads.get("lineups"):
        try:
            playwright_payloads = await _fetch_sofascore_payloads_playwright(payload_paths)
            for payload_type, payload in playwright_payloads.items():
                if payloads.get(payload_type) is None and isinstance(payload, dict):
                    payloads[payload_type] = payload
                    payload_sources[payload_type] = "live_playwright"
        except Exception:
            pass

    for payload_type in payload_paths:
        if payloads.get(payload_type) is None:
            stored = _load_stored_sofascore_payload(event_id, payload_type)
            payloads[payload_type] = stored
            payload_sources[payload_type] = "stored" if stored else "missing"

    event_payload = payloads.get("event_details") or {}
    event_obj = event_payload.get("event") if isinstance(event_payload, dict) else None
    if not isinstance(event_obj, dict) or not event_obj:
        if isinstance(event_payload, dict) and event_payload.get("id"):
            event_obj = event_payload
        else:
            raise HTTPException(status_code=404, detail="No SofaScore event data available for this event.")

    home_team = event_obj.get("homeTeam", {}) if isinstance(event_obj.get("homeTeam"), dict) else {}
    away_team = event_obj.get("awayTeam", {}) if isinstance(event_obj.get("awayTeam"), dict) else {}
    home_team_id = _safe_int(home_team.get("id"))
    away_team_id = _safe_int(away_team.get("id"))

    status = event_obj.get("status", {}) if isinstance(event_obj.get("status"), dict) else {}
    status_type = str(status.get("type", "")).lower()
    status_description = status.get("description") or "Programado"

    start_timestamp = _safe_int(event_obj.get("startTimestamp"))
    kickoff_iso = None
    countdown_minutes = None
    if start_timestamp is not None:
        kickoff_iso = datetime.fromtimestamp(start_timestamp, tz=timezone.utc).isoformat()
        countdown_minutes = int((start_timestamp - int(datetime.now(tz=timezone.utc).timestamp())) / 60)

    lineups_payload = payloads.get("lineups") or {}
    lineups_confirmed = bool(lineups_payload.get("confirmed")) if isinstance(lineups_payload, dict) else False
    if lineups_confirmed:
        lineup_status = "confirmed"
        lineup_label = "Alineaciones confirmadas"
    elif status_type in {"finished", "inprogress", "halftime"}:
        lineup_status = "closed"
        lineup_label = "Partido en curso o finalizado"
    elif countdown_minutes is not None and 0 <= countdown_minutes <= 75:
        lineup_status = "expected_soon"
        lineup_label = "Se confirman cerca del inicio (~1h)"
    else:
        lineup_status = "probable"
        lineup_label = "Alineaciones probables"

    incidents = _compact_incidents(payloads.get("incidents") or {})
    statistics = _compact_statistics(payloads.get("statistics") or {})
    graph_payload = payloads.get("graph") or {}
    graph_points = []
    if isinstance(graph_payload, dict):
        raw_graph = graph_payload.get("graphPoints") or graph_payload.get("points") or graph_payload.get("graph")
        if isinstance(raw_graph, list):
            graph_points = raw_graph

    if force_fresh_history:
        home_last10 = []
        away_last10 = []
        h2h = []
    else:
        home_last10 = db.get_sofascore_team_matches(home_team_id, limit=history_limit) if home_team_id else []
        away_last10 = db.get_sofascore_team_matches(away_team_id, limit=history_limit) if away_team_id else []
        h2h = db.get_sofascore_h2h_matches(home_team_id, away_team_id, limit=history_limit) if home_team_id and away_team_id else []

    history_paths: Dict[str, str] = {}
    if not home_last10 and home_team_id:
        history_paths["home_last10"] = f"team/{home_team_id}/events/last/0"
    if not away_last10 and away_team_id:
        history_paths["away_last10"] = f"team/{away_team_id}/events/last/0"
    if not h2h:
        custom_id = event_obj.get("customId") if isinstance(event_obj, dict) else None
        h2h_id = custom_id if custom_id else event_id
        history_paths["h2h"] = f"event/{h2h_id}/h2h/events"

    def _merge_history_bucket(bucket: str, payload: Optional[Dict[str, Any]]) -> None:
        nonlocal home_last10, away_last10, h2h
        if not isinstance(payload, dict):
            return
        rows = _compact_history_events(payload)
        if not rows:
            return
        if bucket == "home_last10":
            home_last10 = rows[:history_limit]
        elif bucket == "away_last10":
            away_last10 = rows[:history_limit]
        elif bucket == "h2h":
            h2h = rows[:history_limit]

    if history_paths:
        history_tasks = [_fetch_sofascore_json(path) for path in history_paths.values()]
        history_results = await asyncio.gather(*history_tasks, return_exceptions=True)

        unresolved_paths: Dict[str, str] = {}
        for bucket, result in zip(history_paths.keys(), history_results):
            if isinstance(result, dict):
                before_len = len(h2h) if bucket == "h2h" else (len(home_last10) if bucket == "home_last10" else len(away_last10))
                _merge_history_bucket(bucket, result)
                after_len = len(h2h) if bucket == "h2h" else (len(home_last10) if bucket == "home_last10" else len(away_last10))
                if after_len == before_len:
                    unresolved_paths[bucket] = history_paths[bucket]
            else:
                unresolved_paths[bucket] = history_paths[bucket]

        if unresolved_paths:
            try:
                history_playwright = await _fetch_sofascore_payloads_playwright(unresolved_paths)
                for bucket, payload in history_playwright.items():
                    _merge_history_bucket(bucket, payload)
            except Exception:
                pass

    home_last10 = _dedupe_history_rows(home_last10, limit=history_limit)
    away_last10 = _dedupe_history_rows(away_last10, limit=history_limit)
    h2h = _dedupe_history_rows(h2h, limit=history_limit)

    if not h2h and home_team_id and away_team_id:
        h2h = _derive_h2h_from_team_history(home_team_id, away_team_id, home_last10, away_last10)
        h2h = _dedupe_history_rows(h2h, limit=history_limit)

    tournament = event_obj.get("tournament", {}) if isinstance(event_obj.get("tournament"), dict) else {}
    category = tournament.get("category", {}) if isinstance(tournament.get("category"), dict) else {}

    ai_context: Dict[str, Any] = {
        "enabled": bool(enrich_history_stats),
        "history_limit": history_limit,
        "target_competition": tournament.get("name") or "",
        "home_last10": {},
        "away_last10": {},
        "h2h": {},
        "analysis_notes": [],
        "statistics_sources": {},
    }

    if enrich_history_stats:
        target_competition = str(tournament.get("name") or "")
        target_comp_norm = _normalize_lookup_text(target_competition)

        all_history_event_ids: List[int] = []
        for row in (home_last10 + away_last10 + h2h):
            if not isinstance(row, dict):
                continue
            event_ref = _safe_int(row.get("event_id"))
            if event_ref:
                all_history_event_ids.append(event_ref)

        stats_payloads, stats_sources = await _resolve_statistics_payloads_for_events(
            all_history_event_ids,
            force_refresh=refresh_history_stats,
        )

        home_samples = _build_history_stat_samples(
            home_last10,
            team_id=home_team_id,
            target_competition_norm=target_comp_norm,
            stats_payloads=stats_payloads,
            include_statistics=include_history_statistics,
        )
        away_samples = _build_history_stat_samples(
            away_last10,
            team_id=away_team_id,
            target_competition_norm=target_comp_norm,
            stats_payloads=stats_payloads,
            include_statistics=include_history_statistics,
        )
        h2h_samples = _build_history_stat_samples(
            h2h,
            team_id=home_team_id,
            target_competition_norm=target_comp_norm,
            stats_payloads=stats_payloads,
            include_statistics=include_history_statistics,
        )

        home_context = _build_history_bucket_context(home_samples)
        away_context = _build_history_bucket_context(away_samples)
        h2h_context = _build_history_bucket_context(h2h_samples)

        stats_source_counts: Dict[str, int] = {}
        for source_name in stats_sources.values():
            key = str(source_name or "missing")
            stats_source_counts[key] = stats_source_counts.get(key, 0) + 1

        ai_context = {
            "enabled": True,
            "history_limit": history_limit,
            "target_competition": target_competition,
            "home_last10": home_context,
            "away_last10": away_context,
            "h2h": h2h_context,
            "analysis_notes": _build_sofascore_ai_notes(
                home_context,
                away_context,
                h2h_context,
                target_competition,
            ),
            "statistics_sources": stats_source_counts,
            "refresh_used": bool(refresh_history_stats),
            "history_statistics_included": bool(include_history_statistics),
        }

    return {
        "status": "success",
        "event_id": event_id,
        "event": event_obj,
        "event_summary": {
            "id": event_obj.get("id"),
            "slug": event_obj.get("slug"),
            "status_type": status_type,
            "status": status_description,
            "start_timestamp": start_timestamp,
            "kickoff_utc": kickoff_iso,
            "home_team": {
                "id": home_team_id,
                "name": home_team.get("name"),
                "short_name": home_team.get("shortName", home_team.get("name")),
                "logo": _sofascore_team_image(home_team_id),
                "score": (event_obj.get("homeScore") or {}).get("current") if isinstance(event_obj.get("homeScore"), dict) else None,
            },
            "away_team": {
                "id": away_team_id,
                "name": away_team.get("name"),
                "short_name": away_team.get("shortName", away_team.get("name")),
                "logo": _sofascore_team_image(away_team_id),
                "score": (event_obj.get("awayScore") or {}).get("current") if isinstance(event_obj.get("awayScore"), dict) else None,
            },
            "tournament": tournament.get("name"),
            "category": category.get("name"),
            "round": (event_obj.get("roundInfo") or {}).get("name") if isinstance(event_obj.get("roundInfo"), dict) else None,
            "venue": (event_obj.get("venue") or {}).get("stadium") if isinstance(event_obj.get("venue"), dict) else None,
        },
        "lineup": {
            "confirmed": lineups_confirmed,
            "status": lineup_status,
            "label": lineup_label,
            "countdown_minutes": countdown_minutes,
            "home": _compact_lineup_side(lineups_payload.get("home", {}) if isinstance(lineups_payload, dict) else {}),
            "away": _compact_lineup_side(lineups_payload.get("away", {}) if isinstance(lineups_payload, dict) else {}),
        },
        "incidents": incidents,
        "statistics": statistics,
        "graph": graph_points,
        "history": {
            "h2h": h2h,
            "home_last10": home_last10,
            "away_last10": away_last10,
        },
        "ai_context": ai_context,
        "sources": payload_sources,
    }


@app.post("/api/sofascore/event/{event_id}/history-stats/rescrape")
async def rescrape_sofascore_history_stats(
    event_id: int,
    history_limit: int = Query(default=10, ge=5, le=20),
):
    """Force refresh SofaScore history statistics for AI context (last10 + H2H)."""
    data = await get_sofascore_match_center(
        event_id=event_id,
        history_limit=history_limit,
        enrich_history_stats=True,
        refresh_history_stats=True,
        include_history_statistics=False,
    )

    ai_context = data.get("ai_context", {}) if isinstance(data, dict) else {}
    home_ctx = ai_context.get("home_last10", {}) if isinstance(ai_context.get("home_last10"), dict) else {}
    away_ctx = ai_context.get("away_last10", {}) if isinstance(ai_context.get("away_last10"), dict) else {}
    h2h_ctx = ai_context.get("h2h", {}) if isinstance(ai_context.get("h2h"), dict) else {}

    return {
        "status": "success",
        "event_id": event_id,
        "history_limit": history_limit,
        "statistics_sources": ai_context.get("statistics_sources", {}),
        "samples": {
            "home_last10": home_ctx.get("sample_count", 0),
            "away_last10": away_ctx.get("sample_count", 0),
            "h2h": h2h_ctx.get("sample_count", 0),
        },
        "stats_coverage": {
            "home_last10": home_ctx.get("stats_available_count", 0),
            "away_last10": away_ctx.get("stats_available_count", 0),
            "h2h": h2h_ctx.get("stats_available_count", 0),
        },
        "notes": ai_context.get("analysis_notes", []),
    }


def _stubet_stake_text(stake: Dict[str, Any]) -> str:
    if not isinstance(stake, dict):
        return "-"
    all_in = _safe_int(stake.get("all_in"))
    if all_in:
        return f"ALL IN {all_in}/100"
    label = str(stake.get("label") or stake.get("value") or "-")
    return label


def _stubet_is_finished_status(status_type: Any) -> bool:
    status = str(status_type or "").strip().lower()
    return status in {
        "finished",
        "ended",
        "afterpens",
        "aet",
        "canceled",
        "cancelled",
        "postponed",
        "abandoned",
        "interrupted",
        "suspended",
    }


def _stubet_event_runtime_window(event_summary: Dict[str, Any]) -> Dict[str, Any]:
    status_type = str(event_summary.get("status_type") or "").strip().lower()
    start_timestamp = _safe_int(event_summary.get("start_timestamp"))
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())

    minutes_to_kickoff: Optional[int] = None
    minutes_since_kickoff: Optional[int] = None
    if start_timestamp is not None:
        minutes_to_kickoff = int((start_timestamp - now_ts) / 60)
        minutes_since_kickoff = int((now_ts - start_timestamp) / 60)

    return {
        "status_type": status_type,
        "start_timestamp": start_timestamp,
        "minutes_to_kickoff": minutes_to_kickoff,
        "minutes_since_kickoff": minutes_since_kickoff,
        "is_finished": _stubet_is_finished_status(status_type),
    }


def _stubet_stage_allowed(event_summary: Dict[str, Any], stage: str) -> Tuple[bool, str, Dict[str, Any]]:
    runtime = _stubet_event_runtime_window(event_summary)
    status_type = runtime.get("status_type")
    minutes_to_kickoff = runtime.get("minutes_to_kickoff")
    minutes_since_kickoff = runtime.get("minutes_since_kickoff")

    if runtime.get("is_finished"):
        return False, "event_finished", runtime

    stage_key = str(stage or "").strip().lower()

    if stage_key == "pre_match":
        if status_type not in {"notstarted", "scheduled", "ns", "time_to_be_defined", ""}:
            return False, "not_pre_match_state", runtime
        if isinstance(minutes_to_kickoff, int):
            if minutes_to_kickoff < -30:
                return False, "kickoff_already_started", runtime
            if minutes_to_kickoff > (STUBET_PREMATCH_MAX_HOURS_AHEAD * 60):
                return False, "too_early_window", runtime
        return True, "ok", runtime

    if stage_key == "lineup_confirmed":
        if isinstance(minutes_to_kickoff, int) and minutes_to_kickoff > 240:
            return False, "lineups_not_due_yet", runtime
        if isinstance(minutes_since_kickoff, int) and minutes_since_kickoff > (STUBET_STALE_MAX_HOURS_AFTER_KICKOFF * 60):
            return False, "stale_event_window", runtime
        return True, "ok", runtime

    if stage_key == "live":
        if status_type not in {"inprogress", "halftime"}:
            return False, "not_live_state", runtime
        if isinstance(minutes_since_kickoff, int) and minutes_since_kickoff > (STUBET_LIVE_MAX_HOURS_AFTER_KICKOFF * 60):
            return False, "stale_live_window", runtime
        return True, "ok", runtime

    return False, "unsupported_stage", runtime


def _stubet_guess_league_key(event_summary: Dict[str, Any]) -> str:
    text = f"{event_summary.get('category', '')} {event_summary.get('tournament', '')}".lower()
    mapping = [
        ("england", "eng.1"),
        ("premier league", "eng.1"),
        ("spain", "esp.1"),
        ("laliga", "esp.1"),
        ("italy", "ita.1"),
        ("serie a", "ita.1"),
        ("germany", "ger.1"),
        ("bundesliga", "ger.1"),
        ("france", "fra.1"),
        ("ligue 1", "fra.1"),
        ("argentina", "arg.1"),
        ("brazil", "bra.1"),
        ("champions", "uefa.champions"),
        ("europa league", "uefa.europa"),
    ]
    for token, league_key in mapping:
        if token in text:
            return league_key
    return "sofascore_all"


def _stubet_fetch_external_context(match_center: Dict[str, Any], odds_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    event_summary = match_center.get("event_summary", {}) if isinstance(match_center.get("event_summary"), dict) else {}
    home_team = event_summary.get("home_team", {}) if isinstance(event_summary.get("home_team"), dict) else {}
    away_team = event_summary.get("away_team", {}) if isinstance(event_summary.get("away_team"), dict) else {}
    home_name = str(home_team.get("name") or "").strip()
    away_name = str(away_team.get("name") or "").strip()
    if not home_name or not away_name:
        return {
            "status": "missing_teams",
            "summary": "No se pudo resolver home/away para contexto externo.",
        }

    league_key = _stubet_guess_league_key(event_summary)
    try:
        context = news_scraper.get_match_context(home_name, away_name, league_key=league_key, odds_data=odds_payload or {})
        if isinstance(context, dict):
            context["source"] = "news_scraper"
            context["league_key_used"] = league_key
            return context
    except Exception as exc:
        return {
            "status": "error",
            "source": "news_scraper",
            "league_key_used": league_key,
            "error": str(exc),
        }

    return {
        "status": "empty",
        "source": "news_scraper",
        "league_key_used": league_key,
    }


def _stubet_prediction_odds_gate(report: Dict[str, Any], minimum_odds: float = STUBET_MIN_TELEGRAM_ODDS) -> Tuple[bool, str, Optional[float]]:
    pred = report.get("prediction", {}) if isinstance(report.get("prediction"), dict) else {}
    odds_val = _safe_stat_float(pred.get("bookmaker_odds"))
    if odds_val is None:
        return False, "odds_unavailable", None
    if odds_val < minimum_odds:
        return False, "odds_below_floor", odds_val
    return True, "ok", odds_val


def _stubet_metric_from_snapshot(
    snapshot: Dict[str, Dict[str, Dict[str, float]]],
    period_key: str,
    metric_key: str,
) -> Tuple[Optional[float], Optional[float]]:
    period = snapshot.get(period_key, {}) if isinstance(snapshot.get(period_key), dict) else {}
    metric = period.get(metric_key, {}) if isinstance(period.get(metric_key), dict) else {}
    return _safe_stat_float(metric.get("home")), _safe_stat_float(metric.get("away"))


def _stubet_graph_pressure(
    graph_points: List[Dict[str, Any]],
    recent_window: Optional[int] = None,
) -> Tuple[float, float, int]:
    parsed: List[Tuple[int, float]] = []
    for row in graph_points if isinstance(graph_points, list) else []:
        if not isinstance(row, dict):
            continue
        minute = _safe_int(row.get("minute") or row.get("time") or row.get("x"))
        value = _safe_stat_float(row.get("value") or row.get("y") or row.get("intensity"))
        if minute is None or value is None:
            continue
        parsed.append((minute, float(value)))

    if not parsed:
        return 0.0, 0.0, 0

    parsed.sort(key=lambda item: item[0])
    max_minute = parsed[-1][0]
    min_minute = max(0, max_minute - int(recent_window)) if recent_window is not None else 0

    home_sum = 0.0
    away_sum = 0.0
    for minute, value in parsed:
        if minute < min_minute:
            continue
        if value > 0:
            home_sum += value
        elif value < 0:
            away_sum += abs(value)

    return round(home_sum, 3), round(away_sum, 3), max_minute


def _stubet_live_profile_assessment(match_center: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    prediction = report.get("prediction", {}) if isinstance(report.get("prediction"), dict) else {}
    selection = str(prediction.get("selection") or "")
    market = str(prediction.get("market") or "")

    event_summary = match_center.get("event_summary", {}) if isinstance(match_center.get("event_summary"), dict) else {}
    home_team = event_summary.get("home_team", {}) if isinstance(event_summary.get("home_team"), dict) else {}
    away_team = event_summary.get("away_team", {}) if isinstance(event_summary.get("away_team"), dict) else {}
    home_score = _safe_int(home_team.get("score"))
    away_score = _safe_int(away_team.get("score"))

    statistics = match_center.get("statistics", []) if isinstance(match_center.get("statistics"), list) else []
    snapshot = _extract_period_metric_snapshot(statistics)

    graph_points = match_center.get("graph", []) if isinstance(match_center.get("graph"), list) else []
    home_recent_pressure, away_recent_pressure, max_minute = _stubet_graph_pressure(graph_points, recent_window=25)
    home_full_pressure, away_full_pressure, _ = _stubet_graph_pressure(graph_points, recent_window=None)

    factors: List[Dict[str, Any]] = []

    def factor_points(strength: str) -> int:
        return 2 if strength == "high" else 1

    def classify_delta(delta: float, high_thr: float, mid_thr: float) -> Tuple[str, str]:
        abs_delta = abs(delta)
        if abs_delta >= high_thr:
            return ("home" if delta > 0 else "away"), "high"
        if abs_delta >= mid_thr:
            return ("home" if delta > 0 else "away"), "mid"
        return "neutral", "low"

    def add_side_factor(name: str, home_val: Optional[float], away_val: Optional[float], high_thr: float, mid_thr: float) -> None:
        if home_val is None or away_val is None:
            return
        delta = float(home_val) - float(away_val)
        winner, strength = classify_delta(delta, high_thr=high_thr, mid_thr=mid_thr)
        factors.append({
            "name": name,
            "home": round(float(home_val), 3),
            "away": round(float(away_val), 3),
            "delta": round(delta, 3),
            "winner": winner,
            "strength": strength,
        })

    # Core live factors (period-aware first, then ALL)
    for metric_key, high_thr, mid_thr in [
        ("shots_on_target", 2.0, 1.0),
        ("total_shots", 6.0, 3.0),
        ("expected_goals", 0.6, 0.3),
        ("big_chances", 2.0, 1.0),
    ]:
        home_2nd, away_2nd = _stubet_metric_from_snapshot(snapshot, "2ND", metric_key)
        if home_2nd is not None and away_2nd is not None:
            add_side_factor(f"{metric_key}_2nd", home_2nd, away_2nd, high_thr, mid_thr)
        else:
            home_all, away_all = _stubet_metric_from_snapshot(snapshot, "ALL", metric_key)
            add_side_factor(f"{metric_key}_all", home_all, away_all, high_thr, mid_thr)

    # Momentum factors from graph
    momentum_recent_delta = float(home_recent_pressure) - float(away_recent_pressure)
    momentum_recent_winner, momentum_recent_strength = classify_delta(momentum_recent_delta, high_thr=140.0, mid_thr=60.0)
    factors.append({
        "name": "momentum_recent",
        "home": home_recent_pressure,
        "away": away_recent_pressure,
        "delta": round(momentum_recent_delta, 3),
        "winner": momentum_recent_winner,
        "strength": momentum_recent_strength,
    })

    momentum_full_delta = float(home_full_pressure) - float(away_full_pressure)
    momentum_full_winner, momentum_full_strength = classify_delta(momentum_full_delta, high_thr=260.0, mid_thr=110.0)
    factors.append({
        "name": "momentum_full",
        "home": home_full_pressure,
        "away": away_full_pressure,
        "delta": round(momentum_full_delta, 3),
        "winner": momentum_full_winner,
        "strength": momentum_full_strength,
    })

    # Score-state factor
    if home_score is not None and away_score is not None:
        score_delta = float(home_score - away_score)
        score_winner, score_strength = classify_delta(score_delta, high_thr=2.0, mid_thr=1.0)
        factors.append({
            "name": "score_state",
            "home": home_score,
            "away": away_score,
            "delta": round(score_delta, 3),
            "winner": score_winner,
            "strength": score_strength,
        })

    # Evaluate by market/pick
    selected_side = "home" if selection == "1X" else ("away" if selection == "X2" else None)

    support_points = 0
    oppose_points = 0

    if selected_side:
        opposite_side = "away" if selected_side == "home" else "home"
        support_points = sum(factor_points(str(item.get("strength") or "mid")) for item in factors if item.get("winner") == selected_side)
        oppose_points = sum(factor_points(str(item.get("strength") or "mid")) for item in factors if item.get("winner") == opposite_side)

        if support_points >= 4 and support_points >= (oppose_points + 2):
            reason = "ok"
            eligible = True
        elif oppose_points >= support_points:
            reason = "conflicting_live_signals"
            eligible = False
        else:
            reason = "insufficient_multi_signal_confirmation"
            eligible = False

        return {
            "eligible": eligible,
            "reason": reason,
            "selection": selection,
            "market": market,
            "support_points": support_points,
            "oppose_points": oppose_points,
            "max_minute": max_minute,
            "score_state": {"home": home_score, "away": away_score},
            "factors": factors,
        }

    # Goal-oriented markets (Over/Under + BTTS)
    # Reset factor list to keep diagnostics aligned with total-goal style picks.
    factors = []

    home_xg, away_xg = _stubet_metric_from_snapshot(snapshot, "ALL", "expected_goals")
    home_sot, away_sot = _stubet_metric_from_snapshot(snapshot, "ALL", "shots_on_target")
    home_shots, away_shots = _stubet_metric_from_snapshot(snapshot, "ALL", "total_shots")
    home_big, away_big = _stubet_metric_from_snapshot(snapshot, "ALL", "big_chances")

    total_goals = (home_score + away_score) if (home_score is not None and away_score is not None) else None
    total_xg = (float(home_xg) + float(away_xg)) if (home_xg is not None and away_xg is not None) else None
    total_sot = (float(home_sot) + float(away_sot)) if (home_sot is not None and away_sot is not None) else None
    total_shots = (float(home_shots) + float(away_shots)) if (home_shots is not None and away_shots is not None) else None
    total_big = (float(home_big) + float(away_big)) if (home_big is not None and away_big is not None) else None

    def add_binary_factor(name: str, supports_pick: Optional[bool], strength: str = "mid") -> None:
        if supports_pick is None:
            return
        factors.append({
            "name": name,
            "winner": "support" if supports_pick else "oppose",
            "strength": strength,
        })

    if selection == "Over 2.5":
        add_binary_factor("goals_state", None if total_goals is None else total_goals >= 2, "high")
        add_binary_factor("xg_total", None if total_xg is None else total_xg >= 2.2, "high")
        add_binary_factor("shots_on_target_total", None if total_sot is None else total_sot >= 8, "mid")
        add_binary_factor("shots_total", None if total_shots is None else total_shots >= 22, "mid")
        add_binary_factor("big_chances_total", None if total_big is None else total_big >= 4, "mid")
    elif selection == "Under 2.5":
        add_binary_factor("goals_state", None if total_goals is None else total_goals <= 1, "high")
        add_binary_factor("xg_total", None if total_xg is None else total_xg <= 1.6, "high")
        add_binary_factor("shots_on_target_total", None if total_sot is None else total_sot <= 5, "mid")
        add_binary_factor("shots_total", None if total_shots is None else total_shots <= 17, "mid")
        add_binary_factor("big_chances_total", None if total_big is None else total_big <= 2, "mid")
    elif selection == "BTTS Si":
        add_binary_factor("goals_both", None if total_goals is None else (home_score or 0) > 0 and (away_score or 0) > 0, "high")
        add_binary_factor("xg_both", None if (home_xg is None or away_xg is None) else float(home_xg) >= 0.8 and float(away_xg) >= 0.8, "high")
        add_binary_factor("sot_both", None if (home_sot is None or away_sot is None) else float(home_sot) >= 2 and float(away_sot) >= 2, "mid")
    elif selection == "BTTS No":
        add_binary_factor("goals_not_both", None if total_goals is None else not ((home_score or 0) > 0 and (away_score or 0) > 0), "high")
        add_binary_factor("xg_one_low", None if (home_xg is None or away_xg is None) else float(home_xg) <= 0.45 or float(away_xg) <= 0.45, "high")
        add_binary_factor("sot_one_low", None if (home_sot is None or away_sot is None) else float(home_sot) <= 1 or float(away_sot) <= 1, "mid")

    support_points = sum(factor_points(str(item.get("strength") or "mid")) for item in factors if item.get("winner") == "support")
    oppose_points = sum(factor_points(str(item.get("strength") or "mid")) for item in factors if item.get("winner") == "oppose")

    eligible = support_points >= 4 and support_points >= (oppose_points + 2)
    reason = "ok" if eligible else ("conflicting_live_signals" if oppose_points >= support_points else "insufficient_multi_signal_confirmation")

    return {
        "eligible": eligible,
        "reason": reason,
        "selection": selection,
        "market": market,
        "support_points": support_points,
        "oppose_points": oppose_points,
        "max_minute": max_minute,
        "score_state": {"home": home_score, "away": away_score},
        "factors": factors,
    }


def _stubet_live_signal_key(match_center: Dict[str, Any]) -> str:
    event_summary = match_center.get("event_summary", {}) if isinstance(match_center.get("event_summary"), dict) else {}
    lineup = match_center.get("lineup", {}) if isinstance(match_center.get("lineup"), dict) else {}
    home_team = event_summary.get("home_team", {}) if isinstance(event_summary.get("home_team"), dict) else {}
    away_team = event_summary.get("away_team", {}) if isinstance(event_summary.get("away_team"), dict) else {}

    home_score = _safe_int(home_team.get("score")) or 0
    away_score = _safe_int(away_team.get("score")) or 0

    countdown_minutes = _safe_int(lineup.get("countdown_minutes"))
    minute_guess = 0
    if isinstance(countdown_minutes, int) and countdown_minutes < 0:
        minute_guess = abs(countdown_minutes)

    incidents = match_center.get("incidents", []) if isinstance(match_center.get("incidents"), list) else []
    for row in incidents:
        if not isinstance(row, dict):
            continue
        minute_val = _safe_stat_float(row.get("time"))
        if minute_val is not None:
            minute_guess = max(minute_guess, int(minute_val))

    bucket = int((minute_guess // 5) * 5)
    return f"live_signal_{bucket}_{home_score}_{away_score}"


def _stubet_lineup_signal_message(current_report: Dict[str, Any], pre_report: Optional[Dict[str, Any]] = None) -> str:
    event = current_report.get("event", {}) if isinstance(current_report.get("event"), dict) else {}
    home_name = ((event.get("home_team") or {}).get("name") if isinstance(event.get("home_team"), dict) else None) or "Local"
    away_name = ((event.get("away_team") or {}).get("name") if isinstance(event.get("away_team"), dict) else None) or "Visitante"

    pred = current_report.get("prediction", {}) if isinstance(current_report.get("prediction"), dict) else {}
    selection = str(pred.get("selection") or "-")
    market = str(pred.get("market") or "-")
    confidence = _safe_stat_float(pred.get("confidence_pct")) or 0.0
    stake_text = _stubet_stake_text(pred.get("stake", {}) if isinstance(pred.get("stake"), dict) else {})

    odds_val = _safe_stat_float(pred.get("bookmaker_odds"))
    odds_text = f"{odds_val:.2f}" if odds_val is not None else "N/D"

    old_selection = None
    if isinstance(pre_report, dict):
        old_pred = pre_report.get("prediction", {}) if isinstance(pre_report.get("prediction"), dict) else {}
        old_selection = old_pred.get("selection")

    if old_selection:
        if str(old_selection) == selection:
            change_line = f"Sin cambio vs pre-match: {selection}."
        else:
            change_line = f"Cambio vs pre-match: {old_selection} -> {selection}."
    else:
        change_line = "No habia pre-match bloqueado para comparar."

    reasoning = pred.get("reasoning", []) if isinstance(pred.get("reasoning"), list) else []
    reason_lines = "\n".join([f"- {str(item)}" for item in reasoning[:3]]) or "- Muestra estadistica equilibrada, sesgo moderado."
    important_note = str(current_report.get("important_note") or "").strip()
    note_block = f"\n\n⚠️ <b>Nota importante:</b> {important_note}" if important_note else ""

    message = (
        "👑 <b>STUBET — LECTURA DE PARTIDO [LIVE STATS]</b>\n\n"
        f"⚔️ <b>{home_name} vs {away_name}</b>\n"
        "📌 <b>Etapa:</b> Alineaciones confirmadas\n"
        f"🎯 <b>Pick:</b> {selection} ({market})\n"
        f"📈 <b>Confianza:</b> {confidence:.1f}%\n"
        f"🏦 <b>Stake:</b> {stake_text}\n"
        f"💎 <b>Cuota referencia:</b> {odds_text}\n"
        f"🔄 <b>Comparativa:</b> {change_line}\n\n"
        "🧠 <b>Motivos clave</b>\n"
        f"{reason_lines}"
        f"{note_block}"
    )
    return message


def _stubet_live_signal_message(report: Dict[str, Any], live_profile: Optional[Dict[str, Any]] = None) -> str:
    event = report.get("event", {}) if isinstance(report.get("event"), dict) else {}
    home_name = ((event.get("home_team") or {}).get("name") if isinstance(event.get("home_team"), dict) else None) or "Local"
    away_name = ((event.get("away_team") or {}).get("name") if isinstance(event.get("away_team"), dict) else None) or "Visitante"

    pred = report.get("prediction", {}) if isinstance(report.get("prediction"), dict) else {}
    selection = str(pred.get("selection") or "-")
    market = str(pred.get("market") or "-")
    confidence = _safe_stat_float(pred.get("confidence_pct")) or 0.0
    stake_text = _stubet_stake_text(pred.get("stake", {}) if isinstance(pred.get("stake"), dict) else {})

    odds_val = _safe_stat_float(pred.get("bookmaker_odds"))
    odds_text = f"{odds_val:.2f}" if odds_val is not None else "N/D"

    reasoning = pred.get("reasoning", []) if isinstance(pred.get("reasoning"), list) else []
    reason_lines = "\n".join([f"- {str(item)}" for item in reasoning[:3]]) or "- Sin drivers dominantes en este minuto."

    important_note = str(report.get("important_note") or "").strip()
    note_block = f"\n\n⚠️ <b>Nota importante:</b> {important_note}" if important_note else ""

    profile_block = ""
    profile_factors_block = ""
    if isinstance(live_profile, dict):
        support_points = int(_safe_int(live_profile.get("support_points")) or 0)
        oppose_points = int(_safe_int(live_profile.get("oppose_points")) or 0)
        profile_reason = str(live_profile.get("reason") or "ok")
        profile_block = (
            "\n\n🧪 <b>Perfil LIVE:</b> "
            f"soporte={support_points} | conflicto={oppose_points} | estado={profile_reason}"
        )

        factors = live_profile.get("factors", []) if isinstance(live_profile.get("factors"), list) else []
        factor_lines: List[str] = []
        for factor in factors:
            if not isinstance(factor, dict):
                continue
            winner = str(factor.get("winner") or "").strip().lower()
            if winner in {"neutral", "", "low"}:
                continue
            name = str(factor.get("name") or "factor")
            strength = str(factor.get("strength") or "mid")
            delta = _safe_stat_float(factor.get("delta"))
            delta_text = f", delta={delta:+.2f}" if delta is not None else ""
            factor_lines.append(f"- {name}: {winner} ({strength}{delta_text})")
            if len(factor_lines) >= 3:
                break

        if factor_lines:
            profile_factors_block = "\n\n📊 <b>Drivers de confirmación</b>\n" + "\n".join(factor_lines)

    return (
        "👑 <b>STUBET — LECTURA DE PARTIDO [LIVE STATS]</b>\n\n"
        f"⚔️ <b>{home_name} vs {away_name}</b>\n"
        "📌 <b>Etapa:</b> LIVE\n"
        f"🎯 <b>Pick:</b> {selection} ({market})\n"
        f"📈 <b>Confianza:</b> {confidence:.1f}%\n"
        f"🏦 <b>Stake:</b> {stake_text}\n"
        f"💎 <b>Cuota LasPlatas:</b> {odds_text}\n\n"
        "🧠 <b>Motivos clave</b>\n"
        f"{reason_lines}"
        f"{profile_block}"
        f"{profile_factors_block}"
        f"{note_block}"
    )


@app.post("/api/stubet/analyst/sofascore/event/{event_id}/pre-match")
async def stubet_autonomous_pre_match(
    event_id: int,
    history_limit: int = Query(default=10, ge=5, le=20),
    include_odds: bool = Query(default=True),
    lock_prediction: bool = Query(default=True),
):
    """Generate (and optionally lock) autonomous pre-match analysis for a SofaScore event."""
    data = await get_sofascore_match_center(
        event_id=event_id,
        history_limit=history_limit,
        enrich_history_stats=True,
        refresh_history_stats=False,
        include_history_statistics=False,
    )

    event_summary = data.get("event_summary", {}) if isinstance(data.get("event_summary"), dict) else {}
    allowed, reason, runtime_window = _stubet_stage_allowed(event_summary, "pre_match")
    if not allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Event not eligible for pre-match analysis in current state.",
                "reason": reason,
                "runtime_window": runtime_window,
            },
        )

    odds_payload: Optional[Dict[str, Any]] = None
    if include_odds and isinstance(data, dict):
        home_team = event_summary.get("home_team", {}) if isinstance(event_summary.get("home_team"), dict) else {}
        away_team = event_summary.get("away_team", {}) if isinstance(event_summary.get("away_team"), dict) else {}
        home_name = str(home_team.get("name") or "")
        away_name = str(away_team.get("name") or "")
        if home_name and away_name:
            try:
                odds_payload = sync_get_match_odds(home_name, away_name)
            except Exception:
                odds_payload = {"status": "error", "odds": {}, "message": "odds_fetch_failed"}

    external_context = _stubet_fetch_external_context(data, odds_payload=odds_payload)

    report = autonomous_analyst.analyze_event(
        match_center=data,
        stage="pre_match",
        odds_payload=odds_payload,
        external_context=external_context,
        lock_prediction=lock_prediction,
    )

    if report.get("status") == "error":
        raise HTTPException(status_code=400, detail=str(report.get("message") or "autonomous_analysis_error"))

    return {
        "status": "success",
        "event_id": event_id,
        "runtime_window": runtime_window,
        "analysis": report,
    }


@app.post("/api/stubet/analyst/sofascore/event/{event_id}/lineup-confirmed")
async def stubet_autonomous_lineup_signal(
    event_id: int,
    history_limit: int = Query(default=10, ge=5, le=20),
    include_odds: bool = Query(default=True),
    send_telegram: bool = Query(default=True),
):
    """Re-analyze with latest lineups and optionally push signal to Telegram when lineups are confirmed."""
    data = await get_sofascore_match_center(
        event_id=event_id,
        history_limit=history_limit,
        enrich_history_stats=True,
        refresh_history_stats=False,
        include_history_statistics=False,
    )

    event_summary = data.get("event_summary", {}) if isinstance(data.get("event_summary"), dict) else {}
    allowed, reason, runtime_window = _stubet_stage_allowed(event_summary, "lineup_confirmed")
    if not allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Event not eligible for lineup-confirmed signal in current state.",
                "reason": reason,
                "runtime_window": runtime_window,
            },
        )

    odds_payload: Optional[Dict[str, Any]] = None
    if include_odds and isinstance(data, dict):
        home_team = event_summary.get("home_team", {}) if isinstance(event_summary.get("home_team"), dict) else {}
        away_team = event_summary.get("away_team", {}) if isinstance(event_summary.get("away_team"), dict) else {}
        home_name = str(home_team.get("name") or "")
        away_name = str(away_team.get("name") or "")
        if home_name and away_name:
            try:
                odds_payload = sync_get_match_odds(home_name, away_name)
            except Exception:
                odds_payload = {"status": "error", "odds": {}, "message": "odds_fetch_failed"}

    external_context = _stubet_fetch_external_context(data, odds_payload=odds_payload)

    report = autonomous_analyst.analyze_event(
        match_center=data,
        stage="lineup_confirmed",
        odds_payload=odds_payload,
        external_context=external_context,
        lock_prediction=False,
    )

    if report.get("status") == "error":
        raise HTTPException(status_code=400, detail=str(report.get("message") or "autonomous_analysis_error"))

    state = autonomous_analyst.get_event_state(event_id)
    pre_report = state.get("pre_match", {}) if isinstance(state.get("pre_match"), dict) else {}
    lineup_adjustment = report.get("lineup_adjustment", {}) if isinstance(report.get("lineup_adjustment"), dict) else {}
    lineups_confirmed = bool(lineup_adjustment.get("lineups_confirmed"))

    telegram_result = {
        "requested": send_telegram,
        "sent": False,
        "reason": "not_requested",
        "odds_floor": STUBET_MIN_TELEGRAM_ODDS,
    }
    if send_telegram:
        if not lineups_confirmed:
            telegram_result["reason"] = "lineups_not_confirmed"
        elif autonomous_analyst.signal_already_sent(event_id, "lineup_confirmed"):
            telegram_result["reason"] = "already_sent"
        else:
            odds_ok, odds_reason, odds_val = _stubet_prediction_odds_gate(report)
            telegram_result["odds"] = odds_val
            if not odds_ok:
                telegram_result["reason"] = odds_reason
            else:
                message = _stubet_lineup_signal_message(report, pre_report)
                sent = telegram.send_message(message)
                telegram_result = {
                    "requested": True,
                    "sent": bool(sent),
                    "reason": "sent" if sent else "send_failed",
                    "odds_floor": STUBET_MIN_TELEGRAM_ODDS,
                    "odds": odds_val,
                }
                if sent:
                    autonomous_analyst.mark_signal_sent(
                        event_id,
                        "lineup_confirmed",
                        {
                            "selection": ((report.get("prediction") or {}).get("selection") if isinstance(report.get("prediction"), dict) else None),
                            "stake": ((report.get("prediction") or {}).get("stake") if isinstance(report.get("prediction"), dict) else None),
                            "odds": odds_val,
                        },
                    )

    return {
        "status": "success",
        "event_id": event_id,
        "runtime_window": runtime_window,
        "lineups_confirmed": lineups_confirmed,
        "changed_vs_pre_match": bool(lineup_adjustment.get("changed_vs_pre_match")),
        "telegram": telegram_result,
        "analysis": report,
    }


@app.get("/api/stubet/analyst/sofascore/event/{event_id}/power-context")
async def stubet_autonomous_power_context(
    event_id: int,
    history_limit: int = Query(default=10, ge=5, le=20),
    include_odds: bool = Query(default=True),
):
    """Get STUBET power context (match-center + news/injuries + important external note)."""
    data = await get_sofascore_match_center(
        event_id=event_id,
        history_limit=history_limit,
        enrich_history_stats=True,
        refresh_history_stats=False,
        include_history_statistics=False,
    )

    event_summary = data.get("event_summary", {}) if isinstance(data.get("event_summary"), dict) else {}
    runtime_window = _stubet_event_runtime_window(event_summary)

    odds_payload: Optional[Dict[str, Any]] = None
    if include_odds and isinstance(data, dict):
        home_team = event_summary.get("home_team", {}) if isinstance(event_summary.get("home_team"), dict) else {}
        away_team = event_summary.get("away_team", {}) if isinstance(event_summary.get("away_team"), dict) else {}
        home_name = str(home_team.get("name") or "")
        away_name = str(away_team.get("name") or "")
        if home_name and away_name:
            try:
                odds_payload = sync_get_match_odds(home_name, away_name)
            except Exception:
                odds_payload = {"status": "error", "odds": {}, "message": "odds_fetch_failed"}

    external_context = _stubet_fetch_external_context(data, odds_payload=odds_payload)

    probe_stage = "live" if runtime_window.get("status_type") in {"inprogress", "halftime"} else "pre_match"
    probe = autonomous_analyst.analyze_event(
        match_center=data,
        stage=probe_stage,
        odds_payload=odds_payload,
        external_context=external_context,
        lock_prediction=False,
    )

    return {
        "status": "success",
        "event_id": event_id,
        "stage_probe": probe_stage,
        "runtime_window": runtime_window,
        "important_note": probe.get("important_note") if isinstance(probe, dict) else None,
        "external_factors": probe.get("external_factors") if isinstance(probe, dict) else None,
        "power_context": external_context,
    }


@app.post("/api/stubet/analyst/sofascore/event/{event_id}/live-signal")
async def stubet_autonomous_live_signal(
    event_id: int,
    history_limit: int = Query(default=10, ge=5, le=20),
    include_odds: bool = Query(default=True),
    send_telegram: bool = Query(default=True),
):
    """Generate STUBET in-play signal from live match-center and optionally send Telegram alert."""
    data = await get_sofascore_match_center(
        event_id=event_id,
        history_limit=history_limit,
        enrich_history_stats=True,
        refresh_history_stats=False,
        include_history_statistics=False,
    )

    event_summary = data.get("event_summary", {}) if isinstance(data.get("event_summary"), dict) else {}
    allowed, reason, runtime_window = _stubet_stage_allowed(event_summary, "live")
    if not allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Event not eligible for live signal in current state.",
                "reason": reason,
                "runtime_window": runtime_window,
            },
        )

    odds_payload: Optional[Dict[str, Any]] = None
    if include_odds and isinstance(data, dict):
        home_team = event_summary.get("home_team", {}) if isinstance(event_summary.get("home_team"), dict) else {}
        away_team = event_summary.get("away_team", {}) if isinstance(event_summary.get("away_team"), dict) else {}
        home_name = str(home_team.get("name") or "")
        away_name = str(away_team.get("name") or "")
        if home_name and away_name:
            try:
                odds_payload = sync_get_match_odds(home_name, away_name)
            except Exception:
                odds_payload = {"status": "error", "odds": {}, "message": "odds_fetch_failed"}

    external_context = _stubet_fetch_external_context(data, odds_payload=odds_payload)

    report = autonomous_analyst.analyze_event(
        match_center=data,
        stage="live",
        odds_payload=odds_payload,
        external_context=external_context,
        lock_prediction=False,
    )

    if report.get("status") == "error":
        raise HTTPException(status_code=400, detail=str(report.get("message") or "autonomous_analysis_error"))

    live_profile = _stubet_live_profile_assessment(data, report)
    profile_gate = {
        "eligible": bool(live_profile.get("eligible")),
        "reason": str(live_profile.get("reason") or "unknown"),
        "support_points": int(_safe_int(live_profile.get("support_points")) or 0),
        "oppose_points": int(_safe_int(live_profile.get("oppose_points")) or 0),
    }

    signal_key = _stubet_live_signal_key(data)
    telegram_result = {
        "requested": send_telegram,
        "sent": False,
        "reason": "not_requested",
        "signal_key": signal_key,
        "odds_floor": STUBET_MIN_TELEGRAM_ODDS,
        "live_profile": profile_gate,
    }

    if send_telegram:
        odds_ok, odds_reason, odds_val = _stubet_prediction_odds_gate(report)
        telegram_result["odds"] = odds_val
        if not profile_gate["eligible"]:
            telegram_result["reason"] = profile_gate["reason"]
        elif not odds_ok:
            telegram_result["reason"] = odds_reason
        elif autonomous_analyst.signal_already_sent(event_id, signal_key):
            telegram_result["reason"] = "already_sent_bucket"
        else:
            message = _stubet_live_signal_message(report, live_profile=live_profile)
            sent = telegram.send_message(message)
            telegram_result = {
                "requested": True,
                "sent": bool(sent),
                "reason": "sent" if sent else "send_failed",
                "signal_key": signal_key,
                "odds_floor": STUBET_MIN_TELEGRAM_ODDS,
                "odds": odds_val,
                "live_profile": profile_gate,
            }
            if sent:
                autonomous_analyst.mark_signal_sent(
                    event_id,
                    signal_key,
                    {
                        "selection": ((report.get("prediction") or {}).get("selection") if isinstance(report.get("prediction"), dict) else None),
                        "stake": ((report.get("prediction") or {}).get("stake") if isinstance(report.get("prediction"), dict) else None),
                        "odds": odds_val,
                    },
                )

    return {
        "status": "success",
        "event_id": event_id,
        "runtime_window": runtime_window,
        "telegram": telegram_result,
        "analysis": report,
        "live_profile": live_profile,
    }


@app.post("/api/stubet/analyst/sofascore/event/{event_id}/post-match-learn")
async def stubet_autonomous_post_match_learning(
    event_id: int,
    history_limit: int = Query(default=10, ge=5, le=20),
    prefer_lineup_prediction: bool = Query(default=True),
):
    """Evaluate frozen predictions vs real result and apply autonomous learning updates."""
    data = await get_sofascore_match_center(
        event_id=event_id,
        history_limit=history_limit,
        enrich_history_stats=True,
        refresh_history_stats=False,
        include_history_statistics=False,
    )

    post = autonomous_analyst.evaluate_post_match(
        match_center=data,
        prefer_lineup_prediction=prefer_lineup_prediction,
    )

    status = str(post.get("status") or "")
    if status == "error":
        raise HTTPException(status_code=400, detail=str(post.get("message") or "post_match_learning_error"))

    return {
        "status": status or "success",
        "event_id": event_id,
        "post_match": post,
    }


@app.get("/api/stubet/analyst/sofascore/event/{event_id}/state")
async def stubet_autonomous_event_state(event_id: int):
    """Get stored autonomous analyst state for an event (pre-match, lineup, post-match, signals)."""
    return {
        "status": "success",
        "event_id": event_id,
        "state": autonomous_analyst.get_event_state(event_id),
    }


# ==================== MULTI-SPORT: NBA & TENNIS (FASE 2) ====================

ESPN_SPORT_MAP = {
    # Basketball
    "nba": "basketball/nba",
    "euroleague": "basketball/euroleague",
    # Tennis
    "atp": "tennis/atp",
    "wta": "tennis/wta",
    # Soccer (already handled)
}

@app.get("/api/multisport/scoreboard/{sport_key}")
async def get_multisport_scoreboard(sport_key: str, date: Optional[str] = None, upcoming_only: bool = False):
    """Get live scores for NBA, Tennis, etc. from ESPN (FREE, unlimited).
    Set upcoming_only=true to exclude finished matches (only show scheduled + in-progress)."""
    try:
        espn_path = ESPN_SPORT_MAP.get(sport_key)
        if not espn_path:
            return {"matches": [], "error": f"Sport '{sport_key}' not supported"}
        
        url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_path}/scoreboard"
        params = {}
        if date:
            params["dates"] = date
        
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
        
        events = data.get("events", [])
        matches = []
        is_tennis = sport_key in ("atp", "wta")
        
        if is_tennis:
            # Tennis: events are tournaments with groupings â competitions (individual matches)
            for ev in events:
                tournament_name = ev.get("name", "")
                for grouping in ev.get("groupings", []):
                    group_name = grouping.get("grouping", {}).get("displayName", "")
                    for comp in grouping.get("competitions", []):
                        competitors = comp.get("competitors", [])
                        p1 = competitors[0] if len(competitors) > 0 else {}
                        p2 = competitors[1] if len(competitors) > 1 else {}
                        status = comp.get("status", {})
                        
                        # Tennis uses athlete, not team
                        def get_tennis_info(player, opponent):
                            athlete = player.get("athlete", {})
                            roster = player.get("roster", {})
                            name = athlete.get("displayName") or roster.get("displayName", "?")
                            flag = athlete.get("flag", {}).get("href", "")
                            
                            # Calculate global sets won
                            sets_won = 0
                            my_lines = player.get("linescores", [])
                            opp_lines = opponent.get("linescores", [])
                            for i in range(min(len(my_lines), len(opp_lines))):
                                if my_lines[i].get("value", 0) > opp_lines[i].get("value", 0):
                                    sets_won += 1
                                    
                            return {
                                "id": player.get("id"),
                                "name": name,
                                "abbreviation": "",
                                "logo": flag,
                                "score": str(sets_won),
                                "country": athlete.get("flag", {}).get("alt", ""),
                                "winner": player.get("winner", False),
                                "linescores": player.get("linescores", []),
                            }
                        
                        match_info = {
                            "id": comp.get("id"),
                            "name": f"{tournament_name} - {group_name}",
                            "shortName": comp.get("notes", [{}])[0].get("text", "") if comp.get("notes") else "",
                            "date": comp.get("date", ""),
                            "status": status.get("type", {}).get("description", ""),
                            "statusDetail": status.get("type", {}).get("detail", ""),
                            "isLive": status.get("type", {}).get("state") == "in",
                            "home": get_tennis_info(p1, p2),
                            "away": get_tennis_info(p2, p1),
                            "venue": comp.get("venue", {}).get("fullName", ""),
                            "round": comp.get("round", {}).get("displayName", ""),
                            "broadcast": comp.get("broadcast", ""),
                            "sport": sport_key,
                        }
                        matches.append(match_info)
        else:
            # NBA / team sports: events â competitions â competitors â team
            for ev in events:
                comp = ev.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])
                
                home = competitors[0] if len(competitors) > 0 else {}
                away = competitors[1] if len(competitors) > 1 else {}
                
                status = comp.get("status", {})
                
                match_info = {
                    "id": ev.get("id"),
                    "name": ev.get("name", ""),
                    "shortName": ev.get("shortName", ""),
                    "date": ev.get("date", ""),
                    "status": status.get("type", {}).get("description", ""),
                    "statusDetail": status.get("type", {}).get("detail", ""),
                    "isLive": status.get("type", {}).get("state") == "in",
                    "home": {
                        "id": home.get("id"),
                        "name": home.get("team", {}).get("displayName", "?"),
                        "abbreviation": home.get("team", {}).get("abbreviation", ""),
                        "logo": home.get("team", {}).get("logo", ""),
                        "score": home.get("score", "0"),
                        "records": home.get("records", []),
                        "winner": home.get("winner", False),
                    },
                    "away": {
                        "id": away.get("id"),
                        "name": away.get("team", {}).get("displayName", "?"),
                        "abbreviation": away.get("team", {}).get("abbreviation", ""),
                        "logo": away.get("team", {}).get("logo", ""),
                        "score": away.get("score", "0"),
                        "records": away.get("records", []),
                        "winner": away.get("winner", False),
                    },
                    "venue": comp.get("venue", {}).get("fullName", ""),
                    "broadcast": ", ".join(b.get("names", [""])[0] for b in comp.get("broadcasts", []) if b.get("names")),
                    "sport": sport_key,
                }
                matches.append(match_info)
        
        if upcoming_only:
            # Keep only 'Scheduled' or 'In Progress' / exclude 'Final'
            matches = [m for m in matches if m["status"] not in ("Final", "Postponed", "Canceled")]
            
        return {"matches": matches, "count": len(matches), "source": "espn", "sport": sport_key}
    except Exception as e:
        return {"matches": [], "error": str(e)}


@app.post("/api/multisport/predict")
async def predict_multisport(data: dict):
    """Generate on-the-fly predictions for NBA/Tennis matches."""
    sport_key = data.get("sport")
    match_info = data.get("match", {})
    
    predictions = []
    if sport_key == "nba":
        from analysis.nba_predictor import NBAPredictor
        predictor = NBAPredictor(db)
        predictions = predictor.analyze_match(match_info)
    elif sport_key in ("atp", "wta", "tennis"):
        from analysis.tennis_predictor import TennisPredictor
        predictor = TennisPredictor(db)
        predictions = predictor.analyze_match(match_info)
    
    return {"status": "success", "sport": sport_key, "predictions": predictions}


@app.get("/api/multisport/news/{sport_key}")
async def get_multisport_news(sport_key: str):
    """Get news for NBA, Tennis from ESPN (FREE)."""
    try:
        espn_path = ESPN_SPORT_MAP.get(sport_key)
        if not espn_path:
            return {"news": [], "error": f"Sport '{sport_key}' not supported"}
        
        url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_path}/news"
        
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
        
        articles = data.get("articles", [])
        news = []
        for article in articles[:20]:
            news.append({
                "headline": article.get("headline", ""),
                "description": article.get("description", ""),
                "published": article.get("published", ""),
                "type": article.get("type", "Story"),
                "link": article.get("links", {}).get("web", {}).get("href", ""),
                "images": [img.get("url") for img in article.get("images", [])[:1]],
                "categories": [c.get("description", "") for c in article.get("categories", [])[:3]],
            })
        
        return {"news": news, "count": len(news), "source": "espn", "sport": sport_key}
    except Exception as e:
        return {"news": [], "error": str(e)}

# ==================== BANKROLL & PICKS (MAYO 2026) ====================

from pydantic import BaseModel
from datetime import datetime

class BankrollReq(BaseModel):
    amount: float
    bookmaker: str = 'lasplatas'  # lasplatas | metabet

class ManualPickReq(BaseModel):
    match: str
    market: str
    odds: float
    stake: float
    ticket_id: Optional[str] = None
    bookmaker: str = 'lasplatas'
    placed_at: Optional[str] = None

def _get_current_month():
    return datetime.now().strftime("%Y-%m")

@app.get("/api/bankroll")
async def get_bankroll(bookmaker: Optional[str] = None):
    """Obtener bankroll del mes actual. Sin bookmaker devuelve todos."""
    month = _get_current_month()
    return db.get_bankroll(month, bookmaker)

@app.post("/api/bankroll")
async def set_bankroll(req: BankrollReq):
    """Fijar bankroll inicial del mes para una casa de apuestas."""
    month = _get_current_month()
    db.set_bankroll(month, req.amount, req.bookmaker)
    return {"status": "success", "month": month, "amount": req.amount, "bookmaker": req.bookmaker}

@app.get("/api/picks")
async def get_picks(bookmaker: Optional[str] = None, date: Optional[str] = None):
    """Obtener apuestas manuales. Si se pasa date (YYYY-MM-DD), filtra por ese dÃ­a."""
    if date:
        return db.get_manual_picks_by_date(date, bookmaker)
    month = _get_current_month()
    return db.get_manual_picks(month, bookmaker)

@app.post("/api/picks/auto-resolve")
async def auto_resolve_picks():
    """Intenta resolver automÃ¡ticamente picks pendientes usando SofaScore."""
    # TODO: Implement full matching logic. For now return a message.
    return {"status": "success", "message": "Funcionalidad de seguimiento automÃ¡tico en desarrollo."}

@app.post("/api/picks")
async def add_pick(req: ManualPickReq):
    """Agregar apuesta manual o por cupón."""
    month = _get_current_month()
    pick_data = {
        "month_year": month,
        "match_name": req.match,
        "market": req.market,
        "odds": req.odds,
        "stake": req.stake,
        "ticket_id": req.ticket_id,
        "bookmaker": req.bookmaker,
        "placed_at": req.placed_at
    }
    pick_id = db.add_manual_pick(pick_data)
    return {"status": "success", "id": pick_id}

@app.delete("/api/picks/{pick_id}")
async def delete_pick(pick_id: int):
    """Borrar apuesta manual y devolver dinero."""
    success = db.delete_manual_pick(pick_id)
    if success:
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Pick no encontrado")

@app.get("/api/picks/{pick_id}")
async def get_pick(pick_id: int):
    """Obtener un solo pick por ID."""
    pick = db.get_manual_pick(pick_id)
    if pick:
        return pick
    raise HTTPException(status_code=404, detail="Pick no encontrado")

@app.put("/api/picks/{pick_id}")
async def update_pick(pick_id: int, req: ManualPickReq):
    """Actualizar datos de una apuesta (solo si está pendiente)."""
    pick_data = {
        "match_name": req.match,
        "market": req.market,
        "odds": req.odds,
        "stake": req.stake,
        "bookmaker": req.bookmaker,
        "placed_at": req.placed_at
    }
    success = db.update_manual_pick(pick_id, pick_data)
    if success:
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="No se pudo actualizar (quizás ya está resuelto o no existe).")

class SettlePickReq(BaseModel):
    result: str  # 'WON', 'LOST', or 'PENDING'

@app.post("/api/picks/{pick_id}/settle")
async def settle_pick(pick_id: int, req: SettlePickReq):
    """Marcar apuesta como ganada o perdida."""
    success = db.settle_manual_pick(pick_id, req.result.upper())
    if success:
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="No se pudo resolver el pick (quizás ya está resuelto o no existe).")

class TicketReq(BaseModel):
    ticket_id: str
    bookmaker: str = 'lasplatas'  # lasplatas | metabet

@app.post("/api/scraper/ticket")
async def scan_ticket(req: TicketReq):
    """Extraer información de un cupón/link de LasPlatas o Metabet."""
    input_val = req.ticket_id.strip()
    bookmaker = req.bookmaker.lower()
    
    # Auto-detect bookmaker from input
    if "metabet" in input_val.lower() or input_val.startswith("http"):
        bookmaker = "metabet"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*"
    }

    # ==================== METABET (Link-based) ====================
    if bookmaker == "metabet":
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(input_val, headers=headers, timeout=15)
                if resp.status_code == 200:
                    html = resp.text
                    # Try to extract bet info from the Metabet share page
                    # Common patterns: team names, odds, market from the HTML/JSON
                    import re
                    
                    # Try JSON-LD or embedded data
                    json_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
                    if not json_match:
                        json_match = re.search(r'data-bet["\']?\s*[:=]\s*["\']?({.*?})["\']?', html, re.DOTALL)
                    
                    if json_match:
                        try:
                            bet_data = json.loads(json_match.group(1))
                            return {
                                "status": "success",
                                "bookmaker": "metabet",
                                "match": bet_data.get("eventName", bet_data.get("match", "Partido Metabet")),
                                "market": bet_data.get("marketName", bet_data.get("market", "Mercado")),
                                "odds": float(bet_data.get("odds", bet_data.get("price", 1.85))),
                                "stake": float(bet_data.get("stake", 10.0))
                            }
                        except:
                            pass
                    
                    # Fallback: try to extract from page title/meta tags
                    title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
                    og_match = re.search(r'og:description["\s]+content="([^"]+)"', html, re.IGNORECASE)
                    
                    match_name = "Partido Metabet"
                    if title_match:
                        match_name = title_match.group(1).strip()
                    if og_match:
                        match_name = og_match.group(1).strip()
                    
                    # Try to find odds in the page
                    odds_matches = re.findall(r'(?:cuota|odds?|price)["\s:]+(\d+\.?\d*)', html, re.IGNORECASE)
                    found_odds = float(odds_matches[0]) if odds_matches else 0.0
                    
                    return {
                        "status": "success",
                        "bookmaker": "metabet",
                        "match": match_name[:100],
                        "market": "Extraido de link Metabet",
                        "odds": found_odds,
                        "stake": 0.0,
                        "note": "Verifica los datos. Link procesado pero puede requerir ajuste manual."
                    }
        except Exception as e:
            print(f"[Metabet Scraper Error] {e}")
        
        return {
            "status": "error",
            "bookmaker": "metabet",
            "message": f"No se pudo leer el link de Metabet. Ingresa los datos manualmente.",
            "match": f"Link Metabet",
            "market": "N/A",
            "odds": 0.0,
            "stake": 0.0
        }

    # ==================== LASPLATAS (Code-based) ====================
    code = input_val.upper()
    
    # 1. Intentar como código de reserva de Altenar (Betslip/FindReservedBet)
    url_reserve = "https://sb2commongateway-altenar2.biahosted.com/api/Betslip/FindReservedBet"
    params = {
        "culture": "es-ES",
        "timezoneOffset": "240",
        "integration": "lasplatas",
        "deviceType": "1",
        "numFormat": "en-GB",
        "reservationCode": code
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url_reserve, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data and "selections" in data and len(data["selections"]) > 0:
                    # Build match name from all selections
                    sel_names = [s.get("eventName", "") for s in data["selections"]]
                    match_str = " / ".join(filter(None, sel_names))
                    
                    # Build market info
                    markets = [f"{s.get('marketName', '')} ({s.get('oddName', '')})" for s in data["selections"]]
                    market_str = " | ".join(filter(None, markets))
                    
                    # Total odds (multiply all)
                    total_odds = 1.0
                    for s in data["selections"]:
                        total_odds *= s.get("price", 1.0)
                    
                    return {
                        "status": "success",
                        "bookmaker": "lasplatas",
                        "match": match_str or f"Cupón {code}",
                        "market": market_str or "Mercado detectado",
                        "odds": round(total_odds, 2),
                        "stake": data.get("totalStake", 10.0),
                        "selections_count": len(data["selections"])
                    }
            
            # 2. Si falla como reserva, intentar como ShareCode (Storage/GetValue)
            url_share = "https://sb2social-altenar2.biahosted.com/api/Storage/GetValue"
            params_share = {**params, "key": code}
            resp_share = await client.get(url_share, params=params_share, headers=headers, timeout=10)
            
            if resp_share.status_code == 200:
                data_share = resp_share.json()
                if data_share and "value" in data_share:
                    try:
                        parsed_val = json.loads(data_share["value"])
                        if "selections" in parsed_val and len(parsed_val["selections"]) > 0:
                            sel = parsed_val["selections"][0]
                            return {
                                "status": "success",
                                "bookmaker": "lasplatas",
                                "match": sel.get("eventName", f"Cupón {code}"),
                                "market": f"{sel.get('marketName', 'Desconocido')} - {sel.get('oddName', '')}",
                                "odds": sel.get("price", 1.0),
                                "stake": parsed_val.get("stake", 10.0)
                            }
                    except:
                        pass
                        
    except Exception as e:
        print(f"[LasPlatas Scraper Error] {e}")

    return {
        "status": "error",
        "bookmaker": "lasplatas",
        "message": f"No se pudo resolver el código {code} en LasPlatas.",
        "match": f"Desconocido ({code})",
        "market": "N/A",
        "odds": 0.0,
        "stake": 0.0
    }

# ==================== RUN ====================

def start_server():
    """Start the FastAPI server."""
    import uvicorn  # type: ignore
    print("\n Starting Sports AI Predictor Server...")
    print(f" Dashboard: http://localhost:{SERVER_PORT}")
    print(f" API Docs: http://localhost:{SERVER_PORT}/docs")
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)


if __name__ == "__main__":
    start_server()
