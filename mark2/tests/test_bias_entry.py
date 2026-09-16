"""Bias-aligned entry gate loosening."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.bias_entry import bias_entry_gates
from mark2.config import Mark2Config
from mark2.state_machine import Mark2StateMachine
from mark2.types import EventRecord, EventType, MarketSnapshot, RejectReason, ScoreBundle, Side


def _snap(**kw) -> MarketSnapshot:
    base = dict(
        price=20000.0,
        ts=100.0,
        atr=12.0,
        ema=20000.0,
        vwap=20000.0,
        trend_bias="NEUTRAL",
        trend_regime="HIGH_VOL",
        longs_allowed=False,
        shorts_allowed=False,
        structure_state="MIXED",
        velocity=-0.2,
        relative_volume=1.0,
        volume=500.0,
        forming_bar={"time": "b1", "open": 20000.0, "high": 20002.0, "low": 19998.0, "close": 19999.0},
        completed_bars=[],
    )
    base.update(kw)
    return MarketSnapshot(**base)


def _event(side: Side) -> EventRecord:
    return EventRecord(
        event_id=1,
        event_type=EventType.MOMENTUM_EXPANSION,
        direction=side,
        started_ts=1.0,
        started_bar_time="b1",
        started_price=20000.0,
        peak_confidence=60.0,
    )


def _scores(**kw) -> ScoreBundle:
    base = dict(
        long_confidence=45.0,
        short_confidence=55.0,
        long_conf_velocity=0.5,
        short_conf_velocity=0.4,
        long_opportunity=40.0,
        short_opportunity=53.0,
        long_conf_accel=0.0,
        short_conf_accel=0.0,
        extension_risk_long=30.0,
        extension_risk_short=30.0,
    )
    base.update(kw)
    return ScoreBundle(**base)


def test_bias_short_lowers_conf_threshold():
    cfg = Mark2Config()
    cfg.SHORT_CONFIDENCE_THRESHOLD = 58.0
    snap = _snap(trend_bias="BEARISH", shorts_allowed=True)
    gates = bias_entry_gates(cfg, snap, Side.SHORT)
    assert gates.active
    assert gates.tag == "bias_short"
    assert gates.conf_threshold == 52.0
    assert gates.relax_forming_direction is True
    assert gates.relax_structure is True
    assert gates.min_tick_velocity == 0.0
    assert gates.min_relative_volume == pytest.approx(0.18)


def test_bias_inactive_when_chop_profile():
    cfg = Mark2Config()
    snap = _snap(trend_bias="BEARISH", shorts_allowed=True)
    gates = bias_entry_gates(cfg, snap, Side.SHORT, entry_profile="chop_scalp")
    assert not gates.active


def test_bias_short_arms_at_55_conf():
    cfg = Mark2Config()
    cfg.SHORT_CONFIDENCE_THRESHOLD = 58.0
    cfg.MIN_CONFIDENCE_VELOCITY = 0.35
    cfg.MOMENTUM_BUILD_TICKS = 3
    sm = Mark2StateMachine(cfg)
    snap = _snap(trend_bias="BEARISH", shorts_allowed=True)
    gates = bias_entry_gates(cfg, snap, Side.SHORT)
    scores = _scores(short_confidence=55.0, short_conf_velocity=0.4, short_opportunity=53.0)

    for _ in range(2):
        state, reject = sm.evaluate_entry(
            ts=10.0,
            event=_event(Side.SHORT),
            scores=scores,
            extension_blocks=False,
            volume_ok=True,
            structure_ok=True,
            trend_ok=True,
            candle_ok=True,
            bias_gates=gates,
        )
    assert reject == RejectReason.NONE
    assert state.value == "TRADE_ARMED"


def test_bias_trending_no_high_vol_nudge():
    cfg = Mark2Config()
    cfg.SHORT_CONFIDENCE_THRESHOLD = 58.0
    snap = _snap(trend_bias="BEARISH", shorts_allowed=True, trend_regime="TRENDING")
    gates = bias_entry_gates(cfg, snap, Side.SHORT)
    assert gates.conf_threshold == 54.0
    assert gates.relax_forming_direction is False
    assert gates.relax_structure is False


def test_default_profile_still_rejects_55_conf():
    cfg = Mark2Config()
    cfg.SHORT_CONFIDENCE_THRESHOLD = 58.0
    sm = Mark2StateMachine(cfg)
    scores = _scores(short_confidence=55.0, short_conf_velocity=0.4, short_opportunity=53.0)
    state, reject = sm.evaluate_entry(
        ts=10.0,
        event=_event(Side.SHORT),
        scores=scores,
        extension_blocks=False,
        volume_ok=True,
        structure_ok=True,
        trend_ok=True,
        candle_ok=True,
    )
    assert reject == RejectReason.REJECT_LOW_CONFIDENCE


def test_bias_long_mirror():
    cfg = Mark2Config()
    cfg.LONG_CONFIDENCE_THRESHOLD = 58.0
    snap = _snap(trend_bias="BULLISH", longs_allowed=True, trend_regime="TRENDING")
    gates = bias_entry_gates(cfg, snap, Side.LONG)
    assert gates.active
    assert gates.tag == "bias_long"
    assert gates.conf_threshold == 54.0
