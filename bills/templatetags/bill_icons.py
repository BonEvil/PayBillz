from django import template
from django.utils.safestring import mark_safe
from bills.icons import ICONS
register = template.Library()

@register.simple_tag
def icon(name):
    # Only trusted, bundled paths are ever rendered; unknown values use a fallback.
    paths = ICONS.get(name, ICONS['receipt'])[1]
    return mark_safe('<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + paths + '</svg>')
