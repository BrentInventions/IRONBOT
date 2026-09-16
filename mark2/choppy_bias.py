"""Bias-aligned entries in CHOPPY regime — default/EXP profile, not chop scalp."""

from __future__ import annotations

from .config import Mark2Config
from .types import MarketSnapshot, Side


def choppy_bias_entry_ok(
    cfg: Mark2Config,
    snap: MarketSnapshot,
    direction: Side,
) -> tuple[bool, str]:
    if not bool(getattr(cfg, "ENABLE_CHOPPY_BIAS", False)):
        return False, "disabled"
    if (snap.trend_regime or "").upper() != "CHOPPY":
        return False, "not_choppy"
    bias = (snap.trend_bias or "").upper()
    if direction == Side.LONG and bias in ("BULLISH", "BULL"):
        return True, "choppy_bias_ok"
    if direction == Side.SHORT and bias in ("BEARISH", "BEAR"):
        return True, "choppy_bias_ok"
    return False, "bias_mismatch"
