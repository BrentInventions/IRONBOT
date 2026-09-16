"""Manual HUD trades are operator-owned — bot must not trail-exit or auto-stack."""

from __future__ import annotations

from mark2.config import Mark2Config
from mark2.exits import PaperTrade, manage_manual_hold, manage_paper
from mark2.types import Side


def test_manual_hold_ignores_tip_trail_exit():
    cfg = Mark2Config()
    cfg.ENABLE_RECON_TIP_TRAIL = True if hasattr(cfg, "ENABLE_RECON_TIP_TRAIL") else False
    cfg.TRAIL_ARM_USD = 15.0
    entry = 20000.0
    hard = entry - 20.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=1.0,
        stop=hard,
        target=entry + 7.5,
        peak=entry,
        trough=entry,
        qty=1,
        manual_entry=True,
        hard_stop=hard,
        bank_dollars_locked=15.0,
    )
    # Big green push — auto tip trail would move stop up; manual must stay on hard.
    done, why, _ = manage_manual_hold(trade, price=entry + 12.0, cfg=cfg)
    assert done is False
    assert trade.stop == hard
    assert trade.hard_stop == hard
    # Pullback that would hit a tip trail must NOT exit the manual.
    done2, why2, _ = manage_manual_hold(trade, price=entry + 1.0, cfg=cfg)
    assert done2 is False
    # Only the hard stop exits.
    done3, why3, _ = manage_manual_hold(trade, price=hard, cfg=cfg)
    assert done3 is True
    assert why3 in ("STOP", "BREAKEVEN")


def test_auto_manage_still_trails_non_manual():
    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=1.0,
        stop=entry - 20.0,
        target=entry + 7.5,
        peak=entry,
        trough=entry,
        qty=1,
        manual_entry=False,
        bank_dollars_locked=15.0,
        hard_stop=entry - 20.0,
    )
    manage_paper(trade, price=entry + 7.5, atr=4.0, health=80.0, hold_sec=1.0, cfg=cfg)
    assert trade.target_touched is True
    manage_paper(trade, price=entry + 12.0, atr=4.0, health=80.0, hold_sec=2.0, cfg=cfg)
    assert trade.stop > entry - 20.0
