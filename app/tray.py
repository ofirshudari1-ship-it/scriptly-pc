"""אייקון מגש המערכת - שכבה דקה מעל ה-controller ומעל חלון הדשבורד.

לחיצה על האייקון פותחת/מציגה את הדשבורד (זה הממשק הראשי של האפליקציה).
תפריט לחיצה ימנית מאפשר גם התחלה/עצירה מהירה של הקלטה בלי לפתוח חלון.
"""
import subprocess

import pystray
from PIL import Image

from .config import RESOURCE_ROOT
from .i18n import t
from .logger import get_logger

logger = get_logger(__name__)

ASSETS_DIR = RESOURCE_ROOT / "assets"


class TrayIcon:
    def __init__(self, controller, on_show, on_quit):
        self.controller = controller
        self.on_show = on_show
        self.on_quit = on_quit
        self.icon_idle = Image.open(ASSETS_DIR / "icon_idle.png")
        self.icon_recording = Image.open(ASSETS_DIR / "icon_recording.png")
        self.icon = pystray.Icon(
            "Scriptly",
            self.icon_idle,
            f"{t('app_title')} - {t('status_ready')}",
            menu=self._build_menu(),
        )
        controller.add_listener(self._on_event)

    def _build_menu(self):
        # `default=True` controls what a left-click on the icon itself does -
        # per STANDARDS.md 12.2 that must stay "open the main window", not the
        # right-click menu's visual order. The *menu* order (separate concern,
        # same section) puts the most-used action (toggle recording) first,
        # separator, secondary open/settings actions, separator, Quit last and
        # set apart so it can't be clicked by accident.
        return pystray.Menu(
            pystray.MenuItem(self._toggle_label, self._toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("tray_open_dashboard"), self._show, default=True),
            pystray.MenuItem(t("tray_open_folder"), self._open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("tray_quit"), self._quit),
        )

    def _toggle_label(self, item):
        return t("tray_stop") if self.controller.is_recording else t("tray_start")

    def _show(self, icon=None, item=None):
        self.on_show()

    def _toggle(self, icon=None, item=None):
        self.controller.toggle_recording()

    def _open_folder(self, icon=None, item=None):
        folder = self.controller.meetings_dir
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    def _quit(self, icon=None, item=None):
        self.on_quit()

    def _recording_notifications_enabled(self) -> bool:
        """Governs only the recording start/stop/auto-processing-done balloons (that's what
        "Show desktop notifications after recording & processing" in Settings actually says it
        controls) - never errors or the one-time "still running in the background" notice, which
        are safety/orientation messages, not routine recording-workflow noise."""
        return self.controller.config.get("notification_enabled", True)

    def _recording_style(self) -> str:
        """"off" | "minimal" | "verbose" - see config.DEFAULTS["recording_notification_style"]."""
        return self.controller.config.get("recording_notification_style", "minimal")

    def _on_event(self, event, payload):
        try:
            if event == "recording_started":
                self.icon.icon = self.icon_recording
                self.icon.title = f"{t('app_title')} - {t('status_recording')}"
                if self._recording_notifications_enabled() and self._recording_style() == "verbose":
                    self.icon.notify(t("status_recording"), t("app_title"))
            elif event == "recording_stopped":
                self.icon.icon = self.icon_idle
                self.icon.title = f"{t('app_title')} - {t('status_ready')}"
                if self._recording_notifications_enabled() and self._recording_style() in ("minimal", "verbose"):
                    self.icon.notify(t("status_ready"), t("app_title"))
            elif event == "processing_done":
                if self._recording_notifications_enabled() and self._recording_style() in ("minimal", "verbose"):
                    self.icon.notify(t("processing_done_msg"), t("app_title"))
            elif event == "error":
                # Always shown regardless of the recording-notifications toggle - an error is
                # actionable information, not routine start/stop/done noise.
                self.icon.notify(payload.get("message", "Error"), t("app_title"))
            elif event == "tray_background_notice":
                # Always shown (one-time only, see dashboard.hide()) - STANDARDS.md 12.1 requires
                # this explanation regardless of notification preferences, or users conclude the
                # app quit instead of realizing it's still running in the background.
                self.icon.notify(payload.get("message", t("tray_background_notice")), t("app_title"))
        except Exception:
            logger.exception("tray event handling failed for %s", event)

    def run(self):
        self.icon.run()

    def stop(self):
        self.icon.stop()
