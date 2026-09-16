"""Decision log shows close-to-fire and no-fire EMA messages."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.engine import Mark2Engine


def test_ema_feed_close_and_no_fire() -> None:
    with tempfile.TemporaryDirectory() as td:
        cfg = Mark2Config()
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng.completed_bars = [{"time": "2026-09-10T02:00:00", "close": 23500.0}]
        eng._ema_feed(side="LONG", tag="WAIT_9_50", extra="CLOSE TO FIRE")
        eng._ema_feed(side="LONG", tag="WAIT_9_50", extra="CLOSE TO FIRE")
        eng._ema_feed(side="LONG", tag="TIGHT")
        eng._ema_feed(side="SHORT", tag="LONG_ONLY", extra="DID NOT FIRE")
        notes = [r["note"] for r in eng.recent_decisions if r.get("note")]
        assert len(notes) == 3
        assert notes[0].startswith("CLOSE · LONG ·")
        assert "WAITING 9 THROUGH 50" in notes[0].upper() or "waiting 9 through 50" in notes[0]
        assert notes[1].startswith("NO_FIRE · LONG ·")
        assert notes[2].startswith("NO_FIRE · SHORT ·")
        assert any(r.get("decision") == "CLOSE" for r in eng.recent_decisions)
        assert any(r.get("decision") == "NO_FIRE" for r in eng.recent_decisions)


def test_ema_feed_skips_idle() -> None:
    with tempfile.TemporaryDirectory() as td:
        cfg = Mark2Config()
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng._ema_feed(side="LONG", tag="NO_SNIPER")
        eng._ema_feed(side="LONG", tag="WAIT_SEP")
        assert not [r for r in eng.recent_decisions if r.get("event") == "EMA"]
