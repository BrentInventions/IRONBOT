"""413 LONG breakout: filters, arm/cancel, 2R target, BE, trail. Never widen hard stop."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mark2.breakout_413 import (
    Breakout413State,
    compute_stop_target,
    evaluate_filters,
    is_rejection_bar,
    manage_413_hold,
    note_fill,
    note_stop_exit,
    on_completed_bar,
    tick_should_fill,
)
from mark2.config import Mark2Config
from mark2.ema_strategy import manage_ema_hold
from mark2.exits import PaperTrade
from mark2.types import Side

_ET = ZoneInfo("America/New_York")


def _cfg(**kwargs) -> Mark2Config:
    cfg = Mark2Config()
    cfg.ENABLE_413_BREAKOUT = True
    cfg.ENABLE_AI_EXIT_ENGINE = False
    cfg.TICK_SIZE = 0.25
    cfg.BREAKOUT_413_MODE = "BREAKOUT"
    cfg.BREAKOUT_413_MAX_STOP_PTS = 40.0
    cfg.BREAKOUT_413_TARGET_R = 2.0
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _bars(n: int = 80, start: float = 20000.0, step: float = 1.5) -> list[dict]:
    out = []
    px = start
    t0 = datetime(2026, 9, 11, 9, 0, tzinfo=_ET)
    for i in range(n):
        o = px
        c = px + step
        bar = {
            "time": (t0 + timedelta(minutes=i)).isoformat(),
            "open": o,
            "high": max(o, c) + 0.75,
            "low": min(o, c) - 0.5,
            "close": c,
            "volume": 1200.0,
        }
        out.append(bar)
        px = c
    return out


def _pass_filters() -> dict[str, bool]:
    keys = (
        "data",
        "ema9_cross_20",
        "ema9_above_20",
        "ema20_vs_50",
        "ema9_rising",
        "ema20_rising",
        "ema50_flat_or_rising",
        "price_above_emas",
        "close_above_10bar_high",
        "bullish_close",
        "body_50",
        "close_upper_25",
        "volume_125",
        "macd_above_signal",
        "macd_hist_up",
        "rsi_52_75",
        "not_compressed",
        "emas_not_flat",
        "bar_not_1_75_atr",
        "session_hours",
        "setup",
        "breakout",
        "momentum",
        "safety",
    )
    return {k: True for k in keys}


def test_stop_is_below_signal_or_swing_minus_two_ticks() -> None:
    cfg = _cfg()
    stop, target, ok = compute_stop_target(
        entry=20100.25,
        signal_low=20090.0,
        swing_low=20088.0,
        cfg=cfg,
    )
    assert ok is True
    assert abs(stop - (20088.0 - 0.50)) < 1e-9
    risk = 20100.25 - stop
    assert abs(target - (20100.25 + 2.0 * risk)) < 1e-9


def test_max_stop_rejects_wide_risk() -> None:
    cfg = _cfg(BREAKOUT_413_MAX_STOP_PTS=8.0)
    stop, target, ok = compute_stop_target(
        entry=20100.0,
        signal_low=20080.0,
        swing_low=20070.0,
        cfg=cfg,
    )
    assert ok is False
    assert target == 0.0
    assert stop < 20100.0


def test_breakout_mode_arms_buy_stop(monkeypatch) -> None:
    monkeypatch.setattr(
        "mark2.breakout_413.evaluate_filters",
        lambda bars, cfg: _pass_filters(),
    )
    cfg = _cfg()
    bars = _bars()
    last = bars[-1]
    last["high"] = 20110.0
    last["low"] = 20095.0
    last["close"] = 20108.0
    state = Breakout413State()
    scan = on_completed_bar(
        state, bars, cfg, in_trade=False, session_pnl=0.0, enabled=True
    )
    assert scan.arm is True
    assert scan.reason == "413_LONG"
    assert scan.alert == "SETUP_ARMED"
    assert abs(scan.trigger_px - (20110.0 + 0.25)) < 1e-9
    assert tick_should_fill(state, 20110.24) is False
    assert tick_should_fill(state, 20110.25) is True


def test_pullback_waits_then_arms_on_rejection(monkeypatch) -> None:
    monkeypatch.setattr(
        "mark2.breakout_413.evaluate_filters",
        lambda bars, cfg: _pass_filters(),
    )
    cfg = _cfg(BREAKOUT_413_MODE="PULLBACK")
    bars = _bars()
    bars[-1]["high"] = 20110.0
    bars[-1]["low"] = 20095.0
    bars[-1]["close"] = 20108.0
    state = Breakout413State()
    scan = on_completed_bar(
        state, bars, cfg, in_trade=False, session_pnl=0.0, enabled=True
    )
    assert scan.arm is False
    assert state.waiting_pullback is True
    assert scan.reason == "413_WAIT_PULLBACK"

    # Next bar: bullish rejection that tags EMA zone.
    nxt = dict(bars[-1])
    nxt["time"] = "2026-09-11T10:21:00-04:00"
    nxt["open"] = 20100.0
    nxt["low"] = 20099.0
    nxt["high"] = 20106.0
    nxt["close"] = 20105.0
    bars.append(nxt)
    monkeypatch.setattr(
        "mark2.breakout_413.ema",
        lambda closes, n: [float(closes[-1]) - (3 if n == 20 else 1)] * len(closes),
    )
    monkeypatch.setattr("mark2.breakout_413.atr", lambda bars, n=14: [8.0] * len(bars))
    scan2 = on_completed_bar(
        state, bars, cfg, in_trade=False, session_pnl=0.0, enabled=True
    )
    assert scan2.arm is True
    assert scan2.reason == "413_PULLBACK"
    assert abs(scan2.trigger_px - (20106.0 + 0.25)) < 1e-9


def test_pullback_cancels_if_close_below_ema20(monkeypatch) -> None:
    monkeypatch.setattr(
        "mark2.breakout_413.evaluate_filters",
        lambda bars, cfg: _pass_filters(),
    )
    cfg = _cfg(BREAKOUT_413_MODE="PULLBACK")
    bars = _bars()
    state = Breakout413State()
    on_completed_bar(state, bars, cfg, in_trade=False, session_pnl=0.0, enabled=True)
    assert state.waiting_pullback is True
    nxt = dict(bars[-1])
    nxt["close"] = 100.0
    nxt["open"] = 120.0
    nxt["high"] = 121.0
    nxt["low"] = 99.0
    bars.append(nxt)
    monkeypatch.setattr(
        "mark2.breakout_413.ema",
        lambda closes, n: [500.0] * len(closes),
    )
    monkeypatch.setattr("mark2.breakout_413.atr", lambda bars, n=14: [8.0] * len(bars))
    scan = on_completed_bar(
        state, bars, cfg, in_trade=False, session_pnl=0.0, enabled=True
    )
    assert scan.cancel is True
    assert scan.reason == "CLOSE_BELOW_EMA20"
    assert state.waiting_pullback is False


def test_sequence_cap_and_stop_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(
        "mark2.breakout_413.evaluate_filters",
        lambda bars, cfg: _pass_filters(),
    )
    cfg = _cfg()
    bars = _bars()
    bars[-1]["high"] = 20110.0
    bars[-1]["low"] = 20095.0
    state = Breakout413State()
    state.seq_9_above_20 = True
    state.entries_this_seq = 2
    scan = on_completed_bar(
        state, bars, cfg, in_trade=False, session_pnl=0.0, enabled=True
    )
    assert scan.arm is False
    assert scan.reason == "SEQUENCE_CAP"
    state.entries_this_seq = 0
    note_stop_exit(state)
    assert state.stop_cooldown == 5
    scan2 = on_completed_bar(
        state, bars, cfg, in_trade=False, session_pnl=0.0, enabled=True
    )
    assert scan2.reason == "STOP_COOLDOWN"


def test_daily_loss_blocks(monkeypatch) -> None:
    monkeypatch.setattr(
        "mark2.breakout_413.evaluate_filters",
        lambda bars, cfg: _pass_filters(),
    )
    cfg = _cfg(BREAKOUT_413_DAILY_LOSS_USD=200.0)
    scan = on_completed_bar(
        Breakout413State(),
        _bars(),
        cfg,
        in_trade=False,
        session_pnl=-200.0,
        enabled=True,
    )
    assert scan.arm is False
    assert scan.reason == "DAILY_LOSS_LIMIT"


def test_manage_413_target_be_trail_never_widen() -> None:
    cfg = _cfg()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=90.0,
        target=120.0,
        peak=100.0,
        trough=100.0,
        hard_stop=90.0,
        ema_strategy=True,
        ema_entry_tag="413_LONG",
    )
    bars = [
        {"open": 118.0, "high": 119.0, "low": 114.0, "close": 118.5, "volume": 1},
        {"open": 118.5, "high": 119.5, "low": 115.0, "close": 119.0, "volume": 1},
    ]
    done, why, _ = manage_413_hold(trade, price=100.5, bars=bars, cfg=cfg, ema9=101.0)
    assert done is False
    assert trade.stop == 90.0

    done, why, _ = manage_413_hold(trade, price=110.0, bars=bars, cfg=cfg, ema9=109.0)
    assert done is False
    assert trade.stop == 100.25
    assert trade.ema_trade_state == "CONFIRMED"
    prev = trade.stop
    done, why, _ = manage_413_hold(trade, price=109.0, bars=bars, cfg=cfg, ema9=108.0)
    assert done is False
    assert trade.stop >= prev

    done, why, _ = manage_413_hold(trade, price=115.0, bars=bars, cfg=cfg, ema9=114.0)
    assert done is False
    assert trade.stop >= 100.25
    assert trade.ema_trade_state == "RUNNER"
    locked = trade.stop
    done, why, _ = manage_413_hold(trade, price=112.0, bars=bars, cfg=cfg, ema9=100.0)
    assert trade.stop >= locked

    done, why, _ = manage_413_hold(trade, price=120.0, bars=bars, cfg=cfg, ema9=119.0)
    assert done is True
    assert why == "413_TARGET"


def test_manage_ema_hold_routes_413_before_ai() -> None:
    cfg = _cfg(ENABLE_AI_EXIT_ENGINE=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=90.0,
        target=120.0,
        peak=100.0,
        trough=100.0,
        hard_stop=90.0,
        ema_strategy=True,
        ema_entry_tag="413_LONG",
    )
    done, why, _ = manage_ema_hold(trade, price=90.0, exit_armed=False, cfg=cfg)
    assert done is True
    assert why == "HARD_STOP"


def test_hard_stop_never_moves_down() -> None:
    cfg = _cfg()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=90.0,
        target=120.0,
        peak=116.0,
        trough=100.0,
        mfe=16.0,
        hard_stop=90.0,
        ema_strategy=True,
        ema_entry_tag="413_LONG",
    )
    bars = [
        {"open": 114.0, "high": 116.0, "low": 113.0, "close": 115.0, "volume": 1},
        {"open": 115.0, "high": 116.0, "low": 112.0, "close": 113.0, "volume": 1},
    ]
    manage_413_hold(trade, price=116.0, bars=bars, cfg=cfg, ema9=114.0)
    assert trade.hard_stop == 90.0
    assert trade.stop >= 90.0
    after = trade.stop
    manage_413_hold(trade, price=112.0, bars=bars, cfg=cfg, ema9=80.0)
    assert trade.stop >= after
    assert trade.hard_stop == 90.0


def test_rejection_bar_needs_tag_and_close_above_20() -> None:
    bar = {"open": 100.0, "high": 104.0, "low": 99.5, "close": 103.0, "volume": 1}
    assert is_rejection_bar(bar, ema9=100.0, ema20=99.0, atr_v=8.0) is True
    bear = {"open": 104.0, "high": 104.0, "low": 99.5, "close": 100.0, "volume": 1}
    assert is_rejection_bar(bear, ema9=100.0, ema20=99.0, atr_v=8.0) is False


def test_evaluate_filters_needs_warmup() -> None:
    cfg = _cfg()
    got = evaluate_filters(_bars(n=20), cfg)
    assert got.get("data") is False


def test_note_fill_clears_arm() -> None:
    state = Breakout413State(armed=True, trigger_px=1.0)
    note_fill(state)
    assert state.armed is False
    assert state.entries_this_seq == 1
    assert state.trigger_px == 0.0
