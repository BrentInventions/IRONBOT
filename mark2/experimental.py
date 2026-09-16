"""Mark II experimental profile — Phase 1 candidate gates + entry quality rules."""

from __future__ import annotations

from typing import Any

from .config import Mark2Config
from .bias_entry import bias_entry_gates
from .entry_gates import relative_volume_floor
from .entry_tuning import apply_strictness
from .structure_gate import structure_blocks_entry
from .types import MarketSnapshot, ScoreBundle, Side

# Factory defaults restored when experimental mode is turned off.
_FACTORY_EXIT = {
    "TRAIL_ARM_POINTS": 6.0,
    "APPROACH_TRAIL_POINTS": 5.5,
    "RUNNER_TRAIL_POINTS": 5.5,
    "MIN_RELATIVE_VOLUME": 0.45,
    "EXPERIMENTAL_DIRECTION_GAP": 8.0,
}

# Phase 1 Mark II candidate profile (entry + exit knobs wired to cfg).
EXPERIMENTAL_PROFILE: dict[str, float | int | bool] = {
    "LONG_CONFIDENCE_THRESHOLD": 62.0,
    "SHORT_CONFIDENCE_THRESHOLD": 62.0,
    "LONG_OPPORTUNITY_THRESHOLD": 55.0,
    "SHORT_OPPORTUNITY_THRESHOLD": 55.0,
    "MIN_CONFIDENCE_VELOCITY": 0.40,
    "MOMENTUM_BUILD_TICKS": 4,
    "MAX_EXTENSION_RISK": 68.0,
    "MIN_RELATIVE_VOLUME": 0.55,
    "MIN_TICK_VELOCITY": 0.10,
    "EXPERIMENTAL_DIRECTION_GAP": 10.0,
    "TRAIL_ARM_POINTS": 4.0,
    "APPROACH_TRAIL_POINTS": 6.0,
    "RUNNER_TRAIL_POINTS": 5.0,
    "EXPERIMENTAL_REQUIRE_QUALITY": True,
    "EXPERIMENTAL_REQUIRE_SIDE_AGREEMENT": True,
}


def is_experimental(cfg: Mark2Config) -> bool:
    return bool(getattr(cfg, "ENABLE_EXPERIMENTAL_PROFILE", False))


def apply_experimental_profile(cfg: Mark2Config) -> None:
    cfg.ENABLE_EXPERIMENTAL_PROFILE = True
    cfg.ENTRY_TUNING_CUSTOM = True
    for key, val in EXPERIMENTAL_PROFILE.items():
        setattr(cfg, key, val)


def restore_factory_profile(cfg: Mark2Config) -> None:
    cfg.ENABLE_EXPERIMENTAL_PROFILE = False
    apply_strictness(cfg, float(getattr(cfg, "ENTRY_STRICTNESS", 45.0)), custom=False)
    for key, val in _FACTORY_EXIT.items():
        setattr(cfg, key, val)


def toggle_experimental(cfg: Mark2Config, enabled: bool) -> None:
    if enabled:
        apply_experimental_profile(cfg)
    else:
        restore_factory_profile(cfg)


def snapshot_experimental(cfg: Mark2Config) -> dict[str, Any]:
    return {
        "enabled": is_experimental(cfg),
        "profile": "mark2_phase1",
        "gates": {
            "confidence": float(cfg.LONG_CONFIDENCE_THRESHOLD),
            "opportunity": float(cfg.LONG_OPPORTUNITY_THRESHOLD),
            "conf_velocity": float(cfg.MIN_CONFIDENCE_VELOCITY),
            "build_ticks": int(cfg.MOMENTUM_BUILD_TICKS),
            "direction_gap": float(getattr(cfg, "EXPERIMENTAL_DIRECTION_GAP", 10.0)),
            "max_extension": float(cfg.MAX_EXTENSION_RISK),
            "min_rvol": float(cfg.MIN_RELATIVE_VOLUME),
            "tick_velocity": float(cfg.MIN_TICK_VELOCITY),
            "trail_arm": float(getattr(cfg, "TRAIL_ARM_POINTS", 4.0)),
            "approach_trail": float(getattr(cfg, "APPROACH_TRAIL_POINTS", 6.0)),
            "runner_trail": float(getattr(cfg, "RUNNER_TRAIL_POINTS", 5.0)),
        },
        "require_quality": bool(getattr(cfg, "EXPERIMENTAL_REQUIRE_QUALITY", True)),
        "require_side_agreement": bool(
            getattr(cfg, "EXPERIMENTAL_REQUIRE_SIDE_AGREEMENT", True)
        ),
    }


def _side_metrics(
    side: Side, snap: MarketSnapshot, scores: ScoreBundle
) -> tuple[float, float, float, float, float, float]:
    if side == Side.LONG:
        conf = float(scores.long_confidence)
        opp = float(scores.long_opportunity)
        opp_other = float(scores.short_confidence)
        conf_v = float(scores.long_conf_velocity)
        signed_vel = float(snap.velocity)
        ext = float(scores.extension_risk_long)
    else:
        conf = float(scores.short_confidence)
        opp = float(scores.short_opportunity)
        opp_other = float(scores.long_confidence)
        conf_v = float(scores.short_conf_velocity)
        signed_vel = -float(snap.velocity)
        ext = float(scores.extension_risk_short)
    return conf, opp, opp_other, conf_v, signed_vel, ext


def entry_quality_ok(
    snap: MarketSnapshot,
    scores: ScoreBundle,
    side: Side,
    cfg: Mark2Config,
) -> tuple[bool, str]:
    """At least 3 of 4 pillars must be strong: conf, opp, velocity, impulse/rvol."""
    if not is_experimental(cfg) or not bool(
        getattr(cfg, "EXPERIMENTAL_REQUIRE_QUALITY", True)
    ):
        return True, ""
    conf, opp, _, conf_v, signed_vel, _ = _side_metrics(side, snap, scores)
    need_c = float(cfg.LONG_CONFIDENCE_THRESHOLD if side == Side.LONG else cfg.SHORT_CONFIDENCE_THRESHOLD)
    need_o = float(cfg.LONG_OPPORTUNITY_THRESHOLD if side == Side.LONG else cfg.SHORT_OPPORTUNITY_THRESHOLD)
    need_v = float(cfg.MIN_CONFIDENCE_VELOCITY)
    need_tick = float(cfg.MIN_TICK_VELOCITY)
    impulse_min = float(getattr(cfg, "IMPULSE_MIN", 55.0))
    rvol_min = relative_volume_floor(snap, cfg)

    strong = 0
    pillars: list[str] = []
    if conf >= need_c:
        strong += 1
        pillars.append("conf")
    if opp >= need_o:
        strong += 1
        pillars.append("opp")
    if conf_v >= need_v and signed_vel >= need_tick:
        strong += 1
        pillars.append("vel")
    if float(snap.impulse_score) >= impulse_min or float(snap.relative_volume) >= rvol_min:
        strong += 1
        pillars.append("impulse_rvol")

    if strong >= 3:
        return True, f"quality={strong}/4:{','.join(pillars)}"
    return False, f"quality={strong}/4 need 3+"


def directional_agreement_ok(
    snap: MarketSnapshot,
    scores: ScoreBundle,
    side: Side,
    cfg: Mark2Config,
) -> tuple[bool, str]:
    """Opportunity, confidence, and bias must agree on direction."""
    if not is_experimental(cfg) or not bool(
        getattr(cfg, "EXPERIMENTAL_REQUIRE_SIDE_AGREEMENT", True)
    ):
        return True, ""
    conf, opp, opp_conf, _, _, _ = _side_metrics(side, snap, scores)
    gap = float(getattr(cfg, "EXPERIMENTAL_DIRECTION_GAP", 10.0))
    need_c = float(cfg.LONG_CONFIDENCE_THRESHOLD if side == Side.LONG else cfg.SHORT_CONFIDENCE_THRESHOLD)
    bias = (snap.trend_bias or "").upper()

    bias_gates = bias_entry_gates(cfg, snap, side)
    if side == Side.LONG:
        if float(scores.long_opportunity) <= float(scores.short_opportunity):
            return False, "opp_disagree"
        if bias not in ("BULLISH", "BULL"):
            return False, f"bias={bias}"
        if structure_blocks_entry(snap, side, cfg, bias_gates=bias_gates):
            return False, "structure=LH_LL"
    else:
        if float(scores.short_opportunity) <= float(scores.long_opportunity):
            return False, "opp_disagree"
        if bias not in ("BEARISH", "BEAR"):
            return False, f"bias={bias}"
        if structure_blocks_entry(snap, side, cfg, bias_gates=bias_gates):
            return False, "structure=HH_HL"

    if conf < need_c:
        return False, f"conf={conf:.0f}<{need_c:.0f}"
    if conf - opp_conf < gap:
        return False, f"gap={conf - opp_conf:.0f}<{gap:.0f}"
    return True, "side_ok"
