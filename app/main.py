"""נקודת הכניסה של Scriptly - פותח את חלון הדשבורד + אייקון מגש המערכת + חלון צף בזמן הקלטה."""
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from . import autostart, i18n
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
from . import update_checker

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
    # STANDARDS.md §19.3: the main window must be created hidden and only
    # shown once its content is actually built - otherwise Tk maps the
    # window immediately on creation and the user sees a blank/gray frame
    # flash before Dashboard finishes laying out its widgets.
    root.withdraw()
    dashboard = Dashboard(root, controller)
    overlay = RecordingOverlay(root, controller)

    # "--minimized" is only ever appended by our own Windows-startup Run-key entry
    # (app/autostart.py) when the user opted into "start minimized on login" in
    # Settings - never present on a manual launch (Start Menu/desktop shortcut),
    # so this never overrides the "first launch = visible window" default
    # (STANDARDS.md 12.1). It still shows the one-time tray background notice via
    # dashboard.hide(), so the user isn't left wondering where the window went.
    # Skip the deiconify below in that case so the window never flashes visible
    # for a frame before immediately being withdrawn again.
    start_minimized = autostart.MINIMIZED_FLAG in sys.argv[1:]
    if start_minimized:
        root.after(0, dashboard.hide)
    else:
        root.deiconify()

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

    def on_update_available(version, url, asset):
        # Called from the background update-check thread - hop back to the Tk
        # thread before touching any UI (pystray's own icon is thread-safe for
        # notify(), but keep this consistent with the rest of the codebase).
        root.after(0, lambda: update_checker.notify_update_via_tray(tray, version, url))

        if not controller.config.get("auto_update_enabled", False) or not asset:
            # Either the user hasn't opted into silent auto-update, or (today's
            # actual state) GitHub reports the release but nothing is attached
            # to download yet - either way, the tray notification above is all
            # that happens; the user updates manually from Settings/the release page.
            return

        def auto_update_worker():
            try:
                update_checker.perform_self_update()
            except Exception:
                logger.exception("automatic update download/install failed")
                return

            def maybe_quit_and_relaunch():
                if controller.is_recording:
                    # Never interrupt a live recording, even for an opted-in
                    # silent update - the downloaded installer just sits in
                    # temp and gets picked up again on the next update check.
                    logger.info("auto-update downloaded but a recording is in progress - deferring restart")
                    return
                logger.info("auto-update downloaded - quitting to install v%s", version)
                quit_everything()

            root.after(0, maybe_quit_and_relaunch)

        threading.Thread(target=auto_update_worker, daemon=True, name="ScriptlyAutoUpdate").start()

    # A few seconds after launch, not on startup itself, so the update check never
    # competes with the app actually becoming usable. Non-blocking: the real work
    # happens on a background thread (see update_checker.check_for_updates_async).
    root.after(5000, lambda: update_checker.check_for_updates_async(controller.config, on_update_available))

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
