"""EMA crossover strategy — own path when ENABLE_EMA_STRATEGY is on.

Chart: red 9, white 20, blue 50.
Setup is a momentum reversal through an already-spread stack:
separated 20/50 → 9 crosses 20 → 9 later crosses 50.
Tight knots, leftover stacks, and white-only wiggles stay HOLD.
"""

from __future__ import annotations

from dataclasses import dataclass

from .candle_align import is_bearish_bar, is_bullish_bar
from .config import Mark2Config
from .indicators import atr as atr_series
from .indicators import ema, macd, rsi
from .types import EngineState, Side


@dataclass(frozen=True)
class EmaStack:
    ema9: float
    ema20: float
    ema50: float
    prev9: float
    prev20: float
    prev50: float

    @property
    def cluster(self) -> float:
        # Kept for later Red/White vs Red/White+Blue comparison. Not used live.
        vals = (self.ema9, self.ema20, self.ema50)
        return max(vals) - min(vals)


def _closes(bars: list[dict]) -> list[float]:
    return [float(b["close"]) for b in bars if b]


def read_ema_stack(bars: list[dict], cfg: Mark2Config | None = None) -> EmaStack | None:
    fast = int(getattr(cfg, "FAST_EMA", 0) or getattr(cfg, "EMA_FAST", 9) or 9) if cfg else 9
    mid = int(getattr(cfg, "SLOW_EMA", 0) or getattr(cfg, "EMA_MID", 20) or 20) if cfg else 20
    slow = int(getattr(cfg, "REFERENCE_EMA", 0) or getattr(cfg, "EMA_SLOW", 50) or 50) if cfg else 50
    closes = _closes(bars)
    # Trade warmup is red/white only — blue must not delay the first signal.
    if len(closes) < max(fast, mid) + 2:
        return None
    e9 = ema(closes, fast)
    e20 = ema(closes, mid)
    if len(e9) < 2 or len(e20) < 2:
        return None
    e50 = ema(closes, slow)
    if len(e50) < 2:
        return None
    return EmaStack(
        ema9=float(e9[-1]),
        ema20=float(e20[-1]),
        ema50=float(e50[-1]),
        prev9=float(e9[-2]),
        prev20=float(e20[-2]),
        prev50=float(e50[-2]),
    )


def _cluster_limit(cfg: Mark2Config, atr: float) -> float:
    """Knot width is capped. ATR must not turn a waterfall into an intersection."""
    floor = float(getattr(cfg, "EMA_INTERSECT_POINTS", 30.0) or 30.0)
    return max(floor, 0.0)


def _cluster_ok(stack: EmaStack, cfg: Mark2Config, atr: float) -> bool:
    """True when red / white / blue are knotted (the intersection)."""
    return stack.cluster <= _cluster_limit(cfg, atr) + 1e-9


def lines_intersecting(stack: EmaStack, atr: float = 0.0, cfg: Mark2Config | None = None) -> bool:
    if cfg is None:
        cfg = Mark2Config()
    return _cluster_ok(stack, cfg, atr)


def intersection_side(
    stack: EmaStack,
    atr: float = 0.0,
    cfg: Mark2Config | None = None,
) -> Side:
    """When 9/20/50 are knotted, trade the punch — any 20/50 state.

    Red in the middle of the knot still counts. Up = long, down = short.
    """
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return Side.NONE
    if not lines_intersecting(stack, atr, cfg):
        return Side.NONE
    if float(stack.ema9) > float(stack.prev9):
        return Side.LONG
    if float(stack.ema9) < float(stack.prev9):
        return Side.SHORT
    flip = cross_side(stack)
    if flip != Side.NONE:
        return flip
    return Side.LONG if float(stack.ema9) >= float(stack.ema20) else Side.SHORT


def _cluster_width(e9: float, e20: float, e50: float) -> float:
    return max(float(e9), float(e20), float(e50)) - min(float(e9), float(e20), float(e50))


def just_hit_intersection(stack: EmaStack, atr: float = 0.0, cfg: Mark2Config | None = None) -> bool:
    """True on the bar the 9/20/50 knot first comes together."""
    if cfg is None:
        cfg = Mark2Config()
    if not _cluster_ok(stack, cfg, atr):
        return False
    limit = _cluster_limit(cfg, atr)
    prev = _cluster_width(stack.prev9, stack.prev20, stack.prev50)
    return prev > limit + 1e-9


def red_rising(stack: EmaStack) -> bool:
    """Completed/live red is printing higher than the prior bar."""
    return float(stack.ema9) > float(stack.prev9)


def red_falling(stack: EmaStack) -> bool:
    return float(stack.ema9) < float(stack.prev9)


def cross_side(stack: EmaStack) -> Side:
    """Completed-bar red/white state change. Used for exits and short detection."""
    if stack.prev9 <= stack.prev20 and stack.ema9 > stack.ema20:
        return Side.LONG
    if stack.prev9 >= stack.prev20 and stack.ema9 < stack.ema20:
        return Side.SHORT
    return Side.NONE


def _red_above_both(e9: float, e20: float, e50: float) -> bool:
    return float(e9) > float(e20) and float(e9) > float(e50)


def ema_line_lamps(
    price: float,
    ema9: float,
    ema20: float,
    ema50: float,
    atr: float = 0.0,
    near_atr: float = 0.35,
) -> dict:
    """HUD lamps: on when price has passed that EMA, near when inside near_atr."""
    px = float(price)
    room = max(float(near_atr), 0.0) * max(float(atr), 1e-9)

    def _one(level: float) -> tuple[bool, bool]:
        lv = float(level)
        if px <= 0 or lv <= 0:
            return False, False
        passed = px + 1e-12 >= lv
        approaching = (not passed) and (lv - px) <= room + 1e-12
        return passed, approaching

    red, near_red = _one(ema9)
    white, near_white = _one(ema20)
    blue, near_blue = _one(ema50)
    return {
        "red": red,
        "white": white,
        "blue": blue,
        "nearRed": near_red,
        "nearWhite": near_white,
        "nearBlue": near_blue,
    }


def stack_is_bearish(stack: EmaStack) -> bool:
    """White still under blue — 20/50 has not flipped."""
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return False
    return stack.ema20 < stack.ema50 and stack.prev20 < stack.prev50


def stack_is_bullish(stack: EmaStack) -> bool:
    """Red over white over blue — 20/50 has flipped bull."""
    if float(stack.ema50) <= 0:
        return False
    return stack.ema9 > stack.ema20 > stack.ema50


def leftover_long_allowed(cfg: Mark2Config | None) -> bool:
    return cfg is None or bool(getattr(cfg, "EMA_LEFTOVER_LONG", True))


def leftover_stacked_long(stack: EmaStack) -> bool:
    """Already through blue last bar and still stacked — not a fresh 9/50 punch."""
    return red_above_white_and_blue(stack) and float(stack.prev9) > float(stack.prev50)


def red_above_white_and_blue(stack: EmaStack) -> bool:
    """Red is stacked above both slower averages."""
    return _red_above_both(stack.ema9, stack.ema20, stack.ema50)


def red_reached_white_and_blue(stack: EmaStack, cfg: Mark2Config | None = None) -> bool:
    """Red is through or touching white and blue (knot counts)."""
    tick = 0.25
    if cfg is not None:
        tick = max(float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25), 0.25)
    slack = max(tick, float(getattr(cfg, "EMA_THROUGH_SLACK", 0.25) or 0.25) if cfg else tick)
    return float(stack.ema9) + slack >= float(stack.ema20) and float(stack.ema9) + slack >= float(
        stack.ema50
    )


def red_clears_white_and_blue(stack: EmaStack) -> bool:
    """Red finished above white and blue after not being above both."""
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return False
    now = red_above_white_and_blue(stack)
    was = _red_above_both(stack.prev9, stack.prev20, stack.prev50)
    return now and not was


def _red_below_both(e9: float, e20: float, e50: float) -> bool:
    return float(e9) < float(e20) and float(e9) < float(e50)


def red_below_white_and_blue(stack: EmaStack) -> bool:
    """Red is stacked under both slower averages."""
    return _red_below_both(stack.ema9, stack.ema20, stack.ema50)


def red_reached_under_white_and_blue(stack: EmaStack, cfg: Mark2Config | None = None) -> bool:
    """Red is through or touching white and blue from above (knot counts)."""
    tick = 0.25
    if cfg is not None:
        tick = max(float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25), 0.25)
    slack = max(tick, float(getattr(cfg, "EMA_THROUGH_SLACK", 0.25) or 0.25) if cfg else tick)
    return float(stack.ema9) - slack <= float(stack.ema20) and float(stack.ema9) - slack <= float(
        stack.ema50
    )


def red_clears_under_white_and_blue(stack: EmaStack) -> bool:
    """Red finished under white and blue after not being under both."""
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return False
    now = red_below_white_and_blue(stack)
    was = _red_below_both(stack.prev9, stack.prev20, stack.prev50)
    return now and not was


def red_crosses_blue(stack: EmaStack) -> Side:
    """First bar red finishes through blue. Knot leftover already through is NONE."""
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return Side.NONE
    if float(stack.prev9) <= float(stack.prev50) and float(stack.ema9) > float(stack.ema50):
        return Side.LONG
    if float(stack.prev9) >= float(stack.prev50) and float(stack.ema9) < float(stack.ema50):
        return Side.SHORT
    return Side.NONE


def d20_50_points(ema20: float, ema50: float) -> float:
    return abs(float(ema20) - float(ema50))


def separation_atr(ema20: float, ema50: float, atr: float) -> float:
    atr_v = float(atr)
    if atr_v <= 1e-6:
        return 0.0
    return d20_50_points(ema20, ema50) / atr_v


def separation_ok(d20_50: float, atr: float, cfg: Mark2Config | None = None) -> bool:
    """True when 20/50 are spread enough to make a 9/20→9/50 cross meaningful."""
    if cfg is not None and not bool(getattr(cfg, "EMA_REQUIRE_SEP", True)):
        return True
    min_pts = 3.0
    min_atr = 0.20
    if cfg is not None:
        min_pts = float(getattr(cfg, "EMA_MIN_SEP_POINTS", 3.0) or 3.0)
        min_atr = float(getattr(cfg, "EMA_MIN_SEP_ATR", 0.20) or 0.20)
    gap = float(d20_50)
    atr_v = float(atr)
    if atr_v > 1e-6:
        return (gap / atr_v) + 1e-12 >= min_atr
    return gap + 1e-12 >= min_pts


@dataclass
class IntersectionStatus:
    """Live intersection board + fire decision for one side."""

    side: str = ""
    sep_now_atr: float = 0.0
    sep_now_pts: float = 0.0
    d20_50: float = 0.0
    d9_50: float = 0.0
    pre_sep_atr: float = 0.0
    pre_sep_pts: float = 0.0
    sep_ok: bool = False
    hold_ok: bool = True
    tight: bool = True
    cross_920: bool = False
    cross_950: bool = False
    armed_920: bool = False
    fire: bool = False
    reject: str = "NO_SNIPER"
    stage: str = "WAIT_SEP"
    lookback_hits: int = 0
    lookback_bars: int = 0

    def hud(self) -> dict:
        mark = "✓" if self.sep_ok else "✗"
        armed = "ARMED ✓" if self.armed_920 or self.fire else ("TIGHT ✗" if self.tight and self.cross_920 else "WAITING")
        confirm = "FIRED ✓" if self.fire else ("WAITING" if self.armed_920 else "WAITING")
        return {
            "side": self.side,
            "stage": self.stage,
            "sepAtr": round(float(self.pre_sep_atr or self.sep_now_atr), 2),
            "sepNowAtr": round(float(self.sep_now_atr), 2),
            "sepPts": round(float(self.pre_sep_pts or self.sep_now_pts), 2),
            "sepOk": bool(self.sep_ok),
            "sepMark": mark,
            "cross920": "ARMED ✓" if (self.armed_920 or self.fire) else ("TIGHT ✗" if self.cross_920 else "WAITING"),
            "cross950": "GO ✓" if self.fire else ("WAITING" if self.armed_920 else "WAITING"),
            "tight": bool(self.tight),
            "armed920": bool(self.armed_920),
            "fire": bool(self.fire),
            "reject": self.reject,
            "holdHits": int(self.lookback_hits),
            "holdBars": int(self.lookback_bars),
            "armedText": armed,
            "confirmText": confirm,
        }


def ema_fire_gates(
    ix: IntersectionStatus | None,
    *,
    busy: bool = False,
    in_trade: bool = False,
) -> list[dict[str, Any]]:
    """Short list of what still has to happen for a 9/20/50 fire."""
    if ix is None:
        rows = [
            {"id": "spread", "label": "20/50 SPREAD", "status": "wait", "detail": "NEED BARS"},
            {"id": "x920", "label": "9 THROUGH 20", "status": "wait", "detail": ""},
            {"id": "x950", "label": "9 THROUGH 50", "status": "wait", "detail": ""},
            {"id": "fire", "label": "FIRE", "status": "wait", "detail": ""},
        ]
        rows[0]["hot"] = True
        return rows
    spread = "pass" if ix.sep_ok else ("fail" if ix.tight else "wait")
    x920 = "pass" if (ix.armed_920 or ix.fire or ix.cross_920) else "wait"
    if ix.cross_920 and ix.tight and not ix.armed_920 and not ix.fire:
        x920 = "fail"
    x950 = "pass" if ix.fire else ("wait" if ix.armed_920 or ix.cross_920 else "wait")
    if ix.fire:
        fire = "pass"
        fire_d = str(ix.side or "GO")
    elif busy or in_trade:
        fire = "wait"
        fire_d = "SLOT BUSY"
    else:
        fire = "wait"
        fire_d = "1m CLOSE"
    rows = [
        {
            "id": "spread",
            "label": "20/50 SPREAD",
            "status": spread,
            "detail": f"{ix.sep_now_pts:.1f} PTS",
        },
        {
            "id": "x920",
            "label": "9 THROUGH 20",
            "status": x920,
            "detail": str(ix.side or ""),
        },
        {
            "id": "x950",
            "label": "9 THROUGH 50",
            "status": x950,
            "detail": "ARMED" if ix.armed_920 and not ix.fire else "",
        },
        {"id": "fire", "label": "FIRE", "status": fire, "detail": fire_d},
    ]
    hot_set = False
    if ix.fire:
        rows[-1]["hot"] = True
        hot_set = True
    elif ix.armed_920:
        rows[2]["hot"] = True
        hot_set = True
    elif ix.sep_ok and not ix.cross_920:
        rows[1]["hot"] = True
        hot_set = True
    if not hot_set:
        for row in rows:
            if row["status"] == "wait":
                row["hot"] = True
                break
    for row in rows:
        row.setdefault("hot", False)
    return rows


def read_ema_series(bars: list[dict], cfg: Mark2Config | None = None) -> tuple[list[float], list[float], list[float]] | None:
    fast = int(getattr(cfg, "FAST_EMA", 0) or getattr(cfg, "EMA_FAST", 9) or 9) if cfg else 9
    mid = int(getattr(cfg, "SLOW_EMA", 0) or getattr(cfg, "EMA_MID", 20) or 20) if cfg else 20
    slow = int(getattr(cfg, "REFERENCE_EMA", 0) or getattr(cfg, "EMA_SLOW", 50) or 50) if cfg else 50
    closes = _closes(bars)
    if len(closes) < max(fast, mid) + 2:
        return None
    e9 = ema(closes, fast)
    e20 = ema(closes, mid)
    e50 = ema(closes, slow) if len(closes) >= slow + 2 else []
    if len(e9) < 2 or len(e20) < 2 or len(e50) < 2:
        return None
    n = min(len(e9), len(e20), len(e50))
    return [float(x) for x in e9[-n:]], [float(x) for x in e20[-n:]], [float(x) for x in e50[-n:]]


def _last_920_index(e9: list[float], e20: list[float], *, long: bool, end_i: int, max_bars: int) -> int | None:
    start = max(1, end_i - max(1, int(max_bars)))
    for i in range(end_i, start - 1, -1):
        if long:
            if e9[i - 1] <= e20[i - 1] and e9[i] > e20[i]:
                return i
        elif e9[i - 1] >= e20[i - 1] and e9[i] < e20[i]:
            return i
    return None


def _920_still_held(e9: list[float], e20: list[float], *, long: bool, from_i: int, end_i: int) -> bool:
    for i in range(from_i + 1, end_i + 1):
        if long and e9[i - 1] >= e20[i - 1] and e9[i] < e20[i]:
            return False
        if (not long) and e9[i - 1] <= e20[i - 1] and e9[i] > e20[i]:
            return False
    return True


def _sep_lookback(
    e20: list[float],
    e50: list[float],
    *,
    before_i: int,
    atr: float,
    cfg: Mark2Config | None,
) -> tuple[bool, float, int, int]:
    look = 8
    need = 3
    if cfg is not None:
        look = max(1, int(getattr(cfg, "EMA_SEP_LOOKBACK", 8) or 8))
        need = max(1, int(getattr(cfg, "EMA_SEP_MIN_BARS", 3) or 3))
    start = max(0, before_i - look)
    hits = 0
    bars = 0
    pre_pts = d20_50_points(e20[before_i - 1], e50[before_i - 1]) if before_i >= 1 else 0.0
    for j in range(start, before_i):
        bars += 1
        if separation_ok(d20_50_points(e20[j], e50[j]), atr, cfg):
            hits += 1
    if bars >= look:
        return hits >= need, pre_pts, hits, bars
    return separation_ok(pre_pts, atr, cfg), pre_pts, hits, bars


def _status_meters(stack: EmaStack, atr: float) -> IntersectionStatus:
    d20 = d20_50_points(stack.ema20, stack.ema50)
    d9 = abs(float(stack.ema9) - float(stack.ema50))
    sep_now = separation_atr(stack.ema20, stack.ema50, atr)
    return IntersectionStatus(
        sep_now_atr=sep_now,
        sep_now_pts=d20,
        d20_50=d20,
        d9_50=d9,
        pre_sep_atr=sep_now,
        pre_sep_pts=d20,
        tight=sep_now + 1e-12 < 0.20 if atr > 1e-6 else d20 < 3.0,
    )


QUALITY_REJECT_CODES = (
    "REJECT_EMA_COMPRESSION",
    "REJECT_9_20_GAP_TOO_SMALL",
    "REJECT_TOTAL_SPREAD_TOO_SMALL",
    "REJECT_EMA9_NOT_RISING",
    "REJECT_EMA20_NOT_RISING",
    "REJECT_EMA50_FALLING_TOO_FAST",
    "REJECT_SPREAD_NOT_EXPANDING",
    "REJECT_PRICE_BELOW_STRUCTURE",
)


@dataclass(frozen=True)
class LongQualityReport:
    accept: bool
    reason: str
    ema9: float
    ema20: float
    ema50: float
    atr: float
    gap_9_20_atr: float
    gap_20_50_atr: float
    gap_9_50_atr: float
    total_spread_atr: float
    slope9: float
    slope20: float
    slope50: float
    expanding: bool
    knot: bool
    bullish_align: bool
    price: float | None = None

    def log_line(self) -> str:
        decision = "ACCEPT" if self.accept else "REJECT"
        px = "NA" if self.price is None else f"{self.price:.2f}"
        return (
            f"EMA QUALITY LONG {decision} {self.reason}  "
            f"EMA9:{self.ema9:.2f}  EMA20:{self.ema20:.2f}  EMA50:{self.ema50:.2f}  "
            f"ATR:{self.atr:.2f}  Price:{px}  "
            f"gap9/20:{self.gap_9_20_atr:.3f}  gap20/50:{self.gap_20_50_atr:.3f}  "
            f"gap9/50:{self.gap_9_50_atr:.3f}  spread:{self.total_spread_atr:.3f}  "
            f"slope9:{self.slope9:.3f}  slope20:{self.slope20:.3f}  slope50:{self.slope50:.3f}  "
            f"expanding:{'Y' if self.expanding else 'N'}  knot:{'Y' if self.knot else 'N'}  "
            f"bullish:{'Y' if self.bullish_align else 'N'}"
        )


_last_quality_log: tuple | None = None


def _atr_unit(atr: float) -> float:
    return max(float(atr), 1e-9)


def _signed_gap_atr(left: float, right: float, atr: float) -> float:
    return (float(left) - float(right)) / _atr_unit(atr)


def _abs_gap_atr(left: float, right: float, atr: float) -> float:
    return abs(float(left) - float(right)) / _atr_unit(atr)


def _close_from_bars(bars: list[dict] | None) -> float | None:
    if not bars:
        return None
    last = bars[-1] or {}
    close = float(last.get("close") or 0)
    return close if close > 0 else None


def is_ema_compressed(stack: EmaStack, atr: float, cfg: Mark2Config | None = None) -> bool:
    """True when 9/20/50 are knotted vs ATR. Reuses stack.cluster (max-min)."""
    atr_v = float(atr)
    if atr_v <= 1e-6:
        return False
    limit = 0.15
    if cfg is not None:
        limit = float(getattr(cfg, "EMA_COMPRESSION_ATR", 0.15) or 0.15)
    return float(stack.cluster) / atr_v + 1e-12 < limit


def is_bullish_ema_structure(stack: EmaStack) -> bool:
    """Prefer Price path 9>20; do not require 20>50. 9 may already be over 50."""
    if float(stack.ema9) <= float(stack.ema20):
        return False
    return True


def is_bullish_slope_quality(
    stack: EmaStack,
    atr: float,
    cfg: Mark2Config | None = None,
) -> tuple[bool, str]:
    """Slopes are ATR/bar from the existing prev/now EMA pair (no extra indicators)."""
    atr_v = _atr_unit(atr)
    slope9 = (float(stack.ema9) - float(stack.prev9)) / atr_v
    slope20 = (float(stack.ema20) - float(stack.prev20)) / atr_v
    slope50 = (float(stack.ema50) - float(stack.prev50)) / atr_v
    min9 = 0.04
    min20 = -0.03
    max_neg50 = -0.08
    if cfg is not None:
        min9 = float(getattr(cfg, "MIN_EMA9_SLOPE", 0.04) or 0.0)
        raw20 = getattr(cfg, "MIN_EMA20_SLOPE", -0.03)
        min20 = float(-0.03 if raw20 is None else raw20)
        raw50 = getattr(cfg, "MAX_NEGATIVE_EMA50_SLOPE", -0.08)
        max_neg50 = float(-0.08 if raw50 is None else raw50)
    if slope9 + 1e-12 < min9:
        return False, "REJECT_EMA9_NOT_RISING"
    if slope20 + 1e-12 < min20:
        return False, "REJECT_EMA20_NOT_RISING"
    if slope50 + 1e-12 < max_neg50:
        return False, "REJECT_EMA50_FALLING_TOO_FAST"
    return True, ""


def is_ema_expanding_bullishly(
    stack: EmaStack,
    atr: float,
    cfg: Mark2Config | None = None,
    bars: list[dict] | None = None,
) -> bool:
    """9-20 gap opening. 20-50 is not required to fan. One tiny contraction is OK."""
    atr_v = _atr_unit(atr)
    tol = 0.02
    look = 3
    if cfg is not None:
        tol = float(getattr(cfg, "EMA_SPREAD_EXPAND_TOLERANCE_ATR", 0.02) or 0.02)
        look = max(2, int(getattr(cfg, "EMA_SPREAD_LOOKBACK_BARS", 3) or 3))
    now_gap = (float(stack.ema9) - float(stack.ema20)) / atr_v
    prev_gap = (float(stack.prev9) - float(stack.prev20)) / atr_v
    series = read_ema_series(bars, cfg) if bars is not None else None
    if series is None or len(series[0]) < 3:
        return now_gap + 1e-12 >= prev_gap - tol
    e9, e20, _e50 = series
    start = max(0, len(e9) - look)
    gaps = [(float(e9[i]) - float(e20[i])) / atr_v for i in range(start, len(e9))]
    if len(gaps) < 2:
        return now_gap + 1e-12 >= prev_gap - tol
    drops = 0
    for i in range(1, len(gaps)):
        if gaps[i] + 1e-12 < gaps[i - 1] - tol:
            drops += 1
    net_up = gaps[-1] + 1e-12 >= gaps[0] - tol
    return net_up or drops <= 1


def evaluate_ema_long_quality(
    stack: EmaStack,
    cfg: Mark2Config | None = None,
    atr: float = 0.0,
    bars: list[dict] | None = None,
    price: float | None = None,
) -> LongQualityReport:
    """Post-trigger long filter. Toggle off or missing ATR → accept (old behavior)."""
    cfg = cfg or Mark2Config()
    atr_v = float(atr)
    px = price if price is not None else _close_from_bars(bars)
    gap_920 = _signed_gap_atr(stack.ema9, stack.ema20, atr_v if atr_v > 1e-6 else 1.0)
    gap_2050 = _abs_gap_atr(stack.ema20, stack.ema50, atr_v if atr_v > 1e-6 else 1.0)
    gap_950 = _signed_gap_atr(stack.ema9, stack.ema50, atr_v if atr_v > 1e-6 else 1.0)
    spread = float(stack.cluster) / _atr_unit(atr_v if atr_v > 1e-6 else 1.0)
    slope9 = (float(stack.ema9) - float(stack.prev9)) / _atr_unit(atr_v if atr_v > 1e-6 else 1.0)
    slope20 = (float(stack.ema20) - float(stack.prev20)) / _atr_unit(atr_v if atr_v > 1e-6 else 1.0)
    slope50 = (float(stack.ema50) - float(stack.prev50)) / _atr_unit(atr_v if atr_v > 1e-6 else 1.0)
    knot = is_ema_compressed(stack, atr_v, cfg) if atr_v > 1e-6 else False
    expanding = is_ema_expanding_bullishly(stack, atr_v, cfg, bars=bars) if atr_v > 1e-6 else True
    bullish = is_bullish_ema_structure(stack)

    def _report(accept: bool, reason: str) -> LongQualityReport:
        return LongQualityReport(
            accept=accept,
            reason=reason,
            ema9=float(stack.ema9),
            ema20=float(stack.ema20),
            ema50=float(stack.ema50),
            atr=atr_v,
            gap_9_20_atr=gap_920,
            gap_20_50_atr=gap_2050,
            gap_9_50_atr=gap_950,
            total_spread_atr=spread,
            slope9=slope9,
            slope20=slope20,
            slope50=slope50,
            expanding=expanding,
            knot=knot,
            bullish_align=bullish,
            price=px,
        )

    if not bool(getattr(cfg, "ENABLE_EMA_QUALITY_FILTER", True)):
        return _report(True, "FILTER_OFF")
    if atr_v <= 1e-6:
        return _report(True, "SKIP_NO_ATR")

    min_920 = float(getattr(cfg, "MIN_9_20_GAP_ATR", 0.03) or 0.0)
    min_2050 = float(getattr(cfg, "MIN_20_50_GAP_ATR", 0.0) or 0.0)
    min_spread = float(getattr(cfg, "MIN_TOTAL_EMA_SPREAD_ATR", 0.10) or 0.0)
    require_exp = bool(getattr(cfg, "REQUIRE_EXPANDING_SPREAD", True))

    if knot:
        return _report(False, "REJECT_EMA_COMPRESSION")
    if gap_920 + 1e-12 < min_920:
        return _report(False, "REJECT_9_20_GAP_TOO_SMALL")
    if spread + 1e-12 < min_spread or (min_2050 > 0 and gap_2050 + 1e-12 < min_2050):
        return _report(False, "REJECT_TOTAL_SPREAD_TOO_SMALL")
    slope_ok, slope_why = is_bullish_slope_quality(stack, atr_v, cfg)
    if not slope_ok:
        return _report(False, slope_why)
    if require_exp and not expanding:
        return _report(False, "REJECT_SPREAD_NOT_EXPANDING")
    if px is not None:
        cluster_lo = min(float(stack.ema9), float(stack.ema20), float(stack.ema50))
        cluster_hi = max(float(stack.ema9), float(stack.ema20), float(stack.ema50))
        on_tape = (px + 2.0 * atr_v) >= cluster_lo and (px - 4.0 * atr_v) <= cluster_hi
        if on_tape and px + 1e-12 < float(stack.ema20):
            return _report(False, "REJECT_PRICE_BELOW_STRUCTURE")
    if not bullish:
        return _report(False, "REJECT_9_20_GAP_TOO_SMALL")
    return _report(True, "ACCEPT")


def _log_long_quality(report: LongQualityReport) -> None:
    global _last_quality_log
    key = (
        round(report.ema9, 4),
        round(report.ema20, 4),
        round(report.ema50, 4),
        report.reason,
        report.accept,
    )
    if key == _last_quality_log:
        return
    _last_quality_log = key
    print(report.log_line(), flush=True)


def _apply_long_quality_gate(
    st: IntersectionStatus,
    stack: EmaStack,
    cfg: Mark2Config | None,
    atr: float,
    bars: list[dict] | None = None,
) -> IntersectionStatus:
    """After the existing long trigger fires, quality may still block the entry."""
    if not st.fire:
        return st
    report = evaluate_ema_long_quality(stack, cfg, atr, bars=bars)
    if report.accept:
        return st
    st.fire = False
    st.reject = report.reason
    st.stage = "QUALITY"
    return st


def _classify_intersection_stack_core(
    stack: EmaStack,
    cfg: Mark2Config | None,
    atr: float,
    *,
    long: bool,
) -> IntersectionStatus:
    """Two-bar stack path: 9/50 confirm + pre-bar 20/50 separation."""
    st = _status_meters(stack, atr)
    st.side = "LONG" if long else "SHORT"
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        st.reject = "BLUE_WARMUP"
        st.stage = "WAIT_SEP"
        return st

    st.cross_920 = cross_side(stack) == (Side.LONG if long else Side.SHORT)
    st.cross_950 = red_crosses_blue(stack) == (Side.LONG if long else Side.SHORT)
    pre_pts = d20_50_points(stack.prev20, stack.prev50)
    st.pre_sep_pts = pre_pts
    st.pre_sep_atr = separation_atr(stack.prev20, stack.prev50, atr)
    st.sep_ok = separation_ok(pre_pts, atr, cfg)
    st.tight = not st.sep_ok
    ordered = float(stack.prev20) < float(stack.prev50) if long else float(stack.prev20) > float(stack.prev50)
    through_20 = float(stack.ema9) > float(stack.ema20) if long else float(stack.ema9) < float(stack.ema20)

    if long and red_above_white_and_blue(stack):
        leftover = leftover_stacked_long(stack)
        if leftover and not leftover_long_allowed(cfg):
            st.reject = "LEFTOVER_OFF"
            st.stage = "STALE"
            st.fire = False
            return st
        if leftover or bool(getattr(cfg, "EMA_LONG_SNIPER", True) if cfg else True):
            if red_rising(stack):
                st.fire = True
                st.reject = ""
                st.stage = "READY"
                st.armed_920 = True
                st.tight = False
                return st
            st.reject = "RED_FALLING"
            st.stage = "STALE"
            return st
        st.reject = "SNIPER_OFF"
        st.stage = "STALE"
        return st
    if (not long) and red_below_white_and_blue(stack) and not st.cross_950:
        st.reject = "STACK_STALE"
        st.stage = "STALE"
        return st

    if st.cross_920 and not st.cross_950:
        already_through_blue = (
            float(stack.prev9) > float(stack.prev50) if long else float(stack.prev9) < float(stack.prev50)
        )
        if already_through_blue:
            if long and leftover_stacked_long(stack) and not leftover_long_allowed(cfg):
                st.reject = "LEFTOVER_OFF"
                st.stage = "STALE"
                st.fire = False
                return st
            if long and red_above_white_and_blue(stack) and red_rising(stack):
                st.fire = True
                st.reject = ""
                st.stage = "READY"
                st.armed_920 = True
                st.tight = False
                return st
            st.reject = "RED_FALLING" if long and not red_rising(stack) else "NO_SNIPER"
            st.stage = "STALE"
            return st
        st.armed_920 = st.sep_ok and ordered
        st.reject = "TIGHT" if not st.sep_ok else "WHITE_ONLY"
        st.stage = "WAIT_9_50" if st.armed_920 else "TIGHT"
        return st

    if not st.cross_950:
        if long and float(stack.ema9) < float(stack.ema20) < float(stack.ema50) and st.sep_ok:
            st.stage = "WAIT_9_20"
            st.reject = "NO_SNIPER"
            return st
        if (not long) and float(stack.ema9) > float(stack.ema20) > float(stack.ema50) and st.sep_ok:
            st.stage = "WAIT_9_20"
            st.reject = "NO_SNIPER"
            return st
        st.reject = "NO_SNIPER"
        st.stage = "WAIT_SEP"
        return st

    # 9/50 is only a confirm after 9 is already through 20 (or 9/20 this bar).
    if not (through_20 or st.cross_920):
        st.reject = "NO_SNIPER"
        st.stage = "WAIT_SEP"
        return st
    if long and float(stack.prev9) > float(stack.prev50):
        if leftover_stacked_long(stack) and not leftover_long_allowed(cfg):
            st.reject = "LEFTOVER_OFF"
            st.stage = "STALE"
            st.fire = False
            return st
        if red_above_white_and_blue(stack) and red_rising(stack):
            st.fire = True
            st.reject = ""
            st.stage = "READY"
            st.armed_920 = True
            st.tight = False
            return st
        st.reject = "RED_FALLING" if not red_rising(stack) else "NO_SNIPER"
        st.stage = "STALE"
        return st
    if (not long) and float(stack.prev9) < float(stack.prev50):
        st.reject = "STACK_STALE"
        st.stage = "STALE"
        return st
    if not ordered:
        st.reject = "TIGHT"
        st.stage = "TIGHT"
        st.tight = True
        return st
    if not st.sep_ok:
        st.reject = "TIGHT"
        st.stage = "TIGHT"
        return st
    require_bear = bool(getattr(cfg, "EMA_LONG_REQUIRES_BEARISH", False)) if cfg and long else False
    require_bull = bool(getattr(cfg, "EMA_SHORT_REQUIRES_BULLISH", False)) if cfg and not long else False
    if require_bear and not (float(stack.prev20) < float(stack.prev50) or float(stack.ema20) <= float(stack.ema50)):
        st.reject = "NOT_BEARISH"
        st.stage = "WAIT_9_50"
        return st
    if require_bull and not (float(stack.prev20) > float(stack.prev50) or float(stack.ema20) >= float(stack.ema50)):
        st.reject = "NOT_BULLISH"
        st.stage = "WAIT_9_50"
        return st
    if long and cfg is not None and not bool(getattr(cfg, "EMA_LONG_SNIPER", True)):
        st.reject = "SNIPER_OFF"
        st.stage = "STALE"
        st.fire = False
        return st
    st.armed_920 = True
    st.fire = True
    st.reject = ""
    st.stage = "READY"
    st.tight = False
    return st


def _classify_intersection_stack(
    stack: EmaStack,
    cfg: Mark2Config | None,
    atr: float,
    *,
    long: bool,
    bars: list[dict] | None = None,
) -> IntersectionStatus:
    st = _classify_intersection_stack_core(stack, cfg, atr, long=long)
    if long:
        return _apply_long_quality_gate(st, stack, cfg, atr, bars=bars)
    return st


def _classify_intersection_bars_core(
    stack: EmaStack,
    bars: list[dict],
    cfg: Mark2Config | None,
    atr: float,
    *,
    long: bool,
) -> IntersectionStatus:
    series = read_ema_series(bars, cfg)
    if series is None:
        return _classify_intersection_stack_core(stack, cfg, atr, long=long)
    e9, e20, e50 = series
    end_i = len(e9) - 1
    max_bars = 16
    if cfg is not None:
        max_bars = max(2, int(getattr(cfg, "EMA_SETUP_MAX_BARS", 16) or 16))
    st = _classify_intersection_stack_core(stack, cfg, atr, long=long)
    c20 = _last_920_index(e9, e20, long=long, end_i=end_i, max_bars=max_bars)
    if c20 is None:
        return st
    if not _920_still_held(e9, e20, long=long, from_i=c20, end_i=end_i):
        return st
    # 9 must still have been on the far side of 50 when 9/20 printed.
    if long and e9[c20 - 1] > e50[c20 - 1]:
        if leftover_stacked_long(stack) and not leftover_long_allowed(cfg):
            st.cross_920 = True
            st.reject = "LEFTOVER_OFF"
            st.stage = "STALE"
            st.fire = False
            st.armed_920 = False
            return st
        if red_above_white_and_blue(stack) and red_rising(stack):
            st.cross_920 = True
            st.fire = True
            st.reject = ""
            st.stage = "READY"
            st.armed_920 = True
            st.tight = False
            return st
        st.cross_920 = True
        st.reject = "RED_FALLING" if not red_rising(stack) else "NO_SNIPER"
        st.stage = "STALE"
        st.fire = False
        st.armed_920 = False
        return st
    if (not long) and e9[c20 - 1] < e50[c20 - 1]:
        st.cross_920 = True
        st.reject = "STACK_STALE"
        st.stage = "STALE"
        st.fire = False
        st.armed_920 = False
        return st
    hold_ok, pre_pts, hits, bars_n = _sep_lookback(e20, e50, before_i=c20, atr=atr, cfg=cfg)
    ordered = e20[c20 - 1] < e50[c20 - 1] if long else e20[c20 - 1] > e50[c20 - 1]
    st.cross_920 = True
    st.pre_sep_pts = pre_pts
    st.pre_sep_atr = (pre_pts / atr) if atr > 1e-6 else 0.0
    st.sep_ok = hold_ok and ordered
    st.tight = not st.sep_ok
    st.hold_ok = hold_ok
    st.lookback_hits = hits
    st.lookback_bars = bars_n
    st.armed_920 = bool(st.sep_ok)
    cross_950 = False
    if long:
        cross_950 = e9[end_i - 1] <= e50[end_i - 1] and e9[end_i] > e50[end_i]
    else:
        cross_950 = e9[end_i - 1] >= e50[end_i - 1] and e9[end_i] < e50[end_i]
    st.cross_950 = cross_950
    if not st.sep_ok:
        st.fire = False
        st.reject = "TIGHT"
        st.stage = "TIGHT"
        return st
    if not cross_950:
        st.fire = False
        st.reject = "WHITE_ONLY"
        st.stage = "WAIT_9_50"
        return st
    if long and not red_rising(stack):
        st.fire = False
        st.reject = "RED_FALLING"
        st.stage = "WAIT_9_50"
        return st
    if (not long) and not red_falling(stack):
        st.fire = False
        st.reject = "RED_RISING"
        st.stage = "WAIT_9_50"
        return st
    st.fire = True
    st.reject = ""
    st.stage = "READY"
    st.tight = False
    return st


def _classify_intersection_bars(
    stack: EmaStack,
    bars: list[dict],
    cfg: Mark2Config | None,
    atr: float,
    *,
    long: bool,
) -> IntersectionStatus:
    st = _classify_intersection_bars_core(stack, bars, cfg, atr, long=long)
    if long:
        return _apply_long_quality_gate(st, stack, cfg, atr, bars=bars)
    return st


def intersection_status(
    stack: EmaStack | None,
    cfg: Mark2Config | None = None,
    atr: float = 0.0,
    bars: list[dict] | None = None,
) -> IntersectionStatus:
    """HUD + decision for the active intersection side."""
    if stack is None or float(getattr(stack, "ema50", 0) or 0) <= 0:
        return IntersectionStatus(reject="BLUE_WARMUP", stage="WAIT_SEP")
    if bars is not None and len(bars) >= 4:
        long_s = _classify_intersection_bars(stack, bars, cfg, atr, long=True)
        short_s = _classify_intersection_bars(stack, bars, cfg, atr, long=False)
    else:
        long_s = _classify_intersection_stack(stack, cfg, atr, long=True)
        short_s = _classify_intersection_stack(stack, cfg, atr, long=False)
    if long_s.fire:
        return long_s
    if short_s.fire:
        return short_s
    if long_s.armed_920:
        return long_s
    if short_s.armed_920:
        return short_s
    if float(stack.ema9) <= float(stack.ema20):
        return long_s
    return short_s


def red_on_blue_trajectory(stack: EmaStack, atr: float = 0.0, cfg: Mark2Config | None = None, *, long: bool = True) -> bool:
    """Red is through white, still on the far side of blue, and closing on blue.

    Near = remaining gap <= EMA_BLUE_APPROACH_ATR. About-to-cross = the same
    red velocity on the next bar would clear blue. Flattening or turning away
    is not a trajectory.
    """
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return False
    atr_v = max(float(atr), 1e-9)
    near_mult = float(getattr(cfg, "EMA_BLUE_APPROACH_ATR", 0.35) or 0.35) if cfg else 0.35
    red_delta = float(stack.ema9) - float(stack.prev9)
    if long:
        if stack.ema9 <= stack.ema20 or stack.ema9 >= stack.ema50:
            return False
        gap = float(stack.ema50) - float(stack.ema9)
        prev_gap = float(stack.prev50) - float(stack.prev9)
        if red_delta <= 0 or gap >= prev_gap:
            return False
        near = gap <= (near_mult * atr_v) + 1e-12
        would_cross = (float(stack.ema9) + red_delta) >= float(stack.ema50) - 1e-12
        return near or would_cross
    if stack.ema9 >= stack.ema20 or stack.ema9 <= stack.ema50:
        return False
    gap = float(stack.ema9) - float(stack.ema50)
    prev_gap = float(stack.prev9) - float(stack.prev50)
    if red_delta >= 0 or gap >= prev_gap:
        return False
    near = gap <= (near_mult * atr_v) + 1e-12
    would_cross = (float(stack.ema9) + red_delta) <= float(stack.ema50) + 1e-12
    return near or would_cross


def long_sniper_reason(
    stack: EmaStack,
    cfg: Mark2Config | None = None,
    *,
    bias: str = "",
    atr: float = 0.0,
    bars: list[dict] | None = None,
) -> str:
    """Empty string = take the long. Otherwise the ignore tag.

    Spread 20/50 first, then 9 crosses 20, then 9 crosses 50. Already-stacked
    longs (9 above white and blue, still rising) are also a fire.
    """
    if cfg is not None and not bool(getattr(cfg, "EMA_LONG_SNIPER", True)):
        if leftover_stacked_long(stack) and leftover_long_allowed(cfg):
            pass
        else:
            return "SNIPER_OFF"
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return "BLUE_WARMUP"
    if not red_rising(stack):
        return "RED_FALLING"
    if bars is not None and len(bars) >= 4:
        st = _classify_intersection_bars(stack, bars, cfg, atr, long=True)
    else:
        st = _classify_intersection_stack(stack, cfg, atr, long=True, bars=bars)
    if st.fire or str(st.reject or "").startswith("REJECT_"):
        _log_long_quality(evaluate_ema_long_quality(stack, cfg, atr, bars=bars))
    return st.reject


def short_sniper_reason(
    stack: EmaStack,
    cfg: Mark2Config | None = None,
    *,
    bias: str = "",
    atr: float = 0.0,
    bars: list[dict] | None = None,
) -> str:
    """Empty string = take the short. Otherwise the ignore tag.

    Spread 20/50 first, then 9 crosses 20 down, then 9 crosses 50 down.
    Leftover already-under and knot wiggles stay off.
    """
    if cfg is not None and not bool(getattr(cfg, "EMA_SHORT_SNIPER", True)):
        return "SHORT_OFF"
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return "BLUE_WARMUP"
    if bars is not None and len(bars) >= 4:
        st = _classify_intersection_bars(stack, bars, cfg, atr, long=False)
    else:
        st = _classify_intersection_stack(stack, cfg, atr, long=False)
    return st.reject


def short_intersect_reason(
    stack: EmaStack,
    cfg: Mark2Config | None = None,
    *,
    atr: float = 0.0,
) -> str:
    """Empty string = take the bearish intersection short.

    Same print as the long: red finishes through white AND blue, just down.
    """
    if cfg is not None and not bool(getattr(cfg, "EMA_INTERSECT_SHORT", True)):
        return "SHORT_OFF"
    if float(stack.ema50) <= 0 or float(stack.prev50) <= 0:
        return "BLUE_WARMUP"
    if cfg is None or not lines_intersecting(stack, atr, cfg):
        return "NO_INTERSECT"
    if red_clears_under_white_and_blue(stack):
        return ""
    return "NO_SNIPER"


def rsi_bull_long_reason(
    bars: list[dict],
    stack: EmaStack,
    cfg: Mark2Config | None = None,
    *,
    bias: str = "",
) -> str:
    """Empty string = take the bullish-stack long. Otherwise the ignore tag.

    First bar red finishes through white AND blue, with red still rising.
    Already-stacked leftover is not a new long.
    """
    if cfg is not None and not bool(getattr(cfg, "EMA_RSI_LONG", True)):
        return "RSI_LONG_OFF"
    if not stack_is_bullish(stack):
        return "NOT_BULLISH"
    if not red_rising(stack):
        return "RED_FALLING"
    if red_clears_white_and_blue(stack):
        return ""
    if leftover_stacked_long(stack) or red_above_white_and_blue(stack):
        return "LEFTOVER_OFF"
    return "NO_SNIPER"


def stack_lock_should_clear(stack: EmaStack | None) -> bool:
    """True when the one-long-per-stack lock must drop.

    Dip under white/blue, or a brand-new through-both punch.
    """
    if stack is None:
        return True
    if not red_above_white_and_blue(stack):
        return True
    return red_clears_white_and_blue(stack)


def is_choppy_regime(regime: str = "") -> bool:
    """White-only longs. CHAOTIC is directional — through white and blue."""
    return str(regime or "").upper() == "CHOPPY"


def chop_long_reason(stack: EmaStack, cfg: Mark2Config | None = None) -> str:
    """Empty string = take the choppy red/white long."""
    if cfg is not None and not bool(getattr(cfg, "EMA_CHOP_LONG", True)):
        return "CHOP_OFF"
    if cross_side(stack) != Side.LONG:
        return "NO_WHITE_CROSS"
    if not red_rising(stack):
        return "RED_FALLING"
    return ""


def bullish_chop_hold(regime: str = "", bias: str = "") -> bool:
    tape = str(regime or "").upper()
    return str(bias or "").upper() == "BULLISH" and tape in ("CHOPPY", "CHAOTIC")


def short_stack_lock_should_clear(stack: EmaStack | None) -> bool:
    """True when the one-short-per-punch lock must drop."""
    if stack is None:
        return True
    if red_rising(stack) and float(stack.ema9) >= float(stack.ema20):
        return True
    return red_clears_under_white_and_blue(stack)


def bullish_fade_short_reason(
    stack: EmaStack,
    cfg: Mark2Config | None = None,
    *,
    bias: str = "",
    atr: float = 0.0,
    rsi: float | None = None,
    rsi_prev: float | None = None,
    rsi_peak: float = 0.0,
    regime: str = "",
    fade_ready: bool = True,
) -> str:
    """Empty string = take the bullish fade short. Otherwise the ignore tag.

    After the long is out, wait. Do not reverse on that white-down bar.
    Fire when red finishes under white AND blue — the intersection
    punching down. A leftover already-under stack is not a new short.
    """
    if cfg is not None and not bool(getattr(cfg, "EMA_BULL_FADE_SHORT", True)):
        return "FADE_SHORT_OFF"
    if str(bias or "").upper() != "BULLISH":
        return "NOT_BULLISH"
    if not fade_ready:
        return "WAIT_BREAK"
    if not red_falling(stack):
        return "RED_RISING"
    if not rsi_dying_down(rsi, rsi_prev, rsi_peak, cfg):
        return "RSI_NOT_DYING"
    if red_clears_under_white_and_blue(stack):
        return ""
    return "NO_INTERSECT"


def rsi_dying_down(
    rsi_now: float | None,
    rsi_prev: float | None,
    rsi_peak: float = 0.0,
    cfg: Mark2Config | None = None,
) -> bool:
    """True when completed RSI has turned down off its peak."""
    if rsi_now is None:
        return False
    now = float(rsi_now)
    prev = float(rsi_prev) if rsi_prev is not None else now
    peak = max(float(rsi_peak or 0.0), now, prev)
    fade = 5.0
    if cfg is not None:
        fade = float(getattr(cfg, "CHOP_RSI_FADE", 5.0) or 5.0)
    return now < prev - 1e-9 and now <= peak - fade + 1e-9


def chop_white_exit(side: Side, ema9: float | None, ema20: float | None) -> bool:
    """Completed red lost white — flatten a chop long."""
    if ema9 is None or ema20 is None:
        return False
    if side == Side.LONG:
        return float(ema9) < float(ema20)
    if side == Side.SHORT:
        return float(ema9) > float(ema20)
    return False


def _is_chop_cross(trade) -> bool:
    return str(getattr(trade, "ema_entry_tag", "") or "") == "EMA_CHOP_LONG"


def chop_target_points(cfg: Mark2Config | None = None, qty: int = 1) -> float:
    """$150 take-profit on a chop long, in points."""
    usd = 150.0
    if cfg is not None:
        usd = float(getattr(cfg, "CHOP_TARGET_USD", 150.0) or 150.0)
    pv = 2.0
    if cfg is not None:
        pv = max(float(getattr(cfg, "POINT_VALUE", 2.0) or 2.0), 1e-9)
    return usd / (pv * max(1, int(qty or 1)))


def ema_long_signal_why(
    stack: EmaStack,
    cfg: Mark2Config | None = None,
    *,
    bias: str = "",
    atr: float = 0.0,
    regime: str = "",
    bars: list[dict] | None = None,
) -> tuple[str, str]:
    """(why, reject). Spread structure, then 9/20, then 9/50."""
    if is_choppy_regime(regime) and bool(getattr(cfg, "EMA_CHOP_LONG", False) if cfg else False):
        chop = chop_long_reason(stack, cfg)
        if chop == "":
            return "EMA_CHOP_LONG", ""
        return "", chop
    sniper = long_sniper_reason(stack, cfg, bias=bias, atr=atr, bars=bars)
    if sniper == "":
        return "EMA_INTERSECTION_LONG", ""
    if bool(getattr(cfg, "EMA_RSI_LONG", False) if cfg else False):
        bull = rsi_bull_long_reason([], stack, cfg, bias=bias)
        if bull == "":
            return "EMA_RSI_LONG", ""
        if sniper == "NOT_BEARISH":
            return "", bull if bull != "NOT_BULLISH" else sniper
    return "", sniper or "no_cross"


def ema_tape_ok(regime: str = "", cfg: Mark2Config | None = None) -> tuple[bool, str]:
    """CHOPPY uses red/white-only longs. CHAOTIC and directional tape use sniper/bull."""
    return True, ""


def ema_long_arm_ok(
    stack: EmaStack | None,
    why: str,
    cfg: Mark2Config | None = None,
    *,
    stack_taken: bool = False,
    completed: EmaStack | None = None,
    live_tick: bool = False,
    regime: str = "",
    bias: str = "",
    atr: float = 0.0,
    bars: list[dict] | None = None,
) -> tuple[bool, str]:
    """Second gate. Bar-close, live scan, and arm must all pass this.

    Empty reason + True = fire. Otherwise the ignore tag.
    """
    tape_ok, tape_why = ema_tape_ok(regime, cfg)
    if not tape_ok:
        return False, tape_why
    if stack is None:
        return False, "ema_warmup"
    if (
        is_choppy_regime(regime)
        and bool(getattr(cfg, "EMA_CHOP_LONG", False) if cfg else False)
        and str(why or "").upper() not in ("", "EMA_CHOP_LONG")
    ):
        return False, "CHOPPY"
    if not red_rising(stack):
        return False, "RED_FALLING"
    one_per = cfg is None or bool(getattr(cfg, "EMA_ONE_PER_STACK", True))
    taken = bool(stack_taken) and one_per and not stack_lock_should_clear(stack)
    if taken and red_above_white_and_blue(stack):
        return False, "STACK_USED"
    tag = str(why or "").upper()
    if not tag:
        tag, reject = ema_long_signal_why(stack, cfg, bias=bias, atr=atr, regime=regime, bars=bars)
        if not tag:
            return False, reject or "NO_SNIPER"
    if live_tick and tag == "EMA_RSI_LONG":
        return False, "BULL_WAIT_CLOSE"
    if live_tick and tag in ("EMA_SNIPER_LONG", "EMA_INTERSECTION_LONG"):
        done = completed
        if done is None or not red_above_white_and_blue(done):
            return False, "WAIT_CLOSE"
        done_taken = (
            bool(stack_taken)
            and (cfg is None or bool(getattr(cfg, "EMA_ONE_PER_STACK", True)))
            and not stack_lock_should_clear(done)
        )
        if done_taken and red_above_white_and_blue(done):
            return False, "STACK_USED"
    if live_tick and tag == "EMA_CHOP_LONG":
        done = completed
        if done is None or cross_side(done) != Side.LONG:
            return False, "WAIT_CLOSE"
    if tag == "EMA_CHOP_LONG":
        if not is_choppy_regime(regime):
            return False, "WHITE_ONLY"
        if taken and float(stack.ema9) > float(stack.ema20):
            return False, "STACK_USED"
        if chop_long_reason(stack, cfg) != "":
            return False, chop_long_reason(stack, cfg)
        return True, ""
    if tag in ("EMA_SNIPER_LONG", "EMA_INTERSECTION_LONG"):
        reject = long_sniper_reason(stack, cfg, bias=bias, atr=atr, bars=bars)
        if reject:
            return False, reject
        return True, ""
    if tag == "EMA_RSI_LONG":
        bull = rsi_bull_long_reason(bars or [], stack, cfg, bias=bias)
        if bull:
            return False, bull
        return True, ""
    return False, "NO_SNIPER"


def ema_long_decision(
    stack: EmaStack | None,
    cfg: Mark2Config | None = None,
    *,
    bias: str = "",
    atr: float = 0.0,
    stack_taken: bool = False,
    completed: EmaStack | None = None,
    live_tick: bool = False,
    regime: str = "",
    bars: list[dict] | None = None,
) -> tuple[bool, str, str]:
    """(fire, reason, why). Shared product decision for tests and engine."""
    tape_ok, tape_why = ema_tape_ok(regime, cfg)
    if not tape_ok:
        return False, tape_why, ""
    if stack is None:
        return False, "ema_warmup", ""
    why, reject = ema_long_signal_why(stack, cfg, bias=bias, atr=atr, regime=regime, bars=bars)
    if not why:
        return False, reject or "no_cross", ""
    ok, reason = ema_long_arm_ok(
        stack,
        why,
        cfg,
        stack_taken=stack_taken,
        completed=completed,
        live_tick=live_tick,
        regime=regime,
        bias=bias,
        atr=atr,
        bars=bars,
    )
    return ok, reason, why


def ema_short_arm_ok(
    stack: EmaStack | None,
    why: str,
    cfg: Mark2Config | None = None,
    *,
    stack_taken: bool = False,
    completed: EmaStack | None = None,
    live_tick: bool = False,
    bias: str = "",
    atr: float = 0.0,
    rsi: float | None = None,
    rsi_prev: float | None = None,
    rsi_peak: float = 0.0,
    regime: str = "",
    fade_ready: bool = True,
) -> tuple[bool, str]:
    """Gate for the bullish fade short. Generic shorts stay on EMA_ALLOW_SHORT."""
    tag = str(why or "").upper()
    if tag in ("", "EMA_SNIPER_SHORT", "EMA_INTERSECTION_SHORT", "EMA_INTERSECT_SHORT"):
        if stack is None:
            return False, "ema_warmup"
        if not red_falling(stack):
            return False, "RED_RISING"
        reject = short_sniper_reason(stack, cfg, bias=bias, atr=atr)
        if reject:
            return False, reject
        if tag == "EMA_INTERSECT_SHORT":
            irej = short_intersect_reason(stack, cfg, atr=atr)
            if irej:
                return False, irej
        if live_tick:
            done = completed
            if done is None:
                return False, "WAIT_CLOSE"
            done_rej = short_sniper_reason(done, cfg, bias=bias, atr=atr)
            if done_rej:
                return False, "WAIT_CLOSE" if done_rej != "STACK_STALE" else done_rej
        return True, ""
    if tag != "EMA_FADE_SHORT":
        return True, ""
    if stack is None:
        return False, "ema_warmup"
    if not red_falling(stack):
        return False, "RED_RISING"
    taken = bool(stack_taken) and not short_stack_lock_should_clear(stack)
    if taken:
        return False, "STACK_USED"
    reject = bullish_fade_short_reason(
        stack,
        cfg,
        bias=bias,
        atr=atr,
        rsi=rsi,
        rsi_prev=rsi_prev,
        rsi_peak=rsi_peak,
        regime=regime,
        fade_ready=fade_ready,
    )
    if reject:
        return False, reject
    if live_tick:
        done = completed
        if done is None:
            return False, "WAIT_CLOSE"
        done_reject = bullish_fade_short_reason(
            done,
            cfg,
            bias=bias,
            atr=atr,
            rsi=rsi,
            rsi_prev=rsi_prev,
            rsi_peak=rsi_peak,
            regime=regime,
            fade_ready=fade_ready,
        )
        if done_reject:
            return False, "WAIT_CLOSE"
    return True, ""


def crossover_note(side: Side, stack: EmaStack, cfg: Mark2Config | None = None) -> str:
    if side == Side.LONG:
        if cfg is None or bool(getattr(cfg, "EMA_LONG_SNIPER", True)):
            if stack.ema9 <= stack.ema50:
                return "BULLISH CROSS CONFIRMED (RED THROUGH WHITE, BLUE IN TRAJECTORY)"
            return "BULLISH CROSS CONFIRMED (RED THROUGH WHITE+BLUE)"
        return "BULLISH CROSS CONFIRMED"
    if side == Side.SHORT:
        return "BEARISH CROSS CONFIRMED"
    return ""


def atr14(bars: list[dict], cfg: Mark2Config | None = None) -> float:
    period = int(getattr(cfg, "ATR_PERIOD", 14) or 14) if cfg else 14
    series = atr_series(bars, period)
    if not series:
        return 0.0
    return float(series[-1])


def extension_metrics(ref_price: float, ema20: float, atr: float) -> dict:
    ext_pts = abs(float(ref_price) - float(ema20))
    atr_v = max(float(atr), 1e-9)
    return {
        "extensionPoints": round(ext_pts, 4),
        "extensionATR": round(ext_pts / atr_v, 4),
        "atr14": round(float(atr), 4),
        "refPrice": round(float(ref_price), 4),
        "ema20": round(float(ema20), 4),
    }


def bars_are_sequential(prev_time: str, cur_time: str) -> bool:
    """True when both times are missing (unknown) or current is strictly later."""
    prev_s = str(prev_time or "").strip()
    cur_s = str(cur_time or "").strip()
    if not prev_s or not cur_s:
        return True
    return cur_s > prev_s


def ema_classic_stop(entry: float, side: Side, cfg: Mark2Config | None = None) -> float:
    """10-point hard stop from the 10-5 exit."""
    tick = 0.25
    if cfg is not None:
        tick = max(float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25), 0.25)
    pts = 10.0
    if cfg is not None:
        pts = float(getattr(cfg, "EMA_HARD_STOP_POINTS", 10.0) or 10.0)
    gap = max(tick * 4, pts)
    if side == Side.LONG:
        return float(entry) - gap
    return float(entry) + gap


def ema_atr_stop(entry: float, side: Side, atr: float, cfg: Mark2Config) -> float:
    """Hard stop. 10-5 exit uses 10 points; otherwise 1.5 ATR with a 20-pt floor."""
    if bool(getattr(cfg, "EMA_CLASSIC_EXIT", False)):
        return ema_classic_stop(entry, side, cfg)
    tick = max(float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25), 0.25)
    mult = float(getattr(cfg, "CATASTROPHIC_STOP_ATR", 0) or 1.50)
    min_pts = float(getattr(cfg, "EMA_MIN_STOP_POINTS", 20.0) or 0.0)
    gap = max(tick * 4, float(atr) * mult, min_pts)
    if side == Side.LONG:
        return float(entry) - gap
    return float(entry) + gap


def more_protective_stop(side: Side, initial: float, trail: float) -> float:
    if side == Side.LONG:
        return max(float(initial), float(trail))
    return min(float(initial), float(trail))


def _tick_size(cfg: Mark2Config | None = None) -> float:
    if cfg is None:
        return 0.25
    return max(float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25), 0.25)


def green_target_tagged(trade, price: float) -> bool:
    tgt = float(getattr(trade, "target", 0) or 0)
    entry = float(getattr(trade, "entry", 0) or 0)
    if tgt <= 0:
        return False
    if bool(getattr(trade, "target_touched", False)):
        return True
    side = getattr(trade, "side", Side.NONE)
    px = float(price)
    peak = float(getattr(trade, "peak", px) or px)
    if side == Side.LONG:
        if tgt <= entry + 1e-12:
            return False
        return px + 1e-12 >= tgt or peak + 1e-12 >= tgt
    if side == Side.SHORT:
        if entry <= 0 or tgt >= entry - 1e-12:
            return False
        return px - 1e-12 <= tgt or peak - 1e-12 <= tgt
    return False


def _green_trail_pts(trade, cfg: Mark2Config | None = None) -> float:
    tip = float(getattr(trade, "tip_trail_pts", 0) or 0)
    if tip > 0:
        return tip
    if cfg is not None:
        return float(getattr(cfg, "RUNNER_TRAIL_POINTS", 5.5) or 5.5)
    return 5.5


def green_floor_is_live(trade, cfg: Mark2Config | None = None) -> bool:
    """Purple becomes a live stop only after price has traded through the green line."""
    if not bool(getattr(trade, "target_touched", False)):
        return False
    tgt = float(getattr(trade, "target", 0) or 0)
    if tgt <= 0:
        return False
    tick = _tick_size(cfg)
    peak = float(getattr(trade, "peak", 0) or 0)
    side = getattr(trade, "side", Side.NONE)
    if side == Side.LONG:
        return peak + 1e-12 >= tgt + tick
    if side == Side.SHORT:
        return peak - 1e-12 <= tgt - tick
    return False


def lock_stop_at_green_target(trade, *, price: float, protect: float, cfg: Mark2Config | None = None) -> float:
    """Once price tags the green target, that price is the floor. Trail can only tighten from there."""
    tgt = float(getattr(trade, "target", 0) or 0)
    if tgt <= 0 or not green_target_tagged(trade, price):
        return float(protect)
    trade.target_touched = True
    trade.runner_trail_on = True
    side = trade.side
    trail_pts = _green_trail_pts(trade, cfg)
    peak = float(getattr(trade, "peak", price) or price)
    if side == Side.LONG:
        trail = peak - trail_pts
        return more_protective_stop(side, more_protective_stop(side, protect, tgt), trail)
    trail = peak + trail_pts
    return more_protective_stop(side, more_protective_stop(side, protect, tgt), trail)


def green_target_exit_reason(trade, *, price: float, protect: float, cfg: Mark2Config | None = None) -> str:
    """Tagging green arms purple. It is not an exit. Climb first, then the floor is live."""
    if not bool(getattr(trade, "target_touched", False)):
        return ""
    tgt = float(getattr(trade, "target", 0) or 0)
    if tgt <= 0:
        return ""
    tick = _tick_size(cfg)
    px = float(price)
    side = trade.side
    if not green_floor_is_live(trade, cfg):
        trail_pts = _green_trail_pts(trade, cfg)
        if side == Side.LONG and px <= tgt - trail_pts:
            return "FLOOR"
        if side == Side.SHORT and px >= tgt + trail_pts:
            return "FLOOR"
        return ""
    if side == Side.LONG:
        if protect > tgt + tick * 0.51 and px <= protect + 1e-12:
            return "RUNNER_TRAIL"
        if px <= tgt - tick:
            return "FLOOR"
        return ""
    if protect < tgt - tick * 0.51 and px >= protect - 1e-12:
        return "RUNNER_TRAIL"
    if px >= tgt + tick:
        return "FLOOR"
    return ""


def _is_bull_scalp(trade) -> bool:
    return str(getattr(trade, "ema_entry_tag", "") or "") == "EMA_RSI_LONG"


def _peak_open_usd(trade, cfg: Mark2Config | None = None) -> float:
    pv = max(float(getattr(cfg, "POINT_VALUE", 2.0) or 2.0), 1e-9) if cfg else 2.0
    qty = max(1, int(getattr(trade, "qty", 1) or 1))
    mfe = max(0.0, float(getattr(trade, "mfe", 0) or 0))
    return mfe * pv * qty


def _open_usd(trade, price: float, cfg: Mark2Config | None = None) -> float:
    pv = max(float(getattr(cfg, "POINT_VALUE", 2.0) or 2.0), 1e-9) if cfg else 2.0
    qty = max(1, int(getattr(trade, "qty", 1) or 1))
    entry = float(getattr(trade, "entry", 0) or 0)
    side = getattr(trade, "side", Side.NONE)
    if side == Side.LONG:
        pts = float(price) - entry
    elif side == Side.SHORT:
        pts = entry - float(price)
    else:
        pts = 0.0
    return pts * pv * qty


def account_equity_usd(cfg: Mark2Config | None = None, equity: float | None = None) -> float:
    live = float(equity or 0.0)
    start = 250.0
    if cfg is not None:
        start = float(getattr(cfg, "STARTING_EQUITY_USD", 250.0) or 250.0)
    if live > 1.0:
        return live
    return start


def grow_mode_active(cfg: Mark2Config | None = None, equity: float | None = None) -> bool:
    if cfg is None or not bool(getattr(cfg, "ENABLE_GROW_MODE", False)):
        return False
    until = float(getattr(cfg, "GROW_UNTIL_USD", 600.0) or 600.0)
    return account_equity_usd(cfg, equity) + 1e-9 < until


def grow_keep_usd(peak_usd: float, cfg: Mark2Config | None = None) -> float:
    """80% of a $50+ peak. Runner floor takes over once it is larger."""
    peak = float(peak_usd)
    grab = 50.0
    frac = 0.80
    if cfg is not None:
        grab = float(getattr(cfg, "GROW_GRAB_USD", 50.0) or 50.0)
        frac = float(getattr(cfg, "GROW_KEEP_FRAC", 0.80) or 0.80)
    if peak + 1e-9 < grab:
        return 0.0
    keep = peak * frac
    runner = profit_keep_usd(peak, cfg)
    return max(keep, runner)


def _bar_high(bar: dict) -> float:
    o = float(bar.get("open") or 0)
    c = float(bar.get("close") or 0)
    return float(bar.get("high") or max(o, c))


def _bar_low(bar: dict) -> float:
    o = float(bar.get("open") or 0)
    c = float(bar.get("close") or 0)
    return float(bar.get("low") or min(o, c))


def trailing_adverse_bars(side: Side, bars: list[dict] | None) -> list[dict]:
    """Newest-first stack of reds (long) or greens (short) at the end of the tape."""
    if not bars:
        return []
    out: list[dict] = []
    for bar in reversed(bars):
        if side == Side.LONG and is_bearish_bar(bar):
            out.append(bar)
        elif side == Side.SHORT and is_bullish_bar(bar):
            out.append(bar)
        else:
            break
    out.reverse()
    return out


def adverse_stack_exit(
    side: Side,
    bars: list[dict] | None,
    peak_px: float,
    peak_usd: float,
    atr: float,
    cfg: Mark2Config | None = None,
) -> bool:
    """Peak then consistent adverse candles with a real giveback — leave before the hard stop."""
    need = 3
    min_usd = 20.0
    give_atr = 0.25
    tick = 0.25
    if cfg is not None:
        need = max(2, int(getattr(cfg, "ADVERSE_STACK_BARS", 3) or 3))
        min_usd = float(getattr(cfg, "ADVERSE_STACK_MIN_USD", 20.0) or 20.0)
        give_atr = float(getattr(cfg, "ADVERSE_STACK_GIVE_ATR", 0.25) or 0.25)
        tick = max(float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25), 0.25)
    if peak_usd + 1e-9 < min_usd:
        return False
    stack = trailing_adverse_bars(side, bars)
    if len(stack) < need:
        return False
    stack = stack[-need:]
    last_close = float(stack[-1].get("close") or 0)
    min_give = max(tick * 8, float(atr) * give_atr)
    if side == Side.LONG:
        highs = [_bar_high(b) for b in stack]
        fading = all(highs[i] <= highs[i - 1] + tick + 1e-12 for i in range(1, len(highs)))
        given = float(peak_px) - last_close
    elif side == Side.SHORT:
        lows = [_bar_low(b) for b in stack]
        fading = all(lows[i] + 1e-12 >= lows[i - 1] - tick for i in range(1, len(lows)))
        given = last_close - float(peak_px)
    else:
        return False
    return fading and given + 1e-12 >= min_give


def _update_runner_stall(trade, completed_anchor: float | None) -> int:
    peak_now = float(getattr(trade, "peak", 0) or 0)
    last = float(getattr(trade, "last_peak", 0) or 0)
    if abs(peak_now - last) > 1e-9:
        trade.stall_score = 0.0
        trade.last_peak = peak_now
        return 0
    if completed_anchor is not None:
        prev_anchor = float(getattr(trade, "runner_anchor", 0) or 0)
        if abs(float(completed_anchor) - prev_anchor) > 1e-9:
            trade.stall_score = float(getattr(trade, "stall_score", 0) or 0) + 1.0
            trade.runner_anchor = float(completed_anchor)
    return int(getattr(trade, "stall_score", 0) or 0)


def profit_keep_usd(peak_usd: float, cfg: Mark2Config | None = None) -> float:
    """$80 floor at $100, scaling to ~$550 at $600. 0 below $100 so the trade can grow."""
    if cfg is None:
        return 0.0
    peak = float(peak_usd)
    arm = float(getattr(cfg, "DOLLAR_LOCK_1_TRIGGER", 100.0) or 100.0)
    if peak + 1e-9 < arm:
        return 0.0
    keep_arm = float(getattr(cfg, "DOLLAR_LOCK_1_PROFIT", 80.0) or 80.0)
    keep_hi = float(getattr(cfg, "RUNNER_KEEP_HIGH_USD", 550.0) or 550.0)
    ref = float(getattr(cfg, "RUNNER_KEEP_HIGH_PEAK_USD", 600.0) or 600.0)
    span = max(ref - arm, 1e-9)
    t = (peak - arm) / span
    lock = keep_arm + t * (keep_hi - keep_arm)
    cap = peak * 0.95
    return min(max(0.0, lock), cap)


def profit_keep_frac(peak_usd: float, cfg: Mark2Config | None = None) -> float:
    if peak_usd <= 0:
        return 0.0
    return profit_keep_usd(peak_usd, cfg) / peak_usd


def profit_keep_lock_price(
    trade,
    cfg: Mark2Config | None = None,
    *,
    state: str = "",
) -> float | None:
    """Sniper CONFIRMED / RUNNER floors. Bull scalp never uses this."""
    if cfg is None:
        return None
    if _is_bull_scalp(trade) and not bool(getattr(cfg, "BULL_USE_SNIPER_DOLLAR_LOCK", False)):
        return None
    peak_usd = _peak_open_usd(trade, cfg)
    lock_usd = profit_keep_usd(peak_usd, cfg)
    if lock_usd <= 0:
        return None
    pv = max(float(getattr(cfg, "POINT_VALUE", 2.0) or 2.0), 1e-9)
    qty = max(1, int(getattr(trade, "qty", 1) or 1))
    lock_pts = min(lock_usd, peak_usd) / (pv * qty)
    entry = float(getattr(trade, "entry", 0) or 0)
    side = getattr(trade, "side", Side.NONE)
    if side == Side.LONG:
        return entry + lock_pts
    if side == Side.SHORT:
        return entry - lock_pts
    return None


def apply_profit_keep_stop(trade, protect: float, cfg: Mark2Config | None = None) -> float:
    lock = profit_keep_lock_price(trade, cfg)
    if lock is None:
        return float(protect)
    side = getattr(trade, "side", Side.NONE)
    return more_protective_stop(side, protect, lock)


def runner_tip_trail_pts(peak_usd: float, stall_bars: int, cfg: Mark2Config | None = None) -> float:
    """7.5 off the tip at $100. Wider as the run grows. Closes in after a stall."""
    arm = 100.0
    start = 7.5
    wide_hi = 25.0
    tight = 3.0
    stall_need = 4
    if cfg is not None:
        arm = float(getattr(cfg, "TIP_TRAIL_ARM_USD", 100.0) or 100.0)
        start = float(getattr(cfg, "TIP_TRAIL_START_POINTS", 7.5) or 7.5)
        wide_hi = float(getattr(cfg, "TIP_TRAIL_HIGH_POINTS", 25.0) or 25.0)
        tight = float(getattr(cfg, "TIP_TRAIL_STALL_POINTS", 3.0) or 3.0)
        stall_need = max(1, int(getattr(cfg, "TIP_TRAIL_STALL_BARS", 4) or 4))
    peak = float(peak_usd)
    if peak + 1e-9 < arm:
        return 0.0
    ref = 600.0
    if cfg is not None:
        ref = float(getattr(cfg, "RUNNER_KEEP_HIGH_PEAK_USD", 600.0) or 600.0)
    t = min(1.0, (peak - arm) / max(ref - arm, 1e-9))
    wide = start + t * (wide_hi - start)
    bars = max(0, int(stall_bars))
    if bars < stall_need:
        return wide
    stall_t = min(1.0, (bars - stall_need + 1) / 4.0)
    return max(tight, wide + stall_t * (tight - wide))


def runner_structure_failed(
    side: Side,
    ema9: float | None,
    ema20: float | None,
    ema50: float | None,
) -> bool:
    """Completed-bar red lost both white and blue."""
    if ema9 is None or ema20 is None or ema50 is None:
        return False
    if float(ema50) <= 0:
        return False
    if side == Side.LONG:
        return float(ema9) < float(ema20) and float(ema9) < float(ema50)
    if side == Side.SHORT:
        return float(ema9) > float(ema20) and float(ema9) > float(ema50)
    return False


def max_entry_extension_atr(cfg: Mark2Config | None) -> float:
    if cfg is None:
        return 0.60
    return float(getattr(cfg, "MAX_ENTRY_EXTENSION_ATR", 0.60) or 0.60)


def entry_extension_ok(
    ref_price: float,
    ema20: float,
    atr: float,
    cfg: Mark2Config,
) -> tuple[bool, dict]:
    """Immediate-entry gate. Uses signal-bar close vs EMA20 / ATR. Checked before order."""
    metrics = extension_metrics(ref_price, ema20, atr)
    limit = max_entry_extension_atr(cfg)
    metrics["maxExtensionATR"] = limit
    return metrics["extensionATR"] <= limit + 1e-12, metrics


def signed_extension_metrics(price: float, ema20: float, atr: float, side: Side) -> dict:
    """Long: price - EMA20. Short: EMA20 - price. Negative means the wrong side of white."""
    atr_v = max(float(atr), 1e-9)
    if side == Side.LONG:
        pts = float(price) - float(ema20)
    elif side == Side.SHORT:
        pts = float(ema20) - float(price)
    else:
        pts = abs(float(price) - float(ema20))
    return {
        "currentExtensionPoints": round(pts, 4),
        "currentExtensionATR": round(pts / atr_v, 4),
        "onSideOfEma20": pts >= -1e-12,
    }


def pullback_zone_ok(
    side: Side,
    price: float,
    ema20: float,
    atr: float,
    cfg: Mark2Config | None = None,
) -> tuple[bool, dict]:
    """True when price is on the trade side of EMA20 and within MAX_ENTRY_EXTENSION_ATR."""
    limit = max_entry_extension_atr(cfg)
    metrics = signed_extension_metrics(price, ema20, atr, side)
    metrics["maxExtensionATR"] = limit
    ok = bool(metrics["onSideOfEma20"]) and metrics["currentExtensionATR"] <= limit + 1e-12
    return ok, metrics


def ema_structure_valid(side: Side, stack: EmaStack, cfg: Mark2Config | None = None) -> bool:
    """Pending long stays valid while red > white. Sniper also needs white still under blue."""
    if side == Side.LONG:
        if stack.ema9 <= stack.ema20:
            return False
        if cfg is not None and bool(getattr(cfg, "EMA_LONG_SNIPER", True)):
            return stack.ema20 < stack.ema50
        return True
    if side == Side.SHORT:
        return stack.ema9 < stack.ema20
    return False


@dataclass
class EmaPullbackSetup:
    direction: Side
    signal_price: float
    signal_bar_time: str
    signal_ts: float
    ema9: float
    ema20: float
    atr: float
    extension_atr: float
    bars_waited: int = 0


def indicator_snapshot(bars: list[dict], cfg: Mark2Config | None = None) -> dict:
    """RSI / MACD / EMA values on the last completed bar. For logs, not gates."""
    period = int(getattr(cfg, "RSI_PERIOD", 14) or 14) if cfg else 14
    rsi_v = rsi(bars, period)
    m, sig, hist, _d, cross = macd(
        bars,
        fast=int(getattr(cfg, "MACD_FAST", 12) or 12) if cfg else 12,
        slow=int(getattr(cfg, "MACD_SLOW", 26) or 26) if cfg else 26,
        signal=int(getattr(cfg, "MACD_SIGNAL", 9) or 9) if cfg else 9,
    )
    stack = read_ema_stack(bars, cfg)
    last = bars[-1] if bars else {}
    close = float(last.get("close") or 0) if last else 0.0
    atr_v = atr14(bars, cfg)
    white = 0.0 if stack is None else float(stack.ema20)
    ext = extension_metrics(close, white, atr_v) if stack is not None else {}
    red = None if stack is None else round(stack.ema9, 4)
    blu = None if stack is None else round(stack.ema50, 4)
    return {
        "rsi": round(float(rsi_v), 2),
        "rsi14": round(float(rsi_v), 2),
        "macd": round(float(m), 4),
        "macdLine": round(float(m), 4),
        "macdSignal": round(float(sig), 4),
        "macdHist": round(float(hist), 4),
        "macdHistogram": round(float(hist), 4),
        "macdCross": cross,
        "red": red,
        "white": None if stack is None else round(white, 4),
        "blue": blu,
        "ema9": red,
        "ema20": None if stack is None else round(white, 4),
        "ema50": blu,
        "ema9MinusEMA20": None if stack is None else round(float(stack.ema9) - white, 4),
        "atr14": round(atr_v, 4),
        "extensionPoints": ext.get("extensionPoints"),
        "extensionATR": ext.get("extensionATR"),
        "barClose": close,
        "barTime": str(last.get("time") or "") if last else "",
    }


EMA_DATASET_KEYS = (
    "timestamp",
    "side",
    "action",
    "price",
    "ema9",
    "ema20",
    "ema50",
    "ema9MinusEMA20",
    "atr14",
    "extensionPoints",
    "extensionATR",
    "rsi14",
    "macdLine",
    "macdSignal",
    "macdHistogram",
    "bias",
    "regime",
    "barsSincePreviousCross",
    "tradeState",
    "mfePoints",
    "mfeATR",
    "maePoints",
    "maeATR",
    "highestPriceSinceEntry",
    "lowestPriceSinceEntry",
    "currentProtectiveStop",
    "preCrossSepATR",
    "preCrossSepPts",
    "sepNowATR",
    "ixStage",
    "ixTight",
)


def ema_dataset_row(
    bars: list[dict],
    cfg: Mark2Config | None,
    *,
    side: str,
    action: str,
    price: float,
    timestamp: float = 0.0,
    bias: str = "",
    regime: str = "",
    bars_since: int = 0,
    trade_state: str = "WAITING",
    trade=None,
    atr_used: float | None = None,
    extra: dict | None = None,
) -> dict:
    """One research row for every EMA log event. RSI/MACD/blue/bias/regime are log-only."""
    snap = indicator_snapshot(bars, cfg)
    atr_v = float(atr_used) if atr_used is not None else float(snap.get("atr14") or 0.0)
    white = snap.get("ema20")
    if white is None:
        ext_pts = None
        ext_atr = None
    else:
        em = extension_metrics(float(price), float(white), atr_v)
        ext_pts = em["extensionPoints"]
        ext_atr = em["extensionATR"]
    mfe = mae = hi = lo = stop = None
    mfe_atr = mae_atr = None
    if trade is not None:
        atr_e = max(float(getattr(trade, "atr_at_entry", 0) or 0), 1e-9)
        mfe = round(float(getattr(trade, "mfe", 0) or 0), 4)
        mae = round(float(getattr(trade, "mae", 0) or 0), 4)
        mfe_atr = round(mfe / atr_e, 4)
        mae_atr = round(mae / atr_e, 4)
        hi = float(getattr(trade, "peak", 0) or 0)
        lo = float(getattr(trade, "trough", 0) or 0)
        stop = float(getattr(trade, "stop", 0) or 0)
        if not trade_state or trade_state == "WAITING":
            trade_state = str(getattr(trade, "ema_trade_state", "") or trade_state)
    row = {
        "timestamp": timestamp,
        "side": side,
        "action": action,
        "price": float(price),
        "ema9": snap.get("ema9"),
        "ema20": snap.get("ema20"),
        "ema50": snap.get("ema50"),
        "ema9MinusEMA20": snap.get("ema9MinusEMA20"),
        "atr14": round(atr_v, 4),
        "extensionPoints": ext_pts,
        "extensionATR": ext_atr,
        "rsi14": snap.get("rsi14"),
        "macdLine": snap.get("macdLine"),
        "macdSignal": snap.get("macdSignal"),
        "macdHistogram": snap.get("macdHistogram"),
        "bias": bias,
        "regime": regime,
        "barsSincePreviousCross": int(bars_since),
        "tradeState": trade_state,
        "mfePoints": mfe,
        "mfeATR": mfe_atr,
        "maePoints": mae,
        "maeATR": mae_atr,
        "highestPriceSinceEntry": hi,
        "lowestPriceSinceEntry": lo,
        "currentProtectiveStop": stop,
        "barTime": snap.get("barTime"),
        "barClose": snap.get("barClose"),
        "preCrossSepATR": None,
        "preCrossSepPts": None,
        "sepNowATR": None,
        "ixStage": "",
        "ixTight": None,
    }
    stack = read_ema_stack(bars, cfg)
    if stack is not None:
        ix = intersection_status(stack, cfg, atr_v, bars=bars)
        row["preCrossSepATR"] = round(float(ix.pre_sep_atr), 4)
        row["preCrossSepPts"] = round(float(ix.pre_sep_pts), 4)
        row["sepNowATR"] = round(float(ix.sep_now_atr), 4)
        row["ixStage"] = ix.stage
        row["ixTight"] = bool(ix.tight)
    if extra:
        for k, v in extra.items():
            if k not in row:
                row[k] = v
    return row


def rsi_macd_ok(side: Side, bars: list[dict], cfg: Mark2Config) -> tuple[bool, str]:
    """Legacy RSI/MACD gate. Unused live; kept for later comparison."""
    rsi_v = rsi(bars, int(getattr(cfg, "RSI_PERIOD", 14) or 14))
    _m, _s, hist, _d, cross = macd(
        bars,
        fast=int(getattr(cfg, "MACD_FAST", 12) or 12),
        slow=int(getattr(cfg, "MACD_SLOW", 26) or 26),
        signal=int(getattr(cfg, "MACD_SIGNAL", 9) or 9),
    )
    ob = float(getattr(cfg, "RSI_OB_LEVEL", 75.0) or 75.0)
    os_lv = float(getattr(cfg, "RSI_OS_LEVEL", 25.0) or 25.0)
    if side == Side.LONG:
        if rsi_v >= ob:
            return False, "rsi_overbought"
        if hist <= 0 and cross != "bull":
            return False, "macd_not_bull"
        return True, "rsi_macd_long"
    if side == Side.SHORT:
        if rsi_v <= os_lv:
            return False, "rsi_oversold"
        if hist >= 0 and cross != "bear":
            return False, "macd_not_bear"
        return True, "rsi_macd_short"
    return False, "no_side"


def _bars_rsi_pair(
    bars: list[dict],
    cfg: Mark2Config | None,
    rsi_now: float | None,
    rsi_prev: float | None,
) -> tuple[float | None, float | None]:
    if rsi_now is not None:
        return rsi_now, rsi_prev
    if not bars:
        return None, None
    now = float(indicator_snapshot(bars, cfg).get("rsi") or 0)
    prev = now
    if len(bars) >= 2:
        prev = float(indicator_snapshot(bars[:-1], cfg).get("rsi") or 0)
    return now, prev


def ema_entry_signal(
    bars: list[dict],
    cfg: Mark2Config,
    *,
    atr: float = 0.0,
    bias: str = "",
    regime: str = "",
    rsi: float | None = None,
    rsi_prev: float | None = None,
    rsi_peak: float = 0.0,
    fade_ready: bool = True,
) -> tuple[Side, str]:
    tape_ok, tape_why = ema_tape_ok(regime, cfg)
    if not tape_ok:
        return Side.NONE, tape_why
    rsi_now, rsi_was = _bars_rsi_pair(bars, cfg, rsi, rsi_prev)
    peak = max(float(rsi_peak or 0), float(rsi_now or 0), float(rsi_was or 0))

    def _fade(stack: EmaStack) -> str:
        return bullish_fade_short_reason(
            stack,
            cfg,
            bias=bias,
            atr=atr,
            rsi=rsi_now,
            rsi_prev=rsi_was,
            rsi_peak=peak,
            regime=regime,
            fade_ready=fade_ready,
        )

    stack = read_ema_stack(bars, cfg)
    if stack is None:
        return Side.NONE, "ema_warmup"
    if is_choppy_regime(regime) and bool(getattr(cfg, "EMA_CHOP_LONG", False)):
        chop = chop_long_reason(stack, cfg)
        if chop == "":
            return Side.LONG, "EMA_CHOP_LONG"
    fade = _fade(stack)
    if fade == "":
        return Side.SHORT, "EMA_FADE_SHORT"
    long_on = bool(getattr(cfg, "EMA_LONG_SNIPER", True))
    short_on = bool(getattr(cfg, "EMA_SHORT_SNIPER", True)) and bool(
        getattr(cfg, "EMA_ALLOW_SHORT", False)
    )
    long_reject = long_sniper_reason(stack, cfg, bias=bias, atr=atr, bars=bars) if long_on else "NO_SNIPER"
    short_reject = short_sniper_reason(stack, cfg, bias=bias, atr=atr, bars=bars) if short_on else "SHORT_OFF"
    if long_reject == "" and short_reject == "":
        if red_falling(stack):
            return Side.SHORT, "EMA_INTERSECTION_SHORT"
        if red_rising(stack):
            return Side.LONG, "EMA_INTERSECTION_LONG"
        return Side.NONE, "RED_FALLING"
    if long_reject == "":
        return Side.LONG, "EMA_INTERSECTION_LONG"
    if short_reject == "":
        return Side.SHORT, "EMA_INTERSECTION_SHORT"
    if bool(getattr(cfg, "EMA_RSI_LONG", False)):
        rsi_reject = rsi_bull_long_reason(bars, stack, cfg, bias=bias)
        if rsi_reject == "":
            return Side.LONG, "EMA_RSI_LONG"
    if long_reject in (
        "WHITE_ONLY",
        "STACK_STALE",
        "STALE_BLUE",
        "TIGHT",
        "RED_FALLING",
        "BLUE_WARMUP",
        "NO_SNIPER",
    ):
        return Side.NONE, long_reject
    if short_reject in ("WHITE_ONLY", "STACK_STALE", "STALE_BLUE", "TIGHT", "BLUE_WARMUP"):
        return Side.NONE, short_reject
    return Side.NONE, long_reject or short_reject or "no_cross"


def _ema_engine_state(trade) -> EngineState:
    if bool(getattr(trade, "target_touched", False)) or bool(getattr(trade, "runner_trail_on", False)):
        return EngineState.RUNNER_MANAGEMENT
    st = str(getattr(trade, "ema_trade_state", "") or "")
    ai = str(getattr(trade, "ai_exit_state", "") or "")
    if st in ("RUNNER", "RUNNER_HEALTHY", "RUNNER_WATCH", "RUNNER_REACCELERATING", "MOMENTUM_DYING"):
        return EngineState.RUNNER_MANAGEMENT
    if st in ("CONFIRMED", "CONFIRMED_TREND", "TRADE_PROTECTED"):
        return EngineState.TRADE_PROFITABLE
    if ai in ("RUNNER_HEALTHY", "RUNNER_WATCH", "RUNNER_REACCELERATING", "MOMENTUM_DYING"):
        return EngineState.RUNNER_MANAGEMENT
    if ai in ("TRADE_PROTECTED",):
        return EngineState.TRADE_PROFITABLE
    return EngineState.TRADE_INITIAL


def signed_red_white_spread_atr(side: Side, ema9: float, ema20: float, atr: float) -> float:
    """Positive = stacked with the trade. Zero/negative = converged or crossed."""
    atr_v = max(float(atr), 1e-9)
    red = float(ema9)
    white = float(ema20)
    if side == Side.LONG:
        return (red - white) / atr_v
    if side == Side.SHORT:
        return (white - red) / atr_v
    return abs(red - white) / atr_v


def choppy_exit_points(
    cfg: Mark2Config | None = None,
    *,
    regime: str = "",
    trade=None,
) -> tuple[float, float] | None:
    """(target_pts, trail_pts) when the tape is choppy, else None.

    Choppy entries are off. A CHOPPY flip mid-trade must not yank a
    directional hold down to a 4.5 trail.
    """
    return None


def runner_needs_room(
    *,
    regime: str = "",
    atr: float = 0.0,
    atr_at_entry: float = 0.0,
    mfe_atr: float = 0.0,
) -> bool:
    """True when a runner should get the wide high-vol trail."""
    r = str(regime or "").upper()
    if r in ("HIGH_VOL", "TRENDING"):
        return True
    if float(mfe_atr) >= 2.0:
        return True
    atr_e = max(float(atr_at_entry), 1e-9)
    return float(atr) >= 1.25 * atr_e


def runner_trail_atr_mult(spread_atr: float, cfg: Mark2Config | None = None) -> float:
    """Wide purple while red/white are apart; shrink toward MIN as they converge."""
    wide_room = float(getattr(cfg, "RUNNER_TRAIL_ATR", 1.50) or 1.50) if cfg else 1.50
    tight_room = float(getattr(cfg, "RUNNER_TRAIL_MIN_ATR", 0.40) or 0.40) if cfg else 0.40
    wide_spread = float(getattr(cfg, "RUNNER_TRAIL_WIDE_SPREAD_ATR", 0.35) or 0.35) if cfg else 0.35
    tight_spread = float(getattr(cfg, "RUNNER_TRAIL_TIGHT_SPREAD_ATR", 0.08) or 0.08) if cfg else 0.08
    tight_room = min(max(tight_room, 0.0), wide_room)
    if tight_spread >= wide_spread:
        return wide_room if spread_atr >= wide_spread else tight_room
    if spread_atr >= wide_spread:
        return wide_room
    if spread_atr <= tight_spread:
        return tight_room
    t = (spread_atr - tight_spread) / (wide_spread - tight_spread)
    return tight_room + t * (wide_room - tight_room)


def _one_r_points(trade, cfg: Mark2Config | None = None) -> float:
    entry = float(getattr(trade, "entry", 0) or 0)
    hard = float(getattr(trade, "hard_stop", 0) or 0) or float(getattr(trade, "stop", 0) or 0)
    gap = abs(entry - hard)
    if gap > 1e-9:
        return gap
    atr_e = max(float(getattr(trade, "atr_at_entry", 0) or 0), 1e-9)
    mult = float(getattr(cfg, "CATASTROPHIC_STOP_ATR", 1.50) or 1.50) if cfg else 1.50
    return atr_e * mult


def ema_cluster_spread(ema9: float | None, ema20: float | None, ema50: float | None) -> float | None:
    if ema9 is None or ema20 is None or ema50 is None:
        return None
    vals = (float(ema9), float(ema20), float(ema50))
    if min(abs(v) for v in vals) <= 0:
        return None
    return max(vals) - min(vals)


def mfe_giveback_floor_pts(mfe: float, cfg: Mark2Config | None = None) -> float:
    give = 0.30
    if cfg is not None:
        give = float(getattr(cfg, "MFE_GIVEBACK_FRAC", 0.30) or 0.30)
    give = min(0.50, max(0.15, give))
    return max(0.0, float(mfe) * (1.0 - give))


def mfe_open_pts(side: Side, entry: float, price: float) -> float:
    if side == Side.LONG:
        return float(price) - float(entry)
    if side == Side.SHORT:
        return float(entry) - float(price)
    return 0.0


def mfe_losing_momentum(
    trade,
    *,
    price: float,
    cfg: Mark2Config | None = None,
    stall_bars: int = 0,
    rsi: float | None = None,
    state: str = "",
) -> bool:
    """Still green, but has given back 35% of MFE. Runners ignore stall/RSI so a pause is not a floor."""
    if cfg is not None and not bool(getattr(cfg, "MFE_FADE_LOCK", False)):
        return False
    side = getattr(trade, "side", Side.NONE)
    entry = float(getattr(trade, "entry", 0) or 0)
    mfe = float(getattr(trade, "mfe", 0) or 0)
    px = float(price)
    open_pts = mfe_open_pts(side, entry, px)
    if mfe <= 1e-12 or open_pts <= 1e-12:
        return False
    if side == Side.LONG and px + 1e-9 >= float(getattr(trade, "peak", px) or px):
        return False
    if side == Side.SHORT and px - 1e-9 <= float(getattr(trade, "peak", px) or px):
        return False
    give_frac = max(0.0, (mfe - open_pts) / mfe)
    need = 0.35
    stall_need = 2
    rsi_drop = 5.0
    if cfg is not None:
        need = float(getattr(cfg, "MFE_FADE_GIVE_FRAC", 0.35) or 0.35)
        stall_need = max(1, int(getattr(cfg, "MFE_FADE_STALL_BARS", 2) or 2))
        rsi_drop = float(getattr(cfg, "MFE_FADE_RSI_DROP", 5.0) or 5.0)
    if give_frac + 1e-12 >= need:
        return True
    phase = str(state or getattr(trade, "ema_trade_state", "") or "")
    if phase == "RUNNER":
        return False
    if int(stall_bars) >= stall_need:
        return True
    rsi_peak = float(getattr(trade, "rsi_peak", 0) or 0)
    if rsi is not None and rsi_peak > 0 and float(rsi) + rsi_drop <= rsi_peak + 1e-12:
        return True
    return False


def mfe_lock_active(
    trade,
    *,
    price: float,
    state: str,
    cfg: Mark2Config | None = None,
    stall_bars: int = 0,
    rsi: float | None = None,
) -> bool:
    """Fade lock helper. Off on Recon Sniper; runners use the 70% MFE floor."""
    if float(getattr(trade, "mfe", 0) or 0) <= 1e-12:
        return False
    return mfe_losing_momentum(
        trade, price=price, cfg=cfg, stall_bars=stall_bars, rsi=rsi, state=state
    )


def _manage_ema_classic_exit(
    trade,
    *,
    price: float,
    exit_armed: bool,
    cfg: Mark2Config | None,
) -> tuple[bool, str, EngineState]:
    """10-pt hard stop. After +$15, trail 5.5 off the tip."""
    px = float(price)
    entry = float(getattr(trade, "entry", 0) or 0)
    side = trade.side
    if side == Side.LONG:
        trade.peak = max(float(getattr(trade, "peak", px) or px), px)
        trade.trough = min(float(getattr(trade, "trough", px) or px), px)
        trade.mfe = max(0.0, float(trade.peak) - entry)
        trade.mae = max(0.0, entry - float(trade.trough))
    else:
        trade.peak = min(float(getattr(trade, "peak", px) or px), px)
        trade.trough = max(float(getattr(trade, "trough", px) or px), px)
        trade.mfe = max(0.0, entry - float(trade.peak))
        trade.mae = max(0.0, float(trade.trough) - entry)

    hard = float(getattr(trade, "hard_stop", 0) or 0)
    if hard <= 0:
        hard = ema_classic_stop(entry, side, cfg)
    trade.hard_stop = hard

    arm_usd = 15.0
    trail_pts = 5.5
    if cfg is not None:
        arm_usd = float(getattr(cfg, "TRAIL_ARM_USD", 15.0) or 15.0)
        trail_pts = float(getattr(cfg, "RUNNER_TRAIL_POINTS", 5.5) or 5.5)
    peak_usd = _peak_open_usd(trade, cfg)
    armed = peak_usd + 1e-9 >= arm_usd
    trade.ema_trade_state = "RUNNER" if armed else "PROBATION"
    trade.runner_trail_on = armed
    tip_pts = float(getattr(trade, "tip_trail_pts", 0) or 0) or trail_pts
    trade.tip_trail_pts = tip_pts

    protect = hard
    if armed:
        if side == Side.LONG:
            trail = float(trade.peak) - tip_pts
        else:
            trail = float(trade.peak) + tip_pts
        protect = more_protective_stop(side, protect, trail)
    prev_stop = float(trade.stop)
    protect = more_protective_stop(side, protect, prev_stop)
    protect = lock_stop_at_green_target(trade, price=px, protect=protect, cfg=cfg)
    if bool(getattr(trade, "target_touched", False)):
        trade.runner_trail_on = True
        trade.ema_trade_state = "RUNNER"
    trade.stop = protect

    why = green_target_exit_reason(trade, price=px, protect=protect, cfg=cfg)
    if why:
        return True, why, EngineState.EXIT
    tick = _tick_size(cfg)
    tgt = float(getattr(trade, "target", 0) or 0)
    on_green = (
        bool(getattr(trade, "target_touched", False))
        and tgt > 0
        and abs(protect - tgt) <= tick * 0.51 + 1e-12
    )
    hit = (not on_green) and (px <= protect + 1e-12 if side == Side.LONG else px >= protect - 1e-12)
    if hit:
        if armed and abs(protect - hard) > 1e-9:
            return True, "TIP_TRAIL", EngineState.EXIT
        return True, "HARD_STOP", EngineState.EXIT
    if exit_armed and bool(getattr(cfg, "EMA_OPPOSITE_CROSS_EXIT", False) if cfg else False):
        return True, "OPPOSITE_EMA_CROSS", EngineState.EXIT
    return False, "", _ema_engine_state(trade)


def manage_ema_hold(
    trade,
    *,
    price: float,
    exit_armed: bool,
    cfg: Mark2Config | None = None,
    ema9: float | None = None,
    ema20: float | None = None,
    ema50: float | None = None,
    atr: float | None = None,
    regime: str = "",
    completed_anchor: float | None = None,
    bias: str = "",
    rsi: float | None = None,
    rsi_prev: float | None = None,
    account_equity: float | None = None,
    bars: list[dict] | None = None,
    prev9: float | None = None,
    prev20: float | None = None,
    prev50: float | None = None,
) -> tuple[bool, str, EngineState]:
    """Compression / structure / dollar floor. Grow-mode stall bank on a small account."""
    if cfg is not None and bool(getattr(cfg, "EMA_CLASSIC_EXIT", False)):
        return _manage_ema_classic_exit(trade, price=price, exit_armed=exit_armed, cfg=cfg)
    px = float(price)
    entry = float(getattr(trade, "entry", 0) or 0)
    side = trade.side
    if side == Side.LONG:
        trade.peak = max(float(getattr(trade, "peak", px) or px), px)
        trade.trough = min(float(getattr(trade, "trough", px) or px), px)
        trade.mfe = max(0.0, float(trade.peak) - entry)
        trade.mae = max(0.0, entry - float(trade.trough))
    else:
        trade.peak = min(float(getattr(trade, "peak", px) or px), px)
        trade.trough = max(float(getattr(trade, "trough", px) or px), px)
        trade.mfe = max(0.0, entry - float(trade.peak))
        trade.mae = max(0.0, float(trade.trough) - entry)

    if str(getattr(trade, "ema_entry_tag", "") or "").startswith("413"):
        from .breakout_413 import manage_413_hold

        return manage_413_hold(
            trade,
            price=px,
            bars=bars,
            cfg=cfg,
            ema9=ema9,
        )
    if cfg is not None and bool(getattr(cfg, "ENABLE_AI_EXIT_ENGINE", False)):
        from .ai_exit import manage_ai_exit

        return manage_ai_exit(
            trade,
            price=px,
            exit_armed=exit_armed,
            cfg=cfg,
            ema9=ema9,
            ema20=ema20,
            ema50=ema50,
            prev9=prev9,
            prev20=prev20,
            prev50=prev50,
            atr=atr,
            bars=bars,
            rsi=rsi,
            rsi_prev=rsi_prev,
        )

    hard = float(getattr(trade, "hard_stop", 0) or 0) or float(trade.stop)
    trade.hard_stop = hard
    prev_stop = float(trade.stop)

    if rsi is not None:
        trade.rsi_peak = max(float(getattr(trade, "rsi_peak", 0) or 0), float(rsi))

    one_r = _one_r_points(trade, cfg)
    atr_e = max(float(getattr(trade, "atr_at_entry", 0) or 0), 1e-9)
    if trade.mfe + 1e-12 >= 2.0 * one_r:
        state = "RUNNER"
    elif trade.mfe + 1e-12 >= one_r:
        state = "CONFIRMED"
    else:
        state = "PROBATION"
    trade.ema_trade_state = state
    peak_usd_now = _peak_open_usd(trade, cfg)
    arm_now = 100.0
    if cfg is not None:
        arm_now = float(getattr(cfg, "TIP_TRAIL_ARM_USD", 100.0) or 100.0)
    trade.runner_trail_on = state == "RUNNER" or peak_usd_now + 1e-9 >= arm_now
    trade.runner_trail_atr = None
    trade.runner_spread_atr = None

    spread = ema_cluster_spread(ema9, ema20, ema50)
    if spread is not None:
        if float(getattr(trade, "entry_spread", 0) or 0) <= 0:
            trade.entry_spread = spread
        trade.spread_peak = max(float(getattr(trade, "spread_peak", 0) or 0), spread)

    if ema9 is not None and ema20 is not None:
        e9, e20 = float(ema9), float(ema20)
        against = (side == Side.LONG and e9 < e20) or (side == Side.SHORT and e9 > e20)
        trade.ema9_warn = against or (
            (side == Side.LONG and px < e9) or (side == Side.SHORT and px > e9)
        )
        if state == "PROBATION":
            trade.ema_lost_20 = False
            trade.ema_lost_key = ""
        else:
            key = f"{e9:.4f}|{e20:.4f}"
            if against:
                prev_key = str(getattr(trade, "ema_lost_key", "") or "")
                if bool(getattr(trade, "ema_lost_20", False)) and prev_key and prev_key != key:
                    return True, "STRUCTURE_FAILURE", EngineState.EXIT
                trade.ema_lost_20 = True
                if not prev_key:
                    trade.ema_lost_key = key
            else:
                trade.ema_lost_20 = False
                trade.ema_lost_key = ""

    if state != "PROBATION" and spread is not None:
        peak_sp = float(getattr(trade, "spread_peak", 0) or 0)
        entry_sp = float(getattr(trade, "entry_spread", 0) or 0)
        compress = float(getattr(cfg, "SPREAD_COMPRESS_FRAC", 0.35) or 0.35) if cfg else 0.35
        expanded = peak_sp + 1e-12 >= max(entry_sp * 1.25, entry_sp + 4.0)
        if expanded and spread <= peak_sp * (1.0 - compress) + 1e-12:
            return True, "COMPRESSION", EngineState.EXIT

    protect = hard
    if state in ("CONFIRMED", "RUNNER"):
        risk_atr = float(getattr(cfg, "CONFIRMED_STOP_ATR_FROM_ENTRY", 0.25) or 0.25) if cfg else 0.25
        if side == Side.LONG:
            protect = more_protective_stop(side, protect, entry - risk_atr * atr_e)
        else:
            protect = more_protective_stop(side, protect, entry + risk_atr * atr_e)

    lock = None
    trail_lock = None
    dollar_lock = None
    if state == "RUNNER":
        floor_pts = mfe_giveback_floor_pts(float(trade.mfe), cfg)
        prev_floor = float(getattr(trade, "giveback_floor_pts", 0) or 0)
        floor_pts = max(prev_floor, floor_pts)
        trade.giveback_floor_pts = floor_pts
        if side == Side.LONG:
            lock = entry + floor_pts
        else:
            lock = entry - floor_pts
        protect = more_protective_stop(side, protect, lock)

    dollar_lock = profit_keep_lock_price(trade, cfg, state=state)
    if dollar_lock is not None:
        protect = more_protective_stop(side, protect, dollar_lock)

    peak_usd = _peak_open_usd(trade, cfg)
    if adverse_stack_exit(
        side,
        bars,
        float(trade.peak),
        peak_usd,
        float(atr) if atr is not None else atr_e,
        cfg,
    ):
        return True, "ADVERSE_STACK", EngineState.EXIT
    arm_usd = 100.0
    step_usd = 25.0
    stall_need = 4
    grab_usd = 50.0
    grow_stall_need = 3
    grow_keep_frac = 0.75
    grow_on = grow_mode_active(cfg, account_equity)
    if cfg is not None:
        arm_usd = float(getattr(cfg, "TIP_TRAIL_ARM_USD", 100.0) or 100.0)
        step_usd = float(getattr(cfg, "TIP_TRAIL_STEP_USD", 25.0) or 25.0)
        stall_need = max(1, int(getattr(cfg, "TIP_TRAIL_STALL_BARS", 4) or 4))
        grab_usd = float(getattr(cfg, "GROW_GRAB_USD", 50.0) or 50.0)
        grow_stall_need = max(1, int(getattr(cfg, "GROW_STALL_BARS", 3) or 3))
        grow_keep_frac = float(getattr(cfg, "GROW_STALL_KEEP_FRAC", 0.75) or 0.75)
    need_stall = peak_usd + 1e-9 >= arm_usd or (
        grow_on and peak_usd + 1e-9 >= grab_usd
    )
    stall_bars = (
        _update_runner_stall(trade, completed_anchor)
        if need_stall
        else int(getattr(trade, "stall_score", 0) or 0)
    )
    grow_lock = None
    if grow_on and peak_usd + 1e-9 >= grab_usd and stall_bars >= 1:
        grow_usd = grow_keep_usd(peak_usd, cfg)
        if grow_usd > 0:
            pv = max(float(getattr(cfg, "POINT_VALUE", 2.0) or 2.0), 1e-9) if cfg else 2.0
            qty = max(1, int(getattr(trade, "qty", 1) or 1))
            grow_pts = grow_usd / (pv * qty)
            if side == Side.LONG:
                grow_lock = entry + grow_pts
            else:
                grow_lock = entry - grow_pts
            protect = more_protective_stop(side, protect, grow_lock)
    if grow_on and peak_usd + 1e-9 >= grab_usd and stall_bars >= grow_stall_need:
        open_usd = _open_usd(trade, px, cfg)
        good_bulk = open_usd + 1e-9 >= grab_usd or open_usd + 1e-9 >= peak_usd * grow_keep_frac
        if good_bulk:
            return True, "GROW_BANK", EngineState.EXIT
    if peak_usd + 1e-9 >= arm_usd:
        trail_pts = runner_tip_trail_pts(peak_usd, stall_bars, cfg)
        trade.tip_trail_pts = trail_pts
        bucket = int(peak_usd // max(step_usd, 1e-9)) * step_usd
        prev_r = float(getattr(trade, "trail_ratchet_usd", 0) or 0)
        if side == Side.LONG:
            trail_lock = float(trade.peak) - trail_pts
        else:
            trail_lock = float(trade.peak) + trail_pts
        if bucket + 1e-9 >= arm_usd and (bucket > prev_r + 1e-9 or stall_bars >= stall_need):
            trade.trail_ratchet_usd = max(prev_r, float(bucket))
            protect = more_protective_stop(side, protect, trail_lock)
        elif stall_bars >= stall_need:
            protect = more_protective_stop(side, protect, trail_lock)

    protect = more_protective_stop(side, protect, prev_stop)
    protect = lock_stop_at_green_target(trade, price=px, protect=protect, cfg=cfg)
    if bool(getattr(trade, "target_touched", False)):
        trade.runner_trail_on = True
        if str(getattr(trade, "ema_trade_state", "") or "") == "PROBATION":
            trade.ema_trade_state = "CONFIRMED"
    trade.stop = protect

    why = green_target_exit_reason(trade, price=px, protect=protect, cfg=cfg)
    if why:
        return True, why, EngineState.EXIT
    tick = _tick_size(cfg)
    tgt = float(getattr(trade, "target", 0) or 0)
    on_green = (
        bool(getattr(trade, "target_touched", False))
        and tgt > 0
        and abs(protect - tgt) <= tick * 0.51 + 1e-12
    )
    hit = (not on_green) and (px <= protect + 1e-12 if side == Side.LONG else px >= protect - 1e-12)
    if hit:
        if trail_lock is not None and abs(protect - float(trail_lock)) <= 1e-9:
            return True, "TIP_TRAIL", EngineState.EXIT
        if grow_lock is not None and abs(protect - float(grow_lock)) <= 1e-9:
            return True, "GROW_BANK", EngineState.EXIT
        if dollar_lock is not None and abs(protect - float(dollar_lock)) <= 1e-9:
            return True, "PROTECT", EngineState.EXIT
        if lock is not None and abs(protect - float(lock)) <= 1e-9:
            return True, "MFE_GIVEBACK", EngineState.EXIT
        if abs(protect - hard) > 1e-9:
            return True, "PROTECT", EngineState.EXIT
        return True, "CATASTROPHIC_STOP", EngineState.EXIT
    if exit_armed and bool(getattr(cfg, "EMA_OPPOSITE_CROSS_EXIT", False)):
        return True, "OPPOSITE_EMA_CROSS", EngineState.EXIT
    return False, "", _ema_engine_state(trade)


def ema_body_close_exit(side: Side, bar: dict, ema20: float) -> bool:
    """Legacy body-through-white exit. Unused live; kept for later A/B."""
    close = float(bar.get("close") or 0)
    if side == Side.LONG:
        return close < float(ema20)
    if side == Side.SHORT:
        return close > float(ema20)
    return False
