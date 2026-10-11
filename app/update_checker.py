"""Update checker + self-update for Scriptly PC (GitHub Releases).

Flow: a background thread checks GitHub a few seconds after launch and then
every ~6 hours (never blocks the UI, never raises). When a newer release has an
installer attached and "install updates automatically" is on, the installer is
downloaded and verified (HTTPS, GitHub repo URL prefix, byte size, "MZ" header,
sha256 from the GitHub asset digest when present - never blocks if the digest is
absent) and then launched with `--silent --relaunch --install-dir=<this install>`
at a safe moment (no recording running) or when the app exits.

The installer embeds a requireAdministrator manifest (--uac-admin), so a plain
CreateProcess fails with WinError 740 from a non-elevated app. In that case the
launch falls back to ShellExecute, which shows the one Windows UAC prompt; if the
user declines, nothing is installed and the app keeps running. After the silent
install the (elevated) installer relaunches the app through explorer.exe so the
app does not inherit administrator rights.

Source of truth: https://github.com/ofirshudari1-ship-it/scriptly-pc"""
import hashlib
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

import requests

from .config import PROJECT_ROOT, VERSION
from .i18n import t
from .logger import get_logger

logger = get_logger(__name__)

REPO = "ofirshudari1-ship-it/scriptly-pc"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
# Only installers attached to THIS repo's releases are ever downloaded/executed.
ALLOWED_ASSET_PREFIX = f"https://github.com/{REPO}/releases/download/"
REQUEST_TIMEOUT_SECONDS = 5
DOWNLOAD_TIMEOUT_SECONDS = 30  # per-request timeout for the streamed download (not total transfer time)
FIRST_CHECK_DELAY_SECONDS = 5
CHECK_INTERVAL_SECONDS = 6 * 60 * 60
USER_AGENT = "Scriptly-PC-UpdateChecker"
INSTALLER_PREFIX = "Scriptly-PC-Setup-"
ERROR_ELEVATION_REQUIRED = 740

# version -> path of a verified installer already downloaded this session
_STAGED: dict = {}
_stop_event = threading.Event()


class UpdateError(Exception):
    """Anything in the self-update flow that should surface as an honest failure
    message to the user rather than crash the calling thread."""


class NoAssetHostedError(UpdateError):
    """A newer release exists on GitHub but has no installer attached."""


class UpdateDownloadError(UpdateError):
    """The download failed, was truncated, or failed integrity verification."""


class UpdateLaunchError(UpdateError):
    """The installer could not be started (e.g. the UAC prompt was declined)."""


def _parse_version(version_str: str) -> tuple:
    """"v0.13.1" / "0.13.1" -> (0, 13, 1). Non-numeric parts are dropped rather than
    raising, so a release tag like "v0.13.1-beta" still compares on its numeric prefix."""
    cleaned = (version_str or "").strip().lstrip("vV")
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


def is_trusted_asset_url(url) -> bool:
    return isinstance(url, str) and url.startswith(ALLOWED_ASSET_PREFIX)


def _extract_sha256(digest) -> str:
    """GitHub publishes asset digests as "sha256:<64 hex>". Returns the hex, or ""
    when absent/malformed (callers must then skip the check, never fail on it)."""
    d = str(digest or "").strip().lower()
    if not d.startswith("sha256:"):
        return ""
    d = d[len("sha256:"):]
    if len(d) != 64 or any(c not in "0123456789abcdef" for c in d):
        return ""
    return d


def _fetch_latest_release() -> dict:
    """GET releases/latest - returns {} on any failure. Never raises."""
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
    """The CPU installer (Scriptly-PC-Setup-<ver>.exe) attached to the release, as
    {"name", "download_url", "size", "sha256"}; None if nothing matching is attached.
    The optional "-gpu" variant is never auto-installed over the standard one."""
    for asset in release_data.get("assets") or []:
        name = asset.get("name", "") or ""
        url = asset.get("browser_download_url")
        low = name.lower()
        if not url or not low.startswith(INSTALLER_PREFIX.lower()) or not low.endswith(".exe"):
            continue
        if low.endswith("-gpu.exe"):
            continue
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        return {"name": name, "download_url": url, "size": size, "sha256": _extract_sha256(asset.get("digest"))}
    return None


def check_for_update_sync() -> dict | None:
    """Blocking check - {"version", "url", "asset": dict|None} if a newer release
    exists, else None. Call from a background thread."""
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


def verify_installer_file(path: Path, expected_size: int = 0, expected_sha256: str = "") -> str:
    """Returns "" if the file passes every check, else a short reason. Checks byte
    size (when known), the "MZ" PE header, and sha256 (only when a digest is given)."""
    try:
        actual = path.stat().st_size
        if actual == 0:
            return "empty file"
        if expected_size and actual != expected_size:
            return f"size mismatch: got {actual}, expected {expected_size}"
        with open(path, "rb") as f:
            if f.read(2) != b"MZ":
                return "not a Windows executable (missing MZ header)"
        if expected_sha256:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() != expected_sha256.lower():
                return "sha256 mismatch"
    except OSError as exc:
        return f"cannot read file: {exc}"
    return ""


def download_installer(asset: dict, dest_dir: Path | None = None, on_progress=None) -> Path:
    """Streams the installer to a temp file with progress (`on_progress(done, total)`)
    and verifies it (see verify_installer_file) before returning. Raises
    UpdateDownloadError - a failed or unverified file is always deleted."""
    if not is_trusted_asset_url(asset.get("download_url")):
        raise UpdateDownloadError("untrusted installer URL (not a release asset of this repository)")
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

    problem = verify_installer_file(dest_path, expected_size, asset.get("sha256") or "")
    if problem:
        dest_path.unlink(missing_ok=True)
        raise UpdateDownloadError(f"download rejected: {problem}")
    logger.info("update installer downloaded and verified: %s", dest_path)
    return dest_path


def cleanup_stale_downloads(max_age_seconds: float = 3600.0) -> int:
    """Removes installers older than max_age left in %TEMP% by earlier self-updates
    (the detached installer runs from that file, so it can't be deleted earlier).
    Never raises; returns how many were removed."""
    removed = 0
    try:
        now = time.time()
        for p in Path(tempfile.gettempdir()).glob(f"{INSTALLER_PREFIX}*.exe"):
            try:
                if now - p.stat().st_mtime > max_age_seconds:
                    p.unlink()
                    removed += 1
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return removed


def _shell_execute_elevated(exe: str, params: str) -> bool:
    """Starts `exe` through ShellExecute so Windows shows its UAC prompt. True once
    the prompt was accepted and the process started; declining returns <= 32."""
    try:
        import ctypes

        rc = ctypes.windll.shell32.ShellExecuteW(None, "open", exe, params, None, 0)
        if rc > 32:
            logger.info("silent installer started via ShellExecute (UAC accepted)")
            return True
        logger.warning("silent installer not started (UAC declined or blocked, code %s)", rc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ShellExecute failed: %s", exc)
    return False


def build_installer_args(install_dir: Path | str | None = None, relaunch: bool = True) -> list:
    args = ["--silent"]
    if relaunch:
        args.append("--relaunch")
    args.append(f"--install-dir={install_dir or PROJECT_ROOT}")
    return args


def launch_silent_installer(installer_path, install_dir: Path | str | None = None, relaunch: bool = True,
                            *, popen=subprocess.Popen, shell_execute=_shell_execute_elevated) -> bool:
    """Starts the installer silently, detached (this process quits right after).
    Falls back to a UAC prompt via ShellExecute on WinError 740. Returns True once
    started; False if it could not be started (missing file, UAC declined, blocked).
    Never raises. `popen`/`shell_execute` are injectable for tests."""
    try:
        installer_path = Path(installer_path)
        if not installer_path.exists():
            logger.warning("installer to launch is missing: %s", installer_path)
            return False
        args = build_installer_args(install_dir, relaunch)
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            popen([str(installer_path), *args], creationflags=creationflags, close_fds=True)
            return True
        except OSError as exc:
            if getattr(exc, "winerror", None) != ERROR_ELEVATION_REQUIRED:
                raise
            logger.info("installer requires elevation (WinError 740) - asking for UAC")
            return bool(shell_execute(str(installer_path), subprocess.list2cmdline(args)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("launching the silent installer failed: %s", exc)
        return False


def stage_update(on_progress=None) -> dict:
    """Check + download + verify, WITHOUT launching anything. Returns
    {"version", "installer_path", "url"}. Raises NoAssetHostedError / UpdateError /
    UpdateDownloadError. Re-uses an installer already staged for the same version."""
    data = _fetch_latest_release()
    tag = data.get("tag_name")
    if not tag:
        raise UpdateError("could not reach the update server (network error or GitHub API unavailable)")
    version = tag.lstrip("vV")
    asset = _find_installer_asset(data)
    if not asset:
        raise NoAssetHostedError(
            f"Scriptly PC {version} is available, but the installer isn't hosted here yet - "
            f"check https://github.com/{REPO}/releases for how to get it."
        )
    staged = _STAGED.get(version)
    if staged and Path(staged).exists() and not verify_installer_file(Path(staged), asset["size"], asset["sha256"]):
        return {"version": version, "installer_path": Path(staged), "url": data.get("html_url", "")}
    path = download_installer(asset, on_progress=on_progress)
    _STAGED[version] = str(path)
    return {"version": version, "installer_path": path, "url": data.get("html_url", "")}


def pending_installer() -> tuple | None:
    """(version, path) of the newest verified installer staged this session, if its
    file still exists and is newer than the running version; else None."""
    best = None
    for version, p in _STAGED.items():
        if Path(p).exists() and is_newer(version, VERSION):
            if best is None or _parse_version(version) > _parse_version(best[0]):
                best = (version, Path(p))
    return best


def install_pending() -> bool:
    """Launches the staged installer (UAC prompt if needed). True if it started."""
    pend = pending_installer()
    if not pend:
        return False
    ok = launch_silent_installer(pend[1])
    if ok:
        _STAGED.pop(pend[0], None)
    return ok


def perform_self_update(on_progress=None) -> Path:
    """Blocking end-to-end: stage_update + launch. Raises UpdateError subclasses on
    failure (UpdateLaunchError when the installer could not start)."""
    staged = stage_update(on_progress)
    if not launch_silent_installer(staged["installer_path"]):
        raise UpdateLaunchError("could not start the installer (administrator approval was declined or blocked)")
    _STAGED.pop(staged["version"], None)
    return staged["installer_path"]


def start_periodic_checks(get_config, on_update_available,
                          first_delay: float = FIRST_CHECK_DELAY_SECONDS,
                          interval: float = CHECK_INTERVAL_SECONDS):
    """Daemon thread: first check shortly after launch, then every `interval`
    seconds. `get_config()` is read on each tick so the Settings toggle takes effect
    live. `on_update_available(version, url, asset)` runs on the worker thread - hop
    to the UI thread inside it. Returns the thread; stop_periodic_checks() ends it."""
    def worker():
        if _stop_event.wait(first_delay):
            return
        while True:
            try:
                if get_config().get("check_for_updates_enabled", True):
                    result = check_for_update_sync()
                    if result:
                        logger.info("update available: %s (current: %s)", result["version"], VERSION)
                        on_update_available(result["version"], result["url"], result.get("asset"))
                    else:
                        logger.info("update check: already on latest version (%s)", VERSION)
            except Exception:  # noqa: BLE001
                logger.exception("unexpected error during update check")
            if _stop_event.wait(interval):
                return

    th = threading.Thread(target=worker, daemon=True, name="ScriptlyUpdateCheck")
    th.start()
    return th


def stop_periodic_checks() -> None:
    _stop_event.set()


def notify_update_via_tray(tray, version: str, url: str) -> None:
    """Reuses the pystray balloon notification. Only notifies; clicking a balloon
    carries no callback, so the Settings page offers the manual route."""
    try:
        tray.icon.notify(t("update_available_body", version=version), t("update_available_title"))
    except Exception:
        logger.exception("could not show update-available tray notification")
