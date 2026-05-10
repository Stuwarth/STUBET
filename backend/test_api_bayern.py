import requests
import json

url = 'http://localhost:8080/api/sofascore/event/15632634/match-center'
r = requests.get(url, params={
    'history_limit': '10',
    'enrich_history_stats': 'true',
    'refresh_history_stats': 'true',
    'include_history_statistics': 'true',
    'force_fresh_history': 'true',
})

print(f"Status: {r.status_code}")
data = r.json()

history = data.get('history', {})
print(f"History keys: {list(history.keys())}")
for k, v in history.items():
    if isinstance(v, list):
        print(f"  {k}: {len(v)} items")
        for match in v[:3]:
            print(f"    - {match.get('match_date')} | {match.get('home_team_name')} {match.get('home_score')}-{match.get('away_score')} {match.get('away_team_name')} ({match.get('league_name')})")

ai = data.get('ai_context', {})
print(f"\nAI Context:")
print(f"Enabled: {ai.get('enabled')}")
home_ctx = ai.get('home_last10', {})
print(f"Home stats available: {home_ctx.get('stats_available_count')} / {home_ctx.get('sample_count')}")

h2h_ctx = ai.get('h2h', {})
print(f"H2H stats available: {h2h_ctx.get('stats_available_count')} / {h2h_ctx.get('sample_count')}")
