"""מסך פתיחה (splash) - מוצג מיד עם הפעלת התוכנה, נסגר לבד, לא חוסם.
עונה על דרישת התקן: 1.5-2.5 שניות (מינימום 800ms גם אם הטעינה מהירה יותר,
כדי לא להבהב), לוגו+שם+גרסה+פס התקדמות+שורת סטטוס, בלי גבול חלון, פינות מעוגלות."""
import time
import tkinter as tk

from .config import APP_NAME, RESOURCE_ROOT, VERSION
from .i18n import t

ASSETS_DIR = RESOURCE_ROOT / "assets"

_MIN_DISPLAY_SECONDS = 0.8

BG = "#0f1420"
ACCENT = "#00b8ae"
TEXT = "#e9edf5"
TEXT_SOFT = "#8b93a5"


class SplashScreen:
    """Usage: splash = SplashScreen(); ... do startup work ...; splash.close()

    close() guarantees the splash stays visible at least _MIN_DISPLAY_SECONDS
    from creation, so a fast startup doesn't produce a jarring flash."""

    def __init__(self):
        self._shown_at = time.monotonic()
        self.root = tk.Tk()
        self.root.overrideredirect(True)  # no window border/titlebar
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)

        width, height = 420, 270
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        try:
            self.root.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        container = tk.Frame(self.root, bg=BG, highlightthickness=1, highlightbackground="#2a2f3d")
        container.place(x=0, y=0, relwidth=1, relheight=1)

        try:
            from PIL import Image, ImageTk

            img = Image.open(ASSETS_DIR / "icon_idle.png").resize((64, 64))
            self._logo_img = ImageTk.PhotoImage(img)
            tk.Label(container, image=self._logo_img, bg=BG).pack(pady=(30, 8))
        except Exception:
            tk.Label(container, text="🎙", font=("Segoe UI", 32), bg=BG, fg=ACCENT).pack(pady=(30, 8))

        tk.Label(container, text=APP_NAME, font=("Segoe UI", 16, "bold"), bg=BG, fg=TEXT).pack()
        tk.Label(container, text=f"v{VERSION}", font=("Segoe UI", 9), bg=BG, fg=TEXT_SOFT).pack(pady=(0, 16))

        self._progress_canvas = tk.Canvas(container, width=280, height=4, bg=BG, highlightthickness=0)
        self._progress_canvas.pack(pady=(4, 10))
        self._progress_bg = self._progress_canvas.create_rectangle(0, 0, 280, 4, fill="#2a2f3d", outline="")
        self._progress_bar = self._progress_canvas.create_rectangle(0, 0, 0, 4, fill=ACCENT, outline="")

        self.status_label = tk.Label(container, text=t("splash_status_starting"), font=("Segoe UI", 9), bg=BG, fg=TEXT_SOFT)
        self.status_label.pack()

        tk.Label(container, text=t("copyright_line"), font=("Segoe UI", 8), bg=BG, fg=TEXT_SOFT).pack(side="bottom", pady=(0, 10))

        self._fade_in_after_id = None
        self._progress_after_id = None

        self._fade_in()
        self._animate_progress(0)
        self.root.update()

    def _fade_in(self, alpha=0.0):
        alpha = min(alpha + 0.15, 1.0)
        try:
            self.root.attributes("-alpha", alpha)
        except tk.TclError:
            return
        if alpha < 1.0:
            self._fade_in_after_id = self.root.after(15, lambda: self._fade_in(alpha))

    def _animate_progress(self, width):
        width = min(width + 4, 280)
        self._progress_canvas.coords(self._progress_bar, 0, 0, width, 4)
        if width < 280:
            self._progress_after_id = self.root.after(25, lambda: self._animate_progress(width))
        else:
            self._progress_after_id = self.root.after(10, lambda: self._animate_progress(0))

    def set_status(self, text: str) -> None:
        try:
            self.status_label.configure(text=text)
            self.root.update()
        except tk.TclError:
            pass

    def close(self) -> None:
        elapsed = time.monotonic() - self._shown_at
        remaining = _MIN_DISPLAY_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)
        for after_id in (self._fade_in_after_id, self._progress_after_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
