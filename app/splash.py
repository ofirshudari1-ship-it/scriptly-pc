"""מסך פתיחה (splash) - מוצג מיד עם הפעלת התוכנה, נסגר לבד, לא חוסם.

עונה על _AUDIT/STANDARDS.md §19 (תבנית מחייבת לכל הכלים):
- רקע גרדיאנט בצבעי המותג האמיתיים של Scriptly PC (navy הכותרת -> teal ה-accent,
  ראו assets/BRAND.md), לא רקע אחיד/גנרי.
- הלוגו האמיתי (icon_idle.png) הוא האלמנט הדומיננטי - גדול ובמרכז.
- חלון ללא מסגרת, עם fade-in לשקיפות חלקית (alpha) ופינות מעוגלות אמיתיות
  (חיתוך צורת החלון ב-Win32 SetWindowRgn - Tkinter אין לו rounded-corners
  מובנה כמו CSS border-radius, זה השקול הנכון ב-Windows API).
- Spinner מסתובב ורציף (קשת שמסתובבת), לא פס התקדמות מזויף.
- מינימום 800ms תצוגה נאכף בקוד (close() ממתין את ההפרש) + timeout בטיחות
  של 8 שניות שמבטיח שה-splash לא יכול להישאר תקוע לנצח.
- החלון הראשי (app/main.py) נוצר רק אחרי splash.close() - אין הבהוב.
"""
import time
import tkinter as tk

from .config import APP_NAME, RESOURCE_ROOT, VERSION
from .i18n import t

ASSETS_DIR = RESOURCE_ROOT / "assets"

_MIN_DISPLAY_SECONDS = 0.8
_SAFETY_TIMEOUT_SECONDS = 8.0

# צבעי המותג האמיתיים של Scriptly PC (assets/BRAND.md): הכותרת הכהה (navy)
# והצבע הראשי (teal). הגרדיאנט עצמו ייחודי לכלי הזה, לא ברירת מחדל גנרית.
GRAD_TOP = (0x0C, 0x14, 0x24)  # header_alt (dark) - #0c1424
GRAD_BOTTOM = (0x00, 0xB8, 0xAE)  # teal (primary/accent) - #00b8ae
ACCENT = "#00b8ae"
TEXT = "#e9edf5"
TEXT_SOFT = "#8b93a5"
BORDER = "#2a2f3d"

_WIDTH, _HEIGHT = 460, 300
_CORNER_RADIUS = 18
_LOGO_SIZE = 140


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


class SplashScreen:
    """Usage: splash = SplashScreen(); ... do startup work ...; splash.close()

    close() guarantees the splash stays visible at least _MIN_DISPLAY_SECONDS
    from creation, so a fast startup doesn't produce a jarring flash. A
    self-rescheduling safety timer also force-closes the splash after
    _SAFETY_TIMEOUT_SECONDS even if the caller never calls close() (e.g. a
    stuck startup step), so the splash can never block the app forever."""

    def __init__(self):
        self._shown_at = time.monotonic()
        self._closed = False

        self.root = tk.Tk()
        self.root.overrideredirect(True)  # no window border/titlebar
        self.root.attributes("-topmost", True)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - _WIDTH) // 2
        y = (screen_h - _HEIGHT) // 2
        self.root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

        try:
            self.root.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        self._canvas = tk.Canvas(self.root, width=_WIDTH, height=_HEIGHT, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)

        self._draw_gradient_background()
        self._round_window_corners()

        self._draw_logo()

        self._canvas.create_text(
            _WIDTH // 2, 196, text=APP_NAME, font=("Segoe UI", 17, "bold"), fill=TEXT
        )
        self._canvas.create_text(
            _WIDTH // 2, 218, text=f"v{VERSION}", font=("Segoe UI", 9), fill=TEXT_SOFT
        )

        self._spinner_center = (_WIDTH // 2, 248)
        self._spinner_radius = 11
        self._spinner_angle = 0
        self._spinner_arc = self._canvas.create_arc(
            self._spinner_center[0] - self._spinner_radius,
            self._spinner_center[1] - self._spinner_radius,
            self._spinner_center[0] + self._spinner_radius,
            self._spinner_center[1] + self._spinner_radius,
            start=0,
            extent=100,
            style="arc",
            outline=ACCENT,
            width=3,
        )
        self._canvas.create_oval(
            self._spinner_center[0] - self._spinner_radius,
            self._spinner_center[1] - self._spinner_radius,
            self._spinner_center[0] + self._spinner_radius,
            self._spinner_center[1] + self._spinner_radius,
            outline=BORDER,
            width=1,
        )

        self.status_label_id = self._canvas.create_text(
            _WIDTH // 2, 272, text=t("splash_status_starting"), font=("Segoe UI", 9), fill=TEXT_SOFT
        )

        self._canvas.create_text(
            _WIDTH // 2, _HEIGHT - 14, text=t("copyright_line"), font=("Segoe UI", 8), fill=TEXT_SOFT
        )

        self._fade_in_after_id = None
        self._spinner_after_id = None
        self._timeout_after_id = None

        self._fade_in()
        self._spin()
        self._timeout_after_id = self.root.after(
            int(_SAFETY_TIMEOUT_SECONDS * 1000), self._on_safety_timeout
        )
        self.root.update()

    # -- drawing -----------------------------------------------------

    def _draw_gradient_background(self) -> None:
        """Vertical gradient in the tool's own brand colors (navy -> teal),
        eased so text near the top stays over the darker portion for contrast."""
        steps = 90
        for i in range(steps):
            t_lin = i / (steps - 1)
            t_eased = t_lin**1.6  # keep more of the gradient dark near the top
            r = _lerp(GRAD_TOP[0], GRAD_BOTTOM[0], t_eased)
            g = _lerp(GRAD_TOP[1], GRAD_BOTTOM[1], t_eased)
            b = _lerp(GRAD_TOP[2], GRAD_BOTTOM[2], t_eased)
            color = f"#{r:02x}{g:02x}{b:02x}"
            y0 = int(_HEIGHT * i / steps)
            y1 = int(_HEIGHT * (i + 1) / steps) + 1
            self._canvas.create_rectangle(0, y0, _WIDTH, y1, fill=color, outline="")

    def _draw_logo(self) -> None:
        try:
            from PIL import Image, ImageTk

            resample = getattr(Image, "Resampling", Image).LANCZOS
            img = Image.open(ASSETS_DIR / "icon_idle.png").resize((_LOGO_SIZE, _LOGO_SIZE), resample)
            self._logo_img = ImageTk.PhotoImage(img)
            self._canvas.create_image(_WIDTH // 2, 100, image=self._logo_img)
        except Exception:
            self._canvas.create_text(
                _WIDTH // 2, 100, text="🎙", font=("Segoe UI", 56), fill=ACCENT
            )

    def _round_window_corners(self) -> None:
        """Real rounded window shape via the Win32 region API - the Windows
        equivalent of CSS border-radius on a frameless/transparent window
        (Tkinter has no cross-platform rounded-corner primitive)."""
        try:
            import ctypes

            self.root.update_idletasks()
            hwnd = self.root.winfo_id()
            region = ctypes.windll.gdi32.CreateRoundRectRgn(
                0, 0, _WIDTH + 1, _HEIGHT + 1, _CORNER_RADIUS, _CORNER_RADIUS
            )
            ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
        except Exception:
            pass  # non-Windows / API unavailable: falls back to square corners

    # -- animation ----------------------------------------------------

    def _fade_in(self, alpha=0.0):
        # Stops just short of fully opaque (0.97) so the window keeps a subtle
        # translucent quality even once settled, per §19.1.
        alpha = min(alpha + 0.12, 0.97)
        try:
            self.root.attributes("-alpha", alpha)
        except tk.TclError:
            return
        if alpha < 0.97:
            self._fade_in_after_id = self.root.after(15, lambda: self._fade_in(alpha))

    def _spin(self):
        self._spinner_angle = (self._spinner_angle + 9) % 360
        try:
            self._canvas.itemconfigure(self._spinner_arc, start=self._spinner_angle)
        except tk.TclError:
            return
        self._spinner_after_id = self.root.after(30, self._spin)

    def _on_safety_timeout(self) -> None:
        self._timeout_after_id = None
        self.close()

    # -- public API -----------------------------------------------------

    def set_status(self, text: str) -> None:
        try:
            self._canvas.itemconfigure(self.status_label_id, text=text)
            self.root.update()
        except tk.TclError:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        elapsed = time.monotonic() - self._shown_at
        remaining = _MIN_DISPLAY_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)

        for after_id in (self._fade_in_after_id, self._spinner_after_id, self._timeout_after_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
