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

    update_state = {"declined": False, "staging": False, "notified": set()}

    def quit_everything(install_pending_update=True):
        # On exit: if a verified update was already downloaded and the user
        # hasn't declined its UAC prompt this session, install it now (silent,
        # relaunches Scriptly PC afterwards). Never while a recording is running.
        if (install_pending_update and controller.config.get("auto_update_enabled", True)
                and not update_state["declined"] and not controller.is_recording):
            try:
                if update_checker.pending_installer():
                    logger.info("installing downloaded update on exit")
                    update_checker.install_pending()
            except Exception:
                logger.exception("installing the pending update on exit failed")
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
    root.bind("<<ScriptlyQuitNoUpdate>>", lambda e: quit_everything(install_pending_update=False))

    threading.Thread(target=tray.run, daemon=True).start()

    _register_hotkey(controller)

    def install_update_when_idle():
        # UI thread. Installs a downloaded update as soon as nothing is recording;
        # re-checks every minute while a recording is running.
        if update_state["declined"] or not update_checker.pending_installer():
            return
        if not controller.config.get("auto_update_enabled", True):
            return
        if controller.is_recording:
            root.after(60000, install_update_when_idle)
            return
        if update_checker.install_pending():
            logger.info("auto-update launched - quitting so the installer can replace the app")
            quit_everything(install_pending_update=False)
        else:
            # UAC declined / installer blocked: keep running, don't nag again this session.
            update_state["declined"] = True
            logger.info("auto-update installer was not started - will not ask again this session")

    def on_update_available(version, url, asset):
        # Called from the background update-check thread (first check shortly after
        # launch, then every ~6h) - hop back to the Tk thread before touching any UI.
        if version not in update_state["notified"]:
            update_state["notified"].add(version)
            root.after(0, lambda: update_checker.notify_update_via_tray(tray, version, url))

        if (not controller.config.get("auto_update_enabled", True) or not asset
                or update_state["declined"] or update_state["staging"]):
            return
        update_state["staging"] = True
        try:
            update_checker.stage_update()
        except Exception:
            logger.exception("automatic update download failed")
            return
        finally:
            update_state["staging"] = False
        root.after(0, install_update_when_idle)

    # A few seconds after launch, then every ~6 hours, on a background thread so the
    # check never competes with the app becoming usable. Leftover installers from
    # earlier self-updates are removed from %TEMP% first.
    update_checker.cleanup_stale_downloads()
    update_checker.start_periodic_checks(lambda: controller.config, on_update_available)

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
