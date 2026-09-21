"""First-run onboarding screen for Scriptly PC - language, device, and core settings selection.

Single scrollable screen (not a strict multi-page wizard) grouped into clear
sections - a deliberate simplification of the "3-5 screens" guideline: every
field is pre-filled with a sane default, so Skip/Esc and "Start" are
functionally equivalent, and the whole thing takes one scroll to review."""
import tkinter as tk

import customtkinter as ctk

from . import audio_devices, i18n
from .config import save_config
from .dashboard import _apply_keyboard_focus, _mirror_scrollbar_if_rtl
from .i18n import t

FONT = "Segoe UI"
C = {
    "bg": ("#f1f4f9", "#12151c"),
    "card": ("#ffffff", "#1b1f29"),
    "header": ("#152847", "#0c1424"),
    "text": ("#161d2b", "#e9edf5"),
    "text_soft": ("#66707f", "#8b93a5"),
    "teal": ("#00b8ae", "#12c9bd"),
    "teal_text": ("#00706a", "#12c9bd"),  # WCAG-AA-safe text variant, see app/dashboard.py C dict
    "button_hover": ("#009a92", "#0eab9f"),
    "border": ("#e4e8f0", "#2a2f3d"),
}


class OnboardingDialog:
    """First-run setup wizard for Scriptly PC."""

    def __init__(self, parent, config, on_finished=None):
        self.config = config
        self.on_finished = on_finished
        self.hotkey_changed = False
        self._anchor = i18n.anchor()
        self._justify = i18n.justify()

        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title(t("onboarding_wizard_title"))
        self.dialog.geometry("600x720")
        self.dialog.transient(parent)
        self.dialog.configure(fg_color=C["bg"])
        self.dialog.grab_set()
        self.dialog.resizable(False, False)

        # Skip is always available: closing the window or pressing Esc both
        # accept the current (already sane) defaults, same as clicking Start.
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_done)
        self.dialog.bind("<Escape>", lambda e: self._on_done())

        self._build_ui()
        _mirror_scrollbar_if_rtl(self.main)
        _apply_keyboard_focus(self.dialog)
        self.dialog.wait_window()

    def _build_ui(self):
        main = ctk.CTkScrollableFrame(self.dialog, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=20)
        self.main = main

        header_frame = ctk.CTkFrame(main, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 24))

        ctk.CTkLabel(
            header_frame,
            text=t("onboarding_title"),
            font=ctk.CTkFont(family=FONT, size=24, weight="bold"),
            text_color=C["teal_text"],
            anchor=self._anchor,
            justify=self._justify,
        ).pack(anchor=self._anchor, fill="x")

        ctk.CTkLabel(
            header_frame,
            text=t("onboarding_intro"),
            font=ctk.CTkFont(family=FONT, size=12),
            text_color=C["text_soft"],
            anchor=self._anchor,
            justify=self._justify,
            wraplength=540,
        ).pack(anchor=self._anchor, fill="x", pady=(6, 0))

        self._section(t("onboarding_section_language"), t("onboarding_section_language_sub"))
        self.lang_var = tk.StringVar(value=self.config.get("ui_language", "en"))
        for code, name in [("en", "English"), ("he", "עברית (Hebrew)")]:
            self._radio(main, name, self.lang_var, code)
        # RTL mirroring precision (STANDARDS.md 18.1): self._anchor/_justify were computed
        # once from the *saved* language at dialog-open time (defaults to "en" on a real
        # first run, since the language picker above is what lets the user change it) - if
        # someone picks Hebrew right here, the rest of this screen used to stay LTR-anchored
        # until after they finished onboarding and the app restarted, so the very moment
        # someone chooses Hebrew showed it half-mirrored. Live-rebuild on every pick instead.
        self.lang_var.trace_add("write", self._on_language_preview_changed)

        self._section(t("onboarding_section_mic"), t("onboarding_section_mic_sub"))
        try:
            mics = audio_devices.list_input_devices()
            mic_names = [name for _, name in mics]
            current_idx = self.config.get("mic_device_index")
            current_name = next((n for i, n in mics if i == current_idx), None)
            self.mic_var = tk.StringVar(value=current_name or (mic_names[0] if mic_names else ""))
            if mic_names:
                for name in mic_names:
                    self._radio(main, name, self.mic_var, name)
            else:
                self._muted_label(main, t("onboarding_no_mics"))
        except Exception as e:
            self._muted_label(main, t("onboarding_mic_error", error=e))

        self._section(t("onboarding_section_features"), t("onboarding_section_features_sub"))
        self.auto_summarize_var = tk.BooleanVar(value=self.config.get("auto_summarize", True))
        self._checkbox(main, t("onboarding_feat_auto_summarize"), self.auto_summarize_var)

        self.ai_titles_var = tk.BooleanVar(value=self.config.get("ai_titles", True))
        self._checkbox(main, t("onboarding_feat_ai_titles"), self.ai_titles_var)

        self.floating_launcher_var = tk.BooleanVar(value=self.config.get("floating_launcher", True))
        self._checkbox(main, t("onboarding_feat_floating"), self.floating_launcher_var)

        self._section(t("onboarding_section_appearance"), t("onboarding_section_appearance_sub"))
        self.appearance_var = tk.StringVar(value=self.config.get("appearance_mode", "system"))
        for code, name in [
            ("system", t("onboarding_theme_system")),
            ("light", t("onboarding_theme_light")),
            ("dark", t("onboarding_theme_dark")),
        ]:
            self._radio(main, name, self.appearance_var, code)

        button_frame = ctk.CTkFrame(main, fg_color="transparent")
        button_frame.pack(fill="x", pady=(24, 4))

        ctk.CTkButton(
            button_frame,
            text=t("onboarding_finish"),
            font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
            fg_color=C["teal"],
            hover_color=C["button_hover"],
            command=self._on_done,
        ).pack(fill="x")

        # Skip is a visible, first-class action (not hidden/greyed) - it applies
        # whatever defaults are already selected above, same as "Start".
        ctk.CTkButton(
            main,
            text=t("onboarding_skip"),
            font=ctk.CTkFont(family=FONT, size=11),
            fg_color="transparent",
            hover_color=C["bg"],
            text_color=C["text_soft"],
            command=self._on_done,
        ).pack(fill="x", pady=(4, 0))

        ctk.CTkLabel(
            main, text=t("copyright_line"), font=ctk.CTkFont(family=FONT, size=10), text_color=C["text_soft"],
        ).pack(pady=(16, 0))

    def _section(self, title, subtitle):
        ctk.CTkLabel(
            self.main, text=title, font=ctk.CTkFont(family=FONT, size=13, weight="bold"), text_color=C["header"],
            anchor=self._anchor,
        ).pack(anchor=self._anchor, fill="x", pady=(12, 0))
        ctk.CTkLabel(
            self.main, text=subtitle, font=ctk.CTkFont(family=FONT, size=11), text_color=C["text_soft"],
            anchor=self._anchor, justify=self._justify,
        ).pack(anchor=self._anchor, fill="x", pady=(2, 8))

    def _radio(self, parent, text, variable, value):
        ctk.CTkRadioButton(
            parent, text=text, variable=variable, value=value, font=ctk.CTkFont(family=FONT, size=12),
        ).pack(anchor=self._anchor, padx=10, pady=4)

    def _checkbox(self, parent, text, variable):
        ctk.CTkCheckBox(parent, text=text, variable=variable, font=ctk.CTkFont(family=FONT, size=12)).pack(
            anchor=self._anchor, padx=10, pady=4
        )

    def _muted_label(self, parent, text):
        ctk.CTkLabel(
            parent, text=text, text_color=C["text_soft"], font=ctk.CTkFont(family=FONT, size=11),
            anchor=self._anchor, justify=self._justify, wraplength=540,
        ).pack(anchor=self._anchor, fill="x", padx=10, pady=4)

    def _on_language_preview_changed(self, *_args):
        lang = self.lang_var.get()
        if lang not in ("en", "he") or lang == i18n.get_language():
            return  # no-op guard: also prevents the re-trigger below from looping

        # Preserve every other in-progress choice across the rebuild - _build_ui()
        # recreates all the Variables from scratch (they default to self.config,
        # not the user's not-yet-saved picks), so capture and restore them.
        mic_value = self.mic_var.get() if hasattr(self, "mic_var") else None
        auto_summarize = self.auto_summarize_var.get()
        ai_titles = self.ai_titles_var.get()
        floating = self.floating_launcher_var.get()
        appearance = self.appearance_var.get()

        i18n.set_language(lang)
        self._anchor = i18n.anchor()
        self._justify = i18n.justify()

        for child in self.dialog.winfo_children():
            child.destroy()
        self._build_ui()

        self.lang_var.set(lang)
        self.auto_summarize_var.set(auto_summarize)
        self.ai_titles_var.set(ai_titles)
        self.floating_launcher_var.set(floating)
        self.appearance_var.set(appearance)
        if mic_value is not None and hasattr(self, "mic_var"):
            self.mic_var.set(mic_value)

    def _on_done(self):
        lang = self.lang_var.get()
        i18n.set_language(lang)

        config_updates = {
            "ui_language": lang,
            "appearance_mode": self.appearance_var.get(),
            "auto_summarize": self.auto_summarize_var.get(),
            "ai_titles": self.ai_titles_var.get(),
            "floating_launcher": self.floating_launcher_var.get(),
            "onboarding_done": True,
        }

        if hasattr(self, "mic_var"):
            try:
                mics = audio_devices.list_input_devices()
                mic_name_to_index = {name: idx for idx, name in mics}
                selected_name = self.mic_var.get()
                if selected_name in mic_name_to_index:
                    config_updates["mic_device_index"] = mic_name_to_index[selected_name]
            except Exception:
                pass

        self.config.update(config_updates)
        save_config(self.config)

        if self.on_finished:
            self.on_finished(False)

        self.dialog.destroy()


def run_onboarding(root, controller, on_finished=None):
    """Launch the onboarding dialog if needed."""
    OnboardingDialog(root, controller.config, on_finished)
