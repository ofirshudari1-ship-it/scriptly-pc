"""ניהול הגדרות Scriptly - כל הנתונים (config/log/פגישות) נשמרים בתוך תיקיית האפליקציה עצמה,
כדי שהיא תישאר ניידת (אפשר להעביר את כל התיקייה למקום אחר בלי לשבור כלום)."""
import json
import sys
from pathlib import Path

APP_NAME = "Scriptly PC"

# PROJECT_ROOT is where user data lives (data/, Meetings/) - always next to the
# .exe itself, so the whole app folder stays portable/movable.
# RESOURCE_ROOT is where *bundled read-only* files live (locales/, version.json,
# assets/) - PyInstaller's onedir mode puts these under an `_internal/`
# subfolder (sys._MEIPASS), not beside the exe, so the two must not be conflated.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    RESOURCE_ROOT = PROJECT_ROOT


def _load_version_info() -> dict:
    """version.json is the single source of truth - injected everywhere else (window title,
    About screen, splash, installer filename) rather than duplicated as a literal."""
    try:
        with open(RESOURCE_ROOT / "version.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


_VERSION_INFO = _load_version_info()
VERSION = _VERSION_INFO.get("version", "0.0.0")
BUILD_DATE = _VERSION_INFO.get("build_date", "")

APPDATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = APPDATA_DIR / "config.json"
LOG_PATH = APPDATA_DIR / "scriptly.log"

DEFAULT_MEETINGS_DIR = PROJECT_ROOT / "Meetings"

DEFAULTS = {
    "hotkey": "ctrl+alt+m",
    "meetings_dir": str(DEFAULT_MEETINGS_DIR),
    "keep_audio": False,
    "whisper_model": "ivrit-ai/whisper-large-v3-turbo-ct2",
    "whisper_device": "cuda",
    "whisper_compute_type": "float16",
    "ollama_model": "aya-expanse:8b",
    "ollama_url": "http://localhost:11434",
    "language": "he",
    "ui_language": "en",
    "auto_summarize": True,
    "mic_device_index": None,
    "onboarding_done": False,
    "appearance_mode": "system",
    "custom_vocabulary": "",
    "speaker_labels": True,
    "ai_titles": True,
    "ai_tags": True,
    "ui_scale": 1.0,
    "floating_launcher": True,
    "google_client_id": "",
    "google_client_secret": "",
    "voice_commands": False,
    "auto_save_recordings": True,
    "export_format": "docx",
    "notification_enabled": True,
    "min_recording_duration": 5,
    "max_file_size_gb": 10,
    "enable_analytics": False,  # opt-in by design (no analytics backend exists yet either way)
    "window_geometry": "",  # "WxH+X+Y" Tk geometry string, persisted across sessions; empty = use default
    "window_maximized": False,  # separate from window_geometry - Tk's "zoomed" state has no meaningful WxH+X+Y to save
    "tray_background_notice_shown": False,
    "hide_noise_recordings": False,  # see Meeting.likely_noise (app/meetings.py) - off by default so nothing is ever hidden without the user opting in
    "check_for_updates_enabled": True,  # startup GitHub-releases check (app/update_checker.py) - opt-out, not opt-in, since it's a read-only unauthenticated request with no user data involved
    "start_minimized_on_login": False,  # only takes effect on a Windows-startup launch (app/autostart.py passes --minimized), never on a manual launch - STANDARDS.md 12.1/12.3
    "recording_notification_style": "minimal",  # "off" | "minimal" | "verbose" - controls tray balloon notifications specifically for recording start/stop/auto-processing-done (see app/tray.py)
}


def load_config() -> dict:
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULTS)
        return dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save_config(config: dict) -> None:
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
