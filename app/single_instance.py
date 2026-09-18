"""מונע הרצה כפולה של Scriptly באמצעות Mutex ברמת מערכת ההפעלה."""
import ctypes

_MUTEX_NAME = "Global\\ScriptlyPC_SingleInstance_Mutex"
_handle = None

ERROR_ALREADY_EXISTS = 183


def acquire() -> bool:
    """מנסה לתפוס את ה-mutex. מחזיר False אם כבר יש עותק פעיל של Scriptly."""
    global _handle
    _handle = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    return last_error != ERROR_ALREADY_EXISTS
