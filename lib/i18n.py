"""Shared i18n helper for provisioning's Python GUI scripts.

Usage: `from i18n import t` (with lib/ on sys.path), then `t("some.key")`.

Locale source of truth is /etc/default/locale (written by
00-locale-keyboard-timezone.sh's `dpkg-reconfigure locales`) -- read
directly rather than trusting $LANG, since these scripts are sometimes
launched from panel plugins/udev/systemd with a stripped environment even
inside a live desktop session.
"""
import importlib.util
import os
import pathlib
import re

_LOCALE_FILE = "/etc/default/locale"
_I18N_DIR = pathlib.Path(__file__).resolve().parent / "i18n"


def _detect_locale():
    lang = None
    try:
        with open(_LOCALE_FILE) as f:
            for line in f:
                m = re.match(r'^LANG=("?)([^"\n]*)\1\s*$', line.strip())
                if m and m.group(2):
                    lang = m.group(2)
    except OSError:
        pass
    lang = lang or os.environ.get("LANG", "en_US.UTF-8")
    return lang.split("_")[0].split(".")[0]


def _load_catalog(locale):
    path = _I18N_DIR / f"strings_{locale}.py"
    if not path.exists():
        return {}
    spec = importlib.util.spec_from_file_location(f"cyberbeest_i18n_{locale}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.STRINGS


_EN = _load_catalog("en")
_LOCALE = _detect_locale()
_L10N = _load_catalog(_LOCALE) if _LOCALE != "en" else {}


def t(key):
    """Translated string for KEY, falling back to English, then KEY itself."""
    return _L10N.get(key) or _EN.get(key) or key
