"""Build Iron Bot shortcut icon from the helmet still."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "assets" / "ironman" / "helmet.jpg"
OUT_DIR = ROOT / "assets" / "icons"
PNG_OUT = OUT_DIR / "iron-bot.png"
ICO_OUT = OUT_DIR / "iron-bot.ico"
FRONT_DIR = ROOT / "frontend" / "assets" / "icons"
FRONT_PNG = FRONT_DIR / "iron-bot.png"
FRONT_ICO = FRONT_DIR / "iron-bot.ico"


def _helmet_crop(im: Image.Image) -> Image.Image:
    w, h = im.size
    side = min(w, int(h * 0.58))
    left = max(0, int(w * 0.05))
    if left + side > w:
        left = max(0, w - side)
    top = max(0, int(h * 0.04))
    if top + side > h:
        top = max(0, h - side)
    return im.crop((left, top, left + side, top + side))


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"Missing source image: {SRC}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FRONT_DIR.mkdir(parents=True, exist_ok=True)
    im = _helmet_crop(Image.open(SRC).convert("RGBA"))
    im256 = im.resize((256, 256), Image.Resampling.LANCZOS)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    for dest in (PNG_OUT, FRONT_PNG):
        im256.save(dest)
    for dest in (ICO_OUT, FRONT_ICO):
        im256.save(dest, format="ICO", sizes=sizes)
    print(f"Wrote {PNG_OUT}")
    print(f"Wrote {ICO_OUT}")


if __name__ == "__main__":
    main()
