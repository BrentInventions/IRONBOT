"""Early +$15 tip trail with stall/chop squeeze."""

from __future__ import annotations

from mark2.config import Mark2Config
from mark2.exits import (
    PaperTrade,
    early_arm_points,
    manage_paper,
    stall_reversal_score,
)
from mark2.types import MarketSnapshot, Side


def test_early_trail_arms_at_fifteen_dollars_2ct():
    cfg = Mark2Config()
    cfg.ENABLE_DEEP_HOLD = True
    cfg.DEEP_HOLD_ARM_USD = 300.0
    cfg.EARLY_TRAIL_ARM_USD = 15.0
    cfg.POINT_VALUE = 2.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=1.0,
        stop=entry - 180.0,
        target=entry + 75.0,
        peak=entry,
        trough=entry,
        qty=2,
        bank_dollars_locked=300.0,
        deep_hold=True,
    )
    # $15 / ($2*2) = 3.75 pts
    assert abs(early_arm_points(cfg, trade) - 3.75) < 1e-9
    done, _, _ = manage_paper(
        trade, price=entry + 3.75, atr=8.0, health=80.0, hold_sec=2.0, cfg=cfg
    )
    assert done is False
    assert trade.early_trail is True
    assert trade.target_touched is False
    # Floor at early $15 lock
    assert abs(trade.stop - (entry + 3.75)) < 1e-9


def test_stall_squeezes_trail_room():
    cfg = Mark2Config()
    cfg.EARLY_TRAIL_ARM_USD = 15.0
    cfg.STALL_SEC = 4.0
    cfg.STALL_TRAIL_ROOM = 0.75
    cfg.RUNNER_TRAIL_POINTS = 5.5
    cfg.POINT_VALUE = 2.0
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=10.0,
        stop=entry - 20.0,
        target=entry + 7.5,
        peak=entry + 10.0,
        trough=entry,
        qty=1,
        mfe=10.0,
        early_trail=True,
        tip_ts=10.0,
        last_peak=entry + 10.0,
        bank_dollars_locked=15.0,
    )
    snap = MarketSnapshot(
        ts=20.0,  # 10s since tip
        price=entry + 9.5,
        completed_bars=[],
        forming_bar={"open": entry + 9.4, "high": entry + 9.6, "low": entry + 9.3, "close": entry + 9.5},
        atr=8.0,
        velocity=0.0,
    )
    score = stall_reversal_score(
        trade, price=entry + 9.5, atr=8.0, snap=snap, cfg=cfg, hold_sec=10.0
    )
    assert score >= 0.55
    done, why, _ = manage_paper(
        trade,
        price=entry + 9.5,
        atr=8.0,
        health=70.0,
        hold_sec=10.0,
        cfg=cfg,
        snap=snap,
    )
    assert done is False
    assert trade.stall_score >= 0.5
    # Aggressive room ~0.75–2.5, stop much closer than peak-5.5
    assert trade.stop > (entry + 10.0) - 5.5 + 0.5
