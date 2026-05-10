import re

with open('metabet.html', 'r', encoding='utf-8') as f:
    html = f.read()

print('Searching for bet data...')
if "eventName" in html: print("eventName found")
if "odds" in html: print("odds found")

# look for script containing state
scripts = re.findall(r'<script.*?>.*?</script>', html, re.DOTALL)
for s in scripts:
    if 'bet' in s.lower() or '20280133' in s:
        print("Found 20280133 in script:", s[:200])
