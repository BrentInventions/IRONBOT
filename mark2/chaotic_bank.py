"""Bias-aligned quick-bank trades in CHAOTIC regime (high ATR).

Unlike chop scalp, this only trades WITH trend bias:
  BEARISH + CHAOTIC → shorts only
  BULLISH + CHAOTIC → longs only
"""

from __future__ import annotations

from .config import Mark2Config
from .types import MarketSnapshot, ScoreBundle, Side


def _bias_allows(side: Side, bias: str) -> bool:
    b = (bias or "").upper()
    if side == Side.LONG:
        return b in ("BULLISH", "BULL")
    if side == Side.SHORT:
        return b in ("BEARISH", "BEAR")
    return False


def chaotic_entry_ok(
    snap: MarketSnapshot,
    scores: ScoreBundle,
    side: Side,
    cfg: Mark2Config,
) -> tuple[bool, str]:
    if not bool(getattr(cfg, "ENABLE_CHAOTIC_BANK", True)):
        return False, "disabled"
    if (snap.trend_regime or "").upper() != "CHAOTIC":
        return False, "not_chaotic"
    if not _bias_allows(side, snap.trend_bias):
        return False, f"bias={snap.trend_bias or 'NEUTRAL'}"

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

    need_conf = float(getattr(cfg, "CHAOTIC_BANK_CONFIDENCE", 55.0))
    need_opp = float(getattr(cfg, "CHAOTIC_BANK_OPPORTUNITY", 54.0))
    need_vel = float(getattr(cfg, "CHAOTIC_BANK_MIN_TICK_VEL", 0.28))
    need_conf_v = float(getattr(cfg, "CHAOTIC_BANK_MIN_CONF_VEL", 0.22))
    gap = float(getattr(cfg, "CHAOTIC_BANK_DIRECTION_GAP", 8.0))

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
    return True, "chaotic_ok"
