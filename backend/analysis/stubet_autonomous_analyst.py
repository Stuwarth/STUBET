"""
STUBET autonomous football analyst.

Implements a self-improving, event-based analysis workflow:
- Pre-match locked prediction
- Lineup-confirmed re-analysis with change tracking
- Post-match evaluation and lightweight weight adaptation
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import re


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    found = re.search(r"[-+]?\d+(?:[\.,]\d+)?", text)
    if not found:
        return None

    try:
        return float(found.group(0).replace(",", "."))
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _mean(values: List[float]) -> Optional[float]:
    valid = [float(v) for v in values if isinstance(v, (int, float))]
    if not valid:
        return None
    return sum(valid) / len(valid)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_period(value: Any) -> str:
    raw = _normalize_text(value).replace(" ", "")
    if raw in {"all", "full", "fulltime", "ft"}:
        return "ALL"
    if raw in {"1", "1st", "first", "firsthalf", "1sthalf"}:
        return "1ST"
    if raw in {"2", "2nd", "second", "secondhalf", "2ndhalf"}:
        return "2ND"
    return str(value or "ALL").upper()


class StubetAutonomousAnalyst:
    """Autonomous analysis orchestrator for STUBET match-level decisions."""

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "form_recent": 1.00,
        "h2h": 0.95,
        "venue_split": 1.08,
        "goal_trend": 1.00,
        "btts_trend": 1.00,
        "absences": 1.15,
        "suspensions": 1.10,
        "live_xg": 0.90,
        "shots_on_target": 0.95,
        "motivation_standings": 1.20,
    }

    def __init__(self, store_path: Optional[Path] = None):
        root = Path(__file__).resolve().parent.parent.parent
        default_path = root / "data" / "models" / "stubet_autonomous_learning.json"
        self.store_path = store_path or default_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    # ----------------------------
    # Public API
    # ----------------------------

    def analyze_event(
        self,
        match_center: Dict[str, Any],
        stage: str = "pre_match",
        odds_payload: Optional[Dict[str, Any]] = None,
        external_context: Optional[Dict[str, Any]] = None,
        lock_prediction: bool = True,
    ) -> Dict[str, Any]:
        stage_key = _normalize_text(stage) or "pre_match"
        if stage_key not in {"pre_match", "lineup_confirmed", "live"}:
            stage_key = "pre_match"

        event_id = _safe_int(match_center.get("event_id"))
        if not event_id:
            return {
                "status": "error",
                "message": "event_id not found in match-center payload",
            }

        store = self._load_store()
        event_state = self._get_or_create_event_state(store, event_id)

        # Pre-match predictions are immutable once locked.
        if stage_key == "pre_match" and lock_prediction:
            locked = event_state.get("pre_match")
            if isinstance(locked, dict):
                report = dict(locked)
                meta = report.get("meta", {}) if isinstance(report.get("meta"), dict) else {}
                meta["returned_from_lock"] = True
                report["meta"] = meta
                return report

        report = self._build_report(
            match_center=match_center,
            stage_key=stage_key,
            odds_payload=odds_payload,
            external_context=external_context,
            event_state=event_state,
            weights=store.get("weights", {}),
        )

        if stage_key == "pre_match" and lock_prediction:
            event_state["pre_match"] = report
            event_state.setdefault("meta", {})["pre_match_locked_at"] = _now_iso()
        elif stage_key == "lineup_confirmed":
            event_state["lineup_confirmed"] = report

        event_state.setdefault("meta", {})["last_analysis_stage"] = stage_key
        event_state.setdefault("meta", {})["last_analysis_at"] = _now_iso()
        self._save_store(store)

        return report

    def evaluate_post_match(
        self,
        match_center: Dict[str, Any],
        prefer_lineup_prediction: bool = True,
    ) -> Dict[str, Any]:
        event_id = _safe_int(match_center.get("event_id"))
        if not event_id:
            return {"status": "error", "message": "event_id missing"}

        store = self._load_store()
        event_state = self._get_or_create_event_state(store, event_id)

        pre_report = event_state.get("pre_match") if isinstance(event_state.get("pre_match"), dict) else None
        lineup_report = event_state.get("lineup_confirmed") if isinstance(event_state.get("lineup_confirmed"), dict) else None
        if not pre_report and not lineup_report:
            return {
                "status": "error",
                "message": "No pre-match or lineup prediction stored for this event",
            }

        actual = self._extract_actual_result(match_center)
        if not actual.get("finished"):
            return {
                "status": "pending",
                "message": "Match is not finished yet",
                "actual": actual,
            }

        evaluations: Dict[str, Any] = {}
        if pre_report:
            evaluations["pre_match"] = self._evaluate_prediction(pre_report.get("prediction", {}), actual)
        if lineup_report:
            evaluations["lineup_confirmed"] = self._evaluate_prediction(lineup_report.get("prediction", {}), actual)

        chosen_label = "lineup_confirmed" if (prefer_lineup_prediction and lineup_report) else "pre_match"
        chosen_report = lineup_report if chosen_label == "lineup_confirmed" else pre_report
        chosen_eval = evaluations.get(chosen_label, {})

        learning = self._apply_learning(
            store=store,
            event_id=event_id,
            prediction=chosen_report.get("prediction", {}) if isinstance(chosen_report, dict) else {},
            was_hit=bool(chosen_eval.get("is_hit")),
        )

        post_entry = {
            "status": "success",
            "generated_at": _now_iso(),
            "actual": actual,
            "evaluations": evaluations,
            "evaluated_prediction": chosen_label,
            "learning": learning,
        }

        event_state["post_match"] = post_entry
        event_state.setdefault("meta", {})["last_post_match_at"] = _now_iso()
        self._save_store(store)

        return post_entry

    def get_event_state(self, event_id: int) -> Dict[str, Any]:
        store = self._load_store()
        return store.get("events", {}).get(str(event_id), {})

    def signal_already_sent(self, event_id: int, signal_key: str) -> bool:
        state = self.get_event_state(event_id)
        signals = state.get("signals", {}) if isinstance(state.get("signals"), dict) else {}
        return isinstance(signals.get(signal_key), dict)

    def mark_signal_sent(self, event_id: int, signal_key: str, payload: Optional[Dict[str, Any]] = None) -> None:
        store = self._load_store()
        event_state = self._get_or_create_event_state(store, event_id)
        signals = event_state.setdefault("signals", {})
        signals[signal_key] = {
            "sent_at": _now_iso(),
            "payload": payload or {},
        }
        self._save_store(store)

    # ----------------------------
    # Core report building
    # ----------------------------

    def _build_report(
        self,
        match_center: Dict[str, Any],
        stage_key: str,
        odds_payload: Optional[Dict[str, Any]],
        external_context: Optional[Dict[str, Any]],
        event_state: Dict[str, Any],
        weights: Dict[str, Any],
    ) -> Dict[str, Any]:
        event_summary = match_center.get("event_summary", {}) if isinstance(match_center.get("event_summary"), dict) else {}
        ai_context = match_center.get("ai_context", {}) if isinstance(match_center.get("ai_context"), dict) else {}
        history = match_center.get("history", {}) if isinstance(match_center.get("history"), dict) else {}
        lineup = match_center.get("lineup", {}) if isinstance(match_center.get("lineup"), dict) else {}
        statistics = match_center.get("statistics", []) if isinstance(match_center.get("statistics"), list) else []

        home_team = event_summary.get("home_team", {}) if isinstance(event_summary.get("home_team"), dict) else {}
        away_team = event_summary.get("away_team", {}) if isinstance(event_summary.get("away_team"), dict) else {}
        home_team_id = _safe_int(home_team.get("id"))
        away_team_id = _safe_int(away_team.get("id"))
        home_pts = _safe_int(home_team.get("points"))
        away_pts = _safe_int(away_team.get("points"))

        home_rows = history.get("home_last10", []) if isinstance(history.get("home_last10"), list) else []
        away_rows = history.get("away_last10", []) if isinstance(history.get("away_last10"), list) else []
        h2h_rows = history.get("h2h", []) if isinstance(history.get("h2h"), list) else []

        home_bucket = ai_context.get("home_last10", {}) if isinstance(ai_context.get("home_last10"), dict) else {}
        away_bucket = ai_context.get("away_last10", {}) if isinstance(ai_context.get("away_last10"), dict) else {}
        h2h_bucket = ai_context.get("h2h", {}) if isinstance(ai_context.get("h2h"), dict) else {}

        home_form = home_bucket.get("form", {}) if isinstance(home_bucket.get("form"), dict) else self._summarize_rows_form(home_rows, home_team_id)
        away_form = away_bucket.get("form", {}) if isinstance(away_bucket.get("form"), dict) else self._summarize_rows_form(away_rows, away_team_id)
        h2h_form = h2h_bucket.get("form", {}) if isinstance(h2h_bucket.get("form"), dict) else self._summarize_h2h_form(h2h_rows, home_team_id, away_team_id)

        home_venue = self._summarize_rows_form(home_rows, home_team_id, venue="home")
        away_venue = self._summarize_rows_form(away_rows, away_team_id, venue="away")

        home_abs = self._summarize_absences(lineup.get("home", {}) if isinstance(lineup.get("home"), dict) else {})
        away_abs = self._summarize_absences(lineup.get("away", {}) if isinstance(lineup.get("away"), dict) else {})

        live_xg_home, live_xg_away = self._extract_live_metric(statistics, "expected goals")
        live_shots_home, live_shots_away = self._extract_live_metric(statistics, "shots on target")
        external_signals = self._summarize_external_context(external_context)

        model_weights = self._normalize_weights(weights)
        feature_pack = {
            "home_form": home_form,
            "away_form": away_form,
            "h2h_form": h2h_form,
            "home_venue": home_venue,
            "away_venue": away_venue,
            "home_absences": home_abs,
            "away_absences": away_abs,
            "live_xg_home": live_xg_home,
            "live_xg_away": live_xg_away,
            "live_shots_home": live_shots_home,
            "live_shots_away": live_shots_away,
            "home_pts": home_pts,
            "away_pts": away_pts,
            "external": external_signals,
            "weights": model_weights,
        }

        scores, rationales, drivers = self._score_markets(feature_pack)
        selection = self._select_prediction(scores)

        top_score = selection.get("score", 0.0)
        sorted_scores = sorted(scores.values(), reverse=True)
        second_score = sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]
        margin = max(0.0, top_score - second_score)
        confidence_pct = _clamp(top_score + (margin * 1.7), 50.0, 93.0)

        lineups_confirmed = bool(lineup.get("confirmed"))
        if stage_key == "pre_match" and not lineups_confirmed:
            confidence_pct = min(confidence_pct, 84.0)
        if stage_key == "lineup_confirmed" and lineups_confirmed:
            confidence_pct = _clamp(confidence_pct + 2.5, 50.0, 95.0)
        if stage_key == "live":
            confidence_pct = _clamp(confidence_pct + 1.5, 50.0, 95.0)

        if external_signals.get("impact_level") == "HIGH":
            confidence_pct = _clamp(confidence_pct - 2.0, 45.0, 95.0)

        stake = self._compute_stake(confidence_pct, margin, lineups_confirmed)
        market_reasons = rationales.get(selection.get("key"), [])
        market_drivers = drivers.get(selection.get("key"), [])

        odds_value = self._resolve_reference_odds(selection, odds_payload)
        implied_prob = round((1.0 / odds_value) * 100.0, 2) if isinstance(odds_value, (int, float)) and odds_value > 0 else None

        pre_match = event_state.get("pre_match", {}) if isinstance(event_state.get("pre_match"), dict) else {}
        previous_pred = pre_match.get("prediction", {}) if isinstance(pre_match.get("prediction"), dict) else {}
        changed_vs_pre = bool(previous_pred) and previous_pred.get("selection") != selection.get("selection")

        scenarios = self._build_scenarios(feature_pack, selection, confidence_pct)

        return {
            "status": "success",
            "stage": stage_key,
            "generated_at": _now_iso(),
            "event": {
                "id": match_center.get("event_id"),
                "home_team": home_team,
                "away_team": away_team,
                "tournament": event_summary.get("tournament"),
                "category": event_summary.get("category"),
                "round": event_summary.get("round"),
                "kickoff_utc": event_summary.get("kickoff_utc"),
                "status": event_summary.get("status"),
                "status_type": event_summary.get("status_type"),
            },
            "recent_form": {
                "home_last10": home_form,
                "away_last10": away_form,
            },
            "h2h_analysis": {
                "summary": h2h_form,
                "sample_size": len(h2h_rows),
            },
            "home_vs_away_behavior": {
                "home_team_at_home": home_venue,
                "away_team_away": away_venue,
            },
            "absences_and_sanctions": {
                "home": home_abs,
                "away": away_abs,
                "impact_note": self._build_absence_impact_note(home_abs, away_abs),
            },
            "psychological_context": self._build_psychological_context(event_summary, home_form, away_form, lineups_confirmed),
            "external_factors": external_signals,
            "important_note": self._build_important_note(external_signals),
            "scenarios": scenarios,
            "prediction": {
                "market": selection.get("market"),
                "selection": selection.get("selection"),
                "confidence_pct": round(confidence_pct, 2),
                "stake": stake,
                "bookmaker_odds": odds_value,
                "implied_probability_pct": implied_prob,
                "reasoning": market_reasons,
                "drivers": market_drivers,
                "scoreboard": {k: round(v, 2) for k, v in scores.items()},
            },
            "lineup_adjustment": {
                "lineups_confirmed": lineups_confirmed,
                "changed_vs_pre_match": changed_vs_pre,
                "previous_selection": previous_pred.get("selection"),
                "why_changed": market_reasons[:3] if changed_vs_pre else [],
            },
            "meta": {
                "locked_prediction": bool(stage_key == "pre_match"),
                "weights_in_use": model_weights,
            },
        }

    # ----------------------------
    # Feature extraction helpers
    # ----------------------------

    def _summarize_rows_form(self, rows: List[Dict[str, Any]], team_id: Optional[int], venue: Optional[str] = None) -> Dict[str, Any]:
        wins = draws = losses = 0
        scored: List[float] = []
        conceded: List[float] = []

        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not team_id:
                continue
            home_id = _safe_int(row.get("home_team_id"))
            away_id = _safe_int(row.get("away_team_id"))
            if home_id != team_id and away_id != team_id:
                continue
            if venue == "home" and home_id != team_id:
                continue
            if venue == "away" and away_id != team_id:
                continue

            home_score = _safe_float(row.get("home_score"))
            away_score = _safe_float(row.get("away_score"))
            if home_score is None or away_score is None:
                continue

            is_home = home_id == team_id
            gf = home_score if is_home else away_score
            ga = away_score if is_home else home_score
            scored.append(gf)
            conceded.append(ga)

            if gf > ga:
                wins += 1
            elif gf < ga:
                losses += 1
            else:
                draws += 1

        total = wins + draws + losses
        btts_hits = 0
        over25_hits = 0
        for gf, ga in zip(scored, conceded):
            if gf > 0 and ga > 0:
                btts_hits += 1
            if (gf + ga) > 2.5:
                over25_hits += 1

        return {
            "sample_size": total,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "win_rate": round((wins / total) * 100, 1) if total else 0.0,
            "goals_for_avg": round((_mean(scored) or 0.0), 2) if total else None,
            "goals_against_avg": round((_mean(conceded) or 0.0), 2) if total else None,
            "btts_rate": round((btts_hits / total) * 100, 1) if total else None,
            "over25_rate": round((over25_hits / total) * 100, 1) if total else None,
        }

    def _summarize_h2h_form(self, rows: List[Dict[str, Any]], home_team_id: Optional[int], away_team_id: Optional[int]) -> Dict[str, Any]:
        home_wins = away_wins = draws = 0
        totals: List[float] = []
        btts = 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            home_score = _safe_float(row.get("home_score"))
            away_score = _safe_float(row.get("away_score"))
            row_home_id = _safe_int(row.get("home_team_id"))
            row_away_id = _safe_int(row.get("away_team_id"))
            if home_score is None or away_score is None:
                continue

            totals.append(home_score + away_score)
            if home_score > 0 and away_score > 0:
                btts += 1

            if row_home_id == home_team_id and row_away_id == away_team_id:
                if home_score > away_score:
                    home_wins += 1
                elif home_score < away_score:
                    away_wins += 1
                else:
                    draws += 1
            elif row_home_id == away_team_id and row_away_id == home_team_id:
                if home_score > away_score:
                    away_wins += 1
                elif home_score < away_score:
                    home_wins += 1
                else:
                    draws += 1

        sample = home_wins + away_wins + draws
        over25 = len([x for x in totals if x > 2.5])
        return {
            "sample_size": sample,
            "home_wins": home_wins,
            "away_wins": away_wins,
            "draws": draws,
            "btts_rate": round((btts / sample) * 100, 1) if sample else None,
            "over25_rate": round((over25 / sample) * 100, 1) if sample else None,
        }

    def _extract_live_metric(self, statistics: List[Dict[str, Any]], metric_name: str) -> Tuple[Optional[float], Optional[float]]:
        key = _normalize_text(metric_name)
        for period in statistics if isinstance(statistics, list) else []:
            if not isinstance(period, dict):
                continue
            if _normalize_period(period.get("period")) != "ALL":
                continue
            groups = period.get("groups", []) if isinstance(period.get("groups"), list) else []
            for group in groups:
                if not isinstance(group, dict):
                    continue
                items = group.get("items", []) if isinstance(group.get("items"), list) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if _normalize_text(item.get("name")) == key:
                        return _safe_float(item.get("home")), _safe_float(item.get("away"))
        return None, None

    def _summarize_absences(self, lineup_side: Dict[str, Any]) -> Dict[str, Any]:
        missing = lineup_side.get("missing", []) if isinstance(lineup_side.get("missing"), list) else []
        suspended = doubtful = injured = 0
        for row in missing:
            if not isinstance(row, dict):
                continue
            status = _normalize_text(row.get("status"))
            suspension_kind = _normalize_text(row.get("suspension_kind"))
            if "suspend" in status or suspension_kind not in {"", "none"}:
                suspended += 1
            elif "duda" in status or "question" in status:
                doubtful += 1
            else:
                injured += 1

        total = suspended + doubtful + injured
        impact_score = round((injured * 1.0) + (suspended * 1.35) + (doubtful * 0.45), 2)
        return {
            "total": total,
            "injured": injured,
            "suspended": suspended,
            "doubtful": doubtful,
            "impact_score": impact_score,
        }

    # ----------------------------
    # Scoring model
    # ----------------------------

    def _score_markets(self, features: Dict[str, Any]) -> Tuple[Dict[str, float], Dict[str, List[str]], Dict[str, List[Dict[str, Any]]]]:
        scores: Dict[str, float] = {
            "over_25": 50.0,
            "under_25": 50.0,
            "btts_yes": 50.0,
            "btts_no": 50.0,
            "double_chance_home": 52.0,
            "double_chance_away": 52.0,
        }
        reasons: Dict[str, List[str]] = {k: [] for k in scores}
        drivers: Dict[str, List[Dict[str, Any]]] = {k: [] for k in scores}

        home_form = features.get("home_form", {})
        away_form = features.get("away_form", {})
        h2h_form = features.get("h2h_form", {})
        home_venue = features.get("home_venue", {})
        away_venue = features.get("away_venue", {})
        home_abs = features.get("home_absences", {})
        away_abs = features.get("away_absences", {})
        external = features.get("external", {})
        weights = features.get("weights", {})

        def apply(market_key: str, delta: float, reason: str, driver_key: str) -> None:
            scores[market_key] = scores.get(market_key, 50.0) + delta
            reasons[market_key].append(reason)
            drivers[market_key].append({"key": driver_key, "delta": round(delta, 3), "reason": reason})

        # Over/Under trend from recent form and H2H
        over_rates = [
            _safe_float(home_form.get("over25_rate")),
            _safe_float(away_form.get("over25_rate")),
            _safe_float(h2h_form.get("over25_rate")),
        ]
        over_mean = _mean([x for x in over_rates if x is not None])
        if over_mean is not None:
            delta = (over_mean - 50.0) * 0.32 * float(weights.get("goal_trend", 1.0))
            apply("over_25", delta, f"Over 2.5 combinado en muestra: {round(over_mean, 1)}%.", "goal_trend")
            apply("under_25", -delta, "Lectura inversa del mismo sesgo de goles.", "goal_trend")

        btts_rates = [
            _safe_float(home_form.get("btts_rate")),
            _safe_float(away_form.get("btts_rate")),
            _safe_float(h2h_form.get("btts_rate")),
        ]
        btts_mean = _mean([x for x in btts_rates if x is not None])
        if btts_mean is not None:
            delta = (btts_mean - 50.0) * 0.3 * float(weights.get("btts_trend", 1.0))
            apply("btts_yes", delta, f"BTTS combinado en muestra: {round(btts_mean, 1)}%.", "btts_trend")
            apply("btts_no", -delta, "Lectura inversa del mismo sesgo BTTS.", "btts_trend")

        # Home/Away strength differential
        home_win = _safe_float(home_form.get("win_rate")) or 0.0
        away_win = _safe_float(away_form.get("win_rate")) or 0.0
        home_home_win = _safe_float(home_venue.get("win_rate")) or home_win
        away_away_win = _safe_float(away_venue.get("win_rate")) or away_win
        form_edge = ((home_win - away_win) * 0.5) + ((home_home_win - away_away_win) * 0.7)
        venue_delta = form_edge * 0.18 * float(weights.get("venue_split", 1.0))
        apply("double_chance_home", venue_delta, "Ventaja local vs rendimiento visitante.", "venue_split")
        apply("double_chance_away", -venue_delta, "Lectura inversa de ventaja de sede.", "venue_split")

        # Offensive/defensive trend
        home_gf = _safe_float(home_form.get("goals_for_avg")) or 0.0
        home_ga = _safe_float(home_form.get("goals_against_avg")) or 0.0
        away_gf = _safe_float(away_form.get("goals_for_avg")) or 0.0
        away_ga = _safe_float(away_form.get("goals_against_avg")) or 0.0
        goal_volume = home_gf + away_gf
        defensive_leak = home_ga + away_ga
        trend_delta = ((goal_volume - 2.4) * 7.0 + (defensive_leak - 2.0) * 3.0) * 0.1 * float(weights.get("form_recent", 1.0))
        apply("over_25", trend_delta, "Promedio ofensivo/defensivo reciente favorece volumen de gol.", "form_recent")
        apply("under_25", -trend_delta, "Lectura inversa de volumen de gol.", "form_recent")

        # Motivation & Standings Urgency (Lógica Humana STUBET)
        home_pts = features.get("home_pts")
        away_pts = features.get("away_pts")
        if home_pts is not None and away_pts is not None:
            pts_diff = home_pts - away_pts
            mot_weight = float(weights.get("motivation_standings", 1.20))
            if abs(pts_diff) >= 7:
                relax_delta = 4.5 * mot_weight
                apply("under_25", relax_delta, f"Diferencia de {abs(pts_diff)} pts: líder con poca urgencia ofensiva.", "motivation_standings")
                apply("over_25", -relax_delta, f"Diferencia de {abs(pts_diff)} pts: líder con poca urgencia ofensiva.", "motivation_standings")
                if pts_diff >= 7:
                    apply("double_chance_away", relax_delta * 0.4, "Equipo visitante necesitado vs local relajado.", "motivation_standings")
                else:
                    apply("double_chance_home", relax_delta * 0.4, "Equipo local necesitado vs visitante relajado.", "motivation_standings")
            elif abs(pts_diff) <= 3:
                urgency_delta = 3.5 * mot_weight
                apply("btts_yes", urgency_delta, f"Duelo directo en tabla ({abs(pts_diff)} pts): alta urgencia.", "motivation_standings")
                apply("btts_no", -urgency_delta, f"Duelo directo en tabla ({abs(pts_diff)} pts): alta urgencia.", "motivation_standings")


        # Absences and suspensions
        home_abs_impact = _safe_float(home_abs.get("impact_score")) or 0.0
        away_abs_impact = _safe_float(away_abs.get("impact_score")) or 0.0
        abs_delta = (away_abs_impact - home_abs_impact) * 1.8 * float(weights.get("absences", 1.0))
        apply("double_chance_home", abs_delta, "Impacto de bajas favorece al local.", "absences")
        apply("double_chance_away", -abs_delta, "Impacto de bajas favorece al visitante.", "absences")

        susp_delta = ((_safe_float(away_abs.get("suspended")) or 0.0) - (_safe_float(home_abs.get("suspended")) or 0.0))
        susp_delta = susp_delta * 1.5 * float(weights.get("suspensions", 1.0))
        apply("double_chance_home", susp_delta, "Suspensiones activas ajustan probabilidad de no perder.", "suspensions")
        apply("double_chance_away", -susp_delta, "Suspensiones activas ajustan probabilidad de no perder.", "suspensions")

        # Live/in-play cues (if available)
        live_xg_home = _safe_float(features.get("live_xg_home"))
        live_xg_away = _safe_float(features.get("live_xg_away"))
        if live_xg_home is not None and live_xg_away is not None:
            xg_total = live_xg_home + live_xg_away
            xg_delta = (xg_total - 1.2) * 3.5 * float(weights.get("live_xg", 1.0))
            apply("over_25", xg_delta, "xG en vivo refuerza sesgo de goles.", "live_xg")
            apply("under_25", -xg_delta, "xG en vivo refuerza sesgo de goles.", "live_xg")

        live_sh_home = _safe_float(features.get("live_shots_home"))
        live_sh_away = _safe_float(features.get("live_shots_away"))
        if live_sh_home is not None and live_sh_away is not None:
            shots_total = live_sh_home + live_sh_away
            shot_delta = (shots_total - 5.0) * 1.1 * float(weights.get("shots_on_target", 1.0))
            apply("over_25", shot_delta, "Remates al arco en vivo aportan contexto.", "shots_on_target")
            apply("under_25", -shot_delta, "Remates al arco en vivo aportan contexto.", "shots_on_target")

        # News/context cues from STUBET power source (news/injuries + external factors)
        injury_advantage = _normalize_text(external.get("injury_advantage"))
        if injury_advantage == "home":
            apply("double_chance_home", 2.1, "Contexto externo de bajas favorece al local.", "external_injuries")
            apply("double_chance_away", -2.1, "Contexto externo de bajas favorece al local.", "external_injuries")
        elif injury_advantage == "away":
            apply("double_chance_home", -2.1, "Contexto externo de bajas favorece al visitante.", "external_injuries")
            apply("double_chance_away", 2.1, "Contexto externo de bajas favorece al visitante.", "external_injuries")

        impact_level = _normalize_text(external.get("impact_level"))
        if impact_level == "high":
            apply("under_25", 2.2, "Volatilidad alta por contexto externo: sesgo conservador.", "external_impact")
            apply("over_25", -2.2, "Volatilidad alta por contexto externo: sesgo conservador.", "external_impact")
        elif impact_level == "medium":
            apply("under_25", 0.9, "Contexto externo medio: leve sesgo de control.", "external_impact")
            apply("over_25", -0.9, "Contexto externo medio: leve sesgo de control.", "external_impact")

        pace_risk = _normalize_text(external.get("pace_risk"))
        if pace_risk == "high":
            apply("under_25", 1.3, "Viaje/clima/calendario sugieren ritmo contenido.", "external_pace")
            apply("over_25", -1.3, "Viaje/clima/calendario sugieren ritmo contenido.", "external_pace")

        for key in list(scores.keys()):
            scores[key] = _clamp(scores[key], 35.0, 92.0)

        return scores, reasons, drivers

    def _select_prediction(self, scores: Dict[str, float]) -> Dict[str, Any]:
        key = max(scores.keys(), key=lambda item: scores.get(item, 0.0))
        mapping = {
            "over_25": ("over_under_25", "Over 2.5"),
            "under_25": ("over_under_25", "Under 2.5"),
            "btts_yes": ("btts", "BTTS Si"),
            "btts_no": ("btts", "BTTS No"),
            "double_chance_home": ("double_chance", "1X"),
            "double_chance_away": ("double_chance", "X2"),
        }
        market, selection = mapping.get(key, ("double_chance", "1X"))
        return {
            "key": key,
            "market": market,
            "selection": selection,
            "score": float(scores.get(key, 0.0)),
        }

    def _compute_stake(self, confidence_pct: float, margin: float, lineup_confirmed: bool) -> Dict[str, Any]:
        value = 4
        if confidence_pct >= 58:
            value = 5
        if confidence_pct >= 63:
            value = 6
        if confidence_pct >= 68:
            value = 7
        if confidence_pct >= 74:
            value = 8
        if confidence_pct >= 81:
            value = 9
        if confidence_pct >= 87:
            value = 10

        all_in = None
        if confidence_pct >= 93 and margin >= 9 and lineup_confirmed:
            all_in = 60

        return {
            "value": value,
            "label": f"{value}",
            "all_in": all_in,
            "justification": (
                f"Confianza {round(confidence_pct, 1)}%, margen entre mercados {round(margin, 1)} "
                f"y estado de alineaciones {'confirmadas' if lineup_confirmed else 'por confirmar'}."
            ),
        }

    def _resolve_reference_odds(self, selection: Dict[str, Any], odds_payload: Optional[Dict[str, Any]]) -> Optional[float]:
        if not isinstance(odds_payload, dict):
            return None
        odds_root = odds_payload.get("odds", {}) if isinstance(odds_payload.get("odds"), dict) else {}

        market = selection.get("market")
        pick = selection.get("selection")
        if market == "over_under_25":
            bucket = odds_root.get("over_under_25", {}) if isinstance(odds_root.get("over_under_25"), dict) else {}
            return _safe_float(bucket.get("Over 2.5" if pick == "Over 2.5" else "Under 2.5"))
        if market == "btts":
            bucket = odds_root.get("btts", {}) if isinstance(odds_root.get("btts"), dict) else {}
            return _safe_float(bucket.get("BTTS Yes" if pick == "BTTS Si" else "BTTS No"))
        if market == "double_chance":
            bucket = odds_root.get("double_chance", {}) if isinstance(odds_root.get("double_chance"), dict) else {}
            return _safe_float(bucket.get(pick))
        return None

    def _summarize_external_context(self, external_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(external_context, dict):
            return {
                "source_strength": "minimal",
                "injury_advantage": "neutral",
                "impact_level": "LOW",
                "recommendation": "Sin contexto externo adicional; usar lectura estadistica base.",
                "relevant_news_count": 0,
                "weather_available": False,
                "referee_available": False,
                "pace_risk": "LOW",
            }

        impact = external_context.get("impact_analysis", {}) if isinstance(external_context.get("impact_analysis"), dict) else {}
        severity = impact.get("severity", {}) if isinstance(impact.get("severity"), dict) else {}

        relevant_news = external_context.get("relevant_news", [])
        relevant_news_count = len(relevant_news) if isinstance(relevant_news, list) else 0

        injury_advantage = _normalize_text(impact.get("injury_advantage")) or "neutral"
        impact_level = str(severity.get("impact_level") or "LOW").upper()
        recommendation = str(severity.get("recommendation") or "")

        weather_info = external_context.get("weather")
        weather_available = isinstance(weather_info, dict) and bool(weather_info)

        referee_info = external_context.get("referee")
        if not referee_info and isinstance(external_context.get("context"), dict):
            referee_info = external_context.get("context", {}).get("referees")
        referee_available = bool(referee_info)

        pace_risk = "LOW"
        if impact_level == "HIGH" or relevant_news_count >= 5:
            pace_risk = "HIGH"
        elif impact_level == "MEDIUM" or relevant_news_count >= 2:
            pace_risk = "MEDIUM"

        source_strength = "minimal"
        if relevant_news_count > 0:
            source_strength = "partial"
        if relevant_news_count > 0 and (weather_available or referee_available):
            source_strength = "strong"

        return {
            "source_strength": source_strength,
            "injury_advantage": injury_advantage,
            "impact_level": impact_level,
            "recommendation": recommendation or "Contexto de bajas equilibrado, mantener lectura principal.",
            "relevant_news_count": relevant_news_count,
            "weather_available": weather_available,
            "referee_available": referee_available,
            "pace_risk": pace_risk,
        }

    def _build_important_note(self, external_signals: Dict[str, Any]) -> str:
        impact_level = str(external_signals.get("impact_level") or "LOW").upper()
        recommendation = str(external_signals.get("recommendation") or "")
        source_strength = str(external_signals.get("source_strength") or "minimal")

        weather_status = "si" if external_signals.get("weather_available") else "no"
        referee_status = "si" if external_signals.get("referee_available") else "no"
        news_count = int(external_signals.get("relevant_news_count") or 0)

        if impact_level == "HIGH":
            base = "Riesgo externo alto detectado; bajar exposicion y priorizar mercados cubiertos."
        elif impact_level == "MEDIUM":
            base = "Riesgo externo medio; ajustar stake y confirmar alineaciones antes del disparo final."
        else:
            base = "Sin alerta externa severa; se mantiene el enfoque estadistico principal."

        note = (
            f"{base} Fuente externa={source_strength}; noticias relevantes={news_count}; "
            f"clima disponible={weather_status}; arbitraje disponible={referee_status}. "
            f"{recommendation}"
        )
        return note.strip()

    # ----------------------------
    # Scenario and context
    # ----------------------------

    def _build_psychological_context(
        self,
        event_summary: Dict[str, Any],
        home_form: Dict[str, Any],
        away_form: Dict[str, Any],
        lineups_confirmed: bool,
    ) -> Dict[str, Any]:
        tournament = str(event_summary.get("tournament") or "")
        round_name = str(event_summary.get("round") or "")
        context_text = f"{tournament} {round_name}".lower()

        motivation = "media"
        if any(token in context_text for token in ["final", "semi", "playoff", "elimin", "cup"]):
            motivation = "alta"
        elif any(token in context_text for token in ["friendly", "amistoso"]):
            motivation = "baja"

        def mood(form: Dict[str, Any]) -> str:
            wins = _safe_float(form.get("wins")) or 0
            losses = _safe_float(form.get("losses")) or 0
            if wins >= 6:
                return "racha positiva"
            if losses >= 6:
                return "racha negativa"
            return "momento mixto"

        return {
            "what_is_at_stake": (
                "Lectura contextual basada en torneo/ronda. Para tabla exacta o objetivos europeos/descenso, "
                "se recomienda complementar con standings en tiempo real."
            ),
            "motivation_level": motivation,
            "lineup_expectation": "titulares confirmados" if lineups_confirmed else "posibles rotaciones hasta confirmacion",
            "home_mood": mood(home_form),
            "away_mood": mood(away_form),
        }

    def _build_scenarios(self, features: Dict[str, Any], base_selection: Dict[str, Any], confidence_pct: float) -> List[Dict[str, Any]]:
        home_abs = features.get("home_absences", {})
        away_abs = features.get("away_absences", {})
        home_impact = _safe_float(home_abs.get("impact_score")) or 0.0
        away_impact = _safe_float(away_abs.get("impact_score")) or 0.0

        safe_side_pick = "1X" if home_impact <= away_impact else "X2"
        abs_pick = "X2" if home_impact > away_impact else "1X"

        return [
            {
                "id": "A",
                "name": "Titulares y motivacion maxima",
                "projected_pick": base_selection.get("selection"),
                "confidence_pct": round(_clamp(confidence_pct + 3.0, 45.0, 95.0), 1),
                "note": "Con titulares y contexto competitivo alto, se mantiene el pick principal.",
            },
            {
                "id": "B",
                "name": "Rotaciones parciales",
                "projected_pick": safe_side_pick,
                "confidence_pct": round(_clamp(confidence_pct - 7.0, 40.0, 95.0), 1),
                "note": "Con rotaciones el modelo reduce riesgo y prioriza doble oportunidad.",
            },
            {
                "id": "C",
                "name": "Bajas importantes activas",
                "projected_pick": abs_pick,
                "confidence_pct": round(_clamp(confidence_pct - 4.0, 40.0, 95.0), 1),
                "note": "Las ausencias de mayor impacto redirigen el sesgo del pick.",
            },
            {
                "id": "D",
                "name": "Factores externos (viaje, clima, doble competencia)",
                "projected_pick": "Under 2.5",
                "confidence_pct": round(_clamp(confidence_pct - 9.0, 38.0, 95.0), 1),
                "note": "Si aparecen condicionantes externos fuertes, se recomienda sesgo conservador.",
            },
        ]

    def _build_absence_impact_note(self, home_abs: Dict[str, Any], away_abs: Dict[str, Any]) -> str:
        home_score = _safe_float(home_abs.get("impact_score")) or 0.0
        away_score = _safe_float(away_abs.get("impact_score")) or 0.0
        if abs(home_score - away_score) < 0.6:
            return "Impacto de bajas equilibrado entre ambos equipos."
        if home_score > away_score:
            return "El local llega mas condicionado por bajas/sanciones."
        return "El visitante llega mas condicionado por bajas/sanciones."

    # ----------------------------
    # Post-match evaluation
    # ----------------------------

    def _extract_actual_result(self, match_center: Dict[str, Any]) -> Dict[str, Any]:
        summary = match_center.get("event_summary", {}) if isinstance(match_center.get("event_summary"), dict) else {}
        status_type = _normalize_text(summary.get("status_type"))
        home_score = _safe_int((summary.get("home_team") or {}).get("score") if isinstance(summary.get("home_team"), dict) else None)
        away_score = _safe_int((summary.get("away_team") or {}).get("score") if isinstance(summary.get("away_team"), dict) else None)
        finished = status_type in {"finished", "afterpens", "aet"} and home_score is not None and away_score is not None
        return {
            "finished": finished,
            "status_type": status_type,
            "home_score": home_score,
            "away_score": away_score,
            "total_goals": (home_score + away_score) if (home_score is not None and away_score is not None) else None,
        }

    def _evaluate_prediction(self, prediction: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
        if not actual.get("finished"):
            return {"is_hit": None, "reason": "match_not_finished"}

        pick = str(prediction.get("selection") or "")
        home_score = _safe_int(actual.get("home_score")) or 0
        away_score = _safe_int(actual.get("away_score")) or 0
        total = home_score + away_score

        is_hit: Optional[bool] = None
        if pick == "Over 2.5":
            is_hit = total > 2
        elif pick == "Under 2.5":
            is_hit = total <= 2
        elif pick == "BTTS Si":
            is_hit = home_score > 0 and away_score > 0
        elif pick == "BTTS No":
            is_hit = not (home_score > 0 and away_score > 0)
        elif pick == "1X":
            is_hit = home_score >= away_score
        elif pick == "X2":
            is_hit = away_score >= home_score

        return {
            "selection": pick,
            "is_hit": is_hit,
            "scoreline": f"{home_score}-{away_score}",
        }

    def _apply_learning(
        self,
        store: Dict[str, Any],
        event_id: int,
        prediction: Dict[str, Any],
        was_hit: bool,
    ) -> Dict[str, Any]:
        weights = self._normalize_weights(store.get("weights", {}))
        drivers = prediction.get("drivers", []) if isinstance(prediction.get("drivers"), list) else []

        delta_base = 0.04 if was_hit else -0.05
        changes: Dict[str, float] = {}

        patterns = store.setdefault("patterns", {})
        for row in drivers[:6]:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            if key not in weights:
                continue

            updated = _clamp(float(weights[key]) + delta_base, 0.6, 2.4)
            changes[key] = round(updated - float(weights[key]), 4)
            weights[key] = round(updated, 4)

            bucket = patterns.setdefault(key, {"hits": 0, "fails": 0, "last_event_id": None, "updated_at": None})
            if was_hit:
                bucket["hits"] = int(bucket.get("hits", 0)) + 1
            else:
                bucket["fails"] = int(bucket.get("fails", 0)) + 1
            bucket["last_event_id"] = event_id
            bucket["updated_at"] = _now_iso()

        store["weights"] = weights
        store["updated_at"] = _now_iso()

        return {
            "was_hit": was_hit,
            "weight_changes": changes,
            "updated_weights": weights,
            "learning_note": (
                "Variables reforzadas por acierto." if was_hit else "Variables penalizadas por fallo para recalibrar el modelo."
            ),
        }

    # ----------------------------
    # Persistence
    # ----------------------------

    def _default_store(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "updated_at": _now_iso(),
            "weights": dict(self.DEFAULT_WEIGHTS),
            "events": {},
            "patterns": {},
        }

    def _normalize_weights(self, weights: Any) -> Dict[str, float]:
        normalized = dict(self.DEFAULT_WEIGHTS)
        if isinstance(weights, dict):
            for key, default in self.DEFAULT_WEIGHTS.items():
                value = _safe_float(weights.get(key))
                normalized[key] = round(_clamp(value if value is not None else default, 0.6, 2.4), 4)
        return normalized

    def _load_store(self) -> Dict[str, Any]:
        if not self.store_path.exists():
            return self._default_store()

        try:
            raw = self.store_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return self._default_store()
            parsed.setdefault("events", {})
            parsed.setdefault("patterns", {})
            parsed["weights"] = self._normalize_weights(parsed.get("weights", {}))
            parsed.setdefault("updated_at", _now_iso())
            return parsed
        except Exception:
            return self._default_store()

    def _save_store(self, store: Dict[str, Any]) -> None:
        store["updated_at"] = _now_iso()
        try:
            self.store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # Non-fatal: analysis still returned even if persistence fails.
            return

    def _get_or_create_event_state(self, store: Dict[str, Any], event_id: int) -> Dict[str, Any]:
        events = store.setdefault("events", {})
        key = str(event_id)
        state = events.get(key)
        if not isinstance(state, dict):
            state = {"meta": {}, "signals": {}}
            events[key] = state
        state.setdefault("meta", {})
        state.setdefault("signals", {})
        return state
