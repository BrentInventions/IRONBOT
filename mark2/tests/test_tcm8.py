"""8TCM baseline: independent of EMA9/20/50 sniper. Do not tune the numbers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mark2.config import Mark2Config
from mark2.engine import Mark2Engine
from mark2.exits import PaperTrade
from mark2.momentum_barriers import BarrierBook, PREVIOUS_DAY_HIGH
from mark2.strategy_hud import apply_strategy, snapshot
from mark2.tcm8 import (
    EMA8_CLOSE_REJECT,
    ENGULFING,
    ENTRY_LONG,
    ENTRY_LONG_REASON,
    ENTRY_SHORT,
    ENTRY_SHORT_REASON,
    DOLLAR_ARM,
    EXIT_GREEN_BANK,
    EXIT_KEY_LEVEL,
    EXIT_RUNNER_TRAIL,
    PIN_BAR,
    REJ_BARRIER,
    REJ_CHASE,
    REJ_EMA8_NOT_TESTED,
    REJ_HTF,
    REJ_NO_CLEAR_TREND,
    REJ_NO_PULLBACK,
    REJ_NO_REJECTION,
    REJ_NO_RETRACEMENT,
    REJ_RANGE,
    REJ_SIDE,
    REJ_STRUCTURE,
    REJ_TARGET_R,
    REJ_WRONG_SIDE,
    RUNNER_ARM,
    STRONG_WICK,
    TREND_BEARISH,
    TREND_BULLISH,
    TREND_RANGING,
    Tcm8Setup,
    apply_tcm8_runner_trail,
    candle_metrics,
    tcm8_working_target,
    classify_8tcm_trend,
    classify_htf_trend,
    classify_rejection,
    confirmed_swings,
    ema_92050_live,
    evaluate_tcm8,
    is_market_ranging,
    manage_tcm8_hold,
    overlay_forming_htf,
    penetration_atr,
    stop_price,
    tcm8_enabled,
    tcm8_live_checklist,
    tcm8_next_gate,
    tcm8_only_mode,
    tcm8_trade_hud,
    tcm8_initial_stop,
    uses_shared_tcm8_exit,
    uses_tcm8_hold,
    format_tcm8_log,
)
from mark2.indicators import ema as ema_fn
from mark2.types import EventType, RunMode, Side

_ET = ZoneInfo("America/New_York")


def _cfg(**kwargs) -> Mark2Config:
    cfg = Mark2Config()
    cfg.ENABLE_8TCM = True
    cfg.ENABLE_8TCM_LONGS = True
    cfg.ENABLE_8TCM_SHORTS = False
    cfg.ENABLE_8TCM_CLASSIC_TARGET = True
    cfg.ENABLE_8TCM_AI_EXIT = False
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.EMA_ALLOW_LONG = True
    cfg.EMA_ALLOW_SHORT = False
    cfg.TICK_SIZE = 0.25
    cfg.MODE = RunMode.PAPER_TRADE.value
    cfg.MARK2_ENABLED = True
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _bar(dt: datetime, o: float, h: float, l: float, c: float, vol: float = 900.0) -> dict:
    return {"time": dt.isoformat(), "open": o, "high": h, "low": l, "close": c, "volume": vol}


def _trend_bars(n: int, start: float, step: float, minutes: int, t0: datetime | None = None) -> list[dict]:
    t0 = t0 or datetime(2026, 9, 14, 8, 0, tzinfo=_ET)
    bars = []
    px = start
    for i in range(n):
        o = px
        c = px + step
        h = max(o, c) + abs(step) * 0.35
        l = min(o, c) - abs(step) * 0.15
        bars.append(_bar(t0 + timedelta(minutes=minutes * i), o, h, l, c))
        px = c
    return bars


def _book(resistance: float, support: float = 17000.0) -> BarrierBook:
    book = BarrierBook()
    book.previous_day_high = float(resistance)
    book.current_session_high = float(resistance)
    book.previous_day_low = float(support)
    book.current_session_low = float(support)
    return book


def _structure_bars(bullish: bool = True, n: int = 55, t0: datetime | None = None) -> list[dict]:
    t0 = t0 or datetime(2026, 9, 14, 9, 0, tzinfo=_ET)
    bars: list[dict] = []
    base = 20000.0
    for i in range(n):
        c = base + (4 if bullish else -4) * (i / 10.0)
        bars.append(_bar(t0 + timedelta(minutes=i), c, c + 2, c - 2, c))

    def paint_low(i: int, low: float) -> None:
        ts = t0 + timedelta(minutes=i)
        bars[i] = _bar(ts, low + 4, low + 8, low, low + 3)
        bars[i - 1] = _bar(ts - timedelta(minutes=1), low + 8, low + 12, low + 6, low + 7)
        bars[i - 2] = _bar(ts - timedelta(minutes=2), low + 12, low + 16, low + 10, low + 11)
        bars[i + 1] = _bar(ts + timedelta(minutes=1), low + 3, low + 10, low + 5, low + 8)
        bars[i + 2] = _bar(ts + timedelta(minutes=2), low + 8, low + 14, low + 7, low + 12)

    def paint_high(i: int, high: float) -> None:
        ts = t0 + timedelta(minutes=i)
        bars[i] = _bar(ts, high - 4, high, high - 8, high - 3)
        bars[i - 1] = _bar(ts - timedelta(minutes=1), high - 8, high - 6, high - 12, high - 7)
        bars[i - 2] = _bar(ts - timedelta(minutes=2), high - 12, high - 10, high - 16, high - 11)
        bars[i + 1] = _bar(ts + timedelta(minutes=1), high - 3, high - 5, high - 10, high - 8)
        bars[i + 2] = _bar(ts + timedelta(minutes=2), high - 8, high - 6, high - 14, high - 12)

    if bullish:
        paint_low(10, 19940.0)
        paint_high(20, 20120.0)
        paint_low(30, 19980.0)
        paint_high(40, 20200.0)
        for i in range(43, n):
            c = 20240.0 + (i - 43) * 8
            bars[i] = _bar(t0 + timedelta(minutes=i), c - 4, c + 2, c - 6, c)
    else:
        paint_high(10, 20120.0)
        paint_low(20, 19940.0)
        paint_high(30, 20080.0)
        paint_low(40, 19880.0)
        for i in range(43, n):
            c = 19840.0 - (i - 43) * 8
            bars[i] = _bar(t0 + timedelta(minutes=i), c + 4, c + 6, c - 2, c)
    return bars


def _rejection_bar(bars: list[dict], *, long: bool) -> list[dict]:
    out = list(bars)
    prev_ema = ema_fn([float(b["close"]) for b in out[:-1]], 8)[-1]
    last = out[-1]
    t = datetime.fromisoformat(str(last["time"]))
    if long:
        out[-1] = _bar(t, prev_ema + 2, prev_ema + 4, prev_ema - 8, prev_ema + 0.5)
    else:
        out[-1] = _bar(t, prev_ema - 2, prev_ema + 8, prev_ema - 4, prev_ema - 0.5)
    return out


def test_defaults_are_baseline_not_tuned() -> None:
    cfg = Mark2Config()
    assert cfg.ENABLE_8TCM is False
    assert cfg.ENABLE_8TCM_CLASSIC_TARGET is True
    assert cfg.ENABLE_8TCM_AI_EXIT is False
    assert cfg.TCM8_EMA_PERIOD == 8
    assert cfg.TCM8_TREND_SLOPE_LOOKBACK == 5
    assert abs(cfg.TCM8_MIN_TREND_SLOPE_ATR - 0.05) < 1e-12
    assert abs(cfg.TCM8_PULLBACK_MAX_DISTANCE_ATR - 0.15) < 1e-12
    assert abs(cfg.TCM8_EMA_TOUCH_TOLERANCE_ATR - 0.10) < 1e-12
    assert abs(cfg.TCM8_MAX_EMA_PENETRATION_ATR - 0.20) < 1e-12
    assert abs(cfg.TCM8_MAX_ENTRY_DISTANCE_FROM_EMA_ATR - 0.30) < 1e-12
    assert abs(cfg.TCM8_STRONG_WICK_BODY_RATIO - 1.50) < 1e-12
    assert abs(cfg.TCM8_PIN_BAR_WICK_BODY_RATIO - 2.00) < 1e-12
    assert abs(cfg.TCM8_MIN_REJECTION_BODY_ATR - 0.15) < 1e-12
    assert abs(cfg.TCM8_BARRIER_PROXIMITY_BLOCK_ATR - 0.25) < 1e-12
    assert cfg.TCM8_CONSOLIDATION_LOOKBACK == 10
    assert abs(cfg.TCM8_CONSOLIDATION_MAX_RANGE_ATR - 1.00) < 1e-12
    assert abs(cfg.TCM8_STOP_BUFFER_ATR - 0.10) < 1e-12
    assert abs(cfg.TCM8_INITIAL_STOP_POINTS - 20.0) < 1e-12
    assert abs(cfg.TCM8_MINIMUM_TARGET_R - 0.75) < 1e-12
    assert abs(cfg.TCM8_PREFERRED_TARGET_R - 1.50) < 1e-12
    assert abs(cfg.TCM8_TARGET_FRONT_RUN_POINTS - 1.5) < 1e-12
    assert abs(cfg.TCM8_TRAIL_ARM_USD - 50.0) < 1e-12
    assert abs(cfg.TCM8_TRAIL_POINTS - 5.5) < 1e-12
    assert cfg.ENABLE_8TCM_RUNNER is True
    assert cfg.ENABLE_8TCM_EARLY_ENTRY is False
    assert cfg.TCM8_ENTRY_MODE == "CLOSED_BAR"
    assert cfg.TCM8_SWING_STRENGTH == 2
    st = snapshot(cfg)
    assert st["tcm8"] is False
    assert st["tcm8_classic_target"] is True
    assert st["tcm8_ai_exit"] is False


def test_disabled_has_zero_effect() -> None:
    cfg = _cfg(ENABLE_8TCM=False)
    assert tcm8_enabled(cfg) is False
    row = evaluate_tcm8(
        cfg=cfg,
        bars_1m=_trend_bars(40, 20000, 1.0, 1),
        bars_1h=_trend_bars(20, 19800, 20, 60),
        bars_4h=_trend_bars(20, 19000, 40, 240),
        book=_book(22000),
        setup=Tcm8Setup(),
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=True,
        allow_short=False,
    )
    assert row["reason"] == "DISABLED"
    assert row["accept"] is False


def test_8tcm_longs_are_not_the_ema_sniper_switch() -> None:
    cfg = _cfg(EMA_ALLOW_LONG=False, ENABLE_8TCM_LONGS=True)
    row = evaluate_tcm8(
        cfg=cfg,
        bars_1m=_structure_bars(True),
        bars_1h=_trend_bars(20, 19800, 20, 60),
        bars_4h=_trend_bars(20, 19000, 40, 240),
        book=_book(23000),
        setup=Tcm8Setup(),
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=False,
        allow_short=False,
    )
    assert row["trend"] == TREND_BULLISH
    assert row["reason"] != REJ_SIDE
    cfg.ENABLE_8TCM_LONGS = False
    blocked = evaluate_tcm8(
        cfg=cfg,
        bars_1m=_structure_bars(True),
        bars_1h=_trend_bars(20, 19800, 20, 60),
        bars_4h=_trend_bars(20, 19000, 40, 240),
        book=_book(23000),
        setup=Tcm8Setup(),
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=True,
        allow_short=False,
    )
    assert blocked["reason"] == REJ_SIDE


def test_htf_trend_math_and_mismatch_is_not_a_veto() -> None:
    cfg = _cfg(ENABLE_8TCM_SHORTS=True)
    bull = classify_htf_trend(_trend_bars(24, 20000, 12, 60), cfg)
    bear = classify_htf_trend(_trend_bars(24, 21000, -12, 60), cfg)
    assert bull["state"] == TREND_BULLISH
    assert "ABOVE_EMA8_POS_SLOPE" in bull["why"]
    assert bear["state"] == TREND_BEARISH
    empty = classify_htf_trend(_trend_bars(5, 20000, 12, 60), cfg)
    assert empty["state"] == "UNCLEAR"
    bars = _rejection_bar(_structure_bars(True), long=True)
    row = evaluate_tcm8(
        cfg=cfg,
        bars_1m=bars,
        bars_1h=_trend_bars(20, 21000, -12, 60),
        bars_4h=_trend_bars(20, 21000, -12, 240),
        book=_book(23000),
        setup=Tcm8Setup(),
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=True,
        allow_short=True,
    )
    assert row["trend"] == TREND_BULLISH
    assert row["htf_1h"] == TREND_BEARISH
    assert row["htf_4h"] == TREND_BEARISH
    assert row["reason"] not in (REJ_HTF, REJ_NO_CLEAR_TREND)
    assert row["accept"] is True
    assert row["reason"] == ENTRY_LONG_REASON


def test_forming_htf_follows_live_1m_inside_the_hour() -> None:
    t0 = datetime(2026, 9, 14, 14, 0, tzinfo=_ET)
    completed = [_bar(t0, 29300.0, 29320.0, 29280.0, 29310.0)]
    live_1m = []
    px = 29310.0
    for i in range(20):
        px -= 8.0
        live_1m.append(_bar(t0 + timedelta(minutes=i), px + 8, px + 9, px - 1, px))
    merged = overlay_forming_htf(completed, live_1m, 60)
    assert abs(merged[-1]["close"] - px) < 1e-9
    assert merged[-1]["close"] < 29200.0


def test_ranging_filter() -> None:
    cfg = _cfg()
    choppy = []
    t0 = datetime(2026, 9, 14, 10, 0, tzinfo=_ET)
    for i in range(30):
        px = 20000.0
        choppy.append(_bar(t0 + timedelta(minutes=i), px, px + 0.5, px - 0.5, px))
    out = is_market_ranging(choppy, cfg)
    assert out["state"] == TREND_RANGING
    bars = _structure_bars(True)
    last_px = float(bars[-1]["close"])
    t_last = datetime.fromisoformat(str(bars[-1]["time"]))
    for j in range(10):
        i = len(bars) - 10 + j
        ts = t_last - timedelta(minutes=9 - j)
        bars[i] = _bar(ts, last_px, last_px + 0.5, last_px - 0.5, last_px)
    row = evaluate_tcm8(
        cfg=cfg,
        bars_1m=bars,
        bars_1h=_trend_bars(20, 19800, 20, 60),
        bars_4h=_trend_bars(20, 19000, 40, 240),
        book=_book(22000),
        setup=Tcm8Setup(),
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=True,
        allow_short=False,
    )
    assert row["reason"] == REJ_RANGE
    assert row["trend"] == TREND_BULLISH


def test_pin_strong_wick_engulfing_formulas() -> None:
    cfg = _cfg()
    atr_v = 10.0
    pin = {"open": 100.0, "high": 101.0, "low": 94.0, "close": 100.5}
    # body 0.5 too small vs 0.15*10=1.5 → no type
    assert classify_rejection(pin, None, Side.LONG, atr_v, cfg)["type"] == ""
    pin = {"open": 100.0, "high": 102.0, "low": 94.0, "close": 102.0}
    # body 2, lower wick 6, ratio 3.0 → PIN
    out = classify_rejection(pin, None, Side.LONG, atr_v, cfg)
    assert out["type"] == PIN_BAR
    assert abs(out["wick_body_ratio"] - 3.0) < 1e-9
    strong = {"open": 100.0, "high": 102.2, "low": 96.8, "close": 102.0}
    # body 2, lower 3.2, ratio 1.6 → STRONG_WICK
    out = classify_rejection(strong, None, Side.LONG, atr_v, cfg)
    assert out["type"] == STRONG_WICK
    prev = {"open": 102.0, "high": 102.5, "low": 99.5, "close": 100.0}
    eng = {"open": 99.8, "high": 103.5, "low": 99.6, "close": 103.2}
    out = classify_rejection(eng, prev, Side.LONG, atr_v, cfg)
    assert out["type"] == ENGULFING
    c = candle_metrics({"open": 100, "high": 100, "low": 100, "close": 100})
    assert c.body == 0.0
    assert c.wick_body_ratio_lower > 0 or True  # no ZeroDivisionError


def test_penetration_and_stop() -> None:
    cfg = _cfg()
    bar = {"open": 100, "high": 101, "low": 97.5, "close": 100.4}
    pen = penetration_atr(Side.LONG, bar, ema8=100.0, atr_v=10.0)
    assert abs(pen - 0.25) < 1e-9
    stop = stop_price(Side.LONG, 100.0, bar, 10.0, cfg)
    assert abs(stop - (97.5 - 1.0)) < 1e-9


def _long_sequence() -> tuple[list[dict], Tcm8Setup]:
    """Rising 1m, then extend away from EMA8, then pull back with a pin."""
    t0 = datetime(2026, 9, 14, 11, 0, tzinfo=_ET)
    bars = _trend_bars(40, 20000, 3.0, 1, t0)
    setup = Tcm8Setup()
    return bars, setup


def test_no_retracement_when_extended() -> None:
    cfg = _cfg()
    bars = _structure_bars(True)
    row = evaluate_tcm8(
        cfg=cfg,
        bars_1m=bars,
        bars_1h=_trend_bars(20, 19800, 20, 60),
        bars_4h=_trend_bars(20, 19000, 40, 240),
        book=_book(23000),
        setup=Tcm8Setup(),
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=True,
        allow_short=False,
    )
    assert row["trend"] == TREND_BULLISH
    assert row["reason"] == REJ_NO_RETRACEMENT
    assert row["accept"] is False


def _eval_from_bars(cfg, bars_1m, setup, resistance: float = 23000.0, allow_short: bool = False) -> dict:
    return evaluate_tcm8(
        cfg=cfg,
        bars_1m=bars_1m,
        bars_1h=_trend_bars(20, 19000, 30, 60),
        bars_4h=_trend_bars(20, 17000, 80, 240),
        book=_book(resistance),
        setup=setup,
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=True,
        allow_short=allow_short,
    )


def test_sequence_retrace_close_accept() -> None:
    cfg = _cfg()
    bars = _rejection_bar(_structure_bars(True), long=True)
    row = _eval_from_bars(cfg, bars, Tcm8Setup(), 23000)
    assert row["accept"] is True
    assert row["reason"] == ENTRY_LONG_REASON
    assert row["rejection_type"] in (PIN_BAR, STRONG_WICK, ENGULFING, EMA8_CLOSE_REJECT)
    assert row["target_r"] >= 0.75
    assert row.get("entry_reason") != "EMA_SNIPER_LONG"


def test_wick_through_ema8_is_not_a_structure_veto() -> None:
    cfg = _cfg()
    bars = _rejection_bar(_structure_bars(True), long=True)
    row = _eval_from_bars(cfg, bars, Tcm8Setup(), 23000)
    assert row["accept"] is True
    assert row["penetration_atr"] > 0.20
    assert row["reason"] != REJ_STRUCTURE


def test_close_wrong_side_of_ema8_rejects() -> None:
    cfg = _cfg()
    bars = _structure_bars(True)
    prev_ema = ema_fn([float(b["close"]) for b in bars[:-1]], 8)[-1]
    last = bars[-1]
    t = datetime.fromisoformat(str(last["time"]))
    bars[-1] = _bar(t, prev_ema + 2, prev_ema + 4, prev_ema - 8, prev_ema - 1.0)
    row = _eval_from_bars(cfg, bars, Tcm8Setup(), 23000)
    assert row["accept"] is False
    assert row["reason"] == REJ_WRONG_SIDE


def test_near_key_level_blocks() -> None:
    cfg = _cfg()
    bars = _rejection_bar(_structure_bars(True), long=True)
    close = float(bars[-1]["close"])
    row = _eval_from_bars(cfg, bars, Tcm8Setup(), close + 1.0)
    assert row["accept"] is False
    assert row["reason"] in {REJ_BARRIER, REJ_TARGET_R}


def test_five_point_micro_swing_is_a_wall_not_a_target() -> None:
    """8:11 live long: 5-pt 1m swing + 3.6-pt stop printed 1.39R. That is a wall."""
    cfg = _cfg()
    bars = _rejection_bar(_structure_bars(True), long=True)
    close = float(bars[-1]["close"])
    row = _eval_from_bars(cfg, bars, Tcm8Setup(), close + 5.0)
    assert row["accept"] is False
    assert row["reason"] == REJ_BARRIER


def test_classic_target_exit_never_widens() -> None:
    cfg = _cfg(ENABLE_8TCM_RUNNER=False)
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19990.0,
        target=20040.0,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19990.0,
        tcm8=True,
        ema_entry_tag=ENTRY_LONG,
        event_type=EventType.TCM8.value,
    )
    trade.stop = 19980.0  # attempted widen
    assert manage_tcm8_hold(trade, price=20010.0, cfg=cfg) == ""
    assert abs(trade.stop - 19990.0) < 1e-9
    assert manage_tcm8_hold(trade, price=20040.0, cfg=cfg) == EXIT_KEY_LEVEL
    assert manage_tcm8_hold(trade, price=19990.0, cfg=cfg) == "HARD_STOP"


def test_runner_arms_instead_of_flatten() -> None:
    cfg = _cfg(ENABLE_8TCM_RUNNER=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19990.0,
        target=20040.0,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19990.0,
        tcm8=True,
        ema_entry_tag=ENTRY_LONG,
        event_type=EventType.TCM8.value,
    )
    assert manage_tcm8_hold(trade, price=20010.0, cfg=cfg) == ""
    assert manage_tcm8_hold(trade, price=20040.0, cfg=cfg) == RUNNER_ARM
    trade.tcm8_primary_hit = True
    trade.tcm8_runner = True
    apply_tcm8_runner_trail(trade, cfg=cfg)
    green = tcm8_working_target(Side.LONG, 20040.0, cfg)
    assert abs(trade.stop - green) < 1e-9
    assert manage_tcm8_hold(trade, price=20040.0, cfg=cfg) == ""
    assert trade.stop >= green - 1e-9
    assert manage_tcm8_hold(trade, price=20050.0, cfg=cfg) == ""
    assert abs(trade.stop - (20050.0 - 5.5)) < 1e-9
    frozen = trade.stop
    assert manage_tcm8_hold(trade, price=20048.0, cfg=cfg) == ""
    assert trade.stop >= frozen - 1e-9


def test_ema_hold_uses_same_8tcm_runner() -> None:
    cfg = _cfg(ENABLE_8TCM_RUNNER=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19990.0,
        target=20040.0,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19990.0,
        tcm8=False,
        tcm8_hold=True,
        ema_strategy=True,
        ema_entry_tag="EMA_SNIPER",
        event_type=EventType.EMA_CROSS.value,
    )
    assert uses_tcm8_hold(trade)
    assert manage_tcm8_hold(trade, price=20010.0, cfg=cfg) == ""
    assert manage_tcm8_hold(trade, price=20040.0, cfg=cfg) == RUNNER_ARM
    trade.tcm8_primary_hit = True
    trade.tcm8_runner = True
    apply_tcm8_runner_trail(trade, cfg=cfg)
    green = tcm8_working_target(Side.LONG, 20040.0, cfg)
    assert abs(trade.stop - green) < 1e-9
    assert manage_tcm8_hold(trade, price=20050.0, cfg=cfg) == ""
    assert abs(trade.stop - (20050.0 - 5.5)) < 1e-9


def test_runner_trail_starts_at_green_and_follows_tip() -> None:
    cfg = _cfg(ENABLE_8TCM_RUNNER=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19990.0,
        target=20040.0,
        peak=20040.0,
        trough=20000.0,
        hard_stop=19990.0,
        tcm8=True,
        tcm8_primary_hit=True,
        tcm8_runner=True,
        ema_entry_tag=ENTRY_LONG,
        event_type=EventType.TCM8.value,
    )
    apply_tcm8_runner_trail(trade, cfg=cfg)
    green = tcm8_working_target(Side.LONG, 20040.0, cfg)
    assert abs(trade.stop - green) < 1e-9
    assert abs(trade.hard_stop - 19990.0) < 1e-9
    assert manage_tcm8_hold(trade, price=20040.0, cfg=cfg) == ""
    assert manage_tcm8_hold(trade, price=20052.0, cfg=cfg) == ""
    assert abs(trade.stop - 20046.5) < 1e-9
    assert manage_tcm8_hold(trade, price=20046.5, cfg=cfg) == EXIT_RUNNER_TRAIL


def test_runner_sitting_on_green_does_not_flatten() -> None:
    cfg = _cfg(ENABLE_8TCM_RUNNER=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=20040.0,
        target=20040.0,
        peak=20040.0,
        trough=20000.0,
        hard_stop=19990.0,
        tcm8=True,
        tcm8_primary_hit=True,
        tcm8_runner=True,
        ema_entry_tag=ENTRY_LONG,
        event_type=EventType.TCM8.value,
    )
    green = tcm8_working_target(Side.LONG, 20040.0, cfg)
    trade.stop = green
    trade.peak = green
    assert manage_tcm8_hold(trade, price=green, cfg=cfg) == ""
    assert manage_tcm8_hold(trade, price=green - 0.25, cfg=cfg) == EXIT_GREEN_BANK


def test_short_runner_trails_down_from_green() -> None:
    cfg = _cfg(ENABLE_8TCM_RUNNER=True, ENABLE_8TCM_SHORTS=True)
    trade = PaperTrade(
        side=Side.SHORT,
        entry=20000.0,
        entry_ts=1.0,
        stop=20010.0,
        target=19960.0,
        peak=20000.0,
        trough=19960.0,
        hard_stop=20010.0,
        tcm8=True,
        tcm8_primary_hit=True,
        tcm8_runner=True,
        ema_entry_tag=ENTRY_SHORT,
        event_type=EventType.TCM8.value,
    )
    apply_tcm8_runner_trail(trade, cfg=cfg)
    green = tcm8_working_target(Side.SHORT, 19960.0, cfg)
    assert abs(trade.stop - green) < 1e-9
    assert manage_tcm8_hold(trade, price=19948.0, cfg=cfg) == ""
    assert abs(trade.stop - (19948.0 + 5.5)) < 1e-9
    assert trade.stop <= green + 1e-9


def test_stall_one_point_short_of_swing_still_arms() -> None:
    """20:50 live: peaked 29195.25, target 29196.25, then hard-stopped."""
    cfg = _cfg(ENABLE_8TCM_RUNNER=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=29184.0,
        entry_ts=1.0,
        stop=29175.52,
        target=29196.25,
        peak=29184.0,
        trough=29184.0,
        hard_stop=29175.52,
        tcm8=True,
        ema_entry_tag=ENTRY_LONG,
        event_type=EventType.TCM8.value,
    )
    assert manage_tcm8_hold(trade, price=29193.0, cfg=cfg) == ""
    assert manage_tcm8_hold(trade, price=29195.25, cfg=cfg) == RUNNER_ARM
    assert abs(tcm8_working_target(Side.LONG, 29196.25, cfg) - 29194.75) < 1e-9


def test_trail_walks_with_forming_candle() -> None:
    cfg = _cfg(ENABLE_8TCM_RUNNER=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=20006.25,
        target=20040.0,
        peak=20012.0,
        trough=20000.0,
        hard_stop=19990.0,
        qty=4,
        tcm8=True,
        tcm8_runner=True,
        ema_entry_tag=ENTRY_LONG,
        event_type=EventType.TCM8.value,
    )
    first = manage_tcm8_hold(
        trade, price=20017.5, cfg=cfg, forming={"high": 20018.0, "low": 20010.0}
    )
    assert first == ""
    assert abs(trade.stop - 20012.5) < 1e-9
    manage_tcm8_hold(trade, price=20021.5, cfg=cfg, forming={"high": 20022.0, "low": 20011.0})
    assert abs(trade.stop - 20016.5) < 1e-9
    short = PaperTrade(
        side=Side.SHORT,
        entry=20000.0,
        entry_ts=1.0,
        stop=19993.75,
        target=19960.0,
        peak=20000.0,
        trough=19988.0,
        hard_stop=20010.0,
        qty=4,
        tcm8=True,
        tcm8_runner=True,
        ema_entry_tag=ENTRY_SHORT,
        event_type=EventType.TCM8.value,
    )
    assert manage_tcm8_hold(short, price=19982.5, cfg=cfg, forming={"high": 19990.0, "low": 19982.0}) == ""
    assert abs(short.stop - 19987.5) < 1e-9


def test_dollar_arm_floors_before_green_then_upgrades() -> None:
    """4-lot 8:50: $50 arms ~6 pts in, not at the 12-pt swing. Green still upgrades."""
    cfg = _cfg(ENABLE_8TCM_RUNNER=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=29184.0,
        entry_ts=1.0,
        stop=29175.52,
        target=29196.25,
        peak=29184.0,
        trough=29184.0,
        hard_stop=29175.52,
        qty=4,
        tcm8=True,
        ema_entry_tag=ENTRY_LONG,
        event_type=EventType.TCM8.value,
    )
    assert manage_tcm8_hold(trade, price=29188.0, cfg=cfg) == ""
    assert manage_tcm8_hold(trade, price=29191.0, cfg=cfg) == DOLLAR_ARM
    trade.tcm8_runner = True
    apply_tcm8_runner_trail(trade, cfg=cfg)
    assert abs(trade.stop - 29190.25) < 1e-9
    assert trade.stop < 29194.75
    assert manage_tcm8_hold(trade, price=29195.25, cfg=cfg) == RUNNER_ARM


def test_hud_toggle_and_engine_isolation() -> None:
    cfg = _cfg()
    apply_strategy(cfg, {"tcm8": False})
    assert cfg.ENABLE_8TCM is False
    apply_strategy(cfg, {"tcm8": True})
    assert cfg.ENABLE_8TCM is True
    assert cfg.ENABLE_8TCM_AI_EXIT is False
    assert cfg.ENABLE_8TCM_RUNNER is True
    assert cfg.EMA_LONG_SNIPER is True
    eng = Mark2Engine(_cfg())
    eng.cfg.MODE = RunMode.PAPER_TRADE.value
    for b in _trend_bars(20, 17000, 80, 240):
        eng.on_htf_bar(b, minutes=240, seed=True)
    for b in _trend_bars(20, 19000, 30, 60):
        eng.on_htf_bar(b, minutes=60, seed=True)
    for b in _trend_bars(30, 20000, 4.0, 1):
        eng.on_bar_close(b, seed=True)
    assert eng.paper is None
    eng.cfg.ENABLE_8TCM = False
    last = _trend_bars(1, 20120, 1, 1, datetime(2026, 9, 14, 13, 0, tzinfo=_ET))[0]
    eng.on_bar_close(last, seed=False)
    assert eng.paper is None


def test_live_checklist_blocks_on_structure_then_chop() -> None:
    row = {
        "accept": False,
        "reason": REJ_NO_CLEAR_TREND,
        "trend": "UNCLEAR",
        "htf_1h": TREND_BULLISH,
        "htf_4h": "UNCLEAR",
        "range_state": TREND_RANGING,
        "pullback": False,
    }
    steps = {s["id"]: s for s in tcm8_live_checklist(row)}
    assert steps["trend"]["status"] == "fail"
    assert steps["chop"]["status"] == "fail"
    assert steps["retrace"]["status"] == "wait"
    assert steps["fire"]["status"] == "wait"
    nxt = tcm8_next_gate(list(steps.values()))
    assert "1H + 4H" not in nxt
    assert nxt.startswith("BLOCKED · TREND")
    hud = tcm8_trade_hud(_cfg(), row)
    assert hud["checklist"]
    assert "WAITING FOR TREND" in hud["call"] or "BLOCKED" in hud["call"]


def test_live_checklist_ready_when_accept() -> None:
    row = {
        "accept": True,
        "reason": ENTRY_LONG_REASON,
        "direction": "LONG",
        "trend": TREND_BULLISH,
        "sequence": "HIGHER_HIGH -> HIGHER_LOW",
        "htf_1h": TREND_BULLISH,
        "htf_4h": "UNCLEAR",
        "range_state": "TRENDING",
        "pullback": True,
        "retracement": True,
        "tested": True,
        "rejection_type": EMA8_CLOSE_REJECT,
        "close_side": "ABOVE",
        "barrier_type": "PREVIOUS_DAY_HIGH",
        "barrier_price": 20148.0,
        "target_r": 1.82,
        "quality": "A_SETUP",
        "entry": 20112.0,
        "ema8": 20110.25,
        "distance_ema_atr": 0.08,
        "penetration_atr": 0.04,
        "state": "READY_TO_EXECUTE",
    }
    steps = tcm8_live_checklist(row)
    assert all(s["status"] == "pass" for s in steps)
    assert tcm8_next_gate(steps).startswith("READY LONG")
    hud = tcm8_trade_hud(_cfg(), row)
    assert "REJECTION CONFIRMED" in hud["call"]


def test_hud_blocked_not_ready_when_session_low_too_close() -> None:
    row = {
        "accept": False,
        "reason": REJ_BARRIER,
        "direction": "SHORT",
        "trend": TREND_BEARISH,
        "state": "EMA8_REJECTION_CONFIRMED",
        "range_state": "TRENDING",
        "retracement": True,
        "tested": True,
        "rejection_type": EMA8_CLOSE_REJECT,
        "close_side": "BELOW",
        "primary_target_type": "CURRENT_SESSION_LOW",
        "barrier_type": "CURRENT_SESSION_LOW",
        "barrier_distance_atr": 0.0445,
        "quality": "A_SETUP",
    }
    hud = tcm8_trade_hud(_cfg(), row)
    assert hud["badge"] == "BLOCKED"
    assert "READY SHORT" not in hud["call"]
    assert "TOO CLOSE" in hud["call"]
    assert hud["accept"] is False


def test_tcm8_overlay_pushed_to_chart_sink() -> None:
    class _Sink:
        def __init__(self) -> None:
            self.msgs: list[dict] = []

        def send_tcm8_overlay(self, **payload) -> None:
            self.msgs.append(dict(payload))

        def send_barrier_overlay(self, **payload) -> None:
            return

    import tempfile
    from pathlib import Path

    sink = _Sink()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        eng = Mark2Engine(Mark2Config(), persist_path=path, sink=sink)
        t0 = datetime(2026, 9, 14, 10, 0, tzinfo=_ET)
        for i in range(20):
            px = 29250.0 + i
            eng.on_bar_close(_bar(t0 + timedelta(minutes=i), px, px + 2, px - 1, px + 1), seed=True)
        eng.set_strategy({"tcm8": True}, persist=False)
        assert sink.msgs
        last = sink.msgs[-1]
        assert last["enabled"] is True
        assert last["ema1m"] > 0
        eng.set_strategy({"tcm8": False}, persist=False)
        assert sink.msgs[-1]["enabled"] is False


def test_trade_screen_shows_8tcm_when_pack_on() -> None:
    eng = Mark2Engine(Mark2Config())
    assert eng.hud_snapshot()["kickerLong"] == "RECON LONG"
    eng.set_strategy({"tcm8": True}, persist=False)
    snap = eng.hud_snapshot()
    assert snap["tcm8"]["enabled"] is True
    assert snap["tcm8"]["exclusive"] is False
    assert snap["kickerLong"] == "RECON LONG"
    assert snap["kickerShort"] == "RECON SHORT"
    assert snap["strategy"]["long_sniper"] is True
    assert snap["strategy"]["scout"] is True
    assert snap["strategy"]["momentum_barriers"] is False
    assert eng.cfg.ALLOW_LEGACY_ENTRIES is False
    eng.set_strategy({"tcm8": False}, persist=False)
    snap = eng.hud_snapshot()
    assert snap["tcm8"]["enabled"] is False
    assert snap["kickerLong"] == "RECON LONG"
    assert snap["strategy"]["long_sniper"] is True


def test_8tcm_pack_blocks_legacy_tick_entries() -> None:
    eng = Mark2Engine(Mark2Config())
    eng.set_strategy({"tcm8": True}, persist=False)
    eng.cfg.ENABLE_EMA_STRATEGY = False
    eng.cfg.ALLOW_LEGACY_ENTRIES = True
    t0 = datetime(2026, 9, 14, 10, 0, tzinfo=_ET)
    for i in range(20):
        px = 29250.0 + i
        eng.on_bar_close(_bar(t0 + timedelta(minutes=i), px, px + 2, px - 1, px + 1), seed=True)
    from mark2.types import Tick

    out = eng.on_tick(Tick(ts=t0.timestamp() + 21 * 60, price=29281.25))
    assert eng.paper is None
    assert out is not None
    assert out.get("reject") == "TCM8_ONLY"
    snap = eng.hud_snapshot()
    assert snap["tcm8"]["exclusive"] is True


def test_8tcm_and_ema_share_one_trade_slot() -> None:
    cfg = _cfg()
    apply_strategy(cfg, {"tcm8": True})
    assert cfg.ENABLE_8TCM is True
    assert cfg.EMA_LONG_SNIPER is True
    assert ema_92050_live(cfg) is True
    assert tcm8_only_mode(cfg) is False

    eng = Mark2Engine(cfg)
    ema = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19990.0,
        target=20040.0,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19990.0,
        ema_strategy=True,
        qty=1,
    )
    eng.paper = ema
    assert eng._tcm8_on_completed_bar() is False
    assert eng.paper is ema
    assert bool(getattr(eng.paper, "tcm8", False)) is False

    tcm = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19990.0,
        target=20040.0,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19990.0,
        tcm8=True,
        qty=1,
    )
    eng.paper = tcm
    eng._ema_pending_side = Side.LONG
    eng._ema_try_arm_signal(Side.LONG, None, allow_entry=True, why="EMA_SNIPER")
    assert eng.paper is tcm
    assert bool(eng.paper.tcm8) is True
    assert eng._tcm8_execute(
        {
            "direction": "LONG",
            "entry": 20100.0,
            "stop": 20080.0,
            "barrier_price": 20150.0,
            "atr": 4.0,
        }
    ) is False
    snap = eng.hud_snapshot()
    assert snap["kickerLong"] == "8TCM LONG"


def test_8tcm_on_does_not_force_ema_92050() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = False
    cfg.EMA_LONG_SNIPER = False
    cfg.EMA_SHORT_SNIPER = False
    cfg.EMA_LEFTOVER_LONG = False
    apply_strategy(cfg, {"tcm8": True})
    assert cfg.ENABLE_8TCM is True
    assert cfg.ENABLE_EMA_STRATEGY is False
    assert cfg.EMA_LONG_SNIPER is False
    assert ema_92050_live(cfg) is False
    assert tcm8_only_mode(cfg) is True
    apply_strategy(cfg, {"ema_92050": True})
    assert ema_92050_live(cfg) is True
    assert tcm8_only_mode(cfg) is False


def test_ema_completed_bar_runs_before_8tcm() -> None:
    eng = Mark2Engine(_cfg())
    order: list[str] = []
    orig_ema = eng._ema_on_completed_bar
    orig_tcm = eng._tcm8_on_completed_bar

    def ema(*, allow_entry: bool = True) -> None:
        order.append("ema")
        orig_ema(allow_entry=allow_entry)

    def tcm() -> bool:
        order.append("tcm8")
        return orig_tcm()

    eng._ema_on_completed_bar = ema  # type: ignore[method-assign]
    eng._tcm8_on_completed_bar = tcm  # type: ignore[method-assign]
    t0 = datetime(2026, 9, 14, 10, 0, tzinfo=_ET)
    eng.on_bar_close(_bar(t0, 20000, 20001, 19999, 20000.5), seed=False)
    assert order[:2] == ["ema", "tcm8"]


def test_8tcm_ranging_does_not_block_ema_sniper() -> None:
    from mark2.ema_strategy import EmaStack
    from mark2.types import MarketSnapshot

    cfg = _cfg()
    apply_strategy(cfg, {"tcm8": True})
    eng = Mark2Engine(cfg)
    eng._ema_armed = True
    eng.completed_bars = [
        {
            "time": "t0",
            "open": 29300.0,
            "high": 29350.0,
            "low": 29290.0,
            "close": 29341.25,
            "volume": 10,
        }
    ]
    eng.context._cache["atr"] = 30.0
    eng._ema_atr = lambda: 30.0  # type: ignore[method-assign]
    eng._ema_stop_atr = lambda: 30.0  # type: ignore[method-assign]
    eng._tcm8_last = {"accept": False, "reason": REJ_RANGE, "range_state": TREND_RANGING}
    stack = EmaStack(
        ema9=29315.8434,
        ema20=29310.9211,
        ema50=29314.2883,
        prev9=29309.4917,
        prev20=29307.7286,
        prev50=29313.1878,
    )
    eng.last_snap = MarketSnapshot(
        ts=1.0,
        price=29341.25,
        completed_bars=eng.completed_bars,
        forming_bar=None,
        trend_bias="BEARISH",
        trend_regime="CHOPPY",
    )
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why="EMA_SNIPER_LONG")
    assert eng.paper is not None or eng._ema_pending_side == Side.LONG
    assert tcm8_only_mode(eng.cfg) is False


def test_ema_fill_uses_8tcm_hold() -> None:
    eng = Mark2Engine(_cfg())
    apply_strategy(eng.cfg, {"tcm8": False, "ema_92050": True})
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19980.0,
        target=20012.5,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19980.0,
        ema_strategy=True,
        ema_entry_tag="EMA_SNIPER",
        qty=1,
    )
    eng.paper = trade
    eng._stamp_tcm8_hold()
    assert trade.tcm8_hold is True
    assert trade.tcm8 is False
    assert uses_tcm8_hold(trade) is True
    assert trade.tcm8_runner is False
    assert abs(trade.stop - 19980.0) < 1e-9
    assert abs(trade.hard_stop - 19980.0) < 1e-9
    # No barrier book → 1.5R fallback, same preferred R as 8TCM.
    assert abs(trade.target - 20030.0) < 1e-9


def test_initial_stop_is_20_points_for_both_methods() -> None:
    cfg = _cfg()
    assert abs(tcm8_initial_stop(20000.0, Side.LONG, cfg) - 19980.0) < 1e-9
    assert abs(tcm8_initial_stop(20000.0, Side.SHORT, cfg) - 20020.0) < 1e-9
    assert uses_shared_tcm8_exit("EMA_SNIPER") is True
    assert uses_shared_tcm8_exit("8TCM_LONG") is True
    assert uses_shared_tcm8_exit("413_BREAKOUT") is False
    eng = Mark2Engine(cfg)
    eng.execution.enter = lambda intent: "PAPER_EXECUTE"  # type: ignore[method-assign]
    eng.acct_risk.clamp_qty = lambda q: q  # type: ignore[method-assign]
    assert eng._tcm8_execute(
        {
            "direction": "LONG",
            "entry": 20000.0,
            "stop": 19996.0,
            "barrier_price": 20040.0,
            "atr": 4.0,
        }
    )
    assert eng.paper is not None
    assert abs(eng.paper.stop - 19980.0) < 1e-9
    assert abs(eng.paper.hard_stop - 19980.0) < 1e-9
    tight = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19996.0,
        target=20012.5,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19996.0,
        ema_strategy=True,
        ema_entry_tag="EMA_SNIPER",
        qty=1,
    )
    eng.paper = tight
    eng._stamp_tcm8_hold()
    assert abs(tight.stop - 19980.0) < 1e-9
    assert abs(tight.hard_stop - 19980.0) < 1e-9


def test_ema_fill_uses_key_level_target() -> None:
    eng = Mark2Engine(_cfg())
    apply_strategy(eng.cfg, {"tcm8": False, "ema_92050": True})
    eng._barriers = BarrierBook(previous_day_high=20040.0)
    eng._ema_atr = lambda: 20.0  # type: ignore[method-assign]
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19980.0,
        target=20012.5,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19980.0,
        ema_strategy=True,
        ema_entry_tag="EMA_SNIPER",
        qty=1,
    )
    eng.paper = trade
    eng._stamp_tcm8_hold()
    assert trade.tcm8_hold is True
    assert abs(trade.target - 20040.0) < 1e-9
    green = tcm8_working_target(Side.LONG, trade.target, eng.cfg)
    assert abs(green - 20038.5) < 1e-9


def test_ema_does_not_stamp_413() -> None:
    cfg = _cfg()
    apply_strategy(cfg, {"ema_92050": True})
    eng = Mark2Engine(cfg)
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19990.0,
        target=20040.0,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19990.0,
        ema_strategy=True,
        ema_entry_tag="413_BREAKOUT",
        qty=1,
    )
    eng.paper = trade
    eng._stamp_tcm8_hold()
    assert trade.tcm8_hold is False


def test_stats_do_not_mix_into_recon() -> None:
    eng = Mark2Engine(_cfg())
    before = eng.stats.summary()["trades"]
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19990.0,
        target=20040.0,
        peak=20020.0,
        trough=19998.0,
        hard_stop=19990.0,
        tcm8=True,
        tcm8_grade="A_SETUP",
        tcm8_rejection=PIN_BAR,
        tcm8_target_r=2.0,
        ema_entry_tag=ENTRY_LONG,
        event_type=EventType.TCM8.value,
        mfe=20.0,
        mae=2.0,
        qty=1,
    )
    eng.paper = trade
    from mark2.types import MarketSnapshot, ScoreBundle, Tick

    snap = MarketSnapshot(
        ts=2.0,
        price=20040.0,
        completed_bars=[],
        forming_bar=None,
        hour_et=11,
    )
    eng._close_position(Tick(ts=2.0, price=20040.0), snap, ScoreBundle(), EXIT_KEY_LEVEL)
    assert eng.stats.summary()["trades"] == before
    assert eng._tcm8_stats.trades == 1
    assert eng._tcm8_stats.wins == 1


def test_confirmed_swings_wait_for_right_side_bars() -> None:
    bars = _structure_bars(True)
    # Pivot at 40 needs bars 41 and 42 complete. Truncate to 42 bars (indices 0-41):
    # last index 41 = 40+1, strength 2 not met.
    early = bars[:42]
    highs, _lows = confirmed_swings(early, 2)
    assert all(h["index"] != 40 for h in highs)
    later = bars[:43]
    highs, _lows = confirmed_swings(later, 2)
    assert any(h["index"] == 40 for h in highs)


def test_classify_structure_bull_and_bear() -> None:
    bull = classify_8tcm_trend(_structure_bars(True), _cfg())
    bear = classify_8tcm_trend(_structure_bars(False), _cfg())
    assert bull["state"] == TREND_BULLISH
    assert bull["hh"] and bull["hl"]
    assert bear["state"] == TREND_BEARISH
    assert bear["lh"] and bear["ll"]


def test_unclear_1m_uses_1h_trend_not_waiting() -> None:
    cfg = _cfg(ENABLE_8TCM_SHORTS=True)
    bars_1m = _trend_bars(40, 20000, 0.5, 1)
    m1 = classify_8tcm_trend(bars_1m, cfg)
    assert m1["state"] not in (TREND_BEARISH,)
    row = evaluate_tcm8(
        cfg=cfg,
        bars_1m=bars_1m,
        bars_1h=_trend_bars(24, 21000, -12, 60),
        bars_4h=_trend_bars(20, 20000, 20, 240),
        book=_book(23000, 17000),
        setup=Tcm8Setup(),
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=True,
        allow_short=True,
    )
    assert row["trend"] == TREND_BEARISH
    assert row["state"] != "WAITING_FOR_TREND"
    assert row["reason"] not in (REJ_NO_CLEAR_TREND, "REJECT_BULLISH_STRUCTURE_NOT_CONFIRMED")
    assert str(row.get("trend_source") or "").startswith("1H")


def test_short_rejection_accepts_with_shorts_on() -> None:
    cfg = _cfg(ENABLE_8TCM_SHORTS=True)
    bars = _rejection_bar(_structure_bars(False), long=False)
    row = evaluate_tcm8(
        cfg=cfg,
        bars_1m=bars,
        bars_1h=_trend_bars(20, 21000, -12, 60),
        bars_4h=_trend_bars(20, 22000, 20, 240),
        book=_book(23000, 17000),
        setup=Tcm8Setup(),
        armed=True,
        connected=True,
        cooldown=False,
        allow_long=True,
        allow_short=True,
    )
    assert row["trend"] == TREND_BEARISH
    assert row["htf_4h"] == TREND_BULLISH
    assert row["accept"] is True
    assert row["reason"] == ENTRY_SHORT_REASON


def test_status_board_follows_the_state_machine() -> None:
    import os
    import tempfile

    from mark2.tcm8_status import (
        STEP_GATES,
        STEP_READY,
        STEP_RETRACE,
        STEP_TARGET,
        STEP_TRADE,
        STEP_WAITING_TREND,
        STEPS,
        build_tcm8_board,
        pipeline_index,
        publish_tcm8_status,
        read_tcm8_status,
        tcm8_status_path,
    )
    from mark2.tcm8_watch import marquee_slice, render

    assert "BRENTS TRADING BOT" in marquee_slice("BRENTS TRADING BOT", 0, 48)
    assert marquee_slice("BRENTS TRADING BOT", 0, 20) != marquee_slice("BRENTS TRADING BOT", 8, 20)

    assert pipeline_index(state="WAITING_FOR_TREND") == STEPS.index(STEP_WAITING_TREND)
    assert pipeline_index(state="WAITING_FOR_RETRACEMENT") == STEPS.index(STEP_RETRACE)
    assert pipeline_index(state="EMA8_REJECTION_CONFIRMED", reason="REJECT_CHASE") == STEPS.index(STEP_GATES)
    assert pipeline_index(state="READY_TO_EXECUTE", accept=True) == STEPS.index(STEP_READY)
    assert pipeline_index(state="TRADE_ACTIVE", in_trade=True) == STEPS.index(STEP_TRADE)
    assert pipeline_index(state="TRADE_ACTIVE", in_trade=True, runner=True) == STEPS.index(STEP_TARGET)
    board = build_tcm8_board(
        enabled=True,
        row={"state": "WAITING_FOR_RETRACEMENT", "trend": "BEARISH", "reason": "REJECT_NO_RETRACEMENT"},
        armed=True,
        connected=True,
        flat=True,
    )
    assert board["step"] == STEP_RETRACE
    text = render(board)
    assert "WAITING_FOR_RETRACEMENT" in text
    assert "READY_TO_EXECUTE" in text
    assert "PRIMARY TARGET" in text
    assert "4H" not in text
    old = os.environ.get("LOCALAPPDATA")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LOCALAPPDATA"] = tmp
        try:
            publish_tcm8_status(board, force=True)
            saved = read_tcm8_status()
            assert saved["step"] == STEP_RETRACE
            assert tcm8_status_path().is_file()
        finally:
            if old is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old


def test_cmd_tables_show_session_pnl() -> None:
    from mark2.tcm8_status import format_tcm8_cmd_tables
    from mark2.tcm8_watch import render

    board = {
        "date": "2026-09-14",
        "enabled": True,
        "state": "WAITING_FOR_TREND",
        "step_index": 0,
        "steps": ["WAITING_FOR_TREND"],
        "reason": "",
        "session": {
            "trades": 2,
            "wins": 1,
            "losses": 1,
            "net": -24.88,
            "gross_win": 13.04,
            "gross_loss": 37.92,
            "pts": 1.0,
            "win_rate": 50.0,
            "avg_win": 13.04,
            "avg_loss": 37.92,
            "pf": 0.34,
        },
        "trades": [
            {
                "side": "LONG",
                "qty": 4,
                "entry": 29159.25,
                "exit": 29155.75,
                "stop": 29155.65,
                "target": 29164.25,
                "pts": -3.5,
                "pnl": -37.92,
                "fees": 9.92,
                "mfe": 1.5,
                "mae": 3.5,
                "r_mult": -0.97,
                "reason": "NT_FLAT",
                "hold_sec": 17,
                "clock_ts": 1789431078,
                "point_value": 2.0,
            }
        ],
        "open_trade": None,
    }
    text = format_tcm8_cmd_tables(board)
    assert "SESSION" in text
    assert "NET" in text
    assert "LAST EXIT BREAKDOWN" in text
    assert "NT_FLAT" in text
    assert "-$37.92" in text
    assert "fees" in text
    assert "best" in text
    shown = render(board)
    assert "SESSION" in shown
    assert "#  CLOCK  SIDE" in shown
    assert "4H" not in shown


def test_pytest_does_not_touch_live_cmd_files() -> None:
    from mark2.tcm8_status import tcm8_ledger_path, tcm8_status_path

    status = tcm8_status_path()
    ledger = tcm8_ledger_path()
    assert "pytest" in status.name
    assert "pytest" in ledger.name
    assert "ReconSniper" not in str(status)
    assert "ReconSniper" not in str(ledger)


def test_8tcm_log_is_short_and_gates_illuminate() -> None:
    wait = format_tcm8_log({"accept": False, "direction": "SHORT", "reason": REJ_NO_RETRACEMENT})
    assert wait == "SHORT · NO RETRACEMENT"
    fire = format_tcm8_log({"accept": True, "direction": "LONG", "rejection_type": "PIN_BAR"})
    assert fire == "FIRE LONG · PIN_BAR"
    row = {
        "accept": False,
        "reason": REJ_NO_RETRACEMENT,
        "trend": TREND_BEARISH,
        "direction": "SHORT",
        "range_state": "TRENDING",
        "retracement": False,
        "htf_1h": TREND_BEARISH,
    }
    steps = tcm8_live_checklist(row)
    hot = [s for s in steps if s.get("hot")]
    assert len(hot) == 1
    assert hot[0]["id"] == "retrace"
    eng = Mark2Engine(_cfg())
    eng._tcm8_log_candidate({"accept": False, "direction": "SHORT", "reason": REJ_NO_RETRACEMENT})
    snap = eng.hud_snapshot()
    assert snap["logTcm8"]
    assert snap["logTcm8"][-1]["sys"] == "tcm8"
    assert "NO RETRACEMENT" in snap["logTcm8"][-1]["note"]
    assert "ema8:" not in snap["logTcm8"][-1]["note"]

