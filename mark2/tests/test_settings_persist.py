"""Persist ARM / user settings across restarts."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config, load_config, local_app_settings_path, save_config
from mark2.engine import Mark2Engine


def test_set_enabled_persists_to_settings_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        eng = Mark2Engine(Mark2Config(), persist_path=path)
        eng.set_enabled(True)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["MARK2_ENABLED"] is True
        eng.set_enabled(False)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["MARK2_ENABLED"] is False


def test_load_config_merges_settings_over_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        save_config(Mark2Config(MARK2_ENABLED=False, CONTRACTS=3), path)
        cfg = load_config(path)
        assert cfg.MARK2_ENABLED is False
        assert cfg.CONTRACTS == 3


def test_load_config_rearms_empty_ema_snipers():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        cfg = Mark2Config()
        cfg.ENABLE_EMA_STRATEGY = True
        cfg.EMA_LONG_SNIPER = False
        cfg.EMA_SHORT_SNIPER = False
        cfg.EMA_LEFTOVER_LONG = False
        save_config(cfg, path)
        loaded = load_config(path)
        assert loaded.EMA_LONG_SNIPER is True
        assert loaded.EMA_SHORT_SNIPER is True
        assert loaded.EMA_LEFTOVER_LONG is True


def test_load_config_experimental_preserves_user_gate_overrides():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        path.write_text(
            json.dumps(
                {
                    "ENABLE_EXPERIMENTAL_PROFILE": True,
                    "MIN_TICK_VELOCITY": 0.07,
                    "MOMENTUM_BUILD_TICKS": 3,
                    "LONG_CONFIDENCE_THRESHOLD": 58.0,
                    "SHORT_CONFIDENCE_THRESHOLD": 58.0,
                    "LONG_OPPORTUNITY_THRESHOLD": 52.0,
                    "SHORT_OPPORTUNITY_THRESHOLD": 52.0,
                    "MIN_CONFIDENCE_VELOCITY": 0.35,
                    "MAX_EXTENSION_RISK": 72.0,
                    "MIN_RELATIVE_VOLUME": 0.50,
                    "EXPERIMENTAL_DIRECTION_GAP": 8.0,
                    "TRAIL_ARM_POINTS": 4.0,
                    "APPROACH_TRAIL_POINTS": 6.0,
                    "RUNNER_TRAIL_POINTS": 5.0,
                }
            ),
            encoding="utf-8",
        )
        cfg = load_config(path)
        assert cfg.ENABLE_EXPERIMENTAL_PROFILE is True
        assert cfg.MIN_TICK_VELOCITY == 0.07
        assert cfg.MOMENTUM_BUILD_TICKS == 3
        assert cfg.LONG_CONFIDENCE_THRESHOLD == 58.0
        assert cfg.MAX_EXTENSION_RISK == 72.0
        assert cfg.TRAIL_ARM_POINTS == 4.0


def test_ema_strategy_toggle_persists():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        eng = Mark2Engine(Mark2Config(), persist_path=path)
        out = eng.set_entry_toggles({"ema_strategy": True})
        assert out["toggles"]["ema_strategy"] is True
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["ENABLE_EMA_STRATEGY"] is True
        cfg = load_config(path)
        assert cfg.ENABLE_EMA_STRATEGY is True


def test_grow_mode_toggle_persists():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mark2_settings.json"
        eng = Mark2Engine(Mark2Config(), persist_path=path)
        assert eng.cfg.ENABLE_GROW_MODE is False
        out = eng.set_entry_toggles({"grow_mode": True})
        assert out["toggles"]["grow_mode"] is True
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["ENABLE_GROW_MODE"] is True
        cfg = load_config(path)
        assert cfg.ENABLE_GROW_MODE is True
        out = eng.set_entry_toggles({"grow_mode": False})
        assert out["toggles"]["grow_mode"] is False
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["ENABLE_GROW_MODE"] is False


def test_onedrive_settings_path_moves_to_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    cloud = (
        tmp_path
        / "OneDrive"
        / "Desktop"
        / "trading"
        / "dist"
        / "ReconSniper"
        / "mark2_settings.json"
    )
    save_config(Mark2Config(MARK2_ENABLED=False, CONTRACTS=4), cloud)
    dest = local_app_settings_path()
    assert dest == tmp_path / "local" / "ReconSniper" / "mark2_settings.json"
    assert dest.is_file()
    assert not cloud.is_file()
    cfg = load_config(cloud)
    assert cfg.MARK2_ENABLED is False
    assert cfg.CONTRACTS == 4


def test_save_config_swallows_oserror(tmp_path, monkeypatch):
    path = tmp_path / "mark2_settings.json"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "gone"))

    def boom(*_args, **_kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr("mark2.config._atomic_write_text", boom)
    save_config(Mark2Config(CONTRACTS=2), path)


def test_hud_snapshot_sanitizes_nan():
    from mark2.engine import _jsonable

    out = _jsonable({"pf": float("inf"), "x": float("nan"), "ok": 1.5, "nest": [float("-inf")]})
    assert out == {"pf": 0.0, "x": 0.0, "ok": 1.5, "nest": [0.0]}


def test_recon_sniper_hud_owns_grow_bank_default_off():
    """GROW BANK lives on Recon Sniper (mark2), not Impulse engine. Default off."""
    cfg = Mark2Config()
    assert cfg.PRODUCT_NAME == "RECON SNIPER"
    assert cfg.PRODUCT_ENGINE == "ReconSniper"
    assert cfg.BRIDGE_NAME == "ReconSniperBridge"
    assert cfg.ENABLE_GROW_MODE is False
    eng = Mark2Engine(cfg)
    hud = eng.hud_snapshot()
    assert hud["product"] == "RECON SNIPER"
    assert hud["bridgeName"] == "ReconSniperBridge"
    assert hud["growModeEnabled"] is False
    assert hud["growMode"] is False
