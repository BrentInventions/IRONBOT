"""Directional evidence 0–100. Weights are configurable and logged."""

from __future__ import annotations

from collections import deque
from typing import Deque

from .config import Mark2Config
from .types import MarketSnapshot, ScoreBundle, Side


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


def _ema(prev: float, x: float, alpha: float) -> float:
    if prev == 0.0:
        return x
    return alpha * x + (1.0 - alpha) * prev


class ConfidenceEngine:
    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg
        self._long_s = 0.0
        self._short_s = 0.0
        n = max(3, int(cfg.CONFIDENCE_DERIV_WINDOW))
        self._long_hist: Deque[float] = deque(maxlen=n)
        self._short_hist: Deque[float] = deque(maxlen=n)
        self._long_vel = 0.0
        self._short_vel = 0.0
        self.last_parts: dict = {}

    def update(self, snap: MarketSnapshot) -> ScoreBundle:
        w = self.cfg.weights.normalized()
        long_parts = self._parts(snap, Side.LONG)
        short_parts = self._parts(snap, Side.SHORT)
        raw_l = sum(long_parts[k] * w[k] for k in w)
        raw_s = sum(short_parts[k] * w[k] for k in w)
        a = float(self.cfg.CONFIDENCE_SMOOTH_ALPHA)
        self._long_s = _ema(self._long_s, raw_l, a)
        self._short_s = _ema(self._short_s, raw_s, a)
        lv, la = self._deriv(self._long_hist, self._long_s, self._long_vel)
        sv, sa = self._deriv(self._short_hist, self._short_s, self._short_vel)
        self._long_vel, self._short_vel = lv, sv
        self.last_parts = {
            "weights": w,
            "long": long_parts,
            "short": short_parts,
            "raw_long": raw_l,
            "raw_short": raw_s,
        }
        return ScoreBundle(
            long_confidence=_clamp(self._long_s),
            short_confidence=_clamp(self._short_s),
            long_conf_velocity=lv,
            short_conf_velocity=sv,
            long_conf_accel=la,
            short_conf_accel=sa,
            contributors=self.last_parts,
        )

    def _deriv(
        self, hist: Deque[float], current: float, prev_vel: float
    ) -> tuple[float, float]:
        hist.append(current)
        if len(hist) < 3:
            return 0.0, 0.0
        vel = (hist[-1] - hist[0]) / max(len(hist) - 1, 1)
        accel = vel - prev_vel
        return vel, accel

    def _parts(self, snap: MarketSnapshot, side: Side) -> dict[str, float]:
        bull = side == Side.LONG
        bias = snap.trend_bias.upper()
        if bull:
            align = 90.0 if bias in ("BULLISH", "BULL") else (35.0 if bias == "NEUTRAL" else 12.0)
            allowed = 80.0 if snap.longs_allowed else 25.0
        else:
            align = 90.0 if bias in ("BEARISH", "BEAR") else (35.0 if bias == "NEUTRAL" else 12.0)
            allowed = 80.0 if snap.shorts_allowed else 25.0
        trend_alignment = 0.7 * align + 0.3 * min(100.0, snap.trend_strength + allowed * 0.2)

        regime = snap.trend_regime.upper()
        if regime == "TRENDING":
            trend_strength = 88.0
        elif regime == "HIGH_VOL":
            trend_strength = 70.0
        elif regime == "CHOPPY":
            trend_strength = 18.0
        else:
            trend_strength = 15.0

        signed_vel = snap.velocity if bull else -snap.velocity
        signed_acc = snap.acceleration if bull else -snap.acceleration
        momentum = _clamp(50.0 + signed_vel * 8.0)
        impulse = snap.impulse_score if (
            (bull and snap.price >= (snap.forming_bar or {}).get("open", snap.price))
            or (not bull and snap.price <= (snap.forming_bar or {}).get("open", snap.price))
        ) else snap.impulse_score * 0.35

        rel_vol = _clamp(40.0 + (snap.relative_volume - 1.0) * 50.0)
        vol_acc = _clamp(50.0 + snap.volume_acceleration * 80.0)
        velocity = _clamp(50.0 + signed_vel * 12.0)
        acceleration = _clamp(50.0 + signed_acc * 18.0)

        breakout_quality = 50.0
        form = snap.forming_bar or {}
        if form:
            fo = float(form.get("open") or snap.price)
            fh = float(form.get("high") or snap.price)
            fl = float(form.get("low") or snap.price)
            if bull and snap.swing_high > 0:
                progress = (snap.price - snap.swing_high) / max(snap.atr, 0.25)
                breakout_quality = _clamp(50.0 + progress * 25.0)
            elif not bull and snap.swing_low > 0:
                progress = (snap.swing_low - snap.price) / max(snap.atr, 0.25)
                breakout_quality = _clamp(50.0 + progress * 25.0)
            body = abs(snap.price - fo) / max(fh - fl, 1e-9)
            breakout_quality = _clamp(0.6 * breakout_quality + 0.4 * body * 100.0)

        st = snap.structure_state
        if bull:
            structure = 90.0 if st in ("HH_HL", "HH") else (45.0 if st == "MIXED" else 20.0)
        else:
            structure = 90.0 if st in ("LH_LL", "LL") else (45.0 if st == "MIXED" else 20.0)

        vs = snap.volatility_state
        if vs == "expanding":
            volatility_state = 80.0
        elif vs == "shrinking":
            volatility_state = 30.0
        else:
            volatility_state = 55.0

        d = snap.vwap_distance_atr
        if bull:
            vwap_relationship = 82.0 if d >= 0 else _clamp(50.0 + d * 12.0)
        else:
            vwap_relationship = 82.0 if d <= 0 else _clamp(50.0 - d * 12.0)

        return {
            "trend_alignment": trend_alignment,
            "trend_strength": trend_strength,
            "momentum": momentum,
            "impulse": _clamp(impulse),
            "relative_volume": rel_vol,
            "volume_acceleration": vol_acc,
            "velocity": velocity,
            "acceleration": acceleration,
            "breakout_quality": breakout_quality,
            "structure": structure,
            "volatility_state": volatility_state,
            "vwap_relationship": vwap_relationship,
        }
