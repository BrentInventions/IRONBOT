"""Deep hold: no stop until $300 open profit, or market flip → tip trail."""

from __future__ import annotations

from mark2.config import Mark2Config
from mark2.exits import PaperTrade, bank_points, manage_paper, market_flipped_against
from mark2.types import MarketSnapshot, Side


def test_deep_hold_ignores_stop_until_arm():
    cfg = Mark2Config()
    cfg.ENABLE_DEEP_HOLD = True
    cfg.DEEP_HOLD_ARM_USD = 300.0
    cfg.POINT_VALUE = 2.0
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=1.0,
        stop=entry - 180.0,
        target=entry,
        peak=entry,
        trough=entry,
        qty=2,
        bank_dollars_locked=300.0,
        deep_hold=True,
        hard_stop=entry - 180.0,
    )
    # $300 / ($2 * 2) = 75 pts
    assert abs(bank_points(cfg, trade=trade) - 75.0) < 1e-9
    # Pull back toward stop — must NOT exit in deep hold
    done, why, _ = manage_paper(
        trade, price=entry - 20.0, atr=10.0, health=80.0, hold_sec=2.0, cfg=cfg
    )
    assert done is False
    assert why == ""
    assert trade.target_touched is False


def test_deep_hold_arms_at_three_hundred():
    cfg = Mark2Config()
    cfg.ENABLE_DEEP_HOLD = True
    cfg.DEEP_HOLD_ARM_USD = 300.0
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
    arm = entry + 75.0
    done, _, _ = manage_paper(
        trade, price=arm, atr=10.0, health=90.0, hold_sec=10.0, cfg=cfg
    )
    assert done is False
    assert trade.target_touched is True
    assert abs(trade.stop - arm) < 1e-9


def test_market_flip_arms_trail_before_bank():
    cfg = Mark2Config()
    cfg.ENABLE_DEEP_HOLD = True
    cfg.RSI_OB_LEVEL = 75.0
    cfg.DEEP_HOLD_FLIP_TRAIL = 5.5
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=1.0,
        stop=entry - 180.0,
        target=entry + 75.0,
        peak=entry + 40.0,
        trough=entry,
        qty=2,
        mfe=40.0,
        bank_dollars_locked=300.0,
        deep_hold=True,
    )
    # Fake overbought snap via velocity slam (no bars needed)
    snap = MarketSnapshot(
        ts=2.0,
        price=entry + 40.0,
        completed_bars=[],
        forming_bar=None,
        velocity=-1.0,
    )
    assert market_flipped_against(trade, snap=snap, cfg=cfg)
    done, why, _ = manage_paper(
        trade,
        price=entry + 40.0,
        atr=10.0,
        health=80.0,
        hold_sec=5.0,
        cfg=cfg,
        snap=snap,
    )
    assert done is False
    assert trade.flip_armed is True
    assert trade.stop >= entry
