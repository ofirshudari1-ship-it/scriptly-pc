"""יוצר את הלוגו/אייקונים של Scriptly PC (סטטוס רגיל + מקליט) בלי תלות בקבצים חיצוניים."""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)

NAVY = (26, 43, 76, 255)
TEAL = (0, 181, 173, 255)
RED = (224, 64, 64, 255)
WHITE = (255, 255, 255, 255)


def draw_base(accent):
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.ellipse((8, 8, size - 8, size - 8), fill=NAVY)

    # soundwave bars
    bar_w = 14
    gaps = 8
    heights = [40, 80, 130, 90, 55, 100, 60]
    total_w = len(heights) * bar_w + (len(heights) - 1) * gaps
    x = (size - total_w) // 2
    cy = size // 2 - 10
    for h in heights:
        d.rounded_rectangle((x, cy - h // 2, x + bar_w, cy + h // 2), radius=bar_w // 2, fill=accent)
        x += bar_w + gaps

    # checkmark badge (bottom-right) - represents "tasks done"
    badge_r = 46
    bx, by = size - badge_r - 6, size - badge_r - 6
    d.ellipse((bx - badge_r, by - badge_r, bx + badge_r, by + badge_r), fill=WHITE)
    d.ellipse((bx - badge_r + 6, by - badge_r + 6, bx + badge_r - 6, by + badge_r - 6), fill=TEAL if accent != TEAL else NAVY)
    d.line((bx - 18, by, bx - 4, by + 16), fill=WHITE, width=8, joint="curve")
    d.line((bx - 4, by + 16, bx + 20, by - 14), fill=WHITE, width=8, joint="curve")

    return img


def save_multi(img, name):
    img.save(ASSETS / f"{name}.png")
    img.save(ASSETS / f"{name}.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    save_multi(draw_base(TEAL), "icon_idle")
    save_multi(draw_base(RED), "icon_recording")
    print("icons written to", ASSETS)
