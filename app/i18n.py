"""תרגומים ל-UI - ברירת מחדל אנגלית, עם אפשרות מעבר לעברית מתוך ההגדרות.

הטקסטים עצמם חיים ב-locales/en.json ו-locales/he.json (לא בקוד) - זה המקור
היחיד, לפי מבנה התקן המשותף. המודול הזה רק טוען וממשק אליהם (t()/set_language()
וכו') ומחזיק גם את פונקציות העזר ל-RTL, שהן היגיון UI ולא טקסט לתרגום."""
import json
import sys
from pathlib import Path

from .logger import get_logger

logger = get_logger(__name__)

# Bundled read-only resource - lives under PyInstaller's _MEIPASS (`_internal/`
# in onedir mode) when frozen, not beside the exe. See config.py's
# PROJECT_ROOT-vs-RESOURCE_ROOT split for the full explanation.
if getattr(sys, "frozen", False):
    _RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    _RESOURCE_ROOT = Path(__file__).resolve().parent.parent

_LOCALES_DIR = _RESOURCE_ROOT / "locales"


def _load_locale(lang: str) -> dict:
    path = _LOCALES_DIR / f"{lang}.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("could not load locale file %s: %s", path, exc)
        return {}


_LOCALES = {"en": _load_locale("en"), "he": _load_locale("he")}
_current_language = "en"


def set_language(lang: str) -> None:
    global _current_language
    _current_language = lang if lang in _LOCALES and _LOCALES[lang] else "en"


def get_language() -> str:
    return _current_language


def t(key: str, **kwargs) -> str:
    strings = _LOCALES.get(_current_language) or _LOCALES.get("en") or {}
    text = strings.get(key) or _LOCALES.get("en", {}).get(key) or key
    return text.format(**kwargs) if kwargs else text


# ── RTL helpers ──────────────────────────────────────────────────────────
# CustomTkinter (built on Tk) has no built-in RTL/FlowDirection equivalent -
# every widget's text alignment and side-by-side layout order has to be
# mirrored by hand for Hebrew. These helpers are the single source of truth
# for "which direction" so call sites don't hardcode "e"/"right" themselves.

def is_rtl() -> bool:
    return _current_language == "he"


def anchor(ltr: str = "w", rtl: str = "e") -> str:
    """Tk anchor/sticky value (n/s/e/w combos) for the current language."""
    return rtl if is_rtl() else ltr


def justify() -> str:
    """Text-justify value ("left"/"right") for multi-line Label/Textbox text."""
    return "right" if is_rtl() else "left"


def pack_side(ltr: str = "left", rtl: str = "right") -> str:
    """Which side a widget should pack() to, for elements laid out in a row
    (e.g. an icon before a label) so the visual order flips for Hebrew."""
    return rtl if is_rtl() else ltr
