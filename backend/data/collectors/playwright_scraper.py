"""
Stealth Web Scraper for Real-Time Odds
Uses Playwright to intercept WebSocket/XHR traffic from bookmakers.
Includes an asynchronous structure to avoid blocking FastAPI.
"""
import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import httpx
import requests
from playwright.async_api import async_playwright, Page, BrowserContext, Route  # type: ignore
from data.collectors.team_matcher import TeamMatcher  # type: ignore
from analysis.value_bet_engine import ValueBetEngine  # type: ignore
from analysis.anomaly_detector import AnomalyDetector  # type: ignore

logger = logging.getLogger(__name__)

BOOKMAKER_WIDGET_BASE = "https://sb2frontend-altenar2.biahosted.com/api/widget"
BOOKMAKER_WIDGET_PARAMS = {
    "culture": "es-ES",
    "timezoneOffset": "240",
    "integration": "lasplatas",
    "deviceType": "1",
    "numFormat": "en-GB",
    "countryCode": "BO",
}


def _normalize_lookup_name(value: str) -> str:
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in (value or "")).split()
    )


def _event_matches(event: Dict[str, Any], home_team: str, away_team: str) -> bool:
    home_normalized = _normalize_lookup_name(home_team)
    away_normalized = _normalize_lookup_name(away_team)
    event_name = _normalize_lookup_name(event.get("name", ""))

    if home_normalized and away_normalized and home_normalized in event_name and away_normalized in event_name:
        return True

    competitors = event.get("competitors", []) or []
    if len(competitors) >= 2:
        competitor_names = [_normalize_lookup_name(item.get("name", "")) for item in competitors[:2]]
        return home_normalized in competitor_names and away_normalized in competitor_names

    home_tokens = [token for token in home_normalized.split() if len(token) >= 4][:2]
    away_tokens = [token for token in away_normalized.split() if len(token) >= 4][:2]
    if not home_tokens or not away_tokens:
        return False
    return home_tokens[0] in event_name and away_tokens[0] in event_name


def _fetch_widget_payload(endpoint: str, **extra_params) -> Dict[str, Any]:
    params = {**BOOKMAKER_WIDGET_PARAMS, **extra_params}
    try:
        response = requests.get(
            f"{BOOKMAKER_WIDGET_BASE}/{endpoint}",
            params=params,
            timeout=15.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
            },
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug("LasPlatas widget request failed for %s: %s", endpoint, exc)
        return {}


def _extract_direct_event_bundle(home_team: str, away_team: str) -> Optional[Dict[str, Any]]:
    def search_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        events = payload.get("events", []) or []
        for event in events:
            if _event_matches(event, home_team, away_team):
                odds_dict = {
                    odd.get("id"): odd
                    for odd in (payload.get("odds", []) or [])
                    if isinstance(odd, dict) and odd.get("id") is not None
                }
                return {
                    "event": event,
                    "markets": payload.get("markets", []) or [],
                    "odds_dict": odds_dict,
                }
        return None

    endpoint_plan = [
        ("GetHighlights", {"sportId": 66, "eventCount": 20}),
        ("GetUpcoming", {"sportId": 66, "eventCount": 100, "page": 1}),
        ("GetLivenow", {"sportId": 66, "eventCount": 50}),
    ]

    for endpoint, params in endpoint_plan:
        payload = _fetch_widget_payload(endpoint, **params)
        result = search_payload(payload)
        if result:
            return result

        if endpoint == "GetUpcoming":
            total_pages = min(int(payload.get("pageCount") or 1), 6)
            for page in range(2, total_pages + 1):
                paged_payload = _fetch_widget_payload(endpoint, **{**params, "page": page})
                result = search_payload(paged_payload)
                if result:
                    return result
    return None


def _build_direct_match_odds(home_team: str, away_team: str) -> Dict[str, Any]:
    event_bundle = _extract_direct_event_bundle(home_team, away_team)
    if not event_bundle:
        return {
            "status": "error",
            "message": "No se encontraron cuotas para este partido",
            "bookmaker": "LasPlatas",
            "odds": {},
        }

    scraper = PlaywrightOddsScraper(None, None, None)
    market_odds = scraper._normalize_altenar_odds(
        event_bundle["event"],
        event_bundle["markets"],
        event_bundle["odds_dict"],
    )

    extra_markets = {}
    for market in event_bundle["markets"]:
        if market.get("id") not in (event_bundle["event"].get("marketIds", []) or []) and market.get("eventId") != event_bundle["event"].get("id"):
            continue
        market_name = market.get("name", "").lower()
        if not any(k in market_name for k in ["tarjeta", "corner", "córner", "card", "remate", "tiro", "shot", "falta", "foul", "offside", "fuera de juego", "save", "ataj"]):
            continue
        selections = {}
        for odd_id in market.get("oddIds", []):
            odd_data = event_bundle["odds_dict"].get(odd_id, {})
            selection_name = odd_data.get("name", "")
            price = odd_data.get("price")
            if selection_name and price is not None:
                selections[selection_name] = price
        if selections:
            extra_markets[market.get("name", "")] = selections

    if extra_markets:
        market_odds["extended_markets"] = extra_markets

    return {"status": "success", "bookmaker": "LasPlatas", "odds": market_odds}

class PlaywrightOddsScraper:
    """
    Modern Stealth scraper to bypass basic bot-protection (Cloudflare/Datadome)
    by running a real headless browser instance and intercepting JSON APIs.
    """
    
    def __init__(self, db, predictor, telegram_bot=None):
        self.db = db
        self.predictor = predictor
        self.matcher = TeamMatcher(db)
        self.value_engine = ValueBetEngine(db, predictor, telegram_bot=telegram_bot)
        self.anomaly_detector = AnomalyDetector(telegram_bot=telegram_bot)
        self.is_running = False
        
        # LasPlatas URLs and Endpoints
        self.target_url = "https://lasplatas.com/betting#/overview"
        self.api_intercept_pattern = "**/api/widget/Get**"

    async def start(self):
        """Starts the background scraping task."""
        if self.is_running:
            return
        
        self.is_running = True
        logger.info("Starting Playwright Real-Time Stealth Scraper...")
        asyncio.create_task(self._scrape_loop())

    async def stop(self):
        """Stops the scraper."""
        self.is_running = False
        logger.info("Stopping Playwright Real-Time Stealth Scraper...")

    async def _scrape_loop(self):
        """Continuous background loop for scraping odds."""
        async with async_playwright() as p:
            # We use standard Chromium, but you can inject stealth scripts here
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            
            # Anti-detect script injection
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
            
            page = await context.new_page()
            
            while self.is_running:
                try:
                    await self._scrape_cycle(page)
                    # Poll every 60 seconds
                    await asyncio.sleep(60)
                except Exception as e:
                    logger.error(f"Error during scrape loop: {e}")
                    await asyncio.sleep(60) # Backoff before retrying
                    
            await browser.close()

    async def _scrape_cycle(self, page: Page):
        """Single scraping cycle processing live odds."""
        # Setup route interception to grab API responses instead of parsing HTML
        captured_data = []
        
        async def handle_response(response):
            # Target LasPlatas/Altenar JSON feeds
            if ("api/widget/GetLivenow" in response.url or "api/widget/GetHighlights" in response.url) and response.status == 200:
                try:
                    json_data = await response.json()
                    captured_data.append(json_data)
                except Exception:
                    pass
        
        page.on("response", handle_response)
        
        try:
            # LasPlatas keeps long-lived connections; strict networkidle often times out.
            await page.goto(self.target_url, wait_until="domcontentloaded", timeout=45000)

            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                logger.debug("Network idle not reached; continuing with captured feed data.")

            # Let widget XHR/WebSocket chunks arrive before processing.
            await asyncio.sleep(5)
            
            if captured_data:
                await self._process_captured_data(captured_data)
                
        except Exception as e:
            import traceback
            logger.error(f"Failed to load page or extract events: {traceback.format_exc()}")
        finally:
            page.remove_listener("response", handle_response)

    async def _process_captured_data(self, data_chunks: List[Dict]):
        """
        Parses the raw JSON intercepted from the bookmaker.
        Crucially matches team names and sends odds to the ValueBet Engine.
        """
        for chunk in data_chunks:
            if not isinstance(chunk, dict):
                continue
            # LasPlatas/Altenar JSON Structure
            events = chunk.get("events", [])
            market_defs = chunk.get("markets", [])
            odds_list = chunk.get("odds", [])
            
            # Create a lookup for odd definitions
            if not isinstance(odds_list, list):
                odds_list = []
            odds_dict = {odd.get("id"): odd for odd in odds_list}
            
            for event in events:
                sport = event.get("sportName") or event.get("categoryName") or str(event.get("sport", "Deporte Desconocido"))
                
                # Altenar name parsing logic
                name = event.get("name", "")
                competitors = event.get("competitors", [])
                
                if competitors and len(competitors) >= 2:
                    home_raw = competitors[0].get("name", "")
                    away_raw = competitors[1].get("name", "")
                elif " vs " in name:
                    parts = name.split(" vs ")
                    home_raw = parts[0]
                    away_raw = parts[1]
                elif " - " in name:
                    parts = name.split(" - ")
                    home_raw = parts[0]
                    away_raw = parts[1]
                else:
                    home_raw = name
                    away_raw = "Mismo Evento"
                
                if not home_raw or not away_raw:
                    continue
                    
                # Identificamos si está en vivo (Live) para no cruzar falsos positivos con AnomalyDetector
                is_live = event.get("isLive") or "getlivenow" in str(chunk.get("req_url", "")).lower()
                
                # Intentamos extraer Score y Minuto de Altenar (Live Stats) si están presentes
                # Altenar suele guardarlos en 'liveData' o similar, pero por ahora usamos 0 por defecto
                score_home = 0
                score_away = 0
                minute = 0
                if is_live:
                    live_data = event.get("liveData", {})
                    # Extraer minuto
                    if "matchClock" in live_data and "minute" in live_data["matchClock"]:
                        minute = int(live_data["matchClock"].get("minute", 0))
                    
                    # Extraer score
                    if "score" in live_data:
                        score_str = live_data.get("score", "0:0")
                        parts = score_str.split(":")
                        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                            score_home = int(parts[0])
                            score_away = int(parts[1])
                
                # Parse odds mapping for all events
                market_odds = self._normalize_altenar_odds(event, market_defs, odds_dict)
                event_id = str(event.get("id", ""))
                
                # 0. Keep odds-movement anomalies as a complementary PRE-MATCH radar only.
                if not is_live:
                    await self._check_match_fixing(
                        event_id, sport, home_raw, away_raw, market_odds,
                        is_live=is_live,
                        score_home=score_home,
                        score_away=score_away,
                        minute=minute
                    )
                
                sport_lower = sport.lower()
                if "soccer" in sport_lower or "fútbol" in sport_lower or "foot" in sport_lower:
                    home_matched = self.matcher.match_team(home_raw)
                    away_matched = self.matcher.match_team(away_raw)

                    if home_matched and away_matched:
                        await self.value_engine.check_for_value(
                            home_id=home_matched["api_id"],
                            away_id=away_matched["api_id"],
                            home_name=home_matched["name"],
                            away_name=away_matched["name"],
                            scraped_odds=market_odds,
                            is_live=is_live,
                            minute=minute,
                            score_home=score_home,
                            score_away=score_away,
                            sport="football"
                        )
                elif "basket" in sport_lower or "nba" in sport_lower:
                    await self.value_engine.check_for_value(
                        home_id=0, away_id=0, home_name=home_raw, away_name=away_raw,
                        scraped_odds=market_odds, is_live=is_live, minute=minute,
                        score_home=score_home, score_away=score_away, sport="basketball"
                    )
                elif "tenis" in sport_lower or "tennis" in sport_lower:
                    await self.value_engine.check_for_value(
                        home_id=0, away_id=0, home_name=home_raw, away_name=away_raw,
                        scraped_odds=market_odds, is_live=is_live, minute=minute,
                        score_home=score_home, score_away=score_away, sport="tennis"
                    )

    async def _check_match_fixing(self, event_id: str, sport: str, home: str, away: str, parsed_odds: Dict, is_live: bool = False, score_home: int = 0, score_away: int = 0, minute: int = 0):
        """Passes formatted odds into the dark insight anomaly detector with full match context."""
        for market, outcomes in parsed_odds.items():
            if market in ("isLive", "startDate") or not isinstance(outcomes, dict):
                continue
            for outcome, price in outcomes.items():
                if price is not None:
                    await self.anomaly_detector.analyze_odds_movement(
                        event_id=event_id,
                        sport=sport,
                        home_name=home,
                        away_name=away,
                        market_name=market,
                        outcome_name=outcome,
                        current_odd=float(price),
                        is_live=is_live,
                        score_home=score_home,
                        score_away=score_away,
                        minute=minute
                    )

    def _normalize_altenar_odds(self, event: Dict, market_defs: List[Dict], odds_dict: Dict) -> Dict[str, Any]:
        """Converts Altenar format into our standard format."""
        normalized: Dict[str, Any] = {
            "isLive": event.get("isLive", False),
            "startDate": event.get("startDate", ""),
            "extended_markets": {}
        }
        
        # Link event markets to the market definitions
        event_markets = event.get("marketIds", [])
        event_name = event.get("name", "").lower()
        competitor_ids = event.get("competitorIds", []) or []
        home_competitor_id = competitor_ids[0] if len(competitor_ids) > 0 else None
        away_competitor_id = competitor_ids[1] if len(competitor_ids) > 1 else None
        extended_keywords = (
            "tarjeta", "card", "corner", "córner", "remate", "tiro", "shot",
            "falta", "foul", "offside", "fuera de juego", "save", "ataj"
        )
        
        for market in market_defs:
            if market.get("id") not in event_markets and market.get("eventId") != event.get("id"):
                continue
                
            market_name = market.get("name", "").lower()
            odd_ids = market.get("oddIds", [])
            if "1x2" in market_name or "ganador del partido" in market_name:
                match_result_dict: Dict[str, Any] = {}
                for oid in odd_ids:
                    odd_data = odds_dict.get(oid, {})
                    oname = odd_data.get("name", "").lower()
                    price = odd_data.get("price")
                    type_id = odd_data.get("typeId")
                    competitor_id = odd_data.get("competitorId")
                    if "empate" in oname or type_id == 2:
                        match_result_dict["Draw"] = price
                    elif competitor_id == home_competitor_id or type_id == 1:
                        match_result_dict["Home Win"] = price
                    else:
                        match_result_dict["Away Win"] = price
                if match_result_dict:
                    normalized["match_result"] = match_result_dict
                        
            # Handle Over/Under
            if "total de goles" in market_name or "over/under" in market_name:
                over_under_dict = normalized.get("over_under_25", {})
                for oid in odd_ids:
                    odd_data = odds_dict.get(oid, {})
                    oname = odd_data.get("name", "").lower()
                    price = odd_data.get("price")
                    if "2.5" in oname or "2.5" in market_name:
                        if "más de" in oname or "over" in oname:
                            over_under_dict["Over 2.5"] = price
                        elif "menos de" in oname or "under" in oname:
                            over_under_dict["Under 2.5"] = price
                if over_under_dict:
                    normalized["over_under_25"] = over_under_dict

            if "ambos equipos marcan" in market_name or "both teams to score" in market_name:
                btts_dict: Dict[str, Any] = {}
                for oid in odd_ids:
                    odd_data = odds_dict.get(oid, {})
                    oname = odd_data.get("name", "").lower()
                    price = odd_data.get("price")
                    if "sí" in oname or "si" in oname or "yes" in oname:
                        btts_dict["BTTS Yes"] = price
                    elif "no" in oname:
                        btts_dict["BTTS No"] = price
                if btts_dict:
                    normalized["btts"] = btts_dict
                            
            # Apuesta sin empate (Draw No Bet)
            if "empate no acción" in market_name or "apuesta sin empate" in market_name or "draw no bet" in market_name:
                dnb_dict: Dict[str, Any] = {}
                for oid in odd_ids:
                    odd_data = odds_dict.get(oid, {})
                    price = odd_data.get("price")
                    type_id = odd_data.get("typeId")
                    competitor_id = odd_data.get("competitorId")
                    if competitor_id == home_competitor_id or type_id == 1:
                        dnb_dict["Home DNB"] = price
                    else:
                        dnb_dict["Away DNB"] = price
                if dnb_dict:
                    normalized["draw_no_bet"] = dnb_dict
                        
            # Doble Oportunidad
            if "doble oportunidad" in market_name or "double chance" in market_name:
                dc_dict: Dict[str, Any] = {}
                for oid in odd_ids:
                    odd_data = odds_dict.get(oid, {})
                    oname = odd_data.get("name", "").lower()
                    price = odd_data.get("price")
                    type_id = odd_data.get("typeId")
                    if "1x" in oname or ("local" in oname and "empate" in oname) or type_id == 9:
                        dc_dict["1X"] = price
                    elif "x2" in oname or ("visitante" in oname and "empate" in oname) or type_id == 11:
                        dc_dict["X2"] = price
                    elif "12" in oname or ("local" in oname and "visitante" in oname) or type_id == 10:
                        dc_dict["12"] = price
                if dc_dict:
                    normalized["double_chance"] = dc_dict

            if any(keyword in market_name for keyword in extended_keywords):
                extended_market: Dict[str, Any] = {}
                for oid in odd_ids:
                    odd_data = odds_dict.get(oid, {})
                    selection_name = odd_data.get("name", "")
                    price = odd_data.get("price")
                    if selection_name and price is not None:
                        extended_market[selection_name] = price
                if extended_market:
                    normalized["extended_markets"][market.get("name", "Mercado")] = extended_market
                            
        return normalized
        
    async def get_match_odds_on_demand(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """Manually scrapes LasPlatas for a specific match's odds (cards, corners, match result, etc)."""
        return await asyncio.to_thread(_build_direct_match_odds, home_team, away_team)
        captured_data = None
        
        async def handle_response(response):
            nonlocal captured_data
            if "api/widget/GetSearchEvents" in response.url and response.status == 200:
                try:
                    json_data = await response.json()
                    captured_data = json_data
                except Exception:
                    pass

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                page.on("response", handle_response)
                
                # Navigate to LasPlatas search with the home team
                clean_home = home_team.split(" ")[0] # Broad search
                search_url = f"https://lasplatas.com/betting#/search?q={clean_home}"
                await page.goto(search_url, wait_until="networkidle", timeout=15000)
                await asyncio.sleep(2) # Allow React / Altenar API to load
                
                if captured_data and "events" in captured_data:
                    events = captured_data.get("events", [])
                    market_defs = captured_data.get("markets", [])
                    odds_list = captured_data.get("odds", [])
                    odds_dict = {odd.get("id"): odd for odd in odds_list} if isinstance(odds_list, list) else odds_list
                    
                    found_event = None
                    for event in events:
                        name = event.get("name", "").lower()
                        if clean_home.lower() in name and away_team.split(" ")[0].lower() in name:
                            found_event = event
                            break
                            
                    if found_event:
                        market_odds = self._normalize_altenar_odds(found_event, market_defs, odds_dict)
                        # Extract Cards, Corners & Special Markets
                        extra_markets = {}
                        for market in market_defs:
                            if market.get("eventId") == found_event.get("id"):
                                m_name = market.get("name", "").lower()
                                if any(k in m_name for k in ["tarjeta", "córner", "corner", "card", "remate", "tiro", "shot", "falta", "foul", "offside", "fuera de juego", "save", "ataj"]):
                                    odd_ids = market.get("oddIds", [])
                                    extra_dict = {}
                                    for oid in odd_ids:
                                        odd_data = odds_dict.get(oid, {})
                                        extra_dict[odd_data.get("name", "")] = odd_data.get("price")
                                    extra_markets[market.get("name", "")] = extra_dict
                                    
                        if extra_markets:
                            market_odds["extended_markets"] = extra_markets
                            
                        await browser.close()
                        return {"status": "success", "bookmaker": "LasPlatas", "odds": market_odds}
                        
                await browser.close()
        except Exception as e:
            logger.error(f"On-demand scrape failed: {e}")
            
        return {"status": "error", "message": "No se encontraron cuotas para este partido", "bookmaker": "LasPlatas", "odds": {}}

def sync_get_match_odds(home_team: str, away_team: str) -> Dict[str, Any]:
    """Synchronous isolated Playwright task to avoid FastAPI async loop blocking."""
    return _build_direct_match_odds(home_team, away_team)
    from playwright.sync_api import sync_playwright
    import time
    
    captured_data = None
    
    def handle_response(response):
        nonlocal captured_data
        if "api/widget/GetSearchEvents" in response.url and response.status == 200:
            try:
                json_data = response.json()
                captured_data = json_data
            except Exception:
                pass
                
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36")
            page = context.new_page()
            page.on("response", handle_response)
            
            clean_home = home_team.split(" ")[0]
            search_url = f"https://lasplatas.com/betting#/search?q={clean_home}"
            page.goto(search_url, wait_until="networkidle", timeout=15000)
            time.sleep(3)
            
            if captured_data and "events" in captured_data:
                events = captured_data.get("events", [])
                market_defs = captured_data.get("markets", [])
                odds_list = captured_data.get("odds", [])
                odds_dict = {odd.get("id"): odd for odd in odds_list} if isinstance(odds_list, list) else odds_list
                
                found_event = None
                for event in events:
                    name = event.get("name", "").lower()
                    if clean_home.lower() in name and away_team.split(" ")[0].lower() in name:
                        found_event = event
                        break
                        
                if found_event:
                    # Instantiate just to use the normalizer
                    scraper = PlaywrightOddsScraper(None, None, None)
                    market_odds = scraper._normalize_altenar_odds(found_event, market_defs, odds_dict)
                    
                    extra_markets = {}
                    for market in market_defs:
                        if market.get("eventId") == found_event.get("id"):
                            m_name = market.get("name", "").lower()
                            if any(k in m_name for k in ["tarjeta", "córner", "corner", "card", "remate", "tiro", "shot", "falta", "foul", "offside", "fuera de juego", "save", "ataj"]):
                                odd_ids = market.get("oddIds", [])
                                extra_dict = {}
                                for oid in odd_ids:
                                    odd_data = odds_dict.get(oid, {})
                                    extra_dict[odd_data.get("name", "")] = odd_data.get("price")
                                extra_markets[market.get("name", "")] = extra_dict
                                
                    if extra_markets:
                        market_odds["extended_markets"] = extra_markets
                    
                    browser.close()
                    return {"status": "success", "bookmaker": "LasPlatas", "odds": market_odds}
                    
            browser.close()
    except Exception as e:
        logger.error(f"Sync on-demand scrape failed: {e}")
        
    return {"status": "error", "message": "No se encontraron cuotas para este partido", "bookmaker": "LasPlatas", "odds": {}}
