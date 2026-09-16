"""python -m mark2 — Recon Sniper Night Shell HUD."""

from __future__ import annotations

import os
import traceback
from pathlib import Path


def _crash_log(msg: str) -> None:
    try:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
        path = Path(base) / "ReconSniper" / "logs" / "hud_runtime.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(msg)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        from .hud import main

        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        _crash_log(traceback.format_exc())
        raise
