import sys

with open(r'c:\Users\stuwa\Desktop\SportsAI-Predictor\backend\api\deep_analyze.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if '@router.post("/api/analyze/match/pdf")' in line:
        break
    new_lines.append(line)

new_code = """@router.post("/api/analyze/match/pdf")
async def generate_pdf(request: Request):
    req = await request.json()
    data = req.get("data", {})
    home_name = req.get("home_name", "Local")
    away_name = req.get("away_name", "Visitante")
    
    from analysis.pdf_generator import generate_stats_pdf
    pdf_bytes = generate_stats_pdf(
        stubet_data=data,
        team_a_name=home_name,
        team_b_name=away_name,
    )
    
    safe_home = "".join(c if c.isalnum() else "_" for c in home_name)
    safe_away = "".join(c if c.isalnum() else "_" for c in away_name)
    filename = f"STUBET_{safe_home}_vs_{safe_away}.pdf"
    
    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
"""

with open(r'c:\Users\stuwa\Desktop\SportsAI-Predictor\backend\api\deep_analyze.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
    f.write(new_code)
