"""
Build a self-extracting installer EXE for Scriptly PC.
Uses Python + PyInstaller to create a genuinely custom-styled Windows
installer wizard (dark navy/teal theme, brand-colored buttons, Fusion style)
instead of an Inno Setup installer, which always renders native Windows
chrome for its buttons/controls regardless of bitmap branding.

Architecture ported directly from the reference implementation:
PC-Software/SnapAI/build/build_installer.py (same tech stack: PyQt6 wizard,
compiled by PyInstaller into its own small installer .exe, which at runtime
extracts/copies the much larger PyInstaller --onedir app payload bundled
alongside it).

The installer:
  1. Shows a modern PyQt6 wizard: language -> welcome/explain -> license ->
     install-location -> progress -> finish
  2. Copies the bundled "Scriptly PC" --onedir folder (~1GB, Whisper+torch+
     CUDA) to the chosen directory, with real progress reporting
  3. Creates Start Menu / Desktop shortcuts (optional, checkboxes)
  4. Writes an uninstall registry entry
  5. Checks the app's own single-instance Mutex before installing, so an
     update can't be written over a locked, running exe
  6. Optionally launches Scriptly PC on finish
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

# This script lives in build\ (dev tooling) - run everything relative to the
# project root, one level up, where app/, assets/, version.json etc. live.
os.chdir(Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(Path(".").resolve()))

import json as _json


def _read_version() -> str:
    """version.json is the single source of truth (see app/config.py) - read
    it the same way here instead of importing app/ (which would drag in
    customtkinter/faster-whisper/etc. just to build an installer)."""
    with open("version.json", "r", encoding="utf-8") as f:
        return _json.load(f)["version"]


APP_VER = _read_version()

# We create the installer as a Python script that bundles the app folder,
# then compile THAT script with PyInstaller into a small standalone exe.

INSTALLER_SCRIPT = r'''
import sys, os, shutil, winreg, subprocess, ctypes, threading, time
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QDialog, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QProgressBar,
    QTextEdit, QFileDialog, QMessageBox, QRadioButton, QButtonGroup, QWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QColor, QPainter, QFont, QIcon, QLinearGradient

APP_NAME   = "Scriptly PC"
APP_VER    = "__APP_VERSION__"
PUBLISHER  = "Scriptly PC"
EXE_NAME   = "Scriptly PC.exe"
# Must match app/single_instance.py's _MUTEX_NAME exactly, including the
# Global\ namespace prefix, or the running-instance guard below would
# silently never trigger.
APP_MUTEX  = "Global\\ScriptlyPC_SingleInstance_Mutex"
REG_KEY    = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Scriptly PC"

# ── Shared install-state helpers (used by both the GUI wizard and --silent) ──
def is_app_running() -> bool:
    """Ports app/single_instance.py's OS-level Mutex check (the same mechanism
    scriptly.iss used via Inno's CheckForMutexes) rather than a tasklist name
    match, so it can't miss a renamed/relocated exe and can't false-positive on
    an unrelated process that merely shares the app's display name."""
    try:
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, APP_MUTEX)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False

def read_registry_install_dir() -> str | None:
    """Reads InstallLocation from the uninstall-registry entry a previous
    install/update wrote (see write_registry() below) - used by --silent to
    find "the existing location" when it isn't passed --install-dir explicitly,
    so an unattended self-update always lands on top of the current install
    rather than guessing a fresh default path."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY)
        value, _ = winreg.QueryValueEx(key, "InstallLocation")
        winreg.CloseKey(key)
        return value or None
    except Exception:
        return None

# ── Brand palette (assets/BRAND.md - navy header / teal accent) ────────────
NAVY       = "#152847"
NAVY_DARK  = "#0c1424"
PANEL      = "#1b2338"
TEAL       = "#00b8ae"
TEAL_HOVER = "#009a92"
RED        = "#e34848"
FG         = "#e9edf5"
MUTED      = "#8b93a5"
BORDER     = "#2a3550"

# ── Bilingual strings (EN / HE) ─────────────────────────────────────────────
TR = {
    "en": {
        "choose_lang": "Choose your language",
        "lang_en": "\U0001F1EC\U0001F1E7  English",
        "lang_he": "\U0001F1EE\U0001F1F1  \u05e2\u05d1\u05e8\u05d9\u05ea (Hebrew)",
        "welcome_title": "Welcome to Scriptly PC Setup",
        "welcome_body": f"This wizard will install <b>Scriptly PC v{APP_VER}</b> on your computer.",
        "features_title": "What Scriptly PC does:",
        "license_title": "License Agreement",
        "license_agree": "I accept the terms of the license agreement",
        "dir_title": "Choose Install Location",
        "dir_label": "Install Scriptly PC to:",
        "browse": "Browse\u2026",
        "cb_desktop": "Create Desktop shortcut",
        "cb_startmenu": "Create Start Menu shortcut",
        "cb_startup": "Launch Scriptly PC when Windows starts",
        "installing_title": "Installing Scriptly PC\u2026",
        "preparing": "Preparing\u2026",
        "finish_title": "Installation Complete!",
        "finish_body": "<b>Scriptly PC has been installed successfully!</b><br><br>It runs in your system tray. Look for the navy/teal soundwave icon.",
        "cb_launch": "Launch Scriptly PC now",
        "btn_finish": "Finish  \u2713",
        "btn_next": "Next  \u2192",
        "btn_back": "\u2190  Back",
        "btn_cancel": "Cancel",
        "btn_retry": "Retry",
        "app_running_msg": "Scriptly PC is currently running.\n\nPlease close it (including from the system tray) before continuing the installation.",
        "wizard_title": "Scriptly PC \u2014 Setup Wizard",
    },
    "he": {
        "choose_lang": "\u05d1\u05d7\u05e8 \u05e9\u05e4\u05d4",
        "lang_en": "\U0001F1EC\U0001F1E7  English (\u05d0\u05e0\u05d2\u05dc\u05d9\u05ea)",
        "lang_he": "\U0001F1EE\U0001F1F1  \u05e2\u05d1\u05e8\u05d9\u05ea",
        "welcome_title": "\u05d1\u05e8\u05d5\u05db\u05d9\u05dd \u05d4\u05d1\u05d0\u05d9\u05dd \u05dc\u05d4\u05ea\u05e7\u05e0\u05ea Scriptly PC",
        "welcome_body": f"\u05d0\u05e9\u05e3 \u05d6\u05d4 \u05d9\u05ea\u05e7\u05d9\u05df \u05d0\u05ea <b>Scriptly PC \u05d2\u05e8\u05e1\u05d4 {APP_VER}</b> \u05e2\u05dc \u05d4\u05de\u05d7\u05e9\u05d1 \u05e9\u05dc\u05da.",
        "features_title": "\u05de\u05d4 Scriptly PC \u05e2\u05d5\u05e9\u05d4:",
        "license_title": "\u05d4\u05e1\u05db\u05dd \u05e8\u05d9\u05e9\u05d9\u05d5\u05df",
        "license_agree": "\u05d0\u05e0\u05d9 \u05de\u05e7\u05d1\u05dc \u05d0\u05ea \u05ea\u05e0\u05d0\u05d9 \u05d4\u05e1\u05db\u05dd \u05d4\u05e8\u05d9\u05e9\u05d9\u05d5\u05df",
        "dir_title": "\u05d1\u05d7\u05e8 \u05de\u05d9\u05e7\u05d5\u05dd \u05d4\u05ea\u05e7\u05e0\u05d4",
        "dir_label": "\u05d4\u05ea\u05e7\u05df \u05d0\u05ea Scriptly PC \u05d0\u05dc:",
        "browse": "\u05e2\u05d9\u05d5\u05df\u2026",
        "cb_desktop": "\u05e6\u05d5\u05e8 \u05e7\u05d9\u05e6\u05d5\u05e8 \u05d3\u05e8\u05da \u05d1\u05e9\u05d5\u05dc\u05d7\u05df \u05d4\u05e2\u05d1\u05d5\u05d3\u05d4",
        "cb_startmenu": "\u05e6\u05d5\u05e8 \u05e7\u05d9\u05e6\u05d5\u05e8 \u05d3\u05e8\u05da \u05d1\u05ea\u05e4\u05e8\u05d9\u05d8 \u05d4\u05ea\u05d7\u05dc",
        "cb_startup": "\u05d4\u05e4\u05e2\u05dc \u05d0\u05ea Scriptly PC \u05d1\u05d4\u05e4\u05e2\u05dc\u05ea Windows",
        "installing_title": "\u05de\u05ea\u05e7\u05d9\u05df \u05d0\u05ea Scriptly PC\u2026",
        "preparing": "\u05de\u05db\u05d9\u05df...",
        "finish_title": "\u05d4\u05d4\u05ea\u05e7\u05e0\u05d4 \u05d4\u05d5\u05e9\u05dc\u05de\u05d4!",
        "finish_body": "<b>Scriptly PC \u05d4\u05d5\u05ea\u05e7\u05df \u05d1\u05d4\u05e6\u05dc\u05d7\u05d4!</b><br><br>\u05d4\u05d5\u05d0 \u05e4\u05d5\u05e2\u05dc \u05d1\u05de\u05d2\u05e9 \u05d4\u05de\u05e2\u05e8\u05db\u05ea. \u05d7\u05e4\u05e9 \u05d0\u05ea \u05d4\u05e1\u05de\u05dc \u05d4\u05e0\u05d9\u05d9\u05d5\u05d8\u05d9 \u05d1\u05d2\u05d5\u05d5\u05df \u05e0\u05d9\u05d9\u05d1\u05d9-\u05d8\u05d9\u05dc.",
        "cb_launch": "\u05d4\u05e4\u05e2\u05dc \u05d0\u05ea Scriptly PC \u05e2\u05db\u05e9\u05d9\u05d5",
        "btn_finish": "\u05e1\u05d9\u05d5\u05dd  \u2713",
        "btn_next": "\u05d4\u05d1\u05d0  \u2192",
        "btn_back": "\u2190  \u05d4\u05e7\u05d5\u05d3\u05dd",
        "btn_cancel": "\u05d1\u05d9\u05d8\u05d5\u05dc",
        "btn_retry": "\u05e0\u05e1\u05d4 \u05e9\u05d5\u05d1",
        "app_running_msg": "Scriptly PC \u05e4\u05d5\u05e2\u05dc \u05db\u05e8\u05d2\u05e2.\n\n\u05d9\u05e9 \u05dc\u05e1\u05d2\u05d5\u05e8 \u05d0\u05d5\u05ea\u05d5 (\u05d2\u05dd \u05de\u05de\u05d2\u05e9 \u05d4\u05de\u05e2\u05e8\u05db\u05ea) \u05dc\u05e4\u05e0\u05d9 \u05e9\u05de\u05de\u05e9\u05d9\u05db\u05d9\u05dd \u05d1\u05d4\u05ea\u05e7\u05e0\u05d4.",
        "wizard_title": "Scriptly PC \u2014 \u05d0\u05e9\u05e3 \u05d4\u05ea\u05e7\u05e0\u05d4",
    },
}

def detect_lang():
    # Default is English for every tool (2026-09-14 decision) - the language
    # picker page still lets the user switch to Hebrew immediately, this just
    # controls which option is pre-selected when that page first appears.
    return "en"

LANG = {"code": detect_lang()}
def tr(key): return TR.get(LANG["code"], TR["en"]).get(key, key)

STYLE = f"""
QDialog, QWidget {{ background:{NAVY_DARK}; color:{FG}; font-family:'Segoe UI'; font-size:13px; }}
QLabel {{ color:{FG}; }}
QPushButton {{
    background:{PANEL}; border:1px solid {BORDER}; border-radius:8px;
    padding:8px 20px; color:{FG};
}}
QPushButton:hover {{ background:{BORDER}; }}
QPushButton:disabled {{ color:{MUTED}; }}
QPushButton#finish {{ background:{TEAL}; border:none; color:#04211f; font-weight:bold; }}
QPushButton#finish:hover {{ background:{TEAL_HOVER}; }}
QPushButton#finish:disabled {{ background:{BORDER}; color:{MUTED}; }}
QLineEdit {{
    background:{PANEL}; border:1px solid {BORDER}; border-radius:8px;
    padding:7px 11px; color:{FG};
}}
QLineEdit:focus {{ border-color: {TEAL}; }}
QCheckBox, QRadioButton {{ color:{FG}; spacing:10px; }}
QCheckBox::indicator {{ width:18px; height:18px; border:2px solid {BORDER}; border-radius:6px; background:{PANEL}; }}
QCheckBox::indicator:hover {{ border-color:{TEAL}; }}
QCheckBox::indicator:checked {{ background:{TEAL}; border-color:{TEAL}; }}
QRadioButton::indicator {{ width:18px; height:18px; border:2px solid {BORDER}; border-radius:9px; background:{PANEL}; }}
QRadioButton::indicator:hover {{ border-color:{TEAL}; }}
QRadioButton::indicator:checked {{ background:{TEAL}; border-color:{TEAL}; }}
QProgressBar {{
    background:{PANEL}; border:none; border-radius:7px; height:14px; text-align: center; color:{FG};
}}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {NAVY}, stop:1 {TEAL}); border-radius:7px; }}
QTextEdit {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:8px; color:#c3c9d6; font-size:11px; }}
QScrollBar:vertical {{ background:{NAVY_DARK}; width:10px; }}
QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:5px; min-height:24px; }}
"""

# ── Icon / banner ────────────────────────────────────────────────────────────
def _find_real_icon() -> Path | None:
    """The real app icon, bundled next to this installer exe by PyInstaller's
    --add-data (see build_installer_exe() below). Falls back to a drawn mark
    if it's ever missing so the installer never crashes over a resource path."""
    here = Path(sys.executable).parent
    for c in (here / "assets" / "icon_idle.ico", Path(getattr(sys, "_MEIPASS", here)) / "assets" / "icon_idle.ico"):
        if c.exists():
            return c
    return None

def _soundwave_mark(size, accent=QColor(TEAL)) -> QPixmap:
    """Drawn fallback matching build/generate_icons.py's real mark (navy
    circle, teal soundwave bars) - used only if assets/icon_idle.ico can't
    be found, so the installer's branding never falls back to a blank icon."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(NAVY))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(int(size * 0.03), int(size * 0.03), int(size * 0.94), int(size * 0.94))
    heights = [0.16, 0.31, 0.51, 0.35, 0.22, 0.39, 0.23]
    bar_w = max(2, int(size * 0.055)); gap = max(1, int(size * 0.03))
    total_w = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (size - total_w) / 2
    cy = size / 2 - size * 0.04
    p.setBrush(accent)
    for h_ratio in heights:
        h = size * h_ratio
        p.drawRoundedRect(int(x), int(cy - h / 2), bar_w, int(h), bar_w / 2, bar_w / 2)
        x += bar_w + gap
    p.end()
    return px

def make_icon(size=64) -> QIcon:
    icon_path = _find_real_icon()
    if icon_path:
        return QIcon(str(icon_path))
    return QIcon(_soundwave_mark(size))

def make_banner(w=560, h=104) -> QPixmap:
    px = QPixmap(w, h)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(NAVY))
    grad.setColorAt(1, QColor(NAVY_DARK))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(px.rect(), grad)
    icon_path = _find_real_icon()
    if icon_path:
        mark = QPixmap(str(icon_path)).scaled(68, 68, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    else:
        mark = _soundwave_mark(68)
    p.drawPixmap(20, 18, mark)
    p.setFont(QFont("Segoe UI", 27, QFont.Weight.Bold))
    p.setPen(QColor("white"))
    p.drawText(104, 18, 400, 42, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Scriptly PC")
    p.setFont(QFont("Segoe UI", 11))
    p.setPen(QColor(MUTED))
    p.drawText(106, 60, 430, 25, Qt.AlignmentFlag.AlignLeft, "Record. Transcribe. Summarize. 100% offline.")
    p.setFont(QFont("Segoe UI", 9))
    p.setPen(QColor(TEAL))
    p.drawText(w - 90, 12, 80, 20, Qt.AlignmentFlag.AlignRight, f"v{APP_VER}")
    p.end()
    return px

# ── Pages (plain QWidget, no QWizard - see note in SnapAI's build_installer.py
# about QWizard's registerField()/isComplete() Next-button footgun) ─────────
class BasePage(QWidget):
    completeChanged = pyqtSignal()
    def refresh_texts(self):
        pass
    def is_complete(self) -> bool:
        return True
    def on_enter(self):
        pass

class LanguageToggle(QWidget):
    def __init__(self, on_change):
        super().__init__()
        self._on_change_cb = on_change
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._group = QButtonGroup(self)
        self._en = QRadioButton()
        self._he = QRadioButton()
        for r in (self._en, self._he):
            r.setStyleSheet(f"""
                QRadioButton {{ font-size:12px; padding:6px 12px; background:{PANEL};
                                border:1px solid {BORDER}; border-radius:14px; }}
                QRadioButton:hover {{ border-color:{TEAL}; }}
                QRadioButton::indicator {{ width:12px; height:12px; }}
            """)
            self._group.addButton(r)
            row.addWidget(r)
        row.addStretch()
        (self._he if LANG["code"] == "he" else self._en).setChecked(True)
        self._group.buttonClicked.connect(self._on_change)
        self.refresh_texts()
    def refresh_texts(self):
        self._en.setText(tr("lang_en"))
        self._he.setText(tr("lang_he"))
    def _on_change(self):
        LANG["code"] = "he" if self._he.isChecked() else "en"
        self._on_change_cb()

class WelcomePage(BasePage):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        l.setSpacing(12)
        banner = QLabel(); banner.setPixmap(make_banner()); l.addWidget(banner)
        l.addSpacing(8)
        self._features = QLabel()
        self._features.setWordWrap(True)
        self._features.setStyleSheet(f"color:{FG}; font-size:13px; line-height:1.6;")
        l.addWidget(self._features)
        l.addStretch()
        self.refresh_texts()
    def refresh_texts(self):
        self._features.setText(
            f"<b>{tr('welcome_title')}</b><br><br>"
            f"{tr('welcome_body')}<br><br>"
            f"<b>{tr('features_title')}</b><br>"
            "&#x2714; Records meetings, sales calls &amp; browser-based calls (Zoom, Meet, Teams, Skype) - any app<br>"
            "&#x2714; Transcribes locally with Whisper, tuned for Hebrew<br>"
            "&#x2714; Summarizes and extracts tasks with a local AI model (Ollama) - no cloud API<br>"
            "&#x2714; <b>Nothing ever leaves your computer</b> - no audio, transcript or summary is sent anywhere<br>"
            "&#x2714; Global hotkey, floating record button, system tray background operation<br>"
            "&#x2714; Export to Word / Markdown / SRT subtitles, single recording or multi-recording digest<br>"
        )

class LicensePage(BasePage):
    def __init__(self, license_text: str):
        super().__init__()
        l = QVBoxLayout(self)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(license_text)
        l.addWidget(te)
        self._agree = QCheckBox()
        self._agree.stateChanged.connect(self.completeChanged)
        l.addWidget(self._agree)
        self.refresh_texts()
    def refresh_texts(self):
        self._agree.setText(tr("license_agree"))
    def is_complete(self):
        return self._agree.isChecked()

class DirPage(BasePage):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)

        self._lang_toggle = LanguageToggle(self._on_language_changed)
        l.addWidget(self._lang_toggle)
        l.addSpacing(10)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{BORDER};")
        l.addWidget(sep)
        l.addSpacing(14)

        # Default to Program Files, matching the portfolio-wide decision and
        # scriptly.iss's previous DefaultDirName={autopf}. The installer exe
        # requests admin elevation (--uac-admin at build time) so writing
        # here works out of the box.
        default = str(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / APP_NAME)
        self._label = QLabel()
        l.addWidget(self._label)
        row = QHBoxLayout()
        self._path = QLineEdit(default)
        self._path.textChanged.connect(self.completeChanged)
        row.addWidget(self._path)
        self._browse_btn = QPushButton()
        self._browse_btn.clicked.connect(self._browse)
        row.addWidget(self._browse_btn)
        l.addLayout(row)
        self._desktop = QCheckBox(); self._desktop.setChecked(True)
        self._startmenu = QCheckBox(); self._startmenu.setChecked(True)
        self._startup = QCheckBox(); self._startup.setChecked(False)
        l.addWidget(self._desktop)
        l.addWidget(self._startmenu)
        l.addWidget(self._startup)
        l.addStretch()
        self.refresh_texts()
    def refresh_texts(self):
        self._lang_toggle.refresh_texts()
        self._label.setText(tr("dir_label"))
        self._browse_btn.setText(tr("browse"))
        self._desktop.setText(tr("cb_desktop"))
        self._startmenu.setText(tr("cb_startmenu"))
        self._startup.setText(tr("cb_startup"))
    def _on_language_changed(self):
        self.completeChanged.emit()
    def is_complete(self):
        return bool(self._path.text().strip())
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("browse"), self._path.text())
        if d: self._path.setText(d + "\\" + APP_NAME)
    def values(self):
        return {
            "install_dir": self._path.text().strip(),
            "desktop": self._desktop.isChecked(),
            "startmenu": self._startmenu.isChecked(),
            "startup": self._startup.isChecked(),
        }

class InstallPage(BasePage):
    def __init__(self, get_dir_values):
        super().__init__()
        self._get_dir_values = get_dir_values
        self._done = False
        self._started = False
        l = QVBoxLayout(self)
        self._status = QLabel()
        l.addWidget(self._status)
        self._bar = QProgressBar(); self._bar.setRange(0, 100); self._bar.setValue(0)
        l.addWidget(self._bar)
        self._log = QTextEdit(); self._log.setReadOnly(True); self._log.setFixedHeight(160)
        l.addWidget(self._log)
        l.addStretch()
        self.refresh_texts()
    def refresh_texts(self):
        if not self._done:
            self._status.setText(tr("preparing"))
    def on_enter(self):
        if not self._started:
            self._started = True
            QTimer.singleShot(200, self._start_install)
    def _log_line(self, msg):
        self._log.append(msg)
    def _ensure_app_not_running(self) -> bool:
        while is_app_running():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("wizard_title"))
            box.setText(tr("app_running_msg"))
            retry_btn = box.addButton(tr("btn_retry"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("btn_cancel"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not retry_btn:
                return False
        return True
    def _start_install(self):
        if not self._ensure_app_not_running():
            self._status.setText(tr("btn_cancel"))
            QApplication.instance().quit()
            return
        vals = self._get_dir_values()
        self._worker = InstallWorker(vals["install_dir"], vals["desktop"], vals["startmenu"], vals["startup"])
        self._worker.progress.connect(self._bar.setValue)
        self._worker.status.connect(self._status.setText)
        self._worker.log.connect(self._log_line)
        self._worker.finished.connect(self._on_done)
        self._worker.start()
    def _on_done(self):
        self._done = True
        self._bar.setValue(100)
        self._status.setText("\u2713")
        self.completeChanged.emit()
    def is_complete(self):
        return self._done

class FinishPage(BasePage):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        self._lbl = QLabel()
        self._lbl.setWordWrap(True)
        l.addWidget(self._lbl)
        self._launch = QCheckBox()
        self._launch.setChecked(True)
        l.addWidget(self._launch)
        l.addStretch()
        self._copyright = QLabel(f"\u00a9 2026 {PUBLISHER}. All rights reserved.")
        self._copyright.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self._copyright.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(self._copyright)
        self.refresh_texts()
    def refresh_texts(self):
        self._lbl.setText(
            f"{tr('finish_body')}<br><br>"
            "Ctrl+Alt+M \u2014 Start/stop recording (default hotkey, changeable in Settings)<br>"
        )
        self._launch.setText(tr("cb_launch"))
    def launch_checked(self):
        return self._launch.isChecked()

# ── Core install logic (shared by the GUI wizard and --silent) ─────────────
def _find_app_dir() -> Path:
    # --onedir build: the payload bundled into the installer is the whole
    # "Scriptly PC"/ folder (exe + _internal/ deps), matching what
    # build.ps1's PyInstaller step itself produces - no re-flattening.
    here = Path(sys.executable).parent
    candidates = [
        here / APP_NAME,
        here.parent / APP_NAME,
        Path(sys._MEIPASS) / APP_NAME if hasattr(sys, "_MEIPASS") else None,
    ]
    for c in candidates:
        if c and (c / EXE_NAME).exists():
            return c
    return None

def _copy_tree_with_progress(src: Path, dest: Path, status_cb, log_cb, progress_cb):
    """The app is large (~1GB: bundled Whisper/ctranslate2/CUDA runtime,
    thousands of files under _internal/) - a plain shutil.copytree gives no
    feedback for the many seconds/minutes that takes, which reads as a hung
    installer. This walks the tree once to get a total file count, then
    copies file-by-file (shutil.copy2, dirs made as needed) so progress
    (mapped to the 2-85% band) moves the whole time. Copying is purely
    additive/overwrite - it never deletes anything already in dest that isn't
    also in src, so a silent update run on top of an existing install leaves
    the sibling data/ and Meetings/ folders (user settings + recordings,
    living next to the exe - see app/config.py PROJECT_ROOT) untouched."""
    all_files = [p for p in src.rglob("*") if p.is_file()]
    total = max(1, len(all_files))
    log_cb(f"\u2192 {total} files to copy")
    copied = 0
    last_emit_pct = -1
    for f in all_files:
        rel = f.relative_to(src)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
        copied += 1
        pct = 2 + int((copied / total) * 83)  # maps into the 2-85% band
        if pct != last_emit_pct:
            progress_cb(pct)
            last_emit_pct = pct
        if copied % 250 == 0 or copied == total:
            status_cb(f"Copying Scriptly PC files\u2026 ({copied}/{total})")

def _create_shortcut(target: Path, link: Path, log_cb):
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(str(link))
        sc.Targetpath = str(target)
        sc.WorkingDirectory = str(target.parent)
        sc.IconLocation = str(target)
        sc.save()
    except Exception as e:
        log_cb(f"  Shortcut warning: {e}")

def write_registry(install_dir: Path, log_cb=lambda m: None):
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY)
        winreg.SetValueEx(key, "DisplayName",      0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion",   0, winreg.REG_SZ, APP_VER)
        winreg.SetValueEx(key, "Publisher",        0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(key, "InstallLocation",  0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "UninstallString",  0, winreg.REG_SZ, str(install_dir / EXE_NAME) + " --uninstall")
        winreg.SetValueEx(key, "DisplayIcon",      0, winreg.REG_SZ, str(install_dir / EXE_NAME))
        winreg.SetValueEx(key, "NoModify",         0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
    except Exception as e:
        log_cb(f"  Registry warning: {e}")

def perform_install(install_dir, desktop, startmenu, startup, status_cb=lambda m: None, log_cb=lambda m: None, progress_cb=lambda p: None):
    """The actual install steps (copy payload, shortcuts, registry entry),
    shared verbatim by the interactive GUI wizard (InstallWorker, below) and
    the --silent unattended path (run_silent_install). Raises on failure -
    callers decide how to surface that (GUI: log+status line; silent: stderr
    + non-zero exit code) rather than swallowing it here."""
    dest = Path(install_dir)
    status_cb("Creating directory\u2026")
    log_cb(f"\u2192 {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    progress_cb(2)

    status_cb("Copying Scriptly PC files\u2026")
    src = _find_app_dir()
    if src and src.exists():
        _copy_tree_with_progress(src, dest, status_cb, log_cb, progress_cb)
        log_cb(f"\u2713 Copied {src.name}/")
    else:
        log_cb("\u26a0 App folder not found - installer may be incomplete")
    progress_cb(85)

    if desktop:
        status_cb("Creating Desktop shortcut\u2026")
        _create_shortcut(dest / EXE_NAME, Path(os.environ["USERPROFILE"]) / "Desktop" / f"{APP_NAME}.lnk", log_cb)
        log_cb("\u2713 Desktop shortcut")
    progress_cb(90)

    if startmenu:
        status_cb("Creating Start Menu shortcut\u2026")
        sm_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
        sm_dir.mkdir(parents=True, exist_ok=True)
        _create_shortcut(dest / EXE_NAME, sm_dir / f"{APP_NAME}.lnk", log_cb)
        log_cb("\u2713 Start Menu shortcut")
    progress_cb(93)

    if startup:
        status_cb("Adding to startup\u2026")
        startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        _create_shortcut(dest / EXE_NAME, startup_dir / f"{APP_NAME}.lnk", log_cb)
        log_cb("\u2713 Added to startup")
    progress_cb(96)

    status_cb("Writing registry entry\u2026")
    write_registry(dest, log_cb)
    log_cb("\u2713 Registry entry written")
    progress_cb(99)

    status_cb("Done!")
    log_cb("\u2713 Installation complete")
    progress_cb(100)


def run_silent_install(install_dir: str = None) -> int:
    """The --silent entry point: runs the whole install with zero dialogs, to
    the existing install location (preserving settings/meeting data - see
    perform_install's docstring), and returns a proper process exit code
    (0 = success, 1 = failure) instead of ever calling sys.exit() itself, so
    main() stays the single place that does.

    If the app is still running (e.g. the self-update caller's own process
    hasn't fully exited yet), this waits briefly and retries rather than
    failing immediately or forcibly killing anything - but it will NOT wait
    forever or force-close a live app; if it's still running after the retry
    window, this fails loudly (non-zero exit, message on stderr) rather than
    silently overwriting a locked, running exe."""
    for _ in range(20):  # ~10s total - covers the caller's own process exiting after launching us
        if not is_app_running():
            break
        time.sleep(0.5)
    else:
        print("Scriptly PC is still running - cannot complete a silent install/update.", file=sys.stderr)
        return 1

    if not install_dir:
        install_dir = read_registry_install_dir()
    if not install_dir:
        install_dir = str(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / APP_NAME)
    dest = Path(install_dir)

    # Preserve the user's existing shortcut choices (rather than defaulting to
    # "on" like a fresh install) by checking what's already there.
    desktop_link = Path(os.environ["USERPROFILE"]) / "Desktop" / f"{APP_NAME}.lnk"
    startmenu_link = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME / f"{APP_NAME}.lnk"
    startup_link = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{APP_NAME}.lnk"

    try:
        perform_install(
            str(dest),
            desktop=desktop_link.exists(),
            startmenu=startmenu_link.exists(),
            startup=startup_link.exists(),
            status_cb=print, log_cb=print, progress_cb=lambda p: None,
        )
    except Exception as e:
        print(f"Silent install failed: {e}", file=sys.stderr)
        return 1

    print(f"Scriptly PC {APP_VER} installed silently to {dest}")
    return 0


# ── Install Worker (GUI wizard) ─────────────────────────────────────────────
class InstallWorker(QThread):
    progress = pyqtSignal(int)
    status   = pyqtSignal(str)
    log      = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, install_dir, desktop, startmenu, startup):
        super().__init__()
        self.install_dir = install_dir
        self.desktop = desktop
        self.startmenu = startmenu
        self.startup = startup

    def run(self):
        try:
            perform_install(
                self.install_dir, self.desktop, self.startmenu, self.startup,
                status_cb=self.status.emit, log_cb=self.log.emit, progress_cb=self.progress.emit,
            )
            self.finished.emit()
        except Exception as e:
            self.log.emit(f"ERROR: {e}")
            self.status.emit(f"Error: {e}")
            self.finished.emit()

# ── Wizard (QStackedWidget-based) ───────────────────────────────────────────
class SetupWizard(QDialog):
    def __init__(self, license_text: str):
        super().__init__()
        self.setWindowTitle(tr("wizard_title"))
        self.setWindowIcon(make_icon())
        self.setMinimumSize(660, 580)

        self._dir_page = DirPage()
        self._pages = [
            WelcomePage(),
            LicensePage(license_text),
            self._dir_page,
            InstallPage(self._dir_page.values),
            FinishPage(),
        ]
        self._index = 0
        self._accepted = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        for p in self._pages:
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(28, 24, 28, 12)
            wl.addWidget(p)
            self._stack.addWidget(wrap)
            p.completeChanged.connect(self._on_page_changed_signal)
        root.addWidget(self._stack, 1)

        nav = QWidget()
        # Forced LTR regardless of page language: Next always on the right,
        # Back always on the left, matching the app's own nav-mirroring rules.
        nav.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        nav.setStyleSheet(f"background:{PANEL}; border-top:1px solid {BORDER};")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(20, 14, 20, 14)
        self._cancel_btn = QPushButton()
        self._cancel_btn.clicked.connect(self.reject)
        self._back_btn = QPushButton()
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn = QPushButton()
        self._next_btn.setObjectName("finish")
        self._next_btn.clicked.connect(self._go_next)
        nl.addWidget(self._cancel_btn)
        nl.addStretch()
        nl.addWidget(self._back_btn)
        nl.addWidget(self._next_btn)
        root.addWidget(nav)

        self._retranslate_all()
        self._goto(0)

    def _on_page_changed_signal(self):
        self._retranslate_all()
        self._update_nav()

    def _retranslate_all(self):
        self.setWindowTitle(tr("wizard_title"))
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if LANG["code"] == "he" else Qt.LayoutDirection.LeftToRight
        )
        for p in self._pages:
            p.refresh_texts()
        self._cancel_btn.setText(tr("btn_cancel"))
        self._update_nav()

    def _goto(self, index: int):
        self._index = index
        self._stack.setCurrentIndex(index)
        self._pages[index].on_enter()
        self._update_nav()

    def _update_nav(self):
        is_last = self._index == len(self._pages) - 1
        is_install_page = isinstance(self._pages[self._index], InstallPage)
        self._back_btn.setVisible(0 < self._index < len(self._pages) - 2)
        self._cancel_btn.setVisible(not is_last)
        self._next_btn.setText(tr("btn_finish") if is_last else tr("btn_next"))
        self._next_btn.setEnabled(self._pages[self._index].is_complete())
        if is_install_page:
            self._back_btn.setVisible(False)

    def _go_back(self):
        if self._index > 0:
            self._goto(self._index - 1)

    def _go_next(self):
        if self._index == len(self._pages) - 1:
            self._accepted = True
            self.accept()
            return
        self._goto(self._index + 1)

    def launch_requested(self) -> bool:
        return self._accepted and self._pages[-1].launch_checked()

    def install_dir(self) -> str:
        return self._dir_page.values()["install_dir"]


def _load_license_text() -> str:
    here = Path(sys.executable).parent
    for c in (here / "EULA.txt", Path(getattr(sys, "_MEIPASS", here)) / "EULA.txt"):
        if c.exists():
            try:
                return c.read_text(encoding="utf-8")
            except OSError:
                pass
    return "Scriptly PC - see EULA.txt for the full license."


def _parse_silent_args(argv):
    """--silent triggers the unattended path; --install-dir=<path> optionally
    pins the target (see run_silent_install for the fallback chain when it's
    omitted: existing registry InstallLocation, then the default Program
    Files path)."""
    silent = "--silent" in argv
    install_dir = None
    for a in argv:
        if a.startswith("--install-dir="):
            install_dir = a.split("=", 1)[1]
    return silent, install_dir

def main():
    # --silent: the whole point is zero dialogs, so this branch never touches
    # QApplication/QDialog at all - just runs the install and exits with a
    # real process exit code, so a caller (e.g. app/update_checker.py's
    # self-update flow) can tell success from failure without parsing output.
    silent, install_dir = _parse_silent_args(sys.argv[1:])
    if silent:
        sys.exit(run_silent_install(install_dir))

    app = QApplication(sys.argv)
    # Force Fusion style: Qt6's native Windows 11 style ignores custom
    # QPushButton background/border QSS for several button states (a known
    # Qt-on-Windows-11 limitation), which renders buttons as near-invisible
    # native chrome instead of the intended solid brand-colored fill. Fusion
    # fully respects the stylesheet everywhere. MUST be called before any
    # widget is constructed.
    app.setStyle("Fusion")
    app.setApplicationName("Scriptly PC Setup")
    app.setWindowIcon(make_icon())  # covers QMessageBox popups too, not just the main dialog
    app.setStyleSheet(STYLE)

    wiz = SetupWizard(_load_license_text())
    wiz.exec()

    if wiz.launch_requested():
        exe = Path(wiz.install_dir()) / EXE_NAME
        if exe.exists():
            subprocess.Popen([str(exe)], creationflags=subprocess.DETACHED_PROCESS)

    sys.exit(0)

if __name__ == "__main__":
    main()
'''.replace("__APP_VERSION__", APP_VER)
# ^ substituted here (not baked in above as a literal) so the embedded
# installer's version string can never drift from version.json.


def create_installer_script() -> Path:
    script_path = Path("build/installer_app.py")
    script_path.write_text(INSTALLER_SCRIPT, encoding="utf-8")
    print(f"OK Installer script written: {script_path}")
    return script_path


def build_installer_exe(script_path: Path) -> bool:
    print("Building installer EXE with PyInstaller...")
    icon = Path("assets/icon_idle.ico").resolve()
    eula = Path("build/EULA.txt").resolve()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Scriptly_PC_Setup",
        "--onefile",
        "--windowed",
        # Absolute paths: PyInstaller resolves relative --icon/--add-data
        # sources against --specpath (build/), not the CWD.
        "--icon", str(icon),
        # The whole --onedir app payload, bundled under "Scriptly PC/" inside
        # the installer exe - _find_app_dir() in the embedded script looks
        # for it there at runtime.
        "--add-data", f'{Path("dist/Scriptly PC").resolve()};Scriptly PC',
        # The real branded icon + EULA text, so the installer's own banner/
        # window icon and license page use the actual assets, not a redrawn
        # approximation.
        "--add-data", f"{icon};assets",
        "--add-data", f"{eula};.",
        "--hidden-import", "PyQt6.QtCore",
        "--hidden-import", "PyQt6.QtGui",
        "--hidden-import", "PyQt6.QtWidgets",
        "--hidden-import", "win32com.client",
        "--hidden-import", "winreg",
        "--uac-admin",   # embeds a manifest so Windows prompts for elevation -
                         # required to write to C:\Program Files by default
        "--distpath", "build/installer_dist",
        "--workpath", "build/pyinstaller-work",
        "--specpath", "build",
        "--noconfirm",
        str(script_path),
    ]
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode == 0


def main():
    print("=" * 55)
    print("  Scriptly PC \u2014 Building Installer")
    print("=" * 55)

    app_dir = Path("dist/Scriptly PC")
    if not (app_dir / "Scriptly PC.exe").exists():
        print('ERROR: dist/"Scriptly PC"/"Scriptly PC.exe" not found. Run the PyInstaller --onedir step first.')
        sys.exit(1)

    script = create_installer_script()
    ok = build_installer_exe(script)

    built_installer = Path("build/installer_dist/Scriptly_PC_Setup.exe")
    if ok and built_installer.exists():
        size = built_installer.stat().st_size / 1024 / 1024
        # Final deliverable lives at the project root, versioned, matching
        # the previous Inno-built naming (Scriptly-PC-Setup-<version>.exe).
        final_path = Path(f"Scriptly-PC-Setup-{APP_VER}.exe")
        for old in Path(".").glob("Scriptly-PC-Setup-*.exe"):
            old.unlink()
        shutil.move(str(built_installer), str(final_path))
        script.unlink(missing_ok=True)
        try:
            shutil.rmtree("build/installer_dist", ignore_errors=True)
            shutil.rmtree("build/pyinstaller-work", ignore_errors=True)
            for spec in Path("build").glob("Scriptly_PC_Setup.spec"):
                spec.unlink(missing_ok=True)
        except Exception:
            pass
        print(f"\nSUCCESS! Installer: {final_path} ({size:.1f} MB)")
    else:
        print("\nBUILD FAILED. Check output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
