"""Writable app folder vs bundled resources (PyInstaller)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_home() -> Path:
    env = os.environ.get("RECON_APP_HOME", "").strip()
    if env:
        return Path(env)
    if frozen():
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve()
    return here.parents[1].parent


def bundle_root() -> Path:
    if frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def frontend_dir() -> Path:
    env = os.environ.get("MARK2_FRONTEND", "").strip()
    if env:
        override = Path(env)
        if override.is_dir():
            return override
    bundled = bundle_root() / "frontend"
    if bundled.is_dir():
        return bundled
    return Path(__file__).resolve().parents[1] / "frontend"
