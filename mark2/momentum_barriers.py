"""Momentum barriers: next key level, room-to-target, AI-exit awareness.

Does not replace EMA sniper / leftover / 413 unless ENABLE_BARRIER_STRATEGY_ONLY.
Hard stop never widens. Classic take-profit at the level is off by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

from .config import Mark2Config, local_app_settings_path
from .indicators import atr, swing_pivots
from .types import Side

_ET = ZoneInfo("America/New_York")

PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"
CURRENT_SESSION_HIGH = "CURRENT_SESSION_HIGH"
CURRENT_SESSION_LOW = "CURRENT_SESSION_LOW"
SWING_HIGH = "SWING_HIGH"
SWING_LOW = "SWING_LOW"
CONSOLIDATION_HIGH = "CONSOLIDATION_HIGH"
CONSOLIDATION_LOW = "CONSOLIDATION_LOW"

BARRIER_FAR = "BARRIER_FAR"
BARRIER_APPROACHING = "BARRIER_APPROACHING"
BARRIER_TESTING = "BARRIER_TESTING"
BARRIER_BREAKOUT = "BARRIER_BREAKOUT"
BARRIER_REJECTION = "BARRIER_REJECTION"

REJECT_NEAR_MOMENTUM_BARRIER = "REJECT_NEAR_MOMENTUM_BARRIER"
MOMENTUM_BARRIER_REJECTION = "MOMENTUM_BARRIER_REJECTION"
KEY_LEVEL_TARGET = "KEY_LEVEL_TARGET"
BARRIER_BREAKOUT_CONTINUE = "BARRIER_BREAKOUT_CONTINUE"
BARRIER_CLUSTER_REJECTION = "BARRIER_CLUSTER_REJECTION"

RESISTANCE_KINDS = (
    PREVIOUS_DAY_HIGH,
    CURRENT_SESSION_HIGH,
    SWING_HIGH,
    CONSOLIDATION_HIGH,
)
SUPPORT_KINDS = (
    PREVIOUS_DAY_LOW,
    CURRENT_SESSION_LOW,
    SWING_LOW,
    CONSOLIDATION_LOW,
)


def barriers_enabled(cfg: Mark2Config | None) -> bool:
    return bool(cfg is not None and getattr(cfg, "ENABLE_MOMENTUM_BARRIERS", False))


def barriers_only_mode(cfg: Mark2Config | None) -> bool:
    return barriers_enabled(cfg) and bool(getattr(cfg, "ENABLE_BARRIER_STRATEGY_ONLY", False))


def _cfg_bool(cfg: Mark2Config | None, name: str, default: bool) -> bool:
    if cfg is None:
        return default
    return bool(getattr(cfg, name, default))


def _cfg_float(cfg: Mark2Config | None, name: str, default: float) -> float:
    if cfg is None:
        return default
    raw = getattr(cfg, name, default)
    return float(default if raw is None else raw)


def _cfg_int(cfg: Mark2Config | None, name: str, default: int) -> int:
    if cfg is None:
        return default
    return int(getattr(cfg, name, default) or default)


def _tick(cfg: Mark2Config | None) -> float:
    if cfg is None:
        return 0.25
    return max(float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25), 0.01)


def parse_bar_dt(bar: dict | None) -> datetime | None:
    if not bar:
        return None
    raw = bar.get("time")
    if isinstance(raw, (int, float)) and float(raw) > 1e8:
        try:
            return datetime.fromtimestamp(float(raw), _ET)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_ET)
    return dt.astimezone(_ET)


def cme_session_key(dt: datetime) -> str:
    """Globex session date: 18:00 ET starts the next session (MNQ)."""
    et = dt.astimezone(_ET) if dt.tzinfo else dt.replace(tzinfo=_ET)
    day = et.date() + timedelta(days=1) if et.hour >= 18 else et.date()
    return day.isoformat()


def session_store_path() -> Path:
    return local_app_settings_path().parent / "barrier_session.json"


@dataclass
class BarrierCandidate:
    kind: str
    price: float


@dataclass
class BarrierZone:
    found: bool = False
    price: float = 0.0
    kind: str = ""
    zone_low: float = 0.0
    zone_high: float = 0.0
    strength: int = 0
    sources: tuple[str, ...] = ()
    distance_points: float = 0.0
    distance_atr: float = 0.0
    state: str = BARRIER_FAR
    rejection: bool = False
    breakout: bool = False
    room_ok: bool = True
    room_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "price": round(self.price, 2),
            "kind": self.kind,
            "zoneLow": round(self.zone_low, 2),
            "zoneHigh": round(self.zone_high, 2),
            "strength": self.strength,
            "sources": list(self.sources),
            "distancePoints": round(self.distance_points, 2),
            "distanceAtr": round(self.distance_atr, 3),
            "state": self.state,
            "rejection": self.rejection,
            "breakout": self.breakout,
            "roomOk": self.room_ok,
            "roomReason": self.room_reason,
        }


@dataclass
class BarrierBook:
    session_key: str = ""
    current_session_high: float = 0.0
    current_session_low: float = 0.0
    previous_day_high: float = 0.0
    previous_day_low: float = 0.0
    prev_session_key: str = ""
    consolidation_high: float = 0.0
    consolidation_low: float = 0.0
    swing_highs: list[float] = field(default_factory=list)
    swing_lows: list[float] = field(default_factory=list)
    persist_path: Path | None = None
    last_hold_key: tuple = ()


def _load_session(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_session(path: Path | None, book: BarrierBook) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        payload = {
            "session_key": book.session_key,
            "current_session_high": book.current_session_high,
            "current_session_low": book.current_session_low,
            "previous_day_high": book.previous_day_high,
            "previous_day_low": book.previous_day_low,
            "prev_session_key": book.prev_session_key,
        }
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return


def update_session_levels(book: BarrierBook, bars: Sequence[dict], *, persist: bool = True) -> BarrierBook:
    """Freeze PDH/PDL at the Globex session roll. Current H/L updates on completed bars."""
    stored = _load_session(book.persist_path) if persist and book.persist_path else {}
    if stored and not book.session_key:
        book.session_key = str(stored.get("session_key") or "")
        book.current_session_high = float(stored.get("current_session_high") or 0)
        book.current_session_low = float(stored.get("current_session_low") or 0)
        book.previous_day_high = float(stored.get("previous_day_high") or 0)
        book.previous_day_low = float(stored.get("previous_day_low") or 0)
        book.prev_session_key = str(stored.get("prev_session_key") or "")

    by_session: dict[str, list[dict]] = {}
    for bar in bars:
        dt = parse_bar_dt(bar)
        if dt is None:
            continue
        key = cme_session_key(dt)
        by_session.setdefault(key, []).append(bar)
    if not by_session:
        return book

    keys = sorted(by_session)
    live_key = keys[-1]
    live = by_session[live_key]
    live_hi = max(float(b.get("high") or 0) for b in live)
    live_lo = min(float(b.get("low") or 0) for b in live if float(b.get("low") or 0) > 0) or 0.0

    rolled = book.session_key and live_key != book.session_key
    if rolled and book.current_session_high > 0:
        book.previous_day_high = book.current_session_high
        book.previous_day_low = book.current_session_low
        book.prev_session_key = book.session_key
    elif len(keys) >= 2 and book.previous_day_high <= 0:
        prev_bars = by_session[keys[-2]]
        book.previous_day_high = max(float(b.get("high") or 0) for b in prev_bars)
        lows = [float(b.get("low") or 0) for b in prev_bars if float(b.get("low") or 0) > 0]
        book.previous_day_low = min(lows) if lows else 0.0
        book.prev_session_key = keys[-2]

    book.session_key = live_key
    book.current_session_high = live_hi
    book.current_session_low = live_lo
    if persist and book.persist_path is not None:
        _save_session(book.persist_path, book)
    return book


def detect_swings(
    bars: Sequence[dict],
    cfg: Mark2Config | None = None,
) -> tuple[list[float], list[float]]:
    """Confirmed swings only. The last SWING_RIGHT_BARS bars cannot become a pivot."""
    left = max(1, _cfg_int(cfg, "SWING_LEFT_BARS", 3))
    right = max(1, _cfg_int(cfg, "SWING_RIGHT_BARS", 3))
    if left == right:
        return swing_pivots(bars, strength=left)
    highs: list[float] = []
    lows: list[float] = []
    if len(bars) < left + right + 1:
        return highs, lows
    for i in range(left, len(bars) - right):
        h = float(bars[i].get("high") or 0)
        lo = float(bars[i].get("low") or 0)
        left_h = [float(bars[i - j].get("high") or 0) for j in range(1, left + 1)]
        right_h = [float(bars[i + j].get("high") or 0) for j in range(1, right + 1)]
        left_l = [float(bars[i - j].get("low") or 0) for j in range(1, left + 1)]
        right_l = [float(bars[i + j].get("low") or 0) for j in range(1, right + 1)]
        if h > 0 and all(h >= x for x in left_h) and all(h >= x for x in right_h):
            highs.append(h)
        if lo > 0 and all(lo <= x for x in left_l) and all(lo <= x for x in right_l):
            lows.append(lo)
    return highs, lows


def detect_consolidation(
    bars: Sequence[dict],
    atr_v: float,
    cfg: Mark2Config | None = None,
) -> tuple[float, float]:
    lookback = max(4, _cfg_int(cfg, "CONSOLIDATION_LOOKBACK", 12))
    need = max(3, _cfg_int(cfg, "MIN_CONSOLIDATION_BARS", 6))
    max_range = _cfg_float(cfg, "CONSOLIDATION_MAX_RANGE_ATR", 0.85)
    if len(bars) < need:
        return 0.0, 0.0
    chunk = list(bars[-lookback:])
    highs = [float(b.get("high") or 0) for b in chunk]
    lows = [float(b.get("low") or 0) for b in chunk if float(b.get("low") or 0) > 0]
    if not highs or not lows:
        return 0.0, 0.0
    hi = max(highs)
    lo = min(lows)
    rng = hi - lo
    atr_n = max(float(atr_v), 1e-9)
    if rng / atr_n > max_range:
        return 0.0, 0.0
    mid_lo = lo + rng * 0.15
    mid_hi = hi - rng * 0.15
    overlap = 0
    for bar in chunk:
        h = float(bar.get("high") or 0)
        l = float(bar.get("low") or 0)
        if h >= mid_lo and l <= mid_hi:
            overlap += 1
    if overlap < need:
        return 0.0, 0.0
    return hi, lo


def refresh_structure(book: BarrierBook, bars: Sequence[dict], atr_v: float, cfg: Mark2Config | None) -> None:
    sh, sl = detect_swings(bars, cfg)
    book.swing_highs = sh[-8:]
    book.swing_lows = sl[-8:]
    chi, clo = detect_consolidation(bars, atr_v, cfg)
    book.consolidation_high = chi
    book.consolidation_low = clo


def build_barrier_candidates(book: BarrierBook, *, direction: Side) -> list[BarrierCandidate]:
    out: list[BarrierCandidate] = []
    if direction == Side.LONG:
        pairs = (
            (PREVIOUS_DAY_HIGH, book.previous_day_high),
            (CURRENT_SESSION_HIGH, book.current_session_high),
            (CONSOLIDATION_HIGH, book.consolidation_high),
        )
        for kind, px in pairs:
            if px > 0:
                out.append(BarrierCandidate(kind, float(px)))
        for px in book.swing_highs:
            if px > 0:
                out.append(BarrierCandidate(SWING_HIGH, float(px)))
        return out
    pairs = (
        (PREVIOUS_DAY_LOW, book.previous_day_low),
        (CURRENT_SESSION_LOW, book.current_session_low),
        (CONSOLIDATION_LOW, book.consolidation_low),
    )
    for kind, px in pairs:
        if px > 0:
            out.append(BarrierCandidate(kind, float(px)))
    for px in book.swing_lows:
        if px > 0:
            out.append(BarrierCandidate(SWING_LOW, float(px)))
    return out


def _cleared_hit(cleared: Iterable[tuple[str, float]], kind: str, price: float, tick: float) -> bool:
    for ck, cp in cleared:
        if ck == kind and abs(float(cp) - float(price)) <= max(tick, 0.25) * 2:
            return True
        if abs(float(cp) - float(price)) <= max(tick, 0.25):
            return True
    return False


def cluster_barriers(
    candidates: Sequence[BarrierCandidate],
    *,
    direction: Side,
    current_price: float,
    atr_v: float,
    cfg: Mark2Config | None,
    cleared: Sequence[tuple[str, float]] = (),
) -> BarrierZone:
    tick = _tick(cfg)
    atr_n = max(float(atr_v), 1e-9)
    cluster_atr = _cfg_float(cfg, "BARRIER_CLUSTER_TOLERANCE_ATR", 0.15)
    tol = max(tick, cluster_atr * atr_n)
    ahead: list[BarrierCandidate] = []
    for cand in candidates:
        if _cleared_hit(cleared, cand.kind, cand.price, tick):
            continue
        if direction == Side.LONG and cand.price > current_price + tick:
            ahead.append(cand)
        elif direction == Side.SHORT and cand.price < current_price - tick:
            ahead.append(cand)
    if not ahead:
        return BarrierZone(found=False)
    if direction == Side.LONG:
        ahead.sort(key=lambda c: c.price)
        nearest = ahead[0].price
        group = [c for c in ahead if c.price <= nearest + tol]
    else:
        ahead.sort(key=lambda c: -c.price)
        nearest = ahead[0].price
        group = [c for c in ahead if c.price >= nearest - tol]
    sources = tuple(dict.fromkeys(c.kind for c in group))
    zone_low = min(c.price for c in group)
    zone_high = max(c.price for c in group)
    # Nearest edge in the trade direction is the working target.
    price = zone_low if direction == Side.LONG else zone_high
    dist = abs(price - current_price)
    return BarrierZone(
        found=True,
        price=price,
        kind=group[0].kind,
        zone_low=zone_low,
        zone_high=zone_high,
        strength=len(sources),
        sources=sources,
        distance_points=dist,
        distance_atr=dist / atr_n,
    )


def get_next_momentum_barrier(
    direction: Side,
    current_price: float,
    book: BarrierBook,
    atr_v: float,
    cfg: Mark2Config | None = None,
    *,
    cleared: Sequence[tuple[str, float]] = (),
) -> BarrierZone:
    cands = build_barrier_candidates(book, direction=direction)
    return cluster_barriers(
        cands,
        direction=direction,
        current_price=float(current_price),
        atr_v=float(atr_v),
        cfg=cfg,
        cleared=cleared,
    )


def calculate_room_to_barrier(
    direction: Side,
    entry_price: float,
    zone: BarrierZone,
    atr_v: float,
    cfg: Mark2Config | None = None,
) -> BarrierZone:
    if not zone.found:
        zone.room_ok = True
        zone.room_reason = "NO_BARRIER"
        return zone
    if direction == Side.LONG:
        room = zone.price - float(entry_price)
    else:
        room = float(entry_price) - zone.price
    atr_n = max(float(atr_v), 1e-9)
    zone.distance_points = room
    zone.distance_atr = room / atr_n
    min_pts = _cfg_float(cfg, "MIN_ROOM_TO_BARRIER_POINTS", 8.0)
    min_atr = _cfg_float(cfg, "MIN_ROOM_TO_BARRIER_ATR", 0.35)
    fail_pts = min_pts > 0 and room + 1e-12 < min_pts
    fail_atr = min_atr > 0 and room / atr_n + 1e-12 < min_atr
    if fail_pts or fail_atr:
        zone.room_ok = False
        zone.room_reason = REJECT_NEAR_MOMENTUM_BARRIER
        return zone
    zone.room_ok = True
    zone.room_reason = "ROOM_OK"
    return zone


def evaluate_entry_room(
    direction: Side,
    entry_price: float,
    book: BarrierBook,
    atr_v: float,
    cfg: Mark2Config | None,
) -> BarrierZone:
    zone = get_next_momentum_barrier(direction, entry_price, book, atr_v, cfg)
    return calculate_room_to_barrier(direction, entry_price, zone, atr_v, cfg)


def classify_barrier_state(
    direction: Side,
    price: float,
    zone: BarrierZone,
    atr_v: float,
    cfg: Mark2Config | None = None,
) -> str:
    if not zone.found:
        return BARRIER_FAR
    atr_n = max(float(atr_v), 1e-9)
    dist = abs(float(price) - zone.price)
    if direction == Side.LONG:
        dist = zone.price - float(price)
    else:
        dist = float(price) - zone.price
    test_atr = _cfg_float(cfg, "BARRIER_TEST_TOLERANCE_ATR", 0.12)
    approach_atr = _cfg_float(cfg, "BARRIER_APPROACH_ATR", 0.40)
    if zone.breakout:
        return BARRIER_BREAKOUT
    if zone.rejection:
        return BARRIER_REJECTION
    # Beyond the zone without a confirmed breakout is still a test.
    if dist <= test_atr * atr_n or dist < 0:
        return BARRIER_TESTING
    if dist <= approach_atr * atr_n:
        return BARRIER_APPROACHING
    return BARRIER_FAR


def _bar_body_frac(bar: dict) -> float:
    o = float(bar.get("open") or 0)
    c = float(bar.get("close") or 0)
    h = float(bar.get("high") or 0)
    l = float(bar.get("low") or 0)
    rng = max(h - l, 1e-9)
    return abs(c - o) / rng


def _against_candle(direction: Side, bar: dict) -> bool:
    o = float(bar.get("open") or 0)
    c = float(bar.get("close") or 0)
    if direction == Side.LONG:
        return c < o
    return c > o


def detect_barrier_breakout(
    direction: Side,
    bars: Sequence[dict],
    zone: BarrierZone,
    *,
    ema9: float | None = None,
    ema20: float | None = None,
    spread_regime: str = "",
    cfg: Mark2Config | None = None,
) -> bool:
    if not zone.found or len(bars) < 1:
        return False
    bar = bars[-1]
    close = float(bar.get("close") or 0)
    tick = _tick(cfg)
    strong = _bar_body_frac(bar) >= 0.45
    if direction == Side.LONG:
        beyond = close > zone.zone_high + tick
        aligned = ema9 is None or ema20 is None or float(ema9) >= float(ema20)
        with_move = close > float(bar.get("open") or 0)
    else:
        beyond = close < zone.zone_low - tick
        aligned = ema9 is None or ema20 is None or float(ema9) <= float(ema20)
        with_move = close < float(bar.get("open") or 0)
    collapsing = str(spread_regime or "").upper() == "COLLAPSING"
    return bool(beyond and strong and aligned and with_move and not collapsing)


def detect_barrier_rejection(
    direction: Side,
    bars: Sequence[dict],
    zone: BarrierZone,
    *,
    ema9: float | None = None,
    ema20: float | None = None,
    prev9: float | None = None,
    spread_regime: str = "",
    momentum_score: int = 0,
    cfg: Mark2Config | None = None,
) -> bool:
    """Completed-bar rejection. One wick is not enough."""
    if not zone.found or len(bars) < 1:
        return False
    bar = bars[-1]
    close = float(bar.get("close") or 0)
    high = float(bar.get("high") or 0)
    low = float(bar.get("low") or 0)
    tick = _tick(cfg)
    body = _bar_body_frac(bar) >= 0.45
    against = _against_candle(direction, bar)
    contracting = str(spread_regime or "").upper() in ("CONTRACTING", "COLLAPSING", "DECELERATING")
    slope_fail = False
    if ema9 is not None and prev9 is not None:
        if direction == Side.LONG:
            slope_fail = float(ema9) < float(prev9)
        else:
            slope_fail = float(ema9) > float(prev9)
    health_fail = int(momentum_score or 0) >= _cfg_int(cfg, "MOMENTUM_WATCH_SCORE", 3)
    if direction == Side.LONG:
        touched = high >= zone.zone_low - tick
        failed = close < zone.zone_low - tick
    else:
        touched = low <= zone.zone_high + tick
        failed = close > zone.zone_high + tick
    structure_fail = contracting or slope_fail or health_fail
    if ema9 is not None and ema20 is not None:
        if direction == Side.LONG and float(ema9) < float(ema20):
            structure_fail = True
        if direction == Side.SHORT and float(ema9) > float(ema20):
            structure_fail = True
    return bool(touched and failed and body and against and structure_fail)


def confirm_hold_beyond(direction: Side, bars: Sequence[dict], zone: BarrierZone, cfg: Mark2Config | None) -> bool:
    if not zone.found or len(bars) < 1:
        return False
    close = float(bars[-1].get("close") or 0)
    tick = _tick(cfg)
    if direction == Side.LONG:
        return close > zone.zone_high - tick
    return close < zone.zone_low + tick


def sync_trade_barrier(
    trade,
    book: BarrierBook,
    bars: Sequence[dict],
    *,
    price: float,
    atr_v: float,
    cfg: Mark2Config | None,
    ema9: float | None = None,
    ema20: float | None = None,
    prev9: float | None = None,
    spread_regime: str = "",
    momentum_score: int = 0,
) -> BarrierZone:
    side = trade.side
    cleared = list(getattr(trade, "barrier_cleared", []) or [])
    zone = get_next_momentum_barrier(side, float(price), book, atr_v, cfg, cleared=cleared)
    pending = bool(getattr(trade, "barrier_pending_break", False))
    pending_zone = getattr(trade, "barrier_pending_zone", None)
    if not isinstance(pending_zone, BarrierZone):
        pending_zone = zone
    broke = detect_barrier_breakout(
        side, bars, zone, ema9=ema9, ema20=ema20, spread_regime=spread_regime, cfg=cfg
    )
    if pending:
        held = confirm_hold_beyond(side, bars, pending_zone, cfg)
        rejected = detect_barrier_rejection(
            side, bars, pending_zone, ema9=ema9, ema20=ema20, prev9=prev9,
            spread_regime=spread_regime, momentum_score=momentum_score, cfg=cfg,
        )
        if held and not rejected:
            pending_zone.breakout = True
            cleared.append((pending_zone.kind, pending_zone.price))
            trade.barrier_cleared = cleared
            trade.barrier_pending_break = False
            trade.barrier_pending_zone = None
            nxt = get_next_momentum_barrier(side, float(price), book, atr_v, cfg, cleared=cleared)
            nxt.breakout = True
            nxt.state = BARRIER_BREAKOUT
            trade.barrier_view = nxt
            return nxt
        trade.barrier_pending_break = False
        trade.barrier_pending_zone = None
    elif broke:
        trade.barrier_pending_break = True
        trade.barrier_pending_zone = zone
    rejected = detect_barrier_rejection(
        side, bars, zone, ema9=ema9, ema20=ema20, prev9=prev9,
        spread_regime=spread_regime, momentum_score=momentum_score, cfg=cfg,
    )
    zone.rejection = rejected
    zone.breakout = False
    zone.state = classify_barrier_state(side, float(price), zone, atr_v, cfg)
    trade.barrier_view = zone
    return zone


def barrier_trail_stop(
    side: Side,
    price: float,
    atr_v: float,
    zone: BarrierZone,
    cfg: Mark2Config | None,
) -> float | None:
    """Tighter trail as price tags the next level. Never a widen instruction."""
    if not zone.found or zone.state not in (BARRIER_APPROACHING, BARRIER_TESTING, BARRIER_REJECTION):
        return None
    if zone.state == BARRIER_TESTING or zone.state == BARRIER_REJECTION:
        mult = _cfg_float(cfg, "BARRIER_TEST_TRAIL_ATR", 0.40)
    else:
        mult = _cfg_float(cfg, "BARRIER_APPROACH_TRAIL_ATR", 0.70)
    dist = max(float(atr_v) * mult, _tick(cfg) * 4)
    if side == Side.LONG:
        return float(price) - dist
    return float(price) + dist


def classic_target_hit(side: Side, price: float, close: float, zone: BarrierZone, cfg: Mark2Config | None) -> str:
    if not zone.found:
        return ""
    tick = _tick(cfg)
    hard = _cfg_bool(cfg, "ENABLE_HARD_BARRIER_TARGET", False)
    classic = _cfg_bool(cfg, "ENABLE_CLASSIC_KEY_LEVEL_TARGET", False)
    if not hard and not classic:
        return ""
    if side == Side.LONG:
        touch = float(price) >= zone.zone_low - tick
        closed = float(close) >= zone.zone_low - tick
    else:
        touch = float(price) <= zone.zone_high + tick
        closed = float(close) <= zone.zone_high + tick
    if hard and touch:
        return KEY_LEVEL_TARGET
    if classic and closed:
        return KEY_LEVEL_TARGET
    return ""


def rejection_exit_reason(zone: BarrierZone, cfg: Mark2Config | None) -> str:
    if not zone.rejection or not _cfg_bool(cfg, "ENABLE_BARRIER_REJECTION_EXIT", True):
        return ""
    if zone.strength >= 3:
        return BARRIER_CLUSTER_REJECTION
    return MOMENTUM_BARRIER_REJECTION


def format_entry_log(
    *,
    direction: Side,
    entry: float,
    atr_v: float,
    zone: BarrierZone,
    allowed: bool,
) -> str:
    decision = "ALLOW" if allowed else "REJECT"
    reason = zone.room_reason if zone.found or zone.room_reason else "NO_BARRIER"
    zone_txt = f"{zone.zone_low:.2f}–{zone.zone_high:.2f}" if zone.found else "—"
    return (
        f"{direction.value} SETUP  ENTRY:{entry:.2f}  "
        f"NEXT MOMENTUM BARRIER:{zone.price:.2f}  TYPE:{zone.kind or 'NONE'}  "
        f"ZONE:{zone_txt}  STRENGTH:{zone.strength}  "
        f"DISTANCE:{zone.distance_points:.2f} pts  ATR:{atr_v:.2f}  "
        f"DISTANCE ATR:{zone.distance_atr:.3f}  DECISION:{decision}  REASON:{reason}"
    )


_KIND_LABELS = {
    PREVIOUS_DAY_HIGH: "PDH",
    PREVIOUS_DAY_LOW: "PDL",
    CURRENT_SESSION_HIGH: "SESSION HIGH",
    CURRENT_SESSION_LOW: "SESSION LOW",
    SWING_HIGH: "SWING HIGH",
    SWING_LOW: "SWING LOW",
    CONSOLIDATION_HIGH: "BOX HIGH",
    CONSOLIDATION_LOW: "BOX LOW",
}

_STATE_LABELS = {
    BARRIER_FAR: "FAR",
    BARRIER_APPROACHING: "APPROACHING",
    BARRIER_TESTING: "TESTING",
    BARRIER_BREAKOUT: "BREAKOUT",
    BARRIER_REJECTION: "REJECTION",
}


def kind_label(kind: str) -> str:
    raw = str(kind or "").strip()
    return _KIND_LABELS.get(raw, raw.replace("_", " ") or "NONE")


def state_label(state: str) -> str:
    raw = str(state or BARRIER_FAR)
    return _STATE_LABELS.get(raw, raw.replace("BARRIER_", "").replace("_", " "))


def _zone_hud(zone: BarrierZone | None) -> dict[str, Any]:
    z = zone if isinstance(zone, BarrierZone) else BarrierZone()
    out = z.as_dict()
    out["label"] = kind_label(z.kind)
    out["stateLabel"] = state_label(z.state)
    return out


def _live_zone(
    direction: Side,
    price: float,
    book: BarrierBook,
    atr_v: float,
    cfg: Mark2Config | None,
) -> BarrierZone:
    zone = evaluate_entry_room(direction, float(price), book, float(atr_v), cfg)
    zone.state = classify_barrier_state(direction, float(price), zone, float(atr_v), cfg)
    return zone


def barrier_trade_hud(
    cfg: Mark2Config | None,
    book: BarrierBook | None,
    *,
    price: float,
    atr_v: float,
    trade: Any = None,
) -> dict[str, Any]:
    """TRADE-screen payload. Off = empty so the old Recon intersection card stays."""
    enabled = barriers_enabled(cfg)
    exclusive = barriers_only_mode(cfg)
    empty = {
        "enabled": False,
        "exclusive": False,
        "call": "",
        "badge": "",
        "state": BARRIER_FAR,
        "roomOk": True,
        "long": _zone_hud(None),
        "short": _zone_hud(None),
        "active": {},
        "pdh": 0.0,
        "pdl": 0.0,
        "sessionHigh": 0.0,
        "sessionLow": 0.0,
        "kickerLong": "",
        "kickerShort": "",
        "bullets": [],
    }
    if not enabled or book is None:
        return empty
    px = float(price or 0)
    atr_n = float(atr_v or 0)
    long_z = _live_zone(Side.LONG, px, book, atr_n, cfg) if px > 0 else BarrierZone()
    short_z = _live_zone(Side.SHORT, px, book, atr_n, cfg) if px > 0 else BarrierZone()
    trade_side = ""
    active: BarrierZone | None = None
    if trade is not None:
        raw_side = getattr(trade, "side", None)
        trade_side = str(getattr(raw_side, "value", raw_side) or "").upper()
        held = getattr(trade, "barrier_view", None)
        if isinstance(held, BarrierZone) and held.found:
            active = held
            d = Side.SHORT if trade_side == "SHORT" else Side.LONG
            active.state = classify_barrier_state(d, px, active, atr_n, cfg)
        elif trade_side == "SHORT":
            active = short_z
        elif trade_side == "LONG":
            active = long_z
    if active is None:
        if long_z.found and short_z.found:
            active = long_z if abs(long_z.distance_points) <= abs(short_z.distance_points) else short_z
        elif long_z.found:
            active = long_z
        elif short_z.found:
            active = short_z
    if active and active.found:
        dist = abs(float(active.distance_points))
        call = (
            f"NEXT {kind_label(active.kind)} {active.price:.2f} · "
            f"{dist:.1f} PTS · {state_label(active.state)}"
        )
        if trade is None and not active.room_ok:
            call = f"TOO CLOSE · {kind_label(active.kind)} {active.price:.2f}"
        badge = state_label(active.state)
        state = active.state
        room_ok = bool(active.room_ok)
    else:
        call = "FLAT · MAPPING SESSION LEVELS"
        badge = "MAP"
        state = BARRIER_FAR
        room_ok = True
    bullets: list[str] = []
    if exclusive:
        bullets.append("EMA / 413 / SCOUT ENTRIES PAUSED")
    bullets.append("AI EXIT ON · TRAIL TIGHTENS AT THE NEXT LEVEL")
    bullets.append("DOES NOT FLATTEN AT THE LEVEL")
    if active and active.found:
        bullets.append(
            f"ZONE {active.zone_low:.2f}–{active.zone_high:.2f} · STR {active.strength}"
        )
    return {
        "enabled": True,
        "exclusive": exclusive,
        "call": call,
        "badge": badge,
        "state": state,
        "roomOk": room_ok,
        "long": _zone_hud(long_z),
        "short": _zone_hud(short_z),
        "active": _zone_hud(active),
        "pdh": round(float(book.previous_day_high or 0), 2),
        "pdl": round(float(book.previous_day_low or 0), 2),
        "sessionHigh": round(float(book.current_session_high or 0), 2),
        "sessionLow": round(float(book.current_session_low or 0), 2),
        "kickerLong": "BARRIER LONG",
        "kickerShort": "BARRIER SHORT",
        "bullets": bullets,
    }


def format_hold_log(
    *,
    zone: BarrierZone,
    momentum_score: int,
    spread_regime: str,
    decision: str,
    note: str = "",
) -> str:
    nxt = ""
    if zone.breakout and zone.found:
        nxt = f"  NEW ACTIVE TARGET:{zone.price:.2f}"
    return (
        f"ACTIVE TARGET:{zone.kind or 'NONE'}  TARGET:{zone.price:.2f}  "
        f"DISTANCE:{zone.distance_points:.2f} pts  STATE:{zone.state}  "
        f"MOMENTUM SCORE:{momentum_score}  EMA SPREAD:{spread_regime or '—'}  "
        f"DECISION:{decision}{nxt}  {note}"
    ).strip()


def apply_ai_barrier(
    trade,
    *,
    price: float,
    close: float,
    atr_v: float,
    score: int,
    spread_regime: str,
    cfg: Mark2Config | None,
    more_protective_stop,
) -> tuple[int, str]:
    """Adjust AI score / trail. Returns (score, flatten_reason). Empty reason = hold path."""
    if not barriers_enabled(cfg):
        return score, ""
    zone = getattr(trade, "barrier_view", None)
    if not isinstance(zone, BarrierZone) or not zone.found:
        return score, ""
    side = trade.side
    classic = classic_target_hit(side, price, close, zone, cfg)
    if classic:
        return score, classic
    reject_why = rejection_exit_reason(zone, cfg)
    extra = 0
    if zone.state == BARRIER_TESTING:
        extra += 1
    if zone.rejection:
        extra += 2 if zone.strength < 3 else 3
    score = int(score) + extra
    trail = barrier_trail_stop(side, price, atr_v, zone, cfg)
    if trail is not None:
        trade.stop = more_protective_stop(side, float(trade.stop), float(trail))
    if reject_why:
        return score, reject_why
    return score, ""
