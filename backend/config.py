"""
Sports AI Predictor - Configuration
"""
import os
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MODELS_DIR = DATA_DIR / "models"

# Ensure directories exist
for d in [RAW_DATA_DIR, PROCESSED_DATA_DIR, MODELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Database
DB_PATH = DATA_DIR / "sports_ai.db"

def load_runtime_settings() -> Dict[str, str]:
    """Read the latest runtime settings directly from .env."""
    settings: Dict[str, str] = {}
    if ENV_PATH.exists():
        for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip()
    return settings


def get_setting(name: str, default: str = "") -> str:
    """Return a runtime setting with .env taking precedence."""
    runtime = load_runtime_settings()
    if name in runtime:
        return runtime[name]
    return os.getenv(name, default)


def is_configured(value: str, placeholders: tuple[str, ...] = ()) -> bool:
    return bool(value and value.strip() and value not in placeholders)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}***{value[-4:]}"


# API Keys (set these in .env file)
FOOTBALL_API_KEY = get_setting("FOOTBALL_API_KEY", "")  # api-football.com (RapidAPI)
ODDS_API_KEY = get_setting("ODDS_API_KEY", "")  # the-odds-api.com
FOOTBALL_DATA_API_KEY = get_setting("FOOTBALL_DATA_API_KEY", "")  # football-data.org (free)

# Telegram Notifications
TELEGRAM_BOT_TOKEN = get_setting("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = get_setting("TELEGRAM_CHAT_ID", "")

# API-Football settings
FOOTBALL_API_BASE = "https://v3.football.api-sports.io"
FOOTBALL_API_HEADERS = {
    "x-apisports-key": FOOTBALL_API_KEY
}

# The Odds API settings
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Supported leagues (ID: Name)
SUPPORTED_LEAGUES = {
    39: "Premier League",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
    2: "Champions League",
    3: "Europa League",
    848: "Conference League",
    128: "Liga Profesional Argentina",
    71: "Serie A Brasil",
    253: "MLS",
    13: "Copa Libertadores",
    11: "Copa Sudamericana",
}

# ML Configuration
ML_CONFIG = {
    "test_size": 0.2,
    "random_state": 42,
    "n_estimators": 500,
    "max_depth": 8,
    "learning_rate": 0.05,
    "min_samples": 50,  # Minimum matches to train
    "retrain_interval_hours": 24,
    "confidence_threshold": 0.55,  # Minimum confidence for predictions
}

# Model directory alias
MODEL_DIR = MODELS_DIR

# Value Bet Configuration
VALUE_BET_CONFIG = {
    "min_value": 0.05,        # Minimum edge (5%)
    "strong_value": 0.10,     # Strong value bet (10%)
    "premium_value": 0.15,    # Premium value bet (15%)
    "min_odds": 1.30,         # Minimum odds to consider
    "max_odds": 8.00,         # Maximum odds to consider
    "kelly_fraction": 0.25,   # Quarter Kelly for bankroll management
}

# Betting Markets (ALL statistical markets)
MARKETS = [
    "match_result",           # 1X2
    "over_under_25",          # Over/Under 2.5 goals
    "btts",                   # Both Teams To Score
    "corners_total",          # Total corners Over/Under
    "corners_home",           # Home team corners
    "corners_away",           # Away team corners
    "cards_total",            # Total yellow cards
    "cards_home",             # Home team cards
    "cards_away",             # Away team cards
    "shots_on_target_total",  # Total shots on target
    "shots_on_target_home",   # Home shots on target
    "shots_on_target_away",   # Away shots on target
    "shots_total",            # Total shots
    "goalkeeper_saves",       # Goalkeeper saves
    "fouls_total",            # Total fouls
    "offsides_total",         # Total offsides
    "asian_handicap",         # Asian Handicap
]

# Server Configuration
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080
