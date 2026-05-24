"""
Sports AI Predictor — Main Entry Point
Run this to start the complete system.
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from api.server import start_server
from analysis.backfill_sync import run_backfill


def main():
    """Start the Sports AI Predictor."""
    print("""
    +----------------------------------------------------------+
    |                                                          |
    |     STUBET INTELLIGENCE v2.0                             |
    |     Advanced Statistical Betting Engine                  |
    |                                                          |
    |     API-Football: Online & Synchronized                  |
    |     Markets: O/U 2.5, BTTS, Corners, Team Props          |
    |     Advanced AI Value Prediction Engine                   |
    |     Telegram Alerts & Market Monitoring                   |
    |                                                          |
    +----------------------------------------------------------+
    """)
    
    # Run the backfill sync to catch up on any missed data while the system was off
    try:
        run_backfill()
    except Exception as e:
        print(f"[!] Aviso: Hubo un problema menor en la auto-actualizacion: {e}")
        print("Continuando con el inicio del servidor principal...")
    
    start_server()


if __name__ == "__main__":
    main()
