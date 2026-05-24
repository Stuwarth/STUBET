import time
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Dict, Any, List
import io
from fpdf import FPDF
import asyncio

router = APIRouter()

class AnalyzeMatchRequest(BaseModel):
    event_id: int
    home_team_id: int
    away_team_id: int
    home_name: str
    away_name: str

from playwright.sync_api import sync_playwright
import json

def _fetch_multiple_urls(urls: List[str]) -> Dict[str, Any]:
    """Fetch múltiples URLs con un solo browser. Devuelve dict url->data."""
    results = {}
    if not urls:
        return results
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=20000)

            for url in urls:
                try:
                    text = page.evaluate(f"""
                        async () => {{
                            try {{
                                const r = await fetch("{url}", {{headers:{{"accept":"application/json"}}}});
                                return await r.text();
                            }} catch(e) {{ return ""; }}
                        }}
                    """)
                    if text:
                        data = json.loads(text)
                        if isinstance(data, dict):
                            results[url] = data
                except Exception:
                    pass
            browser.close()
    except Exception as e:
        print(f"Playwright multi-fetch error: {e}")
    return results

def _compact_match_info(event: dict) -> dict:
    home_score = event.get("homeScore", {}).get("current")
    away_score = event.get("awayScore", {}).get("current")
    
    # We only want finished matches
    status_type = event.get("status", {}).get("type", "").lower()
    if status_type not in ["finished", "aet", "afterpens"] or home_score is None:
        return None
        
    start_ts = event.get("startTimestamp")
    from datetime import datetime, timezone
    date_str = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d") if start_ts else ""
    
    return {
        "id": event.get("id"),
        "date": date_str,
        "competition": event.get("tournament", {}).get("name", ""),
        "home": event.get("homeTeam", {}).get("name", ""),
        "away": event.get("awayTeam", {}).get("name", ""),
        "home_score": home_score,
        "away_score": away_score
    }

@router.post("/api/analyze/match")
async def analyze_match(req: AnalyzeMatchRequest):
    if req.home_team_id <= 0 or req.away_team_id <= 0:
        return {"error": "IDs de equipo inválidos",
                "home_last10": [], "away_last10": [], "h2h": []}
    loop = asyncio.get_event_loop()

    def run_scraping():
        # Batch 1: Gather Event Lists
        event_list_urls = [
            f"https://api.sofascore.com/api/v1/event/{req.event_id}"
        ]
        # We need pages 0-2 for home and away just in case
        for i in range(3):
            event_list_urls.append(f"https://api.sofascore.com/api/v1/team/{req.home_team_id}/events/last/{i}")
            event_list_urls.append(f"https://api.sofascore.com/api/v1/team/{req.away_team_id}/events/last/{i}")
            
        initial_data = _fetch_multiple_urls(event_list_urls)
        
        # Resolve customId
        event_payload = initial_data.get(f"https://api.sofascore.com/api/v1/event/{req.event_id}", {})
        custom_id = event_payload.get("event", {}).get("customId")
        h2h_id = custom_id if custom_id else req.event_id
        
        # Batch 2: Get H2H
        h2h_data = _fetch_multiple_urls([f"https://api.sofascore.com/api/v1/event/{h2h_id}/h2h/events"])
        h2h_payload = h2h_data.get(f"https://api.sofascore.com/api/v1/event/{h2h_id}/h2h/events", {})
        
        def extract_finished_matches(team_id: int):
            # Juntar todos los eventos de las 3 páginas
            all_events = []
            for i in range(3):
                payload = initial_data.get(
                    f"https://api.sofascore.com/api/v1/team/{team_id}/events/last/{i}",
                    {}
                )
                all_events.extend(payload.get("events", []))
            
            # Ordenar por timestamp descendente (más reciente primero)
            all_events.sort(
                key=lambda e: e.get("startTimestamp", 0),
                reverse=True
            )
            
            # Tomar los 10 primeros que estén terminados
            matches = []
            for e in all_events:
                if len(matches) >= 10:
                    break
                info = _compact_match_info(e)
                if info:
                    matches.append(info)
            return matches

        home_infos = extract_finished_matches(req.home_team_id)
        away_infos = extract_finished_matches(req.away_team_id)
        
        # Extract H2H — ordenar por fecha descendente
        h2h_events = h2h_payload.get("events", [])
        h2h_events.sort(key=lambda e: e.get("startTimestamp", 0), reverse=True)
        h2h_infos = []
        for e in h2h_events:
            if len(h2h_infos) >= 10:
                break
            info = _compact_match_info(e)
            if info:
                h2h_infos.append(info)
                
        # Fallback H2H if empty — juntar, ordenar, filtrar
        if not h2h_infos:
            fallback_events = []
            for i in range(3):
                payload = initial_data.get(f"https://api.sofascore.com/api/v1/team/{req.home_team_id}/events/last/{i}", {})
                for e in payload.get("events", []):
                    home_id = e.get("homeTeam", {}).get("id")
                    away_id = e.get("awayTeam", {}).get("id")
                    if (home_id == req.home_team_id and away_id == req.away_team_id) or \
                       (home_id == req.away_team_id and away_id == req.home_team_id):
                        fallback_events.append(e)
            fallback_events.sort(key=lambda e: e.get("startTimestamp", 0), reverse=True)
            for e in fallback_events:
                if len(h2h_infos) >= 10:
                    break
                info = _compact_match_info(e)
                if info:
                    h2h_infos.append(info)

        # Batch 3: Fetch Statistics
        stats_urls = []
        for info in home_infos + away_infos + h2h_infos:
            stats_urls.append(f"https://api.sofascore.com/api/v1/event/{info['id']}/statistics")
            
        # Deduplicate URLs
        stats_urls = list(dict.fromkeys(stats_urls))
        stats_data = _fetch_multiple_urls(stats_urls)
        
        def bind_stats(infos):
            result = []
            for info in infos:
                s_payload = stats_data.get(f"https://api.sofascore.com/api/v1/event/{info['id']}/statistics", {})
                result.append({
                    "match_info": info,
                    "statistics": s_payload.get("statistics", [])
                })
            return result

        return {
            "home_last10": bind_stats(home_infos),
            "away_last10": bind_stats(away_infos),
            "h2h": bind_stats(h2h_infos)
        }
        
    data = await loop.run_in_executor(None, run_scraping)
    return data

def _safe(text) -> str:
    """Convierte texto a ASCII seguro para fpdf2 (Helvetica built-in)."""
    if text is None:
        return ""
    text = str(text)
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
        'ñ': 'n', 'Ñ': 'N', 'ü': 'u', 'Ü': 'U',
        '—': '-', '–': '-', '\u201c': '"', '\u201d': '"',
        '°': 'o', '•': '*', "'": "'", "'": "'",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text.encode('ascii', errors='replace').decode('ascii')


# ── Color Palette (matching the reference PDF exactly) ──────────
_BLUE_DARK  = (0, 48, 135)       # Main header background
_BLUE_HDR   = (0, 48, 135)       # Group stat header background
_GRAY_DARK  = (44, 44, 44)       # Table-of-contents header
_WHITE      = (255, 255, 255)
_ROW_WHITE  = (255, 255, 255)
_ROW_GRAY   = (242, 242, 242)    # Alternating row
_ROW_BLUE   = (238, 244, 255)    # Alternating row for summary
_YELLOW_HL  = (255, 251, 204)    # Yellow highlight column
_PINK_MATCH = (253, 232, 232)    # Match header background
_BLACK      = (0, 0, 0)


def _compute_summary(matches: list, focus_team: str) -> list:
    """Compute MEDIA, MIN, MAX, ÚLTIMO for key stats across matches."""
    import re
    KEY_STATS = [
        "Total shots", "Shots on target", "Corner kicks",
        "Yellow cards", "Fouls", "Expected goals",
        "Big chances", "Goalkeeper saves", "Passes",
    ]
    # Collect values per stat
    stat_values = {s: [] for s in KEY_STATS}
    STAT_ALIASES = {
        "Total shots": ["Total shots"],
        "Shots on target": ["Shots on target"],
        "Corner kicks": ["Corner kicks"],
        "Yellow cards": ["Yellow cards"],
        "Fouls": ["Fouls"],
        "Expected goals": ["Expected goals"],
        "Big chances": ["Big chances"],
        "Goalkeeper saves": ["Goalkeeper saves", "Total saves"],
        "Passes": ["Passes", "Accurate passes"],
    }

    for m in matches:
        info = m.get("match_info", {})
        home_name = info.get("home", "")
        is_home = (focus_team.lower() in home_name.lower())

        stats = m.get("statistics", [])
        for period in stats:
            if period.get("period", "").upper() != "ALL":
                continue
            for group in period.get("groups", []):
                for item in group.get("statisticsItems", []):
                    name = item.get("name", "")
                    raw = str(item.get("home", "0")) if is_home else str(item.get("away", "0"))
                    # extract number
                    num_match = re.search(r'[\d.]+', raw.replace(',', '').replace('%', ''))
                    if not num_match:
                        continue
                    val = float(num_match.group())
                    for key, aliases in STAT_ALIASES.items():
                        if name in aliases:
                            stat_values[key].append(val)
                            break

    summary = []
    DISPLAY_NAMES = {
        "Total shots": "Remates totales",
        "Shots on target": "Remates a puerta",
        "Corner kicks": "Corners",
        "Yellow cards": "Tarjetas amarillas",
        "Fouls": "Faltas cometidas",
        "Expected goals": "xG",
        "Big chances": "Grandes ocasiones",
        "Goalkeeper saves": "Paradas portero",
        "Passes": "Pases totales",
    }
    for key in KEY_STATS:
        vals = stat_values[key]
        if not vals:
            continue
        summary.append({
            "name": DISPLAY_NAMES.get(key, key),
            "mean": round(sum(vals) / len(vals), 1),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
            "last": round(vals[0], 1),  # first match = most recent
        })
    return summary


@router.post("/api/analyze/match/pdf")
async def generate_pdf(request: Request):
    req = await request.json()
    data = req.get("data", {})
    home_name = req.get("home_name", "Local")
    away_name = req.get("away_name", "Visitante")
    
    from analysis.pdf_generator import generate_stats_pdf
    pdf_bytes = generate_stats_pdf(
        stubet_data=data,
        team_a_name=home_name,
        team_b_name=away_name,
    )
    
    safe_home = "".join(c if c.isalnum() else "_" for c in home_name)
    safe_away = "".join(c if c.isalnum() else "_" for c in away_name)
    filename = f"STUBET_{safe_home}_vs_{safe_away}.pdf"
    
    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
