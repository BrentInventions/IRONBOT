"""Choppy with bias — default/EXP entries when bias aligns in CHOPPY regime."""

from __future__ import annotations

from mark2.choppy_bias import choppy_bias_entry_ok
from mark2.config import Mark2Config
from mark2.entry_tuning import apply_toggles, snapshot
from mark2.state_machine import Mark2StateMachine
from mark2.types import EventRecord, EventType, MarketSnapshot, RejectReason, ScoreBundle, Side


def _choppy_snap(**kw) -> MarketSnapshot:
    base = dict(
        price=30100.0,
        ts=100.0,
        atr=12.0,
        ema=30100.0,
        vwap=30100.0,
        volume=500.0,
        relative_volume=1.0,
        velocity=0.5,
        acceleration=0.1,
        impulse_score=60.0,
        trend_bias="NEUTRAL",
        trend_regime="CHOPPY",
        trend_strength=20.0,
        structure_state="MIXED",
        volatility_state="stable",
        session="RTH",
        vwap_distance_atr=0.0,
        longs_allowed=False,
        shorts_allowed=False,
        forming_bar={"time": "b1", "open": 30100.0, "high": 30102.0, "low": 30098.0, "close": 30100.5},
        completed_bars=[],
    )
    base.update(kw)
    return MarketSnapshot(**base)


def test_choppy_bias_toggle_in_entry_tuning():
    cfg = Mark2Config()
    apply_toggles(cfg, {"choppy_bias": True})
    assert cfg.ENABLE_CHOPPY_BIAS is True
    snap = snapshot(cfg)
    assert snap["toggles"]["choppy_bias"] is True


def test_choppy_bias_entry_ok_requires_choppy_and_aligned_bias():
    cfg = Mark2Config()
    cfg.ENABLE_CHOPPY_BIAS = True

    ok_long, _ = choppy_bias_entry_ok(cfg, _choppy_snap(trend_bias="BULLISH"), Side.LONG)
    assert ok_long is True

    ok_short, _ = choppy_bias_entry_ok(cfg, _choppy_snap(trend_bias="BEARISH"), Side.SHORT)
    assert ok_short is True

    ok_wrong, reason = choppy_bias_entry_ok(
        cfg, _choppy_snap(trend_bias="BULLISH"), Side.SHORT
    )
    assert ok_wrong is False
    assert reason == "bias_mismatch"

    ok_neutral, reason = choppy_bias_entry_ok(
        cfg, _choppy_snap(trend_bias="NEUTRAL"), Side.LONG
    )
    assert ok_neutral is False
    assert reason == "bias_mismatch"

    cfg.ENABLE_CHOPPY_BIAS = False
    ok_off, reason = choppy_bias_entry_ok(
        cfg, _choppy_snap(trend_bias="BULLISH"), Side.LONG
    )
    assert ok_off is False
    assert reason == "disabled"


def test_choppy_bias_arms_with_default_profile_not_chop_scalp():
    cfg = Mark2Config()
    cfg.REQUIRE_TRENDING = True
    cfg.ENABLE_CHOPPY_BIAS = True
    sm = Mark2StateMachine(cfg)
    ev = EventRecord(
        event_id=1,
        event_type=EventType.MOMENTUM_EXPANSION,
        direction=Side.LONG,
        started_ts=1.0,
        started_bar_time="b1",
        started_price=30100.0,
    )
    scores = ScoreBundle(
        long_confidence=70.0,
        short_confidence=20.0,
        long_opportunity=70.0,
        long_conf_velocity=0.5,
    )
    for tick in range(3):
        state, reject = sm.evaluate_entry(
            ts=10.0 + tick * 0.1,
            event=ev,
            scores=scores,
            extension_blocks=False,
            volume_ok=True,
            structure_ok=True,
            trend_ok=True,
            candle_ok=True,
            entry_profile="default",
        )
    assert reject == RejectReason.NONE
    assert state.value == "TRADE_ARMED"


def test_choppy_bias_blocks_when_trend_ok_false():
    cfg = Mark2Config()
    cfg.REQUIRE_TRENDING = True
    cfg.ENABLE_CHOPPY_BIAS = True
    sm = Mark2StateMachine(cfg)
    ev = EventRecord(
        event_id=1,
        event_type=EventType.MOMENTUM_EXPANSION,
        direction=Side.LONG,
        started_ts=1.0,
        started_bar_time="b1",
        started_price=30100.0,
    )
    scores = ScoreBundle(
        long_confidence=70.0,
        short_confidence=20.0,
        long_opportunity=70.0,
        long_conf_velocity=0.5,
    )
    state, reject = sm.evaluate_entry(
        ts=10.0,
        event=ev,
        scores=scores,
        extension_blocks=False,
        volume_ok=True,
        structure_ok=True,
        trend_ok=False,
        candle_ok=True,
        entry_profile="default",
    )
    assert reject == RejectReason.REJECT_REGIME
    assert state.value != "TRADE_ARMED"
