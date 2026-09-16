"""Extension / chase-risk 0–100.

Measures THIS impulse's displacement — not session-long distance from VWAP.
When ENABLE_EXHAUSTION_FILTER is on, blends VWAP/RSI/BB/Stoch chase score so tip
entries into extreme OB/OS show elevated extension risk on the HUD.
"""

from __future__ import annotations

from .config import Mark2Config
from .exhaustion import blend_extension_with_exhaustion, read_exhaustion
from .types import EventRecord, MarketSnapshot, ScoreBundle, Side


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


class ExtensionFilter:
    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg
        self.last_exhaustion = None

    def update(
        self,
        snap: MarketSnapshot,
        scores: ScoreBundle,
        *,
        event: EventRecord | None = None,
    ) -> ScoreBundle:
        start = float(event.started_price) if event and event.started_price else 0.0
        impulse_long = self._risk(
            snap, Side.LONG, start if event and event.direction == Side.LONG else 0.0
        )
        impulse_short = self._risk(
            snap, Side.SHORT, start if event and event.direction == Side.SHORT else 0.0
        )

        exh = read_exhaustion(snap, self.cfg)
        self.last_exhaustion = exh
        scores.contributors["exhaustion"] = {
            "rsi": exh.rsi,
            "stochRsi": exh.stoch_rsi,
            "bbPctB": exh.bb_pct_b,
            "vwapSigma": exh.vwap_sigma,
            "williamsR": exh.williams_r,
            "cci": exh.cci,
            "extensionLong": round(exh.extension_long, 1),
            "extensionShort": round(exh.extension_short, 1),
            "momentumHealth": round(exh.momentum_health, 1),
            "macd": exh.macd,
            "macdSignal": exh.macd_signal,
            "macdHist": exh.macd_hist,
            "macdHistDelta": exh.macd_hist_delta,
            "macdCross": exh.macd_cross,
            "macdDiv": exh.macd_div,
            "longChase": round(exh.long_chase, 1),
            "shortChase": round(exh.short_chase, 1),
            "extremeOb": exh.extreme_ob,
            "extremeOs": exh.extreme_os,
        }

        if bool(getattr(self.cfg, "ENABLE_EXHAUSTION_FILTER", True)):
            scores.extension_risk_long = blend_extension_with_exhaustion(
                impulse_long, exh.long_chase
            )
            scores.extension_risk_short = blend_extension_with_exhaustion(
                impulse_short, exh.short_chase
            )
        else:
            scores.extension_risk_long = impulse_long
            scores.extension_risk_short = impulse_short
        return scores

    def _risk(self, snap: MarketSnapshot, side: Side, start_px: float) -> float:
        atr = max(snap.atr, self.cfg.TICK_SIZE)
        form = snap.forming_bar or {}
        origin = start_px
        if origin <= 0:
            origin = float(form.get("open") or snap.price)

        if side == Side.LONG:
            impulse_atr = max(0.0, (snap.price - origin) / atr)
        else:
            impulse_atr = max(0.0, (origin - snap.price) / atr)

        span = 0.0
        if form:
            span = max(0.0, float(form.get("high") or 0) - float(form.get("low") or 0))
        bar_atr = span / atr if atr > 0 else 0.0

        signed_vel = snap.velocity if side == Side.LONG else -snap.velocity
        signed_acc = snap.acceleration if side == Side.LONG else -snap.acceleration
        exhaust = 0.0
        if impulse_atr >= 0.45 and signed_vel > 0 and signed_acc < 0:
            exhaust = min(1.0, abs(signed_acc) / max(atr * 0.15, 0.5))

        if side == Side.LONG:
            vwap_dir = max(0.0, snap.vwap_distance_atr)
        else:
            vwap_dir = max(0.0, -snap.vwap_distance_atr)

        risk = (
            48.0 * min(1.6, impulse_atr)
            + 18.0 * min(1.4, bar_atr)
            + 14.0 * exhaust
            + 8.0 * min(2.0, vwap_dir)
        )
        return _clamp(risk)

    def blocks(self, side: Side, scores: ScoreBundle, *, max_risk: float | None = None) -> bool:
        risk = (
            scores.extension_risk_long if side == Side.LONG else scores.extension_risk_short
        )
        limit = float(max_risk if max_risk is not None else self.cfg.MAX_EXTENSION_RISK)
        return risk >= limit
