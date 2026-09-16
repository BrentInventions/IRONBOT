"""ENTRY / EXIT strategy knobs persist and change live fire / hold."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mark2.config import Mark2Config, load_config, local_app_settings_path, save_config
from mark2.ema_strategy import ema_long_decision, grow_mode_active, manage_ema_hold
from mark2.engine import Mark2Engine
from mark2.exits import PaperTrade
from mark2.strategy_hud import apply_strategy, snapshot
from mark2.tcm8 import ema_92050_live
from mark2.types import Side
from mark2.tests.test_impulse_recon_parity import LEFTOVER_RISING_LONG


def test_strategy_defaults_match_recon_desktop() -> None:
    cfg = Mark2Config()
    st = snapshot(cfg)
    assert st["grow_mode"] is False
    assert st["leftover_long"] is True
    assert st["ema_92050"] is True
    assert st["tcm8"] is False
    assert st["ema_quality_filter"] is True
    assert st["ai_exit_engine"] is False
    assert st["account_risk"] == "OFF"
    assert st["allow_long"] is True
    assert st["allow_short"] is False
    assert abs(st["mfe_keep_pct"] - 70.0) < 1e-6


def test_leftover_toggle_blocks_stacked_long() -> None:
    cfg = Mark2Config()
    fire, reason, why = ema_long_decision(LEFTOVER_RISING_LONG, cfg, atr=16.8, stack_taken=False)
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"
    cfg.EMA_LEFTOVER_LONG = False
    off, reject, _ = ema_long_decision(LEFTOVER_RISING_LONG, cfg, atr=16.8, stack_taken=False)
    assert off is False
    assert reject == "LEFTOVER_OFF"


def test_leftover_and_sep_persist() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        eng = Mark2Engine(Mark2Config(), persist_path=path)
        assert eng.cfg.ENABLE_GROW_MODE is False
        out = eng.set_strategy({"leftover_long": False, "min_sep_atr": 0.45})
        assert out["leftover_long"] is False
        assert abs(out["min_sep_atr"] - 0.45) < 1e-9
        assert out["grow_mode"] is False
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["EMA_LEFTOVER_LONG"] is False
        assert abs(float(raw["EMA_MIN_SEP_ATR"]) - 0.45) < 1e-9
        assert raw["ENABLE_GROW_MODE"] is False
        cfg = load_config(path)
        assert cfg.EMA_LEFTOVER_LONG is False
        assert abs(cfg.EMA_MIN_SEP_ATR - 0.45) < 1e-9
        assert cfg.ENABLE_GROW_MODE is False


def test_grow_off_still_holds_after_strategy_save() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        eng = Mark2Engine(Mark2Config(), persist_path=path)
        eng.set_strategy({"leftover_long": True, "grow_mode": False, "daily_goal": 400})
        cfg = load_config(path)
        assert cfg.ENABLE_GROW_MODE is False
        assert cfg.DAILY_GOAL_DOLLARS == 400.0
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


def test_tiante_settings_folder_is_isolated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("MARK2_PRODUCT", "TIANTE")
    monkeypatch.setenv("MARK2_APP_NAME", "TianteSniper")
    dest = local_app_settings_path()
    assert dest == tmp_path / "local" / "TianteSniper" / "mark2_settings.json"
    save_config(Mark2Config(CONTRACTS=2, ENABLE_GROW_MODE=False), dest)
    recon = tmp_path / "local" / "ReconSniper" / "mark2_settings.json"
    assert dest.is_file()
    assert not recon.exists()
    cfg = load_config(dest)
    assert cfg.PRODUCT_NAME == "TIANTE SNIPER"
    assert cfg.BRIDGE_PORT == 5566
    assert cfg.BRIDGE_NAME == "TianteSniperBridge"
    assert cfg.ENABLE_GROW_MODE is False


def test_apply_strategy_mfe_keep_and_risk() -> None:
    cfg = Mark2Config()
    apply_strategy(cfg, {"mfe_keep_pct": 80, "account_risk": "SMALL_250", "scout": False})
    assert abs(cfg.MFE_GIVEBACK_FRAC - 0.20) < 1e-6
    assert cfg.ACCOUNT_RISK_PROFILE == "SMALL_250"
    assert cfg.ENABLE_AI_SCOUT is False
    apply_strategy(cfg, {"account_risk": "OFF"})
    assert cfg.ACCOUNT_RISK_PROFILE == "OFF"


def test_apply_413_breakout_toggle() -> None:
    cfg = Mark2Config()
    st = snapshot(cfg)
    assert st["breakout_413"] is False
    assert st["breakout_413_mode"] == "BREAKOUT"
    apply_strategy(
        cfg,
        {
            "breakout_413": True,
            "breakout_413_mode": "PULLBACK",
            "breakout_413_max_stop": 25,
        },
    )
    assert cfg.ENABLE_413_BREAKOUT is True
    assert cfg.BREAKOUT_413_MODE == "PULLBACK"
    assert abs(cfg.BREAKOUT_413_MAX_STOP_PTS - 25.0) < 1e-9
    apply_strategy(cfg, {"breakout_413_mode": "BREAKOUT", "breakout_413": False})
    assert cfg.BREAKOUT_413_MODE == "BREAKOUT"
    assert cfg.ENABLE_413_BREAKOUT is False


def test_apply_momentum_barriers_toggle() -> None:
    cfg = Mark2Config()
    st = snapshot(cfg)
    assert st["momentum_barriers"] is False
    apply_strategy(cfg, {"momentum_barriers": True})
    assert cfg.ENABLE_MOMENTUM_BARRIERS is True
    assert cfg.ENABLE_BARRIER_STRATEGY_ONLY is True
    assert cfg.ENABLE_BARRIER_ENTRY_FILTER is True
    assert cfg.ENABLE_BARRIER_REJECTION_EXIT is True
    assert cfg.ENABLE_CLASSIC_KEY_LEVEL_TARGET is False
    assert cfg.ENABLE_HARD_BARRIER_TARGET is False
    assert cfg.ENABLE_AI_EXIT_ENGINE is True
    assert cfg.ENABLE_MFE_RUNNER is True
    apply_strategy(cfg, {"momentum_barriers": False})
    assert cfg.ENABLE_MOMENTUM_BARRIERS is False
    assert cfg.ENABLE_BARRIER_STRATEGY_ONLY is False
    assert cfg.ENABLE_AI_EXIT_ENGINE is True


def test_apply_8tcm_toggle_independent() -> None:
    cfg = Mark2Config()
    st = snapshot(cfg)
    assert st["tcm8"] is False
    cfg.EMA_LONG_SNIPER = False
    cfg.ENABLE_AI_SCOUT = False
    apply_strategy(cfg, {"tcm8": True})
    assert cfg.ENABLE_8TCM is True
    assert cfg.ENABLE_8TCM_LONGS is True
    assert cfg.ENABLE_8TCM_SHORTS is False
    assert cfg.ENABLE_8TCM_CLASSIC_TARGET is True
    assert cfg.ENABLE_8TCM_AI_EXIT is False
    assert cfg.ENABLE_8TCM_RUNNER is True
    assert cfg.EMA_LONG_SNIPER is False
    assert cfg.ENABLE_AI_SCOUT is False
    assert cfg.ENABLE_413_BREAKOUT is False
    assert cfg.ENABLE_MOMENTUM_BARRIERS is False
    assert cfg.ALLOW_LEGACY_ENTRIES is False
    apply_strategy(cfg, {"tcm8": False})
    assert cfg.ENABLE_8TCM is False
    assert cfg.EMA_LONG_SNIPER is False
    assert cfg.ENABLE_AI_SCOUT is False


def test_apply_92050_pack_independent() -> None:
    cfg = Mark2Config()
    apply_strategy(cfg, {"tcm8": True})
    assert cfg.ENABLE_8TCM is True
    apply_strategy(cfg, {"ema_92050": False})
    assert cfg.ENABLE_8TCM is True
    assert cfg.EMA_LONG_SNIPER is False
    assert cfg.EMA_SHORT_SNIPER is False
    assert cfg.EMA_LEFTOVER_LONG is False
    assert ema_92050_live(cfg) is False
    assert snapshot(cfg)["ema_92050"] is False
    apply_strategy(cfg, {"ema_92050": True})
    assert cfg.ENABLE_8TCM is True
    assert cfg.EMA_LONG_SNIPER is True
    assert cfg.EMA_SHORT_SNIPER is True
    assert cfg.EMA_ALLOW_LONG is True
    assert cfg.EMA_ALLOW_SHORT is True
    assert cfg.EMA_LEFTOVER_LONG is False
    assert cfg.ENABLE_AI_SCOUT is False
    assert cfg.ENABLE_413_BREAKOUT is False
    assert cfg.ENABLE_AI_EXIT_ENGINE is True
    assert ema_92050_live(cfg) is True
    assert snapshot(cfg)["ema_92050"] is True
    apply_strategy(cfg, {"tcm8": False})
    assert cfg.ENABLE_8TCM is False
    assert cfg.EMA_LONG_SNIPER is True
