"""בדיקת עדכונים אוטומטית מול GitHub Releases - רצה פעם אחת בכל הפעלה, ב-thread נפרד
כדי לא לחסום את ה-UI, ולעולם לא זורקת/מציגה שגיאה אם אין רשת או שה-API לא זמין.

המקור הקנוני להפצה הוא https://github.com/ofirshudari1-ship-it/scriptly-pc - הבדיקה
פונה ל-releases/latest הציבורי (בלי טוקן, בלי אימות) ומשווה מול app.config.VERSION.

This module also drives the actual self-update (download + silent install + relaunch,
see perform_self_update below). KNOWN LIMITATION: the installer is ~2.17GB, which
exceeds GitHub's 2GB release-asset limit, so as of this writing every published
release ships as tag+notes only with NO binary attached. perform_self_update /
_find_installer_asset detect that honestly (no assets on the release -> raises
NoAssetHostedError with a clear message) instead of attempting a download that
would just 404. The mechanism itself is generic - it reads whatever asset URL the
GitHub release API reports - so it will start working the moment a binary is
actually attached to a release (e.g. once the installer is hosted on a cloud
bucket and the release is edited to link/attach it there)."""
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

import requests

from .config import PROJECT_ROOT, VERSION
from .i18n import t
from .logger import get_logger

logger = get_logger(__name__)

REPO = "ofirshudari1-ship-it/scriptly-pc"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
REQUEST_TIMEOUT_SECONDS = 5
DOWNLOAD_TIMEOUT_SECONDS = 30  # per-request timeout for the streamed download (not total transfer time)
# GitHub's REST API rejects requests with no User-Agent header (403) - this is
# not a secret, just an identifier, same convention as e.g. pip/npm clients.
USER_AGENT = "Scriptly-PC-UpdateChecker"

_checked_this_session = False


class UpdateError(Exception):
    """Base class for the self-update flow - anything that should surface as an
    honest failure message to the user rather than crash the calling thread."""


class NoAssetHostedError(UpdateError):
    """A newer release exists on GitHub, but it has no installer attached yet.
    This is expected/normal today (see module docstring - the 2GB hosting gap)
    and must be handled as a graceful, honest outcome, never as a crash."""


class UpdateDownloadError(UpdateError):
    """The download itself failed or produced a truncated/incomplete file."""


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


def _find_installer_asset(release_data: dict) -> dict | None:
    """Looks at the GitHub release JSON's `assets` array for a downloadable Windows
    installer. Returns {"name", "download_url", "size"} or None if nothing is
    attached yet - which is today's actual state for every Scriptly PC release,
    since the installer (~2.17GB) exceeds GitHub's 2GB release-asset limit. This
    is intentionally generic (any .exe asset qualifies) rather than hardcoding
    build_installer.py's exact filename pattern, so it keeps working if that
    naming ever changes."""
    for asset in release_data.get("assets") or []:
        name = asset.get("name", "")
        url = asset.get("browser_download_url")
        if not url or not name.lower().endswith(".exe"):
            continue
        return {"name": name, "download_url": url, "size": int(asset.get("size") or 0)}
    return None


def check_for_update_sync() -> dict | None:
    """Blocking check - returns {"version": str, "url": str, "asset": dict|None}
    if a newer release exists, else None. `asset` is None when GitHub reports
    the release but nothing downloadable is attached to it yet (see module
    docstring). Call from a background thread, not the Qt/Tk main thread."""
    data = _fetch_latest_release()
    tag = data.get("tag_name")
    html_url = data.get("html_url")
    if not tag or not html_url:
        return None
    if not is_newer(tag, VERSION):
        return None
    return {"version": tag.lstrip("vV"), "url": html_url, "asset": _find_installer_asset(data)}


def open_release_page(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not open release page %s: %s", url, exc)


def download_installer(asset: dict, dest_dir: Path | None = None, on_progress=None) -> Path:
    """Streams the release's installer asset to a temp file with progress
    reporting (`on_progress(downloaded_bytes, total_bytes)`, total may be 0 if
    unknown), then verifies the download actually completed in full (size
    check against the asset's reported size / Content-Length) before returning.
    Raises UpdateDownloadError - never returns a partially-written file as if
    it succeeded, and always cleans up a failed/partial download."""
    if dest_dir is None:
        dest_dir = Path(tempfile.gettempdir())
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / asset["name"]
    expected_size = int(asset.get("size") or 0)

    try:
        with requests.get(
            asset["download_url"],
            headers={"User-Agent": USER_AGENT},
            stream=True,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        ) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or expected_size or 0)
            downloaded = 0
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        try:
                            on_progress(downloaded, total)
                        except Exception:  # noqa: BLE001 - a broken progress callback must not abort the download
                            logger.exception("update download progress callback failed")
    except Exception as exc:  # noqa: BLE001
        dest_path.unlink(missing_ok=True)
        raise UpdateDownloadError(f"download failed: {exc}") from exc

    actual_size = dest_path.stat().st_size if dest_path.exists() else 0
    if actual_size == 0 or (expected_size and actual_size != expected_size):
        dest_path.unlink(missing_ok=True)
        raise UpdateDownloadError(
            f"download incomplete: got {actual_size} bytes, expected {expected_size or 'unknown'}"
        )
    return dest_path


def launch_silent_installer(installer_path: Path, install_dir: Path | None = None) -> None:
    """Launches the downloaded installer with --silent, pinned to this install's
    own folder via --install-dir so the update lands exactly where this copy of
    Scriptly PC is already running from, rather than trusting the installer's
    own registry lookup (a reasonable fallback for a fresh/manual install, but
    not the right source of truth mid self-update). Detached so it survives
    this process exiting right after."""
    target_dir = str(install_dir or PROJECT_ROOT)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(installer_path), "--silent", f"--install-dir={target_dir}"],
        creationflags=creationflags,
        close_fds=True,
    )


def perform_self_update(on_progress=None) -> Path:
    """Blocking, synchronous end-to-end self-update: fetch the latest release,
    require a downloadable asset (raise NoAssetHostedError with an honest
    message if the release has nothing attached - today's actual state), download
    it with progress reporting, verify the download, then launch it silently.

    Does NOT stop any in-progress recording or quit the app itself - by design,
    the caller (Settings UI / auto-update worker) owns that decision and must
    only quit *after* this returns successfully, having first cleanly stopped
    any live recording. Raises UpdateError (or a subclass) on any failure;
    never partially succeeds silently."""
    data = _fetch_latest_release()
    tag = data.get("tag_name")
    if not tag:
        raise UpdateError("could not reach the update server (network error or GitHub API unavailable)")

    asset = _find_installer_asset(data)
    if not asset:
        version = tag.lstrip("vV")
        raise NoAssetHostedError(
            f"Scriptly PC {version} is available, but the installer isn't hosted here yet - "
            f"check https://github.com/{REPO}/releases for how to get it."
        )

    installer_path = download_installer(asset, on_progress=on_progress)
    launch_silent_installer(installer_path)
    return installer_path


def check_for_updates_async(config: dict, on_update_available) -> None:
    """Kicks off the check on a daemon background thread and returns immediately.
    `on_update_available(version, url, asset)` is called only when a newer release
    is found - the caller decides how to surface it (tray notification, optional
    auto-update, etc.) and must itself be safe to call from a background thread
    (or hop back to the UI thread inside the callback, same as the rest of this
    codebase does with `root.after(...)`). `asset` is None when nothing is
    downloadable on the release yet."""
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
                on_update_available(result["version"], result["url"], result.get("asset"))
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
