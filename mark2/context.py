"""Slow-changing Recon Sniper context. Own trend/regime — not TradeChampion HTF."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .config import Mark2Config
from .indicators import (
    aggregate_5m,
    atr,
    atr_regime,
    directional_efficiency,
    ema,
    swing_pivots,
    volume_ratio,
    vwap,
)
from .types import MarketSnapshot, Tick


def session_and_hour(ts: float) -> tuple[str, int]:
    try:
        dt = datetime.fromtimestamp(ts, ZoneInfo("America/New_York"))
    except Exception:
        dt = datetime.fromtimestamp(ts, timezone.utc)
        return "UNKNOWN", dt.hour
    h = dt.hour + dt.minute / 60.0
    if 9.5 <= h < 11.5:
        return "NY_OPEN", dt.hour
    if 11.5 <= h < 14.0:
        return "NY_MID", dt.hour
    if 14.0 <= h < 16.0:
        return "NY_POWER", dt.hour
    if 4.0 <= h < 9.5:
        return "PREMARKET", dt.hour
    if 18.0 <= h or h < 4.0:
        return "ASIA_OVERNIGHT", dt.hour
    return "AFTER_HOURS", dt.hour


def _recent_structure(bars: list[dict], *, lookback: int = 10) -> str | None:
    """Impulse-sensitive structure from recent bars — no pivot confirmation lag."""
    if len(bars) < lookback:
        return None
    seg = bars[-lookback:]
    q = max(2, lookback // 3)
    early = seg[:q]
    late = seg[-q:]
    early_h = sum(float(b["high"]) for b in early) / len(early)
    late_h = sum(float(b["high"]) for b in late) / len(late)
    early_l = sum(float(b["low"]) for b in early) / len(early)
    late_l = sum(float(b["low"]) for b in late) / len(late)
    hh = late_h > early_h
    lh = late_h < early_h
    hl = late_l > early_l
    ll = late_l < early_l
    if hh and hl:
        return "HH_HL"
    if lh and ll:
        return "LH_LL"
    if hh:
        return "HH"
    if ll:
        return "LL"
    return "MIXED"


def structure_state(bars: list[dict]) -> tuple[str, float, float]:
    highs, lows = swing_pivots(bars, strength=1)
    hh = hl = lh = ll = False
    if len(highs) >= 2:
        hh = highs[-1] > highs[-2]
        lh = highs[-1] < highs[-2]
    if len(lows) >= 2:
        hl = lows[-1] > lows[-2]
        ll = lows[-1] < lows[-2]
    if hh and hl:
        state = "HH_HL"
    elif lh and ll:
        state = "LH_LL"
    elif hh:
        state = "HH"
    elif ll:
        state = "LL"
    else:
        state = "MIXED"
    recent = _recent_structure(bars)
    if recent in ("HH_HL", "LH_LL") and state in ("HH_HL", "LH_LL") and recent != state:
        state = recent
    return (
        state,
        float(highs[-1]) if highs else 0.0,
        float(lows[-1]) if lows else 0.0,
    )


def classify_trend(bars_1m: list[dict], *, ema_period: int, atr_period: int) -> dict[str, Any]:
    """Recon Sniper trend: 5m when enough complete groups exist, else 1m."""
    bars5 = aggregate_5m(bars_1m)
    use = bars5 if len(bars5) >= 8 else list(bars_1m)
    if len(use) < 8:
        return {
            "bias": "NEUTRAL",
            "regime": "QUIET",
            "strength": 0.0,
            "longs": False,
            "shorts": False,
            "ema": 0.0,
            "atr": 0.0,
            "support": None,
            "resistance": None,
        }
    closes = [float(b["close"]) for b in use]
    emas = ema(closes, ema_period)
    atrs = atr(use, atr_period)
    ema_now = float(emas[-1])
    atr_now = float(atrs[-1]) if atrs else 0.0
    slope_n = min(3, max(1, len(emas) // 4))
    slope = ema_now - float(emas[-(1 + slope_n)])
    price = closes[-1]
    if price > ema_now and slope > 0:
        bias = "BULLISH"
    elif price < ema_now and slope < 0:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    eff = directional_efficiency(use, min(8, len(use) - 1))
    if atr_now < 2.0:
        regime = "QUIET"
    elif atr_now >= 40.0:
        regime = "CHAOTIC"
    elif eff < 0.22:
        regime = "CHOPPY"
    elif atr_now > 18.0:
        regime = "HIGH_VOL"
    else:
        regime = "TRENDING"
    strength = min(100.0, max(0.0, abs(slope) / max(atr_now, 0.25) * 80.0 + eff * 40.0))
    sit_out = regime in ("QUIET", "CHAOTIC", "CHOPPY")
    tradeable = regime in ("TRENDING", "HIGH_VOL")
    longs = (not sit_out) and tradeable and bias == "BULLISH"
    shorts = (not sit_out) and tradeable and bias == "BEARISH"
    highs, lows = swing_pivots(use, strength=1)
    support = float(lows[-1]) if lows else None
    resistance = float(highs[-1]) if highs else None
    return {
        "bias": bias,
        "regime": regime,
        "strength": strength,
        "longs": longs,
        "shorts": shorts,
        "ema": ema_now,
        "atr": atr_now,
        "support": support,
        "resistance": resistance,
    }


class MarketContext:
    """Slow context. Recalc on bar close / throttle — never every tick's expensive path."""

    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg
        self._last_refresh_ts = 0.0
        self._cache: dict[str, Any] = {}

    @property
    def last_atr(self) -> float:
        return float(self._cache.get("atr") or 0.0)

    def on_bar_close(self, completed_bars: list[dict], ts: float) -> None:
        self._refresh(completed_bars, ts, force=True)

    def snapshot(
        self,
        tick: Tick,
        completed_bars: list[dict],
        forming_bar: Optional[dict],
        fast: dict[str, float],
    ) -> MarketSnapshot:
        if tick.ts - self._last_refresh_ts >= float(self.cfg.CONTEXT_REFRESH_SEC):
            self._refresh(completed_bars, tick.ts, force=False)
        elif not self._cache:
            self._refresh(completed_bars, tick.ts, force=True)
        c = self._cache
        atr_v = float(c.get("atr") or 0.0)
        ema_v = float(c.get("ema") or 0.0)
        vw = float(c.get("vwap") or 0.0)
        px = float(tick.price)
        vwap_d = ((px - vw) / atr_v) if atr_v > 1e-9 and vw > 0 else 0.0
        ema_d = ((px - ema_v) / atr_v) if atr_v > 1e-9 and ema_v > 0 else 0.0
        session, hour = session_and_hour(tick.ts)
        return MarketSnapshot(
            ts=tick.ts,
            price=px,
            completed_bars=completed_bars,
            forming_bar=forming_bar,
            atr=atr_v,
            ema=ema_v,
            vwap=vw,
            volume=float(fast.get("volume") or tick.forming_volume or tick.volume),
            relative_volume=float(fast.get("relative_volume") or c.get("relative_volume") or 0.0),
            volume_acceleration=float(fast.get("volume_acceleration") or 0.0),
            velocity=float(fast.get("velocity") or 0.0),
            acceleration=float(fast.get("acceleration") or 0.0),
            impulse_score=float(fast.get("impulse_score") or 0.0),
            trend_bias=str(c.get("bias") or "NEUTRAL"),
            trend_regime=str(c.get("regime") or "QUIET"),
            trend_strength=float(c.get("strength") or 0.0),
            longs_allowed=bool(c.get("longs")),
            shorts_allowed=bool(c.get("shorts")),
            nearest_support=c.get("support"),
            nearest_resistance=c.get("resistance"),
            session=session,
            hour_et=hour,
            structure_state=str(c.get("structure_state") or "MIXED"),
            volatility_state=str(c.get("volatility_state") or "stable"),
            vwap_distance_atr=vwap_d,
            ema_distance_atr=ema_d,
            swing_high=float(c.get("swing_high") or 0.0),
            swing_low=float(c.get("swing_low") or 0.0),
        )

    def _refresh(self, completed_bars: list[dict], ts: float, *, force: bool) -> None:
        if not force and self._cache and ts - self._last_refresh_ts < 0.5:
            return
        self._last_refresh_ts = ts
        if len(completed_bars) < 8:
            self._cache = {}
            return
        trend = classify_trend(
            completed_bars,
            ema_period=self.cfg.EMA_PERIOD,
            atr_period=self.cfg.ATR_PERIOD,
        )
        atrs = atr(completed_bars, self.cfg.ATR_PERIOD)
        _ref, _avg, rel = volume_ratio(completed_bars, lookback=self.cfg.VOLUME_LOOKBACK)
        struct, sh, sl = structure_state(completed_bars)
        self._cache = {
            **trend,
            "vwap": vwap(completed_bars, self.cfg.VWAP_LOOKBACK),
            "relative_volume": rel,
            "structure_state": struct,
            "volatility_state": atr_regime(atrs, lookback=self.cfg.ATR_PERIOD),
            "swing_high": sh,
            "swing_low": sl,
            "atr": trend["atr"] or (float(atrs[-1]) if atrs else 0.0),
            "ema": trend["ema"],
        }
