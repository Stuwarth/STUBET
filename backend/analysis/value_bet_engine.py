"""
Market-aware football value engine.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional

from cachetools import TTLCache

from analysis.football_market_intelligence import FootballMarketIntelligence
from analysis.nba_predictor import NBAPredictor
from analysis.tennis_predictor import TennisPredictor
from data.collectors.sport_api_client import SportAPIClient

logger = logging.getLogger(__name__)


class ValueBetEngine:
    def __init__(self, db, predictor, threshold: float = 0.05, telegram_bot=None):
        self.db = db
        self.predictor = predictor
        self.threshold = threshold
        self.telegram_bot = telegram_bot
        self.market_intelligence = FootballMarketIntelligence(db, predictor)
        self.sport_api_client = SportAPIClient()
        self.nba_predictor = NBAPredictor(db)
        self.tennis_predictor = TennisPredictor(db)
        self.alert_cache = TTLCache(maxsize=5000, ttl=3600)
        self.parlay_buffer: List[Dict] = []

    async def check_for_value(
        self,
        home_id: int,
        away_id: int,
        home_name: str,
        away_name: str,
        scraped_odds: Dict,
        is_live: bool = False,
        minute: int = 0,
        score_home: int = 0,
        score_away: int = 0,
        sport: str = "football",
    ):
        """
        Evaluate real LasPlatas lines against real statistical context and send only actionable signals.
        """
        match_name = f"{home_name} vs {away_name}"
        match_row = self._find_active_match(home_id, away_id) if sport == "football" else None
        live_stats: Dict = {}
        analysis: Dict = {"candidates": []}

        try:
            if sport == "football":
                if is_live and match_row:
                    live_stats = await self.sport_api_client.get_live_stats(match_row["api_id"])

                analysis = await asyncio.to_thread(
                    self.market_intelligence.analyze_matchup,
                    home_id,
                    away_id,
                    home_name,
                    away_name,
                    scraped_odds,
                    is_live,
                    minute,
                    score_home,
                    score_away,
                    live_stats,
                )
            elif sport == "basketball":
                match_data = {"id": home_id + away_id, "home": {"name": home_name}, "away": {"name": away_name}}
                preds = await asyncio.to_thread(self.nba_predictor.analyze_match, match_data)
                candidates = []
                for p in preds:
                    candidates.append({
                        "market": p["market"],
                        "market_key": p["market"].lower().replace(" ", "_"),
                        "selection": p["prediction"],
                        "probability": p["probability"],
                        "confidence": p["confidence"],
                        "rationale": p.get("rationale", ""),
                        "odds": 1.9,
                        "implied_probability": 0.52,
                        "edge": p["probability"] - 0.52,
                        "score": p["probability"] * (p["probability"] - 0.52),
                    })
                analysis = {"candidates": candidates}
            elif sport == "tennis":
                match_data = {"id": home_id + away_id, "home": {"name": home_name}, "away": {"name": away_name}}
                preds = await asyncio.to_thread(self.tennis_predictor.analyze_match, match_data)
                candidates = []
                for p in preds:
                    candidates.append({
                        "market": p["market"],
                        "market_key": p["market"].lower().replace(" ", "_"),
                        "selection": p["prediction"],
                        "probability": p["probability"],
                        "confidence": p["confidence"],
                        "rationale": p.get("rationale", ""),
                        "odds": 1.9,
                        "implied_probability": 0.52,
                        "edge": p["probability"] - 0.52,
                        "score": p["probability"] * (p["probability"] - 0.52),
                    })
                analysis = {"candidates": candidates}
        except Exception as exc:
            logger.error("Failed to analyze %s: %s", match_name, exc)
            return

        if not analysis.get("candidates"):
            return

        alert_mode = "LIVE" if is_live else "PRE-MATCH"
        top_candidates = analysis["candidates"][:2]
        for candidate in top_candidates:
            if candidate["edge"] < self.threshold:
                continue
            if candidate["probability"] < 0.58:
                continue

            cache_key = self._build_cache_key(match_row, candidate, alert_mode)
            if cache_key in self.alert_cache:
                continue
            self.alert_cache[cache_key] = True

            enriched_candidate = {
                **candidate,
                "match": match_name,
            }
            self._store_prediction(match_row, enriched_candidate)
            await self._trigger_alert(
                match=match_name,
                mode=alert_mode,
                candidate=enriched_candidate,
            )

            if (
                not is_live
                and 1.22 <= float(candidate.get("odds", 0)) <= 1.65
                and candidate["probability"] >= 0.68
            ):
                self.parlay_buffer.append(enriched_candidate)

        if len(self.parlay_buffer) >= 3:
            await self._trigger_parlay_alert()

    def _find_active_match(self, home_id: int, away_id: int) -> Optional[Dict]:
        return self.db.get_active_match_by_teams(home_id, away_id)

    def _build_cache_key(self, match_row: Optional[Dict], candidate: Dict, mode: str) -> str:
        match_id = match_row["api_id"] if match_row else "no-match"
        return f"{mode}:{match_id}:{candidate.get('market_key')}:{candidate.get('selection')}"

    def _store_prediction(self, match_row: Optional[Dict], candidate: Dict):
        if not match_row:
            return

        try:
            self.db.save_prediction({
                "match_id": match_row["api_id"],
                "market": candidate.get("market_key", "unknown"),
                "prediction": candidate.get("selection", "N/A"),
                "probability": candidate.get("probability", 0),
                "confidence": candidate.get("confidence", "LOW"),
                "rationale": candidate.get("rationale", ""),
                "model_version": "stubet-market-aware-v1",
                "is_value_bet": 1,
                "value_edge": candidate.get("edge", 0),
                "recommended_stake": self._recommended_stake(candidate),
            })
        except Exception as exc:
            logger.warning("Could not store prediction for %s: %s", candidate.get("selection"), exc)

    @staticmethod
    def _recommended_stake(candidate: Dict) -> int:
        probability = float(candidate.get("probability", 0))
        edge = float(candidate.get("edge", 0))
        # STAKE 1 al 10, y si es muy seguro (ALL IN) del 10 al 100
        if probability >= 0.88 and edge >= 0.15:
            return 100 # ALL IN
        if probability >= 0.82 and edge >= 0.12:
            return 50 # Medio ALL IN
        if probability >= 0.72 and edge >= 0.1:
            return 10 # Máximo stake normal
        if probability >= 0.64 and edge >= 0.07:
            return 7
        if probability >= 0.58 and edge >= 0.04:
            return 5
        return 3

    async def _trigger_alert(self, match: str, mode: str, candidate: Dict):
        """Send a single useful alert with the exact line detected in LasPlatas."""
        image_path = None
        if mode == "LIVE":
            live_candidates = [
                Path(__file__).parent.parent.parent / "frontend" / "images" / "live_alert.jpg",
                Path(__file__).parent.parent.parent / "frontend" / "static" / "images" / "live_alert.jpg",
            ]
            for img_file in live_candidates:
                if img_file.exists():
                    image_path = str(img_file)
                    break

        logger.info(
            "STUBET %s alert %s | %s @ %.2f | prob=%.1f%% edge=%.1f%%",
            mode,
            match,
            candidate.get("selection"),
            float(candidate.get("odds", 0)),
            float(candidate.get("probability", 0)) * 100,
            float(candidate.get("edge", 0)) * 100,
        )

        if self.telegram_bot:
            self.telegram_bot.send_stubet_market_alert(candidate, mode=mode, image_path=image_path)

    async def _trigger_parlay_alert(self):
        """Build a conservative pre-match parlay from the best low-volatility picks."""
        picks = self.parlay_buffer[:3]
        self.parlay_buffer = self.parlay_buffer[3:]
        if not picks:
            return

        total_odd = 1.0
        combined_probability = 1.0
        lines = [
            "👑 <b>STUBET — PARLAY CONSERVADOR</b>",
            "",
        ]
        for pick in picks:
            total_odd *= float(pick.get("odds", 1.0))
            combined_probability *= float(pick.get("probability", 1.0))
            lines.append(
                f"• <b>{pick.get('match')}</b> — {pick.get('selection')} @ {pick.get('odds')}"
            )
        lines.extend([
            "",
            f"💎 <b>Cuota total:</b> {total_odd:.2f}",
            f"📈 <b>Probabilidad conjunta:</b> {combined_probability * 100:.1f}%",
            "⚠️ <i>Stake bajo: combinada pensada para líneas estables, no para all-in.</i>",
        ])
        if self.telegram_bot:
            self.telegram_bot.send_message("\n".join(lines))
