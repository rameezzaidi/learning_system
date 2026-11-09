"""Tiny, SAFE text formatting for nugget explanations (no raw HTML is ever allowed).

Supported:  # / ## headings, **bold**, *italic*, "- " bullets, "1. " numbers, "> " quotes, blank line = new paragraph,
$formula$ is left untouched for KaTeX. The same grammar is implemented in static/js/nugget_editor.js (live preview).
"""
import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

_MATH = re.compile(r"\$[^$\n]+\$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")


def _inline(s):
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    return _ITAL.sub(r"<em>\1</em>", s)


def render(text):
    text = escape(text or "").replace("\r\n", "\n")
    saved = []
    text = _MATH.sub(lambda m: saved.append(m.group(0)) or f"\x00{len(saved) - 1}\x00", text)
    out, para, items, kind = [], [], [], ""

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
            para.clear()

    def flush_list():
        nonlocal kind
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{kind}>")
            items.clear()
        kind = ""

    for raw in text.split("\n"):
        line = raw.rstrip()
        m_h = re.match(r"^(#{1,3})\s+(.+)$", line)
        m_ul = re.match(r"^\s*[-*•]\s+(.+)$", line)
        m_ol = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        m_q = re.match(r"^&gt;\s?(.+)$", line)
        if not line.strip():
            flush_para(); flush_list()
        elif m_h:
            flush_para(); flush_list()
            out.append(f"<h{len(m_h.group(1)) + 2}>{_inline(m_h.group(2))}</h{len(m_h.group(1)) + 2}>")
        elif m_ul or m_ol:
            flush_para()
            want = "ul" if m_ul else "ol"
            if kind and kind != want:
                flush_list()
            kind = want
            items.append((m_ul or m_ol).group(1))
        elif m_q:
            flush_para(); flush_list()
            out.append(f"<blockquote>{_inline(m_q.group(1))}</blockquote>")
        else:
            flush_list()
            para.append(line)
    flush_para(); flush_list()
    html = "".join(out)
    html = re.sub(r"\x00(\d+)\x00", lambda m: saved[int(m.group(1))], html)
    return mark_safe(html)
