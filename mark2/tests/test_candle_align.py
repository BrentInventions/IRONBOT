"""Candle alignment gate for Recon Sniper entries."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.candle_align import candle_alignment_ok, count_aligned, forming_bearish, forming_bullish
from mark2.types import Side


def _bar(o: float, c: float) -> dict:
    return {"open": o, "high": max(o, c) + 0.5, "low": min(o, c) - 0.5, "close": c}


def test_count_aligned_long():
    bars = [_bar(100, 101), _bar(101, 100.5), _bar(100.5, 101.5)]
    assert count_aligned(bars, Side.LONG, 3) == 2


def test_blocks_long_when_forming_red():
    bars = [_bar(100, 101), _bar(101, 102), _bar(102, 103)]
    ok, detail = candle_alignment_ok(
        bars,
        {"open": 104, "high": 104.5, "low": 103},
        price=103.5,
        side=Side.LONG,
        min_aligned=2,
        lookback=3,
    )
    assert not ok
    assert detail == "forming_not_bullish"


def test_passes_long_green_forming_and_velocity():
    bars = [_bar(100, 101), _bar(101, 102), _bar(102, 103)]
    ok, detail = candle_alignment_ok(
        bars,
        {"open": 103, "high": 104, "low": 103},
        price=103.75,
        side=Side.LONG,
        min_aligned=2,
        lookback=3,
        velocity=0.15,
    )
    assert ok
    assert "bars=3/3" in detail


def test_blocks_long_low_velocity():
    bars = [_bar(100, 101), _bar(101, 102), _bar(102, 103)]
    ok, detail = candle_alignment_ok(
        bars,
        {"open": 103, "high": 104, "low": 103},
        price=103.75,
        side=Side.LONG,
        min_aligned=2,
        velocity=0.02,
    )
    assert not ok
    assert "vel=" in detail


def test_relax_forming_allows_small_green_body():
    forming = {"open": 100.0, "high": 100.5, "low": 99.5}
    assert forming_bullish(forming, 100.1, min_body_ratio=0.5, relax=True)


def test_relax_forming_direction_skips_open_check():
    forming = {"open": 100.0, "high": 100.5, "low": 99.5}
    assert forming_bearish(forming, 100.25, relax_direction=True)
    assert not forming_bearish(forming, 100.25, relax=False)


def test_passes_with_one_aligned_bar():
    bars = [_bar(100, 99), _bar(99, 98.5), _bar(98.5, 99.5)]
    ok, detail = candle_alignment_ok(
        bars,
        {"open": 99.5, "high": 100, "low": 99.5},
        price=99.75,
        side=Side.LONG,
        min_aligned=1,
        lookback=3,
        velocity=0.15,
    )
    assert ok
    assert "bars=1/3" in detail
