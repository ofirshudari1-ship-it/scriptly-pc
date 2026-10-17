"""ניהול הגדרות Scriptly - כל הנתונים (config/log/פגישות) נשמרים בתוך תיקיית האפליקציה עצמה,
כדי שהיא תישאר ניידת (אפשר להעביר את כל התיקייה למקום אחר בלי לשבור כלום)."""
import json
import sys
from pathlib import Path

APP_NAME = "Scriptly PC"

# Config schema version. Bump only together with a migration in migrate_config().
SETTINGS_VERSION = 2

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
    # CPU/int8 by default - matches the default (non -IncludeGPU) build, which
    # doesn't bundle the ~1.8GB CUDA/cuDNN runtime. A user who built or obtained
    # the GPU variant can switch this to cuda/float16 in Settings; the engine
    # already falls back to cpu/int8 automatically either way if cuda fails to
    # load (app/transcribe.py), so this is a "start correct" default, not a
    # capability change.
    "whisper_device": "cpu",
    "whisper_compute_type": "int8",
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
    "ai_provider": "local",  # "local" (Ollama, offline) | "claude" (opt-in cloud analysis, app/claude_ai.py)
    "anthropic_api_key": "",  # user-supplied; ANTHROPIC_API_KEY env var is also honored
    "claude_model": "claude-sonnet-5",
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
    "auto_update_enabled": True,  # default ON: download+install a newer release when idle or on exit (app/update_checker.py); a later opt-out in Settings sticks (see settings_version)
    "settings_version": SETTINGS_VERSION,  # 2 = one-time migration that turned auto_update_enabled ON for configs saved while the default was still False
    "start_minimized_on_login": False,  # only takes effect on a Windows-startup launch (app/autostart.py passes --minimized), never on a manual launch - STANDARDS.md 12.1/12.3
    "recording_notification_style": "minimal",  # "off" | "minimal" | "verbose" - controls tray balloon notifications specifically for recording start/stop/auto-processing-done (see app/tray.py)
}


def migrate_config(data: dict) -> tuple:
    """Pure one-time migration of a saved config. Returns (data, changed).
    Configs written before settings_version 2 persisted auto_update_enabled=False
    (the old default), so flipping the default alone never reached existing users.
    Once migrated, settings_version is stored, so a later explicit opt-out sticks."""
    data = dict(data)
    try:
        saved_version = int(data.get("settings_version", 0))
    except (TypeError, ValueError):
        saved_version = 0
    if saved_version >= SETTINGS_VERSION:
        return data, False
    data["auto_update_enabled"] = True
    data["settings_version"] = SETTINGS_VERSION
    return data, True


def load_config() -> dict:
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULTS)
        return dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data, changed = migrate_config(data)
        merged = dict(DEFAULTS)
        merged.update(data)
        if changed:
            try:
                save_config(merged)
            except OSError:
                pass
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save_config(config: dict) -> None:
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def cuda_dll_dirs() -> list:
    """The two DLL directories CTranslate2 needs on its PATH for GPU acceleration
    to work, if this build/install bundles them at all (the -IncludeGPU variant).
    Single source of truth for the lookup path, shared by transcribe.py's actual
    DLL-dir registration and diagnostics.py's GPU check, so the two can never
    silently disagree about where to look."""
    if getattr(sys, "frozen", False):
        base = RESOURCE_ROOT
    else:
        base = Path(sys.prefix) / "Lib" / "site-packages"  # matches an activated venv's own site-packages
    return [base / "nvidia" / "cublas" / "bin", base / "nvidia" / "cudnn" / "bin"]


def has_bundled_cuda_runtime() -> bool:
    """Whether this specific build/install actually contains the CUDA/cuDNN DLLs,
    as opposed to whether the machine merely has an NVIDIA GPU (a separate
    question - see app/diagnostics.py:check_gpu, which checks nvidia-smi)."""
    return all(d.is_dir() for d in cuda_dll_dirs())
