import requests

url = 'http://localhost:8080/api/live/scoreboard/sofascore_all'
try:
    r = requests.get(url, params={'date': '20260506'})
    data = r.json()
    matches = data.get('matches', [])
    found = False
    for m in matches:
        name = str(m.get('name'))
        if 'Bayern' in name or 'PSG' in name or 'Paris' in name:
            print(f"Found Match: ID={m.get('id')}, Name={name}, Date={m.get('date')}")
            found = True
    if not found:
        print(f"No Bayern/PSG match found among {len(matches)} matches.")
except Exception as e:
    print(f"Error: {e}")
