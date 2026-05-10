"""
Anomaly Detector Engine — STUBET Premium Intelligence
Detects massive, sudden odds drops or irregular betting patterns.
Distinguishes between: Normal Live Movement vs TRUE Insider/Match-Fixing activity.
"""
import logging
import time
from typing import Dict, Optional
from cachetools import TTLCache  # type: ignore

logger = logging.getLogger(__name__)


class AnomalyDetector:
    def __init__(self, telegram_bot=None):
        self.telegram = telegram_bot
        # Cache: "eventId_market_outcome" -> {initial_odd, timestamp, alerts_sent, is_live}
        self.opening_odds_cache = TTLCache(maxsize=10000, ttl=86400 * 3)  # 3-day memory
        # Track alert cooldown per event to avoid spam
        self.alert_cooldown = TTLCache(maxsize=5000, ttl=3600)  # 1hr cooldown per alert

    async def analyze_odds_movement(
        self,
        event_id: str,
        sport: str,
        home_name: str,
        away_name: str,
        market_name: str,
        outcome_name: str,
        current_odd: float,
        is_live: bool = False,
        minute: int = 0,
        score_home: int = 0,
        score_away: int = 0,
    ):
        """
        Analyzes odds movement and categorizes as:
        - NORMAL (live in-game swing based on score/time)
        - SUSPICIOUS (pre-match drop >30% without obvious cause)
        - CRITICAL (extreme pre-match drop >45%)
        """
        if current_odd <= 1.05:
            return  # Ignore near-certain priced events

        if "DEPORTE DESCONOCIDO" in sport.upper() or "Mismo Evento" in home_name or "Mismo Evento" in away_name:
            return  # Ignore generic outrights or unknown sports (protects against phantom drops)

        cache_key = f"{event_id}_{market_name}_{outcome_name}"
        alert_key = f"alert_{cache_key}"

        # Register opening odds on first sight
        if cache_key not in self.opening_odds_cache:
            self.opening_odds_cache[cache_key] = {
                "initial_odd": current_odd,
                "timestamp": time.time(),
                "is_live": is_live,
            }
            return

        opening_data = self.opening_odds_cache[cache_key]
        initial_odd = opening_data["initial_odd"]

        if initial_odd == 0:
            return

        drop_pct = ((initial_odd - current_odd) / initial_odd) * 100
        rise_pct = ((current_odd - initial_odd) / initial_odd) * 100

        # --- 1. NORMAL LIVE MOVEMENT (no alert) ---
        # Score-driven: if there's a goal or the match is live, odds swinging is natural
        if is_live:
            has_goal = (score_home + score_away) > 0
            time_factor = minute > 30  # After 30min, even 0-0 affects draw odds heavily

            # If drop < 40% AND it's live AND there's a goal or significant time passed → normal
            if drop_pct < 40.0 and (has_goal or time_factor):
                return  # Expected live market reaction — no alert

            # If it's a RISE (odds going up) on live → also normal (losing team's odds improve)
            if rise_pct > 0:
                return

        # --- 2. DROP THRESHOLD TRIGGERS ---
        threshold = 45.0 if is_live else 30.0  # Higher bar for live anomalies
        if drop_pct < threshold:
            return

        # --- 3. DEDUP: Don't spam same alert ---
        if alert_key in self.alert_cooldown:
            return
        self.alert_cooldown[alert_key] = True

        # Reset baseline to current to track further movements
        self.opening_odds_cache[cache_key]["initial_odd"] = current_odd

        # --- 4. Categorize severity ---
        if drop_pct >= 50:
            severity = "🔴 CRÍTICO"
            classification = "AMAÑO CONFIRMADO / INSIDER TRADE MASIVO"
            explanation = (
                "Una caída de esta magnitud es estadísticamente imposible sin información privilegiada. "
                "Con más del 50% de caída, el mercado ha recibido dinero organizado (sindicato de apuestas). "
                "Esto puede indicar: resultado pactado, lesión estrella no comunicada, o información de formación falsa."
            )
        elif drop_pct >= 35:
            severity = "🟠 ALTO"
            classification = "POSIBLE INFORMACIÓN PRIVILEGIADA"
            explanation = (
                "Caídas entre 35-50% en pre-partido son el patrón clásico de 'Smart Money' (dinero inteligente). "
                "Puede ser: baja de jugador clave filtrada a círculos internos, cambio táctico secreto, "
                "o apuesta coordinada de grupos organizados. Verificar noticias en últimas 2 horas."
            )
        else:
            severity = "🟡 MODERADO"
            classification = "MOVIMIENTO SOSPECHOSO — MONITOREAR"
            explanation = (
                "Caída significativa pero puede tener causa legítima. "
                "Posibles motivos: flujo de apuestas público (partido popular), ajuste de la bookie por balance de libro, "
                "o información de última hora. Verificar antes de actuar."
            )

        logger.warning(f"🚨 ANOMALY [{severity}]: {home_name} vs {away_name} — {drop_pct:.1f}% drop on {market_name}/{outcome_name}")

        await self._trigger_stubet_alert(
            sport=sport,
            home=home_name,
            away=away_name,
            market=market_name,
            outcome=outcome_name,
            initial_odd=initial_odd,
            current_odd=current_odd,
            drop_pct=drop_pct,
            severity=severity,
            classification=classification,
            explanation=explanation,
            is_live=is_live,
            minute=minute,
            score=f"{score_home}-{score_away}",
        )

    async def _trigger_stubet_alert(
        self,
        sport: str,
        home: str,
        away: str,
        market: str,
        outcome: str,
        initial_odd: float,
        current_odd: float,
        drop_pct: float,
        severity: str,
        classification: str,
        explanation: str,
        is_live: bool,
        minute: int,
        score: str,
    ):
        """Sends a professional STUBET-style Telegram alert."""

        context_line = (
            f"⏱️ <b>EN VIVO — Minuto {minute}</b> | Marcador: {score}"
            if is_live
            else "🕐 <b>PRE-PARTIDO</b> — Movimiento detectado ANTES del inicio"
        )

        action_guide = (
            "⚡ <b>ACCIÓN RECOMENDADA:</b> NO actúes. En live, las cuotas se mueven por el juego. "
            "Espera análisis completo."
            if is_live and drop_pct < 50
            else "⚡ <b>ACCIÓN RECOMENDADA:</b> Investiga antes de apostar. Si tienes posición abierta, evalúa si cierra o mantiene. "
            "Consultar noticias oficiales del club."
        )

        message = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👑 <b>STUBET — ALERTA DE MERCADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔎 <b>{classification}</b>\n"
            f"Severidad: {severity}\n\n"
            f"⚽ <b>Partido:</b> {home} vs {away}\n"
            f"🏅 <b>Deporte:</b> {sport.upper()}\n"
            f"{context_line}\n\n"
            f"📉 <b>MOVIMIENTO DE CUOTA:</b>\n"
            f"  Mercado: {market} — {outcome}\n"
            f"  Apertura: <b>{initial_odd:.2f}</b> ➡️ Actual: <b>{current_odd:.2f}</b>\n"
            f"  💥 Caída: <b>{drop_pct:.1f}%</b>\n\n"
            f"🧠 <b>ANÁLISIS STUBET [STATS LIVE]:</b>\n"
            f"{explanation}\n\n"
            f"{action_guide}\n\n"
            f"⚠️ <i>Verifica siempre con Sofascore/Flashscore antes de tomar decisiones.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        print(f"\n{'='*60}\n{message}\n{'='*60}\n")
        if self.telegram:
            self.telegram.send_message(message)
