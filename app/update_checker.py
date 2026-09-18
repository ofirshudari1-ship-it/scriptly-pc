"""בדיקת עדכונים אוטומטית מול GitHub Releases - רצה פעם אחת בכל הפעלה, ב-thread נפרד
כדי לא לחסום את ה-UI, ולעולם לא זורקת/מציגה שגיאה אם אין רשת או שה-API לא זמין.

המקור הקנוני להפצה הוא https://github.com/ofirshudari1-ship-it/scriptly-pc - הבדיקה
פונה ל-releases/latest הציבורי (בלי טוקן, בלי אימות) ומשווה מול app.config.VERSION."""
import threading
import webbrowser

import requests

from .config import VERSION
from .i18n import t
from .logger import get_logger

logger = get_logger(__name__)

REPO = "ofirshudari1-ship-it/scriptly-pc"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
REQUEST_TIMEOUT_SECONDS = 5
# GitHub's REST API rejects requests with no User-Agent header (403) - this is
# not a secret, just an identifier, same convention as e.g. pip/npm clients.
USER_AGENT = "Scriptly-PC-UpdateChecker"

_checked_this_session = False


def _parse_version(version_str: str) -> tuple:
    """"v0.13.1" / "0.13.1" -> (0, 13, 1). Non-numeric parts are dropped rather than
    raising, so a release tag like "v0.13.1-beta" still compares on its numeric prefix."""
    cleaned = version_str.strip().lstrip("vV")
    parts = []
    for chunk in cleaned.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(remote_version: str, current_version: str = VERSION) -> bool:
    return _parse_version(remote_version) > _parse_version(current_version)


def _fetch_latest_release() -> dict:
    """GET releases/latest - returns {} on any failure (network, timeout, non-2xx,
    malformed JSON). Never raises: this must be safe to call from a background
    thread with nothing watching for exceptions."""
    try:
        resp = requests.get(
            LATEST_RELEASE_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            logger.info("update check: unexpected status %s from GitHub API", resp.status_code)
            return {}
        return resp.json() or {}
    except Exception as exc:  # noqa: BLE001 - deliberately broad, must never crash the app
        logger.info("update check failed (network/parse): %s", exc)
        return {}


def check_for_update_sync() -> dict | None:
    """Blocking check - returns {"version": str, "url": str} if a newer release
    exists, else None. Call from a background thread, not the Qt/Tk main thread."""
    data = _fetch_latest_release()
    tag = data.get("tag_name")
    html_url = data.get("html_url")
    if not tag or not html_url:
        return None
    if not is_newer(tag, VERSION):
        return None
    return {"version": tag.lstrip("vV"), "url": html_url}


def open_release_page(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not open release page %s: %s", url, exc)


def check_for_updates_async(config: dict, on_update_available) -> None:
    """Kicks off the check on a daemon background thread and returns immediately.
    `on_update_available(version, url)` is called only when a newer release is
    found - the caller decides how to surface it (tray notification etc.) and
    must itself be safe to call from a background thread (or hop back to the
    UI thread inside the callback, same as the rest of this codebase does with
    `root.after(...)`)."""
    global _checked_this_session

    if _checked_this_session:
        return
    if not config.get("check_for_updates_enabled", True):
        return

    def worker():
        global _checked_this_session
        _checked_this_session = True
        try:
            result = check_for_update_sync()
            if result:
                logger.info("update available: %s (current: %s)", result["version"], VERSION)
                on_update_available(result["version"], result["url"])
            else:
                logger.info("update check: already on latest version (%s)", VERSION)
        except Exception:
            logger.exception("unexpected error during update check")

    threading.Thread(target=worker, daemon=True, name="ScriptlyUpdateCheck").start()


def notify_update_via_tray(tray, version: str, url: str) -> None:
    """Reuses the existing pystray balloon-notification mechanism (TrayIcon._on_event
    already does `self.icon.notify(...)` for other events) instead of adding a new
    notification channel. Clicking the balloon on Windows doesn't carry a callback
    through pystray, so this just notifies; `open_release_page` is exposed
    separately for a manual "Check for Updates" action to call directly."""
    try:
        tray.icon.notify(t("update_available_body", version=version), t("update_available_title"))
    except Exception:
        logger.exception("could not show update-available tray notification")
