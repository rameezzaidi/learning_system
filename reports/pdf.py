"""Server-side PDF of the paged report (landscape A4) with real 'Page X of Y'."""
import io
import os

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PDF_ROWS_PER_PAGE = 28
ROW_H = 14
MARGIN = 28
_FONTS = None


def _fonts():
    """Prefer DejaVu (covers Urdu/Arabic-free extended Latin); fall back to built-in Helvetica."""
    global _FONTS
    if _FONTS:
        return _FONTS
    base = "/usr/share/fonts/truetype/dejavu/"
    try:
        if os.path.exists(base + "DejaVuSans.ttf"):
            pdfmetrics.registerFont(TTFont("DV", base + "DejaVuSans.ttf"))
            pdfmetrics.registerFont(TTFont("DV-B", base + "DejaVuSans-Bold.ttf"))
            _FONTS = ("DV", "DV-B")
            return _FONTS
    except Exception:
        pass
    _FONTS = ("Helvetica", "Helvetica-Bold")
    return _FONTS


def _fit(text, font, size, width):
    text = str(text or "")
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def render_pdf(pages, columns, meta):
    """pages: from engine.paginate(); columns: engine.columns_for(); meta: dict(school, title, filters, printed_by, printed_at)."""
    reg, bold = _fonts()
    w, h = landscape(A4)
    usable = w - 2 * MARGIN
    xs, x = [], MARGIN
    for c in columns:
        cw = usable * c["pct"] / 100
        xs.append((x, cw, c))
        x += cw
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=(w, h))
    cv.setTitle(meta["title"])
    total = len(pages)

    def cell(text, x0, cw, y, font, size, align):
        t = _fit(text, font, size, cw - 8)
        if align == "r":
            cv.drawRightString(x0 + cw - 4, y, t)
        else:
            cv.drawString(x0 + 4, y, t)

    for pno, lines in enumerate(pages, start=1):
        # ---- page header ----
        cv.setFillColorRGB(0.1, 0.1, 0.1)
        cv.setFont(bold, 13)
        cv.drawString(MARGIN, h - MARGIN - 10, meta["school"])
        cv.setFont(reg, 8)
        cv.drawRightString(w - MARGIN, h - MARGIN - 8, meta["printed_at"])
        cv.setFont(bold, 11)
        cv.drawString(MARGIN, h - MARGIN - 28, meta["title"])
        cv.setFont(reg, 8)
        cv.setFillColorRGB(0.35, 0.35, 0.35)
        cv.drawString(MARGIN, h - MARGIN - 42, _fit(meta["filters"], reg, 8, usable))
        cv.setStrokeColorRGB(0.2, 0.2, 0.2)
        cv.line(MARGIN, h - MARGIN - 48, w - MARGIN, h - MARGIN - 48)

        # ---- column header ----
        y = h - MARGIN - 48 - ROW_H
        cv.setFillColorRGB(0.9, 0.92, 0.95)
        cv.rect(MARGIN, y - 3, usable, ROW_H, stroke=0, fill=1)
        cv.setFillColorRGB(0.1, 0.1, 0.1)
        for x0, cw, c in xs:
            cell(c["label"], x0, cw, y + 1, bold, 8, c["align"])
        y -= ROW_H

        # ---- body ----
        for ln in lines:
            t = ln["t"]
            if t == "g":
                cv.setFillColorRGB(0.95, 0.96, 0.98 if ln["depth"] else 0.93)
                cv.rect(MARGIN + ln["depth"] * 12, y - 3, usable - ln["depth"] * 12, ROW_H, stroke=0, fill=1)
                cv.setFillColorRGB(0.1, 0.1, 0.1)
                label = ln["label"] + ("  (continued)" if ln.get("cont") else f'  ({ln["count"]})')
                cv.setFont(bold, 9)
                cv.drawString(MARGIN + 4 + ln["depth"] * 12, y + 1, _fit(label, bold, 9, usable - 20))
            elif t == "d":
                r = ln["row"]
                cv.setFillColorRGB(0.1, 0.1, 0.1)
                for x0, cw, c in xs:
                    cell(r.get(c["key"], ""), x0, cw, y + 1, reg, 8, c["align"])
                cv.setStrokeColorRGB(0.9, 0.9, 0.9)
                cv.line(MARGIN, y - 3, w - MARGIN, y - 3)
            elif t == "s":
                cv.setFillColorRGB(0.25, 0.25, 0.25)
                cv.setFont(bold, 8)
                cv.drawRightString(w - MARGIN - 4, y + 1,
                                   f'{ln["label"]} total: {ln["count"]}   (active {ln["active"]})')
                cv.setStrokeColorRGB(0.6, 0.6, 0.6)
                cv.line(MARGIN, y - 3, w - MARGIN, y - 3)
            else:  # grand total
                cv.setStrokeColorRGB(0.1, 0.1, 0.1)
                cv.line(MARGIN, y + ROW_H - 3, w - MARGIN, y + ROW_H - 3)
                cv.setFillColorRGB(0.1, 0.1, 0.1)
                cv.setFont(bold, 9)
                cv.drawString(MARGIN + 4, y + 1,
                              f'GRAND TOTAL: {ln["count"]} students · {ln["active"]} active · {ln["inactive"]} inactive'
                              f' · {ln["oracle"]} from Oracle · {ln["manual"]} manual')
            y -= ROW_H

        # ---- page footer ----
        cv.setStrokeColorRGB(0.5, 0.5, 0.5)
        cv.line(MARGIN, MARGIN + 12, w - MARGIN, MARGIN + 12)
        cv.setFont(reg, 8)
        cv.setFillColorRGB(0.35, 0.35, 0.35)
        cv.drawString(MARGIN, MARGIN, f'Printed by {meta["printed_by"]}')
        cv.drawCentredString(w / 2, MARGIN, f"Page {pno} of {total}")
        cv.drawRightString(w - MARGIN, MARGIN, meta["school"])
        cv.showPage()
    cv.save()
    return buf.getvalue()
