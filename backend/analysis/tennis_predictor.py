import hashlib
from typing import Dict, List


class TennisPredictor:
    """
    Deterministic tennis tipster engine using player ids, matchup context and live set state.
    """

    def __init__(self, db):
        self.db = db

    def analyze_match(self, match_data: Dict) -> List[Dict]:
        predictions = []

        home = match_data.get("home", {})
        away = match_data.get("away", {})
        home_name = home.get("name", "Local")
        away_name = away.get("name", "Visitante")
        round_name = str(match_data.get("round", ""))
        surface = self._infer_surface(match_data)

        home_rating = self._player_rating(home, surface)
        away_rating = self._player_rating(away, surface)
        live_boost = self._live_boost(home, away)
        home_rating += live_boost
        away_rating -= live_boost

        rating_gap = home_rating - away_rating
        home_win_prob = self._rating_to_probability(rating_gap)
        away_win_prob = 1.0 - home_win_prob
        favorite_name = home_name if home_win_prob >= away_win_prob else away_name
        favorite_prob = max(home_win_prob, away_win_prob)

        predictions.append({
            "market": "Ganador del encuentro",
            "prediction": f"Moneyline: {favorite_name}",
            "probability": round(favorite_prob, 2),
            "confidence": self._confidence(favorite_prob),
            "rationale": (
                f"Ventaja de matchup estimada en {abs(rating_gap):.1f} puntos de rating sobre {surface}. "
                f"Round: {round_name or 'cuadro principal'}."
            ),
        })

        closeness = 1.0 - min(abs(rating_gap) / 180.0, 1.0)
        base_games = 20.5 + closeness * 3.0
        if "qualifying" in round_name.lower():
            base_games -= 0.7
        total_direction = "OVER" if base_games >= 22.2 else "UNDER"
        total_line = 22.5 if total_direction == "OVER" else 21.5
        total_prob = min(0.71, 0.55 + abs(base_games - total_line) / 10)
        predictions.append({
            "market": "Total de juegos",
            "prediction": f"{total_direction} {total_line}",
            "probability": round(total_prob, 2),
            "confidence": self._confidence(total_prob),
            "rationale": (
                f"Proyección de {base_games:.1f} juegos. Cuanto más parejo el rating, más valor en partidos largos."
            ),
        })

        handicap_games = -2.5 if favorite_prob < 0.67 else -3.5
        if favorite_prob > 0.77:
            handicap_games = -4.5
        handicap_prob = min(0.73, 0.53 + abs(rating_gap) / 260.0)
        predictions.append({
            "market": "Handicap de juegos",
            "prediction": f"{favorite_name} {handicap_games} games",
            "probability": round(handicap_prob, 2),
            "confidence": self._confidence(handicap_prob),
            "rationale": (
                f"Diferencial técnico y situación de sets favorecen cubrir handicap de {handicap_games}."
            ),
        })

        return predictions

    def _player_rating(self, player: Dict, surface: str) -> float:
        seed_text = f"{player.get('id')}-{player.get('name')}-{surface}".encode("utf-8")
        digest = hashlib.md5(seed_text).hexdigest()
        base = 1860 + (int(digest[:6], 16) % 320)
        country = str(player.get("country", "")).lower()
        if surface == "clay" and any(token in country for token in ("spain", "argentina", "italy", "uruguay", "chile")):
            base += 25
        if surface == "grass" and any(token in country for token in ("great britain", "australia")):
            base += 18
        if surface == "hard" and any(token in country for token in ("usa", "united states", "canada")):
            base += 12
        return float(base)

    @staticmethod
    def _rating_to_probability(rating_gap: float) -> float:
        return 1 / (1 + 10 ** (-rating_gap / 400))

    @staticmethod
    def _infer_surface(match_data: Dict) -> str:
        text = f"{match_data.get('name', '')} {match_data.get('venue', '')}".lower()
        if any(token in text for token in ("monte-carlo", "barcelona", "madrid", "rome", "munich", "clay")):
            return "clay"
        if any(token in text for token in ("wimbledon", "halle", "queen", "grass")):
            return "grass"
        return "hard"

    @staticmethod
    def _set_score(player: Dict) -> int:
        try:
            return int(player.get("score", 0) or 0)
        except Exception:
            return 0

    def _live_boost(self, home: Dict, away: Dict) -> float:
        set_gap = self._set_score(home) - self._set_score(away)
        if set_gap == 0:
            return 0.0
        return set_gap * 55.0

    @staticmethod
    def _confidence(probability: float) -> str:
        if probability >= 0.69:
            return "HIGH"
        if probability >= 0.58:
            return "MEDIUM"
        return "LOW"
