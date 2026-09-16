"""Tip trail arms at total open $15 (scales with contracts)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from mark2.config import Mark2Config
from mark2.engine import Mark2Engine
from mark2.exits import (
    PaperTrade,
    bank_dollars,
    bank_points,
    goal_hunt_bank_dollars,
    goal_hunting,
    initial_target,
    lock_price,
    manage_paper,
    trail_arm_usd,
)
from mark2.types import Side


def test_trail_arm_is_fifteen_total_dollars():
    cfg = Mark2Config()
    assert trail_arm_usd(cfg) == 15.0
    assert goal_hunt_bank_dollars(cfg, session_pnl=0.0) == 15.0


def test_three_contracts_arms_at_two_point_five_pts():
    """3 MNQ · $2/pt → $15 total = 2.5 pts MFE."""
    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 20.0,
        target=entry + 2.5,
        peak=entry,
        trough=entry,
        qty=3,
        goal_hunt=True,
        bank_dollars_locked=15.0,
    )
    assert abs(bank_points(cfg, trade=trade) - 2.5) < 1e-9
    lock = lock_price(entry, Side.LONG, cfg, trade=trade)
    assert abs(lock - (entry + 2.5)) < 1e-9

    # Under $15 — no trail yet
    done, _, _ = manage_paper(
        trade, price=entry + 2.0, atr=4.0, health=90.0, hold_sec=1.0, cfg=cfg
    )
    assert done is False
    assert trade.target_touched is False

    # Hit $15 (2.5 pts × $2 × 3 = $15) — tip trail arms
    done, _, _ = manage_paper(
        trade, price=lock, atr=4.0, health=90.0, hold_sec=2.0, cfg=cfg
    )
    assert done is False
    assert trade.target_touched is True
    # tip 2.5 - 5.5 undercuts bank → floored at lock ($15)
    assert abs(trade.stop - lock) < 1e-9

    tip = entry + 8.0  # $48 MFE on 3ct
    done2, _, _ = manage_paper(
        trade, price=tip, atr=4.0, health=90.0, hold_sec=3.0, cfg=cfg
    )
    assert done2 is False
    assert abs(trade.stop - (tip - 5.5)) < 1e-9
    assert trade.stop > entry

    # Pullback through bank lock — bank the winner
    done3, why3, _ = manage_paper(
        trade, price=lock - 0.25, atr=4.0, health=90.0, hold_sec=4.0, cfg=cfg
    )
    assert done3 is True
    assert why3 in ("TRAIL", "BANK", "BREAKEVEN")


def test_one_contract_arms_at_seven_point_five_pts():
    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=0.0,
        stop=19980.0,
        target=20007.5,
        peak=20000.0,
        trough=20000.0,
        qty=1,
        bank_dollars_locked=15.0,
    )
    assert abs(bank_points(cfg, trade=trade) - 7.5) < 1e-9


def test_initial_target_uses_trail_arm_usd():
    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    tgt = initial_target(
        20000.0,
        Side.LONG,
        4.0,
        cfg,
        goal_hunt=True,
        bank_dollars_locked=15.0,
    )
    # qty defaults to 1 on the temp trade inside initial_target
    assert abs(tgt - 20007.5) < 1e-9


def test_near_goal_uses_ten_dollar_bank():
    cfg = Mark2Config()
    assert goal_hunt_bank_dollars(cfg, session_pnl=325.0) == 10.0
    assert goal_hunt_bank_dollars(cfg, session_pnl=100.0) == 15.0


def test_engine_snapshot_shows_trail_arm_total():
    cfg = Mark2Config()
    cfg.CONTRACTS = 3
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        snap = eng.hud_snapshot()
        # Total $, not × contracts
        assert abs(float(snap["bankDollars"]) - 15.0) < 1e-6
        assert abs(float(snap["bankPoints"]) - 2.5) < 1e-6


def test_clear_session_unlocks_goal():
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng.goal_met = True
        eng.risk.goal_met = True
        eng.clear_session()
        assert eng.goal_met is False


def test_goal_window_clock_expires_hunt():
    cfg = Mark2Config()
    cfg.GOAL_WINDOW_HOURS = 1.0
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        hunt0, _ = eng._goal_bank_for_entry(ts=100.0)
        assert hunt0 is True
        hunt, bank = eng._goal_bank_for_entry(ts=100.0 + 3601.0)
        assert hunt is False
        assert bank == 0.0


def test_goal_hunting_flag():
    cfg = Mark2Config()
    assert goal_hunting(cfg) is True
    assert bank_dollars(3, cfg) == 15.0
