"""Chop scalp mode — quick entries in CHOPPY regime."""

from __future__ import annotations

from mark2.chop_scalp import chop_entry_ok
from mark2.config import Mark2Config
from mark2.exits import PaperTrade, bank_points, initial_stop, initial_target, stop_points
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


def test_chop_entry_ok_requires_choppy_and_thresholds():
    cfg = Mark2Config()
    cfg.ENABLE_CHOP_SCALP = True
    snap = _choppy_snap(velocity=-0.5)
    scores = ScoreBundle(
        long_confidence=40.0,
        short_confidence=58.0,
        short_opportunity=65.0,
        short_conf_velocity=0.25,
    )
    ok, reason = chop_entry_ok(snap, scores, Side.SHORT, cfg)
    assert ok is True, reason
    assert reason == "chop_ok"

    snap_trend = _choppy_snap(trend_regime="TRENDING")
    ok2, _ = chop_entry_ok(snap_trend, scores, Side.SHORT, cfg)
    assert ok2 is False

    cfg.ENABLE_CHOP_SCALP = False
    ok3, reason3 = chop_entry_ok(snap, scores, Side.SHORT, cfg)
    assert ok3 is False
    assert reason3 == "disabled"


def test_chop_scalp_arms_in_choppy_with_profile():
    cfg = Mark2Config()
    cfg.REQUIRE_TRENDING = True
    sm = Mark2StateMachine(cfg)
    ev = EventRecord(
        event_id=1,
        event_type=EventType.MOMENTUM_EXPANSION,
        direction=Side.SHORT,
        started_ts=1.0,
        started_bar_time="b1",
        started_price=30100.0,
    )
    scores = ScoreBundle(
        long_confidence=35.0,
        short_confidence=58.0,
        short_opportunity=65.0,
        short_conf_velocity=0.25,
    )
    for tick in range(2):
        state, reject = sm.evaluate_entry(
            ts=10.0 + tick * 0.1,
            event=ev,
            scores=scores,
            extension_blocks=False,
            volume_ok=True,
            structure_ok=True,
            trend_ok=True,
            candle_ok=True,
            entry_profile="chop_scalp",
        )
    assert reject == RejectReason.NONE
    assert state.value == "TRADE_ARMED"


def test_chop_scalp_exit_profile():
    cfg = Mark2Config()
    chop = PaperTrade(
        side=Side.LONG, entry=20000.0, entry_ts=0.0, stop=19990.0, target=20007.5,
        peak=20000.0, trough=20000.0, chop_scalp=True,
    )
    assert bank_points(cfg, trade=chop) == 7.5
    assert stop_points(cfg, chop_scalp=True) == 10.0
    assert initial_stop(20000.0, Side.LONG, 12.0, cfg, chop_scalp=True) == 19990.0
    assert initial_target(20000.0, Side.LONG, 12.0, cfg, chop_scalp=True) == 20007.5


def test_chop_long_and_short_both_ok_in_choppy():
    cfg = Mark2Config()
    cfg.ENABLE_CHOP_SCALP = True
    snap = _choppy_snap(velocity=0.5)
    long_scores = ScoreBundle(
        long_confidence=58.0,
        short_confidence=38.0,
        long_opportunity=65.0,
        long_conf_velocity=0.25,
    )
    ok_long, _ = chop_entry_ok(snap, long_scores, Side.LONG, cfg)
    assert ok_long is True

    snap_short = _choppy_snap(velocity=-0.5)
    short_scores = ScoreBundle(
        long_confidence=38.0,
        short_confidence=58.0,
        short_opportunity=65.0,
        short_conf_velocity=0.25,
    )
    ok_short, _ = chop_entry_ok(snap_short, short_scores, Side.SHORT, cfg)
    assert ok_short is True


def test_chop_trails_with_room_behind_tip():
    from mark2.exits import manage_paper

    cfg = Mark2Config()
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 10.0,
        target=entry + 7.5,
        peak=entry,
        trough=entry,
        chop_scalp=True,
    )
    done, _, _ = manage_paper(
        trade, price=entry + 6.0, atr=12.0, health=80.0, hold_sec=2.0, cfg=cfg
    )
    assert done is False
    assert trade.stop == entry + 0.5


def test_chop_green_uses_five_point_five_trail():
    from mark2.exits import manage_paper

    cfg = Mark2Config()
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 10.0,
        target=entry + 7.5,
        peak=entry,
        trough=entry,
        chop_scalp=True,
    )
    manage_paper(trade, price=entry + 0.75, atr=12.0, health=80.0, hold_sec=1.0, cfg=cfg)
    assert trade.was_green is True
    assert trade.stop == entry - 10.0

    done, why, _ = manage_paper(
        trade, price=entry, atr=12.0, health=50.0, hold_sec=3.0, cfg=cfg
    )
    assert done is False
    assert why == ""

    manage_paper(trade, price=entry + 6.0, atr=12.0, health=80.0, hold_sec=3.5, cfg=cfg)
    assert trade.stop == entry + 0.5

    done, why, _ = manage_paper(
        trade, price=entry, atr=12.0, health=50.0, hold_sec=4.0, cfg=cfg
    )
    assert done is True
    assert why == "STOP"
