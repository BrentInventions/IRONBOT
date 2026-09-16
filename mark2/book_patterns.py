"""Simple Trading Book candle patterns — optional entry filter for Recon Sniper."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Mark2Config
from .types import Side


@dataclass
class PatternHit:
    name: str
    side: Side  # LONG = bullish, SHORT = bearish
    bars_used: int
    detail: str = ""


def _f(bar: dict, key: str) -> float:
    try:
        return float(bar.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _ohlc(bar: dict) -> tuple[float, float, float, float]:
    return _f(bar, "open"), _f(bar, "high"), _f(bar, "low"), _f(bar, "close")


def _body(o: float, c: float) -> float:
    return abs(c - o)


def _range(h: float, l: float) -> float:
    return max(0.0, h - l)


def _is_bull(o: float, c: float) -> bool:
    return c > o


def _is_bear(o: float, c: float) -> bool:
    return c < o


def is_doji(bar: dict, *, body_max_frac: float = 0.12) -> bool:
    o, h, l, c = _ohlc(bar)
    r = _range(h, l)
    if r <= 0:
        return False
    return _body(o, c) / r <= body_max_frac


def is_spinning_top(bar: dict, *, body_max_frac: float = 0.30) -> bool:
    o, h, l, c = _ohlc(bar)
    r = _range(h, l)
    if r <= 0:
        return False
    body = _body(o, c)
    if body / r > body_max_frac:
        return False
    upper = h - max(o, c)
    lower = min(o, c) - l
    if body <= 0:
        return upper > 0 and lower > 0
    return upper >= body * 0.8 and lower >= body * 0.8 and abs(upper - lower) <= body * 1.5


def is_hammer(bar: dict, *, wick_body_mult: float = 2.0) -> bool:
    o, h, l, c = _ohlc(bar)
    body = _body(o, c)
    r = _range(h, l)
    if r <= 0 or body <= 0:
        return False
    lower = min(o, c) - l
    upper = h - max(o, c)
    return lower >= body * wick_body_mult and upper <= body * 1.05 and body / r <= 0.40


def is_shooting_star(bar: dict, *, wick_body_mult: float = 2.0) -> bool:
    o, h, l, c = _ohlc(bar)
    body = _body(o, c)
    r = _range(h, l)
    if r <= 0 or body <= 0:
        return False
    upper = h - max(o, c)
    lower = min(o, c) - l
    return upper >= body * wick_body_mult and lower <= body * 1.05 and body / r <= 0.40


def is_bullish_engulfing(prev: dict, cur: dict) -> bool:
    po, _, _, pc = _ohlc(prev)
    o, _, _, c = _ohlc(cur)
    if not _is_bear(po, pc) or not _is_bull(o, c):
        return False
    return o <= pc and c >= po and _body(o, c) > _body(po, pc)


def is_bearish_engulfing(prev: dict, cur: dict) -> bool:
    po, _, _, pc = _ohlc(prev)
    o, _, _, c = _ohlc(cur)
    if not _is_bull(po, pc) or not _is_bear(o, c):
        return False
    return o >= pc and c <= po and _body(o, c) > _body(po, pc)


def is_piercing_line(prev: dict, cur: dict) -> bool:
    po, _, _, pc = _ohlc(prev)
    o, _, _, c = _ohlc(cur)
    if not _is_bear(po, pc) or not _is_bull(o, c):
        return False
    mid = (po + pc) / 2.0
    return o < pc and c > mid and c < po


def is_dark_cloud_cover(prev: dict, cur: dict) -> bool:
    po, _, _, pc = _ohlc(prev)
    o, _, _, c = _ohlc(cur)
    if not _is_bull(po, pc) or not _is_bear(o, c):
        return False
    mid = (po + pc) / 2.0
    return o > pc and c < mid and c > po


def is_morning_star(a: dict, b: dict, c: dict) -> bool:
    ao, _, _, ac = _ohlc(a)
    bo, _, _, bc = _ohlc(b)
    co, _, _, cc = _ohlc(c)
    if not _is_bear(ao, ac) or not _is_bull(co, cc):
        return False
    if _body(ao, ac) <= 0 or _body(co, cc) <= 0:
        return False
    mid_body = _body(bo, bc)
    if mid_body > _body(ao, ac) * 0.55:
        return False
    mid_mid = (bo + bc) / 2.0
    if mid_mid > (ao + ac) / 2.0:
        return False
    return cc >= (ao + ac) / 2.0


def is_evening_star(a: dict, b: dict, c: dict) -> bool:
    ao, _, _, ac = _ohlc(a)
    bo, _, _, bc = _ohlc(b)
    co, _, _, cc = _ohlc(c)
    if not _is_bull(ao, ac) or not _is_bear(co, cc):
        return False
    if _body(ao, ac) <= 0 or _body(co, cc) <= 0:
        return False
    mid_body = _body(bo, bc)
    if mid_body > _body(ao, ac) * 0.55:
        return False
    mid_mid = (bo + bc) / 2.0
    if mid_mid < (ao + ac) / 2.0:
        return False
    return cc <= (ao + ac) / 2.0


def is_three_white_soldiers(a: dict, b: dict, c: dict) -> bool:
    closes = []
    for bar in (a, b, c):
        o, _, _, cl = _ohlc(bar)
        if not _is_bull(o, cl):
            return False
        if _body(o, cl) <= 0:
            return False
        closes.append(cl)
    return closes[1] > closes[0] and closes[2] > closes[1]


def is_three_black_crows(a: dict, b: dict, c: dict) -> bool:
    closes = []
    for bar in (a, b, c):
        o, _, _, cl = _ohlc(bar)
        if not _is_bear(o, cl):
            return False
        if _body(o, cl) <= 0:
            return False
        closes.append(cl)
    return closes[1] < closes[0] and closes[2] < closes[1]


class BookPatternDetector:
    """Scan recent completed bars for Simple Trading Book candle patterns."""

    def __init__(self, *, enabled: bool = False, wick_body_mult: float = 2.0) -> None:
        self.enabled = bool(enabled)
        self.mode = "filter"
        self.wick_body_mult = float(wick_body_mult)
        self.allow_hammer = True
        self.allow_shooting_star = True
        self.allow_engulfing = True
        self.allow_stars = True
        self.allow_soldiers_crows = True
        self.block_on_doji = True
        self.last_hits: list[PatternHit] = []
        self.last_status = "BOOK PATTERNS OFF"
        self.last_primary: PatternHit | None = None

    def scan(self, bars: list[dict]) -> list[PatternHit]:
        hits: list[PatternHit] = []
        if len(bars) < 2:
            self.last_hits = []
            self.last_primary = None
            self.last_status = "need bars"
            return hits

        cur = bars[-1]
        prev = bars[-2]
        w = self.wick_body_mult

        if self.allow_hammer and is_hammer(cur, wick_body_mult=w):
            hits.append(PatternHit("Hammer", Side.LONG, 1, "long lower wick"))
        if self.allow_shooting_star and is_shooting_star(cur, wick_body_mult=w):
            hits.append(PatternHit("Shooting Star", Side.SHORT, 1, "long upper wick"))

        if self.allow_engulfing and is_bullish_engulfing(prev, cur):
            hits.append(PatternHit("Bullish Engulfing", Side.LONG, 2))
        if self.allow_engulfing and is_bearish_engulfing(prev, cur):
            hits.append(PatternHit("Bearish Engulfing", Side.SHORT, 2))
        if self.allow_engulfing and is_piercing_line(prev, cur):
            hits.append(PatternHit("Piercing Line", Side.LONG, 2))
        if self.allow_engulfing and is_dark_cloud_cover(prev, cur):
            hits.append(PatternHit("Dark Cloud Cover", Side.SHORT, 2))

        if len(bars) >= 3:
            a, b, c = bars[-3], bars[-2], bars[-1]
            if self.allow_stars and is_morning_star(a, b, c):
                hits.append(PatternHit("Morning Star", Side.LONG, 3))
            if self.allow_stars and is_evening_star(a, b, c):
                hits.append(PatternHit("Evening Star", Side.SHORT, 3))
            if self.allow_soldiers_crows and is_three_white_soldiers(a, b, c):
                hits.append(PatternHit("Three White Soldiers", Side.LONG, 3))
            if self.allow_soldiers_crows and is_three_black_crows(a, b, c):
                hits.append(PatternHit("Three Black Crows", Side.SHORT, 3))

        if is_doji(cur):
            hits.append(PatternHit("Doji", Side.LONG, 1, "indecision"))
        if is_spinning_top(cur):
            hits.append(PatternHit("Spinning Top", Side.LONG, 1, "indecision"))

        self.last_hits = hits
        directional = [h for h in hits if h.name not in ("Doji", "Spinning Top")]
        self.last_primary = directional[0] if directional else (hits[0] if hits else None)
        if not self.enabled:
            self.last_status = "BOOK PATTERNS OFF"
        elif not hits:
            self.last_status = "no book pattern"
        else:
            self.last_status = ", ".join(h.name for h in hits[:4])
        return hits

    def allows_side(self, side: Side, bars: list[dict]) -> tuple[bool, str]:
        if not self.enabled:
            return True, "book patterns not filtering"
        hits = self.scan(bars)
        if self.mode != "filter":
            return True, "book patterns not filtering"

        directional = [h for h in hits if h.name not in ("Doji", "Spinning Top")]
        indecision = [h for h in hits if h.name in ("Doji", "Spinning Top")]

        if self.block_on_doji and indecision and not directional:
            return False, f"book filter — {indecision[0].name} (indecision)"

        matching = [h for h in directional if h.side == side]
        if matching:
            return True, f"book OK — {matching[0].name}"
        if directional:
            names = ", ".join(h.name for h in directional[:3])
            return False, f"book filter — need {side.value} pattern (saw {names})"
        return False, "book filter — no confirming book pattern"

    def status_line(self) -> str:
        if not self.enabled:
            return "BOOK OFF"
        return f"BOOK: {self.last_status}"


def book_pattern_entry_ok(
    cfg: Mark2Config,
    bars: list[dict],
    direction: Side,
) -> tuple[bool, str]:
    """Zero overhead when ENABLE_BOOK_PATTERNS is false."""
    if not bool(getattr(cfg, "ENABLE_BOOK_PATTERNS", False)):
        return True, ""
    det = BookPatternDetector(enabled=True)
    return det.allows_side(direction, bars)
