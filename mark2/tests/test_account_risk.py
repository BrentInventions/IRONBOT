"""Account-level SMALL_250 risk — independent of Recon entry signals."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.account_risk import AccountRiskManager, planned_risk_usd
from mark2.config import Mark2Config
from mark2.ema_strategy import ema_atr_stop, more_protective_stop
from mark2.execution import ExecutionEngine, Intent
from mark2.risk import RiskGate
from mark2.types import Side


def _cfg() -> Mark2Config:
    cfg = Mark2Config()
    cfg.ACCOUNT_RISK_PROFILE = "SMALL_250"
    cfg.ACCOUNT_MAX_RISK_PER_TRADE_USD = 50.0
    cfg.ACCOUNT_MAX_DAILY_LOSS_USD = 75.0
    cfg.ACCOUNT_MAX_CONSECUTIVE_LOSSES = 3
    cfg.ACCOUNT_EQUITY_FLOOR_USD = 100.0
    cfg.ACCOUNT_MAX_CONTRACTS = 1
    cfg.POINT_VALUE = 2.0
    cfg.CATASTROPHIC_STOP_ATR = 1.50
    return cfg


def test_planned_risk_mnq_math() -> None:
    assert planned_risk_usd(20000.0, 19990.0, 1, 2.0) == 20.0  # 10 pts
    assert planned_risk_usd(20000.0, 19950.0, 1, 2.0) == 100.0  # 50 pts


def test_1_normal_losing_trade_stays_inside_budget() -> None:
    mgr = AccountRiskManager(_cfg())
    dec = mgr.approve_entry(entry=20000.0, stop=19990.0, qty=1)  # $20
    assert dec.ok is True
    assert dec.risk_usd == 20.0
    fill_pnl = -20.0  # stop hit, no extra slip
    mgr.note_exit(fill_pnl)
    assert mgr.state == "ARMED"
    assert abs(fill_pnl) <= mgr.max_risk_usd()


def test_2_strong_runner_is_not_killed() -> None:
    mgr = AccountRiskManager(_cfg())
    mgr.approve_entry(entry=20000.0, stop=19990.0, qty=1)
    dec = mgr.evaluate_open(daily_pnl=180.0, in_trade=True, connected=True)
    assert dec.flatten is False
    assert dec.state == "ARMED"


def test_3_runner_floor_never_loosens() -> None:
    protect = more_protective_stop(Side.LONG, 19980.0, 20010.0)
    assert protect == 20010.0
    loosened = more_protective_stop(Side.LONG, protect, 19990.0)
    assert loosened == 20010.0


def test_4_extreme_morning_volatility_rejects() -> None:
    cfg = _cfg()
    mgr = AccountRiskManager(cfg)
    entry = 20000.0
    atr = 80.0
    stop = ema_atr_stop(entry, Side.LONG, atr, cfg)
    risk = planned_risk_usd(entry, stop, 1, 2.0)
    assert risk > 50.0  # 1.5 * 80 * $2 = $240
    dec = mgr.approve_entry(entry=entry, stop=stop, qty=1)
    assert dec.ok is False
    assert dec.reason == "ACCOUNT_TOO_SMALL_FOR_SETUP"
    assert dec.state == "TRADE_BLOCKED"
    assert mgr.state == "ARMED"


def test_5_consecutive_losses_lock_session() -> None:
    mgr = AccountRiskManager(_cfg())
    mgr.note_exit(-20.0)
    mgr.note_exit(-20.0)
    assert mgr.state == "ARMED"
    mgr.note_exit(-20.0)
    assert mgr.state == "DAILY_LOCKOUT"
    dec = mgr.approve_entry(entry=20000.0, stop=19990.0, qty=1)
    assert dec.ok is False
    assert dec.reason in ("CONSECUTIVE_LOSSES", "DAILY_LOCKOUT") or "consecutive" in (mgr.lock_reason or "").lower()


def test_6_daily_loss_threshold_blocks_entries() -> None:
    mgr = AccountRiskManager(_cfg())
    dec = mgr.evaluate_open(daily_pnl=-80.0, in_trade=True, connected=True)
    assert dec.flatten is True
    assert dec.state == "DAILY_LOCKOUT"
    blocked = mgr.approve_entry(entry=20000.0, stop=19990.0, qty=1, daily_pnl=-80.0)
    assert blocked.ok is False


def test_7_duplicate_signal_one_position() -> None:
    mgr = AccountRiskManager(_cfg())
    first = mgr.approve_entry(entry=20000.0, stop=19990.0, qty=1, in_trade=False)
    assert first.ok is True
    second = mgr.approve_entry(entry=20000.0, stop=19990.0, qty=1, in_trade=True)
    assert second.ok is False
    assert second.reason == "DUPLICATE"


def test_8_connection_failure_blocks_new_entries_keeps_stop_design() -> None:
    mgr = AccountRiskManager(_cfg())
    dec = mgr.approve_entry(entry=20000.0, stop=19990.0, qty=1, connected=False)
    assert dec.ok is False
    assert dec.state == "CONNECTION_FAILSAFE"
    open_watch = mgr.evaluate_open(daily_pnl=12.0, in_trade=True, connected=False)
    assert open_watch.flatten is False  # Python cannot flatten if the wire is dead
    intent = Intent(side=Side.LONG, price=20000.0, stop=19990.0, quantity=1, reason="t", ts=1.0)
    assert intent.attach_stop is True


def test_9_fast_market_slippage_then_account_responds() -> None:
    mgr = AccountRiskManager(_cfg())
    mgr.approve_entry(entry=20000.0, stop=19975.0, qty=1)  # planned $50
    slipped_pnl = -90.0  # filled through the stop
    mgr.note_exit(slipped_pnl)
    dec = mgr.evaluate_open(daily_pnl=slipped_pnl, in_trade=False, connected=True)
    assert dec.state == "DAILY_LOCKOUT"
    assert dec.ok is False or mgr.state == "DAILY_LOCKOUT"


def test_10_old_vs_new_250_blowup() -> None:
    cfg = _cfg()
    entry = 20000.0
    atr = 83.0
    stop = ema_atr_stop(entry, Side.LONG, atr, cfg)
    old_risk = planned_risk_usd(entry, stop, 1, 2.0)
    # Old architecture: MAX_LOSS_DOLLARS=50000 allows this ~$249 planned stop.
    assert old_risk > 240.0
    assert old_risk < float(cfg.MAX_LOSS_DOLLARS)
    reversal_fill = stop - 5.0
    reversal_pnl = -(entry - reversal_fill) * 2.0
    assert reversal_pnl <= -250.0

    mgr = AccountRiskManager(cfg)
    dec = mgr.approve_entry(entry=entry, stop=stop, qty=1)
    assert dec.ok is False
    assert dec.reason == "ACCOUNT_TOO_SMALL_FOR_SETUP"
    assert dec.risk_usd > dec.allowed_usd


def test_qty_cap_small_250() -> None:
    mgr = AccountRiskManager(_cfg())
    dec = mgr.approve_entry(entry=20000.0, stop=19990.0, qty=3)
    assert dec.ok is True
    assert dec.qty == 1


def test_equity_kill() -> None:
    mgr = AccountRiskManager(_cfg())
    dec = mgr.evaluate_open(daily_pnl=0.0, equity=90.0, equity_synced=True, in_trade=True)
    assert dec.flatten is True
    assert dec.state == "EQUITY_KILL"


def test_execution_rejects_before_submit() -> None:
    cfg = _cfg()
    risk = RiskGate(cfg)
    ex = ExecutionEngine(cfg, risk)
    ex.acct_risk = AccountRiskManager(cfg)
    intent = Intent(
        side=Side.LONG,
        price=20000.0,
        stop=19880.0,  # 120 pts = $240
        quantity=1,
        reason="t",
        ts=1.0,
    )
    assert ex.enter(intent) == "ACCOUNT_TOO_SMALL_FOR_SETUP"
    assert ex.orders_submitted == 0


def test_profile_off_does_not_block() -> None:
    cfg = _cfg()
    cfg.ACCOUNT_RISK_PROFILE = "OFF"
    mgr = AccountRiskManager(cfg)
    dec = mgr.approve_entry(entry=20000.0, stop=19800.0, qty=2)
    assert dec.ok is True
    assert dec.state == "OFF"
