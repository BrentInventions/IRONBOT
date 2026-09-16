"""Bias-aligned entry loosening — lower gates when tape agrees with direction."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Mark2Config
from .types import MarketSnapshot, Side


@dataclass(frozen=True)
class BiasEntryGates:
    active: bool = False
    tag: str = ""
    conf_threshold: float | None = None
    opp_threshold: float | None = None
    min_conf_vel: float | None = None
    build_ticks: int | None = None
    relax_candle: bool = False
    relax_forming_direction: bool = False
    relax_structure: bool = False
    min_tick_velocity: float | None = None
    min_relative_volume: float | None = None
    direction_gap: float | None = None


def _tradeable_regime(regime: str) -> bool:
    return regime in ("TRENDING", "HIGH_VOL")


def bias_entry_gates(
    cfg: Mark2Config,
    snap: MarketSnapshot,
    side: Side,
    *,
    entry_profile: str = "default",
) -> BiasEntryGates:
    if not bool(getattr(cfg, "ENABLE_BIAS_ENTRY_ADJUST", True)):
        return BiasEntryGates()
    if entry_profile in ("chop_scalp", "chaotic_bank"):
        return BiasEntryGates()
    if side not in (Side.LONG, Side.SHORT):
        return BiasEntryGates()

    regime = (snap.trend_regime or "").upper()
    if not _tradeable_regime(regime):
        return BiasEntryGates()

    bias = (snap.trend_bias or "").upper()
    relax = bool(getattr(cfg, "BIAS_RELAX_CANDLES", True))
    build = max(1, int(getattr(cfg, "BIAS_BUILD_TICKS", 2)))
    min_tick = float(getattr(cfg, "BIAS_MIN_TICK_VEL", 0.05))
    gap = float(getattr(cfg, "BIAS_DIRECTION_GAP", 6.0))

    high_vol = regime == "HIGH_VOL"
    hv_conf = float(getattr(cfg, "BIAS_HIGH_VOL_CONF_DELTA", 2.0)) if high_vol else 0.0
    hv_opp = float(getattr(cfg, "BIAS_HIGH_VOL_OPP_DELTA", 1.0)) if high_vol else 0.0
    hv_tick = float(getattr(cfg, "BIAS_HIGH_VOL_TICK_VEL", 0.02)) if high_vol else 0.0
    hv_min_rvol = (
        float(getattr(cfg, "BIAS_HIGH_VOL_MIN_RVOL", 0.18)) if high_vol else None
    )
    conf_floor = (
        float(getattr(cfg, "BIAS_HIGH_VOL_CONF_FLOOR", 46.0))
        if high_vol
        else 48.0
    )
    relax_direction = high_vol and bool(getattr(cfg, "BIAS_HIGH_VOL_RELAX_FORMING", True))
    relax_structure = high_vol and bool(getattr(cfg, "BIAS_HIGH_VOL_RELAX_STRUCTURE", True))
    # HIGH_VOL: block wrong-way tick flow only (0), not flat tape (~0.03).
    hv_min_tick = 0.0 if high_vol else max(0.03, min_tick - hv_tick)

    if side == Side.SHORT and bias in ("BEARISH", "BEAR") and snap.shorts_allowed:
        conf_delta = float(getattr(cfg, "BIAS_SHORT_CONF_DELTA", 4.0)) + hv_conf
        opp_delta = float(getattr(cfg, "BIAS_SHORT_OPP_DELTA", 2.0)) + hv_opp
        vel_delta = float(getattr(cfg, "BIAS_SHORT_CONF_VEL_DELTA", 0.12))
        return BiasEntryGates(
            active=True,
            tag="bias_short",
            conf_threshold=max(conf_floor, float(cfg.SHORT_CONFIDENCE_THRESHOLD) - conf_delta),
            opp_threshold=max(45.0, float(cfg.SHORT_OPPORTUNITY_THRESHOLD) - opp_delta),
            min_conf_vel=max(0.08, float(cfg.MIN_CONFIDENCE_VELOCITY) - vel_delta),
            build_ticks=build,
            relax_candle=relax,
            relax_forming_direction=relax_direction,
            relax_structure=relax_structure,
            min_tick_velocity=hv_min_tick,
            min_relative_volume=hv_min_rvol,
            direction_gap=gap,
        )

    if side == Side.LONG and bias in ("BULLISH", "BULL") and snap.longs_allowed:
        conf_delta = float(getattr(cfg, "BIAS_LONG_CONF_DELTA", 4.0)) + hv_conf
        opp_delta = float(getattr(cfg, "BIAS_LONG_OPP_DELTA", 2.0)) + hv_opp
        vel_delta = float(getattr(cfg, "BIAS_LONG_CONF_VEL_DELTA", 0.12))
        return BiasEntryGates(
            active=True,
            tag="bias_long",
            conf_threshold=max(conf_floor, float(cfg.LONG_CONFIDENCE_THRESHOLD) - conf_delta),
            opp_threshold=max(45.0, float(cfg.LONG_OPPORTUNITY_THRESHOLD) - opp_delta),
            min_conf_vel=max(0.08, float(cfg.MIN_CONFIDENCE_VELOCITY) - vel_delta),
            build_ticks=build,
            relax_candle=relax,
            relax_forming_direction=relax_direction,
            relax_structure=relax_structure,
            min_tick_velocity=hv_min_tick,
            min_relative_volume=hv_min_rvol,
            direction_gap=gap,
        )

    return BiasEntryGates()
