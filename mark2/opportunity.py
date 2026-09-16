"""OpportunityScore: is this moment unusual vs recent behavior?

Separate from confidence. A persistently bullish tape should not keep firing.
"""

from __future__ import annotations

from collections import deque
from typing import Deque

from .config import Mark2Config
from .types import MarketSnapshot, ScoreBundle, Side


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


def _z(x: float, hist: Deque[float]) -> float:
    if len(hist) < 8:
        return 0.0
    mean = sum(hist) / len(hist)
    var = sum((v - mean) ** 2 for v in hist) / max(len(hist) - 1, 1)
    sd = var ** 0.5
    if sd < 1e-9:
        return 0.0
    return (x - mean) / sd


class OpportunityEngine:
    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg
        n = max(12, int(cfg.OPPORTUNITY_BASELINE_BARS) * 4)
        self._abs_vel: Deque[float] = deque(maxlen=n)
        self._rel_vol: Deque[float] = deque(maxlen=n)
        self._vol_acc: Deque[float] = deque(maxlen=n)
        self._impulse: Deque[float] = deque(maxlen=n)
        self._conf_vel_l: Deque[float] = deque(maxlen=n)
        self._conf_vel_s: Deque[float] = deque(maxlen=n)

    def update(self, snap: MarketSnapshot, scores: ScoreBundle) -> ScoreBundle:
        self._abs_vel.append(abs(snap.velocity))
        self._rel_vol.append(snap.relative_volume)
        self._vol_acc.append(snap.volume_acceleration)
        self._impulse.append(snap.impulse_score)
        self._conf_vel_l.append(scores.long_conf_velocity)
        self._conf_vel_s.append(scores.short_conf_velocity)

        scores.long_opportunity = self._score(snap, scores, Side.LONG)
        scores.short_opportunity = self._score(snap, scores, Side.SHORT)
        return scores

    def _score(self, snap: MarketSnapshot, scores: ScoreBundle, side: Side) -> float:
        signed_vel = snap.velocity if side == Side.LONG else -snap.velocity
        z_vel = max(0.0, _z(abs(snap.velocity), self._abs_vel)) if signed_vel > 0 else 0.0
        z_vol = max(0.0, _z(snap.relative_volume, self._rel_vol))
        z_vacc = max(0.0, _z(snap.volume_acceleration, self._vol_acc))
        z_imp = max(0.0, _z(snap.impulse_score, self._impulse))
        cv = scores.long_conf_velocity if side == Side.LONG else scores.short_conf_velocity
        hist = self._conf_vel_l if side == Side.LONG else self._conf_vel_s
        z_cv = max(0.0, _z(cv, hist)) if cv > 0 else 0.0

        vol_exp = 80.0 if snap.volatility_state == "expanding" else (
            25.0 if snap.volatility_state == "shrinking" else 45.0
        )
        # Compression-to-expansion: shrinking recently but live impulse rising
        if snap.volatility_state != "expanding" and snap.impulse_score >= 60:
            vol_exp = max(vol_exp, 70.0)

        breakout = 50.0
        if side == Side.LONG and snap.swing_high > 0 and snap.price > snap.swing_high:
            breakout = 78.0
        elif side == Side.SHORT and snap.swing_low > 0 and snap.price < snap.swing_low:
            breakout = 78.0

        unusual = (
            0.22 * _clamp(50.0 + z_vel * 18.0)
            + 0.18 * _clamp(50.0 + z_vol * 18.0)
            + 0.14 * _clamp(50.0 + z_vacc * 22.0)
            + 0.16 * _clamp(50.0 + z_imp * 16.0)
            + 0.16 * _clamp(50.0 + z_cv * 20.0)
            + 0.08 * vol_exp
            + 0.06 * breakout
        )
        # Directional: unusual activity against the side is not an opportunity
        if signed_vel < 0:
            unusual *= 0.35
        return _clamp(unusual)
