"""Fast-changing features from the live tick stream.

Only uses information available at the current tick. The forming bar is a
copy of OHLC accumulated so far — never the final high/low of an unfinished candle.
"""

from __future__ import annotations

from collections import deque
from typing import Deque

from .config import Mark2Config
from .types import Tick


class FastFeatures:
    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg
        self._ticks: Deque[tuple[float, float, float]] = deque(maxlen=max(16, int(cfg.TICK_BUFFER)))
        self._prev_velocity = 0.0
        self._prev_rel_vol = 0.0
        self._forming_vol_hist: Deque[tuple[float, float]] = deque(maxlen=40)

    def reset(self) -> None:
        self._ticks.clear()
        self._forming_vol_hist.clear()
        self._prev_velocity = 0.0
        self._prev_rel_vol = 0.0

    def update(self, tick: Tick, atr_now: float, completed_avg_volume: float) -> dict[str, float]:
        self._ticks.append((tick.ts, tick.price, tick.forming_volume or tick.volume))
        vel = self._velocity(tick.ts)
        dt = max(self.cfg.ACCEL_WINDOW_SEC, 0.05)
        accel = (vel - self._prev_velocity) / dt
        self._prev_velocity = vel

        form_vol = float(tick.forming_volume or tick.volume or 0.0)
        self._forming_vol_hist.append((tick.ts, form_vol))
        rel = 0.0
        if completed_avg_volume > 0 and form_vol > 0:
            rel = form_vol / completed_avg_volume
        vol_accel = rel - self._prev_rel_vol
        self._prev_rel_vol = rel

        atr_safe = max(float(atr_now), self.cfg.TICK_SIZE)
        vel_atr = vel / atr_safe
        impulse = _impulse_live(tick, atr_safe, vel_atr, rel)

        return {
            "velocity": vel,
            "acceleration": accel,
            "relative_volume": rel,
            "volume_acceleration": vol_accel,
            "volume": form_vol,
            "impulse_score": impulse,
            "velocity_atr": vel_atr,
        }

    def _velocity(self, now: float) -> float:
        window = float(self.cfg.VELOCITY_WINDOW_SEC)
        samples = [(t, p) for t, p, _v in self._ticks if now - t <= window]
        if len(samples) < 2:
            return 0.0
        dt = samples[-1][0] - samples[0][0]
        if dt < 0.05:
            return 0.0
        return (samples[-1][1] - samples[0][1]) / dt


def _impulse_live(tick: Tick, atr_now: float, vel_atr: float, rel_vol: float) -> float:
    """Intrabar impulse proxy. Uses forming range so far, not a closed candle."""
    fo = float(tick.forming_open or tick.price)
    fh = float(tick.forming_high or tick.price)
    fl = float(tick.forming_low or tick.price)
    span = max(fh - fl, 1e-9)
    body = abs(float(tick.price) - fo)
    body_pct = min(1.0, body / span)
    range_atr = span / max(atr_now, 1e-9)
    expand = min(100.0, (range_atr / 1.6) * 55.0)
    body_s = min(100.0, body_pct / 0.55 * 50.0)
    vel_s = min(100.0, abs(vel_atr) * 35.0)
    vol_s = min(100.0, 40.0 + 40.0 * min(max(rel_vol, 0.0) / 1.4, 1.5))
    score = 0.35 * expand + 0.30 * body_s + 0.20 * vel_s + 0.15 * vol_s
    return float(max(0.0, min(100.0, score)))
