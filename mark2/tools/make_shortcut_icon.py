"""Build Recon Sniper desktop shortcut icon from logo PNG."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "assets" / "images" / "airborne-sunset.png"
OUT_DIR = ROOT / "assets" / "icons"
PNG_OUT = OUT_DIR / "airborne-shortcut.png"
ICO_OUT = OUT_DIR / "airborne-shortcut.ico"


def _square_crop(im: Image.Image) -> Image.Image:
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return im.crop((left, top, left + side, top + side))


def _strip_black_bg(im: Image.Image, *, lum_cut: float = 28.0) -> Image.Image:
    out = im.convert("RGBA")
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            mx = max(r, g, b)
            if lum < lum_cut and mx < 40:
                px[x, y] = (r, g, b, 0)
            elif lum < 55 and mx < 70:
                t = (lum - lum_cut) / max(55 - lum_cut, 1.0)
                px[x, y] = (r, g, b, int(a * max(0.0, min(1.0, t))))
    return out


def _logo_crop(im: Image.Image) -> Image.Image:
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = min(int(h * 0.12), h - side)
    return im.crop((left, top, left + side, top + side))


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"Missing source image: {SRC}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    im = _logo_crop(Image.open(SRC).convert("RGBA"))
    im256 = im.resize((256, 256), Image.Resampling.LANCZOS)
    im256.save(PNG_OUT)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    im256.save(ICO_OUT, format="ICO", sizes=sizes)
    print(f"Wrote {PNG_OUT}")
    print(f"Wrote {ICO_OUT}")


if __name__ == "__main__":
    main()
