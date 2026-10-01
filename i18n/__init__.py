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
for _module in pkgutil.iter_modules(__path__):
    if _module.name.startswith('sw_'):
        SW.update(importlib.import_module(f'{__name__}.{_module.name}').SW)


def current():
    return getattr(g, 'lang', 'en') if has_request_context() else 'en'


def tr(text, **values):
    """`text` in the current user's language, with {placeholders} filled in."""
    out = SW.get(text, text) if current() == 'sw' else text
    return out.format(**values) if values else out
