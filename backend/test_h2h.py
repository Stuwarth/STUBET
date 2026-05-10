import requests

url = 'https://api.sofascore.app/api/v1/event/15632634/h2h/events'
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
print('Status:', r.status_code)
if r.status_code == 200:
    data = r.json()
    events = data.get('events', [])
    print(f'Found {len(events)} H2H events.')
    for e in events[:3]:
        print(f"  {e.get('homeTeam', {}).get('name')} vs {e.get('awayTeam', {}).get('name')}")
else:
    print('Error:', r.text)
