"""The owner dashboard in English or Kiswahili.

Write the English in the code, wrapped: `tr('Payment settings saved.')` in Python, `{{ _('Earnings') }}` in templates.
Values go in as named placeholders: `tr('{n} packages on sale', n=count)`. The Kiswahili lives in the
i18n/sw_*.py modules, each defining SW = {english: kiswahili}; tests/test_i18n.py fails if one is missing.
Each user picks their language (Admin.language); before login it comes from a cookie.
"""
import importlib
import pkgutil

from flask import g, has_request_context

LANGS = {'en': 'English', 'sw': 'Kiswahili'}

SW = {}
# Fixed order, sw_base last: it holds the agreed words when two files translate the same English differently
for _name in sorted(m.name for m in pkgutil.iter_modules(__path__) if m.name.startswith('sw_') and m.name != 'sw_base') + ['sw_base']:
    SW.update(importlib.import_module(f'{__name__}.{_name}').SW)


def current():
    return getattr(g, 'lang', 'en') if has_request_context() else 'en'


def tr(text, **values):
    """`text` in the current user's language, with {placeholders} filled in."""
    out = SW.get(text, text) if current() == 'sw' else text
    return out.format(**values) if values else out


class L(str):
    """Text translated when it's shown, not when it's defined: for form labels, choices and messages in forms.py
    (written at import time, shown in a request). Behaves like the English str everywhere else."""
    def __str__(self):
        return tr(str.__str__(self))

    def __html__(self):
        from markupsafe import escape
        return str(escape(tr(str.__str__(self))))

    def format(self, *args, **kwargs):
        return tr(str.__str__(self)).format(*args, **kwargs)

    def __mod__(self, values):
        return tr(str.__str__(self)) % values
