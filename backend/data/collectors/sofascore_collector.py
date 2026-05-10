"""
SofaScore historical collector.

Collects finished football events globally and stores:
- Normalized event snapshot
- Team snapshots
- Raw payloads (event details, lineups, incidents, statistics, graph)
"""
import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

from data.database import DatabaseManager


class SofaScoreCollector:
    """Collects post-match historical data from SofaScore API endpoints."""

    BASE_URL = "https://www.sofascore.com/api/v1"

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

    @staticmethod
    def _is_finished_event(event: Dict[str, Any]) -> bool:
        status = event.get("status", {}) if isinstance(event, dict) else {}
        status_type = str(status.get("type", "")).lower().strip()
        status_code = int(status.get("code", 0) or 0)
        return status_type == "finished" or status_code in {100, 110, 120}

    @staticmethod
    def _match_date_from_timestamp(start_timestamp: Optional[int], fallback_date: str) -> str:
        if start_timestamp:
            try:
                return datetime.utcfromtimestamp(int(start_timestamp)).isoformat() + "Z"
            except Exception:
                pass
        return fallback_date

    async def _fetch_json(self, page, url: str) -> Optional[Dict[str, Any]]:
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if not response or response.status != 200:
                return None
            text = await page.evaluate("document.body.innerText")
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _upsert_teams_from_event(self, event: Dict[str, Any]):
        for side in ("homeTeam", "awayTeam"):
            team = event.get(side, {}) if isinstance(event, dict) else {}
            if not isinstance(team, dict):
                continue

            team_id = team.get("id")
            if not team_id:
                continue

            country = team.get("country", {}) if isinstance(team.get("country"), dict) else {}
            sport = team.get("sport", {}) if isinstance(team.get("sport"), dict) else {}

            self.db.upsert_sofascore_team({
                "sofascore_id": int(team_id),
                "name": team.get("name"),
                "short_name": team.get("shortName"),
                "country": country.get("name") or country.get("slug"),
                "gender": team.get("gender"),
                "sport": sport.get("slug"),
                "raw_json": team,
            })

    def _upsert_match_from_event(self, event: Dict[str, Any], fallback_date: str):
        status = event.get("status", {}) if isinstance(event.get("status"), dict) else {}
        tournament = event.get("tournament", {}) if isinstance(event.get("tournament"), dict) else {}
        category = tournament.get("category", {}) if isinstance(tournament.get("category"), dict) else {}
        season = event.get("season", {}) if isinstance(event.get("season"), dict) else {}
        round_info = event.get("roundInfo", {}) if isinstance(event.get("roundInfo"), dict) else {}
        home_team = event.get("homeTeam", {}) if isinstance(event.get("homeTeam"), dict) else {}
        away_team = event.get("awayTeam", {}) if isinstance(event.get("awayTeam"), dict) else {}
        home_score = event.get("homeScore", {}) if isinstance(event.get("homeScore"), dict) else {}
        away_score = event.get("awayScore", {}) if isinstance(event.get("awayScore"), dict) else {}

        home_team_id = int(home_team.get("id")) if home_team.get("id") else None
        away_team_id = int(away_team.get("id")) if away_team.get("id") else None
        if not home_team_id or not away_team_id:
            return

        start_timestamp = event.get("startTimestamp")
        self.db.upsert_sofascore_match({
            "event_id": int(event.get("id")),
            "start_timestamp": int(start_timestamp) if start_timestamp else None,
            "match_date": self._match_date_from_timestamp(start_timestamp, fallback_date),
            "status_code": int(status.get("code", 0) or 0),
            "status_type": status.get("type"),
            "status_description": status.get("description"),
            "league_name": tournament.get("name"),
            "league_slug": tournament.get("slug"),
            "category_name": category.get("name"),
            "category_slug": category.get("slug"),
            "season_name": season.get("name") or season.get("year"),
            "round_info": json.dumps(round_info) if round_info else None,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_team_name": home_team.get("name"),
            "away_team_name": away_team.get("name"),
            "home_score": home_score.get("current"),
            "away_score": away_score.get("current"),
            "home_score_ht": home_score.get("period1"),
            "away_score_ht": away_score.get("period1"),
            "winner_code": event.get("winnerCode"),
            "has_xg": bool(event.get("hasXg")),
            "has_player_stats": bool(event.get("hasEventPlayerStatistics")),
            "raw_event_json": event,
        })

    async def _collect_event_payloads(self, page, event_id: int) -> Dict[str, int]:
        endpoints = {
            "event_details": f"{self.BASE_URL}/event/{event_id}",
            "lineups": f"{self.BASE_URL}/event/{event_id}/lineups",
            "incidents": f"{self.BASE_URL}/event/{event_id}/incidents",
            "statistics": f"{self.BASE_URL}/event/{event_id}/statistics",
            "graph": f"{self.BASE_URL}/event/{event_id}/graph",
        }

        saved = 0
        attempted = 0

        for payload_type, url in endpoints.items():
            attempted += 1
            payload = await self._fetch_json(page, url)
            if payload is None:
                continue
            self.db.upsert_sofascore_payload(event_id, payload_type, payload)
            saved += 1

        return {"payloads_saved": saved, "payloads_attempted": attempted}

    async def collect_date(self, date_str: str, only_finished: bool = True, max_events: int = 0) -> Dict[str, Any]:
        """Collect and store events for a given YYYY-MM-DD date."""
        from playwright.async_api import async_playwright  # type: ignore

        url = f"{self.BASE_URL}/sport/football/scheduled-events/{date_str}"
        summary: Dict[str, Any] = {
            "date": date_str,
            "events_seen": 0,
            "events_processed": 0,
            "payloads_saved": 0,
            "payloads_attempted": 0,
        }

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_extra_http_headers({"User-Agent": self.user_agent})

            payload = await self._fetch_json(page, url) or {}
            events = payload.get("events", []) if isinstance(payload, dict) else []
            if not isinstance(events, list):
                events = []

            summary["events_seen"] = len(events)

            if only_finished:
                events = [event for event in events if self._is_finished_event(event)]

            if max_events and max_events > 0:
                events = events[:max_events]

            for event in events:
                event_id = event.get("id") if isinstance(event, dict) else None
                if not event_id:
                    continue

                self._upsert_teams_from_event(event)
                self._upsert_match_from_event(event, date_str)
                stats = await self._collect_event_payloads(page, int(event_id))

                summary["events_processed"] += 1
                summary["payloads_saved"] += stats["payloads_saved"]
                summary["payloads_attempted"] += stats["payloads_attempted"]

            await browser.close()

        return summary

    async def sync_recent_finished(self, days_back: int = 2, max_events_per_day: int = 0) -> Dict[str, Any]:
        """Sync finished events for today and N previous days."""
        end_day = date.today()
        start_day = end_day - timedelta(days=max(days_back, 0))
        return await self.backfill_finished(start_day.isoformat(), end_day.isoformat(), max_events_per_day=max_events_per_day)

    async def backfill_finished(self, start_date: str, end_date: str, max_events_per_day: int = 0) -> Dict[str, Any]:
        """Backfill finished events across a date range (inclusive)."""
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end < start:
            raise ValueError("end_date must be greater than or equal to start_date")

        days = (end - start).days + 1
        details: List[Dict[str, Any]] = []
        totals = {
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "events_seen": 0,
            "events_processed": 0,
            "payloads_saved": 0,
            "payloads_attempted": 0,
            "by_date": details,
        }

        for offset in range(days):
            current = start + timedelta(days=offset)
            daily = await self.collect_date(
                current.isoformat(),
                only_finished=True,
                max_events=max_events_per_day,
            )
            details.append(daily)
            totals["events_seen"] += int(daily.get("events_seen", 0))
            totals["events_processed"] += int(daily.get("events_processed", 0))
            totals["payloads_saved"] += int(daily.get("payloads_saved", 0))
            totals["payloads_attempted"] += int(daily.get("payloads_attempted", 0))

            await asyncio.sleep(0.2)

        return totals


async def _run_cli():
    import argparse

    parser = argparse.ArgumentParser(description="SofaScore historical sync")
    parser.add_argument("--date", type=str, help="Single date YYYY-MM-DD")
    parser.add_argument("--start-date", type=str, help="Backfill start date YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, help="Backfill end date YYYY-MM-DD")
    parser.add_argument("--days-back", type=int, default=2, help="Sync recent N days back from today")
    parser.add_argument("--max-events-per-day", type=int, default=0, help="Optional cap per day for testing")
    args = parser.parse_args()

    collector = SofaScoreCollector()

    if args.date:
        result = await collector.collect_date(args.date, only_finished=True, max_events=args.max_events_per_day)
    elif args.start_date and args.end_date:
        result = await collector.backfill_finished(args.start_date, args.end_date, max_events_per_day=args.max_events_per_day)
    else:
        result = await collector.sync_recent_finished(days_back=args.days_back, max_events_per_day=args.max_events_per_day)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(_run_cli())
