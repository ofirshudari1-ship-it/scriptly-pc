"""Generates the branded Inno Setup wizard images (WizardImageFile/WizardSmallImageFile)
so the installer uses Scriptly PC's own navy/teal identity instead of Inno's generic grey
default - same palette as app/dashboard.py's C dict and assets/BRAND.md, same soundwave+
checkmark mark as build/generate_icons.py (not a different logo drawn separately)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)

NAVY = (21, 40, 71)
NAVY_DARK = (12, 20, 36)
TEAL = (0, 184, 174)
WHITE = (255, 255, 255)
TEXT_SOFT = (139, 147, 165)


def _soundwave_mark(size, accent=TEAL):
    """Same mark as build/generate_icons.py, redrawn at whatever size the banner needs."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((size * 0.03, size * 0.03, size * 0.97, size * 0.97), fill=NAVY)
    bar_w = max(2, int(size * 0.055))
    gap = max(1, int(size * 0.03))
    heights = [0.16, 0.31, 0.51, 0.35, 0.22, 0.39, 0.23]
    total_w = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (size - total_w) / 2
    cy = size / 2 - size * 0.04
    for h_ratio in heights:
        h = size * h_ratio
        d.rounded_rectangle((x, cy - h / 2, x + bar_w, cy + h / 2), radius=bar_w / 2, fill=accent)
        x += bar_w + gap
    return img


def _font(size, bold=False):
    candidates = (
        ["segoeuib.ttf"] if bold else ["segoeui.ttf"]
    ) + ["arialbd.ttf" if bold else "arial.ttf"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_wizard_image():
    """164x314 - shown full-height on the Welcome/Finished pages."""
    w, h = 164, 314
    img = Image.new("RGB", (w, h), NAVY)
    d = ImageDraw.Draw(img)

    # subtle vertical gradient for depth, navy -> darker navy
    for y in range(h):
        t = y / h
        r = int(NAVY[0] * (1 - t) + NAVY_DARK[0] * t)
        g = int(NAVY[1] * (1 - t) + NAVY_DARK[1] * t)
        b = int(NAVY[2] * (1 - t) + NAVY_DARK[2] * t)
        d.line([(0, y), (w, y)], fill=(r, g, b))

    mark = _soundwave_mark(88)
    img.paste(mark, ((w - 88) // 2, 56), mark)

    font_title = _font(17, bold=True)
    title = "Scriptly PC"
    bbox = d.textbbox((0, 0), title, font=font_title)
    d.text(((w - (bbox[2] - bbox[0])) // 2, 168), title, font=font_title, fill=WHITE)

    font_sub = _font(10)
    sub = "Record. Transcribe."
    bbox = d.textbbox((0, 0), sub, font=font_sub)
    d.text(((w - (bbox[2] - bbox[0])) // 2, 194), sub, font=font_sub, fill=TEAL)
    sub2 = "Summarize."
    bbox = d.textbbox((0, 0), sub2, font=font_sub)
    d.text(((w - (bbox[2] - bbox[0])) // 2, 210), sub2, font=font_sub, fill=TEAL)

    out = ASSETS / "installer_wizard.bmp"
    img.save(out, "BMP")
    print("wrote", out)


def make_wizard_small_image():
    """55x58 - shown top-right on every inner wizard page."""
    w, h = 55, 58
    img = Image.new("RGB", (w, h), NAVY)
    mark = _soundwave_mark(44)
    img.paste(mark, ((w - 44) // 2, (h - 44) // 2), mark)
    out = ASSETS / "installer_wizard_small.bmp"
    img.save(out, "BMP")
    print("wrote", out)


if __name__ == "__main__":
    make_wizard_image()
    make_wizard_small_image()
