"""
STUBET Live Alert Engine
Analiza partidos en vivo y envía alertas a Telegram 
cuando detecta señales fuertes con valor en cuota.
"""

import asyncio
import httpx
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

# ── Configuración ─────────────────────────────────────
SCAN_INTERVAL_SECONDS = 300      # Cada 5 minutos
MIN_ODDS = 1.50                  # Cuota mínima para alertar
MIN_MINUTE = 20                  # No alertar antes del minuto 20
MAX_MINUTE = 80                  # No alertar después del minuto 80
MIN_SIGNAL_STRENGTH = 5          # Puntos mínimos de señal
ALERT_COOLDOWN_MINUTES = 15      # No repetir alerta del mismo partido

SOFASCORE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.sofascore.com",
    "Accept": "application/json",
}

class LiveAlertEngine:

    def __init__(self, telegram_notifier, odds_scraper, news_scraper):
        self.telegram = telegram_notifier
        self.odds_scraper = odds_scraper
        self.news_scraper = news_scraper
        self.is_running = False
        self._task = None
        # Cooldown: event_id -> timestamp de última alerta
        self._sent_alerts: Dict[int, float] = {}
        # Señales previas para detectar cambios
        self._prev_signals: Dict[int, str] = {}

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._scan_loop())
        print("[LiveAlerts] Motor iniciado")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[LiveAlerts] Motor detenido")

    async def _scan_loop(self):
        while self.is_running:
            try:
                await self._scan_live_matches()
            except Exception as e:
                print(f"[LiveAlerts] Error en scan: {e}")
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    async def _scan_live_matches(self):
        """Obtiene partidos en vivo de SofaScore y analiza cada uno."""
        print(f"[LiveAlerts] Escaneando partidos en vivo... "
              f"{datetime.now().strftime('%H:%M:%S')}")
        
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            matches = await self.news_scraper.get_sofascore_schedule(today)
        except Exception as e:
            print(f"[LiveAlerts] Error obteniendo partidos: {e}")
            return

        if not matches:
            return

        # Filtrar solo partidos EN VIVO
        live_matches = [
            m for m in matches
            if str(m.get("status_type","")).lower() in 
               ("inprogress", "halftime")
        ]

        print(f"[LiveAlerts] {len(live_matches)} partidos en vivo")

        for match in live_matches:
            try:
                await self._analyze_match(match)
            except Exception as e:
                event_id = match.get("event_id") or match.get("id")
                print(f"[LiveAlerts] Error analizando {event_id}: {e}")

    async def _analyze_match(self, match: Dict):
        """Analiza un partido y decide si enviar alerta."""
        event_id = match.get("event_id") or match.get("id")
        if not event_id:
            return

        # Verificar cooldown
        now_ts = time.time()
        last_alert = self._sent_alerts.get(int(event_id), 0)
        if (now_ts - last_alert) < (ALERT_COOLDOWN_MINUTES * 60):
            return

        # Obtener datos completos del partido desde SofaScore
        match_data = await self._fetch_match_center(int(event_id))
        if not match_data:
            return

        event_summary = match_data.get("event_summary", {})
        statistics = match_data.get("statistics", [])
        graph = match_data.get("graph", [])

        # Obtener minuto actual
        minute = self._get_current_minute(match_data)
        if minute < MIN_MINUTE or minute > MAX_MINUTE:
            return

        # Analizar señal
        signal = self._compute_signal(
            statistics, graph, event_summary, minute
        )

        if not signal or signal["strength"] < MIN_SIGNAL_STRENGTH:
            return

        # Buscar cuota en LasPlatas
        home_name = event_summary.get("home_team",{}).get("name","")
        away_name = event_summary.get("away_team",{}).get("name","")

        odds_data = await self._fetch_lasplatas_odds(home_name, away_name)
        if not odds_data:
            return

        best_market, best_odds = self._find_best_market(
            signal, odds_data
        )

        if not best_market or best_odds < MIN_ODDS:
            return

        # Calcular stake sugerido con Kelly simplificado
        stake = self._kelly_stake(
            signal["probability"], best_odds
        )

        # Enviar alerta
        await self._send_alert(
            event_summary, signal, best_market, 
            best_odds, stake, minute
        )

        # Registrar cooldown
        self._sent_alerts[int(event_id)] = now_ts

    async def _fetch_match_center(self, event_id: int) -> Optional[Dict]:
        """Obtiene datos completos del partido de SofaScore."""
        try:
            async with httpx.AsyncClient(
                timeout=15.0, 
                headers=SOFASCORE_HEADERS
            ) as client:
                urls = [
                    f"https://api.sofascore.com/api/v1/event/{event_id}",
                    f"https://api.sofascore.com/api/v1/event/{event_id}/statistics",
                    f"https://api.sofascore.com/api/v1/event/{event_id}/graph",
                ]
                results = {}
                for url in urls:
                    try:
                        r = await client.get(url)
                        if r.status_code == 200:
                            results[url] = r.json()
                    except:
                        pass

            event_url   = f"https://api.sofascore.com/api/v1/event/{event_id}"
            stats_url   = f"https://api.sofascore.com/api/v1/event/{event_id}/statistics"
            graph_url   = f"https://api.sofascore.com/api/v1/event/{event_id}/graph"

            event_data  = results.get(event_url, {})
            stats_data  = results.get(stats_url, {})
            graph_data  = results.get(graph_url, {})

            event_obj = event_data.get("event", event_data)
            if not event_obj:
                return None

            home_team = event_obj.get("homeTeam", {})
            away_team = event_obj.get("awayTeam", {})
            home_score_obj = event_obj.get("homeScore", {})
            away_score_obj = event_obj.get("awayScore", {})

            return {
                "event_summary": {
                    "id": event_id,
                    "status_type": event_obj.get("status",{}).get("type",""),
                    "start_timestamp": event_obj.get("startTimestamp"),
                    "home_team": {
                        "id": home_team.get("id"),
                        "name": home_team.get("name",""),
                        "score": home_score_obj.get("current"),
                        "logo": f"https://api.sofascore.app/api/v1/team/"
                                f"{home_team.get('id')}/image",
                    },
                    "away_team": {
                        "id": away_team.get("id"),
                        "name": away_team.get("name",""),
                        "score": away_score_obj.get("current"),
                        "logo": f"https://api.sofascore.app/api/v1/team/"
                                f"{away_team.get('id')}/image",
                    },
                    "tournament": event_obj.get("tournament",{}).get("name",""),
                },
                "statistics": stats_data.get("statistics", []),
                "graph": graph_data.get("graphPoints", 
                         graph_data.get("points", [])),
            }
        except Exception as e:
            print(f"[LiveAlerts] Error fetch match center {event_id}: {e}")
            return None

    def _get_current_minute(self, match_data: Dict) -> int:
        """Estima el minuto actual del partido."""
        event_summary = match_data.get("event_summary", {})
        start_ts = event_summary.get("start_timestamp")
        if not start_ts:
            return 0
        elapsed = int(time.time()) - int(start_ts)
        minute = max(0, min(130, elapsed // 60))
        return minute

    def _get_stat(self, statistics: List, period: str, 
                  stat_name: str) -> Tuple[Optional[float], Optional[float]]:
        """Extrae un valor estadístico para un periodo dado."""
        period_map = {"ALL": "ALL", "1ST": "1ST", "2ND": "2ND"}
        target_period = period_map.get(period, period)

        for period_block in statistics:
            if not isinstance(period_block, dict):
                continue
            if period_block.get("period","").upper() != target_period:
                continue
            for group in period_block.get("groups", []):
                if not isinstance(group, dict):
                    continue
                for item in group.get("statisticsItems", []):
                    if not isinstance(item, dict):
                        continue
                    if item.get("name","").lower() == stat_name.lower():
                        try:
                            h = float(str(item.get("home","0"))
                                      .replace("%","").strip() or 0)
                            a = float(str(item.get("away","0"))
                                      .replace("%","").strip() or 0)
                            return h, a
                        except:
                            return None, None
        return None, None

    def _compute_signal(self, statistics: List, graph: List,
                        event_summary: Dict, 
                        minute: int) -> Optional[Dict]:
        """
        Analiza las estadísticas y el momentum para detectar 
        señales fuertes.
        Retorna dict con: team, market_hint, strength, probability
        """
        home_name = event_summary.get("home_team",{}).get("name","Local")
        away_name = event_summary.get("away_team",{}).get("name","Visitante")
        home_score = event_summary.get("home_team",{}).get("score", 0) or 0
        away_score = event_summary.get("away_team",{}).get("score", 0) or 0
        total_goals = home_score + away_score

        scores = {
            "home": 0,
            "away": 0,
            "over": 0,   # señal para over goles
        }
        reasons = []

        # ── xG ───────────────────────────────────────────────
        xg_h, xg_a = self._get_stat(statistics, "ALL", "Expected goals")
        if xg_h is not None and xg_a is not None:
            total_xg = xg_h + xg_a
            if xg_h > xg_a * 1.5:
                scores["home"] += 2
                reasons.append(f"xG domina local ({xg_h:.2f} vs {xg_a:.2f})")
            elif xg_a > xg_h * 1.5:
                scores["away"] += 2
                reasons.append(f"xG domina visitante ({xg_a:.2f} vs {xg_h:.2f})")
            
            if total_xg > 2.0:
                scores["over"] += 2
                reasons.append(f"xG total alto ({total_xg:.2f})")
            elif total_xg > 1.5:
                scores["over"] += 1

        # ── Tiros a puerta ────────────────────────────────────
        sot_h, sot_a = self._get_stat(statistics, "ALL", "Shots on target")
        if sot_h is not None and sot_a is not None:
            if sot_h > sot_a * 2:
                scores["home"] += 2
                reasons.append(f"Tiros a puerta local ({sot_h:.0f} vs {sot_a:.0f})")
            elif sot_a > sot_h * 2:
                scores["away"] += 2
                reasons.append(f"Tiros a puerta visitante ({sot_a:.0f} vs {sot_h:.0f})")
            
            total_sot = sot_h + sot_a
            if total_sot >= 8:
                scores["over"] += 1
                reasons.append(f"Muchos tiros a puerta ({total_sot:.0f} total)")

        # ── Grandes ocasiones ─────────────────────────────────
        bc_h, bc_a = self._get_stat(statistics, "ALL", "Big chances")
        if bc_h is not None and bc_a is not None:
            if bc_h > bc_a + 2:
                scores["home"] += 2
                reasons.append(f"Big chances local ({bc_h:.0f} vs {bc_a:.0f})")
            elif bc_a > bc_h + 2:
                scores["away"] += 2
                reasons.append(f"Big chances visitante ({bc_a:.0f} vs {bc_h:.0f})")
            
            if bc_h + bc_a >= 5:
                scores["over"] += 1

        # ── Posesión ──────────────────────────────────────────
        pos_h, pos_a = self._get_stat(statistics, "ALL", "Ball possession")
        if pos_h is not None and pos_a is not None:
            if pos_h > 65:
                scores["home"] += 1
                reasons.append(f"Posesión local dominante ({pos_h:.0f}%)")
            elif pos_a > 65:
                scores["away"] += 1
                reasons.append(f"Posesión visitante dominante ({pos_a:.0f}%)")

        # ── Momentum (grafico) ────────────────────────────────
        if graph:
            recent = [
                pt for pt in graph 
                if isinstance(pt, dict) and 
                (pt.get("minute") or pt.get("x") or 0) >= minute - 15
            ]
            if recent:
                home_pressure = sum(
                    pt.get("value", pt.get("y", 0)) 
                    for pt in recent 
                    if (pt.get("value", pt.get("y", 0)) or 0) > 0
                )
                away_pressure = abs(sum(
                    pt.get("value", pt.get("y", 0)) 
                    for pt in recent 
                    if (pt.get("value", pt.get("y", 0)) or 0) < 0
                ))
                
                if home_pressure > away_pressure * 2 and home_pressure > 50:
                    scores["home"] += 2
                    reasons.append("Momentum reciente: local presionando")
                elif away_pressure > home_pressure * 2 and away_pressure > 50:
                    scores["away"] += 2
                    reasons.append("Momentum reciente: visitante presionando")

        # ── 2do tiempo más activo ─────────────────────────────
        sot_h_2, sot_a_2 = self._get_stat(statistics, "2ND", 
                                            "Shots on target")
        if sot_h_2 is not None and sot_a_2 is not None:
            if sot_h_2 + sot_a_2 >= 4 and minute >= 45:
                scores["over"] += 1
                reasons.append(
                    f"2T activo en tiros ({sot_h_2+sot_a_2:.0f} SOT)"
                )

        # ── Determinar señal principal ────────────────────────
        best_team_signal = max(scores["home"], scores["away"])
        best_team = "home" if scores["home"] >= scores["away"] else "away"
        
        # Señal de equipo dominando
        if best_team_signal >= MIN_SIGNAL_STRENGTH:
            team_name = home_name if best_team == "home" else away_name
            opp_score = away_score if best_team == "home" else home_score
            team_score = home_score if best_team == "home" else away_score
            goal_diff = team_score - opp_score

            # Sugerir mercado según contexto
            if goal_diff < 0:
                # El equipo dominante va perdiendo → remontar
                market_hint = f"Gana {team_name}"
                prob = 0.45 + (best_team_signal * 0.03)
            elif goal_diff == 0:
                # Empate, equipo dominando → ganar o al menos no perder
                market_hint = f"Gana o Empata {team_name}"
                prob = 0.55 + (best_team_signal * 0.02)
            else:
                # Ya ganando, mantener ventaja
                market_hint = f"{team_name} -0.5 Handicap"
                prob = 0.65 + (best_team_signal * 0.02)

            return {
                "team": team_name,
                "side": best_team,
                "market_hint": market_hint,
                "strength": best_team_signal,
                "probability": min(0.92, prob),
                "reasons": reasons[:4],
                "scores": scores,
                "score_state": f"{home_score}-{away_score}",
                "minute": minute,
            }

        # Señal Over goles
        if scores["over"] >= MIN_SIGNAL_STRENGTH and total_goals >= 1:
            line = float(total_goals) + 0.5
            prob = 0.55 + (scores["over"] * 0.03)
            return {
                "team": "both",
                "side": "over",
                "market_hint": f"Over {line} Goles",
                "strength": scores["over"],
                "probability": min(0.88, prob),
                "reasons": reasons[:4],
                "scores": scores,
                "score_state": f"{home_score}-{away_score}",
                "minute": minute,
            }

        return None

    async def _fetch_lasplatas_odds(self, home_name: str, 
                                     away_name: str) -> Optional[Dict]:
        """Obtiene cuotas en vivo de LasPlatas para el partido."""
        try:
            from data.collectors.playwright_scraper import sync_get_match_odds
            loop = asyncio.get_event_loop()
            odds = await loop.run_in_executor(
                None, sync_get_match_odds, home_name, away_name
            )
            return odds if isinstance(odds, dict) else None
        except Exception as e:
            print(f"[LiveAlerts] Error obteniendo cuotas: {e}")
            return None

    def _find_best_market(self, signal: Dict, 
                           odds_data: Dict) -> Tuple[Optional[str], float]:
        """
        Busca en las cuotas de LasPlatas el mercado que mejor
        coincide con la señal detectada.
        Retorna (nombre_mercado, cuota).
        """
        if not odds_data:
            return None, 0.0

        market_hint = signal.get("market_hint","").lower()
        side = signal.get("side","")
        
        all_markets = odds_data.get("odds", {})
        if not isinstance(all_markets, dict):
            return None, 0.0

        best_name = None
        best_odds = 0.0

        for market_name, odds_value in all_markets.items():
            if not isinstance(odds_value, (int, float)):
                continue
            if odds_value < MIN_ODDS:
                continue

            market_lower = market_name.lower()
            score = 0

            # Coincidencia por tipo de señal
            if side == "over":
                if "over" in market_lower or "más de" in market_lower:
                    # Preferir la línea más cercana al marcador actual
                    score = 3
            elif side in ("home", "away"):
                if side == "home" and any(
                    k in market_lower for k in ["1 gana", "home", "local",
                                                 "1x", "1-x"]
                ):
                    score = 3
                elif side == "away" and any(
                    k in market_lower for k in ["2 gana", "away", "visitante",
                                                  "x2", "x-2"]
                ):
                    score = 3

            if score > 0 and odds_value > best_odds:
                best_odds = odds_value
                best_name = market_name

        # Si no encontramos nada específico, buscar cualquier 
        # mercado con cuota razonable
        if not best_name:
            for market_name, odds_value in all_markets.items():
                if isinstance(odds_value, (int,float)) and \
                   MIN_ODDS <= odds_value <= 3.5:
                    if odds_value > best_odds:
                        best_odds = odds_value
                        best_name = market_name

        return best_name, best_odds

    def _kelly_stake(self, probability: float, 
                      odds: float, 
                      fraction: float = 0.25) -> str:
        """
        Calcula stake sugerido con Kelly fraccionado.
        fraction=0.25 significa Kelly al 25% (conservador).
        """
        if odds <= 1 or probability <= 0:
            return "STAKE 1"
        
        # Kelly: (p * (b+1) - 1) / b  donde b = odds - 1
        b = odds - 1.0
        kelly = (probability * (b + 1) - 1) / b
        kelly_fractional = kelly * fraction
        kelly_fractional = max(0, min(kelly_fractional, 0.15))
        
        # Convertir a escala STAKE 1-10
        stake_num = round(kelly_fractional * 100 / 1.5)
        stake_num = max(1, min(10, stake_num))
        
        return f"STAKE {stake_num}"

    async def _send_alert(self, event_summary: Dict, signal: Dict,
                           market: str, odds: float, stake: str, 
                           minute: int):
        """Formatea y envía la alerta por Telegram."""
        home = event_summary.get("home_team",{})
        away = event_summary.get("away_team",{})
        home_name  = home.get("name","Local")
        away_name  = away.get("name","Visitante")
        tournament = event_summary.get("tournament","")
        score      = signal.get("score_state","?-?")
        prob_pct   = round(signal.get("probability",0) * 100, 1)
        strength   = signal.get("strength", 0)
        reasons    = signal.get("reasons", [])

        # Calcular value edge
        implied_prob = 1 / odds
        edge = round((signal.get("probability",0) - implied_prob) * 100, 1)
        
        edge_emoji = "⚡" if edge >= 20 else "🔥" if edge >= 10 else "✅"

        reasons_text = "\n".join([f"• {r}" for r in reasons]) \
                       if reasons else "• Análisis estadístico STUBET"

        message = (
            f"👑 <b>STUBET — ALERTA EN VIVO</b>\n\n"
            f"⚔️ <b>{home_name} vs {away_name}</b>\n"
            f"🏆 {tournament}\n"
            f"⏱️ Minuto {minute}' | Marcador: <b>{score}</b>\n\n"
            f"🎯 <b>Selección:</b> {signal.get('market_hint','')}\n"
            f"💎 <b>Mercado LP:</b> {market}\n"
            f"📊 <b>Cuota:</b> <code>{odds:.2f}</code>\n"
            f"📈 <b>Probabilidad:</b> {prob_pct}%\n"
            f"{edge_emoji} <b>Value Edge:</b> +{edge}%\n"
            f"🏦 <b>Stake:</b> {stake}\n\n"
            f"🧠 <b>Señales detectadas</b> "
            f"(fuerza: {strength}/10):\n"
            f"{reasons_text}\n\n"
            f"⚠️ <i>Verificar cuota antes de apostar. "
            f"Las cuotas en vivo fluctúan.</i>"
        )

        try:
            self.telegram.send_message(message)
            print(f"[LiveAlerts] Alerta enviada: "
                  f"{home_name} vs {away_name} | "
                  f"{market} @{odds}")
        except Exception as e:
            print(f"[LiveAlerts] Error enviando Telegram: {e}")

    def get_status(self) -> Dict:
        return {
            "running": self.is_running,
            "alerts_sent_today": len(self._sent_alerts),
            "scan_interval_minutes": SCAN_INTERVAL_SECONDS // 60,
            "min_odds": MIN_ODDS,
            "min_signal_strength": MIN_SIGNAL_STRENGTH,
        }
