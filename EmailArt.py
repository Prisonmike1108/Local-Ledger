"""
EmailArt.py - draws the small looping animation at the top of each season's payday email (needs Pillow).

    snow for winter, petals for spring, a turning sun for summer, leaves for fall

Mail apps don't run CSS animations (Gmail removes them), so the movement is an animated GIF. Each one is drawn once,
kept in ./email_assets, and loops seamlessly: every piece travels a whole number of laps and turns per loop.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 600, 48           # size in the email
SS = 2                   # drawn at twice the size, then shrunk, for smooth edges
FRAMES, FRAME_MS = 48, 80
PAD = 16                 # how far above/below the strip a piece travels, so it never pops in or out
OUT = Path(__file__).resolve().parent / "email_assets"
VERSION = "v7"       # bump to redraw everything


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _tile(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def _flake(r: float, color, alpha: int) -> Image.Image:
    s = int(r * 2 * SS) + 4
    im, d = _tile(s)
    d.ellipse((2, 2, s - 2, s - 2), fill=(*color, alpha))
    return im


def _star(r: float, color, alpha: int) -> Image.Image:
    """A six-armed snowflake."""
    s = int(r * 2 * SS) + 6
    im, d = _tile(s)
    c = s / 2
    for k in range(3):
        a = math.pi * k / 3
        dx, dy = math.cos(a) * (c - 3), math.sin(a) * (c - 3)
        d.line((c - dx, c - dy, c + dx, c + dy), fill=(*color, alpha), width=max(2, SS))
    return im


def _leaf(size: float, color, alpha: int) -> Image.Image:
    """A pointed leaf with a midrib and a short stem."""
    s = int(size * SS) + 8
    im, d = _tile(s)
    c, half, fat = s / 2, s / 2 - 4, (s / 2 - 4) * 0.46
    pts = [(c + half * math.cos(t), c + fat * math.sin(t) * (1 - 0.35 * math.cos(t) ** 2))
           for t in [2 * math.pi * k / 40 for k in range(40)]]
    d.polygon(pts, fill=(*color, alpha))
    dark = tuple(int(v * .72) for v in color)
    d.line((c - half, c, c + half * .8, c), fill=(*dark, alpha), width=max(1, SS))
    d.line((c - half - 3, c + 2, c - half, c), fill=(*dark, alpha), width=max(2, SS))
    return im


def _petal(size: float, color, alpha: int) -> Image.Image:
    s = int(size * SS) + 6
    im, d = _tile(s)
    c, half = s / 2, s / 2 - 3
    d.ellipse((c - half, c - half * .58, c + half, c + half * .58), fill=(*color, alpha))
    return im


def _sparkle(r: float, color, alpha: int) -> Image.Image:
    """A four-point twinkle."""
    s = int(r * 2 * SS) + 6
    im, d = _tile(s)
    c, a, b = s / 2, s / 2 - 3, (s / 2 - 3) * .22
    d.polygon([(c, c - a), (c + b, c - b), (c + a, c), (c + b, c + b), (c, c + a), (c - b, c + b), (c - a, c),
               (c - b, c - b)], fill=(*color, alpha))
    return im


def _paste(base: Image.Image, tile: Image.Image, x: float, y: float, angle: float = 0.0) -> None:
    if angle:
        tile = tile.rotate(angle, resample=Image.BICUBIC, expand=True)
    px, py = int(x * SS - tile.width / 2), int(y * SS - tile.height / 2)
    if px >= base.width or py >= base.height or px + tile.width <= 0 or py + tile.height <= 0:
        return  # fully off the strip
    if px >= 0 and py >= 0 and px + tile.width <= base.width and py + tile.height <= base.height:
        base.alpha_composite(tile, (px, py))
    else:  # alpha_composite can't hang off an edge, so a piece crossing one goes through a same-size layer
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        layer.paste(tile, (px, py))
        base.alpha_composite(layer)


def _falling(rng: random.Random, n: int, make, sizes, colors, alphas, sway=(5, 16), spins=(0,), laps=(1, 1, 2), w=W, h=H):
    """n drifting pieces, each with its own start, speed (whole laps per loop), sway and spin."""
    span = h + 2 * PAD
    out = []
    for _ in range(n):
        size = rng.uniform(*sizes)
        out.append(dict(tile=make(size, rng.choice(colors), rng.randint(*alphas)), x0=rng.uniform(0, w), w=w, span=span,
                        y0=rng.uniform(0, span), laps=rng.choice(laps), amp=rng.uniform(*sway),
                        waves=rng.choice((1, 2)), phase=rng.uniform(0, 2 * math.pi), spin=rng.choice(spins),
                        a0=rng.uniform(0, 360)))
    return out


def _draw_falling(base: Image.Image, pieces: list[dict], t: float) -> None:
    for p in pieces:
        span = p["span"]
        y = (p["y0"] + p["laps"] * span * t) % span - PAD
        x = (p["x0"] + p["amp"] * math.sin(2 * math.pi * p["waves"] * t + p["phase"])) % p["w"]
        _paste(base, p["tile"], x, y, (p["a0"] + 360 * p["spin"] * t) if p["spin"] else 0.0)


def _sun(base: Image.Image, t: float, color) -> None:
    """A glowing sun whose rays turn one ray-step per loop (so the loop is seamless) and breathe in and out."""
    cx, cy, r, rays = W / 2 * SS, 24 * SS, 10 * SS, 12
    for k, a in enumerate((34, 22, 12)):  # soft glow: each ring on its own layer so it blends instead of covering
        g = r + (9 + 8 * k) * SS
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse((cx - g, cy - g, cx + g, cy + g), fill=(*color, a))
        base.alpha_composite(layer)
    d = ImageDraw.Draw(base)
    turn = 2 * math.pi / rays * t
    for k in range(rays):
        a = turn + 2 * math.pi * k / rays
        grow = 1 + 0.22 * math.sin(2 * math.pi * 2 * t + k * math.pi)  # alternate rays pulse opposite ways
        r1, r2 = r + 5 * SS, r + (5 + 10 * grow) * SS
        d.line((cx + r1 * math.cos(a), cy + r1 * math.sin(a), cx + r2 * math.cos(a), cy + r2 * math.sin(a)),
               fill=(*color, 235), width=3 * SS)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, 255))


def _frames(season: str, head: tuple[int, int, int]) -> list[Image.Image]:
    rng = random.Random(f"ledger-{season}")
    white = (255, 255, 255)
    if season == "winter":
        pieces = (_falling(rng, 18, _flake, (1.2, 3.4), [white, (214, 234, 248)], (120, 235), sway=(3, 10))
                  + _falling(rng, 4, _star, (5, 8), [white], (170, 240), sway=(4, 12), spins=(-1, 1), laps=(1,)))
    elif season == "spring":
        pieces = _falling(rng, 13, _petal, (9, 16), [(255, 170, 200), (255, 205, 222), (255, 240, 245), (247, 130, 172)],
                          (235, 255), sway=(8, 22), spins=(-2, -1, 1, 2), laps=(1,))
    elif season == "fall":
        pieces = _falling(rng, 10, _leaf, (14, 24), [(229, 138, 31), (242, 178, 62), (201, 78, 30), (236, 110, 40),
                                                     (250, 204, 96)], (215, 255), sway=(10, 26),
                          spins=(-2, -1, 1, 2), laps=(1,))
    else:  # summer: twinkles around a turning sun
        pieces = [dict(x=rng.uniform(20, W - 20), y=rng.uniform(10, H - 10), r=rng.uniform(4, 8),
                       waves=rng.choice((1, 2)), phase=rng.uniform(0, 2 * math.pi)) for _ in range(10)]
        pieces = [p for p in pieces if abs(p["x"] - W / 2) > 70]  # keep them clear of the sun
    crng = random.Random(f"confetti-header-{season}")
    conf = _falling(crng, 6, _confetti_maker(crng), *CALM_CONFETTI, sway=(3, 9), spins=(-2, -1, 1, 2), laps=(1,))
    out = []
    for k in range(FRAMES):
        t = k / FRAMES
        base = Image.new("RGBA", (W * SS, H * SS), (*head, 255))
        if season == "summer":
            _sun(base, t, (255, 201, 60))
            for p in pieces:
                glow = 0.5 + 0.5 * math.sin(2 * math.pi * p["waves"] * t + p["phase"])
                _paste(base, _sparkle(p["r"] * (0.6 + 0.4 * glow), (255, 236, 170), int(60 + 180 * glow)), p["x"], p["y"])
        else:
            _draw_falling(base, pieces, t)
        _draw_falling(base, conf, t)  # confetti falls over everything
        out.append(base.convert("RGB").resize((W, H), Image.LANCZOS))
    return out


def ensure_gif(season: str, head_hex: str) -> Path:
    """The season's header animation on the given header color, drawn the first time it's asked for."""
    path = OUT / f"{season}_{head_hex.lstrip('#').lower()}_{VERSION}.gif"
    if path.exists():
        return path
    OUT.mkdir(parents=True, exist_ok=True)
    frames = _frames(season, _rgb(head_hex))
    sheet = Image.new("RGB", (W, H * 4))  # one shared palette (from a few spread-out frames) keeps the file small
    for n, k in enumerate((0, FRAMES // 4, FRAMES // 2, 3 * FRAMES // 4)):
        sheet.paste(frames[k], (0, H * n))
    pal = sheet.quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    quant = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    quant[0].save(path, save_all=True, append_images=quant[1:], duration=FRAME_MS, loop=0, optimize=False, disposal=1)
    return path


CONF_COLORS = [(255, 89, 94), (255, 202, 58), (138, 201, 38), (25, 130, 196), (106, 76, 147), (255, 159, 243),
               (255, 146, 76)]


# a calm confetti: small pieces in soft, see-through colors (size range, colors, opacity range)
CALM_CONFETTI = ((4, 8), CONF_COLORS, (140, 205))


def _confetti_maker(rng: random.Random):
    """Little bars, dots and triangles, in party colors."""
    def make(size: float, color, alpha: int) -> Image.Image:
        s = int(size * SS) + 6
        im, d = _tile(s)
        c, kind = s / 2, rng.choice(("bar", "bar", "dot", "tri"))
        fill = (*color, alpha)
        if kind == "dot":
            d.ellipse((c - s * .28, c - s * .28, c + s * .28, c + s * .28), fill=fill)
        elif kind == "tri":
            d.polygon([(c, c - s * .34), (c + s * .34, c + s * .28), (c - s * .34, c + s * .28)], fill=fill)
        else:
            d.rectangle((c - s * .42, c - s * .15, c + s * .42, c + s * .15), fill=fill)
        return im
    return make


def _save_exact(frames: list[Image.Image], path: Path, ms: int, colors: int, bg: tuple[int, int, int]) -> None:
    """Save frames as a looping GIF whose background is EXACTLY `bg`, so it melts into the email around it."""
    import numpy as np
    step = max(1, len(frames) // 6)
    pick = frames[::step][:6]
    sheet = Image.new("RGB", (frames[0].width, frames[0].height * len(pick)))
    for n, f in enumerate(pick):
        sheet.paste(f, (0, f.height * n))
    pal = sheet.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    p_ = pal.getpalette()[:colors * 3]
    near = min(range(colors), key=lambda i: sum((bg[j] - p_[i * 3 + j]) ** 2 for j in range(3)))
    p_[near * 3:near * 3 + 3] = list(bg)
    rgb = np.array(p_, dtype=int).reshape(-1, 3)

    def to_p(frame):
        px = np.asarray(frame, dtype=int).reshape(-1, 1, 3)
        idx = ((px - rgb[None]) ** 2).sum(axis=2).argmin(axis=1).astype("uint8").reshape(frame.height, frame.width)
        out = Image.fromarray(idx, "P")
        out.putpalette(p_)
        return out

    q = [to_p(f) for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:], duration=ms, loop=0, optimize=False, disposal=1)


def ensure_confetti(kind: str, bg_hex: str) -> Path:
    """A looping confetti fall. "band" is a thin strip across the card; "side" is a tall column for the margins.
    The same file is shown many times in the email, so it only travels once."""
    w, h, n, laps = (600, 48, 9, (1,)) if kind == "band" else (130, 420, 8, (1,))
    path = OUT / f"confetti_{kind}_{bg_hex.lstrip('#').lower()}_{VERSION}.gif"
    if path.exists():
        return path
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(f"confetti-{kind}")
    pieces = _falling(rng, n, _confetti_maker(rng), *CALM_CONFETTI, sway=(3, 9), spins=(-2, -1, 1, 2), laps=laps,
                      w=w, h=h)
    bg, frames = _rgb(bg_hex), []
    for k in range(36):
        base = Image.new("RGBA", (w * SS, h * SS), (*bg, 255))
        _draw_falling(base, pieces, k / 36)
        frames.append(base.convert("RGB").resize((w, h), Image.LANCZOS))
    _save_exact(frames, path, 70, 48, bg)
    return path


WALK_FRAMES, WALK_MS, WALK_H = 60, 110, 36   # one slow loop (about 6.6s): out to the far end and back, 36px tall


def ensure_walker(name: str, x_frac: float = 0.5) -> Path:
    """A confetti strip (same size and white as the plain ones) with one Pokemon standing in one spot along the bottom,
    waddling gently as if strolling, so it moves without going anywhere. `x_frac` is where along the strip it stands
    (0 = left edge, 1 = right edge). Drawn once per Pokemon and spot, and kept."""
    path = OUT / f"walk_{VERSION}_{name}_{int(round(x_frac * 100))}.gif"
    if path.exists():
        return path
    src = POKEMON_DIR / f"{name}.png"
    if not src.exists() and name == "pikachu":
        src = OUT / "pikachu.png"
    if not src.exists():
        raise FileNotFoundError(f"{src} is missing")
    OUT.mkdir(parents=True, exist_ok=True)
    w, h = 600, 48
    sprite = Image.open(src).convert("RGBA")
    sprite = sprite.crop(sprite.getbbox())
    sprite = sprite.resize((max(1, int(sprite.width * WALK_H * SS / sprite.height)), WALK_H * SS), Image.LANCZOS)
    rng = random.Random("confetti-band")   # the same calm confetti as the plain band, over a longer loop (3 laps)
    pieces = _falling(rng, 9, _confetti_maker(rng), *CALM_CONFETTI, sway=(3, 9), spins=(-2, -1, 1, 2), laps=(3,),
                      w=w, h=h)
    bg, frames = (255, 255, 255), []
    x = min(max(x_frac, 0.1), 0.9) * w * SS
    for k in range(WALK_FRAMES):
        t = k / WALK_FRAMES
        base = Image.new("RGBA", (w * SS, h * SS), (*bg, 255))
        _draw_falling(base, pieces, t)
        step = math.sin(2 * math.pi * 7 * t)                          # seven waddles per loop
        y = h * SS - 4 * SS - sprite.height / 2 - abs(step) * 3 * SS
        img = sprite.rotate(-4 * step, resample=Image.BICUBIC, expand=True)
        base.alpha_composite(img, (int(x - img.width / 2), int(y - img.height / 2)))
        frames.append(base.convert("RGB").resize((w, h), Image.LANCZOS))
    _save_exact(frames, path, WALK_MS, 64, bg)
    return path


ZIP_W, ZIP_H, ZIP_FRAMES, ZIP_MS = 600, 130, 40, 60


def _dance_frame(sprites: list[Image.Image], t: float) -> Image.Image:
    """Each Pokemon stays in its own spot across the strip (evenly spaced) and dances there: hopping, swaying side to
    side and squashing a little on each landing. With several, they bounce a beat apart. t runs 0..1; the loop ends
    exactly where it starts."""
    base = Image.new("RGBA", (ZIP_W, ZIP_H), (255, 255, 255, 255))
    fx = Image.new("RGBA", base.size, (0, 0, 0, 0))   # shadows on their own layer, so they blend
    d = ImageDraw.Draw(fx)
    placed = []
    n = len(sprites)
    for k, sprite in enumerate(sprites):
        tk = (t + k / (2 * n)) % 1.0
        cx = ZIP_W * (k + 0.5) / n
        hop = abs(math.sin(2 * math.pi * 3 * tk))                   # three hops per loop
        sway = math.sin(2 * math.pi * 3 * tk + math.pi / 2)          # leans one way, then the other, with each hop
        squash = 1 - 0.07 * (1 - hop) ** 4                           # a little flatter right at the landing
        img = sprite.resize((max(1, int(sprite.width * (2 - squash))), max(1, int(sprite.height * squash))), Image.LANCZOS)
        img = img.rotate(-7 * sway, resample=Image.BICUBIC, expand=True)
        y = ZIP_H - 8 - img.height / 2 - hop * 20
        shadow_w = 46 * (1 - 0.35 * hop)
        d.ellipse((cx - shadow_w / 2, ZIP_H - 12, cx + shadow_w / 2, ZIP_H - 4), fill=(0, 0, 0, 38))
        placed.append((img, cx, y))
    base.alpha_composite(fx)
    for img, x, y in placed:
        base.alpha_composite(img, (int(x - img.width / 2), int(y - img.height / 2)))
    return base.convert("RGB")


POKEMON_DIR = OUT / "pokemon"   # one transparent PNG per Pokemon; the file name (without .png) is its name


def ensure_pokemon(names: list[str]) -> Path:
    """The strip for the bottom of the email: the chosen Pokemon (pictures in email_assets/pokemon), each dancing in its
    own spot. Drawn once per combination and kept."""
    names = [n for n in names if (POKEMON_DIR / f"{n}.png").exists() or (n == "pikachu" and (OUT / "pikachu.png").exists())]
    if not names:
        raise FileNotFoundError("none of the chosen Pokemon pictures were found")
    import hashlib
    tag = "" if names == ["pikachu"] else "_" + hashlib.md5(",".join(names).encode()).hexdigest()[:8]
    path = OUT / f"zip_{VERSION}{tag}.gif"
    if path.exists():
        return path
    height = {1: 92, 2: 78, 3: 66}.get(len(names), 56)
    sprites = []
    for n in names:
        src = POKEMON_DIR / f"{n}.png"
        sprite = Image.open(src if src.exists() else OUT / "pikachu.png").convert("RGBA")
        sprite = sprite.crop(sprite.getbbox())
        sprites.append(sprite.resize((max(1, int(sprite.width * height / sprite.height)), height), Image.LANCZOS))
    frames = [_dance_frame(sprites, k / ZIP_FRAMES) for k in range(ZIP_FRAMES)]
    sheet = Image.new("RGB", (ZIP_W, ZIP_H * 5))
    for n, k in enumerate((0, 8, 16, 24, 32)):
        sheet.paste(frames[k], (0, ZIP_H * n))
    pal = sheet.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    p_ = pal.getpalette()[:384]
    near = min(range(128), key=lambda i: sum((255 - v) ** 2 for v in p_[i * 3:i * 3 + 3]))
    p_[near * 3:near * 3 + 3] = [255, 255, 255]  # the background must be exactly the card's white
    import numpy as np
    rgb = np.array(p_, dtype=int).reshape(-1, 3)

    def to_p(frame):  # nearest palette color, worked out here so white stays exactly white
        px = np.asarray(frame, dtype=int).reshape(-1, 1, 3)
        idx = ((px - rgb[None]) ** 2).sum(axis=2).argmin(axis=1).astype("uint8").reshape(frame.height, frame.width)
        out = Image.fromarray(idx, "P")
        out.putpalette(p_)
        return out

    quant = [to_p(f) for f in frames]
    quant[0].save(path, save_all=True, append_images=quant[1:], duration=ZIP_MS, loop=0, optimize=False, disposal=1)
    return path

if __name__ == "__main__":
    print(ensure_confetti("band", "#ffffff").name, ensure_confetti("side", "#f9f2ea").name)
    print(ensure_pokemon(["pikachu"]).name)
    for name, color in (("winter", "#1d3557"), ("spring", "#2d6a4f"), ("summer", "#0b6e8f"), ("fall", "#7a3b12")):
        p = ensure_gif(name, color)
        print(p.name, f"{p.stat().st_size / 1024:.0f} KB")
