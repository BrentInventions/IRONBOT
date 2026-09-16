"""Impulse Pro is mark2. Leader mode must not change Recon fire/hold/exit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.ai_scout import scout_opportunity
from mark2.config import Mark2Config, _apply_json_file
from mark2.ema_strategy import (
    EmaStack,
    ema_long_decision,
    grow_mode_active,
    manage_ema_hold,
)
from mark2.exits import PaperTrade
from mark2.impulse_lead import leader_enabled
from mark2.types import Side

RECON_EXE_DEFAULTS = ROOT / "packaging" / "willie_pack" / "mark2_defaults.json"

# Already stacked, 9 still rising — first leftover long must fire.
LEFTOVER_RISING_LONG = EmaStack(
    ema9=29321.3747,
    ema20=29314.0239,
    ema50=29315.4338,
    prev9=29315.8434,
    prev20=29310.9211,
    prev50=29314.2883,
)

BEHAVIOR_KEYS = (
    "ENABLE_EMA_STRATEGY",
    "ALLOW_LEGACY_ENTRIES",
    "EMA_ALLOW_LONG",
    "EMA_ALLOW_SHORT",
    "EMA_LONG_SNIPER",
    "EMA_SHORT_SNIPER",
    "ENABLE_AI_SCOUT",
    "AI_SCOUT_LONG",
    "AI_SCOUT_SHORT",
    "AI_SCOUT_OVERRIDE_MISSED",
    "ENABLE_GROW_MODE",
    "ENABLE_RUNNER_TRAIL",
    "INITIAL_STOP_ATR",
    "CATASTROPHIC_STOP_ATR",
    "MFE_GIVEBACK_FRAC",
    "RUNNER_THRESHOLD",
    "CONTRACTS",
)


def _impulse_cfg() -> Mark2Config:
    """Same knobs Impulse Pro loads after syncing to the desktop Recon exe pack."""
    cfg = Mark2Config()
    _apply_json_file(cfg, RECON_EXE_DEFAULTS)
    cfg.ENABLE_GROW_MODE = False
    cfg.ACCOUNT_RISK_PROFILE = "OFF"
    cfg.AI_SCOUT_PAPER_FALLBACK = False
    cfg.IMPULSE_PRO_LEADER = False
    return cfg


def test_recon_exe_pack_is_the_impulse_behavior_source() -> None:
    assert RECON_EXE_DEFAULTS.is_file()
    raw = json.loads(RECON_EXE_DEFAULTS.read_text(encoding="utf-8"))
    cfg = _impulse_cfg()
    for key in BEHAVIOR_KEYS:
        if key == "ENABLE_GROW_MODE":
            assert cfg.ENABLE_GROW_MODE is False
            continue
        assert getattr(cfg, key) == raw[key], key
    assert cfg.ACCOUNT_RISK_PROFILE == "OFF"
    assert cfg.AI_SCOUT_PAPER_FALLBACK is False
    assert raw["EMA_ALLOW_SHORT"] is True
    assert cfg.EMA_ALLOW_SHORT is True
    assert cfg.AI_SCOUT_SHORT is True


def test_impulse_leader_flag_does_not_change_leftover_long_fire(monkeypatch) -> None:
    monkeypatch.setenv("IMPULSE_PRO_LEADER", "1")
    cfg = _impulse_cfg()
    assert leader_enabled(cfg) is True
    fire, reason, why = ema_long_decision(LEFTOVER_RISING_LONG, cfg, atr=16.8, stack_taken=False)
    assert fire is True
    assert reason == ""
    assert why == "EMA_INTERSECTION_LONG"
    again, used, _ = ema_long_decision(LEFTOVER_RISING_LONG, cfg, atr=16.8, stack_taken=True)
    assert again is False
    assert used == "STACK_USED"


def test_impulse_leader_skips_grow_bank_when_off(monkeypatch) -> None:
    monkeypatch.setenv("IMPULSE_PRO_LEADER", "1")
    cfg = _impulse_cfg()
    cfg.POINT_VALUE = 2.0
    cfg.RUNNER_STRUCTURE_EXIT = False
    assert grow_mode_active(cfg, 250.0) is False
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
    manage_ema_hold(trade, price=130.0, exit_armed=False, cfg=cfg, completed_anchor=130.0, account_equity=250.0)
    manage_ema_hold(trade, price=129.0, exit_armed=False, cfg=cfg, completed_anchor=129.4, account_equity=250.0)
    manage_ema_hold(trade, price=128.8, exit_armed=False, cfg=cfg, completed_anchor=129.1, account_equity=250.0)
    done, why, _st = manage_ema_hold(
        trade, price=128.5, exit_armed=False, cfg=cfg, completed_anchor=128.8, account_equity=250.0
    )
    assert done is False
    assert why != "GROW_BANK"


def test_impulse_scout_override_needs_a_real_order(monkeypatch) -> None:
    monkeypatch.setenv("IMPULSE_PRO_LEADER", "1")
    cfg = _impulse_cfg()
    hold = scout_opportunity(
        stack=LEFTOVER_RISING_LONG,
        price=29326.5,
        atr=16.8,
        missed_side=Side.LONG,
        missed_why="WAIT",
        cfg=cfg,
    )
    assert hold.action != "OVERRIDE"
    take = scout_opportunity(
        stack=LEFTOVER_RISING_LONG,
        price=29326.5,
        atr=16.8,
        missed_side=Side.LONG,
        missed_why="EMA_INTERSECTION_LONG",
        cfg=cfg,
    )
    assert take.action == "OVERRIDE"
    assert take.why == "AI_SCOUT_OVERRIDE_LONG"


def test_impulse_risk_stays_off_with_recon_exe_shorts(monkeypatch) -> None:
    monkeypatch.setenv("IMPULSE_PRO_LEADER", "1")
    cfg = _impulse_cfg()
    assert cfg.ACCOUNT_RISK_PROFILE == "OFF"
    assert cfg.ENABLE_GROW_MODE is False
    assert cfg.EMA_ALLOW_SHORT is True
    assert cfg.AI_SCOUT_SHORT is True
    assert cfg.ENABLE_RUNNER_TRAIL is True
    assert abs(float(cfg.MFE_GIVEBACK_FRAC) - 0.30) < 1e-9
