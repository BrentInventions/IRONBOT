"""8TCM — 8-EMA Trend Continuation Model.

Independent of EMA9/20/50 sniper, 413, and scout.

FIND STRUCTURE TREND → RETRACE TO EMA8 → TEST → REJECT → CONTINUE
→ PRIMARY TARGET AT NEXT KEY LEVEL → optional Recon runner after that.

1H/4H are context only. They are not a mandatory AND-gate.
Baseline numbers are Recon's software translation, not Ameer's published figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .config import Mark2Config
from .indicators import atr, ema
from .momentum_barriers import (
    BarrierBook,
    SWING_HIGH,
    SWING_LOW,
    get_next_momentum_barrier,
    parse_bar_dt,
)
from .types import Side

TREND_BULLISH = "BULLISH"
TREND_BEARISH = "BEARISH"
TREND_RANGING = "RANGING"
TREND_UNCLEAR = "UNCLEAR"
TREND_TRENDING = "TRENDING"

ST_WAITING_FOR_TREND = "WAITING_FOR_TREND"
ST_TREND_CONFIRMED = "TREND_CONFIRMED"
ST_WAITING_FOR_RETRACEMENT = "WAITING_FOR_RETRACEMENT"
ST_EMA8_TESTING = "EMA8_TESTING"
ST_WAITING_FOR_REJECTION = "WAITING_FOR_REJECTION"
ST_EMA8_REJECTION_CONFIRMED = "EMA8_REJECTION_CONFIRMED"
ST_READY_TO_EXECUTE = "READY_TO_EXECUTE"
ST_TRADE_ACTIVE = "TRADE_ACTIVE"
ST_TARGET_REACHED = "TARGET_REACHED"
ST_RUNNER_ACTIVE = "RUNNER_ACTIVE"
ST_TRADE_COMPLETE = "TRADE_COMPLETE"
# Legacy aliases so old logs/tests still import.
ST_WAITING_FOR_PULLBACK = ST_WAITING_FOR_RETRACEMENT
ST_PULLBACK_AT_EMA = ST_EMA8_TESTING
ST_REJECTION_CONFIRMED = ST_EMA8_REJECTION_CONFIRMED

REJ_NO_CLEAR_TREND = "REJECT_NO_CLEAR_TREND"
REJ_BEARISH_STRUCT = "REJECT_BEARISH_STRUCTURE_NOT_CONFIRMED"
REJ_BULLISH_STRUCT = "REJECT_BULLISH_STRUCTURE_NOT_CONFIRMED"
REJ_RANGE = "REJECT_MARKET_RANGING"
REJ_NO_RETRACEMENT = "REJECT_NO_RETRACEMENT"
REJ_EMA8_NOT_TESTED = "REJECT_EMA8_NOT_TESTED"
REJ_EMA8_REJECTION = "REJECT_EMA8_REJECTION_NOT_CONFIRMED"
REJ_WRONG_SIDE = "REJECT_CANDLE_WRONG_SIDE_EMA8"
REJ_CHASE = "REJECT_CHASE"
REJ_BARRIER = "REJECT_NEAR_KEY_LEVEL"
REJ_TARGET_R = "REJECT_INSUFFICIENT_TARGET_R"
REJ_STOP = "REJECT_INVALID_STOP"
REJ_ARMED = "REJECT_NOT_ARMED"
REJ_BRIDGE = "REJECT_BRIDGE_DISCONNECTED"
REJ_COOLDOWN = "REJECT_COOLDOWN"
REJ_SIDE = "REJECT_8TCM_SIDE_OFF"
REJ_EARLY = "REJECT_EARLY_ENTRY_DISABLED"
# Legacy aliases
REJ_HTF = REJ_NO_CLEAR_TREND
REJ_NO_PULLBACK = REJ_NO_RETRACEMENT
REJ_NO_REJECTION = REJ_EMA8_REJECTION
REJ_STRUCTURE = REJ_EMA8_NOT_TESTED

PIN_BAR = "PIN_BAR"
STRONG_WICK = "STRONG_WICK_REJECTION"
ENGULFING = "ENGULFING"
EMA8_CLOSE_REJECT = "EMA8_CLOSE_REJECT"

ENTRY_LONG = "8TCM_LONG"
ENTRY_SHORT = "8TCM_SHORT"
ENTRY_LONG_REASON = "8TCM_LONG_EMA8_REJECTION"
ENTRY_SHORT_REASON = "8TCM_SHORT_EMA8_REJECTION"
EXIT_KEY_LEVEL = "8TCM_KEY_LEVEL_TARGET"
RUNNER_ARM = "8TCM_RUNNER_ARM"
DOLLAR_ARM = "8TCM_DOLLAR_ARM"
EXIT_RUNNER_TRAIL = "8TCM_RUNNER_TRAIL"
EXIT_GREEN_BANK = "8TCM_GREEN_BANK"
GRADE_A = "A_SETUP"
GRADE_B = "B_SETUP"
GRADE_C = "C_SETUP"
GRADE_A_PLUS_ROOM = "A_PLUS_ROOM"
GRADE_LOWER = "VALID_BUT_LOWER_QUALITY"

_BARRIER_KIND = {
    SWING_HIGH: "CONFIRMED_SWING_HIGH",
    SWING_LOW: "CONFIRMED_SWING_LOW",
}


def tcm8_enabled(cfg: Mark2Config | None) -> bool:
    return bool(cfg is not None and getattr(cfg, "ENABLE_8TCM", False))


def ema_92050_live(cfg: Mark2Config | None) -> bool:
    """True when the EMA 9/20/50 path can still take entries."""
    if cfg is None or not bool(getattr(cfg, "ENABLE_EMA_STRATEGY", False)):
        return False
    return bool(
        getattr(cfg, "EMA_LONG_SNIPER", True)
        or getattr(cfg, "EMA_SHORT_SNIPER", True)
        or getattr(cfg, "EMA_LEFTOVER_LONG", False)
    )


def tcm8_only_mode(cfg: Mark2Config | None) -> bool:
    """True only when 8TCM is on and the EMA 9/20/50 path is off."""
    return tcm8_enabled(cfg) and not ema_92050_live(cfg)


def uses_tcm8_hold(trade) -> bool:
    """8TCM entries and EMA 9/20/50 fills that inherit the 8TCM trail/exit."""
    if trade is None:
        return False
    return bool(getattr(trade, "tcm8", False) or getattr(trade, "tcm8_hold", False))


def barrier_kind_label(kind: str) -> str:
    return _BARRIER_KIND.get(str(kind or ""), str(kind or ""))


def _f(cfg: Mark2Config | None, name: str, default: float) -> float:
    if cfg is None:
        return float(default)
    raw = getattr(cfg, name, default)
    return float(default if raw is None else raw)


def _i(cfg: Mark2Config | None, name: str, default: int) -> int:
    if cfg is None:
        return int(default)
    return int(getattr(cfg, name, default) or default)


def _b(cfg: Mark2Config | None, name: str, default: bool) -> bool:
    if cfg is None:
        return bool(default)
    return bool(getattr(cfg, name, default))


def _tick(cfg: Mark2Config | None) -> float:
    return max(_f(cfg, "TICK_SIZE", 0.25), 0.01)


def _period(cfg: Mark2Config | None) -> int:
    return max(1, _i(cfg, "TCM8_EMA_PERIOD", 8))


@dataclass
class Tcm8Candle:
    open: float
    high: float
    low: float
    close: float
    body: float
    upper_wick: float
    lower_wick: float
    bullish: bool
    bearish: bool

    @property
    def wick_body_ratio_lower(self) -> float:
        return self.lower_wick / max(self.body, 1e-9)

    @property
    def wick_body_ratio_upper(self) -> float:
        return self.upper_wick / max(self.body, 1e-9)


def candle_metrics(bar: dict) -> Tcm8Candle:
    o = float(bar.get("open") or 0)
    h = float(bar.get("high") or 0)
    l = float(bar.get("low") or 0)
    c = float(bar.get("close") or 0)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return Tcm8Candle(
        open=o,
        high=h,
        low=l,
        close=c,
        body=max(0.0, body),
        upper_wick=max(0.0, upper),
        lower_wick=max(0.0, lower),
        bullish=c > o,
        bearish=c < o,
    )


def last_atr(bars: list[dict], period: int = 14) -> float:
    xs = atr(bars, period)
    return float(xs[-1]) if xs else 0.0


def last_ema(bars: list[dict], period: int) -> float:
    closes = [float(b.get("close") or 0) for b in bars]
    xs = ema(closes, period)
    return float(xs[-1]) if xs else 0.0


def ema_series(bars: list[dict], period: int) -> list[float]:
    closes = [float(b.get("close") or 0) for b in bars]
    return ema(closes, period)


def aggregate_timeframe(bars_1m: list[dict], minutes: int) -> list[dict]:
    """Build HTF OHLC from 1-minute bars. Session-agnostic clock buckets."""
    if minutes <= 1 or not bars_1m:
        return list(bars_1m)
    buckets: dict[str, dict] = {}
    order: list[str] = []
    for bar in bars_1m:
        dt = parse_bar_dt(bar)
        if dt is None:
            continue
        minute = (dt.minute // minutes) * minutes if minutes < 60 else 0
        if minutes >= 60:
            hour_block = (dt.hour // (minutes // 60)) * (minutes // 60)
            key_dt = dt.replace(minute=0, second=0, microsecond=0)
            if minutes >= 240:
                block = (dt.hour // 4) * 4
                key_dt = dt.replace(hour=block, minute=0, second=0, microsecond=0)
            else:
                key_dt = dt.replace(hour=hour_block, minute=0, second=0, microsecond=0)
            key = key_dt.isoformat()
        else:
            key_dt = dt.replace(minute=minute, second=0, microsecond=0)
            key = key_dt.isoformat()
        o = float(bar.get("open") or 0)
        h = float(bar.get("high") or 0)
        l = float(bar.get("low") or 0)
        c = float(bar.get("close") or 0)
        v = float(bar.get("volume") or 0)
        if key not in buckets:
            buckets[key] = {
                "time": key,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
            order.append(key)
        else:
            row = buckets[key]
            row["high"] = max(row["high"], h)
            row["low"] = min(row["low"], l) if row["low"] > 0 else l
            row["close"] = c
            row["volume"] += v
    return [buckets[k] for k in order]


def _htf_bucket(dt: datetime, minutes: int) -> datetime:
    minutes = int(minutes)
    if minutes >= 240:
        block = (dt.hour // 4) * 4
        return dt.replace(hour=block, minute=0, second=0, microsecond=0)
    if minutes >= 60:
        step = max(1, minutes // 60)
        hour_block = (dt.hour // step) * step
        return dt.replace(hour=hour_block, minute=0, second=0, microsecond=0)
    snap = (dt.minute // minutes) * minutes
    return dt.replace(minute=snap, second=0, microsecond=0)


def overlay_forming_htf(
    completed: list[dict],
    bars_1m: list[dict],
    minutes: int,
) -> list[dict]:
    """Keep native 1H/4H history, but let the current bucket follow the live 1m tape.

    NinjaTrader only sends a 1H/4H bar after that candle closes. Without this,
    a selloff inside the hour never updates HTF close.
    """
    agg = aggregate_timeframe(bars_1m, int(minutes))
    if not agg:
        return list(completed)
    if not completed:
        return list(agg)
    live = dict(agg[-1])
    live_dt = parse_bar_dt(live)
    last_dt = parse_bar_dt(completed[-1])
    out = list(completed)
    if live_dt is None or last_dt is None:
        out.append(live)
        return out
    live_b = _htf_bucket(live_dt, int(minutes))
    last_b = _htf_bucket(last_dt, int(minutes))
    if live_b == last_b:
        out[-1] = live
    elif live_b > last_b:
        out.append(live)
    return out


def classify_htf_trend(bars: list[dict], cfg: Mark2Config | None) -> dict[str, Any]:
    """Transparent baseline: price vs EMA8, slope/ATR, recent highs/lows."""
    period = _period(cfg)
    lookback = max(1, _i(cfg, "TCM8_TREND_SLOPE_LOOKBACK", 5))
    min_slope = _f(cfg, "TCM8_MIN_TREND_SLOPE_ATR", 0.05)
    need = period + lookback + 2
    empty = {
        "state": TREND_UNCLEAR,
        "ema8": 0.0,
        "slope": 0.0,
        "slope_atr": 0.0,
        "atr": 0.0,
        "close": 0.0,
        "why": "INSUFFICIENT_HTF_BARS",
        "bars": len(bars),
        "need": need,
    }
    if len(bars) < need:
        return empty
    series = ema_series(bars, period)
    atr_v = max(last_atr(bars), _tick(cfg))
    ema_now = float(series[-1])
    ema_prev = float(series[-1 - lookback])
    slope = ema_now - ema_prev
    slope_atr = slope / atr_v
    close = float(bars[-1].get("close") or 0)
    hi_now = max(float(b.get("high") or 0) for b in bars[-lookback:])
    hi_prior = max(float(b.get("high") or 0) for b in bars[-2 * lookback : -lookback])
    lo_now = min(float(b.get("low") or 0) for b in bars[-lookback:])
    lo_prior = min(float(b.get("low") or 0) for b in bars[-2 * lookback : -lookback])
    hh = hi_now > hi_prior
    hl = lo_now > lo_prior
    lh = hi_now < hi_prior
    ll = lo_now < lo_prior
    above = close > ema_now
    below = close < ema_now
    why_parts = [
        f"close={close:.2f}",
        f"ema8={ema_now:.2f}",
        f"slope_atr={slope_atr:.4f}",
        f"hh={hh}",
        f"hl={hl}",
        f"lh={lh}",
        f"ll={ll}",
    ]
    if abs(slope_atr) < min_slope and not (hh and hl) and not (lh and ll):
        state = TREND_RANGING
        why_parts.append("FLAT_SLOPE_NO_STRUCTURE")
    elif slope_atr >= min_slope and above and not (lh and ll):
        state = TREND_BULLISH
        why_parts.append("ABOVE_EMA8_POS_SLOPE")
    elif slope_atr <= -min_slope and below and not (hh and hl):
        state = TREND_BEARISH
        why_parts.append("BELOW_EMA8_NEG_SLOPE")
    elif abs(slope_atr) < min_slope:
        state = TREND_RANGING
        why_parts.append("FLAT_SLOPE")
    else:
        state = TREND_UNCLEAR
        why_parts.append("MIXED_PRICE_SLOPE_STRUCTURE")
    return {
        "state": state,
        "ema8": round(ema_now, 4),
        "slope": round(slope, 4),
        "slope_atr": round(slope_atr, 5),
        "atr": round(atr_v, 4),
        "close": round(close, 4),
        "why": " ".join(why_parts),
        "bars": len(bars),
        "need": need,
    }


def is_market_ranging(bars_1m: list[dict], cfg: Mark2Config | None) -> dict[str, Any]:
    """1-minute chop filter. Explainable, few inputs."""
    lookback = max(3, _i(cfg, "TCM8_CONSOLIDATION_LOOKBACK", 10))
    max_range_atr = _f(cfg, "TCM8_CONSOLIDATION_MAX_RANGE_ATR", 1.00)
    min_slope = _f(cfg, "TCM8_MIN_TREND_SLOPE_ATR", 0.05)
    period = _period(cfg)
    if len(bars_1m) < lookback + 2:
        return {"state": TREND_UNCLEAR, "why": "INSUFFICIENT_1M_BARS"}
    window = bars_1m[-lookback:]
    atr_v = max(last_atr(bars_1m), _tick(cfg))
    hi = max(float(b.get("high") or 0) for b in window)
    lo = min(float(b.get("low") or 0) for b in window)
    rng = hi - lo
    series = ema_series(bars_1m, period)
    slope_lb = min(len(series) - 1, max(1, _i(cfg, "TCM8_TREND_SLOPE_LOOKBACK", 5)))
    slope_atr = (series[-1] - series[-1 - slope_lb]) / atr_v
    ema_now = series[-1]
    crosses = 0
    for i in range(1, len(window)):
        prev_c = float(window[i - 1].get("close") or 0)
        cur_c = float(window[i].get("close") or 0)
        if (prev_c - ema_now) * (cur_c - ema_now) < 0:
            crosses += 1
    overlaps = 0
    for i in range(1, len(window)):
        a = window[i - 1]
        b = window[i]
        ah, al = float(a.get("high") or 0), float(a.get("low") or 0)
        bh, bl = float(b.get("high") or 0), float(b.get("low") or 0)
        overlap = min(ah, bh) - max(al, bl)
        smaller = min(ah - al, bh - bl)
        if smaller > 0 and overlap >= 0.5 * smaller:
            overlaps += 1
    why = (
        f"range_atr={rng / atr_v:.3f} slope_atr={slope_atr:.4f} "
        f"crosses={crosses} overlaps={overlaps}"
    )
    if rng <= max_range_atr * atr_v:
        return {"state": TREND_RANGING, "why": "TIGHT_RANGE " + why}
    # Crosses / overlaps / a flat 1m EMA8 during a pullback are notes, not a veto.
    # A healthy retracement into EMA8 is not a range.
    return {"state": TREND_TRENDING, "why": why}


def confirmed_swings(bars: list[dict], strength: int = 2) -> tuple[list[dict], list[dict]]:
    """Confirmed swing highs/lows. Pivot at i is usable only after `strength` bars close after it."""
    s = max(1, int(strength))
    highs: list[dict] = []
    lows: list[dict] = []
    n = len(bars)
    if n < s * 2 + 1:
        return highs, lows
    for i in range(s, n - s):
        h = float(bars[i].get("high") or 0)
        lo = float(bars[i].get("low") or 0)
        if all(
            h > float(bars[i - j].get("high") or 0) and h > float(bars[i + j].get("high") or 0)
            for j in range(1, s + 1)
        ):
            highs.append({"index": i, "price": h, "time": str(bars[i].get("time") or "")})
        if all(
            lo < float(bars[i - j].get("low") or 0) and lo < float(bars[i + j].get("low") or 0)
            for j in range(1, s + 1)
        ):
            lows.append({"index": i, "price": lo, "time": str(bars[i].get("time") or "")})
    return highs, lows


def _compress_pivots(pivots: list[dict], min_move: float, *, keep: str) -> list[dict]:
    """Drop 1m noise: cluster swings closer than min_move. Keep the extreme of the cluster."""
    if not pivots:
        return []
    out = [dict(pivots[0])]
    floor = max(float(min_move), 1e-9)
    for p in pivots[1:]:
        if abs(float(p["price"]) - float(out[-1]["price"])) < floor:
            if keep == "high" and float(p["price"]) >= float(out[-1]["price"]):
                out[-1] = dict(p)
            elif keep == "low" and float(p["price"]) <= float(out[-1]["price"]):
                out[-1] = dict(p)
            continue
        out.append(dict(p))
    return out


def classify_8tcm_trend(bars: list[dict], cfg: Mark2Config | None) -> dict[str, Any]:
    """Current trend from confirmed structure. EMA8 slope supports, does not define."""
    period = _period(cfg)
    strength = max(1, _i(cfg, "TCM8_SWING_STRENGTH", 2))
    lookback = max(1, _i(cfg, "TCM8_TREND_SLOPE_LOOKBACK", 5))
    empty = {
        "state": TREND_UNCLEAR,
        "why": "INSUFFICIENT_SWINGS",
        "sequence": "",
        "swing_high": 0.0,
        "swing_low": 0.0,
        "prior_high": 0.0,
        "prior_low": 0.0,
        "hh": False,
        "hl": False,
        "lh": False,
        "ll": False,
        "ema8": 0.0,
        "slope_atr": 0.0,
        "close": 0.0,
        "swings": "",
        "source": "",
    }
    if len(bars) < period + strength * 2 + 2:
        return empty
    highs, lows = confirmed_swings(bars, strength)
    atr_v = max(last_atr(bars), _tick(cfg))
    min_move = max(_tick(cfg), _f(cfg, "TCM8_PULLBACK_MAX_DISTANCE_ATR", 0.15) * atr_v)
    highs = _compress_pivots(highs, min_move, keep="high")
    lows = _compress_pivots(lows, min_move, keep="low")
    ema8 = last_ema(bars, period)
    series = ema_series(bars, period)
    slope_lb = min(len(series) - 1, lookback)
    slope_atr = (series[-1] - series[-1 - slope_lb]) / max(atr_v, 1e-9)
    close = float(bars[-1].get("close") or 0)
    out = dict(empty)
    out["ema8"] = round(ema8, 4)
    out["slope_atr"] = round(slope_atr, 5)
    out["close"] = round(close, 4)
    if len(highs) < 2 or len(lows) < 2:
        out["why"] = f"NEED_2_HIGHS_AND_2_LOWS h={len(highs)} l={len(lows)}"
        return out
    sh, psh = highs[-1], highs[-2]
    sl, psl = lows[-1], lows[-2]
    hh = sh["price"] > psh["price"]
    hl = sl["price"] > psl["price"]
    lh = sh["price"] < psh["price"]
    ll = sl["price"] < psl["price"]
    out.update(
        {
            "swing_high": round(sh["price"], 2),
            "swing_low": round(sl["price"], 2),
            "prior_high": round(psh["price"], 2),
            "prior_low": round(psl["price"], 2),
            "hh": hh,
            "hl": hl,
            "lh": lh,
            "ll": ll,
            "swings": (
                f"SWING HIGH: {psh['price']:.2f}  SWING LOW: {psl['price']:.2f}  "
                f"{'LOWER HIGH' if lh else 'HIGHER HIGH'}: {sh['price']:.2f}  "
                f"{'LOWER LOW' if ll else 'HIGHER LOW'}: {sl['price']:.2f}"
            ),
        }
    )
    if hh and hl:
        out["state"] = TREND_BULLISH
        out["sequence"] = "HIGHER_HIGH -> HIGHER_LOW"
        out["why"] = "CONFIRMED_HH_HL"
    elif lh and ll:
        out["state"] = TREND_BEARISH
        out["sequence"] = "LOWER_HIGH -> LOWER_LOW"
        out["why"] = "CONFIRMED_LH_LL"
    else:
        out["state"] = TREND_UNCLEAR
        out["sequence"] = "MIXED"
        out["why"] = f"MIXED_SWINGS hh={hh} hl={hl} lh={lh} ll={ll}"
    return out


def resolve_8tcm_trend(
    bars_1m: list[dict],
    bars_1h: list[dict],
    cfg: Mark2Config | None,
) -> dict[str, Any]:
    """Clear current trend. 1m significant structure first, then 1H. 4H never vetoes."""
    m1 = classify_8tcm_trend(bars_1m, cfg)
    if m1["state"] in (TREND_BULLISH, TREND_BEARISH):
        m1["source"] = "1M_STRUCTURE"
        return m1
    h1s = classify_8tcm_trend(bars_1h, cfg) if bars_1h else None
    if h1s is not None and h1s["state"] in (TREND_BULLISH, TREND_BEARISH):
        out = dict(m1)
        out["state"] = h1s["state"]
        out["sequence"] = h1s.get("sequence") or m1.get("sequence") or ""
        out["why"] = "1H_STRUCTURE " + str(h1s.get("why") or "")
        out["source"] = "1H_STRUCTURE"
        out["hh"] = bool(h1s.get("hh"))
        out["hl"] = bool(h1s.get("hl"))
        out["lh"] = bool(h1s.get("lh"))
        out["ll"] = bool(h1s.get("ll"))
        if h1s.get("swings"):
            out["swings"] = "1H " + str(h1s.get("swings"))
        return out
    h1e = classify_htf_trend(bars_1h, cfg) if bars_1h else {"state": TREND_UNCLEAR, "why": ""}
    if h1e.get("state") in (TREND_BULLISH, TREND_BEARISH):
        out = dict(m1)
        out["state"] = h1e["state"]
        out["sequence"] = "1H EMA8 " + str(h1e["state"])
        out["why"] = "1H_EMA8 " + str(h1e.get("why") or "")
        out["source"] = "1H_EMA8"
        return out
    m1["source"] = "NONE"
    return m1


def ema8_is_tested(side: Side, bar: dict, ema8: float, atr_v: float, cfg: Mark2Config | None) -> bool:
    """Near / wick touch / through / body overlap. Not tick-perfect."""
    touch = _f(cfg, "TCM8_EMA_TOUCH_TOLERANCE_ATR", 0.10) * max(atr_v, _tick(cfg))
    hi = float(bar.get("high") or 0)
    lo = float(bar.get("low") or 0)
    o = float(bar.get("open") or 0)
    c = float(bar.get("close") or 0)
    body_lo, body_hi = min(o, c), max(o, c)
    if lo - touch <= ema8 <= hi + touch:
        return True
    if body_lo <= ema8 <= body_hi:
        return True
    probe = lo if side == Side.LONG else hi
    return abs(probe - ema8) <= touch


def classify_rejection(
    bar: dict,
    prev: dict | None,
    side: Side,
    atr_v: float,
    cfg: Mark2Config | None,
) -> dict[str, Any]:
    c = candle_metrics(bar)
    min_body = _f(cfg, "TCM8_MIN_REJECTION_BODY_ATR", 0.15) * max(atr_v, _tick(cfg))
    pin_r = _f(cfg, "TCM8_PIN_BAR_WICK_BODY_RATIO", 2.00)
    strong_r = _f(cfg, "TCM8_STRONG_WICK_BODY_RATIO", 1.50)
    body_atr = c.body / max(atr_v, _tick(cfg))
    out = {
        "type": "",
        "body": round(c.body, 4),
        "body_atr": round(body_atr, 4),
        "upper_wick": round(c.upper_wick, 4),
        "lower_wick": round(c.lower_wick, 4),
        "wick_body_ratio": 0.0,
        "bullish": c.bullish,
        "bearish": c.bearish,
    }
    if c.body + 1e-12 < min_body:
        out["type"] = ""
        return out
    if side == Side.LONG:
        ratio = c.wick_body_ratio_lower
        out["wick_body_ratio"] = round(ratio, 4)
        engulf = False
        if prev:
            p = candle_metrics(prev)
            engulf = (
                c.bullish
                and p.bearish
                and min(c.open, c.close) <= min(p.open, p.close) + 1e-12
                and max(c.open, c.close) >= max(p.open, p.close) - 1e-12
            )
        if c.bullish and ratio >= pin_r:
            out["type"] = PIN_BAR
        elif c.bullish and ratio >= strong_r:
            out["type"] = STRONG_WICK
        elif engulf:
            out["type"] = ENGULFING
            out["wick_body_ratio"] = round(ratio, 4)
        return out
    ratio = c.wick_body_ratio_upper
    out["wick_body_ratio"] = round(ratio, 4)
    engulf = False
    if prev:
        p = candle_metrics(prev)
        engulf = (
            c.bearish
            and p.bullish
            and min(c.open, c.close) <= min(p.open, p.close) + 1e-12
            and max(c.open, c.close) >= max(p.open, p.close) - 1e-12
        )
    if c.bearish and ratio >= pin_r:
        out["type"] = PIN_BAR
    elif c.bearish and ratio >= strong_r:
        out["type"] = STRONG_WICK
    elif engulf:
        out["type"] = ENGULFING
    return out


def penetration_atr(side: Side, bar: dict, ema8: float, atr_v: float) -> float:
    atr_n = max(atr_v, 1e-9)
    if side == Side.LONG:
        return max(0.0, (ema8 - float(bar.get("low") or 0)) / atr_n)
    return max(0.0, (float(bar.get("high") or 0) - ema8) / atr_n)


def distance_to_ema_atr(price: float, ema8: float, atr_v: float) -> float:
    return abs(float(price) - float(ema8)) / max(atr_v, 1e-9)


def stop_price(side: Side, ema8: float, bar: dict, atr_v: float, cfg: Mark2Config | None) -> float:
    buf = _f(cfg, "TCM8_STOP_BUFFER_ATR", 0.10) * max(atr_v, _tick(cfg))
    if side == Side.LONG:
        ref = min(float(ema8), float(bar.get("low") or ema8))
        return ref - buf
    ref = max(float(ema8), float(bar.get("high") or ema8))
    return ref + buf


def quality_grade(target_r: float) -> str:
    if target_r >= 1.50:
        return GRADE_A
    if target_r >= 1.00:
        return GRADE_B
    if target_r >= 0.75:
        return GRADE_C
    return ""


def room_label(target_r: float) -> str:
    if target_r >= 1.50:
        return GRADE_A_PLUS_ROOM
    if target_r >= 0.75:
        return GRADE_LOWER
    return ""


@dataclass
class Tcm8Setup:
    state: str = ST_WAITING_FOR_TREND
    side: str = ""
    had_extension: bool = False
    pullback: bool = False
    tested: bool = False


@dataclass
class Tcm8Stats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    r_sum: float = 0.0
    mfe_sum: float = 0.0
    mae_sum: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    equity: float = 0.0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    by_grade: dict[str, int] = field(default_factory=dict)
    by_rejection: dict[str, int] = field(default_factory=dict)
    by_hour: dict[str, int] = field(default_factory=dict)
    target_r_sum: float = 0.0

    def record(self, *, side: str, pnl: float, r_mult: float, mfe: float, mae: float,
               grade: str, rejection: str, hour: int, target_r: float) -> None:
        self.trades += 1
        self.net_pnl += pnl
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        self.max_drawdown = max(self.max_drawdown, self.peak_equity - self.equity)
        self.r_sum += r_mult
        self.mfe_sum += mfe
        self.mae_sum += mae
        self.target_r_sum += target_r
        if pnl > 0:
            self.wins += 1
            self.gross_profit += pnl
        elif pnl < 0:
            self.losses += 1
            self.gross_loss += abs(pnl)
        if side == "LONG":
            self.long_trades += 1
        else:
            self.short_trades += 1
        if grade:
            self.by_grade[grade] = self.by_grade.get(grade, 0) + 1
        if rejection:
            self.by_rejection[rejection] = self.by_rejection.get(rejection, 0) + 1
        hk = str(hour)
        self.by_hour[hk] = self.by_hour.get(hk, 0) + 1

    def clear(self) -> None:
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.net_pnl = 0.0
        self.r_sum = 0.0
        self.mfe_sum = 0.0
        self.mae_sum = 0.0
        self.long_trades = 0
        self.short_trades = 0
        self.equity = 0.0
        self.peak_equity = 0.0
        self.max_drawdown = 0.0
        self.by_grade = {}
        self.by_rejection = {}
        self.by_hour = {}
        self.target_r_sum = 0.0

    def summary(self) -> dict[str, Any]:
        losses = max(self.losses, 0)
        wins = self.wins
        pf = (self.gross_profit / self.gross_loss) if self.gross_loss > 1e-9 else (99.99 if self.gross_profit > 0 else 0.0)
        avg_w = (self.gross_profit / wins) if wins else 0.0
        avg_l = (self.gross_loss / losses) if losses else 0.0
        n = max(self.trades, 1)
        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(100.0 * self.wins / n, 2) if self.trades else 0.0,
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "net_pnl": round(self.net_pnl, 2),
            "profit_factor": round(min(pf, 99.99), 2),
            "average_winner": round(avg_w, 2),
            "average_loser": round(avg_l, 2),
            "average_r": round(self.r_sum / n, 3) if self.trades else 0.0,
            "expectancy_r": round(self.r_sum / n, 3) if self.trades else 0.0,
            "max_drawdown": round(self.max_drawdown, 2),
            "average_mae": round(self.mae_sum / n, 3) if self.trades else 0.0,
            "average_mfe": round(self.mfe_sum / n, 3) if self.trades else 0.0,
            "long_trades": self.long_trades,
            "short_trades": self.short_trades,
            "by_grade": dict(self.by_grade),
            "by_rejection": dict(self.by_rejection),
            "by_hour": dict(self.by_hour),
            "avg_target_r": round(self.target_r_sum / n, 3) if self.trades else 0.0,
        }


def _reset_setup(setup: Tcm8Setup, state: str = ST_WAITING_FOR_TREND) -> None:
    setup.state = state
    setup.side = ""
    setup.had_extension = False
    setup.pullback = False
    setup.tested = False


def _empty_log(**kwargs: Any) -> dict[str, Any]:
    row = {
        "strategy": "8TCM",
        "accept": False,
        "reason": "",
        "direction": "",
        "state": ST_WAITING_FOR_TREND,
        "trend": TREND_UNCLEAR,
        "trend_why": "",
        "trend_source": "",
        "sequence": "",
        "swings": "",
        "swing_high": 0.0,
        "swing_low": 0.0,
        "prior_high": 0.0,
        "prior_low": 0.0,
        "hh": False,
        "hl": False,
        "lh": False,
        "ll": False,
        "htf_1h": TREND_UNCLEAR,
        "htf_4h": TREND_UNCLEAR,
        "slope_1h": 0.0,
        "slope_4h": 0.0,
        "slope_atr": 0.0,
        "range_state": TREND_UNCLEAR,
        "ema8": 0.0,
        "atr": 0.0,
        "close": 0.0,
        "pullback": False,
        "retracement": False,
        "tested": False,
        "close_side": "",
        "distance_ema_atr": 0.0,
        "penetration_atr": 0.0,
        "rejection_type": "",
        "rejection_body": 0.0,
        "rejection_body_atr": 0.0,
        "upper_wick": 0.0,
        "lower_wick": 0.0,
        "wick_body_ratio": 0.0,
        "entry": 0.0,
        "stop": 0.0,
        "risk_points": 0.0,
        "barrier_price": 0.0,
        "barrier_type": "",
        "barrier_distance": 0.0,
        "barrier_distance_atr": 0.0,
        "target_r": 0.0,
        "primary_target_price": 0.0,
        "primary_target_type": "",
        "quality": "",
        "room": "",
    }
    row.update(kwargs)
    return row


def _structure_reject(trend: dict[str, Any]) -> str:
    if trend.get("state") == TREND_RANGING:
        return REJ_RANGE
    hh, hl = bool(trend.get("hh")), bool(trend.get("hl"))
    lh, ll = bool(trend.get("lh")), bool(trend.get("ll"))
    if (hh and ll) or (lh and hl):
        return REJ_NO_CLEAR_TREND
    if hh and not hl:
        return REJ_BULLISH_STRUCT
    if lh and not ll:
        return REJ_BEARISH_STRUCT
    return REJ_NO_CLEAR_TREND


def _was_extended(
    bars: list[dict],
    side: Side,
    ema8: float,
    atr_v: float,
    pull_max: float,
) -> bool:
    """Prior completed bars only. Price must have traded away from EMA8 before this bar."""
    thresh = pull_max * max(atr_v, 1e-9)
    for bar in bars[-13:-1]:
        close = float(bar.get("close") or 0)
        if side == Side.LONG and close >= ema8 + thresh:
            return True
        if side == Side.SHORT and close <= ema8 - thresh:
            return True
    return False


def evaluate_tcm8(
    *,
    cfg: Mark2Config,
    bars_1m: list[dict],
    bars_1h: list[dict],
    bars_4h: list[dict],
    book: BarrierBook,
    setup: Tcm8Setup,
    armed: bool,
    connected: bool,
    cooldown: bool,
    allow_long: bool,
    allow_short: bool,
) -> dict[str, Any]:
    """One completed 1m bar. Structure trend → retrace → EMA8 test → close reject."""
    if not tcm8_enabled(cfg):
        return _empty_log(reason="DISABLED")
    if cooldown:
        _reset_setup(setup)
        return _empty_log(reason=REJ_COOLDOWN)
    if not armed:
        return _empty_log(reason=REJ_ARMED)
    if not connected:
        return _empty_log(reason=REJ_BRIDGE)

    period = _period(cfg)
    if len(bars_1m) < period + 5:
        _reset_setup(setup)
        return _empty_log(reason=REJ_NO_CLEAR_TREND, range_state=TREND_UNCLEAR)

    trend = resolve_8tcm_trend(bars_1m, bars_1h, cfg)
    t1 = classify_htf_trend(bars_1h, cfg)
    t4 = classify_htf_trend(bars_4h, cfg)
    chop = is_market_ranging(bars_1m, cfg)
    atr_v = max(last_atr(bars_1m), _tick(cfg))
    ema8 = last_ema(bars_1m, period)
    last = bars_1m[-1]
    prev = bars_1m[-2] if len(bars_1m) > 1 else None
    close = float(last.get("close") or 0)
    close_side = "ABOVE" if close > ema8 else ("BELOW" if close < ema8 else "ON")
    base = _empty_log(
        trend=trend["state"],
        trend_why=trend.get("why"),
        sequence=trend.get("sequence") or "",
        swings=trend.get("swings") or "",
        trend_source=str(trend.get("source") or ""),
        swing_high=trend.get("swing_high") or 0.0,
        swing_low=trend.get("swing_low") or 0.0,
        prior_high=trend.get("prior_high") or 0.0,
        prior_low=trend.get("prior_low") or 0.0,
        hh=bool(trend.get("hh")),
        hl=bool(trend.get("hl")),
        lh=bool(trend.get("lh")),
        ll=bool(trend.get("ll")),
        htf_1h=t1["state"],
        htf_4h=t4["state"],
        slope_1h=t1.get("slope_atr") or 0.0,
        slope_4h=t4.get("slope_atr") or 0.0,
        slope_atr=trend.get("slope_atr") or 0.0,
        range_state=chop["state"],
        ema8=round(ema8, 4),
        atr=round(atr_v, 4),
        close=round(close, 4),
        close_side=close_side,
        htf_1h_why=t1.get("why"),
        htf_4h_why=t4.get("why"),
        range_why=chop.get("why"),
        timestamp=str(last.get("time") or ""),
        structure_log=(
            f"8TCM STRUCTURE: {trend['state']}  {trend.get('swings') or ''}  "
            f"TREND: {trend['state']}"
        ),
    )

    if trend["state"] not in (TREND_BULLISH, TREND_BEARISH):
        _reset_setup(setup)
        base["reason"] = _structure_reject(trend)
        base["state"] = setup.state
        return base
    if chop["state"] == TREND_RANGING:
        _reset_setup(setup)
        base["reason"] = REJ_RANGE
        base["state"] = setup.state
        return base

    side = Side.LONG if trend["state"] == TREND_BULLISH else Side.SHORT
    if setup.side and setup.side != side.value:
        _reset_setup(setup, ST_TREND_CONFIRMED)
    setup.side = side.value
    setup.state = ST_TREND_CONFIRMED
    if side == Side.LONG and not _b(cfg, "ENABLE_8TCM_LONGS", True):
        base["reason"] = REJ_SIDE
        base["direction"] = "LONG"
        base["state"] = setup.state
        return base
    if side == Side.SHORT and not _b(cfg, "ENABLE_8TCM_SHORTS", False):
        base["reason"] = REJ_SIDE
        base["direction"] = "SHORT"
        base["state"] = setup.state
        return base

    base["direction"] = side.value
    pull_max = _f(cfg, "TCM8_PULLBACK_MAX_DISTANCE_ATR", 0.15)
    max_entry = _f(cfg, "TCM8_MAX_ENTRY_DISTANCE_FROM_EMA_ATR", 0.30)
    prox = _f(cfg, "TCM8_BARRIER_PROXIMITY_BLOCK_ATR", 0.25)
    min_r = _f(cfg, "TCM8_MINIMUM_TARGET_R", 0.75)

    dist_close = distance_to_ema_atr(close, ema8, atr_v)
    probe = float(last.get("low") or close) if side == Side.LONG else float(last.get("high") or close)
    pen = penetration_atr(side, last, ema8, atr_v)
    base["distance_ema_atr"] = round(dist_close, 4)
    base["penetration_atr"] = round(pen, 4)

    thresh = pull_max * atr_v
    if side == Side.LONG:
        away = close >= ema8 + thresh
        toward = probe <= ema8 + thresh
    else:
        away = close <= ema8 - thresh
        toward = probe >= ema8 - thresh

    if away:
        setup.had_extension = True
        setup.pullback = False
        setup.tested = False
    elif _was_extended(bars_1m, side, ema8, atr_v, pull_max):
        setup.had_extension = True

    setup.state = ST_WAITING_FOR_RETRACEMENT
    if not setup.had_extension:
        base["reason"] = REJ_NO_RETRACEMENT
        base["state"] = setup.state
        base["pullback"] = False
        base["retracement"] = False
        return base
    if away and not toward:
        base["reason"] = REJ_NO_RETRACEMENT
        base["state"] = setup.state
        base["pullback"] = False
        base["retracement"] = False
        return base
    if not toward:
        base["reason"] = REJ_NO_RETRACEMENT
        base["state"] = setup.state
        base["pullback"] = False
        base["retracement"] = False
        return base

    setup.pullback = True
    setup.state = ST_EMA8_TESTING
    base["pullback"] = True
    base["retracement"] = True

    tested = ema8_is_tested(side, last, ema8, atr_v, cfg)
    setup.tested = tested
    base["tested"] = tested
    if not tested:
        base["reason"] = REJ_EMA8_NOT_TESTED
        base["state"] = setup.state
        return base

    setup.state = ST_WAITING_FOR_REJECTION
    rej = classify_rejection(last, prev, side, atr_v, cfg)
    base.update(
        {
            "rejection_type": rej["type"],
            "rejection_body": rej["body"],
            "rejection_body_atr": rej["body_atr"],
            "upper_wick": rej["upper_wick"],
            "lower_wick": rej["lower_wick"],
            "wick_body_ratio": rej["wick_body_ratio"],
        }
    )
    close_ok = (side == Side.LONG and close > ema8) or (side == Side.SHORT and close < ema8)
    if not close_ok:
        base["reason"] = REJ_WRONG_SIDE
        base["state"] = setup.state
        return base

    if not rej["type"]:
        base["rejection_type"] = EMA8_CLOSE_REJECT

    setup.state = ST_EMA8_REJECTION_CONFIRMED
    entry = close
    if distance_to_ema_atr(entry, ema8, atr_v) > max_entry:
        base["reason"] = REJ_CHASE
        base["entry"] = round(entry, 2)
        base["state"] = setup.state
        return base

    stop = stop_price(side, ema8, last, atr_v, cfg)
    tick = _tick(cfg)
    risk = abs(entry - stop)
    if risk < tick:
        base["reason"] = REJ_STOP
        base["entry"] = round(entry, 2)
        base["stop"] = round(stop, 2)
        base["state"] = setup.state
        return base

    zone = get_next_momentum_barrier(side, entry, book, atr_v, cfg)
    if not zone.found:
        base["reason"] = REJ_BARRIER
        base["entry"] = round(entry, 2)
        base["stop"] = round(stop, 2)
        base["risk_points"] = round(risk, 4)
        base["state"] = setup.state
        return base
    if side == Side.LONG:
        dist_pts = float(zone.price) - entry
    else:
        dist_pts = entry - float(zone.price)
    dist_atr = dist_pts / max(atr_v, 1e-9)
    kind = barrier_kind_label(zone.kind)
    min_pts = _f(cfg, "MIN_ROOM_TO_BARRIER_POINTS", 8.0)
    min_room_atr = _f(cfg, "MIN_ROOM_TO_BARRIER_ATR", 0.35)
    too_close = (
        dist_atr < prox
        or (min_pts > 0 and dist_pts + 1e-12 < min_pts)
        or (min_room_atr > 0 and dist_atr + 1e-12 < min_room_atr)
    )
    if too_close:
        base["reason"] = REJ_BARRIER
        base["barrier_price"] = round(zone.price, 2)
        base["barrier_type"] = kind
        base["primary_target_price"] = round(zone.price, 2)
        base["primary_target_type"] = kind
        base["barrier_distance"] = round(dist_pts, 4)
        base["barrier_distance_atr"] = round(dist_atr, 4)
        base["entry"] = round(entry, 2)
        base["stop"] = round(stop, 2)
        base["risk_points"] = round(risk, 4)
        base["state"] = setup.state
        return base

    if side == Side.LONG:
        reward = zone.price - entry
    else:
        reward = entry - zone.price
    if reward <= 0:
        base["reason"] = REJ_TARGET_R
        base["barrier_price"] = round(zone.price, 2)
        base["barrier_type"] = kind
        base["state"] = setup.state
        return base
    target_r = reward / risk
    grade = quality_grade(target_r)
    base.update(
        {
            "entry": round(entry, 2),
            "stop": round(stop, 2),
            "risk_points": round(risk, 4),
            "barrier_price": round(zone.price, 2),
            "barrier_type": kind,
            "primary_target_price": round(zone.price, 2),
            "primary_target_type": kind,
            "barrier_distance": round(dist_pts, 4),
            "barrier_distance_atr": round(dist_atr, 4),
            "target_r": round(target_r, 4),
            "quality": grade,
            "room": room_label(target_r),
        }
    )
    if target_r < min_r:
        base["reason"] = REJ_TARGET_R
        base["state"] = setup.state
        return base

    mode = str(getattr(cfg, "TCM8_ENTRY_MODE", "CLOSED_BAR") or "CLOSED_BAR").upper()
    if mode != "CLOSED_BAR" and not _b(cfg, "ENABLE_8TCM_EARLY_ENTRY", False):
        base["reason"] = REJ_EARLY
        base["state"] = setup.state
        return base

    setup.state = ST_READY_TO_EXECUTE
    base["accept"] = True
    base["reason"] = ENTRY_LONG_REASON if side == Side.LONG else ENTRY_SHORT_REASON
    base["state"] = setup.state
    base["entry_reason"] = base["reason"]
    _reset_setup(setup, ST_TRADE_ACTIVE)
    return base


def tcm8_peak_usd(trade, cfg: Mark2Config | None) -> float:
    pv = 2.0
    if cfg is not None:
        pv = max(float(getattr(cfg, "POINT_VALUE", 2.0) or 2.0), 1e-9)
    qty = max(1, int(getattr(trade, "qty", 1) or 1))
    entry = float(getattr(trade, "entry", 0) or 0)
    mfe = max(0.0, float(getattr(trade, "mfe", 0) or 0))
    side = getattr(trade, "side", None)
    if side == Side.LONG:
        mfe = max(mfe, float(getattr(trade, "peak", entry) or entry) - entry)
    elif side == Side.SHORT:
        tip = float(getattr(trade, "trough", entry) or entry)
        mfe = max(mfe, entry - tip)
    return mfe * pv * qty


def tcm8_dollar_lock_price(trade, cfg: Mark2Config | None) -> float:
    """Stop floor once the dollar trail is armed. Not the green key level."""
    entry = float(getattr(trade, "entry", 0) or 0)
    arm = 50.0
    pv = 2.0
    if cfg is not None:
        arm = float(getattr(cfg, "TCM8_TRAIL_ARM_USD", 50.0) or 50.0)
        pv = max(float(getattr(cfg, "POINT_VALUE", 2.0) or 2.0), 1e-9)
    qty = max(1, int(getattr(trade, "qty", 1) or 1))
    pts = arm / max(pv * qty, 1e-9)
    side = getattr(trade, "side", None)
    if side == Side.LONG:
        return round(entry + pts, 2)
    return round(entry - pts, 2)


def tcm8_runner_floor(trade, cfg: Mark2Config | None) -> float:
    side = getattr(trade, "side", None)
    if bool(getattr(trade, "tcm8_primary_hit", False)):
        return tcm8_working_target(side, float(getattr(trade, "target", 0) or 0), cfg)
    return tcm8_dollar_lock_price(trade, cfg)


def tcm8_working_target(side: Side, key_level: float, cfg: Mark2Config | None) -> float:
    """Green bank line: slightly in front of the raw key level. Entry R still uses the wall."""
    key = float(key_level or 0)
    if key <= 0:
        return 0.0
    tick = _tick(cfg)
    front = max(tick, _f(cfg, "TCM8_TARGET_FRONT_RUN_POINTS", 1.5))
    if side == Side.LONG:
        return round(key - front, 2)
    return round(key + front, 2)


def tcm8_runner_room(cfg: Mark2Config | None) -> float:
    """Leftover purple: 5.5 points behind the live candle tip."""
    tick = _tick(cfg)
    raw = 5.5
    if cfg is not None:
        raw = float(getattr(cfg, "TCM8_TRAIL_POINTS", 5.5) or 5.5)
    return max(tick, raw)


def tcm8_live_tip(trade, *, price: float, forming: dict | None = None) -> float:
    """Ratchet the favorable extreme from last price and the forming candle."""
    px = float(price)
    hi = px
    lo = px
    if forming:
        hi = max(hi, float(forming.get("high") or 0) or px)
        raw_lo = float(forming.get("low") or 0)
        if raw_lo > 0:
            lo = min(lo, raw_lo)
    side = getattr(trade, "side", None)
    if side == Side.LONG:
        tip = max(float(getattr(trade, "peak", px) or px), hi, px)
        trade.peak = tip
        return tip
    tip = min(float(getattr(trade, "trough", px) or px), lo, px)
    if tip <= 0:
        tip = px
    trade.trough = tip
    return tip


def apply_tcm8_runner_trail(
    trade,
    *,
    cfg: Mark2Config | None,
    price: float | None = None,
    forming: dict | None = None,
) -> None:
    """Purple follows the live candle tip. Never widen. Floor at dollar/green."""
    if trade is None:
        return
    side = trade.side
    hard = float(getattr(trade, "hard_stop", 0) or trade.stop)
    trade.hard_stop = hard
    floor = tcm8_runner_floor(trade, cfg)
    entry = float(getattr(trade, "entry", 0) or 0)
    room = tcm8_runner_room(cfg)
    prev = float(getattr(trade, "stop", 0) or hard)
    px = float(price if price is not None else getattr(trade, "peak", entry) or entry)
    tip = tcm8_live_tip(trade, price=px, forming=forming)
    if side == Side.LONG:
        if floor <= 0:
            floor = entry
        nxt = max(hard, floor, tip - room)
        trade.stop = max(prev, nxt)
        return
    if floor <= 0:
        floor = entry
    nxt = min(hard, floor, tip + room)
    trade.stop = nxt if prev <= 0 else min(prev, nxt)


def tcm8_broke_green_or_trail(trade, *, price: float, cfg: Mark2Config | None) -> str:
    """Sitting on the green line does not flatten. One tick through it does.

    Purple only exits after the tip has run trail-room past the green line.
    """
    side = trade.side
    lock = tcm8_runner_floor(trade, cfg)
    if lock <= 0:
        lock = float(getattr(trade, "entry", 0) or 0)
    tick = _tick(cfg)
    px = float(price)
    stop = float(getattr(trade, "stop", 0) or 0)
    if side == Side.LONG:
        if px <= lock - tick:
            return EXIT_GREEN_BANK
        if stop > lock + tick * 0.51 and px <= stop:
            return EXIT_RUNNER_TRAIL
        return ""
    if px >= lock + tick:
        return EXIT_GREEN_BANK
    if stop < lock - tick * 0.51 and px >= stop:
        return EXIT_RUNNER_TRAIL
    return ""


def manage_tcm8_hold(
    trade,
    *,
    price: float,
    cfg: Mark2Config | None,
    forming: dict | None = None,
) -> str:
    """Classic flatten at key level, or leftover purple from the green line after primary."""
    if trade is None or not uses_tcm8_hold(trade):
        return ""
    side = trade.side
    hard = float(getattr(trade, "hard_stop", 0) or trade.stop)
    trade.hard_stop = hard
    px = float(price)
    entry = float(getattr(trade, "entry", 0) or 0)
    tcm8_live_tip(trade, price=px, forming=forming)
    if side == Side.LONG:
        trade.trough = min(float(getattr(trade, "trough", px) or px), px)
        trade.mfe = max(0.0, float(getattr(trade, "mfe", 0) or 0), trade.peak - entry)
    else:
        trade.peak = max(float(getattr(trade, "peak", px) or px), px)
        trade.mfe = max(0.0, float(getattr(trade, "mfe", 0) or 0), entry - trade.trough)
    runner_on = bool(getattr(trade, "tcm8_runner", False) or getattr(trade, "tcm8_primary_hit", False))
    if side == Side.LONG:
        if px <= hard:
            return "HARD_STOP"
    else:
        if px >= hard:
            return "HARD_STOP"
    raw_tgt = float(getattr(trade, "target", 0) or 0)
    tgt = tcm8_working_target(side, raw_tgt, cfg)
    hit_green = tgt > 0 and (
        (side == Side.LONG and px >= tgt) or (side == Side.SHORT and px <= tgt)
    )
    if runner_on:
        if hit_green and not bool(getattr(trade, "tcm8_primary_hit", False)):
            return RUNNER_ARM
        apply_tcm8_runner_trail(trade, cfg=cfg, price=px, forming=forming)
        return tcm8_broke_green_or_trail(trade, price=px, cfg=cfg)
    trade.stop = hard
    if hit_green:
        if _b(cfg, "ENABLE_8TCM_RUNNER", False):
            return RUNNER_ARM
        if _b(cfg, "ENABLE_8TCM_CLASSIC_TARGET", True):
            return EXIT_KEY_LEVEL
    arm_usd = _f(cfg, "TCM8_TRAIL_ARM_USD", 50.0) if cfg is not None else 50.0
    if _b(cfg, "ENABLE_8TCM_RUNNER", False) and arm_usd > 0 and tcm8_peak_usd(trade, cfg) + 1e-9 >= arm_usd:
        return DOLLAR_ARM
    return ""


def format_tcm8_log(row: dict[str, Any]) -> str:
    side = str(row.get("direction") or "—")
    if row.get("accept"):
        rej = str(row.get("rejection_type") or "REJECTION")
        return f"FIRE {side} · {rej}"
    reason = str(row.get("reason") or "WAIT").replace("REJECT_", "").replace("_", " ")
    return f"{side} · {reason}"


def _step(key: str, label: str, status: str, detail: str = "") -> dict[str, str]:
    return {"id": key, "label": label, "status": status, "detail": str(detail or ""), "hot": False}


def _mark_hot_steps(steps: list[dict[str, str]], *, ready: bool = False) -> list[dict[str, str]]:
    for step in steps:
        step["hot"] = False
    if ready:
        for step in steps:
            if step.get("id") == "fire":
                step["hot"] = True
        return steps
    for step in steps:
        if step.get("status") in ("wait", "fail"):
            step["hot"] = True
            return steps
    return steps


def tcm8_live_checklist(
    row: dict[str, Any] | None,
    *,
    cfg: Mark2Config | None = None,
    trade: Any = None,
) -> list[dict[str, str]]:
    """TRADE checklist. PASS / FAIL / WAIT in fire order."""
    row = dict(row or {})
    reason = str(row.get("reason") or "")
    accept = bool(row.get("accept"))
    in_trade = trade is not None and bool(getattr(trade, "tcm8", False))
    trend = str(row.get("trend") or TREND_UNCLEAR)
    rang = str(row.get("range_state") or "—")
    direction = str(row.get("direction") or "")
    early = ("", "DISABLED", REJ_ARMED, REJ_BRIDGE, REJ_COOLDOWN)
    structure_block = (REJ_NO_CLEAR_TREND, REJ_BEARISH_STRUCT, REJ_BULLISH_STRUCT, REJ_HTF)
    past_trend = reason not in early or accept
    past_chop = (past_trend and reason not in structure_block) or accept
    past_side = (past_chop and reason not in (*structure_block, REJ_RANGE)) or accept
    past_retrace = (past_side and reason not in (*structure_block, REJ_RANGE, REJ_SIDE)) or accept
    past_test = (
        past_retrace and reason not in (*structure_block, REJ_RANGE, REJ_SIDE, REJ_NO_RETRACEMENT, REJ_NO_PULLBACK)
    ) or accept
    past_rej = (
        past_test
        and reason
        not in (
            *structure_block,
            REJ_RANGE,
            REJ_SIDE,
            REJ_NO_RETRACEMENT,
            REJ_NO_PULLBACK,
            REJ_EMA8_NOT_TESTED,
            REJ_STRUCTURE,
        )
    ) or accept
    past_chase = (
        past_rej
        and reason
        not in (
            *structure_block,
            REJ_RANGE,
            REJ_SIDE,
            REJ_NO_RETRACEMENT,
            REJ_NO_PULLBACK,
            REJ_EMA8_NOT_TESTED,
            REJ_STRUCTURE,
            REJ_EMA8_REJECTION,
            REJ_NO_REJECTION,
            REJ_WRONG_SIDE,
        )
    ) or accept
    past_room = (
        past_chase
        and reason
        not in (
            *structure_block,
            REJ_RANGE,
            REJ_SIDE,
            REJ_NO_RETRACEMENT,
            REJ_NO_PULLBACK,
            REJ_EMA8_NOT_TESTED,
            REJ_STRUCTURE,
            REJ_EMA8_REJECTION,
            REJ_NO_REJECTION,
            REJ_WRONG_SIDE,
            REJ_CHASE,
            REJ_STOP,
        )
    ) or accept

    if reason in (REJ_ARMED,):
        tr_st, tr_d = "fail", "DISARMED · ARM ON CONTROL"
    elif reason in (REJ_BRIDGE,):
        tr_st, tr_d = "fail", "BRIDGE OFF"
    elif reason in (REJ_COOLDOWN,):
        tr_st, tr_d = "wait", "COOLDOWN"
    elif reason in structure_block:
        tr_st, tr_d = "fail", str(row.get("sequence") or row.get("trend_why") or trend)
    elif trend in (TREND_BULLISH, TREND_BEARISH):
        tr_st, tr_d = "pass", f"{trend} · {row.get('sequence') or ''}".strip(" ·")
    elif not reason:
        tr_st, tr_d = "wait", "NEED HH/HL OR LH/LL"
    else:
        tr_st, tr_d = "fail", f"{trend} · {row.get('trend_why') or 'NO CLEAR TREND'}"

    if rang == TREND_TRENDING:
        chop_st, chop_d = "pass", "NOT A TIGHT RANGE"
    elif rang == TREND_RANGING or reason == REJ_RANGE:
        chop_st, chop_d = "fail", "RANGING · NO FIRE"
    elif not past_trend:
        chop_st, chop_d = "wait", str(rang)
    else:
        chop_st, chop_d = "wait", str(rang)

    if reason == REJ_SIDE:
        side_st, side_d = "fail", f"{direction or 'SIDE'} OFF"
    elif past_side and direction:
        side_st, side_d = "pass", direction
    else:
        side_st, side_d = "wait", "NEED CLEAR STRUCTURE FIRST"

    dist = row.get("distance_ema_atr")
    if reason in (REJ_NO_RETRACEMENT, REJ_NO_PULLBACK):
        pull_st, pull_d = "fail", f"NO RETRACEMENT · distATR {dist}"
    elif bool(row.get("retracement") or row.get("pullback")):
        pull_st, pull_d = "pass", f"RETRACE TO EMA8 {row.get('ema8')} · distATR {dist}"
    elif past_retrace:
        pull_st, pull_d = "fail", "NO RETRACEMENT"
    else:
        pull_st, pull_d = "wait", "WAIT PULL TO 8"

    rej = str(row.get("rejection_type") or "")
    if reason in (REJ_EMA8_NOT_TESTED, REJ_STRUCTURE) and not rej:
        test_st, test_d = "fail", f"EMA8 NOT TESTED · penATR {row.get('penetration_atr')}"
    elif bool(row.get("tested")) or rej:
        test_st, test_d = "pass", f"TESTED · penATR {row.get('penetration_atr')}"
    elif past_test:
        test_st, test_d = "fail", "EMA8 NOT TESTED"
    else:
        test_st, test_d = "wait", "TOUCH / WICK 8"
    if reason == REJ_WRONG_SIDE:
        rej_st, rej_d = "fail", f"CLOSE {row.get('close_side')} EMA8"
    elif reason in (REJ_EMA8_REJECTION, REJ_NO_REJECTION):
        rej_st, rej_d = "fail", "REJECTION NOT CONFIRMED"
    elif rej:
        rej_st, rej_d = "pass", f"{rej} · CLOSE {row.get('close_side')}"
    elif past_rej:
        rej_st, rej_d = "fail", "REJECTION NOT CONFIRMED"
    else:
        rej_st, rej_d = "wait", "CLOSE BACK TREND SIDE"

    if reason == REJ_CHASE:
        chase_st, chase_d = "fail", f"distATR {dist} · TOO FAR"
    elif past_chase:
        chase_st, chase_d = "pass", f"entry {row.get('entry')} · distATR {dist}"
    else:
        chase_st, chase_d = "wait", "STAY NEAR 8"

    bar = str(row.get("primary_target_type") or row.get("barrier_type") or "")
    r = row.get("target_r")
    tgt = row.get("primary_target_price") or row.get("barrier_price")
    if reason == REJ_STOP:
        room_st, room_d = "fail", "INVALID STOP"
    elif reason == REJ_BARRIER:
        room_st, room_d = (
            "fail",
            f"{bar or 'LEVEL'} TOO CLOSE · {row.get('barrier_distance')} pts · {row.get('barrier_distance_atr')} ATR",
        )
    elif reason == REJ_TARGET_R:
        need = _f(cfg, "TCM8_MINIMUM_TARGET_R", 0.75) if cfg is not None else 0.75
        room_st, room_d = "fail", f"R {r} · NEED {need:.2f}"
    elif accept or (past_room and bar):
        room_st, room_d = "pass", f"{bar}@{tgt} · R {r}"
    else:
        room_st, room_d = "wait", "NEXT KEY LEVEL"

    runner = bool(trade is not None and getattr(trade, "tcm8_runner", False))
    if in_trade and runner:
        fire_st, fire_d = "hold", "PRIMARY TARGET REACHED · RUNNER ACTIVE"
    elif in_trade:
        fire_st, fire_d = "hold", f"{direction or 'TRADE'} ACTIVE · INITIAL STOP"
    elif accept:
        fire_st, fire_d = "pass", f"READY {direction} {row.get('quality') or ''}".strip()
    elif reason in (REJ_ARMED, REJ_BRIDGE):
        fire_st, fire_d = "fail", reason.replace("REJECT_", "")
    else:
        fire_st, fire_d = "wait", "1m CLOSE"

    steps = [
        _step("trend", "TREND", tr_st, tr_d),
        _step("chop", "NO RANGE", chop_st, chop_d),
        _step("side", "SIDE", side_st, side_d),
        _step("retrace", "RETRACE 8", pull_st, pull_d),
        _step("test", "TEST 8", test_st, test_d),
        _step("rej", "REJECT 8", rej_st, rej_d),
        _step("dist", "NEAR 8", chase_st, chase_d),
        _step("room", "TARGET", room_st, room_d),
        _step("fire", "FIRE", fire_st, fire_d),
    ]
    return _mark_hot_steps(steps, ready=bool(accept or in_trade))


def tcm8_next_gate(checklist: list[dict[str, str]]) -> str:
    for step in checklist:
        if step.get("status") == "fail":
            return f"BLOCKED · {step.get('label')} · {step.get('detail')}"
        if step.get("status") == "wait":
            return f"NEXT · {step.get('label')} · {step.get('detail')}"
        if step.get("status") == "hold":
            return str(step.get("detail") or "IN TRADE")
    for step in reversed(checklist):
        if step.get("status") == "pass" and step.get("id") == "fire":
            return str(step.get("detail") or "READY TO FIRE")
    return "WAITING 1m CLOSE"


def tcm8_state_call(row: dict[str, Any], trade: Any = None) -> tuple[str, str]:
    """HUD headline from the entry state machine."""
    in_trade = trade is not None and bool(getattr(trade, "tcm8", False))
    direction = str(row.get("direction") or "")
    if in_trade:
        side = str(getattr(getattr(trade, "side", None), "value", "") or direction)
        if bool(getattr(trade, "tcm8_runner", False) or getattr(trade, "tcm8_primary_hit", False)):
            return "RUNNER", f"8TCM · PRIMARY TARGET REACHED · RUNNER ACTIVE"
        tgt = float(getattr(trade, "target", 0) or 0)
        entry = float(getattr(trade, "entry", 0) or 0)
        peak = float(getattr(trade, "peak", entry) or entry)
        trough = float(getattr(trade, "trough", entry) or entry)
        if tgt > 0 and entry > 0:
            if side == "LONG" and (tgt - entry) > 0 and (peak - entry) >= 0.75 * (tgt - entry):
                return f"{side} HOLD", "8TCM · TARGET APPROACHING"
            if side == "SHORT" and (entry - tgt) > 0 and (entry - trough) >= 0.75 * (entry - tgt):
                return f"{side} HOLD", "8TCM · TARGET APPROACHING"
        return f"{side} HOLD" if side else "IN TRADE", f"8TCM · {side or 'TRADE'} ACTIVE"
    state = str(row.get("state") or ST_WAITING_FOR_TREND)
    trend = str(row.get("trend") or "")
    reason = str(row.get("reason") or "")
    if reason.startswith("REJECT") and not bool(row.get("accept")):
        return "BLOCKED", f"8TCM · {reason.replace('REJECT_', '').replace('_', ' ')} · {direction}".strip(" ·")
    if bool(row.get("accept")) or state == ST_READY_TO_EXECUTE:
        return "READY", f"8TCM · REJECTION CONFIRMED · READY {direction or ''}".strip()
    if state == ST_EMA8_REJECTION_CONFIRMED:
        return "WAIT", f"8TCM · REJECTION CONFIRMED · GATES {direction or ''}".strip()
    if state == ST_WAITING_FOR_REJECTION:
        kind = "BULLISH" if direction == "LONG" else "BEARISH" if direction == "SHORT" else ""
        return "WAIT", f"8TCM · WAITING FOR {kind} REJECTION".strip()
    if state == ST_EMA8_TESTING:
        return "WAIT", "8TCM · EMA8 TESTING"
    if state in (ST_WAITING_FOR_RETRACEMENT, ST_TREND_CONFIRMED):
        label = trend if trend in (TREND_BULLISH, TREND_BEARISH) else direction
        return "WAIT", f"8TCM · {label} TREND · WAITING FOR EMA8 RETRACEMENT".strip(" ·")
    if state == ST_WAITING_FOR_TREND:
        return "WAIT", "8TCM · WAITING FOR TREND"
    return "WAIT", "8TCM · WAITING FOR TREND"


def tcm8_trade_hud(
    cfg: Mark2Config | None,
    last: dict[str, Any] | None,
    *,
    stats: dict[str, Any] | None = None,
    trade: Any = None,
) -> dict[str, Any]:
    """TRADE-screen payload. Off = empty so the old Recon card stays."""
    enabled = tcm8_enabled(cfg)
    exclusive = tcm8_only_mode(cfg)
    empty = {
        "enabled": False,
        "exclusive": False,
        "call": "",
        "badge": "",
        "state": "",
        "reason": "",
        "accept": False,
        "direction": "",
        "htf1h": "",
        "htf4h": "",
        "range": "",
        "quality": "",
        "rejection": "",
        "targetR": 0.0,
        "ema8": 0.0,
        "barrier": "",
        "kickerLong": "",
        "kickerShort": "",
        "bullets": [],
        "checklist": [],
        "next": "",
        "stats": stats or {},
    }
    if not enabled:
        return empty
    row = dict(last or {})
    reason = str(row.get("reason") or "WAIT")
    state = str(row.get("state") or ST_WAITING_FOR_TREND)
    htf1 = str(row.get("htf_1h") or "—")
    htf4 = str(row.get("htf_4h") or "—")
    rang = str(row.get("range_state") or "—")
    checklist = tcm8_live_checklist(row, cfg=cfg, trade=trade)
    nxt = tcm8_next_gate(checklist)
    badge, call = tcm8_state_call(row, trade)
    if (not bool(row.get("accept"))) and reason.startswith("REJECT") and trade is None:
        badge = "BLOCKED"
        call = nxt
    runner = _b(cfg, "ENABLE_8TCM_RUNNER", False)
    classic = _b(cfg, "ENABLE_8TCM_CLASSIC_TARGET", True)
    if runner:
        tgt_line = "RUNNER AFTER PRIMARY KEY-LEVEL TARGET"
    elif classic:
        tgt_line = "CLASSIC TP AT NEXT KEY LEVEL"
    else:
        tgt_line = "PRIMARY TARGET OFF"
    bullets = [
        "STRUCTURE TREND · RETRACE TO EMA8 · TEST · CLOSE REJECT",
        tgt_line,
        "1H IS CONTEXT ONLY · NOT AN ENTRY VETO",
    ]
    return {
        "enabled": True,
        "exclusive": exclusive,
        "call": call,
        "badge": badge,
        "state": state,
        "reason": reason,
        "next": nxt,
        "checklist": checklist,
        "accept": bool(row.get("accept")),
        "direction": str(row.get("direction") or ""),
        "trend": str(row.get("trend") or ""),
        "sequence": str(row.get("sequence") or ""),
        "swings": str(row.get("swings") or ""),
        "htf1h": htf1,
        "htf4h": htf4,
        "range": rang,
        "quality": str(row.get("quality") or ""),
        "rejection": str(row.get("rejection_type") or ""),
        "targetR": float(row.get("target_r") or 0),
        "ema8": float(row.get("ema8") or 0),
        "barrier": str(row.get("primary_target_type") or row.get("barrier_type") or ""),
        "barrierPrice": float(row.get("primary_target_price") or row.get("barrier_price") or 0),
        "pullback": bool(row.get("pullback") or row.get("retracement")),
        "tested": bool(row.get("tested")),
        "kickerLong": "8TCM LONG",
        "kickerShort": "8TCM SHORT",
        "bullets": bullets,
        "stats": stats or {},
    }
