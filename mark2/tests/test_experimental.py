"""Mark II experimental profile tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.experimental import (
    apply_experimental_profile,
    directional_agreement_ok,
    entry_quality_ok,
    is_experimental,
    restore_factory_profile,
    toggle_experimental,
)
from mark2.types import MarketSnapshot, ScoreBundle, Side


def _snap(**kw) -> MarketSnapshot:
    base = dict(
        ts=1.0,
        price=20000.0,
        completed_bars=[],
        forming_bar={"open": 20000.0, "high": 20001.0, "low": 19999.0},
        atr=12.0,
        velocity=-0.35,
        impulse_score=58.0,
        relative_volume=1.2,
        trend_bias="BEARISH",
        trend_regime="TRENDING",
        structure_state="MIXED",
        longs_allowed=False,
        shorts_allowed=True,
    )
    base.update(kw)
    return MarketSnapshot(**base)


def _scores(**kw) -> ScoreBundle:
    base = dict(
        long_confidence=44.0,
        short_confidence=64.0,
        long_opportunity=40.0,
        short_opportunity=58.0,
        long_conf_velocity=0.1,
        short_conf_velocity=0.42,
    )
    base.update(kw)
    return ScoreBundle(**base)


def test_toggle_applies_phase1_gates():
    cfg = Mark2Config()
    toggle_experimental(cfg, True)
    assert is_experimental(cfg)
    assert cfg.LONG_CONFIDENCE_THRESHOLD == 62.0
    assert cfg.MOMENTUM_BUILD_TICKS == 4
    assert cfg.TRAIL_ARM_POINTS == 4.0
    assert cfg.APPROACH_TRAIL_POINTS == 6.0
    assert cfg.RUNNER_TRAIL_POINTS == 5.0
    toggle_experimental(cfg, False)
    assert not is_experimental(cfg)


def test_quality_uses_high_vol_rvol_floor():
    cfg = Mark2Config()
    apply_experimental_profile(cfg)
    cfg.MIN_RELATIVE_VOLUME = 0.50
    ok, _ = entry_quality_ok(
        _snap(relative_volume=0.33, impulse_score=40.0, trend_regime="HIGH_VOL"),
        _scores(short_confidence=63.0, short_opportunity=54.0, short_conf_velocity=0.41),
        Side.SHORT,
        cfg,
    )
    assert ok is True


def test_quality_requires_three_of_four():
    cfg = Mark2Config()
    apply_experimental_profile(cfg)
    ok, _ = entry_quality_ok(_snap(), _scores(), Side.SHORT, cfg)
    assert ok is True
    ok, detail = entry_quality_ok(
        _snap(relative_volume=0.30, impulse_score=40.0, trend_regime="TRENDING"),
        _scores(short_confidence=63.0, short_opportunity=54.0, short_conf_velocity=0.41),
        Side.SHORT,
        cfg,
    )
    assert ok is False
    assert "quality=" in detail


def test_side_agreement_blocks_counter_bias():
    cfg = Mark2Config()
    apply_experimental_profile(cfg)
    ok, why = directional_agreement_ok(_snap(), _scores(), Side.LONG, cfg)
    assert ok is False
    assert why in ("opp_disagree", "bias=BEARISH", "bias=BEAR")
    ok, _ = directional_agreement_ok(_snap(), _scores(), Side.SHORT, cfg)
    assert ok is True


def test_side_agreement_relaxes_structure_in_high_vol():
    cfg = Mark2Config()
    apply_experimental_profile(cfg)
    snap = _snap(
        relative_volume=0.33,
        impulse_score=40.0,
        trend_regime="HIGH_VOL",
        trend_bias="BEARISH",
        shorts_allowed=True,
        structure_state="HH_HL",
    )
    ok, why = directional_agreement_ok(snap, _scores(), Side.SHORT, cfg)
    assert ok is True
    assert why == "side_ok"
