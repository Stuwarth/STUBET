# Project Guidelines

## Code Style
- Keep changes consistent with the surrounding code in backend and frontend.
- Preserve the existing Python import style and bootstrap pattern in backend/api/server.py; do not replace the current "sys.path" setup casually.
- The frontend is plain HTML/CSS/JS in frontend; prefer targeted edits over framework-style refactors.
- Use ASCII by default unless the file already uses non-ASCII characters.

## Architecture
- The main entry point is backend/main.py; it starts the FastAPI app defined in backend/api/server.py.
- The pipeline is data collection -> database -> feature engineering -> ML prediction -> value detection -> dashboard.
- Server module initialization currently creates shared instances at import time; check route dependencies before changing that pattern.
- The Playwright odds scraper is intentionally not started on server boot on Windows; it is activated manually through the dashboard endpoint instead.

## Build and Test
- Install dependencies with "pip install -r requirements.txt".
- Start the app with "cd backend && python main.py".
- Use "python test_api.py" for API checks, "python test_playwright.py" for scraper checks, and "python setup_telegram.py" for Telegram setup.
- There is no automated CI test runner in the repo; validate changes with the most relevant script plus manual browser/API checks.

## Conventions
- Link to README.md for user-facing setup and feature documentation instead of duplicating it here.
- Keep ".env" values aligned with ".env.example"; treat API keys as optional configuration.
- Be conservative with external API usage because the project depends on rate-limited services (API-Football max 100 reqs/day via "sport_api_client.py" and "stubet_pipeline.py").
- Do not add startup logic that assumes the Playwright scraper can run safely on Windows.

## Domain Rules: STUBET Engine
- **Branding**: The project is called **STUBET** (no longer "Monarca"). Telegram messages must use "👑 STUBET — LECTURA DE PARTIDO [LIVE STATS]". 
- **Betting Strategy**: Strictly statistical (xG, corners, possession, H2H). Move away from simple odds-drop tracking.
- **Markets Target**: To reach +80% win rates, focus the analysis on secondary markets (BTTS, Over/Under 2.5, Corners, First Half Goals, Player Saves/Props), ignoring the highly efficient 1X2 full-match market where possible.
