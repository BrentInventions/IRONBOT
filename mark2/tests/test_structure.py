"""Structure classification and entry gate tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.bias_entry import bias_entry_gates
from mark2.config import Mark2Config
from mark2.context import structure_state
from mark2.structure_gate import structure_blocks_entry
from mark2.types import MarketSnapshot, Side


def _bar(i: int, o: float, h: float, lo: float, c: float) -> dict:
    return {"time": f"b{i}", "open": o, "high": h, "low": lo, "close": c, "volume": 1000}


def _uptrend_then_dump() -> list[dict]:
    """Prior HH_HL pivots, then sharp selloff — reproduces stale pivot lag."""
    bars: list[dict] = []
    base = 27800.0
    for i in range(15):
        if i % 3 == 0:
            lo, hi, c = base, base + 8, base + 4
        elif i % 3 == 1:
            lo, hi, c = base + 5, base + 25, base + 20
        else:
            lo, hi, c = base + 10, base + 18, base + 12
        bars.append(_bar(i, c - 2, hi, lo, c))
        base += 8.0
    peak = base + 20.0
    for j in range(12):
        drop = 30.0 * (j + 1)
        b = peak - drop
        bars.append(_bar(15 + j, b + 15, b + 18, b - 8, b))
    return bars


def _snap(**kw) -> MarketSnapshot:
    base = dict(
        ts=1.0,
        price=20000.0,
        completed_bars=[],
        forming_bar={"time": "b1", "open": 20000.0, "high": 20002.0, "low": 19998.0, "close": 20000.0},
    )
    base.update(kw)
    return MarketSnapshot(**base)


def test_recent_structure_overrides_stale_hh_hl_on_selloff():
    bars = _uptrend_then_dump()
    state, _, _ = structure_state(bars)
    assert state == "LH_LL"


def test_structure_gate_blocks_short_on_hh_hl():
    cfg = Mark2Config()
    snap = _snap(
        structure_state="HH_HL",
        trend_regime="TRENDING",
        trend_bias="BEARISH",
        shorts_allowed=True,
    )
    assert structure_blocks_entry(snap, Side.SHORT, cfg) is True


def test_high_vol_bias_relaxes_structure_block():
    cfg = Mark2Config()
    snap = _snap(
        structure_state="HH_HL",
        trend_regime="HIGH_VOL",
        trend_bias="BEARISH",
        shorts_allowed=True,
    )
    gates = bias_entry_gates(cfg, snap, Side.SHORT)
    assert gates.active
    assert gates.relax_structure is True
    assert structure_blocks_entry(snap, Side.SHORT, cfg, bias_gates=gates) is False


def test_trending_bias_does_not_relax_structure():
    cfg = Mark2Config()
    snap = _snap(
        structure_state="HH_HL",
        trend_regime="TRENDING",
        trend_bias="BEARISH",
        shorts_allowed=True,
    )
    gates = bias_entry_gates(cfg, snap, Side.SHORT)
    assert gates.active
    assert gates.relax_structure is False
    assert structure_blocks_entry(snap, Side.SHORT, cfg, bias_gates=gates) is True


def test_require_structure_alignment_toggle():
    cfg = Mark2Config()
    cfg.REQUIRE_STRUCTURE_ALIGNMENT = False
    snap = _snap(
        structure_state="HH_HL",
        trend_regime="TRENDING",
        trend_bias="BEARISH",
        shorts_allowed=True,
    )
    assert structure_blocks_entry(snap, Side.SHORT, cfg) is False
