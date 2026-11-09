"""Report card as a PDF (A4 portrait)."""
import io
from pathlib import Path

from django.conf import settings

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape


URDU_FONT, URDU_FONT_BOLD = "DejaVuSans", "DejaVuSans-Bold"
_fonts_ready = False


def _register_fonts():
    """Urdu script needs a TrueType font with Arabic glyphs (DejaVu Sans is bundled in static/fonts)."""
    global _fonts_ready
    if _fonts_ready:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    base = Path(settings.BASE_DIR) / "static" / "fonts"
    pdfmetrics.registerFont(TTFont(URDU_FONT, str(base / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(URDU_FONT_BOLD, str(base / "DejaVuSans-Bold.ttf")))
    _fonts_ready = True


def _shape(text, base_dir="R"):
    """Join Urdu letters and put them in visual right-to-left order for reportlab."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
    except ImportError:  # libraries missing: keep the text readable as logical order rather than crash
        return text
    # DejaVu lacks Urdu heh-goal (ہ), yeh-barree (ے) and the Urdu full stop (۔); use the nearest glyphs it has.
    text = text.translate({0x06C1: 0x0647, 0x06C3: 0x0629, 0x06D2: 0x0649, 0x06D3: 0x0649, 0x06D4: 0x002E})
    return get_display(arabic_reshaper.reshape(text), base_dir=base_dir)


def _num(d):
    """100 not 1E+2: Decimal.normalize() switches to exponent form for round numbers."""
    return format(d.normalize(), "f")


def _wrap_urdu(text, font, size, width):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    lines, cur = [], ""
    for word in str(text).split():
        trial = (cur + " " + word).strip()
        if cur and stringWidth(_shape(trial), font, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def _has_urdu(text):
    return any("\u0600" <= ch <= "\u06FF" for ch in str(text))


def _cell(text):
    """Table cell: plain string, or a DejaVu paragraph when it contains Urdu (mixed English / Urdu stays in reading order)."""
    if not _has_urdu(text):
        return text
    return Paragraph(escape(_shape(str(text), "L")), ParagraphStyle("cell", fontName=URDU_FONT, fontSize=9, leading=12))


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def report_card_pdf(school, ins, row, guidance, stats, scale, urdu=None):
    _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Report card - {ins['student'].display_name}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading3"], spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.grey)
    ex, st = ins["exam"], ins["student"]
    els = [_p(school, h1), _p(f"Report Card — {ex.name}", ss["Heading2"]),
           _p(f"Student: {st.display_name}    Class: {ex.school_class}", body), Spacer(1, 6)]
    data = [["Subject", "Marks", "Out of", "%", "Grade", "Remarks", "Class avg %", "Result"]]
    for c in row["cells"]:
        if not c["entered"]:
            data.append([c["paper"].subject_name, "—", _num(c["paper"].total_marks), "", "", "", "", "Pending"])
            continue
        avg = next((s["avg_pct"] for s in stats if s["paper"].id == c["paper"].id), None)
        data.append([c["paper"].subject_name, "ABS" if c["absent"] else _num(c["marks"]), _num(c["paper"].total_marks),
                     "" if c["absent"] else c["pct"], c["band"].grade, ("Absent" if c["absent"] else c["band"].remark), "" if avg is None else avg, "Pass" if c["passed"] else "Fail"])
    data.append(["TOTAL", _num(row["total"]), _num(row["out_of"]), row["pct"] if row["pct"] is not None else "",
                 row["band"].grade if row["band"] else "", row["band"].remark if row["band"] else "", "", row["result"].title()])
    t = Table(data, colWidths=[34 * mm, 15 * mm, 14 * mm, 15 * mm, 14 * mm, 36 * mm, 22 * mm, 16 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a8a")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8ccd4")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef1f6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fb")])]))
    els += [t, Spacer(1, 8)]
    els.append(_p(f"Overall: {_num(row['total'])} / {_num(row['out_of'])} = {row['pct']}%   Grade: {row['band'].grade if row['band'] else '-'}   GPA: {row['gpa']}   "
                  f"Position: {row['rank'] or '-'} of {ins['n_ranked']}   Result: {row['result'].title()}", body))
    L = {"en": dict(summary="English", weak="Weak areas", strong="Strengths", plan="Study plan for the student - please follow",
                    habits="General habits", parent="Note for parents"),
         "ur": dict(summary="اردو", weak="کمزور مضامین", strong="مضبوط پہلو", plan="طالب علم کا اسٹڈی پلان — اس پر عمل کریں",
                    habits="عمومی ہدایات", parent="والدین کے لیے نوٹ")}
    ur_body = ParagraphStyle("urb", parent=body, fontName=URDU_FONT, alignment=TA_RIGHT, leading=17, fontSize=10)
    ur_bold = ParagraphStyle("urbold", parent=ur_body, fontName=URDU_FONT_BOLD)

    def para(text, lang, bold=False):
        """List of flowables. Urdu is wrapped in logical order FIRST and each line is shaped on its own,
        otherwise reportlab would break the already-reversed text and the lines would read backwards."""
        if lang == "urs":
            return [Paragraph(escape(_shape(line)), ur_bold if bold else ur_body)
                    for line in _wrap_urdu(text, URDU_FONT_BOLD if bold else URDU_FONT, 10, 496)]
        return [_p(text, ParagraphStyle("ph", parent=body, fontName="Helvetica-Bold", spaceBefore=8) if bold else body)]

    def heading(lang, key):
        els.extend(para(L[lang][key], "urs", True)) if lang == "ur" else els.append(_p(L[lang][key], h2))

    def text(lang, value, bullet=False):
        els.extend(para(("• " if bullet else "") + value, "urs")) if lang == "ur" else els.append(_p(("• " if bullet else "") + value, body))

    for lang, g in (("en", guidance), ("ur", urdu)):
        if g:
            heading(lang, "summary")
            text(lang, g["summary"])
    if guidance:
        if guidance.get("weak_areas"):
            els.append(_p(L["en"]["weak"], h2))
            els.extend(para(L["ur"]["weak"], "urs", True))
            for w in guidance["weak_areas"]:
                els.extend(para(f"{w['subject']}: {w['issue']}. {w['advice']}" if w.get("lang") != "urs" else f"{w['subject']}: {w['issue']} {w['advice']}", w.get("lang"), False))
        if guidance.get("subject_plans"):
            els.append(_p(L["en"]["plan"], h2))
            els.extend(para(L["ur"]["plan"], "urs", True))
            if guidance.get("timetable"):
                rows = [["Day", "Subject", "Time", "Done"]] + [
                    [_cell(t["day"]), _cell(t["subject"]), f"{t['minutes']} min" if t["minutes"] else "-", ""] for t in guidance["timetable"]]
                tt = Table(rows, colWidths=[38 * mm, 66 * mm, 28 * mm, 18 * mm])
                tt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")), ("FONTSIZE", (0, 0), (-1, -1), 9),
                                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8ccd4")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
                els += [tt, Spacer(1, 4)]
                if guidance.get("timetable_tip"):
                    els.append(_p(guidance["timetable_tip"], small))
                if guidance.get("timetable_tip_ur"):
                    els.extend(para(guidance["timetable_tip_ur"], "urs"))
            for p_ in guidance["subject_plans"]:
                pl = p_.get("lang")
                head = (f"{p_['subject']}  {p_['current']}% -> {p_['target']}%  ({p_['daily_minutes']} min)" if pl != "urs" else
                        f"{p_['subject']}: ابھی {p_['current']}% ← ہدف {p_['target']}% ، روزانہ {p_['daily_minutes']} منٹ")
                els.extend(para(head, pl, True))
                for w in p_["weeks"]:
                    els.extend(para(f"{w['title']}: " + " ".join(f"({i}) {t}" for i, t in enumerate(w["tasks"], 1)), pl))
                els.extend(para(p_["checkpoint"], pl))
    for lang, g in (("en", guidance), ("ur", urdu)):
        if not g:
            continue
        for key, label in (("strengths", "strong"), ("action_plan", "habits")):
            if g.get(key):
                heading(lang, label)
                for x in g[key]:
                    text(lang, x, True)
        if g.get("parent_note"):
            heading(lang, "parent")
            text(lang, g["parent_note"])
    els += [Spacer(1, 14), _p("Grading scale: " + ", ".join(f"{b.grade} >= {b.min_percent:g}%" for b in scale), small)]
    doc.build(els)
    return buf.getvalue()
