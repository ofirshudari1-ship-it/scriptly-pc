"""ניהול הפעלה אוטומטית עם Windows דרך מפתח ה-Run של המשתמש הנוכחי ברגיסטרי."""
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Scriptly PC"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # מצב פיתוח: מריצים את run.pyw דרך ה-pythonw של ה-venv כדי שלא ייפתח חלון קונסולה
    project_root = Path(__file__).resolve().parent.parent
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{project_root / "run.pyw"}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
