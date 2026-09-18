"""נקודת הכניסה של Scriptly - פותח את חלון הדשבורד + אייקון מגש המערכת + חלון צף בזמן הקלטה."""
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from . import i18n
from .config import load_config
from .controller import AppController
from .dashboard import Dashboard
from .i18n import t
from .logger import get_logger
from .onboarding import run_onboarding
from .overlay import RecordingOverlay
from .single_instance import acquire
from .splash import SplashScreen
from .tray import TrayIcon

logger = get_logger(__name__)


def _show_already_running_message():
    try:
        i18n.set_language(load_config().get("ui_language", "en"))
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(t("app_title"), t("already_running"))
        root.destroy()
    except Exception:
        pass


def _set_dpi_awareness():
    """Must run before any Tk window is created, or Windows scales the whole UI as a
    blurry bitmap at 125%/150%/200% display scaling instead of rendering it natively."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # older Windows fallback
        except Exception:
            pass


def _register_hotkey(controller):
    try:
        import keyboard

        keyboard.add_hotkey(controller.config["hotkey"], controller.toggle_recording)
        logger.info("registered global hotkey: %s", controller.config["hotkey"])
    except Exception as exc:
        logger.warning("could not register global hotkey %s: %s", controller.config["hotkey"], exc)


def main():
    _set_dpi_awareness()

    if sys.platform == "win32" and not acquire():
        logger.warning("Scriptly is already running - exiting this instance")
        _show_already_running_message()
        return

    logger.info("Scriptly starting...")

    # Set the language before the splash appears so its status text (and any
    # error dialog shown before the dashboard exists) is already in the
    # user's chosen language, not a hardcoded English placeholder.
    i18n.set_language(load_config().get("ui_language", "en"))

    splash = SplashScreen()
    splash.set_status(t("splash_status_config"))

    controller = AppController()

    splash.set_status(t("splash_status_ui"))

    import customtkinter as ctk

    ctk.set_widget_scaling(controller.config.get("ui_scale", 1.0))

    splash.close()

    root = ctk.CTk()
    dashboard = Dashboard(root, controller)
    overlay = RecordingOverlay(root, controller)

    def quit_everything():
        try:
            tray.stop()
        except Exception:
            pass
        root.quit()

    tray = TrayIcon(
        controller,
        on_show=lambda: root.after(0, dashboard.show),
        on_quit=lambda: root.after(0, quit_everything),
    )
    root.bind("<<ScriptlyQuit>>", lambda e: quit_everything())

    threading.Thread(target=tray.run, daemon=True).start()

    _register_hotkey(controller)

    if not controller.config.get("onboarding_done", False):
        hotkey_before_onboarding = controller.config["hotkey"]

        def on_onboarding_finished(hotkey_changed):
            if hotkey_changed:
                try:
                    import keyboard

                    keyboard.remove_hotkey(hotkey_before_onboarding)
                except Exception:
                    pass
                _register_hotkey(controller)
            dashboard.hint_label.configure(text=t("hotkey_hint", hotkey=controller.config["hotkey"]))

        root.after(400, lambda: run_onboarding(root, controller, on_onboarding_finished))

    root.mainloop()
    logger.info("Scriptly shut down")


if __name__ == "__main__":
    main()
