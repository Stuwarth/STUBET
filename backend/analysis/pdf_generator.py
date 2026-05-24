"""
STUBET — pdf_generator.py
==========================
Módulo de generación de PDF profesional para estadísticas de partidos.
"""

import re
import io
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ═══════════════════════════════════════════════════════════════
# COLORES Y ESTILOS
# ═══════════════════════════════════════════════════════════════
C_TEAM_A   = colors.HexColor('#003087')   # Azul oscuro — equipo local (hoy)
C_TEAM_B   = colors.HexColor('#0057A8')   # Azul medio  — equipo visitante (hoy)
C_H2H      = colors.HexColor('#8B6914')   # Dorado — H2H
C_YELLOW   = colors.HexColor('#fffbcc')   # Amarillo claro — columna equipo analizado
C_WIN      = colors.HexColor('#e6f4ea')   # Verde claro — victoria
C_LOSE     = colors.HexColor('#fde8e8')   # Rojo claro  — derrota
C_DRAW     = colors.HexColor('#f0f0f0')   # Gris claro  — empate
C_CAT_BG   = colors.HexColor('#e8f0fe')   # Azul muy claro — fila categoría
C_LGRAY    = colors.HexColor('#f5f5f5')   # Gris claro — filas alternas
C_DGRAY    = colors.HexColor('#2c2c2c')   # Texto oscuro
WHITE      = colors.white

def _ps(name, **kw):
    return ParagraphStyle(name, **kw)

TITLE_S  = _ps('T',  fontSize=18, textColor=WHITE, fontName='Helvetica-Bold',
                leading=24, alignment=TA_CENTER)
HEAD_S   = _ps('H',  fontSize=11, textColor=WHITE, fontName='Helvetica-Bold',
                leading=15, alignment=TA_CENTER)
SUB_S    = _ps('S',  fontSize=9,  textColor=C_DGRAY, fontName='Helvetica-Bold', leading=12)
BODY_S   = _ps('B',  fontSize=8,  textColor=C_DGRAY, fontName='Helvetica',      leading=10)
BOLD_S   = _ps('Bd', fontSize=8,  textColor=C_DGRAY, fontName='Helvetica-Bold', leading=10)
SMALL_S  = _ps('Sm', fontSize=7,  textColor=colors.HexColor('#555'), fontName='Helvetica', leading=9)
NOTE_S   = _ps('N',  fontSize=7,  textColor=C_TEAM_A, fontName='Helvetica-BoldOblique', leading=9)


# ═══════════════════════════════════════════════════════════════
# ADAPTADOR PARA STUBET FORMAT
# ═══════════════════════════════════════════════════════════════

def stubet_to_new_format(stubet_data: dict, home_name: str, away_name: str) -> dict:
    result = {
        home_name: [],
        away_name: [],
        'H2H': [],
        '_team_a': home_name,
        '_team_b': away_name
    }
    
    def convert_matches(matches_list):
        out = []
        for m in matches_list:
            info = m.get("match_info", {})
            date = info.get("date", "")
            comp = info.get("competition", "")
            h = info.get("home", "?")
            a = info.get("away", "?")
            hs = info.get("home_score", "?")
            as_ = info.get("away_score", "?")
            name = f"{h} {hs}-{as_} {a}"
            
            periods_out = {}
            for p in m.get("statistics", []):
                p_name = p.get("period", "ALL")
                periods_out[p_name] = {}
                for g in p.get("groups", []):
                    g_name = g.get("groupName", "Stats")
                    periods_out[p_name][g_name] = []
                    for s in g.get("statisticsItems", []):
                        periods_out[p_name][g_name].append({
                            'stat': s.get("name", ""),
                            'left': str(s.get("home", "")),
                            'right': str(s.get("away", ""))
                        })
            
            out.append({
                'date': date,
                'competition': comp,
                'name': name,
                'periods': periods_out
            })
        return out

    result[home_name] = convert_matches(stubet_data.get('home_last10', []))
    result[away_name] = convert_matches(stubet_data.get('away_last10', []))
    result['H2H'] = convert_matches(stubet_data.get('h2h', []))
    
    return result


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _extract_teams(match_name: str):
    """'FC Barcelona 2-0 Real Madrid' → ('FC Barcelona', 'Real Madrid', 2, 0)"""
    m = re.match(r'^(.+?)\s+(\d+)-(\d+)\s+(.+)$', match_name)
    if m:
        return m.group(1).strip(), m.group(4).strip(), int(m.group(2)), int(m.group(3))
    return match_name, '', 0, 0

def _num(raw: str) -> Optional[float]:
    """Extrae el primer número de un string."""
    m = re.search(r'[\d.]+', raw.replace(',', ''))
    return float(m.group()) if m else None

def _result_color(focus_team: str, home: str, away: str, sh: int, sa: int):
    """Color de resultado para el equipo analizado."""
    if focus_team == home:
        if sh > sa: return C_WIN
        if sh < sa: return C_LOSE
        return C_DRAW
    else:
        if sa > sh: return C_WIN
        if sa < sh: return C_LOSE
        return C_DRAW

def _result_emoji(focus_team: str, home: str, away: str, sh: int, sa: int) -> str:
    if focus_team == home:
        if sh > sa: return 'V'
        if sh < sa: return 'D'
        return 'E'
    else:
        if sa > sh: return 'V'
        if sa < sh: return 'D'
        return 'E'

def _localidad(focus_team: str, home: str) -> str:
    return 'L (Local)' if focus_team == home else 'V (Visitante)'


# ═══════════════════════════════════════════════════════════════
# TABLA DE RESUMEN ESTADÍSTICO (media casa/fuera/general)
# ═══════════════════════════════════════════════════════════════

KEY_STATS = [
    ('Match overview', 'Total shots',    'Remates totales'),
    ('Shots',          'Shots on target','Remates a puerta'),
    ('Match overview', 'Corner kicks',   'Córners a favor'),
    ('Match overview', 'Yellow cards',   'Tarjetas amarillas PROPIAS'),
    ('Match overview', 'Fouls',          'Faltas cometidas'),
    ('Match overview', 'Expected goals', 'xG'),
    ('Match overview', 'Big chances',    'Grandes ocasiones'),
    ('Match overview', 'Ball possession','Posesión (%)'),
    ('Goalkeeping',    'Total saves',    'Paradas del portero'),
]

def _get_stat_val(match: dict, period: str, cat: str, stat: str, focus: str) -> Optional[float]:
    home, _, _, _ = _extract_teams(match['name'])
    is_left = (focus == home)
    for s in match.get('periods', {}).get(period, {}).get(cat, []):
        if s['stat'] == stat:
            return _num(s['left'] if is_left else s['right'])
    return None

def build_summary_table(matches: list, focus_team: str, accent: colors.Color) -> Optional[Table]:
    """Tabla resumen con media general, casa, fuera, mín, máx, último."""
    rows = [['ESTADÍSTICA', 'MEDIA', 'CASA', 'FUERA', 'MÍN', 'MÁX', 'ÚLTIMO']]

    for cat, stat, label in KEY_STATS:
        home_vals, away_vals = [], []
        for m in matches[:10]:
            home, _, _, _ = _extract_teams(m['name'])
            is_home = (focus_team == home)
            v = _get_stat_val(m, 'ALL', cat, stat, focus_team)
            if v is not None:
                (home_vals if is_home else away_vals).append(v)

        all_vals = home_vals + away_vals
        if not all_vals:
            continue

        avg     = sum(all_vals) / len(all_vals)
        avg_h   = sum(home_vals) / len(home_vals) if home_vals else '—'
        avg_a   = sum(away_vals) / len(away_vals) if away_vals else '—'
        mn      = min(all_vals)
        mx      = max(all_vals)
        last    = all_vals[0]

        def fmt(v): return f'{v:.1f}' if isinstance(v, float) else v
        rows.append([label, fmt(avg), fmt(avg_h), fmt(avg_a), fmt(mn), fmt(mx), fmt(last)])

    if len(rows) <= 1:
        return None

    COL_W = [5.5*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.5*cm, 1.5*cm, 1.8*cm]
    ts = [
        ('BACKGROUND',  (0, 0), (-1, 0),  accent),
        ('TEXTCOLOR',   (0, 0), (-1, 0),  WHITE),
        ('FONTNAME',    (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, -1), 7.5),
        ('ALIGN',       (0, 0), (0, -1),  'LEFT'),
        ('ALIGN',       (1, 0), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, C_LGRAY]),
        ('GRID',        (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('TOPPADDING',  (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0,0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        # Destacar columna MEDIA
        ('BACKGROUND',  (1, 1), (1, -1),  C_YELLOW),
        ('FONTNAME',    (1, 1), (1, -1),  'Helvetica-Bold'),
    ]
    tbl = Table(rows, colWidths=COL_W)
    tbl.setStyle(TableStyle(ts))
    return tbl


# ═══════════════════════════════════════════════════════════════
# TABLA DE ESTADÍSTICAS POR PERÍODO
# ═══════════════════════════════════════════════════════════════

CAT_ORDER = [
    ('Match overview', 'VISION GENERAL'),
    ('Shots',          'REMATES'),
    ('Attack',         'ATAQUE'),
    ('Passes',         'PASES'),
    ('Defending',      'DEFENSA'),
    ('Duels',          'DUELOS'),
    ('Goalkeeping',    'PORTERIA'),
]

def build_period_table(period_data: dict, home_team: str, away_team: str,
                       focus_team: str, accent: colors.Color) -> Optional[Table]:
    """Tabla de stats para un período, con columna del equipo analizado en amarillo."""
    focus_col = 1 if focus_team == home_team else 2

    # Acortar nombres largos
    def short(n): return n if len(n) <= 16 else n[:14] + '..'

    rows = [['ESTADÍSTICA', short(home_team), short(away_team)]]

    for cat_key, cat_label in CAT_ORDER:
        stats = period_data.get(cat_key, [])
        if not stats:
            continue
        rows.append([cat_label, '', ''])  # fila separadora de categoría
        for s in stats:
            rows.append([s['stat'], s['left'], s['right']])

    if len(rows) <= 1:
        return None

    ts = [
        # Cabecera
        ('BACKGROUND',  (0, 0), (-1, 0),  accent),
        ('TEXTCOLOR',   (0, 0), (-1, 0),  WHITE),
        ('FONTNAME',    (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, -1), 7.5),
        ('ALIGN',       (0, 0), (0, -1),  'LEFT'),
        ('ALIGN',       (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),  [WHITE, C_LGRAY]),
        ('GRID',        (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('TOPPADDING',  (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING',(0,0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
    ]

    for i, row in enumerate(rows):
        if i == 0:
            continue
        # Separador de categoría
        if row[1] == '' and row[2] == '':
            ts.append(('BACKGROUND', (0, i), (-1, i), C_CAT_BG))
            ts.append(('FONTNAME',   (0, i), (-1, i), 'Helvetica-BoldOblique'))
            ts.append(('TEXTCOLOR',  (0, i), (-1, i), accent))
            ts.append(('SPAN',       (0, i), (-1, i)))
        else:
            # Resaltar columna del equipo analizado
            ts.append(('BACKGROUND', (focus_col, i), (focus_col, i), C_YELLOW))
            ts.append(('FONTNAME',   (focus_col, i), (focus_col, i), 'Helvetica-Bold'))

    COL_W = [7*cm, 3.5*cm, 3.5*cm]
    tbl = Table(rows, colWidths=COL_W)
    tbl.setStyle(TableStyle(ts))
    return tbl


# ═══════════════════════════════════════════════════════════════
# FICHA DE UN PARTIDO
# ═══════════════════════════════════════════════════════════════

def build_match_card(match: dict, focus_team: str, accent: colors.Color) -> list:
    """Construye la ficha completa de un partido (cabecera + tablas de períodos)."""
    home, away, sh, sa = _extract_teams(match['name'])
    rc   = _result_color(focus_team, home, away, sh, sa)
    res  = _result_emoji(focus_team, home, away, sh, sa)
    loc  = _localidad(focus_team, home)
    elems = []

    # ── Cabecera del partido ──────────────────────────────────────────────────
    hdr_data = [[
        Paragraph(f'<b>{match["date"]}</b><br/>'
                  f'<font size="6" color="gray">{match["competition"]}</font>', BODY_S),
        Paragraph(f'<b><font size="11">{home}</font></b>',
                  _ps('hn', fontSize=10, fontName='Helvetica-Bold', alignment=TA_RIGHT)),
        Paragraph(f'<b><font size="14">{sh} - {sa}</font></b>',
                  _ps('sc', fontSize=13, fontName='Helvetica-Bold', alignment=TA_CENTER)),
        Paragraph(f'<b><font size="11">{away}</font></b>',
                  _ps('an', fontSize=10, fontName='Helvetica-Bold', alignment=TA_LEFT)),
        Paragraph(f'<b>{res}</b><br/><font size="6">{loc}</font>',
                  _ps('rl', fontSize=7.5, fontName='Helvetica-Bold',
                      alignment=TA_CENTER, textColor=accent)),
    ]]
    hdr_tbl = Table(hdr_data, colWidths=[3.5*cm, 4.5*cm, 2*cm, 4.5*cm, 2.5*cm])
    hdr_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), rc),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',          (0, 0), (-1, -1), 0.5, colors.HexColor('#aaaaaa')),
        ('LINEBELOW',     (0, 0), (-1, -1), 2, accent),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
    ]))
    elems.append(hdr_tbl)

    # Nota de columna resaltada
    focus_side = 'IZQUIERDA' if focus_team == home else 'DERECHA'
    elems.append(Paragraph(
        f'Columna amarilla = {focus_team} | columna {focus_side}',
        _ps('fn', fontSize=6.5, textColor=accent, fontName='Helvetica-BoldOblique', leading=8)
    ))
    elems.append(Spacer(1, 2*mm))

    # ── Tablas por período ────────────────────────────────────────────────────
    PERIOD_LABELS = {'ALL': 'PARTIDO COMPLETO', '1ST': '1a MITAD', '2ND': '2a MITAD'}
    for period, label in PERIOD_LABELS.items():
        pd = match.get('periods', {}).get(period)
        if not pd:
            continue
        elems.append(Paragraph(label, _ps(f'pl{period}',
            fontSize=8, fontName='Helvetica-Bold', textColor=accent, leading=11)))
        tbl = build_period_table(pd, home, away, focus_team, accent)
        if tbl:
            elems.append(tbl)
        elems.append(Spacer(1, 2*mm))

    elems.append(Spacer(1, 3*mm))
    elems.append(HRFlowable(width='100%', thickness=0.8, color=colors.HexColor('#dddddd')))
    elems.append(Spacer(1, 3*mm))
    return elems


# ═══════════════════════════════════════════════════════════════
# SECCIÓN COMPLETA DE UN EQUIPO
# ═══════════════════════════════════════════════════════════════

def build_team_section(matches: list, focus_team: str, section_num: int,
                       accent: colors.Color, story: list):
    """Añade al story la sección completa de un equipo."""
    # Cabecera de sección
    sec_tbl = Table([[Paragraph(
        f'{section_num}. {focus_team.upper()} - ULTIMOS {len(matches)} PARTIDOS', HEAD_S
    )]], colWidths=[17*cm])
    sec_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), accent),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(KeepTogether([sec_tbl]))
    story.append(Spacer(1, 4*mm))

    # Resumen estadístico
    story.append(Paragraph('RESUMEN ESTADISTICO - CON SEPARACION LOCAL / VISITANTE', SUB_S))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        'MEDIA = promedio general | CASA = promedio jugando de local | '
        'FUERA = promedio jugando de visitante',
        _ps('leg', fontSize=6.5, textColor=colors.HexColor('#555'),
            fontName='Helvetica-Oblique', leading=9)
    ))
    story.append(Spacer(1, 2*mm))
    sum_tbl = build_summary_table(matches, focus_team, accent)
    if sum_tbl:
        story.append(sum_tbl)
    story.append(Spacer(1, 5*mm))

    # Detalle por partido
    story.append(Paragraph('DETALLE PARTIDO POR PARTIDO', SUB_S))
    story.append(Spacer(1, 3*mm))

    for match in matches:
        card = build_match_card(match, focus_team, accent)
        story.append(KeepTogether(card[:3]))  # cabecera + primeras tablas juntas
        for elem in card[3:]:
            story.append(elem)

    story.append(PageBreak())


# ═══════════════════════════════════════════════════════════════
# SECCIÓN H2H
# ═══════════════════════════════════════════════════════════════

def build_h2h_section(matches: list, team_a: str, story: list):
    """Añade la sección H2H al story."""
    sec_tbl = Table([[Paragraph(
        f'3. HISTORIAL H2H - ENFRENTAMIENTOS DIRECTOS', HEAD_S
    )]], colWidths=[17*cm])
    sec_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_H2H),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(KeepTogether([sec_tbl]))
    story.append(Spacer(1, 4*mm))

    # Tabla resumen de resultados
    rows = [['FECHA', 'PARTIDO', f'RESULTADO ({team_a})', 'LOCALIA']]
    wins = draws = losses = 0
    for m in matches:
        home, away, sh, sa = _extract_teams(m['name'])
        res  = _result_emoji(team_a, home, away, sh, sa)
        loc  = _localidad(team_a, home)
        rows.append([m['date'], m['name'], res, loc])
        if 'V' in res: wins   += 1
        elif 'E'  in res: draws  += 1
        else:                  losses += 1

    h2h_tbl = Table(rows, colWidths=[2.5*cm, 8*cm, 4*cm, 2.5*cm])
    h2h_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), C_H2H),
        ('TEXTCOLOR',     (0, 0), (-1, 0), WHITE),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1,-1), 8),
        ('ALIGN',         (0, 0), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS',(0, 1), (-1,-1), [WHITE, colors.HexColor('#fff8dc')]),
        ('GRID',          (0, 0), (-1,-1), 0.3, colors.HexColor('#cccccc')),
        ('TOPPADDING',    (0, 0), (-1,-1), 4),
        ('BOTTOMPADDING', (0, 0), (-1,-1), 4),
    ]))
    story.append(h2h_tbl)
    story.append(Spacer(1, 3*mm))

    # Totales
    story.append(Paragraph(
        f'Victorias de {team_a}: <b>{wins}</b> | '
        f'Empates: <b>{draws}</b> | '
        f'Derrotas de {team_a}: <b>{losses}</b>',
        _ps('tot', fontSize=9, fontName='Helvetica-Bold', textColor=C_H2H, leading=12)
    ))
    story.append(Spacer(1, 5*mm))

    # Detalle estadístico solo de partidos recientes con datos completos
    modern = [m for m in matches if int(m['date'][:4]) >= 2020 and m.get('periods')]
    if modern:
        story.append(Paragraph('DETALLE ESTADISTICO (PARTIDOS RECIENTES)', SUB_S))
        story.append(Spacer(1, 3*mm))
        for match in modern:
            card = build_match_card(match, team_a, C_H2H)
            story.append(KeepTogether(card[:3]))
            for elem in card[3:]:
                story.append(elem)


# ═══════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL — GENERA EL PDF
# ═══════════════════════════════════════════════════════════════

def generate_stats_pdf(
    stubet_data: dict,
    team_a_name: str,
    team_b_name: str,
    match_date: str = None,
    output_path: str = None,
) -> bytes:
    # Transformar a formato esperado por el layout
    data = stubet_to_new_format(stubet_data, team_a_name, team_b_name)

    team_a = team_a_name
    team_b = team_b_name
    matches_a = data.get(team_a, [])
    matches_b = data.get(team_b, [])
    h2h       = data.get('H2H', [])
    date_str  = match_date or datetime.today().strftime('%d/%m/%Y')

    # Buffer de salida
    buffer = io.BytesIO()
    dest   = output_path or buffer

    doc = SimpleDocTemplate(
        dest, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
        title=f'STUBET - {team_a} vs {team_b}',
        author='STUBET Intelligence v2.0',
    )
    story = []

    # ── PORTADA ───────────────────────────────────────────────────────────────
    cover_tbl = Table([[Paragraph(
        f'<b>STUBET INTELLIGENCE</b><br/>'
        f'<font size="16">{team_a} vs {team_b}</font><br/>'
        f'<font size="10">{date_str}</font>',
        _ps('cv', fontSize=20, textColor=WHITE, fontName='Helvetica-Bold',
            alignment=TA_CENTER, leading=28)
    )]], colWidths=[17*cm])
    cover_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_TEAM_A),
        ('TOPPADDING',    (0, 0), (-1, -1), 20),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
    ]))
    story.append(Spacer(1, 2*cm))
    story.append(cover_tbl)
    story.append(Spacer(1, 1*cm))

    # Índice
    idx_data = [
        ['SECCION', 'CONTENIDO', 'PARTIDOS'],
        [f'1. {team_a}', 'Ultimos partidos + Resumen estadistico (Local/Visitante)', str(len(matches_a))],
        [f'2. {team_b}', 'Ultimos partidos + Resumen estadistico (Local/Visitante)', str(len(matches_b))],
        ['3. H2H',       'Historial de enfrentamientos directos',                   str(len(h2h))],
    ]
    idx_tbl = Table(idx_data, colWidths=[4.5*cm, 9*cm, 3.5*cm])
    idx_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), C_DGRAY),
        ('TEXTCOLOR',     (0, 0), (-1, 0), WHITE),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1,-1), 9),
        ('ALIGN',         (0, 0), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS',(0, 1), (-1,-1), [WHITE, C_LGRAY]),
        ('GRID',          (0, 0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
        ('TOPPADDING',    (0, 0), (-1,-1), 6),
        ('BOTTOMPADDING', (0, 0), (-1,-1), 6),
    ]))
    story.append(idx_tbl)
    story.append(Spacer(1, 8*mm))

    # Leyenda
    leyenda_data = [[
        Paragraph('Columna AMARILLA = estadisticas del equipo analizado', BOLD_S),
        Paragraph('V Victoria  E Empate  D Derrota', BOLD_S),
        Paragraph('L = Local | V = Visitante | ALL/1ST/2ND = periodo', BODY_S),
    ]]
    ley_tbl = Table(leyenda_data, colWidths=[6*cm, 5*cm, 6*cm])
    ley_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fffbcc')),
        ('BOX',        (0, 0), (-1, -1), 1, colors.HexColor('#ccaa00')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1),  5),
        ('LEFTPADDING',(0, 0), (-1, -1), 5),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(ley_tbl)
    story.append(PageBreak())

    # ── SECCIÓN EQUIPO A ──────────────────────────────────────────────────────
    if matches_a:
        build_team_section(matches_a, team_a, 1, C_TEAM_A, story)

    # ── SECCIÓN EQUIPO B ──────────────────────────────────────────────────────
    if matches_b:
        build_team_section(matches_b, team_b, 2, C_TEAM_B, story)

    # ── SECCIÓN H2H ───────────────────────────────────────────────────────────
    if h2h:
        build_h2h_section(h2h, team_a, story)

    doc.build(story)

    if output_path:
        return None  # guardado en disco

    buffer.seek(0)
    return buffer.read()
