"""חלון הדשבורד הראשי של Scriptly - ממשק מודרני (CustomTkinter) עם תמיכה במצב כהה/בהיר,
ברירת מחדל אנגלית עם החלפה לעברית."""
import re
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from . import audio_devices, audio_player, autostart, diagnostics, google_integration, i18n
from .config import BUILD_DATE, PROJECT_ROOT, RESOURCE_ROOT, VERSION, save_config
from .export import DIGEST_EXPORT_EXTENSIONS, EXPORT_EXTENSIONS, export_digest, export_meeting, export_meeting_srt
from .i18n import t
from .logger import get_logger
from .meetings import list_meetings
from .stats import compute_daily_trend, compute_stats, compute_talk_ratio, compute_tone_breakdown, compute_top_tags, format_duration

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

logger = get_logger(__name__)

ASSETS_DIR = RESOURCE_ROOT / "assets"

# כל צבע הוא tuple (light, dark) - customtkinter עובר ביניהם אוטומטית לפי appearance mode.
C = {
    "bg": ("#f1f4f9", "#12151c"),
    "card": ("#ffffff", "#1b1f29"),
    "card_hover": ("#eef2f8", "#242938"),
    "card_selected": ("#e3f7f6", "#0f3a37"),
    "border": ("#e4e8f0", "#2a2f3d"),
    "header": ("#152847", "#0c1424"),
    "header_alt": ("#213960", "#16233d"),
    "text": ("#161d2b", "#e9edf5"),
    "text_soft": ("#66707f", "#8b93a5"),
    "input": ("#f5f7fb", "#242938"),
    "teal": ("#00b8ae", "#12c9bd"),
    # Same brand hue, darkened for use as *text* on the light background - the
    # base "teal" only clears WCAG AA (4.5:1) as a button fill with dark text
    # on top of it (see #062824 usage), not as foreground text on #f1f4f9
    # (was 2.25:1 - a real accessibility fail, STANDARDS.md 14.3). Dark mode's
    # value already passes AA as text (8.80:1) so it's reused unchanged.
    "teal_text": ("#00706a", "#12c9bd"),
    "teal_hover": ("#009a92", "#0eab9f"),
    # Darkened from the original #e34848/#f0574f so white button text on top of
    # it clears WCAG AA (4.5:1) - the original only reached 3.4-3.97:1 with
    # white text at the "Stop Recording" button's 13pt-bold size (STANDARDS.md
    # 14.3; doesn't qualify for the large-text 3:1 exception, which needs 14pt
    # bold minimum). Use for fills that carry light/white text on top.
    "red": ("#b11b1b", "#cf1b12"),
    "red_hover": ("#8f1515", "#b8170f"),
    # Original brighter red, kept for use as *text* directly on a surface
    # (error banners/labels) - there it already passes AA on both themes; the
    # darker "red" above would be too dark to read comfortably on the near-
    # black dark-mode background if reused for text there.
    "red_text": ("#b11b1b", "#f0574f"),
    "amber": ("#e2a52a", "#f0b93c"),
    "green": ("#1caa6b", "#2bc27f"),
    "chip_bg": ("#eef2f8", "#242938"),
}

FONT = "Segoe UI"


def _img(name, size):
    return ctk.CTkImage(Image.open(ASSETS_DIR / name), size=size)


class Dashboard:
    def __init__(self, root: ctk.CTk, controller):
        self.root = root
        self.controller = controller
        self._meetings = []
        self._selected_index = None
        self._recording_since = None
        self._blink_on = True
        self._processing_dirs = set()
        self.player = audio_player.SimplePlayer()
        self._playing_dir = None
        self._play_after_id = None
        self._geometry_save_after_id = None

        i18n.set_language(controller.config.get("ui_language", "en"))
        ctk.set_appearance_mode(controller.config.get("appearance_mode", "system"))
        ctk.set_default_color_theme("blue")

        root.title(f"{t('app_title')} v{VERSION}")
        root.geometry(self._restorable_geometry())
        root.minsize(860, 520)
        root.configure(fg_color=C["bg"])
        try:
            root.iconbitmap(str(ASSETS_DIR / "icon_idle.ico"))
        except Exception:
            pass

        self.logo_img = _img("icon_idle.png", (30, 30))

        self.container = ctk.CTkFrame(root, fg_color=C["bg"], corner_radius=0)
        self.container.pack(fill="both", expand=True)

        self._build_layout()

        root.protocol("WM_DELETE_WINDOW", self.hide)
        root.bind("<Configure>", self._on_configure)
        controller.add_listener(self._on_controller_event)

        self.refresh_meetings()
        self._tick()

    def _anchor(self):
        return "e" if i18n.get_language() == "he" else "w"

    def _justify(self):
        return "right" if i18n.get_language() == "he" else "left"

    # ---------- window geometry persistence (size/position, not tray state) ----------

    _DEFAULT_GEOMETRY = "1080x680"

    def _restorable_geometry(self) -> str:
        """Restore last window size/position if it still fits on a currently-connected
        screen; otherwise fall back to the default centered size. We deliberately never
        persist "started minimized to tray" as a launch state (see hide()/quit_app()) -
        this only ever restores size+position of a *visible* window."""
        saved = self.controller.config.get("window_geometry", "")
        if not saved:
            return self._DEFAULT_GEOMETRY
        try:
            size_part, x_str, y_str = saved.split("+")
            w, h = (int(v) for v in size_part.split("x"))
            x, y = int(x_str), int(y_str)
        except (ValueError, AttributeError):
            return self._DEFAULT_GEOMETRY

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if w < 200 or h < 200 or x < -50 or y < -50 or x > screen_w - 100 or y > screen_h - 100:
            return self._DEFAULT_GEOMETRY
        return saved

    def _on_configure(self, event):
        if event.widget is not self.root:
            return
        # Debounce: only persist once movement/resize has settled, not on every pixel.
        if self._geometry_save_after_id:
            self.root.after_cancel(self._geometry_save_after_id)
        self._geometry_save_after_id = self.root.after(600, self._save_geometry)

    def _save_geometry(self):
        self._geometry_save_after_id = None
        if self.root.state() != "normal":
            return  # don't persist a maximized/withdrawn geometry string
        self.controller.config["window_geometry"] = self.root.geometry()
        save_config(self.controller.config)

    def _is_dark(self) -> bool:
        return ctk.get_appearance_mode() == "Dark"

    def _color(self, key: str) -> str:
        """ערך צבע בודד (light/dark) עבור ווידג'טים גולמיים של tkinter (כמו Canvas) שלא יודעים לפרש tuple."""
        value = C[key]
        return value[1] if self._is_dark() else value[0]

    # ---------- UI construction ----------

    def rebuild(self):
        for child in self.container.winfo_children():
            child.destroy()
        self.root.title(f"{t('app_title')} v{VERSION}")
        self._build_layout()
        self.refresh_meetings()

    def _build_layout(self):
        c = self.container

        # ---- header ----
        header = ctk.CTkFrame(c, fg_color=C["header"], corner_radius=0, height=78)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", padx=22)
        brand_row = ctk.CTkFrame(brand, fg_color="transparent")
        brand_row.pack(anchor="w")
        ctk.CTkLabel(brand_row, image=self.logo_img, text="").pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            brand_row, text=t("app_title"), font=ctk.CTkFont(family=FONT, size=21, weight="bold"), text_color="white"
        ).pack(side="left")
        self.hint_label = ctk.CTkLabel(
            brand,
            text=t("hotkey_hint", hotkey=self.controller.config["hotkey"]),
            font=ctk.CTkFont(family=FONT, size=11),
            text_color="#93a4c4",
        )
        self.hint_label.pack(anchor="w", padx=(38, 0))

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.pack(side="right", padx=22)

        icon_btn_style = dict(
            width=36, height=36, corner_radius=18, fg_color=C["header_alt"], hover_color="#33487a",
            font=ctk.CTkFont(size=16),
        )
        ctk.CTkButton(controls, text="⚙", command=self.open_settings, **icon_btn_style).pack(side="right", padx=(10, 0))
        self._menu_btn = ctk.CTkButton(controls, text="☰", command=self._show_menu, **icon_btn_style)
        self._menu_btn.pack(side="right", padx=(10, 0))

        status_box = ctk.CTkFrame(controls, fg_color="transparent")
        status_box.pack(side="right", padx=12)
        side1 = "left" if i18n.get_language() != "he" else "right"
        self.status_dot = ctk.CTkLabel(status_box, text="●", text_color=C["teal_text"], font=ctk.CTkFont(size=14))
        self.status_dot.pack(side=side1)
        self.status_label = ctk.CTkLabel(
            status_box, text=t("status_ready"), font=ctk.CTkFont(family=FONT, size=13, weight="bold"), text_color="white"
        )
        self.status_label.pack(side=side1, padx=6)
        self.timer_label = ctk.CTkLabel(status_box, text="", font=ctk.CTkFont(family=FONT, size=13), text_color="#c8d3e6")
        self.timer_label.pack(side=side1, padx=6)

        self.toggle_btn = ctk.CTkButton(
            controls,
            text="●  " + t("btn_start"),
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
            fg_color=C["teal"],
            hover_color=C["teal_hover"],
            text_color="#062824",
            corner_radius=18,
            height=36,
            width=170,
            command=self.controller.toggle_recording,
        )
        self.toggle_btn.pack(side="right")

        # ---- banner ----
        self.banner = ctk.CTkLabel(
            c, text="", font=ctk.CTkFont(family=FONT, size=12), text_color=C["text_soft"], anchor=self._anchor()
        )
        self.banner.pack(side="top", fill="x", padx=22, pady=(10, 0))

        # ---- body ----
        body = ctk.CTkFrame(c, fg_color=C["bg"])
        body.pack(side="top", fill="both", expand=True, padx=18, pady=14)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left_col = 1 if i18n.get_language() == "he" else 0
        right_col = 0 if i18n.get_language() == "he" else 1

        left = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=14, width=300, border_width=1, border_color=C["border"])
        left.grid(row=0, column=left_col, sticky="ns", padx=(0, 14) if left_col == 0 else (14, 0))
        left.grid_propagate(False)

        ctk.CTkLabel(
            left,
            text=t("meetings_header"),
            font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
            text_color=C["text"],
            anchor=self._anchor(),
        ).pack(fill="x", padx=16, pady=(16, 8))

        self.search_var = tk.StringVar(value="")
        self.search_var.trace_add("write", lambda *a: self._render_meeting_list())
        search_entry = ctk.CTkEntry(
            left, textvariable=self.search_var, placeholder_text=t("search_placeholder"),
            fg_color=C["input"], border_width=0, corner_radius=8, justify=self._justify(),
        )
        search_entry.pack(fill="x", padx=16, pady=(0, 10))

        # Local-only heuristic (Meeting.likely_noise, app/meetings.py) - off by default,
        # remembered per STANDARDS.md's "remembers last choices" rule. Reduces clutter in a
        # growing recordings list without ever deleting anything - the filter only hides.
        self.hide_noise_var = tk.BooleanVar(value=self.controller.config.get("hide_noise_recordings", False))
        ctk.CTkCheckBox(
            left, text=t("filter_hide_noise"), variable=self.hide_noise_var, command=self._on_toggle_hide_noise,
            font=ctk.CTkFont(family=FONT, size=11), text_color=C["text_soft"],
        ).pack(fill="x", padx=16, pady=(0, 10), anchor=self._anchor())

        self.meetings_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.meetings_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        right = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=14, border_width=1, border_color=C["border"])
        right.grid(row=0, column=right_col, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        tabs_bar = ctk.CTkFrame(right, fg_color="transparent")
        tabs_bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 0))

        self.view_mode = ctk.StringVar(value=t("tab_summary"))
        self.segmented = ctk.CTkSegmentedButton(
            tabs_bar,
            values=[t("tab_summary"), t("tab_transcript")],
            variable=self.view_mode,
            fg_color=C["chip_bg"],
            selected_color=C["teal"],
            selected_hover_color=C["teal_hover"],
            unselected_hover_color=C["card_hover"],
            text_color=C["text"],
            font=ctk.CTkFont(family=FONT, size=12),
            command=lambda _v: self._render_selected(),
        )
        self.segmented.pack(side="left" if i18n.get_language() != "he" else "right")

        chip_style = dict(
            height=30, corner_radius=10, fg_color=C["chip_bg"], text_color=C["text"],
            hover_color=C["card_hover"], font=ctk.CTkFont(family=FONT, size=12),
        )
        actions_side = "right" if i18n.get_language() != "he" else "left"

        self.more_btn = ctk.CTkButton(
            tabs_bar, text="⋯", width=36, command=self._show_detail_menu, **chip_style
        )
        self.more_btn.pack(side=actions_side, padx=(6, 0))

        self.tags_btn = ctk.CTkButton(
            tabs_bar, text="🏷", width=36, command=self._open_tags_notes_dialog, **chip_style
        )
        self.tags_btn.pack(side=actions_side, padx=(6, 0))

        self.play_btn = ctk.CTkButton(
            tabs_bar, text="▶  " + t("btn_play"), width=90, command=self._toggle_play, **chip_style
        )
        self.play_btn.pack(side=actions_side, padx=(6, 0))

        self.action_bar = ctk.CTkFrame(right, fg_color=("#fff4d9", "#3a3315"), corner_radius=10)
        self.action_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(12, 0))
        self.action_bar.grid_remove()

        self.action_label = ctk.CTkLabel(
            self.action_bar,
            text="",
            text_color=("#8a6d1f", "#e0c060"),
            anchor=self._anchor(),
            justify=self._justify(),
            font=ctk.CTkFont(family=FONT, size=12),
            wraplength=520,
        )
        self.action_label.pack(side="top", fill="x", padx=16, pady=(12, 4))

        self.summarize_now_btn = ctk.CTkButton(
            self.action_bar,
            text=t("btn_summarize_now"),
            corner_radius=10,
            fg_color=C["teal"],
            hover_color=C["teal_hover"],
            text_color="#062824",
            font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
            command=self._summarize_now,
        )
        self.summarize_now_btn.pack(side="top", padx=16, pady=(0, 12), anchor=self._anchor())

        text_frame = ctk.CTkFrame(right, fg_color=C["input"], corner_radius=10)
        text_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=16)

        text_bg, text_fg, header_fg = self._text_colors()
        self.text = tk.Text(
            text_frame,
            wrap="word",
            font=(FONT, 11),
            padx=16,
            pady=14,
            relief="flat",
            bd=0,
            bg=text_bg,
            fg=text_fg,
            insertbackground=text_fg,
            state="disabled",
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("header", font=(FONT, 13, "bold"), spacing3=6, foreground=header_fg)
        self.text.tag_configure("bold", font=(FONT, 11, "bold"))

    def _text_colors(self):
        if self._is_dark():
            return "#1b1f29", "#e9edf5", "#5fd6cd"
        return "#f5f7fb", "#161d2b", "#152847"

    # ---------- data / rendering ----------

    def _date_group(self, ts: datetime) -> str:
        today = datetime.now().date()
        d = ts.date()
        if d == today:
            return t("group_today")
        if d == today - timedelta(days=1):
            return t("group_yesterday")
        if d >= today - timedelta(days=7):
            return t("group_this_week")
        return t("group_earlier")

    def refresh_meetings(self, select_dir: Path = None):
        self._meetings_all = list_meetings(self.controller.meetings_dir)
        self._render_meeting_list(select_dir)

    def _on_toggle_hide_noise(self):
        self.controller.config["hide_noise_recordings"] = bool(self.hide_noise_var.get())
        save_config(self.controller.config)
        self._render_meeting_list()

    def _render_meeting_list(self, select_dir: Path = None):
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        hide_noise = self.controller.config.get("hide_noise_recordings", False)
        source = [m for m in self._meetings_all if not (hide_noise and m.likely_noise)]
        if query:
            self._meetings = [m for m in source if query in m.searchable_text]
        else:
            self._meetings = list(source)

        for child in self.meetings_scroll.winfo_children():
            child.destroy()

        if not self._meetings_all:
            self._selected_index = None
            empty = ctk.CTkFrame(self.meetings_scroll, fg_color="transparent")
            empty.pack(fill="both", expand=True, pady=40)
            ctk.CTkLabel(empty, text="🎙", font=ctk.CTkFont(size=32)).pack()
            ctk.CTkLabel(
                empty, text=t("no_meetings", hotkey=self.controller.config["hotkey"].upper()), text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=12),
                wraplength=230, justify="center",
            ).pack(pady=(8, 0))
            self._set_text("")
            return

        if not self._meetings and source != self._meetings_all and not query:
            # Every recording that exists got filtered out by the noise toggle (none by
            # search) - a distinct message from "no search results" so it's clear what to do.
            self._selected_index = None
            ctk.CTkLabel(
                self.meetings_scroll, text=t("all_filtered_as_noise"), text_color=C["text_soft"],
                font=ctk.CTkFont(family=FONT, size=12), wraplength=230, justify="center",
            ).pack(pady=30)
            self._set_text("")
            return

        if not self._meetings:
            ctk.CTkLabel(
                self.meetings_scroll, text=t("no_search_results"), text_color=C["text_soft"],
                font=ctk.CTkFont(family=FONT, size=12), wraplength=230, justify="center",
            ).pack(pady=30)
            self._set_text("")
            return

        target_index = 0
        if select_dir is not None:
            for i, m in enumerate(self._meetings):
                if m.dir == select_dir:
                    target_index = i
                    break

        self._row_widgets = []
        last_group = None
        for i, m in enumerate(self._meetings):
            group = self._date_group(m.timestamp)
            if group != last_group:
                ctk.CTkLabel(
                    self.meetings_scroll, text=group, font=ctk.CTkFont(family=FONT, size=10, weight="bold"),
                    text_color=C["text_soft"], anchor=self._anchor(),
                ).pack(fill="x", padx=6, pady=(10 if last_group else 0, 2))
                last_group = group

            outer = ctk.CTkFrame(self.meetings_scroll, fg_color=C["card"], corner_radius=10, cursor="hand2")
            outer.pack(fill="x", pady=4)
            outer.columnconfigure(1, weight=1)

            if m.dir in self._processing_dirs:
                accent, marker = C["amber"], "⏳"
            elif not m.has_summary and m.has_audio:
                accent, marker = C["text_soft"], "⏸"
            else:
                accent, marker = C["green"], "✓"

            bar = ctk.CTkFrame(outer, fg_color=accent, corner_radius=4, width=4)
            bar.grid(row=0, column=0, sticky="ns", padx=(6, 0), pady=6)

            inner = ctk.CTkFrame(outer, fg_color="transparent")
            inner.grid(row=0, column=1, sticky="ew", padx=(10, 12), pady=(8, 8))

            title_row = ctk.CTkFrame(inner, fg_color="transparent")
            title_row.pack(fill="x")
            ctk.CTkLabel(title_row, text=marker, font=ctk.CTkFont(size=11), text_color=accent).pack(
                side="left" if self._anchor() == "w" else "right"
            )
            title_lbl = ctk.CTkLabel(
                title_row,
                text=m.title,
                font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
                text_color=C["text"],
                anchor=self._anchor(),
                justify=self._justify(),
                wraplength=195,
            )
            title_lbl.pack(side="left" if self._anchor() == "w" else "right", padx=6, fill="x", expand=True)

            tone_lbl = None
            if m.tone in ("positive", "tense"):
                tone_color = C["green"] if m.tone == "positive" else C["amber"]
                tone_icon = "🙂" if m.tone == "positive" else "⚠"
                tone_lbl = ctk.CTkLabel(title_row, text=tone_icon, font=ctk.CTkFont(size=11), text_color=tone_color)
                tone_lbl.pack(side="left" if self._anchor() == "w" else "right", padx=(0, 4))

            datetime_lbl = None
            if m.ai_title:
                datetime_lbl = ctk.CTkLabel(
                    inner, text=m.datetime_label, font=ctk.CTkFont(family=FONT, size=10),
                    text_color=C["text_soft"], anchor=self._anchor(),
                )
                datetime_lbl.pack(fill="x", pady=(1, 0))

            preview_lbl = ctk.CTkLabel(
                inner,
                text=m.preview,
                font=ctk.CTkFont(family=FONT, size=11),
                text_color=C["text_soft"],
                anchor=self._anchor(),
                wraplength=220,
                justify=self._justify(),
            )
            preview_lbl.pack(fill="x", pady=(3, 0))

            noise_lbl = None
            if m.likely_noise:
                noise_lbl = ctk.CTkLabel(
                    inner, text=t("badge_likely_noise"), font=ctk.CTkFont(family=FONT, size=9),
                    text_color=C["text_soft"], anchor=self._anchor(),
                )
                noise_lbl.pack(fill="x", pady=(2, 0))

            row_widgets = [outer, inner, title_row, title_lbl, preview_lbl]
            if datetime_lbl is not None:
                row_widgets.append(datetime_lbl)
            if tone_lbl is not None:
                row_widgets.append(tone_lbl)
            if noise_lbl is not None:
                row_widgets.append(noise_lbl)
            for widget in row_widgets:
                widget.bind("<Button-1>", lambda e, idx=i: self._select_meeting(idx))
                widget.bind("<Enter>", lambda e, r=outer, idx=i: self._on_row_hover(r, idx, True))
                widget.bind("<Leave>", lambda e, r=outer, idx=i: self._on_row_hover(r, idx, False))

            self._row_widgets.append(outer)

        self._select_meeting(target_index)

    def _on_row_hover(self, row, idx, entering):
        if idx == self._selected_index:
            return
        row.configure(fg_color=C["card_hover"] if entering else C["card"])

    def _select_meeting(self, index):
        if index is None or index >= len(self._meetings):
            return
        if self._selected_index is not None and self._selected_index < len(self._row_widgets):
            self._row_widgets[self._selected_index].configure(fg_color=C["card"])
        self._selected_index = index
        self._row_widgets[index].configure(fg_color=C["card_selected"])
        meeting = self._meetings[index]
        if self._playing_dir is not None and self._playing_dir != meeting.dir:
            self._stop_playback()
        self._render_selected()

    def _selected_meeting(self):
        if self._selected_index is None or self._selected_index >= len(self._meetings):
            return None
        return self._meetings[self._selected_index]

    def _render_selected(self):
        meeting = self._selected_meeting()
        if meeting is None:
            return

        if meeting.has_audio:
            self.play_btn.configure(state="normal")
            if self._playing_dir == meeting.dir:
                # text_color must be set explicitly here - the default C["text"]
                # (dark navy in light mode) fails WCAG AA against this red fill
                # (2.44:1); white does not.
                self.play_btn.configure(
                    text="⏹  " + t("btn_stop_playback"), fg_color=C["red"], hover_color=C["red_hover"], text_color="white"
                )
            else:
                self.play_btn.configure(
                    text="▶  " + t("btn_play"), fg_color=C["chip_bg"], hover_color=C["card_hover"], text_color=C["text"]
                )
        else:
            self.play_btn.configure(state="disabled", text="▶  " + t("btn_play"), fg_color=C["chip_bg"], text_color=C["text_soft"])

        pending = not meeting.has_summary and meeting.has_audio and meeting.dir not in self._processing_dirs
        if pending:
            self.action_label.configure(text=t("pending_summarize_msg"))
            self.action_bar.grid()
        else:
            self.action_bar.grid_remove()

        if self.view_mode.get() == t("tab_summary"):
            if meeting.summary:
                content = meeting.summary
            elif meeting.dir in self._processing_dirs:
                content = t("processing_summary_placeholder")
            elif pending:
                content = ""
            else:
                content = t("no_summary")
            self._set_text(content, markdown=True)
        else:
            self._set_text(meeting.transcript or t("no_transcript"), markdown=False)

    def _summarize_now(self):
        meeting = self._selected_meeting()
        if meeting is not None:
            self.controller.summarize_meeting(meeting.dir)

    def _delete_selected(self):
        meeting = self._selected_meeting()
        if meeting is None:
            return
        if self._playing_dir == meeting.dir:
            self._stop_playback()
        if messagebox.askyesno(t("delete_confirm_title"), t("delete_confirm_body")):
            self.controller.delete_meeting(meeting.dir)

    def _toggle_play(self):
        meeting = self._selected_meeting()
        if meeting is None or not meeting.has_audio:
            return
        if self._playing_dir == meeting.dir:
            self._stop_playback()
            self._render_selected()
            return
        self.player.play(meeting.dir / "recording.wav")
        self._playing_dir = meeting.dir
        self._render_selected()
        duration_ms = max(1, int(meeting.duration_seconds * 1000)) + 400
        self._play_after_id = self.root.after(duration_ms, self._on_playback_finished)

    def _on_playback_finished(self):
        self._play_after_id = None
        self._playing_dir = None
        if self._selected_meeting() is not None:
            self._render_selected()

    def _stop_playback(self):
        self.player.stop()
        if self._play_after_id is not None:
            self.root.after_cancel(self._play_after_id)
            self._play_after_id = None
        self._playing_dir = None

    def _copy_selected(self):
        content = self.text.get("1.0", "end-1c")
        if not content.strip():
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.banner.configure(text=t("copied_toast"), text_color=C["green"])

    def _export_selected(self):
        meeting = self._selected_meeting()
        if meeting is None:
            return
        fmt = self.controller.config.get("export_format", "docx")
        ext = EXPORT_EXTENSIONS.get(fmt, ".docx")
        filetypes = {
            "docx": [("Word Document", "*.docx")],
            "txt": [("Plain Text", "*.txt")],
            "md": [("Markdown", "*.md")],
        }.get(fmt, [("Word Document", "*.docx")])
        default_name = meeting.timestamp.strftime("Scriptly_%Y-%m-%d_%H-%M") + ext
        out_path = filedialog.asksaveasfilename(initialfile=default_name, defaultextension=ext, filetypes=filetypes)
        if not out_path:
            return
        try:
            export_meeting(meeting, Path(out_path), fmt)
            self.banner.configure(text=t("export_done_toast", path=out_path), text_color=C["green"])
        except Exception as exc:
            logger.exception("export failed")
            self.banner.configure(text=t("export_failed", exc=exc), text_color=C["red_text"])

    def _export_selected_srt(self):
        """Captions/subtitle export (.srt) - offered as its own explicit action rather than
        folded into the "default export format" setting above, since the digest (multi-
        meeting) export has no equivalent SRT mode and a single global format setting would
        silently fall back to Word there (confusing). See export.py's export_meeting_srt."""
        meeting = self._selected_meeting()
        if meeting is None:
            return
        default_name = meeting.timestamp.strftime("Scriptly_%Y-%m-%d_%H-%M") + ".srt"
        out_path = filedialog.asksaveasfilename(
            initialfile=default_name, defaultextension=".srt", filetypes=[("SubRip Captions", "*.srt")]
        )
        if not out_path:
            return
        try:
            export_meeting_srt(meeting, Path(out_path))
            self.banner.configure(text=t("export_done_toast", path=out_path), text_color=C["green"])
        except Exception as exc:
            logger.exception("srt export failed")
            self.banner.configure(text=t("export_failed", exc=exc), text_color=C["red_text"])

    def _open_tags_notes_dialog(self):
        meeting = self._selected_meeting()
        if meeting is None:
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("tab_notes"))
        dialog.geometry("420x360")
        dialog.transient(self.root)
        dialog.configure(fg_color=C["bg"])
        dialog.grab_set()
        anchor = self._anchor()

        ctk.CTkLabel(dialog, text=t("tags_label"), anchor=anchor, font=ctk.CTkFont(family=FONT, size=12)).pack(
            fill="x", padx=18, pady=(18, 4)
        )
        tags_var = tk.StringVar(value=", ".join(meeting.tags))
        ctk.CTkEntry(
            dialog, textvariable=tags_var, placeholder_text=t("tags_placeholder"), justify=self._justify(),
            fg_color=C["input"], border_width=0,
        ).pack(fill="x", padx=18)

        ctk.CTkLabel(dialog, text=t("notes_label"), anchor=anchor, font=ctk.CTkFont(family=FONT, size=12)).pack(
            fill="x", padx=18, pady=(16, 4)
        )
        notes_box = ctk.CTkTextbox(dialog, fg_color=C["input"], height=140)
        notes_box.pack(fill="both", expand=True, padx=18)
        showing_placeholder = not meeting.notes
        if meeting.notes:
            notes_box.insert("1.0", meeting.notes)
        else:
            notes_box.insert("1.0", t("notes_placeholder"))
            notes_box.configure(text_color=C["text_soft"])

        def clear_placeholder(_event=None):
            nonlocal showing_placeholder
            if showing_placeholder:
                notes_box.delete("1.0", "end")
                notes_box.configure(text_color=C["text"])
                showing_placeholder = False

        notes_box.bind("<FocusIn>", clear_placeholder)

        def save():
            tags = [tg.strip() for tg in tags_var.get().split(",") if tg.strip()]
            notes = "" if showing_placeholder else notes_box.get("1.0", "end-1c")
            self.controller.update_meeting_meta(meeting.dir, tags=tags, notes=notes)
            dialog.destroy()

        ctk.CTkButton(
            dialog, text=t("btn_save_meta"), fg_color=C["teal"], hover_color=C["teal_hover"], text_color="#062824",
            command=save,
        ).pack(pady=16)

    def _set_text(self, content: str, markdown: bool = False):
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        if not markdown:
            self.text.insert(tk.END, content)
        else:
            for line in content.splitlines():
                stripped = line.lstrip("#").strip()
                if line.startswith("#") and stripped:
                    self.text.insert(tk.END, stripped + "\n", "header")
                    continue
                self._insert_markdown_line(line)
        self.text.configure(state="disabled")

    def _insert_markdown_line(self, line: str):
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            self.text.insert(tk.END, " " * indent + "•  ")
            stripped = stripped[2:]
        elif stripped in ("-", "*"):
            stripped = ""

        pos = 0
        for m in BOLD_RE.finditer(stripped):
            self.text.insert(tk.END, stripped[pos : m.start()])
            self.text.insert(tk.END, m.group(1), "bold")
            pos = m.end()
        self.text.insert(tk.END, stripped[pos:] + "\n")

    def _open_selected_folder(self):
        meeting = self._selected_meeting()
        if meeting is not None:
            subprocess.Popen(["explorer", str(meeting.dir)])

    def _show_detail_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=t("btn_copy"), command=self._copy_selected)
        menu.add_command(label=t("btn_export"), command=self._export_selected)
        menu.add_command(label=t("btn_export_srt"), command=self._export_selected_srt)
        menu.add_command(label="📁  " + t("btn_open_folder"), command=self._open_selected_folder)
        menu.add_separator()
        menu.add_command(label=t("btn_delete"), command=self._delete_selected)
        x = self.more_btn.winfo_rootx()
        y = self.more_btn.winfo_rooty() + self.more_btn.winfo_height()
        menu.tk_popup(x, y)

    def _show_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=t("menu_open_folder"), command=self.open_meetings_folder)
        menu.add_command(label=t("menu_tasks"), command=self.open_tasks)
        menu.add_command(label=t("menu_digest"), command=self.open_digest_export)
        menu.add_command(label=t("menu_stats"), command=self.open_stats)
        menu.add_command(label=t("menu_diagnostics"), command=self.open_diagnostics)
        menu.add_command(label=t("menu_about"), command=self.open_about)
        menu.add_separator()
        menu.add_command(label=t("menu_hide"), command=self.hide)
        menu.add_command(label=t("menu_quit"), command=self.quit_app)
        x = self._menu_btn.winfo_rootx()
        y = self._menu_btn.winfo_rooty() + self._menu_btn.winfo_height()
        menu.tk_popup(x, y)

    def open_stats(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("stats_title"))
        dialog.geometry("440x700")
        dialog.transient(self.root)
        dialog.configure(fg_color=C["bg"])
        dialog.grab_set()
        anchor = self._anchor()
        meetings = self._meetings_all

        body = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=14)

        def section_title(text):
            ctk.CTkLabel(
                body, text=text, text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=11, weight="bold"), anchor=anchor,
            ).pack(fill="x", padx=4, pady=(14, 6))

        # --- מדדים כלליים ---
        s = compute_stats(meetings)
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x")
        grid.columnconfigure((0, 1), weight=1)
        tiles = [
            (t("stats_total_recordings"), str(s["total"])),
            (t("stats_total_time"), format_duration(s["total_seconds"]) if s["total_seconds"] else t("stats_none")),
            (t("stats_this_week"), str(s["this_week"])),
            (t("stats_avg_length"), format_duration(s["avg_seconds"]) if s["avg_seconds"] else t("stats_none")),
        ]
        for i, (label, value) in enumerate(tiles):
            tile = ctk.CTkFrame(grid, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
            tile.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)
            ctk.CTkLabel(tile, text=value, text_color=C["teal_text"], font=ctk.CTkFont(family=FONT, size=18, weight="bold"), anchor=anchor).pack(
                fill="x", padx=12, pady=(10, 0)
            )
            ctk.CTkLabel(tile, text=label, text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=11), anchor=anchor).pack(
                fill="x", padx=12, pady=(0, 10)
            )

        # --- 14 הימים האחרונים ---
        section_title(t("stats_trend"))
        trend = compute_daily_trend(meetings, days=14)
        trend_card = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
        trend_card.pack(fill="x")
        canvas_w, canvas_h, pad = 380, 90, 6
        card_bg, teal_c, soft_c, border_c = self._color("card"), self._color("teal"), self._color("text_soft"), self._color("border")
        canvas = tk.Canvas(trend_card, width=canvas_w, height=canvas_h, bg=card_bg, highlightthickness=0)
        canvas.pack(padx=12, pady=(12, 4))
        max_v = max(trend) or 1
        bar_w = (canvas_w - 2 * pad) / len(trend)
        for i, v in enumerate(trend):
            x0 = pad + i * bar_w + 2
            x1 = pad + (i + 1) * bar_w - 2
            bar_h = (canvas_h - 20) * (v / max_v)
            canvas.create_rectangle(x0, canvas_h - 18 - bar_h, x1, canvas_h - 18, fill=teal_c, outline="")
            if v:
                canvas.create_text((x0 + x1) / 2, canvas_h - 18 - bar_h - 8, text=str(v), fill=soft_c, font=(FONT, 8))
        canvas.create_line(pad, canvas_h - 18, canvas_w - pad, canvas_h - 18, fill=border_c)
        canvas.create_text(pad + 4, canvas_h - 8, text=t("stats_trend_start"), fill=soft_c, font=(FONT, 8), anchor="w")
        canvas.create_text(canvas_w - pad - 4, canvas_h - 8, text=t("stats_trend_end"), fill=soft_c, font=(FONT, 8), anchor="e")
        ctk.CTkFrame(trend_card, fg_color="transparent", height=4).pack()

        # --- יחס דיבור ---
        ratio = compute_talk_ratio(meetings)
        if ratio:
            section_title(t("stats_talk_ratio"))
            ratio_card = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
            ratio_card.pack(fill="x")
            bar = ctk.CTkFrame(ratio_card, fg_color=C["border"], corner_radius=6, height=16)
            bar.pack(fill="x", padx=14, pady=(14, 8))
            bar.pack_propagate(False)
            you_part = ctk.CTkFrame(bar, fg_color=C["teal"], corner_radius=6)
            you_part.place(relx=0, rely=0, relwidth=max(ratio["you_pct"] / 100, 0.02), relheight=1)
            legend = ctk.CTkFrame(ratio_card, fg_color="transparent")
            legend.pack(fill="x", padx=14, pady=(0, 14))
            ctk.CTkLabel(
                legend, text=f"{t('speaker_you')} · {ratio['you_pct']}%", text_color=C["teal_text"], font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
            ).pack(side="left" if anchor == "w" else "right")
            ctk.CTkLabel(
                legend, text=f"{t('speaker_other')} · {ratio['other_pct']}%", text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=12),
            ).pack(side="right" if anchor == "w" else "left")

        # --- טון שיחות ---
        tones = compute_tone_breakdown(meetings)
        if any(tones.values()):
            section_title(t("stats_tone"))
            tone_row = ctk.CTkFrame(body, fg_color="transparent")
            tone_row.pack(fill="x")
            tone_specs = [
                ("positive", "🙂", C["green"], t("tone_positive")),
                ("neutral", "😐", C["text_soft"], t("tone_neutral")),
                ("tense", "⚠", C["amber"], t("tone_tense")),
            ]
            tone_row.columnconfigure((0, 1, 2), weight=1)
            for i, (key, icon, color, label) in enumerate(tone_specs):
                tile = ctk.CTkFrame(tone_row, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
                tile.grid(row=0, column=i, sticky="ew", padx=3)
                ctk.CTkLabel(tile, text=f"{icon} {tones[key]}", text_color=color, font=ctk.CTkFont(family=FONT, size=15, weight="bold")).pack(pady=(10, 0))
                ctk.CTkLabel(tile, text=label, text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=10)).pack(pady=(0, 10))

        # --- תגיות מובילות ---
        top_tags = compute_top_tags(meetings)
        if top_tags:
            section_title(t("stats_top_tags"))
            chips = ctk.CTkFrame(body, fg_color="transparent")
            chips.pack(fill="x")
            for tag, count in top_tags:
                chip = ctk.CTkFrame(chips, fg_color=C["card"], corner_radius=999, border_width=1, border_color=C["border"])
                chip.pack(side="left" if anchor == "w" else "right", padx=(0, 6), pady=2)
                ctk.CTkLabel(
                    chip, text=f"#{tag}  {count}", text_color=C["text"], font=ctk.CTkFont(family=FONT, size=11),
                ).pack(padx=10, pady=5)

        section_title(t("stats_busiest_day"))
        ctk.CTkLabel(
            body, text=s["busiest_day"] or t("stats_none"), text_color=C["text"], font=ctk.CTkFont(family=FONT, size=13), anchor=anchor,
        ).pack(fill="x", padx=4)

    def open_tasks(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("tasks_dialog_title"))
        dialog.geometry("460x520")
        dialog.transient(self.root)
        dialog.configure(fg_color=C["bg"])
        dialog.grab_set()
        anchor = self._anchor()

        header_row = ctk.CTkFrame(dialog, fg_color="transparent")
        header_row.pack(fill="x", padx=18, pady=(18, 4))
        ctk.CTkLabel(header_row, text=t("tasks_dialog_title"), font=ctk.CTkFont(family=FONT, size=17, weight="bold"), anchor=anchor).pack(
            side="left" if anchor == "w" else "right"
        )

        def copy_all_open():
            open_texts = [tk_.text for tk_ in self.controller.get_all_tasks() if not tk_.done]
            if not open_texts:
                return
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(f"- {t_}" for t_ in open_texts))

        ctk.CTkButton(
            header_row, text="📋 " + t("tasks_copy_all"), width=0, height=26, fg_color="transparent",
            border_width=1, border_color=C["border"], text_color=C["text_soft"], hover_color=C["card_hover"],
            command=copy_all_open,
        ).pack(side="right" if anchor == "w" else "left")

        count_lbl = ctk.CTkLabel(dialog, text="", text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=12), anchor=anchor)
        count_lbl.pack(fill="x", padx=18, pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=(0, 14))

        def render():
            for child in scroll.winfo_children():
                child.destroy()
            tasks = self.controller.get_all_tasks()
            open_tasks = [tk_ for tk_ in tasks if not tk_.done]
            done_tasks = [tk_ for tk_ in tasks if tk_.done]
            count_lbl.configure(text=t("tasks_open_count", n=len(open_tasks)))

            if not tasks:
                ctk.CTkLabel(
                    scroll, text=t("tasks_empty"), text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=13),
                    wraplength=380, justify=self._justify(),
                ).pack(pady=30)
                return

            def add_row(task):
                row = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
                row.pack(fill="x", padx=8, pady=4)
                var = tk.BooleanVar(value=task.done)

                def on_toggle(t=task, v=var):
                    self.controller.set_task_done(t.meeting_dir, t.index, v.get())
                    render()

                cb = ctk.CTkCheckBox(
                    row, text=task.text, variable=var, command=on_toggle,
                    font=ctk.CTkFont(family=FONT, size=13), text_color=C["text_soft"] if task.done else C["text"],
                    wraplength=330, justify=self._justify(),
                )
                cb.pack(fill="x", padx=10, pady=(8, 2), anchor=anchor)

                meta_row = ctk.CTkFrame(row, fg_color="transparent")
                meta_row.pack(fill="x", padx=32, pady=(0, 8))
                ctk.CTkLabel(
                    meta_row, text=task.meeting_title, text_color=C["teal_text"], font=ctk.CTkFont(family=FONT, size=10.5), anchor=anchor
                ).pack(side="left" if anchor == "w" else "right")

                status_lbl = ctk.CTkLabel(meta_row, text="", font=ctk.CTkFont(family=FONT, size=10))
                status_lbl.pack(side="right" if anchor == "w" else "left", padx=(0, 4))

                def copy_one(task_obj=task):
                    self.root.clipboard_clear()
                    self.root.clipboard_append(task_obj.text)

                def send(task_obj=task, lbl=status_lbl, service="tasks"):
                    if not google_integration.is_configured(self.controller.config) or not google_integration.is_connected():
                        lbl.configure(text=t("task_send_not_configured"), text_color=C["amber"])
                        return
                    lbl.configure(text="…", text_color=C["text_soft"])

                    def worker():
                        try:
                            if service == "tasks":
                                google_integration.send_task_to_google_tasks(task_obj.text, self.controller.config)
                            else:
                                google_integration.send_task_to_calendar(task_obj.text, self.controller.config)
                            self.root.after(0, lambda: lbl.configure(text=t("task_sent_ok"), text_color=C["green"]))
                        except Exception as exc:
                            logger.error("send task to google failed: %s", exc)
                            self.root.after(0, lambda: lbl.configure(text=t("task_send_failed"), text_color=C["red_text"]))

                    threading.Thread(target=worker, daemon=True).start()

                for icon, cmd, tip in (
                    ("📋", copy_one, t("task_copy_one")),
                    ("✅", lambda task_obj=task: send(task_obj, status_lbl, "tasks"), t("task_send_tasks")),
                    ("📅", lambda task_obj=task: send(task_obj, status_lbl, "calendar"), t("task_send_calendar")),
                ):
                    btn = ctk.CTkButton(
                        meta_row, text=icon, width=22, height=20, fg_color="transparent", hover_color=C["card_hover"],
                        text_color=C["text_soft"], command=cmd, font=ctk.CTkFont(size=11),
                    )
                    btn.pack(side="right" if anchor == "w" else "left", padx=1)

                    def on_enter(_e=None, lbl=status_lbl, tip=tip):
                        lbl._pre_hover_text = lbl.cget("text")
                        lbl._pre_hover_color = lbl.cget("text_color")
                        lbl.configure(text=tip, text_color=C["text_soft"])

                    def on_leave(_e=None, lbl=status_lbl):
                        if hasattr(lbl, "_pre_hover_text"):
                            lbl.configure(text=lbl._pre_hover_text, text_color=lbl._pre_hover_color)

                    btn.bind("<Enter>", on_enter)
                    btn.bind("<Leave>", on_leave)

            if open_tasks:
                for task in open_tasks:
                    add_row(task)
            elif done_tasks:
                ctk.CTkLabel(
                    scroll, text=t("tasks_all_done"), text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=13),
                ).pack(pady=20)

            if done_tasks:
                ctk.CTkLabel(
                    scroll, text=t("tasks_done_section"), text_color=C["text_soft"],
                    font=ctk.CTkFont(family=FONT, size=11, weight="bold"), anchor=anchor,
                ).pack(fill="x", padx=8, pady=(14, 4))
                for task in done_tasks:
                    add_row(task)

        render()

    def open_digest_export(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("digest_dialog_title"))
        dialog.geometry("380x300")
        dialog.transient(self.root)
        dialog.configure(fg_color=C["bg"])
        dialog.grab_set()
        anchor = self._anchor()

        ctk.CTkLabel(
            dialog, text=t("digest_dialog_title"), font=ctk.CTkFont(family=FONT, size=17, weight="bold"), anchor=anchor,
        ).pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkLabel(
            dialog, text=t("digest_dialog_intro"), text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=12),
            wraplength=330, justify=self._justify(), anchor=anchor,
        ).pack(fill="x", padx=20, pady=(0, 16))

        range_var = tk.StringVar(value="week")
        for value, label in (("week", t("digest_range_week")), ("month", t("digest_range_month")), ("all", t("digest_range_all"))):
            ctk.CTkRadioButton(dialog, text=label, variable=range_var, value=value).pack(anchor=anchor, padx=24, pady=6)

        status_lbl = ctk.CTkLabel(dialog, text="", text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=11), wraplength=330)
        status_lbl.pack(fill="x", padx=20, pady=(10, 0))

        def do_export():
            now = datetime.now()
            choice = range_var.get()
            if choice == "week":
                cutoff = now - timedelta(days=7)
                label = t("digest_range_week")
            elif choice == "month":
                cutoff = now - timedelta(days=30)
                label = t("digest_range_month")
            else:
                cutoff = None
                label = t("digest_range_all")
            selected = [m for m in self._meetings_all if cutoff is None or m.timestamp >= cutoff]
            if not selected:
                status_lbl.configure(text=t("digest_no_meetings"), text_color=C["amber"])
                return
            fmt = self.controller.config.get("export_format", "docx")
            # Digest has no SRT equivalent (a caption file only makes sense for one
            # recording) - DIGEST_EXPORT_EXTENSIONS has no "srt" key so this correctly
            # falls back to ".docx" (matching export_digest()'s own srt->docx fallback)
            # instead of naming the file ".srt" while writing Word bytes into it.
            ext = DIGEST_EXPORT_EXTENSIONS.get(fmt, ".docx")
            filetypes = {
                "docx": [("Word Document", "*.docx")],
                "txt": [("Plain Text", "*.txt")],
                "md": [("Markdown", "*.md")],
            }.get(fmt, [("Word Document", "*.docx")])
            default_name = f"Scriptly_Digest_{now.strftime('%Y-%m-%d')}{ext}"
            out_path = filedialog.asksaveasfilename(initialfile=default_name, defaultextension=ext, filetypes=filetypes)
            if not out_path:
                return
            try:
                export_digest(selected, Path(out_path), label, fmt)
                status_lbl.configure(text=t("digest_done_toast", path=out_path), text_color=C["green"])
            except Exception as exc:
                logger.exception("digest export failed")
                status_lbl.configure(text=t("export_failed", exc=exc), text_color=C["red_text"])

        ctk.CTkButton(
            dialog, text=t("btn_export"), fg_color=C["teal"], hover_color=C["teal_hover"], text_color="#062824", command=do_export,
        ).pack(pady=16)

    def open_about(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("menu_about"))
        dialog.geometry("380x400")
        dialog.transient(self.root)
        dialog.configure(fg_color=C["bg"])
        dialog.grab_set()

        ctk.CTkLabel(dialog, image=self.logo_img, text="").pack(pady=(24, 8))
        ctk.CTkLabel(
            dialog, text=t("about_body", version=f"v{VERSION}"), text_color=C["text"],
            font=ctk.CTkFont(family=FONT, size=12), justify="center", wraplength=320,
        ).pack(padx=20)

        if BUILD_DATE:
            ctk.CTkLabel(
                dialog, text=t("about_build_date", date=BUILD_DATE), text_color=C["text_soft"],
                font=ctk.CTkFont(family=FONT, size=11),
            ).pack(pady=(12, 0))

        def open_changelog():
            changelog_path = PROJECT_ROOT / "CHANGELOG.md"
            try:
                if changelog_path.exists():
                    subprocess.Popen(["notepad.exe", str(changelog_path)])
                else:
                    messagebox.showinfo(t("app_title"), t("about_changelog_missing"))
            except Exception:
                logger.warning("could not open CHANGELOG.md")

        ctk.CTkButton(
            dialog, text=t("about_view_changelog"), height=30, fg_color="transparent", border_width=1,
            border_color=C["border"], text_color=C["text_soft"], hover_color=C["card_hover"], command=open_changelog,
        ).pack(pady=(12, 0))

        ctk.CTkLabel(
            dialog, text=t("copyright_line"), text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=10),
        ).pack(pady=(20, 0), side="bottom")

    def open_diagnostics(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("diagnostics_title"))
        dialog.geometry("520x460")
        dialog.transient(self.root)
        dialog.configure(fg_color=C["bg"])
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text=t("diagnostics_intro"), text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=12),
            wraplength=460, justify=self._justify(), anchor=self._anchor(),
        ).pack(fill="x", padx=20, pady=(16, 4))

        results_frame = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        results_frame.pack(fill="both", expand=True, padx=14, pady=10)

        icon_for = {"ok": ("✓", C["green"]), "warn": ("⚠", C["amber"]), "fail": ("✗", C["red"])}

        def render_results():
            for child in results_frame.winfo_children():
                child.destroy()
            for level, title, detail in diagnostics.run_all(self.controller.config):
                icon, color = icon_for[level]
                row = ctk.CTkFrame(results_frame, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
                row.pack(fill="x", pady=4)
                head = ctk.CTkFrame(row, fg_color="transparent")
                head.pack(fill="x", padx=14, pady=(10, 2))
                ctk.CTkLabel(head, text=icon, text_color=color, font=ctk.CTkFont(size=14, weight="bold")).pack(
                    side="left" if self._anchor() == "w" else "right"
                )
                ctk.CTkLabel(
                    head, text=title, font=ctk.CTkFont(family=FONT, size=12, weight="bold"), text_color=C["text"],
                    anchor=self._anchor(),
                ).pack(side="left" if self._anchor() == "w" else "right", padx=8, fill="x", expand=True)
                ctk.CTkLabel(
                    row, text=detail, text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=11),
                    anchor=self._anchor(), justify=self._justify(), wraplength=440,
                ).pack(fill="x", padx=14, pady=(0, 10))

        render_results()
        ctk.CTkButton(
            dialog, text=t("diagnostics_rerun"), fg_color=C["chip_bg"], text_color=C["text"],
            hover_color=C["card_hover"], command=render_results,
        ).pack(pady=(0, 14))

    def open_meetings_folder(self):
        folder = self.controller.meetings_dir
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    # ---------- controller events ----------

    def _on_controller_event(self, event, payload):
        self.root.after(0, lambda: self._handle_event(event, payload))

    def _handle_event(self, event, payload):
        if event == "recording_started":
            self._recording_since = time.time()
            self.status_label.configure(text=t("status_recording"))
            self.toggle_btn.configure(text="■  " + t("btn_stop"), fg_color=C["red"], hover_color=C["red_hover"], text_color="white")
            self.banner.configure(text="")
        elif event == "recording_stopped":
            self._recording_since = None
            self.timer_label.configure(text="")
            self.toggle_btn.configure(text="●  " + t("btn_start"), fg_color=C["teal"], hover_color=C["teal_hover"], text_color="#062824")
        elif event == "recording_discarded":
            self.status_label.configure(text=t("status_ready"))
            self.status_dot.configure(text_color=C["teal_text"])
            self.banner.configure(text=t("discard_msg"))
        elif event == "recording_size_limit_reached":
            # Recording already auto-stopped and saved (see AppController._on_recording_size_limit) -
            # this is a heads-up, not an error, so it uses the amber warning color rather than red.
            self.banner.configure(text=t("recording_size_limit_banner"), text_color=C["amber"])
        elif event == "recording_saved_pending":
            self.status_label.configure(text=t("status_ready"))
            self.status_dot.configure(text_color=C["teal_text"])
            self.banner.configure(text=t("recording_saved_pending_banner"), text_color=C["text_soft"])
            self.refresh_meetings(select_dir=payload.get("meeting_dir"))
            self.show()
        elif event == "processing_started":
            self._processing_dirs.add(payload.get("meeting_dir"))
            self.status_label.configure(text=t("status_transcribing"))
            self.status_dot.configure(text_color=C["amber"])
            self.refresh_meetings(select_dir=payload.get("meeting_dir"))
        elif event == "processing_done":
            self._processing_dirs.discard(payload.get("meeting_dir"))
            self.status_label.configure(text=t("status_ready"))
            self.status_dot.configure(text_color=C["teal_text"])
            self.banner.configure(text=t("processing_done_msg"), text_color=C["green"])
            self.refresh_meetings(select_dir=payload.get("meeting_dir"))
            self.show()
        elif event == "meeting_deleted":
            self.refresh_meetings()
        elif event == "meeting_meta_updated":
            self.refresh_meetings(select_dir=payload.get("meeting_dir"))
        elif event == "error":
            if payload.get("meeting_dir") is not None:
                self._processing_dirs.discard(payload.get("meeting_dir"))
                self.refresh_meetings(select_dir=payload.get("meeting_dir"))
            self.status_label.configure(text=t("status_ready"))
            self.status_dot.configure(text_color=C["teal_text"])
            self.banner.configure(text=payload.get("message", "Error"), text_color=C["red_text"])

    def _tick(self):
        if self._recording_since is not None:
            elapsed = int(time.time() - self._recording_since)
            self.timer_label.configure(text=f"{elapsed // 60:02d}:{elapsed % 60:02d}")
            self._blink_on = not self._blink_on
            self.status_dot.configure(text_color=C["red_text"] if self._blink_on else "#7a8aa8")
        self.root.after(500, self._tick)

    # ---------- settings ----------

    def open_settings(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(t("settings_title"))
        dialog.geometry("560x700")
        dialog.transient(self.root)
        dialog.configure(fg_color=C["bg"])
        dialog.grab_set()

        config = self.controller.config
        anchor = self._anchor()

        scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=6, pady=6)

        def section(title):
            frame = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["border"])
            frame.pack(fill="x", padx=10, pady=8)
            ctk.CTkLabel(
                frame, text=title, font=ctk.CTkFont(family=FONT, size=13, weight="bold"), text_color=C["teal_text"], anchor=anchor
            ).pack(fill="x", padx=16, pady=(14, 6))
            return frame

        def add_help(parent, help_text):
            if not help_text:
                return
            ctk.CTkLabel(
                parent, text=help_text, text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=10),
                anchor=anchor, justify=self._justify(), wraplength=480,
            ).pack(fill="x", padx=16, pady=(0, 6))

        def add_row(parent, label_text, widget, help_text=None):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(6, 0 if help_text else 6))
            ctk.CTkLabel(row, text=label_text, anchor=anchor, width=170, font=ctk.CTkFont(family=FONT, size=12)).pack(
                side="left" if anchor == "w" else "right"
            )
            widget.pack(side="left" if anchor == "w" else "right", fill="x", expand=True, padx=8)
            add_help(parent, help_text)
            return row

        # --- Recording section ---
        sec_rec = section("🎙  " + t("meetings_header"))
        hotkey_var = tk.StringVar(value=config["hotkey"])
        add_row(sec_rec, t("settings_hotkey"), ctk.CTkEntry(sec_rec, textvariable=hotkey_var), t("help_hotkey"))

        dir_var = tk.StringVar(value=config["meetings_dir"])
        dir_row = ctk.CTkFrame(sec_rec, fg_color="transparent")
        dir_row.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(dir_row, text=t("settings_dir"), anchor=anchor, width=170, font=ctk.CTkFont(family=FONT, size=12)).pack(
            side="left" if anchor == "w" else "right"
        )
        dir_entry_frame = ctk.CTkFrame(dir_row, fg_color="transparent")
        dir_entry_frame.pack(side="left" if anchor == "w" else "right", fill="x", expand=True, padx=8)
        ctk.CTkEntry(dir_entry_frame, textvariable=dir_var).pack(side="left", fill="x", expand=True)

        def browse():
            chosen = filedialog.askdirectory(initialdir=dir_var.get() or ".")
            if chosen:
                dir_var.set(chosen)

        ctk.CTkButton(dir_entry_frame, text=t("settings_browse"), width=80, command=browse).pack(side="left", padx=(6, 0))
        add_help(sec_rec, t("help_dir"))

        try:
            mic_devices = audio_devices.list_input_devices()
        except Exception:
            mic_devices = []
        mic_names = [name for _idx, name in mic_devices]
        mic_name_to_index = {name: idx for idx, name in mic_devices}
        current_mic_index = config.get("mic_device_index")
        current_mic_name = next((n for i, n in mic_devices if i == current_mic_index), None)
        mic_var = tk.StringVar(value=current_mic_name or (mic_names[0] if mic_names else ""))
        if mic_names:
            add_row(sec_rec, t("onboarding_mic_label"), ctk.CTkOptionMenu(sec_rec, values=mic_names, variable=mic_var), t("help_mic"))

        keep_audio_var = tk.BooleanVar(value=config.get("keep_audio", False))
        ctk.CTkCheckBox(sec_rec, text=t("settings_keep_audio"), variable=keep_audio_var).pack(
            anchor=anchor, padx=16, pady=(4, 0)
        )
        add_help(sec_rec, t("help_keep_audio"))
        auto_summarize_var = tk.BooleanVar(value=config.get("auto_summarize", True))
        ctk.CTkCheckBox(sec_rec, text=t("settings_auto_summarize"), variable=auto_summarize_var).pack(
            anchor=anchor, padx=16, pady=(4, 0)
        )
        add_help(sec_rec, t("help_auto_summarize"))

        min_duration_var = tk.StringVar(value=str(config.get("min_recording_duration", 5)))
        add_row(sec_rec, t("settings_min_duration"), ctk.CTkEntry(sec_rec, textvariable=min_duration_var), t("help_min_duration"))

        max_size_var = tk.StringVar(value=str(config.get("max_file_size_gb", 10)))
        add_row(sec_rec, t("settings_max_size"), ctk.CTkEntry(sec_rec, textvariable=max_size_var), t("help_max_size"))
        ctk.CTkFrame(sec_rec, fg_color="transparent", height=8).pack()

        # --- AI section ---
        sec_ai = section("🧠  " + t("settings_transcription_section"))
        ollama_model_var = tk.StringVar(value=config["ollama_model"])
        add_row(sec_ai, t("settings_summary_model"), ctk.CTkEntry(sec_ai, textvariable=ollama_model_var), t("help_ollama_model"))
        whisper_device_var = tk.StringVar(value=config["whisper_device"])
        add_row(
            sec_ai, t("settings_transcribe_engine"), ctk.CTkOptionMenu(sec_ai, values=["cuda", "cpu"], variable=whisper_device_var),
            t("help_whisper_device"),
        )
        vocab_var = tk.StringVar(value=config.get("custom_vocabulary", ""))
        add_row(sec_ai, t("settings_custom_vocab"), ctk.CTkEntry(sec_ai, textvariable=vocab_var), t("help_custom_vocab"))

        speaker_labels_var = tk.BooleanVar(value=config.get("speaker_labels", True))
        ctk.CTkCheckBox(sec_ai, text=t("settings_speaker_labels"), variable=speaker_labels_var).pack(
            anchor=anchor, padx=16, pady=(4, 0)
        )
        add_help(sec_ai, t("help_speaker_labels"))

        ai_titles_var = tk.BooleanVar(value=config.get("ai_titles", True))
        ctk.CTkCheckBox(sec_ai, text=t("settings_ai_titles"), variable=ai_titles_var).pack(
            anchor=anchor, padx=16, pady=(8, 0)
        )
        add_help(sec_ai, t("help_ai_titles"))

        ai_tags_var = tk.BooleanVar(value=config.get("ai_tags", True))
        ctk.CTkCheckBox(sec_ai, text=t("settings_ai_tags"), variable=ai_tags_var).pack(
            anchor=anchor, padx=16, pady=(8, 0)
        )
        add_help(sec_ai, t("help_ai_tags"))

        ctk.CTkLabel(
            sec_ai, text="🔒 " + t("settings_privacy_note"), text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=11),
            wraplength=460, justify=self._justify(), anchor=anchor,
        ).pack(fill="x", padx=16, pady=(10, 16))

        # --- Interface section ---
        sec_ui = section("🎨  " + t("settings_interface_section"))
        lang_display = {"en": "English", "he": "עברית"}
        lang_reverse = {v: k for k, v in lang_display.items()}
        lang_var = tk.StringVar(value=lang_display.get(config.get("ui_language", "en"), "English"))
        add_row(
            sec_ui, t("settings_language"), ctk.CTkOptionMenu(sec_ui, values=list(lang_display.values()), variable=lang_var),
            t("help_language"),
        )

        appearance_display = {
            "system": t("settings_appearance_system"),
            "light": t("settings_appearance_light"),
            "dark": t("settings_appearance_dark"),
        }
        appearance_reverse = {v: k for k, v in appearance_display.items()}
        appearance_var = tk.StringVar(
            value=appearance_display.get(config.get("appearance_mode", "system"), appearance_display["system"])
        )

        def on_appearance_change(choice):
            ctk.set_appearance_mode(appearance_reverse.get(choice, "system"))
            self._refresh_text_theme()

        add_row(
            sec_ui, t("settings_appearance"),
            ctk.CTkOptionMenu(sec_ui, values=list(appearance_display.values()), variable=appearance_var, command=on_appearance_change),
            t("help_appearance"),
        )

        autostart_var = tk.BooleanVar(value=autostart.is_enabled())
        ctk.CTkCheckBox(sec_ui, text=t("settings_autostart"), variable=autostart_var).pack(
            anchor=anchor, padx=16, pady=(4, 0)
        )
        add_help(sec_ui, t("help_autostart"))

        floating_var = tk.BooleanVar(value=config.get("floating_launcher", True))
        ctk.CTkCheckBox(sec_ui, text=t("settings_floating_launcher"), variable=floating_var).pack(
            anchor=anchor, padx=16, pady=(8, 0)
        )
        add_help(sec_ui, t("help_floating_launcher"))

        voice_var = tk.BooleanVar(value=config.get("voice_commands", False))
        ctk.CTkCheckBox(sec_ui, text=t("settings_voice_commands"), variable=voice_var).pack(
            anchor=anchor, padx=16, pady=(8, 0)
        )
        add_help(sec_ui, t("help_voice_commands"))

        scale_display = {1.0: t("scale_normal"), 1.15: t("scale_large"), 1.3: t("scale_xlarge")}
        scale_reverse = {v: k for k, v in scale_display.items()}
        scale_var = tk.StringVar(value=scale_display.get(config.get("ui_scale", 1.0), scale_display[1.0]))
        add_row(
            sec_ui, t("settings_text_size"), ctk.CTkOptionMenu(sec_ui, values=list(scale_display.values()), variable=scale_var),
            t("help_text_size"),
        )
        ctk.CTkFrame(sec_ui, fg_color="transparent", height=8).pack()

        # --- Storage & Export section ---
        sec_storage = section("💾 " + t("settings_storage_section"))
        notification_var = tk.BooleanVar(value=config.get("notification_enabled", True))
        ctk.CTkCheckBox(sec_storage, text=t("settings_notifications_enabled"), variable=notification_var).pack(
            anchor=anchor, padx=16, pady=(4, 0)
        )
        add_help(sec_storage, t("settings_notifications_enabled_help"))

        auto_save_var = tk.BooleanVar(value=config.get("auto_save_recordings", True))
        ctk.CTkCheckBox(sec_storage, text=t("settings_auto_save_recordings"), variable=auto_save_var).pack(
            anchor=anchor, padx=16, pady=(8, 0)
        )
        add_help(sec_storage, t("settings_auto_save_recordings_help"))

        check_updates_var = tk.BooleanVar(value=config.get("check_for_updates_enabled", True))
        ctk.CTkCheckBox(sec_storage, text=t("settings_check_for_updates"), variable=check_updates_var).pack(
            anchor=anchor, padx=16, pady=(8, 0)
        )
        add_help(sec_storage, t("settings_check_for_updates_help"))

        update_status_lbl = ctk.CTkLabel(
            sec_storage, text="", text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=12), anchor=anchor,
        )

        def do_check_for_updates_now():
            update_status_lbl.configure(text=t("update_check_checking"))

            def worker():
                from . import update_checker

                result = update_checker.check_for_update_sync()
                if result:
                    def show_found():
                        update_status_lbl.configure(text=t("update_check_found", version=result["version"]))

                    self.root.after(0, show_found)
                    self.root.after(0, lambda: update_checker.open_release_page(result["url"]))
                else:
                    self.root.after(0, lambda: update_status_lbl.configure(text=t("update_check_up_to_date")))

            threading.Thread(target=worker, daemon=True).start()

        check_updates_row = ctk.CTkFrame(sec_storage, fg_color="transparent")
        check_updates_row.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkButton(
            check_updates_row, text=t("settings_check_for_updates_now"), height=28, fg_color="transparent",
            border_width=1, border_color=C["border"], text_color=C["text_soft"], hover_color=C["card_hover"],
            command=do_check_for_updates_now,
        ).pack(side="left" if anchor == "w" else "right")
        update_status_lbl.pack(fill="x", padx=0, pady=(4, 0))

        export_formats = {
            "docx": t("settings_export_format_docx"),
            "txt": t("settings_export_format_txt"),
            "md": t("settings_export_format_md"),
        }
        export_reverse = {v: k for k, v in export_formats.items()}
        export_var = tk.StringVar(value=export_formats.get(config.get("export_format", "docx"), export_formats["docx"]))
        add_row(
            sec_storage, t("settings_export_format"),
            ctk.CTkOptionMenu(sec_storage, values=list(export_formats.values()), variable=export_var),
            t("settings_export_format_help"),
        )
        ctk.CTkFrame(sec_storage, fg_color="transparent", height=8).pack()

        # --- Integrations section ---
        sec_int = section("🔗  " + t("settings_integrations"))
        ctk.CTkLabel(
            sec_int, text=t("settings_integrations_intro"), text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=11),
            wraplength=460, justify=self._justify(), anchor=anchor,
        ).pack(fill="x", padx=16, pady=(0, 8))

        client_id_var = tk.StringVar(value=config.get("google_client_id", ""))
        add_row(sec_int, t("settings_google_client_id"), ctk.CTkEntry(sec_int, textvariable=client_id_var), None)
        client_secret_var = tk.StringVar(value=config.get("google_client_secret", ""))
        add_row(
            sec_int, t("settings_google_client_secret"),
            ctk.CTkEntry(sec_int, textvariable=client_secret_var, show="•"), t("help_google_integration"),
        )

        google_status_lbl = ctk.CTkLabel(
            sec_int, text=t("google_status_connected") if google_integration.is_connected() else t("google_status_not_connected"),
            text_color=C["green"] if google_integration.is_connected() else C["text_soft"],
            font=ctk.CTkFont(family=FONT, size=12), anchor=anchor,
        )
        google_status_lbl.pack(fill="x", padx=16, pady=(6, 4))

        def do_connect():
            client_id_var_val = client_id_var.get().strip()
            client_secret_var_val = client_secret_var.get().strip()
            if not client_id_var_val or not client_secret_var_val:
                google_status_lbl.configure(text=t("google_status_missing_creds"), text_color=C["amber"])
                return
            google_status_lbl.configure(text=t("google_status_connecting"), text_color=C["amber"])
            live_config = dict(config, google_client_id=client_id_var_val, google_client_secret=client_secret_var_val)

            def worker():
                try:
                    google_integration.connect(live_config)
                    self.root.after(0, lambda: google_status_lbl.configure(text=t("google_status_connected"), text_color=C["green"]))
                except Exception as exc:
                    logger.error("google connect failed: %s", exc)
                    self.root.after(0, lambda: google_status_lbl.configure(text=t("google_status_failed"), text_color=C["red_text"]))

            threading.Thread(target=worker, daemon=True).start()

        def do_disconnect():
            google_integration.disconnect()
            google_status_lbl.configure(text=t("google_status_not_connected"), text_color=C["text_soft"])

        btn_row = ctk.CTkFrame(sec_int, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(btn_row, text=t("google_btn_connect"), height=30, fg_color=C["teal"], hover_color=C["teal_hover"], text_color="#062824", command=do_connect).pack(
            side="left" if anchor == "w" else "right", padx=(0, 8)
        )
        ctk.CTkButton(
            btn_row, text=t("google_btn_disconnect"), height=30, fg_color="transparent", border_width=1,
            border_color=C["border"], text_color=C["text_soft"], hover_color=C["card_hover"], command=do_disconnect,
        ).pack(side="left" if anchor == "w" else "right")

        def on_save():
            old_hotkey = self.controller.config["hotkey"]
            old_ui_lang = config.get("ui_language", "en")

            config["hotkey"] = hotkey_var.get().strip() or config["hotkey"]
            config["meetings_dir"] = dir_var.get().strip() or config["meetings_dir"]
            config["keep_audio"] = bool(keep_audio_var.get())
            config["auto_summarize"] = bool(auto_summarize_var.get())
            try:
                min_duration = int(float(min_duration_var.get().strip()))
                config["min_recording_duration"] = max(0, min_duration)
            except (ValueError, TypeError):
                pass  # keep previous value if the field isn't a valid number
            try:
                max_size = float(max_size_var.get().strip())
                config["max_file_size_gb"] = max(0.1, max_size)
            except (ValueError, TypeError):
                pass  # keep previous value if the field isn't a valid number
            if mic_names:
                config["mic_device_index"] = mic_name_to_index.get(mic_var.get())
            config["ollama_model"] = ollama_model_var.get().strip() or config["ollama_model"]
            config["whisper_device"] = whisper_device_var.get().strip() or config["whisper_device"]
            config["custom_vocabulary"] = vocab_var.get().strip()
            config["speaker_labels"] = bool(speaker_labels_var.get())
            config["ai_titles"] = bool(ai_titles_var.get())
            config["ai_tags"] = bool(ai_tags_var.get())
            config["floating_launcher"] = bool(floating_var.get())
            config["voice_commands"] = bool(voice_var.get())
            config["google_client_id"] = client_id_var.get().strip()
            config["google_client_secret"] = client_secret_var.get().strip()
            config["ui_language"] = lang_reverse.get(lang_var.get(), "en")
            config["appearance_mode"] = appearance_reverse.get(appearance_var.get(), "system")
            config["notification_enabled"] = bool(notification_var.get())
            config["auto_save_recordings"] = bool(auto_save_var.get())
            config["check_for_updates_enabled"] = bool(check_updates_var.get())
            config["export_format"] = export_reverse.get(export_var.get(), "docx")
            old_scale = config.get("ui_scale", 1.0)
            config["ui_scale"] = scale_reverse.get(scale_var.get(), 1.0)
            save_config(config)
            autostart.set_enabled(bool(autostart_var.get()))
            self.controller.reload_config()
            if config["ui_scale"] != old_scale:
                ctk.set_widget_scaling(config["ui_scale"])

            if config["hotkey"] != old_hotkey:
                self._reregister_hotkey(old_hotkey, config["hotkey"])

            dialog.destroy()

            if config["ui_language"] != old_ui_lang:
                i18n.set_language(config["ui_language"])
                self.rebuild()
            else:
                self.hint_label.configure(text=t("hotkey_hint", hotkey=config["hotkey"]))
                self.refresh_meetings()
            self.banner.configure(text=t("settings_saved"), text_color=C["green"])

        ctk.CTkButton(
            dialog, text=t("settings_save"), fg_color=C["teal"], hover_color=C["teal_hover"], text_color="#062824",
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"), height=38, corner_radius=10, command=on_save,
        ).pack(pady=14)

    def _refresh_text_theme(self):
        bg, fg, header_fg = self._text_colors()
        self.text.configure(bg=bg, fg=fg, insertbackground=fg)
        self.text.tag_configure("header", foreground=header_fg)

    def _reregister_hotkey(self, old_hotkey, new_hotkey):
        try:
            import keyboard

            try:
                keyboard.remove_hotkey(old_hotkey)
            except (KeyError, ValueError):
                pass
            keyboard.add_hotkey(new_hotkey, self.controller.toggle_recording)
            logger.info("hotkey changed: %s -> %s", old_hotkey, new_hotkey)
        except Exception as exc:
            logger.warning("could not re-register hotkey: %s", exc)
            messagebox.showwarning(t("app_title"), t("hotkey_update_failed"))

    # ---------- window lifecycle ----------

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _flush_geometry(self):
        """Save geometry immediately (not the debounced version) - used right before the
        window disappears (hide/quit), since a pending after() timer may never fire once
        the process is exiting or the window is withdrawn."""
        if self._geometry_save_after_id:
            self.root.after_cancel(self._geometry_save_after_id)
            self._geometry_save_after_id = None
        if self.root.state() == "normal":
            self.controller.config["window_geometry"] = self.root.geometry()
            save_config(self.controller.config)

    def hide(self):
        self._flush_geometry()
        self.root.withdraw()
        if not self.controller.config.get("tray_background_notice_shown", False):
            self.controller.config["tray_background_notice_shown"] = True
            save_config(self.controller.config)
            self.controller.notify_event("tray_background_notice", {"message": t("tray_background_notice")})

    def quit_app(self):
        if messagebox.askyesno(t("app_title"), t("quit_confirm")):
            self._flush_geometry()
            if self.controller.is_recording:
                self.controller.stop_recording()
            self.root.event_generate("<<ScriptlyQuit>>")
