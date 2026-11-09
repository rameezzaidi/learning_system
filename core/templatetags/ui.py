from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

ICONS = {
    "chat": '<path d="M4 5h16a1 1 0 011 1v10a1 1 0 01-1 1H10l-5 4v-4H4a1 1 0 01-1-1V6a1 1 0 011-1z"/><path d="M8 10h8M8 13h5"/>',
    "send": '<path d="M21 3L10 14"/><path d="M21 3l-7 18-4-7-7-4z"/>',
    "clip": '<path d="M20 11.5l-8 8a5 5 0 01-7-7l9-9a3.5 3.5 0 015 5l-9 9a2 2 0 01-3-3l8-8"/>',
    "smile": '<circle cx="12" cy="12" r="9"/><path d="M8.5 14c1 1.3 2.2 2 3.5 2s2.5-.7 3.5-2"/><path d="M9 9.5h.01M15 9.5h.01"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    "back": '<path d="M15 5l-7 7 7 7"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><circle cx="17.5" cy="9" r="2.5"/><path d="M17 14.2c2.8.2 4.5 2.2 4.5 5.3"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
    "settings": '<path d="M3 6h11M18 6h3M3 12h5M12 12h9M3 18h13M20 18h1"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "palette": '<path d="M12 3a9 9 0 100 18c1.4 0 2-1 1.6-2.2-.4-1.2.3-2.3 1.6-2.3H17a4 4 0 004-4c0-5-4-9.5-9-9.5z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7" r="1"/><circle cx="15.5" cy="7.5" r="1"/>',
    "book": '<path d="M4 5a2 2 0 012-2h14v16H6a2 2 0 00-2 2z"/><path d="M4 21V5"/>',
    "clipboard": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 11h6M9 15h4"/>',
    "sparkles": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
    "chart": '<path d="M4 20V4M4 20h16"/><path d="M8 16v-4M12 16V8M16 16v-7"/>',
    "logout": '<path d="M9 4H5a1 1 0 00-1 1v14a1 1 0 001 1h4M16 8l4 4-4 4M20 12H9"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "power": '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1011.4 0"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "school": '<path d="M3 9l9-5 9 5-9 5z"/><path d="M7 11.5V16c0 1.2 2.2 3 5 3s5-1.8 5-3v-4.5"/><path d="M21 9v6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3"/>',
    "bell": '<path d="M6 17V11a6 6 0 0112 0v6l1.5 2h-15z"/><path d="M10 21h4"/>',
    "play": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5l6 3.5-6 3.5z"/>',
    "puzzle": '<path d="M9 4h3v2a1.5 1.5 0 003 0V4h3v4h-2a1.5 1.5 0 000 3h2v4h-3v-2a1.5 1.5 0 00-3 0v2H9v-3H7a1.5 1.5 0 010-3h2z"/>',
    "link": '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3A4 4 0 0010 18.7l1-1"/>',
    "file": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 114 2c-.9.6-1.5 1.1-1.5 2.2M12 17h.01"/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "bell": '<path d="M6 9a6 6 0 0112 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9z"/><path d="M10 20a2 2 0 004 0"/>',
    "calendar": '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/>',
}


@register.simple_tag
def icon(name, size=20):
    body = ICONS.get(name, ICONS["check"])
    return format_html(
        '<svg class="ico" width="{0}" height="{0}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{1}</svg>',
        size, mark_safe(body),
    )


@register.filter
def embed(url):
    """Turn a YouTube watch/short link into an embeddable URL ('' if not YouTube)."""
    import re

    m = re.search(r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})", url or "")
    return f"https://www.youtube.com/embed/{m.group(1)}" if m else ""


@register.filter
def get(mapping, key):
    return mapping.get(key)


@register.filter
def initials(user):
    name = (user.get_full_name() or user.username or "?").split()
    return "".join(p[0] for p in name[:2]).upper()


KIND_ICON = {"text": "book", "video": "play", "link": "link", "file": "file", "embed": "puzzle", "game": "puzzle",
             "quiz": "clipboard"}


@register.filter
def kind_icon(kind):
    return KIND_ICON.get(kind, "book")


@register.filter
def cover(name):
    """Stable gradient per subject name, used as the course 'cover image'."""
    h = sum(ord(c) * (i + 3) for i, c in enumerate(name or "x")) % 360
    return mark_safe(f"background:linear-gradient(135deg,hsl({h} 65% 42%),hsl({(h + 45) % 360} 70% 32%))")


@register.filter
def hours(minutes):
    m = int(minutes or 0)
    if not m:
        return ""
    return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m} min"


@register.filter
def subj_kind(name):
    """'math' | 'english' | 'urdu' | 'general' for a subject name."""
    from core.subjects import subject_kind
    return subject_kind(name)


@register.simple_tag
def avatar(u, size=""):
    """Round profile photo, or initials when the user has no photo."""
    cls = ("avatar " + size).strip()
    if u is not None and getattr(u, "avatar", None):
        try:
            return format_html('<span class="{} has-img"><img src="{}" alt="" loading="lazy"></span>', cls, u.avatar.url)
        except ValueError:
            pass
    return format_html('<span class="{}">{}</span>', cls, initials(u) if u is not None else "?")


@register.filter
def json_attr(value):
    """JSON for a data-* attribute (Django's autoescape makes the quotes safe)."""
    import json
    return json.dumps(value, ensure_ascii=False)


@register.filter
def get_item(d, key):
    try:
        return d.get(key, "")
    except AttributeError:
        return ""
