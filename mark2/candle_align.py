"""Completed + forming bar alignment — entries only when candles agree with direction."""

from __future__ import annotations

from .types import Side


def _bar_body(bar: dict) -> tuple[float, float, float]:
    o = float(bar.get("open") or 0)
    c = float(bar.get("close") or 0)
    h = float(bar.get("high") or max(o, c))
    lo = float(bar.get("low") or min(o, c))
    return o, c, max(h - lo, 0.25)


def is_bullish_bar(bar: dict) -> bool:
    o, c, _ = _bar_body(bar)
    return c > o


def is_bearish_bar(bar: dict) -> bool:
    o, c, _ = _bar_body(bar)
    return c < o


def forming_bullish(
    forming: dict | None,
    price: float,
    *,
    min_body_ratio: float = 0.2,
    relax: bool = False,
    relax_direction: bool = False,
) -> bool:
    if not forming:
        return True
    if relax_direction:
        return True
    o, _, span = _bar_body({**forming, "close": price})
    if price <= o:
        return False
    if relax:
        return True
    body = price - o
    return body / span >= min_body_ratio or body >= 0.5


def forming_bearish(
    forming: dict | None,
    price: float,
    *,
    min_body_ratio: float = 0.2,
    relax: bool = False,
    relax_direction: bool = False,
) -> bool:
    if not forming:
        return True
    if relax_direction:
        return True
    o, _, span = _bar_body({**forming, "close": price})
    if price >= o:
        return False
    if relax:
        return True
    body = o - price
    return body / span >= min_body_ratio or body >= 0.5


def count_aligned(completed: list[dict], side: Side, lookback: int) -> int:
    tail = completed[-lookback:] if lookback > 0 else completed
    if side == Side.LONG:
        return sum(1 for b in tail if is_bullish_bar(b))
    if side == Side.SHORT:
        return sum(1 for b in tail if is_bearish_bar(b))
    return 0


def candle_alignment_ok(
    completed_bars: list[dict],
    forming_bar: dict | None,
    price: float,
    side: Side,
    *,
    min_aligned: int,
    lookback: int = 3,
    min_forming_body_ratio: float = 0.2,
    require_tick_velocity: bool = True,
    velocity: float = 0.0,
    min_velocity: float = 0.08,
    relax_forming: bool = False,
    relax_forming_direction: bool = False,
) -> tuple[bool, str]:
    """Return (ok, detail) for logging."""
    if side == Side.NONE:
        return True, ""

    aligned = count_aligned(completed_bars, side, lookback)
    if aligned < min_aligned:
        return False, f"bars={aligned}/{lookback} need>={min_aligned}"

    if side == Side.LONG:
        if not forming_bullish(
            forming_bar,
            price,
            min_body_ratio=min_forming_body_ratio,
            relax=relax_forming,
            relax_direction=relax_forming_direction,
        ):
            return False, "forming_not_bullish"
        if require_tick_velocity and velocity < min_velocity:
            return False, f"vel={velocity:.2f}<{min_velocity}"
    elif side == Side.SHORT:
        if not forming_bearish(
            forming_bar,
            price,
            min_body_ratio=min_forming_body_ratio,
            relax=relax_forming,
            relax_direction=relax_forming_direction,
        ):
            return False, "forming_not_bearish"
        if require_tick_velocity and velocity > -min_velocity:
            return False, f"vel={velocity:.2f}>-{min_velocity}"

    return True, f"bars={aligned}/{lookback}"
