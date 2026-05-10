import requests, json

r = requests.get('http://localhost:8080/api/sofascore/event/13260038/match-center', params={
    'history_limit': '10',
    'enrich_history_stats': 'true',
    'refresh_history_stats': 'true',
    'include_history_statistics': 'true',
    'force_fresh_history': 'true',
})

print(f"Status: {r.status_code}")
data = r.json()
print(f"Top keys: {list(data.keys())}")
print(f"Status field: {data.get('status')}")

# Write full response to debug file
with open("debug_response.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False, default=str)
print("Full response written to debug_response.json")

# Check sources
print(f"\nPayload sources: {data.get('sources')}")

history = data.get('history', {})
print(f"\nHistory keys: {list(history.keys())}")
for k, v in history.items():
    if isinstance(v, list):
        print(f"  {k}: {len(v)} items")
    else:
        print(f"  {k}: {type(v).__name__}")
