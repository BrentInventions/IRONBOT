"""In-trade health: does the reason we entered still exist?"""

from __future__ import annotations

from .config import Mark2Config
from .types import MarketSnapshot, ScoreBundle, Side


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


class TradeHealthEngine:
    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg

    def score(
        self,
        snap: MarketSnapshot,
        scores: ScoreBundle,
        *,
        side: Side,
        entry_price: float,
        mfe: float,
        mae: float,
        hold_sec: float,
    ) -> float:
        signed_vel = snap.velocity if side == Side.LONG else -snap.velocity
        signed_acc = snap.acceleration if side == Side.LONG else -snap.acceleration
        conf = scores.long_confidence if side == Side.LONG else scores.short_confidence
        conf_v = scores.long_conf_velocity if side == Side.LONG else scores.short_conf_velocity
        atr = max(snap.atr, self.cfg.TICK_SIZE)
        mfe_atr = mfe / atr
        mae_atr = mae / atr
        pullback = mae_atr / max(mfe_atr, 0.15)

        mom = _clamp(50.0 + signed_vel * 10.0)
        acc = _clamp(50.0 + signed_acc * 16.0)
        vol = _clamp(40.0 + (snap.relative_volume - 1.0) * 45.0)
        conf_term = _clamp(conf)
        conf_v_term = _clamp(50.0 + conf_v * 12.0)
        mfe_term = _clamp(40.0 + mfe_atr * 20.0)
        mae_term = _clamp(80.0 - mae_atr * 35.0)
        pb_term = _clamp(80.0 - pullback * 40.0)
        age_term = 70.0 if hold_sec < 30 else (50.0 if hold_sec < 90 else 35.0)

        health = (
            0.16 * mom
            + 0.12 * acc
            + 0.10 * vol
            + 0.14 * conf_term
            + 0.10 * conf_v_term
            + 0.12 * mfe_term
            + 0.12 * mae_term
            + 0.08 * pb_term
            + 0.06 * age_term
        )
        return _clamp(health)
