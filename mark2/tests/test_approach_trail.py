"""Green floor + approach trail exit behavior."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.exits import PaperTrade, broker_stop_for_nt, lock_price, manage_paper, nt_stop_for_broker
from mark2.types import Side


def test_approach_trail_climbs_before_target():
    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0  # 7.5 pts @ 1ct
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 20.0,
        target=entry + 7.5,
        peak=entry,
        trough=entry,
        bank_dollars_locked=15.0,
    )
    # Before bank: hard stop stays put (no early BE trail)
    manage_paper(trade, price=entry + 5.0, atr=4.0, health=80.0, hold_sec=1.0, cfg=cfg)
    assert trade.target_touched is False
    assert abs(trade.stop - (entry - 20.0)) < 1e-9
    # Hit $15 arm → tip trail live, floored at bank lock
    manage_paper(trade, price=entry + 7.5, atr=4.0, health=80.0, hold_sec=2.0, cfg=cfg)
    assert trade.target_touched is True
    lock = entry + 7.5
    # tip 7.5 - 5.5 = entry+2.0, but floor is bank lock → stop = lock
    assert abs(trade.stop - lock) < 1e-9


def test_earned_breakeven_only_after_five_point_five():
    cfg = Mark2Config()
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 20.0,
        target=entry + 12.5,
        peak=entry,
        trough=entry,
    )
    manage_paper(trade, price=entry + 5.5, atr=4.0, health=80.0, hold_sec=1.0, cfg=cfg)
    assert trade.stop == entry - 20.0  # no trail until $15 bank


def test_five_point_five_push_does_not_die_at_entry():
    cfg = Mark2Config()
    entry = 30079.5
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 25.0,
        target=entry + 12.5,
        peak=entry,
        trough=entry,
    )
    manage_paper(trade, price=entry + 5.5, atr=12.0, health=80.0, hold_sec=4.0, cfg=cfg)
    assert trade.stop == entry - 25.0
    done, why, _ = manage_paper(
        trade, price=entry, atr=12.0, health=45.0, hold_sec=5.0, cfg=cfg
    )
    assert done is False
    assert why == ""


def test_approach_trail_starts_at_five_and_a_half():
    cfg = Mark2Config()
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 20.0,
        target=entry + 12.5,
        peak=entry,
        trough=entry,
    )
    manage_paper(trade, price=entry + 6.0, atr=4.0, health=80.0, hold_sec=1.0, cfg=cfg)
    # Pre-bank: no approach trail — hard stop only
    assert trade.stop == entry - 20.0


def test_flicker_green_keeps_initial_stop():
    cfg = Mark2Config()
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 20.0,
        target=entry + 12.5,
        peak=entry,
        trough=entry,
    )
    manage_paper(trade, price=entry + 0.75, atr=4.0, health=80.0, hold_sec=0.5, cfg=cfg)
    assert trade.was_green is True
    assert trade.stop == entry - 20.0


def test_trail_arms_after_six_points():
    cfg = Mark2Config()
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 20.0,
        target=entry + 12.5,
        peak=entry,
        trough=entry,
    )
    manage_paper(trade, price=entry + 5.75, atr=4.0, health=80.0, hold_sec=0.5, cfg=cfg)
    assert trade.stop == entry - 20.0
    manage_paper(trade, price=entry + 6.0, atr=4.0, health=80.0, hold_sec=0.6, cfg=cfg)
    assert trade.was_green is True
    assert trade.stop == entry - 20.0  # still pre-bank


def test_switches_to_runner_trail_after_target():
    cfg = Mark2Config()
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 20.0,
        target=entry + 12.5,
        peak=entry,
        trough=entry,
        bank_dollars_locked=15.0,
    )
    manage_paper(trade, price=entry + 18.0, atr=4.0, health=80.0, hold_sec=5.0, cfg=cfg)
    assert trade.target_touched is True
    # peak 20018 - 5.5 = 20012.5, bank lock = entry+7.5 → stop = 20012.5
    assert abs(trade.stop - (entry + 12.5)) < 1e-9
    assert trade.stop >= entry + 7.5


def test_green_does_not_flatten_at_entry():
    from mark2.types import MarketSnapshot, ScoreBundle

    cfg = Mark2Config()
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 20.0,
        target=entry + 12.5,
        peak=entry,
        trough=entry,
        chop_scalp=False,
    )
    snap = MarketSnapshot(
        ts=1.0,
        price=20000.0,
        completed_bars=[],
        forming_bar={"open": 20000.0, "high": 20001.0, "low": 19999.0},
        atr=4.0,
        velocity=0.1,
        acceleration=-0.12,
        relative_volume=1.0,
        impulse_score=60.0,
        trend_bias="BULLISH",
        trend_regime="HIGH_VOL",
        structure_state="HH_HL",
        longs_allowed=True,
        shorts_allowed=False,
        vwap_distance_atr=0.0,
        volume_acceleration=0.0,
        swing_high=0.0,
        swing_low=0.0,
    )
    scores = ScoreBundle(long_confidence=60.0, short_confidence=40.0)
    manage_paper(
        trade,
        price=entry + 0.75,
        atr=4.0,
        health=80.0,
        hold_sec=1.0,
        cfg=cfg,
        scores=scores,
        snap=snap,
        event_alive=True,
    )
    assert trade.was_green is True
    assert trade.stop == entry - 20.0
    done, why, _ = manage_paper(
        trade,
        price=entry,
        atr=4.0,
        health=50.0,
        hold_sec=2.0,
        cfg=cfg,
        scores=scores,
        snap=snap,
        event_alive=True,
    )
    assert done is False
    assert why == ""
    manage_paper(
        trade,
        price=entry + 6.0,
        atr=4.0,
        health=80.0,
        hold_sec=2.5,
        cfg=cfg,
        scores=scores,
        snap=snap,
        event_alive=True,
    )
    # Pre-bank: still on hard stop — no BE trail
    assert trade.stop == entry - 20.0
    done, why, _ = manage_paper(
        trade,
        price=entry,
        atr=4.0,
        health=50.0,
        hold_sec=3.0,
        cfg=cfg,
        scores=scores,
        snap=snap,
        event_alive=True,
    )
    assert done is False
    assert why == ""


def test_abort_blocked_until_green():
    from mark2.types import MarketSnapshot, ScoreBundle

    cfg = Mark2Config()
    cfg.ABORT_REQUIRES_GREEN = True
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=0.0,
        stop=19980.0,
        target=20012.5,
        peak=20000.0,
        trough=20000.0,
    )
    snap = MarketSnapshot(
        ts=1.0,
        price=19999.5,
        completed_bars=[],
        forming_bar={"open": 20000.0, "high": 20001.0, "low": 19999.0},
        atr=4.0,
        velocity=-0.2,
        acceleration=-0.2,
        relative_volume=1.0,
        impulse_score=60.0,
        trend_bias="BULLISH",
        trend_regime="HIGH_VOL",
        structure_state="HH_HL",
        longs_allowed=True,
        shorts_allowed=False,
        vwap_distance_atr=0.0,
        volume_acceleration=0.0,
        swing_high=0.0,
        swing_low=0.0,
    )
    scores = ScoreBundle(long_confidence=60.0, short_confidence=40.0, long_conf_velocity=-0.25)
    done, why, _ = manage_paper(
        trade,
        price=19999.5,
        atr=4.0,
        health=55.0,
        hold_sec=0.5,
        cfg=cfg,
        scores=scores,
        snap=snap,
        event_alive=False,
    )
    assert done is False
    assert trade.was_green is False


def test_chop_uses_approach_trail_before_target():
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
    manage_paper(trade, price=entry + 6.0, atr=12.0, health=80.0, hold_sec=2.0, cfg=cfg)
    assert trade.stop == entry - 10.0


def test_short_trail_exits_when_bounce_crosses_stop():
    cfg = Mark2Config()
    entry = 30100.0
    trade = PaperTrade(
        side=Side.SHORT,
        entry=entry,
        entry_ts=0.0,
        stop=entry + 20.0,
        target=entry - 12.5,
        peak=entry,
        trough=entry,
    )
    manage_paper(trade, price=entry - 16.0, atr=4.0, health=80.0, hold_sec=1.0, cfg=cfg)
    manage_paper(trade, price=entry - 20.0, atr=4.0, health=80.0, hold_sec=2.0, cfg=cfg)
    done, why, _ = manage_paper(
        trade, price=entry - 11.0, atr=4.0, health=80.0, hold_sec=3.0, cfg=cfg
    )
    assert done is True
    assert why in ("STOP", "TRAIL")


def test_nt_stop_for_broker_short():
    stop, flat = nt_stop_for_broker(Side.SHORT, 30090.25, 30095.0, 0.25)
    assert stop is None
    assert flat is True

    stop, flat = nt_stop_for_broker(Side.SHORT, 30090.25, 30089.0, 0.25)
    assert stop == 30090.25
    assert flat is False

    stop, flat = nt_stop_for_broker(Side.SHORT, 30085.0, 30089.0, 0.25)
    assert stop is None
    assert flat is True


def test_broker_stop_for_nt_long_bank_does_not_send_floor():
    """After $15 arm, NT gets tip-trail (not the green print as a fake TP)."""
    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    entry = 20000.0
    tip = entry + 10.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry + 4.5,
        target=entry + 7.5,
        peak=tip,
        trough=entry,
        target_touched=True,
        mfe=10.0,
        bank_dollars_locked=15.0,
    )
    stop, flat = broker_stop_for_nt(trade, trade.stop, tip, entry + 7.5, cfg)
    assert flat is False
    assert stop is not None
    assert abs(float(stop) - (entry + 7.5)) < 1e-9
    assert float(stop) > entry


def test_broker_stop_for_nt_short_bank_never_flattens():
    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    entry = 29586.75
    tip = entry - 10.0
    trade = PaperTrade(
        side=Side.SHORT,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 4.5,
        target=entry - 7.5,
        peak=tip,
        trough=entry,
        target_touched=True,
        bank_dollars_locked=15.0,
    )
    stop, flat = broker_stop_for_nt(trade, trade.stop, tip, entry - 7.5, cfg)
    assert flat is False
    assert stop is not None
    assert abs(float(stop) - (entry - 7.5)) < 1e-9


def test_broker_stop_for_nt_short_bank_penetration_still_managed_in_engine():
    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    entry = 29586.75
    tip = entry - 12.0
    trade = PaperTrade(
        side=Side.SHORT,
        entry=entry,
        entry_ts=0.0,
        stop=tip + 5.5,
        target=entry - 7.5,
        peak=tip,
        trough=entry,
        target_touched=True,
        bank_dollars_locked=15.0,
    )
    stop, flat = broker_stop_for_nt(trade, trade.stop, tip + 1.0, entry - 7.5, cfg)
    assert flat is False
    assert stop is not None
    assert abs(float(stop) - (entry - 7.5)) < 1e-9
