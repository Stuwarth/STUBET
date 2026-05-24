import re

def emoji_to_html(match):
    char = match.group(0)
    # Convert surrogate pairs or high-code points to HTML entities
    return f"&#{ord(char)};"

with open(r'c:\Users\stuwa\Desktop\SportsAI-Predictor\frontend\js\app.js', 'r', encoding='utf-8') as f:
    text = f.read()

# Emojis and other non-ascii high characters (roughly > 127)
# But we don't want to replace accented characters like á, é, í, ó, ú, ñ
# So let's target specific emoji blocks or just high unicode.
# Actually, the user just mentioned the emojis in buttons.
replacements = {
    "⚽": "&#9917;",
    "🔥": "&#128293;",
    "◀": "&#9664;",
    "▶": "&#9654;",
    "📅": "&#128197;",
    "📭": "&#128237;",
    "💰": "&#128176;",
    "📊": "&#128202;",
    "✅": "&#9989;",
    "❌": "&#10060;",
    "🔄": "&#128259;",
    "⚠️": "&#9888;",
    "💡": "&#128161;",
    "📈": "&#128200;",
    "📉": "&#128201;",
    "🏆": "&#127942;",
    "🎯": "&#127919;",
    "⚽️": "&#9917;&#65039;",
    "🤖": "&#129302;"
}

for emoji, html in replacements.items():
    text = text.replace(emoji, html)

# Also fix the weird "â" characters if they slipped in
text = text.replace('âš½', '&#9917;')

with open(r'c:\Users\stuwa\Desktop\SportsAI-Predictor\frontend\js\app.js', 'w', encoding='utf-8') as f:
    f.write(text)

print("Replaced emojis in app.js")
