"""Draws the app icon (assets/icon.png, icon.ico and icon.icns) with shapes only, so it looks the same on every machine.
    python tools/make_icon.py"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets"
S = 1024  # drawn large, then shrunk for smooth edges


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # a vertical gradient tile: deep indigo to teal
    top, bot = (52, 48, 120), (22, 120, 130)
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=255)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    # three rising bars (the runway) and a coin
    base = 760
    for i, h in enumerate((200, 330, 470)):
        x = 250 + i * 190
        d.rounded_rectangle((x, base - h, x + 130, base), radius=34, fill=(255, 255, 255, 235))
    d.ellipse((600, 200, 800, 400), fill=(250, 204, 21, 255), outline=(255, 255, 255, 255), width=14)
    d.rounded_rectangle((690, 252, 710, 348), radius=8, fill=(160, 120, 0, 255))
    return im


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    big = draw()
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    big.resize((1024, 1024), Image.LANCZOS).save(OUT / "icon.icns")  # the Mac app icon
    print("wrote icon.png, icon.ico and icon.icns in", OUT)
