"""ניהול הפעלה אוטומטית עם Windows דרך מפתח ה-Run של המשתמש הנוכחי ברגיסטרי."""
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Scriptly PC"


# Passed to the exe only on a Windows-startup launch registered via this module -
# app/main.py checks for it to decide whether to withdraw the window right after
# creating it (STANDARDS.md 12.1: start minimized only on explicit opt-in, never
# on a manual launch, so this flag is never part of a desktop/Start-Menu shortcut).
MINIMIZED_FLAG = "--minimized"


def _launch_command(minimized: bool = False) -> str:
    suffix = f" {MINIMIZED_FLAG}" if minimized else ""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"{suffix}'
    # מצב פיתוח: מריצים את run.pyw דרך ה-pythonw של ה-venv כדי שלא ייפתח חלון קונסולה
    project_root = Path(__file__).resolve().parent.parent
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{project_root / "run.pyw"}"{suffix}'


def is_enabled() -> bool:
    """Always reads the live registry value rather than trusting a cached config
    flag - the user (or another installer/uninstaller) can change the Run key
    outside the app, so the checkbox in Settings must reflect reality, not memory."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool, minimized: bool = False) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _launch_command(minimized))
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
