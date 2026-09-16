"""Quick scalps in CHOPPY regime — micro bank, tight stop, fast thesis exit."""

from __future__ import annotations

from .config import Mark2Config
from .types import MarketSnapshot, ScoreBundle, Side


def chop_entry_ok(
    snap: MarketSnapshot,
    scores: ScoreBundle,
    side: Side,
    cfg: Mark2Config,
    *,
    force_enable: bool = False,
    need_conf: float | None = None,
    need_opp: float | None = None,
    need_vel: float | None = None,
    need_conf_v: float | None = None,
    gap: float | None = None,
) -> tuple[bool, str]:
    if not force_enable and not bool(getattr(cfg, "ENABLE_CHOP_SCALP", True)):
        return False, "disabled"
    if (snap.trend_regime or "").upper() != "CHOPPY":
        return False, "not_choppy"

    long_c = float(scores.long_confidence)
    short_c = float(scores.short_confidence)
    if side == Side.LONG:
        conf = long_c
        opp_conf = short_c
        signed_vel = float(snap.velocity)
        conf_v = float(scores.long_conf_velocity)
        opp = float(scores.long_opportunity)
    elif side == Side.SHORT:
        conf = short_c
        opp_conf = long_c
        signed_vel = -float(snap.velocity)
        conf_v = float(scores.short_conf_velocity)
        opp = float(scores.short_opportunity)
    else:
        return False, "no_side"

    need_conf = float(
        need_conf if need_conf is not None else getattr(cfg, "CHOP_SCALP_CONFIDENCE", 52.0)
    )
    need_opp = float(
        need_opp if need_opp is not None else getattr(cfg, "CHOP_SCALP_OPPORTUNITY", 60.0)
    )
    need_vel = float(
        need_vel if need_vel is not None else getattr(cfg, "CHOP_SCALP_MIN_TICK_VEL", 0.35)
    )
    need_conf_v = float(
        need_conf_v
        if need_conf_v is not None
        else getattr(cfg, "CHOP_SCALP_MIN_CONF_VEL", 0.18)
    )
    gap = float(gap if gap is not None else getattr(cfg, "CHOP_SCALP_DIRECTION_GAP", 10.0))

    if conf < need_conf:
        return False, f"conf={conf:.0f}<{need_conf:.0f}"
    if opp < need_opp:
        return False, f"opp={opp:.0f}<{need_opp:.0f}"
    if signed_vel < need_vel:
        return False, f"vel={signed_vel:.2f}<{need_vel}"
    if conf_v < need_conf_v:
        return False, f"conf_vel={conf_v:.2f}<{need_conf_v}"
    if conf - opp_conf < gap:
        return False, f"gap={conf - opp_conf:.0f}<{gap:.0f}"
    return True, "chop_ok"
