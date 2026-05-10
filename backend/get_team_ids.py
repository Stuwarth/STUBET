import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request(
    'https://api.sofascore.com/api/v1/search/teams?q=Real%20Madrid',
    headers={'User-Agent': 'Mozilla/5.0'}
)
with urllib.request.urlopen(req, context=ctx) as res:
    print("RM Team Search:")
    data = json.loads(res.read().decode())
    print(json.dumps(data['results'][0] if 'results' in data and data['results'] else data, indent=2))

req = urllib.request.Request(
    'https://api.sofascore.com/api/v1/search/teams?q=Espanyol',
    headers={'User-Agent': 'Mozilla/5.0'}
)
with urllib.request.urlopen(req, context=ctx) as res:
    print("\nESP Team Search:")
    data = json.loads(res.read().decode())
    print(json.dumps(data['results'][0] if 'results' in data and data['results'] else data, indent=2))
