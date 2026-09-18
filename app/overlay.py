"""סרגל צף שנשאר תמיד למעלה (נגרר לכל מקום על המסך) - במצב מנוחה מציג כפתור הקלטה קטן,
ובזמן הקלטה הופך ל-HUD עם טיימר וכפתור עצירה. כדי שאפשר יהיה להתחיל/לעצור הקלטה בקליק אחד
בלי לפתוח את הדשבורד ובלי לזכור קיצור מקלדת."""
import time

import customtkinter as ctk

from . import i18n
from .i18n import t

NAVY = "#1a2b4c"
NAVY_LIGHT = "#33487a"
# Darkened from the original #e04040 - white button text on top of it only
# reached 4.22:1 (below WCAG AA's 4.5:1 for this button's default/small font
# size), same class of issue as the C["red"] fix in dashboard.py.
RED = "#db2424"
RED_DARK = "#b81f1f"
TEAL = "#00b8ae"
TEAL_DARK = "#009991"


class RecordingOverlay:
    def __init__(self, root, controller):
        self.controller = controller
        self._recording_since = None
        self._blink_on = True

        self.win = ctk.CTkToplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(fg_color=NAVY)

        self.frame = ctk.CTkFrame(self.win, fg_color=NAVY, corner_radius=14)
        self.frame.pack(padx=2, pady=2)

        self._drag_offset = (0, 0)
        for widget in (self.win, self.frame):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)

        # --- מצב מנוחה: כפתור הקלטה קטן ---
        # RTL: every .pack(side=...) in this bar uses i18n.pack_side() instead of a
        # hardcoded "left", so the whole row visually mirrors for Hebrew (dot/button/
        # mic appear right-to-left instead of left-to-right) - a floating HUD bar like
        # this reads as one visual unit, so packing order matters more here than
        # per-widget text justification.
        self.idle_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        idle_dot = ctk.CTkLabel(self.idle_frame, text="●", text_color=TEAL, font=ctk.CTkFont(size=13))
        idle_dot.pack(side=i18n.pack_side(), padx=(12, 2), pady=8)
        for w in (self.idle_frame, idle_dot):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
        ctk.CTkButton(
            self.idle_frame,
            text="⏺ " + t("overlay_record"),
            width=100,
            height=26,
            fg_color=TEAL,
            hover_color=TEAL_DARK,
            text_color="#062824",
            command=controller.start_recording,
        ).pack(side=i18n.pack_side(), padx=(2, 4), pady=6)

        self.mic_btn_idle = ctk.CTkButton(
            self.idle_frame, text="🎤", width=32, height=26, fg_color=NAVY_LIGHT, hover_color="#3f5a95",
            command=self._toggle_voice_arm,
        )
        self.mic_btn_idle.pack(side=i18n.pack_side(), padx=(0, 10), pady=6)

        # --- מצב הקלטה: HUD עם טיימר ועצירה ---
        self.rec_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.dot = ctk.CTkLabel(self.rec_frame, text="●", text_color=RED, font=ctk.CTkFont(size=14))
        self.dot.pack(side=i18n.pack_side(), padx=(14, 4), pady=10)

        self.label = ctk.CTkLabel(
            self.rec_frame, text=t("status_recording"), text_color="white", font=ctk.CTkFont(size=12, weight="bold")
        )
        self.label.pack(side=i18n.pack_side(), padx=4)

        self.timer_label = ctk.CTkLabel(self.rec_frame, text="00:00", text_color="#c8d3e6", font=ctk.CTkFont(size=12))
        self.timer_label.pack(side=i18n.pack_side(), padx=8)

        ctk.CTkButton(
            self.rec_frame,
            text="⏹ " + t("overlay_stop"),
            width=80,
            height=28,
            fg_color=RED,
            hover_color=RED_DARK,
            text_color="white",
            command=controller.stop_recording,
        ).pack(side=i18n.pack_side(), padx=6, pady=6)

        self.mic_btn_rec = ctk.CTkButton(
            self.rec_frame, text="🎤", width=32, height=28, fg_color=NAVY_LIGHT, hover_color="#3f5a95",
            command=self._toggle_voice_arm,
        )
        self.mic_btn_rec.pack(side=i18n.pack_side(), padx=(0, 6), pady=6)

        ctk.CTkButton(
            self.rec_frame,
            text=t("overlay_continue"),
            width=130,
            height=28,
            fg_color=NAVY_LIGHT,
            hover_color="#3f5a95",
            command=self.hide,
        ).pack(side=i18n.pack_side(), padx=(0, 12), pady=6)

        controller.add_listener(self._on_event)
        self._sync_idle_visibility()
        self._sync_voice_buttons()

    def _start_drag(self, event):
        self._drag_offset = (event.x, event.y)

    def _on_drag(self, event):
        x = self.win.winfo_pointerx() - self._drag_offset[0]
        y = self.win.winfo_pointery() - self._drag_offset[1]
        self.win.geometry(f"+{x}+{y}")

    def _place_bottom_right(self):
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        self.win.geometry(f"+{sw - w - 24}+{sh - h - 90}")

    def show_idle(self):
        self.rec_frame.pack_forget()
        self.idle_frame.pack()
        self._place_bottom_right()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)

    def show_recording(self):
        self.idle_frame.pack_forget()
        self.rec_frame.pack()
        self._place_bottom_right()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)

    def hide(self):
        self.win.withdraw()

    def _sync_idle_visibility(self):
        """מציג/מסתיר את כפתור ההקלטה הצף במצב מנוחה, לפי ההגדרה (דלוק כברירת מחדל)."""
        if self._recording_since is not None:
            return
        if self.controller.config.get("floating_launcher", True):
            self.show_idle()
        else:
            self.hide()

    def _sync_voice_buttons(self):
        enabled = self.controller.config.get("voice_commands", False)
        for btn in (self.mic_btn_idle, self.mic_btn_rec):
            if enabled:
                btn.pack(side=i18n.pack_side(), padx=(0, 6), pady=6)
            else:
                btn.pack_forget()
        self._render_voice_state()

    def _render_voice_state(self):
        armed = self.controller.voice_armed
        for btn in (self.mic_btn_idle, self.mic_btn_rec):
            if armed:
                btn.configure(text="🔴", fg_color=RED, hover_color=RED_DARK)
            else:
                btn.configure(text="🎤", fg_color=NAVY_LIGHT, hover_color="#3f5a95")

    def _toggle_voice_arm(self):
        if self.controller.voice_armed:
            self.controller.disarm_voice_command()
        else:
            self.controller.arm_voice_command()

    def _on_event(self, event, payload):
        self.win.after(0, lambda: self._handle(event))

    def _handle(self, event):
        if event == "recording_started":
            self._recording_since = time.time()
            self.show_recording()
            self._tick()
        elif event == "recording_stopped":
            self._recording_since = None
            self._sync_idle_visibility()
        elif event == "config_reloaded":
            self._sync_idle_visibility()
            self._sync_voice_buttons()
        elif event in ("voice_armed", "voice_disarmed"):
            self._render_voice_state()

    def _tick(self):
        if self._recording_since is None:
            return
        elapsed = int(time.time() - self._recording_since)
        self.timer_label.configure(text=f"{elapsed // 60:02d}:{elapsed % 60:02d}")
        self._blink_on = not self._blink_on
        self.dot.configure(text_color=RED if self._blink_on else "#7a3030")
        self.win.after(500, self._tick)
