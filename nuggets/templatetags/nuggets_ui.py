from django import template

from .. import md as _md

register = template.Library()


@register.filter
def md(value):
    """Safe formatting for nugget text: **bold**, *italic*, lists, headings, quotes, $math$."""
    return _md.render(value)
