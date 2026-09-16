"""413 LONG — MNQ 1-minute bullish breakout resembling a developing 9/20/50 fan.

Long-only. Does not change sniper / leftover / AI-exit unless the fill is tagged 413_*.
Hard stop never widens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import Mark2Config
from .indicators import atr, ema, macd, rsi
from .types import EngineState, Side

_ET = ZoneInfo("America/New_York")


@dataclass
class Breakout413State:
    armed: bool = False
    waiting_pullback: bool = False
    bars_waited: int = 0
    breakout_high: float = 0.0
    signal_low: float = 0.0
    swing_low: float = 0.0
    trigger_px: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    sequence_id: int = 0
    entries_this_seq: int = 0
    stop_cooldown: int = 0
    last_alert: str = ""
    last_filters: dict[str, bool] = field(default_factory=dict)
    last_reason: str = ""
    seq_9_above_20: bool = False


@dataclass
class Breakout413Scan:
    fire: bool = False
    arm: bool = False
    cancel: bool = False
    fill_now: bool = False
    reason: str = ""
    alert: str = ""
    filters: dict[str, bool] = field(default_factory=dict)
    trigger_px: float = 0.0
    stop: float = 0.0
    target: float = 0.0


def _tick(cfg: Mark2Config) -> float:
    return max(float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25), 0.01)


def _closes(bars: list[dict]) -> list[float]:
    return [float(b.get("close") or 0) for b in bars]


def _bar(bars: list[dict], i: int) -> dict:
    return bars[i]


def _range(bar: dict) -> float:
    return max(float(bar.get("high") or 0) - float(bar.get("low") or 0), 1e-9)


def _body_frac(bar: dict) -> float:
    o = float(bar.get("open") or 0)
    c = float(bar.get("close") or 0)
    return abs(c - o) / _range(bar)


def _close_in_upper_frac(bar: dict) -> float:
    c = float(bar.get("close") or 0)
    lo = float(bar.get("low") or 0)
    return (c - lo) / _range(bar)


def _bullish_bar(bar: dict) -> bool:
    return float(bar.get("close") or 0) > float(bar.get("open") or 0)


def _series_ok(xs: list[float], n: int) -> bool:
    return len(xs) >= n


def _hour_ok(bars: list[dict], cfg: Mark2Config) -> bool:
    start = str(getattr(cfg, "BREAKOUT_413_START_ET", "") or "").strip()
    end = str(getattr(cfg, "BREAKOUT_413_END_ET", "") or "").strip()
    if not start and not end:
        return True
    raw = str((bars[-1] or {}).get("time") or "")
    if not raw:
        return True
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_ET)
        et = ts.astimezone(_ET)
    except ValueError:
        return True
    hm = et.hour * 60 + et.minute

    def _parse(s: str, default: int) -> int:
        if not s:
            return default
        parts = s.replace(".", ":").split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            return h * 60 + m
        except ValueError:
            return default

    a = _parse(start, 0)
    b = _parse(end, 24 * 60)
    if a <= b:
        return a <= hm < b
    return hm >= a or hm < b


def _vol_sma(bars: list[dict], lookback: int = 20) -> float:
    if len(bars) < lookback + 1:
        return 0.0
    chunk = bars[-(lookback + 1) : -1]
    if not chunk:
        return 0.0
    return sum(float(b.get("volume") or 0) for b in chunk) / len(chunk)


def _cross_up(fast: list[float], slow: list[float], *, within: int) -> bool:
    """True if fast crossed above slow on this bar or within `within` prior completed bars."""
    if len(fast) < 2 or len(slow) < 2:
        return False
    start = max(1, len(fast) - 1 - max(0, int(within)))
    for i in range(start, len(fast)):
        if fast[i] > slow[i] and fast[i - 1] <= slow[i - 1]:
            return True
    return False


def evaluate_filters(bars: list[dict], cfg: Mark2Config) -> dict[str, bool]:
    tick = _tick(cfg)
    atr_p = int(getattr(cfg, "ATR_PERIOD", 14) or 14)
    atr_s = atr(bars, atr_p)
    atr_v = float(atr_s[-1]) if atr_s else 0.0
    atr_v = max(atr_v, tick)
    closes = _closes(bars)
    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    last = bars[-1]
    close = float(last.get("close") or 0)
    high = float(last.get("high") or 0)
    low = float(last.get("low") or 0)
    vol = float(last.get("volume") or 0)
    avg_vol = _vol_sma(bars, 20)
    m, sig, hist, hist_d, _x = macd(bars, fast=12, slow=26, signal=9)
    rsi_v = rsi(bars, 14)
    tol50 = float(getattr(cfg, "BREAKOUT_413_EMA50_TOL_ATR", 0.02) or 0.02) * atr_v
    compress_atr = float(getattr(cfg, "EMA_COMPRESSION_ATR", 0.15) or 0.15)
    filters: dict[str, bool] = {}

    enough = len(bars) >= 55 and _series_ok(e9, 6) and _series_ok(e20, 6) and _series_ok(e50, 9)
    filters["data"] = enough
    if not enough:
        return filters

    filters["ema9_cross_20"] = _cross_up(e9, e20, within=5)
    filters["ema9_above_20"] = e9[-1] > e20[-1]
    filters["ema20_vs_50"] = (e20[-1] > e50[-1]) or _cross_up(e20, e50, within=8)
    filters["ema9_rising"] = e9[-1] > e9[-3]
    filters["ema20_rising"] = e20[-1] > e20[-3]
    filters["ema50_flat_or_rising"] = e50[-1] >= (e50[-4] - tol50)
    filters["price_above_emas"] = close > e9[-1] and close > e20[-1] and close > e50[-1]

    prior = bars[-11:-1] if len(bars) >= 11 else bars[:-1]
    prior_high = max(float(b.get("high") or 0) for b in prior) if prior else 0.0
    filters["close_above_10bar_high"] = close > prior_high
    filters["bullish_close"] = _bullish_bar(last)
    filters["body_50"] = _body_frac(last) >= 0.50
    filters["close_upper_25"] = _close_in_upper_frac(last) >= 0.75
    filters["volume_125"] = avg_vol > 0 and vol >= 1.25 * avg_vol

    filters["macd_above_signal"] = m > sig
    filters["macd_hist_up"] = hist > 0 and hist_d > 0
    filters["rsi_52_75"] = 52.0 < rsi_v < 75.0

    spread = max(e9[-1], e20[-1], e50[-1]) - min(e9[-1], e20[-1], e50[-1])
    filters["not_compressed"] = (spread / atr_v) >= compress_atr
    flat_tol = 0.01 * atr_v
    filters["emas_not_flat"] = abs(e9[-1] - e9[-3]) > flat_tol or abs(e20[-1] - e20[-3]) > flat_tol
    filters["bar_not_1_75_atr"] = (high - low) <= 1.75 * atr_v
    filters["session_hours"] = _hour_ok(bars, cfg)

    filters["setup"] = all(
        filters[k]
        for k in (
            "ema9_cross_20",
            "ema9_above_20",
            "ema20_vs_50",
            "ema9_rising",
            "ema20_rising",
            "ema50_flat_or_rising",
            "price_above_emas",
        )
    )
    filters["breakout"] = all(
        filters[k]
        for k in (
            "close_above_10bar_high",
            "bullish_close",
            "body_50",
            "close_upper_25",
            "volume_125",
        )
    )
    filters["momentum"] = all(filters[k] for k in ("macd_above_signal", "macd_hist_up", "rsi_52_75"))
    filters["safety"] = all(
        filters[k]
        for k in ("not_compressed", "emas_not_flat", "bar_not_1_75_atr", "session_hours")
    )
    return filters


def _swing_low(bars: list[dict], n: int = 5) -> float:
    chunk = bars[-n:] if len(bars) >= n else bars
    return min(float(b.get("low") or 0) for b in chunk)


def compute_stop_target(
    *,
    entry: float,
    signal_low: float,
    swing_low: float,
    cfg: Mark2Config,
) -> tuple[float, float, bool]:
    tick = _tick(cfg)
    raw_stop = min(signal_low, swing_low) - 2.0 * tick
    risk = entry - raw_stop
    max_pts = float(getattr(cfg, "BREAKOUT_413_MAX_STOP_PTS", 40.0) or 0.0)
    if max_pts > 0 and risk > max_pts + 1e-9:
        return raw_stop, 0.0, False
    if risk <= tick:
        return raw_stop, 0.0, False
    r_mult = float(getattr(cfg, "BREAKOUT_413_TARGET_R", 2.0) or 2.0)
    target = entry + r_mult * risk
    return raw_stop, target, True


def filter_note(filters: dict[str, bool]) -> str:
    bits = []
    for key, ok in filters.items():
        if key in {"setup", "breakout", "momentum", "safety", "data"}:
            continue
        bits.append(f"{key}={'Y' if ok else 'N'}")
    return "413 LONG · " + " ".join(bits[:12])


def _update_sequence(state: Breakout413State, bars: list[dict]) -> None:
    closes = _closes(bars)
    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    if len(e9) < 2 or len(e20) < 2:
        return
    above = e9[-1] > e20[-1]
    if above and not state.seq_9_above_20:
        state.sequence_id += 1
        state.entries_this_seq = 0
    state.seq_9_above_20 = above


def _cancel(state: Breakout413State, reason: str) -> Breakout413Scan:
    state.armed = False
    state.waiting_pullback = False
    state.bars_waited = 0
    state.trigger_px = 0.0
    state.last_alert = "SETUP_CANCELLED"
    state.last_reason = reason
    return Breakout413Scan(cancel=True, reason=reason, alert="SETUP_CANCELLED", filters=state.last_filters)


def is_rejection_bar(bar: dict, ema9: float, ema20: float, atr_v: float) -> bool:
    if not _bullish_bar(bar):
        return False
    low = float(bar.get("low") or 0)
    close = float(bar.get("close") or 0)
    pad = 0.15 * max(atr_v, 1e-9)
    tagged = low <= ema9 + pad or low <= ema20 + pad
    recovered = close >= min(ema9, ema20)
    return tagged and recovered and close > ema20


def on_completed_bar(
    state: Breakout413State,
    bars: list[dict],
    cfg: Mark2Config,
    *,
    in_trade: bool,
    session_pnl: float,
    enabled: bool,
) -> Breakout413Scan:
    if state.stop_cooldown > 0:
        state.stop_cooldown -= 1
    if not enabled:
        return Breakout413Scan(reason="FILTER_OFF")
    if len(bars) < 55:
        return Breakout413Scan(reason="WARMUP")
    _update_sequence(state, bars)
    if in_trade:
        return Breakout413Scan(reason="IN_TRADE")

    daily = float(getattr(cfg, "BREAKOUT_413_DAILY_LOSS_USD", 0.0) or 0.0)
    if daily > 0 and session_pnl <= -abs(daily):
        return Breakout413Scan(reason="DAILY_LOSS_LIMIT", filters={"daily_loss": False})

    max_per_seq = int(getattr(cfg, "BREAKOUT_413_MAX_PER_SEQUENCE", 2) or 2)
    if state.entries_this_seq >= max_per_seq:
        return Breakout413Scan(reason="SEQUENCE_CAP")
    if state.stop_cooldown > 0:
        return Breakout413Scan(reason="STOP_COOLDOWN")

    closes = _closes(bars)
    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    last = bars[-1]
    close = float(last.get("close") or 0)
    atr_s = atr(bars, 14)
    atr_v = max(float(atr_s[-1]) if atr_s else 0.0, _tick(cfg))
    tick = _tick(cfg)
    mode = str(getattr(cfg, "BREAKOUT_413_MODE", "BREAKOUT") or "BREAKOUT").upper()

    if state.waiting_pullback:
        state.bars_waited += 1
        if close < e20[-1]:
            return _cancel(state, "CLOSE_BELOW_EMA20")
        if len(e9) >= 2 and e9[-1] < e20[-1] and e9[-2] >= e20[-2]:
            return _cancel(state, "EMA9_CROSS_DOWN")
        if close > e20[-1] + 1.25 * atr_v:
            return _cancel(state, "EXTENDED_1_25_ATR")
        if state.bars_waited > 5:
            return _cancel(state, "PULLBACK_EXPIRED")
        if is_rejection_bar(last, e9[-1], e20[-1], atr_v):
            high = float(last.get("high") or 0)
            trigger = high + tick
            stop, target, ok = compute_stop_target(
                entry=trigger,
                signal_low=state.signal_low,
                swing_low=_swing_low(bars, 5),
                cfg=cfg,
            )
            if not ok:
                return _cancel(state, "STOP_TOO_WIDE")
            state.armed = True
            state.waiting_pullback = False
            state.trigger_px = trigger
            state.stop = stop
            state.target = target
            state.last_alert = "SETUP_ARMED"
            state.last_reason = "413_PULLBACK"
            return Breakout413Scan(
                arm=True,
                reason="413_PULLBACK",
                alert="SETUP_ARMED",
                filters=state.last_filters,
                trigger_px=trigger,
                stop=stop,
                target=target,
            )
        return Breakout413Scan(reason="PULLBACK_WAIT", filters=state.last_filters)

    filters = evaluate_filters(bars, cfg)
    state.last_filters = filters
    if not filters.get("data"):
        return Breakout413Scan(reason="WARMUP", filters=filters)
    if not (filters.get("setup") and filters.get("breakout") and filters.get("momentum") and filters.get("safety")):
        fail = [k for k, v in filters.items() if v is False]
        return Breakout413Scan(reason="FILTER:" + ",".join(fail[:6]), filters=filters)

    signal_low = float(last.get("low") or 0)
    swing = _swing_low(bars, 5)
    high = float(last.get("high") or 0)
    trigger = high + tick
    stop, target, ok = compute_stop_target(entry=trigger, signal_low=signal_low, swing_low=swing, cfg=cfg)
    if not ok:
        return Breakout413Scan(reason="STOP_TOO_WIDE", filters=filters)

    state.signal_low = signal_low
    state.swing_low = swing
    state.breakout_high = high
    if mode.startswith("PULL"):
        state.waiting_pullback = True
        state.armed = False
        state.bars_waited = 0
        state.last_alert = "SETUP_ARMED"
        state.last_reason = "413_WAIT_PULLBACK"
        return Breakout413Scan(
            reason="413_WAIT_PULLBACK",
            alert="SETUP_ARMED",
            filters=filters,
            trigger_px=trigger,
            stop=stop,
            target=target,
        )

    state.armed = True
    state.waiting_pullback = False
    state.trigger_px = trigger
    state.stop = stop
    state.target = target
    state.last_alert = "SETUP_ARMED"
    state.last_reason = "413_LONG"
    return Breakout413Scan(
        arm=True,
        reason="413_LONG",
        alert="SETUP_ARMED",
        filters=filters,
        trigger_px=trigger,
        stop=stop,
        target=target,
    )


def tick_should_fill(state: Breakout413State, price: float) -> bool:
    if not state.armed or state.trigger_px <= 0:
        return False
    return float(price) + 1e-12 >= state.trigger_px


def note_fill(state: Breakout413State) -> None:
    state.armed = False
    state.waiting_pullback = False
    state.entries_this_seq += 1
    state.last_alert = "LONG_ENTRY"
    state.trigger_px = 0.0


def note_stop_exit(state: Breakout413State) -> None:
    state.stop_cooldown = 5
    state.armed = False
    state.waiting_pullback = False


def manage_413_hold(
    trade: Any,
    *,
    price: float,
    bars: list[dict] | None,
    cfg: Mark2Config | None,
    ema9: float | None = None,
) -> tuple[bool, str, EngineState]:
    """413 risk: 2R target, +1R BE+1 tick, +1.5R trail EMA9 / 2-bar low. Never widen."""
    px = float(price)
    entry = float(getattr(trade, "entry", 0) or 0)
    hard = float(getattr(trade, "hard_stop", 0) or 0) or float(trade.stop)
    trade.hard_stop = hard
    if Side(trade.side) != Side.LONG:
        if px <= hard + 1e-12:
            return True, "HARD_STOP", EngineState.EXIT
        return False, "", EngineState.TRADE_PROFITABLE

    trade.peak = max(float(getattr(trade, "peak", px) or px), px)
    trade.trough = min(float(getattr(trade, "trough", px) or px), px)
    trade.mfe = max(0.0, float(trade.peak) - entry)
    trade.mae = max(0.0, entry - float(trade.trough))

    if px <= hard + 1e-12:
        return True, "HARD_STOP", EngineState.EXIT

    tick = _tick(cfg) if cfg is not None else 0.25
    risk = max(entry - hard, tick)
    target = float(getattr(trade, "target", 0) or 0)
    if target <= 0:
        r_mult = float(getattr(cfg, "BREAKOUT_413_TARGET_R", 2.0) or 2.0) if cfg else 2.0
        target = entry + r_mult * risk
        trade.target = target
    if px >= target - 1e-12:
        return True, "413_TARGET", EngineState.EXIT

    r_peak = float(trade.mfe) / risk
    protect = hard
    if r_peak >= 1.0:
        protect = max(protect, entry + tick)
        trade.ema_trade_state = "CONFIRMED"
    if r_peak >= 1.5:
        two_bar_low = entry
        if bars and len(bars) >= 2:
            two_bar_low = min(
                float(bars[-1].get("low") or entry),
                float(bars[-2].get("low") or entry),
            )
        trail = two_bar_low - tick
        if ema9 is not None and 0 < float(ema9) < px:
            trail = max(trail, float(ema9) - tick)
        protect = max(protect, trail)
        trade.ema_trade_state = "RUNNER"
    # Never widen: only raise a long stop.
    if protect > float(trade.stop) + 1e-12:
        trade.stop = protect
    if px <= float(trade.stop) + 1e-12:
        reason = "413_BE" if r_peak >= 1.0 and r_peak < 1.5 else "413_TRAIL"
        return True, reason, EngineState.EXIT
    return False, "", EngineState.TRADE_PROFITABLE
