"""MNQ long quality filter — post-trigger only. Exits and shorts stay untouched."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.ema_strategy import (
    EmaStack,
    ema_long_decision,
    evaluate_ema_long_quality,
    leftover_stacked_long,
    long_sniper_reason,
    manage_ema_hold,
    short_sniper_reason,
)
from mark2.exits import PaperTrade
from mark2.strategy_hud import apply_strategy, snapshot
from mark2.types import Side
from mark2.tests.test_ema_fire_checks import JUL08_0325_SNIPER, JUL08_0326_LEFTOVER
from mark2.tests.test_impulse_recon_parity import LEFTOVER_RISING_LONG

KNOT_LEFTOVER = EmaStack(
    ema9=100.80,
    ema20=100.35,
    ema50=100.50,
    prev9=100.55,
    prev20=100.30,
    prev50=100.48,
)

EXPANDING_BULL = EmaStack(
    ema9=120.0,
    ema20=110.0,
    ema50=100.0,
    prev9=116.0,
    prev20=108.5,
    prev50=99.6,
)


def _cfg(*, quality: bool = True) -> Mark2Config:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.EMA_ALLOW_LONG = True
    cfg.EMA_LONG_SNIPER = True
    cfg.EMA_LEFTOVER_LONG = True
    cfg.ENABLE_EMA_QUALITY_FILTER = quality
    cfg.ACCOUNT_RISK_PROFILE = "OFF"
    return cfg


def test_compressed_knot_rejects() -> None:
    cfg = _cfg(quality=True)
    assert leftover_stacked_long(KNOT_LEFTOVER) is True
    fire, reason, why = ema_long_decision(KNOT_LEFTOVER, cfg, atr=12.0, stack_taken=False)
    assert fire is False
    assert reason == "REJECT_EMA_COMPRESSION"
    assert why == ""
    report = evaluate_ema_long_quality(KNOT_LEFTOVER, cfg, 12.0)
    assert report.knot is True
    assert report.accept is False


def test_expanding_bullish_accepts() -> None:
    cfg = _cfg(quality=True)
    fire, reason, why = ema_long_decision(EXPANDING_BULL, cfg, atr=12.0, stack_taken=False)
    assert fire is True
    assert reason == ""
    assert why == "EMA_INTERSECTION_LONG"
    assert long_sniper_reason(EXPANDING_BULL, cfg, atr=12.0) == ""


def test_toggle_off_restores_old_accept() -> None:
    cfg = _cfg(quality=False)
    fire, reason, why = ema_long_decision(KNOT_LEFTOVER, cfg, atr=12.0, stack_taken=False)
    assert fire is True
    assert reason == ""
    assert why == "EMA_INTERSECTION_LONG"
    assert long_sniper_reason(KNOT_LEFTOVER, cfg, atr=12.0) == ""


def test_leftover_long_still_works_when_filter_off() -> None:
    cfg = _cfg(quality=False)
    fire, reason, why = ema_long_decision(LEFTOVER_RISING_LONG, cfg, atr=16.8, stack_taken=False)
    assert leftover_stacked_long(LEFTOVER_RISING_LONG) is True
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"
    assert reason == ""


def test_leftover_blocked_in_knot_when_filter_on() -> None:
    cfg = _cfg(quality=True)
    assert leftover_stacked_long(KNOT_LEFTOVER) is True
    fire, reason, _why = ema_long_decision(KNOT_LEFTOVER, cfg, atr=12.0, stack_taken=False)
    assert fire is False
    assert reason == "REJECT_EMA_COMPRESSION"
    fire_off, _, why_off = ema_long_decision(JUL08_0326_LEFTOVER, cfg, atr=16.8, stack_taken=False)
    assert leftover_stacked_long(JUL08_0326_LEFTOVER) is True
    assert fire_off is True
    assert why_off == "EMA_INTERSECTION_LONG"


def test_july8_sniper_still_clears_quality() -> None:
    cfg = _cfg(quality=True)
    fire, reason, why = ema_long_decision(JUL08_0325_SNIPER, cfg, atr=16.8, stack_taken=False)
    assert fire is True
    assert reason == ""
    assert why == "EMA_INTERSECTION_LONG"


def test_price_below_structure_rejects() -> None:
    cfg = _cfg(quality=True)
    bars = [{"open": 99.0, "high": 101.0, "low": 98.0, "close": 99.0, "volume": 10}]
    fire, reason, _why = ema_long_decision(
        EXPANDING_BULL, cfg, atr=12.0, stack_taken=False, bars=bars
    )
    assert fire is False
    assert reason == "REJECT_PRICE_BELOW_STRUCTURE"


def test_short_leftover_stays_stack_stale() -> None:
    cfg = _cfg(quality=True)
    leftover = EmaStack(
        ema9=29411.8444,
        ema20=29422.6685,
        ema50=29441.3766,
        prev9=29412.7256,
        prev20=29425.3873,
        prev50=29443.9796,
    )
    assert short_sniper_reason(leftover, cfg, atr=11.82) == "STACK_STALE"


def test_quality_filter_does_not_change_hold_exit() -> None:
    cfg = _cfg(quality=True)
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    done, why, _st = manage_ema_hold(
        trade, price=101.0, exit_armed=False, cfg=cfg, ema9=102.0, ema20=99.0, ema50=95.0, atr=10.0
    )
    assert done is False
    assert why == ""
    assert trade.ema_trade_state == "PROBATION"


def test_hud_toggle_wires_enable_flag() -> None:
    cfg = _cfg(quality=True)
    assert snapshot(cfg)["ema_quality_filter"] is True
    out = apply_strategy(cfg, {"ema_quality_filter": False})
    assert out["ema_quality_filter"] is False
    assert cfg.ENABLE_EMA_QUALITY_FILTER is False
    fire, _reason, why = ema_long_decision(KNOT_LEFTOVER, cfg, atr=12.0, stack_taken=False)
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"
    apply_strategy(cfg, {"ema_quality_filter": True})
    blocked, reason, _ = ema_long_decision(KNOT_LEFTOVER, cfg, atr=12.0, stack_taken=False)
    assert blocked is False
    assert reason == "REJECT_EMA_COMPRESSION"
