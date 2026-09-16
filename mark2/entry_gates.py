"""Shared entry gate helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import Mark2Config
from .types import MarketSnapshot

if TYPE_CHECKING:
    from .bias_entry import BiasEntryGates


def relative_volume_floor(
    snap: MarketSnapshot,
    cfg: Mark2Config,
    *,
    bias_gates: BiasEntryGates | None = None,
) -> float:
    """Effective rvol minimum for the current regime (shared by base + EXP quality gates)."""
    regime = (snap.trend_regime or "").upper()
    floor = float(getattr(cfg, "MIN_RELATIVE_VOLUME", 0.45))
    if regime in ("HIGH_VOL", "TRENDING", "CHOPPY"):
        floor = min(floor, float(getattr(cfg, "MIN_RELATIVE_VOLUME_TREND", 0.35)))
    if regime == "HIGH_VOL":
        floor = min(floor, float(getattr(cfg, "MIN_RELATIVE_VOLUME_HIGH_VOL", 0.32)))
    if (
        bias_gates is not None
        and bias_gates.active
        and bias_gates.min_relative_volume is not None
    ):
        floor = min(floor, float(bias_gates.min_relative_volume))
    return floor


def volume_entry_ok(
    snap: MarketSnapshot,
    cfg: Mark2Config,
    *,
    signed_vel: float = 0.0,
    bias_gates: BiasEntryGates | None = None,
) -> bool:
    """Relative volume floor with trend/chop relax and strong-velocity bypass."""
    if float(snap.volume or 0) <= 0:
        return True
    bypass = float(getattr(cfg, "VOLUME_VEL_BYPASS", 0.25))
    if abs(float(signed_vel)) >= bypass:
        return True
    return float(snap.relative_volume) >= relative_volume_floor(
        snap, cfg, bias_gates=bias_gates
    )


def candle_min_aligned(
    cfg: Mark2Config,
    *,
    side_signed_vel: float,
    bias_active: bool,
    entry_profile: str,
) -> int:
    base = max(0, int(cfg.CANDLE_ALIGN_MIN_BARS))
    if entry_profile == "chop_scalp":
        return max(0, int(getattr(cfg, "CHOP_CANDLE_MIN_BARS", 0)))
    if entry_profile == "chaotic_bank":
        return max(0, int(getattr(cfg, "CHAOTIC_CANDLE_MIN_BARS", 0)))
    if not bias_active or not bool(getattr(cfg, "BIAS_ALLOW_ZERO_BARS", True)):
        return base
    strong = float(getattr(cfg, "BIAS_STRONG_TICK_VEL", 0.25))
    if abs(float(side_signed_vel)) >= strong:
        return 0
    return base
