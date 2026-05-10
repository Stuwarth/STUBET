import httpx
import logging
from typing import Dict, Optional, List

from config import get_setting, is_configured

logger = logging.getLogger(__name__)

class SportAPIClient:
    """
    Cliente oficial STUBET v2.0 para interactuar con APIs deportivas GRATUITAS (RapidAPI / API-Football).
    Obtiene estadisticas EN VIVO, Lesiones de ultima hora y Alineaciones Confirmadas (H2H real).
    """
    def __init__(self, api_key: str = None):
        self.api_key = api_key or get_setting("FOOTBALL_API_KEY", "")
        self.base_url = "https://v3.football.api-sports.io"
        self.headers = {}
        self._refresh_headers()

    def _refresh_headers(self):
        if not self.api_key:
            self.api_key = get_setting("FOOTBALL_API_KEY", "")
        self.headers = {
            "x-apisports-key": self.api_key,
            "x-rapidapi-host": "v3.football.api-sports.io"
        }

    def _is_ready(self) -> bool:
        self.api_key = get_setting("FOOTBALL_API_KEY", self.api_key or "")
        self._refresh_headers()
        return is_configured(self.api_key)

    async def get_real_injuries(self, fixture_id: int) -> List[Dict]:
        """Obtiene las bajas y sanciones reales del partido desde la API oficial."""
        if not self._is_ready():
            logger.warning("STUBET: API Key no configurada. Usando scraping local como fallback.")
            return []
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/injuries?fixture={fixture_id}",
                    headers=self.headers
                )
                data = resp.json()
                if data.get("response"):
                    return data["response"]
                return []
        except Exception as e:
            logger.error(f"Error fetcheando lesiones de API-Football: {e}")
            return []

    async def get_live_stats(self, fixture_id: int) -> Dict:
        """Obtiene las estadisticas 100% REALES EN VIVO (corners, posesion, tiros, ataques peligrosos)."""
        if fixture_id <= 0 or not self._is_ready():
            return {}
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/fixtures/statistics?fixture={fixture_id}",
                    headers=self.headers
                )
                data = resp.json()
                if data.get("response"):
                    parsed: Dict[str, Dict] = {}
                    total_corners = 0
                    total_shots = 0
                    for side in data["response"]:
                        team = side.get("team", {})
                        team_stats = {
                            "possession": 50.0,
                            "total_shots": 0,
                            "corners": 0,
                            "shots_on_target": 0,
                        }
                        for item in side.get("statistics", []):
                            stat_type = item.get("type")
                            raw_value = item.get("value")
                            if stat_type == "Ball Possession":
                                val = str(raw_value).replace("%", "")
                                team_stats["possession"] = float(val) if val and val != "None" else 50.0
                            elif stat_type == "Total Shots":
                                team_stats["total_shots"] = int(raw_value or 0)
                            elif stat_type == "Corner Kicks":
                                team_stats["corners"] = int(raw_value or 0)
                            elif stat_type == "Shots on Goal":
                                team_stats["shots_on_target"] = int(raw_value or 0)

                        key = "home" if "home" not in parsed else "away"
                        parsed[key] = {
                            "team_id": team.get("id"),
                            "team_name": team.get("name"),
                            **team_stats,
                        }
                        total_corners += team_stats["corners"]
                        total_shots += team_stats["total_shots"]

                    parsed["total_corners"] = total_corners
                    parsed["total_shots"] = total_shots
                    return parsed
                return {}
        except Exception as e:
            logger.error(f"Error fetcheando live stats de API-Football: {e}")
            return {}

    async def get_h2h_stats(self, team1_id: int, team2_id: int) -> Dict:
        """Obtiene el verdadero historial cara a cara y no alucinaciones web."""
        if not self._is_ready():
            return {}
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/fixtures/headtohead?h2h={team1_id}-{team2_id}",
                    headers=self.headers
                )
                data = resp.json()
                return data.get("response", [])
        except Exception as e:
            logger.error(f"Error fetcheando H2H de API-Football: {e}")
            return {}
