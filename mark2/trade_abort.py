"""Exit when entry thesis breaks — momentum/confidence turn against the trade."""

from __future__ import annotations

from .config import Mark2Config
from .types import MarketSnapshot, ScoreBundle, Side


def _signed(snap: MarketSnapshot, side: Side) -> tuple[float, float]:
    vel = snap.velocity if side == Side.LONG else -snap.velocity
    acc = snap.acceleration if side == Side.LONG else -snap.acceleration
    return vel, acc


def check_thesis_abort(
    *,
    cfg: Mark2Config,
    snap: MarketSnapshot,
    scores: ScoreBundle,
    side: Side,
    health: float,
    peak_health: float,
    hold_sec: float,
    bad_streak: int,
    event_alive: bool,
    chop_scalp: bool = False,
) -> tuple[bool, str, int]:
    """Return (abort_now, detail_reason, updated_bad_streak)."""
    if not bool(getattr(cfg, "ENABLE_MOMENTUM_EXIT", True)):
        return False, "", bad_streak

    conf = scores.long_confidence if side == Side.LONG else scores.short_confidence
    conf_v = scores.long_conf_velocity if side == Side.LONG else scores.short_conf_velocity
    opp_conf = scores.short_confidence if side == Side.LONG else scores.long_confidence
    signed_vel, signed_acc = _signed(snap, side)

    if chop_scalp:
        health_floor = float(getattr(cfg, "CHOP_SCALP_EXIT_HEALTH", 35.0))
        vel_cut = float(getattr(cfg, "CHOP_SCALP_EXIT_VEL", -0.08))
        conf_v_cut = float(getattr(cfg, "CHOP_SCALP_EXIT_CONF_VEL", -0.1))
        opp_lead = float(getattr(cfg, "CHOP_SCALP_EXIT_OPP_LEAD", 8.0))
        health_drop = float(getattr(cfg, "CHOP_SCALP_EXIT_HEALTH_DROP", 15.0))
        need_streak = max(1, int(getattr(cfg, "CHOP_SCALP_EXIT_STREAK", 1)))
    else:
        health_floor = float(cfg.SCRATCH_THRESHOLD)
        vel_cut = float(getattr(cfg, "MOMENTUM_EXIT_VEL", -0.12))
        conf_v_cut = float(getattr(cfg, "MOMENTUM_EXIT_CONF_VEL", -0.15))
        opp_lead = float(getattr(cfg, "MOMENTUM_EXIT_OPP_LEAD", 10.0))
        health_drop = float(getattr(cfg, "MOMENTUM_EXIT_HEALTH_DROP", 22.0))
        need_streak = max(1, int(getattr(cfg, "MOMENTUM_EXIT_STREAK", 2)))

    max_sec = float(cfg.SCRATCH_MAX_SECONDS)
    health_window_ok = max_sec <= 0 or hold_sec <= max_sec

    instant: list[str] = []
    soft: list[str] = []

    if health_window_ok and health < health_floor:
        instant.append("health_low")
    if peak_health - health >= health_drop and signed_vel < 0:
        instant.append("health_collapse")
    if signed_vel <= vel_cut * 1.75:
        instant.append("vel_hard")
    if opp_conf >= conf + opp_lead + 4:
        instant.append("opp_flip")
    if not event_alive:
        instant.append("event_dead")

    if signed_vel <= vel_cut:
        soft.append("vel")
    if conf_v <= conf_v_cut:
        soft.append("conf_vel")
    if signed_acc < -0.08:
        soft.append("acc")
    if opp_conf > conf + opp_lead:
        soft.append("opp")

    if instant:
        return True, "+".join(instant), 0

    if len(soft) >= 2:
        bad_streak += 1
    else:
        bad_streak = 0

    if bad_streak >= need_streak:
        return True, "+".join(soft), bad_streak
    return False, "", bad_streak
