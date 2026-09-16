"""Entry gate helpers — volume floor + bias candle relax."""

from __future__ import annotations

from mark2.bias_entry import bias_entry_gates
from mark2.config import Mark2Config
from mark2.entry_gates import candle_min_aligned, volume_entry_ok
from mark2.types import MarketSnapshot, Side


def _snap(**kw) -> MarketSnapshot:
    base = dict(
        ts=1.0,
        price=20000.0,
        completed_bars=[],
        forming_bar=None,
        volume=500.0,
        relative_volume=0.30,
        trend_regime="HIGH_VOL",
        velocity=-0.5,
    )
    base.update(kw)
    return MarketSnapshot(**base)


def test_volume_bypass_on_strong_velocity():
    cfg = Mark2Config()
    snap = _snap(relative_volume=0.20)
    assert volume_entry_ok(snap, cfg, signed_vel=-0.30) is True


def test_volume_trend_floor_035():
    cfg = Mark2Config()
    snap = _snap(relative_volume=0.38)
    assert volume_entry_ok(snap, cfg, signed_vel=0.0) is True
    snap2 = _snap(relative_volume=0.30)
    assert volume_entry_ok(snap2, cfg, signed_vel=0.0) is False


def test_volume_high_vol_floor_032():
    cfg = Mark2Config()
    snap = _snap(relative_volume=0.33, trend_regime="HIGH_VOL")
    assert volume_entry_ok(snap, cfg, signed_vel=0.0) is True
    snap2 = _snap(relative_volume=0.30, trend_regime="HIGH_VOL")
    assert volume_entry_ok(snap2, cfg, signed_vel=0.0) is False


def test_bias_zero_bars_when_velocity_strong():
    cfg = Mark2Config()
    assert (
        candle_min_aligned(
            cfg,
            side_signed_vel=-0.30,
            bias_active=True,
            entry_profile="default",
        )
        == 0
    )
    assert (
        candle_min_aligned(
            cfg,
            side_signed_vel=-0.10,
            bias_active=True,
            entry_profile="default",
        )
        == 1
    )


def test_chop_uses_zero_bar_default():
    cfg = Mark2Config()
    assert (
        candle_min_aligned(
            cfg,
            side_signed_vel=0.0,
            bias_active=False,
            entry_profile="chop_scalp",
        )
        == 0
    )


def test_bias_high_vol_volume_floor_018():
    cfg = Mark2Config()
    snap = _snap(
        relative_volume=0.20,
        trend_regime="HIGH_VOL",
        trend_bias="BEARISH",
        shorts_allowed=True,
    )
    gates = bias_entry_gates(cfg, snap, Side.SHORT)
    assert gates.active
    assert volume_entry_ok(snap, cfg, signed_vel=0.0, bias_gates=gates) is True
    snap2 = _snap(relative_volume=0.15, trend_regime="HIGH_VOL")
    assert volume_entry_ok(snap2, cfg, signed_vel=0.0, bias_gates=gates) is False
