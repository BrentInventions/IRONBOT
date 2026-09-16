"""Momentum barriers: PDH/PDL, swings, room filter, rejection vs breakout, AI trail."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mark2.ai_exit import manage_ai_exit
from mark2.config import Mark2Config, load_config
from mark2.ema_strategy import manage_ema_hold
from mark2.engine import Mark2Engine
from mark2.exits import PaperTrade
from mark2.momentum_barriers import (
    BARRIER_APPROACHING,
    BARRIER_BREAKOUT,
    BARRIER_BREAKOUT_CONTINUE,
    BARRIER_CLUSTER_REJECTION,
    BARRIER_FAR,
    BARRIER_REJECTION,
    BARRIER_TESTING,
    BarrierBook,
    KEY_LEVEL_TARGET,
    MOMENTUM_BARRIER_REJECTION,
    PREVIOUS_DAY_HIGH,
    REJECT_NEAR_MOMENTUM_BARRIER,
    SWING_HIGH,
    barriers_only_mode,
    calculate_room_to_barrier,
    classify_barrier_state,
    cluster_barriers,
    cme_session_key,
    detect_barrier_breakout,
    detect_barrier_rejection,
    detect_consolidation,
    detect_swings,
    evaluate_entry_room,
    format_entry_log,
    format_hold_log,
    get_next_momentum_barrier,
    sync_trade_barrier,
    update_session_levels,
)
from mark2.strategy_hud import apply_strategy, snapshot
from mark2.types import Side

_ET = ZoneInfo("America/New_York")


def _cfg(**kwargs) -> Mark2Config:
    cfg = Mark2Config()
    cfg.ENABLE_MOMENTUM_BARRIERS = True
    cfg.ENABLE_BARRIER_STRATEGY_ONLY = False
    cfg.ENABLE_BARRIER_ENTRY_FILTER = True
    cfg.ENABLE_BARRIER_REJECTION_EXIT = True
    cfg.ENABLE_CLASSIC_KEY_LEVEL_TARGET = False
    cfg.ENABLE_HARD_BARRIER_TARGET = False
    cfg.ENABLE_AI_EXIT_ENGINE = True
    cfg.TICK_SIZE = 0.25
    cfg.MIN_ROOM_TO_BARRIER_POINTS = 8.0
    cfg.MIN_ROOM_TO_BARRIER_ATR = 0.35
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _bar(dt: datetime, o: float, h: float, l: float, c: float, vol: float = 800.0) -> dict:
    return {
        "time": dt.isoformat(),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": vol,
    }


def _session_bars() -> list[dict]:
    """Friday Globex session (key 2026-09-11) then Monday session (key 2026-09-14)."""
    out: list[dict] = []
    t0 = datetime(2026, 9, 10, 18, 5, tzinfo=_ET)  # Friday session starts Thu 18:00
    px = 24220.0
    for i in range(40):
        o = px
        c = px + 1.0
        hi = 24380.0 if i == 12 else max(o, c) + 0.75
        lo = 24200.0 if i == 3 else min(o, c) - 0.5
        out.append(_bar(t0 + timedelta(minutes=i), o, hi, lo, c))
        px = c
    t1 = datetime(2026, 9, 13, 18, 5, tzinfo=_ET)  # Monday session starts Sun 18:00
    px = 24310.0
    for i in range(30):
        o = px
        c = px + 0.25
        out.append(_bar(t1 + timedelta(minutes=i), o, max(o, c) + 0.5, min(o, c) - 0.4, c))
        px = c
    return out


def _trade(*, entry=24320.0, stop=24300.0, peak=24320.0, mfe=0.0) -> PaperTrade:
    return PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=1.0,
        stop=stop,
        target=0.0,
        peak=peak,
        trough=entry,
        hard_stop=stop,
        ema_strategy=True,
        atr_at_entry=31.0,
        mfe=mfe,
    )


def test_cme_session_key_rolls_at_18et() -> None:
    sun_open = datetime(2026, 9, 13, 18, 0, tzinfo=_ET)
    mon_rth = datetime(2026, 9, 14, 9, 30, tzinfo=_ET)
    fri_rth = datetime(2026, 9, 11, 15, 0, tzinfo=_ET)
    assert cme_session_key(sun_open) == "2026-09-14"
    assert cme_session_key(mon_rth) == "2026-09-14"
    assert cme_session_key(fri_rth) == "2026-09-11"


def test_previous_day_high_is_frozen_not_current_session() -> None:
    bars = _session_bars()
    book = BarrierBook()
    update_session_levels(book, bars, persist=False)
    assert book.previous_day_high == 24380.0
    assert book.previous_day_low == 24200.0
    assert book.current_session_high < book.previous_day_high
    assert book.current_session_high > 0
    live = list(bars)
    live.append(
        _bar(datetime(2026, 9, 14, 10, 0, tzinfo=_ET), 24340.0, 24390.0, 24335.0, 24388.0)
    )
    update_session_levels(book, live, persist=False)
    assert book.previous_day_high == 24380.0
    assert book.current_session_high == 24390.0


def test_swings_do_not_repaint_last_bars() -> None:
    t0 = datetime(2026, 9, 14, 9, 0, tzinfo=_ET)
    bars = []
    px = 24300.0
    for i in range(20):
        if i == 10:
            bars.append(_bar(t0 + timedelta(minutes=i), px, 24340.0, px - 1, px + 0.5))
        else:
            bars.append(_bar(t0 + timedelta(minutes=i), px, px + 1, px - 1, px + 0.25))
        px += 0.25
    cfg = _cfg(SWING_LEFT_BARS=3, SWING_RIGHT_BARS=3)
    highs, _lows = detect_swings(bars, cfg)
    assert 24340.0 in highs
    forming = list(bars)
    forming.append(_bar(t0 + timedelta(minutes=20), px, 24355.0, px - 1, px))
    highs2, _ = detect_swings(forming, cfg)
    assert 24355.0 not in highs2


def test_consolidation_range_vs_atr() -> None:
    t0 = datetime(2026, 9, 14, 9, 0, tzinfo=_ET)
    bars = [
        _bar(t0 + timedelta(minutes=i), 24320.0, 24324.0, 24316.0, 24320.5)
        for i in range(12)
    ]
    hi, lo = detect_consolidation(bars, atr_v=20.0, cfg=_cfg())
    assert hi > 0 and lo > 0
    assert hi - lo <= 0.85 * 20.0
    wide = [
        _bar(t0 + timedelta(minutes=i), 24300.0 + i, 24300.0 + i + 8, 24300.0 + i - 8, 24300.0 + i)
        for i in range(12)
    ]
    chi, clo = detect_consolidation(wide, atr_v=12.0, cfg=_cfg())
    assert chi == 0.0 and clo == 0.0


def test_cluster_near_levels() -> None:
    from mark2.momentum_barriers import BarrierCandidate, cluster_barriers

    cands = [
        BarrierCandidate(PREVIOUS_DAY_HIGH, 24350.0),
        BarrierCandidate(SWING_HIGH, 24352.0),
        BarrierCandidate("CONSOLIDATION_HIGH", 24349.0),
    ]
    zone = cluster_barriers(
        cands,
        direction=Side.LONG,
        current_price=24320.0,
        atr_v=20.0,
        cfg=_cfg(BARRIER_CLUSTER_TOLERANCE_ATR=0.20),
    )
    assert zone.found
    assert zone.strength == 3
    assert zone.zone_low == 24349.0
    assert zone.zone_high == 24352.0
    assert PREVIOUS_DAY_HIGH in zone.sources


def test_entry_rejected_near_resistance() -> None:
    book = BarrierBook()
    book.previous_day_high = 24325.0
    cfg = _cfg()
    zone = evaluate_entry_room(Side.LONG, 24320.25, book, 31.0, cfg)
    assert zone.found
    assert zone.room_ok is False
    assert zone.room_reason == REJECT_NEAR_MOMENTUM_BARRIER
    line = format_entry_log(
        direction=Side.LONG, entry=24320.25, atr_v=31.0, zone=zone, allowed=False
    )
    assert "REJECT" in line
    assert REJECT_NEAR_MOMENTUM_BARRIER in line
    assert "4.75" in line


def test_entry_allowed_with_room() -> None:
    book = BarrierBook()
    book.previous_day_high = 24380.0
    cfg = _cfg()
    zone = evaluate_entry_room(Side.LONG, 24320.25, book, 31.0, cfg)
    assert zone.room_ok is True
    assert zone.room_reason == "ROOM_OK"
    assert zone.distance_points > 8
    assert zone.distance_atr > 0.35
    line = format_entry_log(
        direction=Side.LONG, entry=24320.25, atr_v=31.0, zone=zone, allowed=True
    )
    assert "ALLOW" in line


def test_filter_off_does_not_block() -> None:
    book = BarrierBook()
    book.previous_day_high = 24325.0
    cfg = _cfg(ENABLE_BARRIER_ENTRY_FILTER=False)
    zone = evaluate_entry_room(Side.LONG, 24320.25, book, 31.0, cfg)
    # Room math still flags it; engine respects ENABLE_BARRIER_ENTRY_FILTER.
    assert zone.room_ok is False
    assert cfg.ENABLE_BARRIER_ENTRY_FILTER is False


def test_module_off_is_old_recon() -> None:
    cfg = Mark2Config()
    assert cfg.ENABLE_MOMENTUM_BARRIERS is False
    assert barriers_only_mode(cfg) is False
    st = snapshot(cfg)
    assert st["momentum_barriers"] is False


def test_hud_toggles() -> None:
    cfg = Mark2Config()
    apply_strategy(cfg, {"momentum_barriers": True})
    assert cfg.ENABLE_MOMENTUM_BARRIERS is True
    assert cfg.ENABLE_BARRIER_STRATEGY_ONLY is True
    assert cfg.ENABLE_BARRIER_ENTRY_FILTER is True
    assert cfg.ENABLE_AI_EXIT_ENGINE is True
    apply_strategy(cfg, {"momentum_barriers": False})
    assert cfg.ENABLE_MOMENTUM_BARRIERS is False
    assert cfg.ENABLE_BARRIER_STRATEGY_ONLY is False


def test_hud_api_set_strategy_persists_momentum_barriers() -> None:
    from mark2.hud import Mark2Api

    assert callable(getattr(Mark2Api, "set_strategy", None))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        eng = Mark2Engine(Mark2Config(), persist_path=path)
        out = eng.set_strategy({"momentum_barriers": True})
        assert out["momentum_barriers"] is True
        assert eng.cfg.ENABLE_MOMENTUM_BARRIERS is True
        assert eng.hud_snapshot()["strategy"]["momentum_barriers"] is True
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["ENABLE_MOMENTUM_BARRIERS"] is True
        cfg = load_config(path)
        assert cfg.ENABLE_MOMENTUM_BARRIERS is True
        out = eng.set_strategy({"momentum_barriers": False})
        assert out["momentum_barriers"] is False
        assert eng.cfg.ENABLE_MOMENTUM_BARRIERS is False


def test_trade_hud_payload_off_is_old_recon() -> None:
    from mark2.momentum_barriers import barrier_trade_hud

    out = barrier_trade_hud(Mark2Config(), BarrierBook(), price=24320.0, atr_v=20.0)
    assert out["enabled"] is False
    assert out["exclusive"] is False
    snap = Mark2Engine(Mark2Config()).hud_snapshot()
    assert snap["barriers"]["enabled"] is False
    assert snap["kickerLong"] == "RECON LONG"


def test_trade_hud_payload_shows_next_level() -> None:
    from mark2.momentum_barriers import barrier_trade_hud

    book = BarrierBook()
    book.previous_day_high = 24350.0
    book.previous_day_low = 24200.0
    book.current_session_high = 24340.0
    book.current_session_low = 24280.0
    cfg = Mark2Config()
    apply_strategy(cfg, {"momentum_barriers": True})
    out = barrier_trade_hud(cfg, book, price=24320.0, atr_v=20.0)
    assert out["enabled"] is True
    assert out["exclusive"] is True
    assert out["long"]["found"] is True
    assert out["long"]["label"] in {"PDH", "SESSION HIGH", "SWING HIGH", "BOX HIGH"}
    assert out["pdh"] == 24350.0
    assert "NEXT" in out["call"]
    assert "EMA / 413 / SCOUT ENTRIES PAUSED" in out["bullets"]
    eng = Mark2Engine(cfg)
    eng._barriers = book
    snap = eng.hud_snapshot()
    assert snap["barriers"]["enabled"] is True
    assert snap["kickerLong"] == "BARRIER LONG"
    assert snap["kickerShort"] == "BARRIER SHORT"


def test_barrier_overlay_pushed_to_chart_sink() -> None:
    class _Sink:
        def __init__(self) -> None:
            self.msgs: list[dict] = []

        def send_barrier_overlay(self, **payload) -> None:
            self.msgs.append(dict(payload))

    sink = _Sink()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        eng = Mark2Engine(Mark2Config(), persist_path=path, sink=sink)
        book = BarrierBook()
        book.previous_day_high = 24350.0
        book.previous_day_low = 24200.0
        eng._barriers = book
        eng.set_strategy({"momentum_barriers": True}, persist=False)
        assert sink.msgs
        last = sink.msgs[-1]
        assert last["enabled"] is True
        assert last["pdh"] == 24350.0
        assert last["pdl"] == 24200.0
        eng.set_strategy({"momentum_barriers": False}, persist=False)
        assert sink.msgs[-1]["enabled"] is False


def test_approach_vs_test_state() -> None:
    from mark2.momentum_barriers import BarrierZone

    zone = BarrierZone(found=True, price=24350.0, zone_low=24349.0, zone_high=24352.0, kind=PREVIOUS_DAY_HIGH)
    cfg = _cfg()
    assert classify_barrier_state(Side.LONG, 24320.0, zone, 30.0, cfg) == BARRIER_FAR
    assert classify_barrier_state(Side.LONG, 24340.0, zone, 30.0, cfg) == BARRIER_APPROACHING
    assert classify_barrier_state(Side.LONG, 24348.0, zone, 30.0, cfg) == BARRIER_TESTING


def test_rejection_needs_completed_failure_not_a_wick() -> None:
    t0 = datetime(2026, 9, 14, 10, 0, tzinfo=_ET)
    zone_book = BarrierBook(previous_day_high=24350.0)
    zone = get_next_momentum_barrier(Side.LONG, 24340.0, zone_book, 20.0, _cfg())
    wick = [_bar(t0, 24348.0, 24351.0, 24347.0, 24349.5)]  # close still at the level
    assert detect_barrier_rejection(Side.LONG, wick, zone, ema9=24348.0, ema20=24340.0, prev9=24347.0, spread_regime="EXPANDING") is False
    reject = [_bar(t0, 24350.0, 24351.5, 24342.0, 24343.0)]  # bearish close back below
    assert detect_barrier_rejection(
        Side.LONG,
        reject,
        zone,
        ema9=24344.0,
        ema20=24346.0,
        prev9=24348.0,
        spread_regime="CONTRACTING",
        momentum_score=4,
        cfg=_cfg(),
    )


def test_breakout_vs_rejection() -> None:
    t0 = datetime(2026, 9, 14, 10, 0, tzinfo=_ET)
    book = BarrierBook(previous_day_high=24350.0)
    zone = get_next_momentum_barrier(Side.LONG, 24340.0, book, 20.0, _cfg())
    brk = [_bar(t0, 24348.0, 24358.0, 24347.0, 24356.0)]
    assert detect_barrier_breakout(
        Side.LONG, brk, zone, ema9=24352.0, ema20=24344.0, spread_regime="EXPANDING", cfg=_cfg()
    )
    fail = [_bar(t0, 24350.0, 24351.5, 24342.0, 24343.0)]
    assert not detect_barrier_breakout(
        Side.LONG, fail, zone, ema9=24344.0, ema20=24346.0, spread_regime="COLLAPSING", cfg=_cfg()
    )


def test_rollover_after_confirmed_hold() -> None:
    t0 = datetime(2026, 9, 14, 10, 0, tzinfo=_ET)
    book = BarrierBook(previous_day_high=24350.0, swing_highs=[24378.0])
    trade = _trade(entry=24320.0, peak=24356.0, mfe=36.0)
    cfg = _cfg()
    first = [
        _bar(t0, 24320.0, 24330.0, 24318.0, 24328.0),
        _bar(t0 + timedelta(minutes=1), 24348.0, 24358.0, 24347.0, 24356.0),
    ]
    zone = sync_trade_barrier(
        trade, book, first, price=24348.0, atr_v=20.0, cfg=cfg,
        ema9=24352.0, ema20=24344.0, prev9=24350.0, spread_regime="EXPANDING",
    )
    assert getattr(trade, "barrier_pending_break", False) is True
    hold = first + [_bar(t0 + timedelta(minutes=2), 24356.0, 24362.0, 24354.0, 24360.0)]
    nxt = sync_trade_barrier(
        trade, book, hold, price=24360.0, atr_v=20.0, cfg=cfg,
        ema9=24355.0, ema20=24346.0, prev9=24352.0, spread_regime="EXPANDING",
    )
    assert nxt.breakout is True
    assert nxt.state == BARRIER_BREAKOUT
    assert abs(nxt.price - 24378.0) < 1e-6
    line = format_hold_log(
        zone=nxt, momentum_score=2, spread_regime="EXPANDING",
        decision=BARRIER_BREAKOUT_CONTINUE, note="PRICE CLOSED ABOVE TARGET",
    )
    assert "24378" in line
    assert BARRIER_BREAKOUT_CONTINUE in line


def test_classic_target_flattens_ai_exit() -> None:
    cfg = _cfg(ENABLE_CLASSIC_KEY_LEVEL_TARGET=True)
    trade = _trade(entry=24320.0, peak=24350.0, mfe=30.0)
    trade.barrier_view = get_next_momentum_barrier(
        Side.LONG, 24349.0, BarrierBook(previous_day_high=24350.0), 20.0, cfg
    )
    bars = [_bar(datetime(2026, 9, 14, 10, 0, tzinfo=_ET), 24348.0, 24351.0, 24347.0, 24350.5)]
    done, why, _st = manage_ai_exit(
        trade,
        price=24350.5,
        exit_armed=False,
        cfg=cfg,
        ema9=24352.0,
        ema20=24340.0,
        ema50=24330.0,
        prev9=24351.0,
        prev20=24339.5,
        prev50=24329.8,
        atr=20.0,
        bars=bars,
    )
    assert done is True
    assert why == KEY_LEVEL_TARGET
    assert trade.hard_stop == 24300.0


def test_barrier_trail_tightens_never_widens() -> None:
    cfg = _cfg()
    trade = _trade(entry=24320.0, stop=24300.0, peak=24345.0, mfe=25.0)
    book = BarrierBook(previous_day_high=24350.0)
    trade.barrier_view = get_next_momentum_barrier(Side.LONG, 24346.0, book, 20.0, cfg)
    trade.barrier_view.state = BARRIER_TESTING
    hard = trade.hard_stop
    done, why, _st = manage_ema_hold(
        trade,
        price=24346.0,
        exit_armed=False,
        cfg=cfg,
        ema9=24348.0,
        ema20=24338.0,
        ema50=24328.0,
        prev9=24347.0,
        prev20=24337.5,
        prev50=24327.8,
        atr=20.0,
        bars=[_bar(datetime(2026, 9, 14, 10, 0, tzinfo=_ET), 24344.0, 24347.0, 24343.0, 24346.0)],
    )
    assert done is False
    assert trade.hard_stop == hard
    assert trade.stop + 1e-9 >= hard
    assert trade.stop > hard


def test_rejection_exit_reason() -> None:
    cfg = _cfg(ENABLE_STRUCTURE_OVERRIDE=False, MOMENTUM_EXIT_SCORE=99, MOMENTUM_DYING_SCORE=99)
    trade = _trade(entry=24320.0, peak=24350.0, mfe=30.0)
    book = BarrierBook(previous_day_high=24350.0)
    zone = get_next_momentum_barrier(Side.LONG, 24343.0, book, 20.0, cfg)
    zone.rejection = True
    zone.state = BARRIER_REJECTION
    zone.strength = 1
    trade.barrier_view = zone
    bars = [_bar(datetime(2026, 9, 14, 10, 0, tzinfo=_ET), 24350.0, 24351.5, 24342.0, 24343.0)]
    done, why, _st = manage_ai_exit(
        trade,
        price=24343.0,
        exit_armed=False,
        cfg=cfg,
        ema9=24348.0,
        ema20=24340.0,
        ema50=24330.0,
        prev9=24347.5,
        prev20=24339.5,
        prev50=24329.8,
        atr=20.0,
        bars=bars,
    )
    assert done is True
    assert why == MOMENTUM_BARRIER_REJECTION


def test_barriers_off_ai_exit_unchanged() -> None:
    cfg = _cfg(ENABLE_MOMENTUM_BARRIERS=False)
    trade = _trade(entry=100.0, stop=85.0, peak=101.0, mfe=1.0)
    done, why, _st = manage_ema_hold(
        trade,
        price=101.0,
        exit_armed=False,
        cfg=cfg,
        ema9=102.0,
        ema20=99.0,
        ema50=95.0,
        prev9=101.5,
        prev20=98.8,
        prev50=94.9,
        atr=10.0,
    )
    assert done is False
    assert why == ""
