"""Iron Man HUD font (Audiowide — OFL). Registers for this process and for NinjaTrader."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

FONT_FAMILY = "Audiowide"
IRON_RED = "#E10600"
IRON_RED_DIM = "#7A0C10"
IRON_GOLD = "#FFB347"
IRON_BG = "#050203"


def font_file() -> Path:
    return Path(__file__).resolve().parent / "assets" / "fonts" / "Audiowide-Regular.ttf"


def register_ironman_font() -> str:
    """Load Audiowide for this process and install it for the current Windows user."""
    src = font_file()
    if not src.is_file():
        return FONT_FAMILY
    if os.name != "nt":
        return FONT_FAMILY
    try:
        import ctypes

        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        FR_PRIVATE = 0x10
        gdi32.AddFontResourceExW(str(src), FR_PRIVATE, 0)
        fonts = Path(os.environ.get("LOCALAPPDATA") or "") / "Microsoft" / "Windows" / "Fonts"
        fonts.mkdir(parents=True, exist_ok=True)
        dest = fonts / src.name
        if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        gdi32.AddFontResourceW(str(dest))
        try:
            import winreg

            key = winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts",
            )
            winreg.SetValueEx(key, "Audiowide Regular (TrueType)", 0, winreg.REG_SZ, dest.name)
            winreg.CloseKey(key)
        except OSError:
            pass
        user32.PostMessageW(0xFFFF, 0x001D, 0, 0)
    except Exception:
        pass
    return FONT_FAMILY
