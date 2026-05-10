"""
Telegram Bot — Sends automated notifications for:
- 🎯 High-confidence predictions
- 💎 Value bet opportunities (Premium/Strong/Normal)
- ⚠️ Breaking news affecting matches (injuries, suspensions)
- 📊 Daily performance reports
- 🔍 Pattern alerts when conditions are met
- ⚡ Live match alerts for in-play opportunities

Setup:
1. Create a bot via @BotFather on Telegram
2. Get your chat ID via @userinfobot
3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
"""
import httpx
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys

sys.path.append(str(Path(__file__).parent.parent))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_setting, is_configured


class TelegramNotifier:
    """
    Sends formatted betting alerts and reports via Telegram.
    """
    
    API_BASE = "https://api.telegram.org/bot{token}"
    
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.client = httpx.Client(timeout=10.0)
        self.notification_log = []
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.base_url = ""
        self.enabled = False
        self.reload_config()
    
    def reload_config(self):
        """Hot-reload credentials from .env so no server restart is needed"""
        self.bot_token = get_setting("TELEGRAM_BOT_TOKEN", self.bot_token or "")
        self.chat_id = get_setting("TELEGRAM_CHAT_ID", self.chat_id or "")
        self.base_url = self.API_BASE.format(token=self.bot_token or "")
        self.enabled = is_configured(self.bot_token) and is_configured(self.chat_id, ("your_chat_id",))

    def _log_notification(self, success: bool, kind: str, preview: str):
        self.notification_log.append({
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "type": kind,
            "preview": preview[:120],
        })
    
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured Telegram chat."""
        self.reload_config()
        if not self.enabled:
            print(f"[Telegram] Bot not configured. Message: {text[:100]}...")
            return False
        
        try:
            response = self.client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                }
            )
            
            result = response.json()
            success = result.get("ok", False)
            
            if not success:
                print(f"[Telegram] Error sending message: {result.get('description')}")
            
            self._log_notification(success, "message", text)
            
            return success
            
        except Exception as e:
            print(f"[Telegram] Exception sending message: {e}")
            self._log_notification(False, "message", text)
            return False

    def send_photo(self, photo_path: str, caption: str = "", parse_mode: str = "HTML") -> bool:
        """Sends a photo to the configured Telegram chat."""
        self.reload_config()
        if not self.enabled:
            print(f"[Telegram] Bot not configured. Photo: {photo_path}")
            return False
            
        try:
            with open(photo_path, "rb") as f:
                response = self.client.post(
                    f"{self.base_url}/sendPhoto",
                    data={
                        "chat_id": self.chat_id,
                        "caption": caption,
                        "parse_mode": parse_mode
                    },
                    files={"photo": f}
                )
            result = response.json()
            success = result.get("ok", False)
            if not success:
                print(f"[Telegram Error] Photo Failed: {result.get('description')}")
            self._log_notification(success, "photo", caption or photo_path)
            return success
        except Exception as e:
            print(f"[Telegram Exception] {e}")
            self._log_notification(False, "photo", caption or photo_path)
            return False

    def send_stubet_market_alert(self, alert: Dict, mode: str = "PRE-MATCH", image_path: Optional[str] = None) -> bool:
        """Send a market-aware STUBET alert generated from real lines and real stats."""
        selection = alert.get("selection", "Selección")
        market = alert.get("market", "Mercado")
        odds = alert.get("odds", 0)
        probability = alert.get("probability", 0) * 100
        edge = alert.get("edge", 0) * 100
        confidence = alert.get("confidence", "LOW")
        rationale = alert.get("rationale", "Sin justificación disponible.")
        event_name = alert.get("match", "Evento")
        
        # Format Stake 1-100 logically for Live and PreMatch
        raw_stake = alert.get("recommended_stake", 1)
        if raw_stake >= 50:
            stake_display = f"ALL IN 🔥 {raw_stake}/100"
            confidence = "MAXIMA"
        else:
            stake_display = f"{raw_stake}/10"

        message = (
            f"👑 <b>STUBET — SEÑAL [{mode} / MARKET-AWARE]</b>\n\n"
            f"⚔️ <b>Evento:</b> {event_name}\n"
            f"🎯 <b>Pick:</b> {selection}\n"
            f"📊 <b>Mercado:</b> {market}\n"
            f"💎 <b>Cuota LasPlatas:</b> {odds}\n"
            f"📈 <b>Probabilidad STUBET:</b> {probability:.1f}%\n"
            f"⚡ <b>Edge real:</b> {edge:+.1f}%\n"
            f"🔥 <b>Confianza:</b> {confidence}\n"
            f"🏦 <b>Stake Recomendado:</b> {stake_display}\n\n"
            f"🧠 <b>Justificación:</b> {rationale}\n"
        )

        if image_path and Path(image_path).exists():
            return self.send_photo(image_path, caption=message)
        return self.send_message(message)
    
    # ==================== PREDICTION ALERTS ====================
    
    def send_prediction_alert(self, prediction: Dict) -> bool:
        """Send a formatted prediction notification."""
        home = prediction.get("home_team_name", "Local")
        away = prediction.get("away_team_name", "Visitante")
        market = prediction.get("market", "")
        pred = prediction.get("prediction", "")
        prob = prediction.get("probability", 0)
        confidence = prediction.get("confidence", "LOW")
        
        # Only send HIGH or MEDIUM confidence
        if confidence == "LOW":
            return False
        
        emoji_map = {
            "match_result": "⚽", "over_under_25": "🎯", "btts": "🥅",
            "corners": "🔄", "cards": "🟨", "shots_on_target": "🎯",
        }
        emoji = emoji_map.get(market, "📊")
        conf_emoji = "🟢" if confidence == "HIGH" else "🟡"
        
        market_names = {
            "match_result": "Resultado 1X2", "over_under_25": "O/U 2.5 Goles",
            "btts": "Ambos Marcan", "corners": "Corners",
            "cards": "Tarjetas", "shots_on_target": "Remates al Arco",
        }
        market_name = market_names.get(market, market)
        
        message = f"""
{emoji} <b>PREDICCIÓN IA</b> {conf_emoji}

⚽ <b>{home}</b> vs <b>{away}</b>
📊 Mercado: {market_name}
🎯 Predicción: <b>{pred}</b>
📈 Probabilidad: <b>{prob*100:.1f}%</b>
{conf_emoji} Confianza: <b>{confidence}</b>

🤖 <i>Sports AI Predictor v1.0</i>
⏰ {datetime.now().strftime("%d/%m/%Y %H:%M")}
"""
        return self.send_message(message.strip())
    
    # ==================== VALUE BET ALERTS ====================
    
    def send_value_bet_alert(self, value_bet: Dict) -> bool:
        """Send a high-priority value bet notification."""
        home = value_bet.get("home_team_name", "Local")
        away = value_bet.get("away_team_name", "Visitante")
        market = value_bet.get("market", "")
        pred = value_bet.get("prediction", "")
        prob = value_bet.get("probability", 0)
        edge = value_bet.get("value_edge", 0)
        stake = value_bet.get("recommended_stake", 0)
        
        # Tier classification
        edge_pct = edge * 100
        
        # New STAKE formatting 1-100
        if stake >= 50:
            stake_display = f"ALL IN 🔥 {stake}/100"
            tier = "⚡ PREMIUM"
            tier_desc = "Value bet de MUY ALTA CONFIANZA"
        elif edge_pct >= 15:
            stake_display = f"{stake}/10"
            tier = "⚡ PREMIUM"
            tier_desc = "Value bet de máxima calidad"
        elif edge_pct >= 10:
            stake_display = f"{stake}/10"
            tier = "🔥 FUERTE"
            tier_desc = "Value bet con ventaja significativa"
        else:
            stake_display = f"{stake}/10"
            tier = "✅ VALUE"
            tier_desc = "Value bet positivo detectado"

        message = f"""
👑 <b>STUBET — LECTURA DE PARTIDO [LIVE STATS]</b> 👑

{tier}
{tier_desc}

⚽ <b>{home}</b> vs <b>{away}</b>
📊 Mercado: {market}
🎯 Predicción: <b>{pred}</b>

📈 Prob. Modelo: <b>{prob*100:.1f}%</b>
💰 Value Edge: <b>+{edge_pct:.1f}%</b>
🏦 Stake Recomendado: <b>{stake_display}</b>
🤖 <i>Sports AI Predictor v1.0</i>
⏰ {datetime.now().strftime("%d/%m/%Y %H:%M")}
"""
        return self.send_message(message.strip())
    
    # ==================== PATTERN ALERTS ====================
    
    def send_pattern_alert(self, pattern: Dict, match: Dict) -> bool:
        """Send alert when a validated pattern is triggered for an upcoming match."""
        message = f"""
🔍 <b>PATRÓN DETECTADO</b>

📋 Patrón: <b>{pattern.get('name', 'N/A')}</b>
📝 {pattern.get('description', '')}

⚽ Partido: <b>{match.get('home', 'Local')} vs {match.get('away', 'Visitante')}</b>

📊 Estadísticas del patrón:
├ Hit Rate: <b>{pattern.get('hit_rate', 0)*100:.0f}%</b>
├ Confianza: <b>{pattern.get('confidence', 0)*100:.0f}%</b>
├ Muestra: <b>{pattern.get('sample_size', 0)} partidos</b>
└ Precisión en vivo: <b>{pattern.get('live_accuracy', 0)*100:.0f}%</b>

🎯 Predicción: <b>{pattern.get('prediction', {}).get('expected', 'N/A')}</b>
📊 Mercado: {pattern.get('prediction', {}).get('market', 'N/A')}

🤖 <i>Sports AI Predictor — Pattern Engine</i>
"""
        return self.send_message(message.strip())
    
    # ==================== INJURY ALERTS ====================
    
    def send_injury_alert(self, team: str, injuries: List[Dict]) -> bool:
        """Send alert about important injuries affecting upcoming matches."""
        if not injuries:
            return False
        
        injury_lines = []
        for inj in injuries[:8]:  # Max 8 injuries
            status_emoji = "🔴" if inj.get("status") == "Out" else "🟡"
            injury_lines.append(
                f"  {status_emoji} <b>{inj.get('player', 'Desconocido')}</b> ({inj.get('position', '?')})"
                f"\n    └ {inj.get('injury_type', 'Lesión')}"
            )
        
        injuries_text = "\n".join(injury_lines)
        
        message = f"""
⚠️ <b>ALERTA DE LESIONES</b>

🏥 Equipo: <b>{team}</b>
👥 Jugadores afectados: <b>{len(injuries)}</b>

{injuries_text}

💡 <i>Las lesiones pueden afectar significativamente las cuotas. 
Verifica si las casas de apuestas ya ajustaron.</i>

🤖 <i>Sports AI Predictor — News Scout</i>
⏰ {datetime.now().strftime("%d/%m/%Y %H:%M")}
"""
        return self.send_message(message.strip())
    
    # ==================== DAILY REPORT ====================
    
    def send_daily_report(self, stats: Dict) -> bool:
        """Send a daily performance and opportunity report."""
        overview = stats.get("overview", {})
        roi = stats.get("roi", {})
        by_market = stats.get("by_market", [])
        
        market_lines = []
        for m in by_market:
            market_names = {
                "match_result": "1X2", "over_under_25": "O/U 2.5", "btts": "BTTS",
                "corners": "Corners", "cards": "Cards",
            }
            name = market_names.get(m.get("market", ""), m.get("market", ""))
            acc = m.get("accuracy", 0)
            acc_emoji = "🟢" if acc >= 60 else ("🟡" if acc >= 50 else "🔴")
            market_lines.append(f"  {acc_emoji} {name}: <b>{acc}%</b> ({m.get('wins', 0)}W/{m.get('losses', 0)}L)")
        
        markets_text = "\n".join(market_lines) if market_lines else "  Sin datos"
        
        profit = roi.get("profit", 0)
        profit_emoji = "📈" if profit >= 0 else "📉"
        
        message = f"""
📊 <b>REPORTE DIARIO</b>
📅 {datetime.now().strftime("%d/%m/%Y")}

━━━━━━━━━━━━━━━━━━

🎯 <b>Rendimiento General</b>
├ Total Predicciones: <b>{overview.get('total', 0)}</b>
├ Acertadas: <b>{overview.get('correct', 0)}</b>
├ Precisión: <b>{overview.get('accuracy', 0)}%</b>
└ Value Bets: <b>{overview.get('value_bets', 0)}</b>

💰 <b>Financiero</b>
├ {profit_emoji} P/L: <b>${profit:.2f}</b>
├ ROI: <b>{roi.get('roi', 0)}%</b>
└ Bankroll: <b>${roi.get('bankroll', 1000):.2f}</b>

📊 <b>Por Mercado</b>
{markets_text}

━━━━━━━━━━━━━━━━━━
🤖 <i>Sports AI Predictor v1.0</i>
"""
        return self.send_message(message.strip())
    
    # ==================== ADVANCED MARKET ALERTS ====================
    
    def send_stats_prediction_alert(self, match: Dict, predictions: Dict) -> bool:
        """Send detailed statistical market predictions."""
        home = match.get("home_team", "Local")
        away = match.get("away_team", "Visitante")
        
        corners = predictions.get("corners", {})
        shots = predictions.get("shots", {})
        cards = predictions.get("cards", {})
        saves = predictions.get("goalkeeper_saves", {})
        
        message = f"""
📊 <b>PREDICCIÓN ESTADÍSTICA COMPLETA</b>

⚽ <b>{home}</b> vs <b>{away}</b>

🔄 <b>CORNERS</b>
├ Total pred.: <b>{corners.get('total_corners_predicted', '?')}</b>
├ {home}: <b>{corners.get('home_corners_predicted', '?')}</b>
└ {away}: <b>{corners.get('away_corners_predicted', '?')}</b>

🎯 <b>REMATES AL ARCO</b>
├ Total pred.: <b>{shots.get('total_shots_on_target_predicted', '?')}</b>
├ {home}: <b>{shots.get('home_shots_on_target_predicted', '?')}</b>
└ {away}: <b>{shots.get('away_shots_on_target_predicted', '?')}</b>

🟨 <b>TARJETAS AMARILLAS</b>
├ Total pred.: <b>{cards.get('total_yellow_cards_predicted', '?')}</b>
├ {home}: <b>{cards.get('home_yellow_cards_predicted', '?')}</b>
└ {away}: <b>{cards.get('away_yellow_cards_predicted', '?')}</b>

🧤 <b>ATAJADAS</b>
├ Total pred.: <b>{saves.get('total_saves_predicted', '?')}</b>
├ GK {home}: <b>{saves.get('home_saves_predicted', '?')}</b>
└ GK {away}: <b>{saves.get('away_saves_predicted', '?')}</b>

🤖 <i>Sports AI Predictor — Advanced Stats Engine</i>
⏰ {datetime.now().strftime("%d/%m/%Y %H:%M")}
"""
        return self.send_message(message.strip())
    
    def get_status(self) -> Dict:
        """Get notifier status and recent history."""
        self.reload_config()
        return {
            "enabled": self.enabled,
            "bot_configured": bool(self.bot_token and self.bot_token != "your_telegram_bot_token"),
            "chat_configured": bool(self.chat_id and self.chat_id != "your_chat_id"),
            "recent_notifications": self.notification_log[-10:],
            "total_sent": len([n for n in self.notification_log if n.get("success")]),
        }
    
    def test_connection(self) -> Dict:
        """Test the Telegram connection."""
        self.reload_config()
        if not self.enabled:
            return {"success": False, "error": "Bot not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"}
        
        success = self.send_message(
            "🤖 <b>Sports AI Predictor</b>\n\n"
            "✅ Conexión exitosa! Las notificaciones están activas.\n\n"
            "Recibirás alertas de:\n"
            "├ 🎯 Predicciones de alta confianza\n"
            "├ 💎 Value bets detectados\n"
            "├ 🔍 Patrones estadísticos\n"
            "├ ⚠️ Lesiones importantes\n"
            "└ 📊 Reportes diarios"
        )
        
        return {
            "success": success,
            "message": "Connection successful!" if success else "Connection failed"
        }
    
    def close(self):
        """Close HTTP client."""
        self.client.close()
