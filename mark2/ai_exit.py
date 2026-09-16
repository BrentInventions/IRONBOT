"""AI momentum exit engine — optional path next to the existing EMA hold.

Hard stop stays frozen. This module may flatten earlier or ratchet a profit
floor up. ENABLE_AI_EXIT_ENGINE=False keeps manage_ema_hold on the old path.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Mark2Config
from .momentum_barriers import (
    BARRIER_APPROACHING,
    BARRIER_BREAKOUT,
    BARRIER_BREAKOUT_CONTINUE,
    BARRIER_REJECTION,
    BARRIER_TESTING,
    BarrierZone,
    barrier_trail_stop,
    barriers_enabled,
    classic_target_hit,
    format_hold_log,
    rejection_exit_reason,
)
from .types import EngineState, Side

AI_DEVELOPING = "TRADE_DEVELOPING"
AI_PROTECTED = "TRADE_PROTECTED"
AI_RUNNER_HEALTHY = "RUNNER_HEALTHY"
AI_RUNNER_WATCH = "RUNNER_WATCH"
AI_REACCEL = "RUNNER_REACCELERATING"
AI_DYING = "MOMENTUM_DYING"
AI_EXIT = "EXIT_TRIGGERED"

SPREAD_EXPANDING = "EXPANDING"
SPREAD_STABLE = "STABLE"
SPREAD_DECEL = "DECELERATING"
SPREAD_CONTRACT = "CONTRACTING"
SPREAD_COLLAPSE = "COLLAPSING"


@dataclass(frozen=True)
class AiExitSnapshot:
    state: str
    score: int
    decision: str
    reason: str
    r_mult: float
    mfe_pts: float
    mfe_r: float
    runner_floor: float
    protect_floor: float
    slope9: float
    slope20: float
    slope50: float
    gap_9_20: float
    gap_9_20_atr: float
    spread_velocity: float
    total_spread: float
    spread_regime: str
    price_gt_9: bool
    price_gt_20: bool
    bearish_cross: bool
    lower_high: bool
    lower_low: bool
    compressed: bool
    note: str

    def log_line(self, trade) -> str:
        entry = float(getattr(trade, "entry", 0) or 0)
        return (
            f"AI EXIT {self.decision} {self.reason}  STATE:{self.state}  "
            f"R:{self.r_mult:.2f}  MFE:{self.mfe_pts:.2f}pts/{self.mfe_r:.2f}R  "
            f"FLOOR:{self.runner_floor:.2f}  PROTECT:{self.protect_floor:.2f}  "
            f"EMA9:{getattr(trade, 'ai_ema9', 0):.2f}  "
            f"EMA20:{getattr(trade, 'ai_ema20', 0):.2f}  "
            f"EMA50:{getattr(trade, 'ai_ema50', 0):.2f}  "
            f"slope9:{self.slope9:.3f}  slope20:{self.slope20:.3f}  slope50:{self.slope50:.3f}  "
            f"gap9/20:{self.gap_9_20_atr:.3f}  vel:{self.spread_velocity:.3f}  "
            f"spread:{self.spread_regime}  tot:{self.total_spread:.2f}  "
            f"px>9:{'Y' if self.price_gt_9 else 'N'}  px>20:{'Y' if self.price_gt_20 else 'N'}  "
            f"x9/20:{'Y' if self.bearish_cross else 'N'}  "
            f"LH:{'Y' if self.lower_high else 'N'}  LL:{'Y' if self.lower_low else 'N'}  "
            f"knot:{'Y' if self.compressed else 'N'}  SCORE:{self.score}  "
            f"ENTRY:{entry:.2f}  {self.note}"
        )


def maybe_partial_exit(trade, state: str, cfg: Mark2Config | None = None):
    """Extension point only. Live tickets flatten the full qty; no partials."""
    return None


def _helpers():
    from .ema_strategy import (
        _ema_engine_state,
        _one_r_points,
        ema_cluster_spread,
        is_ema_compressed,
        more_protective_stop,
        EmaStack,
    )

    return (
        _ema_engine_state,
        _one_r_points,
        ema_cluster_spread,
        is_ema_compressed,
        more_protective_stop,
        EmaStack,
    )


def _atr(trade, atr: float | None) -> float:
    if atr is not None and float(atr) > 1e-9:
        return float(atr)
    return max(float(getattr(trade, "atr_at_entry", 0) or 0), 1e-9)


def _cfg_int(cfg, name: str, default: int) -> int:
    if cfg is None:
        return default
    return int(getattr(cfg, name, default) or default)


def _cfg_float(cfg, name: str, default: float) -> float:
    if cfg is None:
        return default
    raw = getattr(cfg, name, default)
    return float(default if raw is None else raw)


def _cfg_bool(cfg, name: str, default: bool) -> bool:
    if cfg is None:
        return default
    return bool(getattr(cfg, name, default))


def _close(bars: list[dict] | None, price: float) -> float:
    if bars:
        close = float((bars[-1] or {}).get("close") or 0)
        if close > 0:
            return close
    return float(price)


def _pivots(values: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(values) - 1):
        if values[i] > values[i - 1] and values[i] > values[i + 1]:
            out.append(values[i])
    return out


def _troughs(values: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(values) - 1):
        if values[i] < values[i - 1] and values[i] < values[i + 1]:
            out.append(values[i])
    return out


def swing_flags(side: Side, bars: list[dict] | None) -> tuple[bool, bool]:
    """Confirmed 3-bar pivots only. No repaint of the last (forming) bar."""
    if not bars or len(bars) < 5:
        return False, False
    highs = [float(b.get("high") or 0) for b in bars]
    lows = [float(b.get("low") or 0) for b in bars]
    ph, pl = _pivots(highs), _troughs(lows)
    if side == Side.LONG:
        lh = len(ph) >= 2 and ph[-1] + 1e-12 < ph[-2]
        ll = len(pl) >= 2 and pl[-1] + 1e-12 < pl[-2]
        return lh, ll
    lh = len(pl) >= 2 and pl[-1] - 1e-12 > pl[-2]
    ll = len(ph) >= 2 and ph[-1] - 1e-12 > ph[-2]
    return lh, ll


def classify_spread(now_gap: float, prev_gap: float, avg_gap: float, atr: float) -> str:
    """Tiny one-bar wiggles stay STABLE. Collapse needs a real ATR-sized drop."""
    atr_v = max(float(atr), 1e-9)
    vel = (float(now_gap) - float(prev_gap)) / atr_v
    now_n = float(now_gap) / atr_v
    avg_n = float(avg_gap) / atr_v
    if vel <= -0.08 and now_n <= 0.08:
        return SPREAD_COLLAPSE
    if vel <= -0.04 and now_n + 1e-12 < avg_n:
        return SPREAD_CONTRACT
    if vel < -0.015:
        return SPREAD_DECEL
    if vel > 0.015:
        return SPREAD_EXPANDING
    return SPREAD_STABLE


def momentum_score(
    *,
    side: Side,
    slope9: float,
    slope20: float,
    gap_now: float,
    gap_prev: float,
    close: float,
    ema9: float,
    ema20: float,
    compressed: bool,
    bearish_cross: bool,
    lower_high: bool,
    lower_low: bool,
    bearish_bar: bool,
    spread_regime: str,
    cfg: Mark2Config | None,
) -> int:
    if not _cfg_bool(cfg, "ENABLE_MOMENTUM_SCORE", True):
        return 0
    w9 = _cfg_int(cfg, "MOM_W_EMA9_SLOPE_NEG", 1)
    w_ct = _cfg_int(cfg, "MOM_W_SPREAD_CONTRACT", 1)
    w_cl = _cfg_int(cfg, "MOM_W_SPREAD_COLLAPSE", 2)
    w_px9 = _cfg_int(cfg, "MOM_W_CLOSE_BELOW_9", 1)
    w_px20 = _cfg_int(cfg, "MOM_W_CLOSE_BELOW_20", 2)
    w_x = _cfg_int(cfg, "MOM_W_BEARISH_CROSS", 3)
    w_lh = _cfg_int(cfg, "MOM_W_LOWER_HIGH", 1)
    w_ll = _cfg_int(cfg, "MOM_W_LOWER_LOW", 2)
    w_k = _cfg_int(cfg, "MOM_W_COMPRESSION", 2)
    w_bar = _cfg_int(cfg, "MOM_W_BEARISH_BAR", 2)
    score = 0
    long = side == Side.LONG
    if long:
        if slope9 < 0:
            score += w9
        if close + 1e-12 < ema9:
            score += w_px9
        if close + 1e-12 < ema20:
            score += w_px20
    else:
        if slope9 > 0:
            score += w9
        if close - 1e-12 > ema9:
            score += w_px9
        if close - 1e-12 > ema20:
            score += w_px20
    if spread_regime in (SPREAD_CONTRACT, SPREAD_DECEL):
        score += w_ct
    if spread_regime == SPREAD_COLLAPSE or (gap_now + 1e-12 < gap_prev and abs(gap_now - gap_prev) > abs(gap_prev) * 0.35):
        score += w_cl
    if bearish_cross:
        score += w_x
    if lower_high:
        score += w_lh
    if lower_low:
        score += w_ll
    if compressed:
        score += w_k
    if bearish_bar:
        score += w_bar
    return int(score)


def _retain_frac(cfg: Mark2Config | None) -> float:
    if cfg is None:
        return 0.70
    retain = getattr(cfg, "RUNNER_MFE_RETAIN", None)
    if retain is not None:
        return min(0.95, max(0.50, float(retain)))
    return min(0.85, max(0.50, 1.0 - float(getattr(cfg, "MFE_GIVEBACK_FRAC", 0.30) or 0.30)))


def _bar_ohlc(bar: dict) -> tuple[float, float, float, float]:
    o = float((bar or {}).get("open") or 0)
    h = float((bar or {}).get("high") or 0)
    l = float((bar or {}).get("low") or 0)
    c = float((bar or {}).get("close") or 0)
    return o, h, l, c


def candle_momentum_dying(side: Side, bars: list[dict] | None) -> bool:
    """True when the last three bars lose range, body, and follow-through."""
    if not bars or len(bars) < 3:
        return False
    last3 = bars[-3:]
    ranges: list[float] = []
    bodies: list[float] = []
    closes: list[float] = []
    dirs: list[float] = []
    for bar in last3:
        o, h, l, c = _bar_ohlc(bar)
        rng = max(h - l, 1e-9)
        ranges.append(rng)
        bodies.append(abs(c - o))
        closes.append(c)
        dirs.append(c - o)
    shrinking = ranges[-1] <= ranges[0] * 0.70 and bodies[-1] <= max(bodies[0], 1e-9) * 0.55
    if not shrinking:
        return False
    if side == Side.LONG:
        lost_push = closes[-1] <= max(closes[0], closes[1]) + 1e-12
        return lost_push and dirs[-1] <= 0
    lost_push = closes[-1] >= min(closes[0], closes[1]) - 1e-12
    return lost_push and dirs[-1] >= 0


def rsi_dying_for_side(
    side: Side,
    *,
    rsi_now: float | None,
    rsi_prev: float | None,
    rsi_peak: float = 0.0,
    rsi_floor: float = 0.0,
    cfg: Mark2Config | None = None,
) -> bool:
    """Long: RSI rolled over off its peak. Short: RSI lifted off its trough."""
    if rsi_now is None:
        return False
    now = float(rsi_now)
    prev = float(rsi_prev) if rsi_prev is not None else now
    fade = _cfg_float(cfg, "CHOP_RSI_FADE", 5.0)
    if side == Side.LONG:
        peak = max(float(rsi_peak or 0.0), now, prev)
        return now < prev - 1e-9 and now <= peak - fade + 1e-12
    trough = now
    if rsi_floor and float(rsi_floor) > 0:
        trough = min(float(rsi_floor), now, prev)
    else:
        trough = min(now, prev)
    return now > prev + 1e-9 and now >= trough + fade - 1e-12


def trend_reversing(
    side: Side,
    *,
    close: float,
    ema9: float,
    ema20: float,
    slope9: float,
    slope20: float,
    bearish_cross: bool,
) -> bool:
    """9/20 flipped, close through 20, and both slopes rolled against the trade."""
    close_broke_20 = (close + 1e-12 < ema20) if side == Side.LONG else (close - 1e-12 > ema20)
    if not (bearish_cross and close_broke_20):
        return False
    if side == Side.LONG:
        return slope9 < 0 and slope20 <= 0
    return slope9 > 0 and slope20 >= 0


def smart_exit_reason(
    side: Side,
    *,
    close: float,
    ema9: float,
    ema20: float,
    slope9: float,
    slope20: float,
    bearish_cross: bool,
    bars: list[dict] | None,
    rsi_now: float | None,
    rsi_prev: float | None,
    rsi_peak: float = 0.0,
    rsi_floor: float = 0.0,
    cfg: Mark2Config | None = None,
) -> str:
    """Flatten when the trend is reversing, or RSI and candle momentum are both dying."""
    if trend_reversing(
        side,
        close=close,
        ema9=ema9,
        ema20=ema20,
        slope9=slope9,
        slope20=slope20,
        bearish_cross=bearish_cross,
    ):
        return "TREND_REVERSAL"
    rsi_dead = rsi_dying_for_side(
        side,
        rsi_now=rsi_now,
        rsi_prev=rsi_prev,
        rsi_peak=rsi_peak,
        rsi_floor=rsi_floor,
        cfg=cfg,
    )
    if rsi_dead and candle_momentum_dying(side, bars):
        return "RSI_CANDLE_DEATH"
    return ""


def _bearish_structure_bar(side: Side, bars: list[dict] | None, ema20: float) -> bool:
    if not bars:
        return False
    bar = bars[-1] or {}
    o = float(bar.get("open") or 0)
    c = float(bar.get("close") or 0)
    h = float(bar.get("high") or 0)
    l = float(bar.get("low") or 0)
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    if body / rng < 0.55:
        return False
    if side == Side.LONG:
        return c < o and c + 1e-12 < float(ema20)
    return c > o and c - 1e-12 > float(ema20)


def _phase_state(r_mult: float, score: int, cfg: Mark2Config | None, prev: str) -> str:
    watch = _cfg_int(cfg, "MOMENTUM_WATCH_SCORE", 3)
    dying = _cfg_int(cfg, "MOMENTUM_DYING_SCORE", 5)
    start_r = _cfg_float(cfg, "RUNNER_START_R", 2.0)
    protect_r = _cfg_float(cfg, "PROTECT_AT_R", 1.0)
    if score >= dying:
        return AI_DYING
    if r_mult + 1e-12 >= start_r:
        if score >= watch:
            return AI_RUNNER_WATCH
        if prev == AI_RUNNER_WATCH:
            return AI_REACCEL
        if prev == AI_REACCEL:
            return AI_RUNNER_HEALTHY
        return AI_RUNNER_HEALTHY
    if r_mult + 1e-12 >= protect_r:
        if score >= watch:
            return AI_RUNNER_WATCH
        return AI_PROTECTED
    return AI_DEVELOPING


def _log_snapshot(trade, snap: AiExitSnapshot) -> None:
    key = (snap.state, snap.score, snap.decision, snap.reason, snap.spread_regime)
    if key == getattr(trade, "ai_last_log_key", None):
        return
    trade.ai_last_log_key = key
    print(snap.log_line(trade), flush=True)


def manage_ai_exit(
    trade,
    *,
    price: float,
    exit_armed: bool,
    cfg: Mark2Config | None = None,
    ema9: float | None = None,
    ema20: float | None = None,
    ema50: float | None = None,
    prev9: float | None = None,
    prev20: float | None = None,
    prev50: float | None = None,
    atr: float | None = None,
    bars: list[dict] | None = None,
    rsi: float | None = None,
    rsi_prev: float | None = None,
) -> tuple[bool, str, EngineState]:
    """Hard stop first. Then 1R cushion / 2R MFE floor / momentum / structure."""
    (
        _ema_engine_state,
        _one_r_points,
        ema_cluster_spread,
        is_ema_compressed,
        more_protective_stop,
        EmaStack,
    ) = _helpers()
    from .ema_strategy import green_target_exit_reason, lock_stop_at_green_target
    px = float(price)
    entry = float(getattr(trade, "entry", 0) or 0)
    side = trade.side
    atr_v = _atr(trade, atr)
    hard = float(getattr(trade, "hard_stop", 0) or 0) or float(trade.stop)
    trade.hard_stop = hard
    prev_stop = float(trade.stop)

    if side == Side.LONG and px <= hard + 1e-12:
        trade.ema_trade_state = AI_EXIT
        return True, "HARD_STOP", EngineState.EXIT
    if side == Side.SHORT and px >= hard - 1e-12:
        trade.ema_trade_state = AI_EXIT
        return True, "HARD_STOP", EngineState.EXIT

    one_r = max(_one_r_points(trade, cfg), 1e-9)
    r_mult = float(trade.mfe) / one_r
    close = _close(bars, px)
    e9 = float(ema9) if ema9 is not None else close
    e20 = float(ema20) if ema20 is not None else close
    e50 = float(ema50) if ema50 is not None else e20
    p9 = float(prev9) if prev9 is not None else e9
    p20 = float(prev20) if prev20 is not None else e20
    p50 = float(prev50) if prev50 is not None else e50
    trade.ai_ema9, trade.ai_ema20, trade.ai_ema50 = e9, e20, e50
    if rsi is not None:
        now_rsi = float(rsi)
        trade.rsi_peak = max(float(getattr(trade, "rsi_peak", 0) or 0), now_rsi)
        floor = float(getattr(trade, "rsi_floor", 0) or 0)
        trade.rsi_floor = now_rsi if floor <= 0 else min(floor, now_rsi)

    slope9 = (e9 - p9) / atr_v
    slope20 = (e20 - p20) / atr_v
    slope50 = (e50 - p50) / atr_v
    gap_now = (e9 - e20) if side == Side.LONG else (e20 - e9)
    gap_prev = (p9 - p20) if side == Side.LONG else (p20 - p9)
    tot = ema_cluster_spread(e9, e20, e50) or abs(gap_now)
    avg_gap = gap_prev
    if bars and len(bars) >= 2:
        avg_gap = (gap_now + gap_prev) / 2.0
    regime = classify_spread(gap_now, gap_prev, avg_gap, atr_v)
    compressed = False
    if ema9 is not None and ema20 is not None and ema50 is not None:
        compressed = is_ema_compressed(
            EmaStack(e9, e20, e50, p9, p20, p50), atr_v, cfg
        )
    long = side == Side.LONG
    bearish_cross = (e9 < e20) if long else (e9 > e20)
    lh, ll = swing_flags(side, bars)
    trade.ai_lower_high, trade.ai_lower_low = lh, ll
    px_gt_9 = (close > e9) if long else (close < e9)
    px_gt_20 = (close > e20) if long else (close < e20)
    death_bar = _bearish_structure_bar(side, bars, e20)
    score = momentum_score(
        side=side,
        slope9=slope9,
        slope20=slope20,
        gap_now=gap_now,
        gap_prev=gap_prev,
        close=close,
        ema9=e9,
        ema20=e20,
        compressed=compressed,
        bearish_cross=bearish_cross,
        lower_high=lh,
        lower_low=ll,
        bearish_bar=death_bar,
        spread_regime=regime,
        cfg=cfg,
    )
    trade.ai_momentum_score = score
    prev_ai = str(getattr(trade, "ai_exit_state", "") or "")
    state = _phase_state(r_mult, score, cfg, prev_ai)

    if (
        _cfg_bool(cfg, "ENABLE_MOMENTUM_REACCELERATION", True)
        and prev_ai in (AI_RUNNER_WATCH, AI_DYING)
        and state not in (AI_DYING, AI_RUNNER_WATCH)
        and regime == SPREAD_EXPANDING
        and ((slope9 > 0) if long else (slope9 < 0))
        and ((px + 1e-12 >= float(trade.peak)) if long else (px - 1e-12 <= float(trade.peak)))
        and ((slope20 >= -0.01) if long else (slope20 <= 0.01))
    ):
        state = AI_REACCEL

    protect = hard
    protect_r = _cfg_float(cfg, "PROTECT_AT_R", 1.0)
    cushion = _cfg_float(cfg, "PROTECT_ATR_CUSHION", 0.25)
    has_tgt = float(getattr(trade, "target", 0) or 0) > 0
    allow_r_floors = (not has_tgt) or bool(getattr(trade, "target_touched", False))
    if allow_r_floors and r_mult + 1e-12 >= protect_r:
        if long:
            protect = more_protective_stop(side, protect, entry - cushion * atr_v)
        else:
            protect = more_protective_stop(side, protect, entry + cushion * atr_v)

    runner_lock = None
    if (
        allow_r_floors
        and _cfg_bool(cfg, "ENABLE_MFE_RUNNER", True)
        and r_mult + 1e-12 >= _cfg_float(cfg, "RUNNER_START_R", 2.0)
    ):
        retain = _retain_frac(cfg)
        floor_pts = max(0.0, float(trade.mfe) * retain)
        prev_floor = float(getattr(trade, "giveback_floor_pts", 0) or 0)
        floor_pts = max(prev_floor, floor_pts)
        trade.giveback_floor_pts = floor_pts
        runner_lock = entry + floor_pts if long else entry - floor_pts
        protect = more_protective_stop(side, protect, runner_lock)

    protect = more_protective_stop(side, protect, prev_stop)
    protect = lock_stop_at_green_target(trade, price=px, protect=protect, cfg=cfg)
    if bool(getattr(trade, "target_touched", False)):
        trade.runner_trail_on = True
        if state == AI_DEVELOPING:
            state = AI_PROTECTED
    trade.stop = protect
    trade.ai_runner_floor = float(runner_lock or 0.0)
    trade.ai_protect_floor = protect

    floor_why = green_target_exit_reason(trade, price=px, protect=protect, cfg=cfg)
    if floor_why:
        return _flatten_ai(
            trade, floor_why, score, state, r_mult, runner_lock,
            protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
            px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
            "Green target is a floor. Trail never gives it back.",
        )

    on_green = bool(getattr(trade, "target_touched", False)) and abs(protect - float(getattr(trade, "target", 0) or 0)) <= _cfg_float(cfg, "TICK_SIZE", 0.25) * 0.51 + 1e-12
    if long and px <= protect + 1e-12 and not on_green:
        why = "RUNNER_PROFIT_FLOOR" if runner_lock is not None and abs(protect - float(runner_lock)) <= 1e-9 else "PROTECT"
        if abs(protect - hard) <= 1e-9:
            why = "HARD_STOP"
        trade.ema_trade_state = AI_EXIT
        trade.ai_exit_state = AI_EXIT
        snap = _snap(
            trade, state=AI_EXIT, score=score, decision="EXIT", reason=why, r_mult=r_mult,
            runner_lock=float(runner_lock or protect), protect=protect, slope9=slope9,
            slope20=slope20, slope50=slope50, gap_now=gap_now, atr_v=atr_v,
            vel=(gap_now - gap_prev) / atr_v, tot=tot, regime=regime, px_gt_9=px_gt_9,
            px_gt_20=px_gt_20, bearish_cross=bearish_cross, lh=lh, ll=ll,
            compressed=compressed, note="Protective floor hit (never widened).",
        )
        _log_snapshot(trade, snap)
        return True, why, EngineState.EXIT
    if (not long) and px >= protect - 1e-12 and not on_green:
        why = "RUNNER_PROFIT_FLOOR" if runner_lock is not None and abs(protect - float(runner_lock)) <= 1e-9 else "PROTECT"
        if abs(protect - hard) <= 1e-9:
            why = "HARD_STOP"
        trade.ema_trade_state = AI_EXIT
        trade.ai_exit_state = AI_EXIT
        snap = _snap(
            trade, state=AI_EXIT, score=score, decision="EXIT", reason=why, r_mult=r_mult,
            runner_lock=float(runner_lock or protect), protect=protect, slope9=slope9,
            slope20=slope20, slope50=slope50, gap_now=gap_now, atr_v=atr_v,
            vel=(gap_now - gap_prev) / atr_v, tot=tot, regime=regime, px_gt_9=px_gt_9,
            px_gt_20=px_gt_20, bearish_cross=bearish_cross, lh=lh, ll=ll,
            compressed=compressed, note="Protective floor hit (never widened).",
        )
        _log_snapshot(trade, snap)
        return True, why, EngineState.EXIT

    zone = getattr(trade, "barrier_view", None) if barriers_enabled(cfg) else None
    if isinstance(zone, BarrierZone) and zone.found:
        classic = classic_target_hit(side, px, close, zone, cfg)
        if classic:
            return _flatten_ai(
                trade, classic, score, state, r_mult, runner_lock,
                protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
                px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
                "Key-level take-profit (classic / hard barrier target).",
            )
        trail = barrier_trail_stop(side, px, atr_v, zone, cfg)
        if trail is not None:
            protect = more_protective_stop(side, protect, trail)
            protect = more_protective_stop(side, protect, prev_stop)
            trade.stop = protect
            trade.ai_protect_floor = protect
            hit_trail = (long and px <= protect + 1e-12) or ((not long) and px >= protect - 1e-12)
            if hit_trail:
                why = "PROTECT"
                if runner_lock is not None and abs(protect - float(runner_lock)) <= 1e-9:
                    why = "RUNNER_PROFIT_FLOOR"
                if abs(protect - hard) <= 1e-9:
                    why = "HARD_STOP"
                return _flatten_ai(
                    trade, why, score, state, r_mult, runner_lock,
                    protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
                    px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
                    "Barrier-aware trail floor (never widened).",
                )
        extra = 0
        if zone.state == BARRIER_TESTING:
            extra += 1
        if zone.rejection or zone.state == BARRIER_REJECTION:
            extra += 2 if int(zone.strength or 0) < 3 else 3
        elif zone.state == BARRIER_APPROACHING:
            extra += 0
        score = int(score) + extra
        trade.ai_momentum_score = score

    smart_why = smart_exit_reason(
        side,
        close=close,
        ema9=e9,
        ema20=e20,
        slope9=slope9,
        slope20=slope20,
        bearish_cross=bearish_cross,
        bars=bars,
        rsi_now=rsi,
        rsi_prev=rsi_prev,
        rsi_peak=float(getattr(trade, "rsi_peak", 0) or 0),
        rsi_floor=float(getattr(trade, "rsi_floor", 0) or 0),
        cfg=cfg,
    )
    if smart_why:
        note = (
            "9/20 flipped, close through 20, slopes rolled — trend reversed."
            if smart_why == "TREND_REVERSAL"
            else "RSI faded and candle follow-through died."
        )
        return _flatten_ai(
            trade, smart_why, score, state, r_mult, runner_lock,
            protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
            px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
            note,
        )

    collapsing = regime == SPREAD_COLLAPSE
    close_broke_20 = (close + 1e-12 < e20) if long else (close - 1e-12 > e20)
    early_bits = sum(
        (
            1 if bearish_cross else 0,
            1 if close_broke_20 else 0,
            1 if collapsing else 0,
            1 if ll else 0,
        )
    )
    need = max(2, _cfg_int(cfg, "EARLY_FAILURE_MIN_EVIDENCE", 3))
    exit_score = _cfg_int(cfg, "MOMENTUM_EXIT_SCORE", 7)
    dying_score = _cfg_int(cfg, "MOMENTUM_DYING_SCORE", 5)

    structure_break = (
        _cfg_bool(cfg, "ENABLE_STRUCTURE_OVERRIDE", True)
        and bearish_cross
        and close_broke_20
        and collapsing
    )
    if structure_break and (r_mult + 1e-12 >= protect_r or early_bits >= need):
        return _flatten_ai(
            trade, "MOMENTUM_STRUCTURE_BREAK", score, state, r_mult, runner_lock,
            protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
            px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
            "Completed 9/20 cross + close through 20 + collapsing spread.",
        )

    if r_mult + 1e-12 < protect_r and early_bits >= need:
        return _flatten_ai(
            trade, "EARLY_SETUP_FAILURE", score, state, r_mult, runner_lock,
            protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
            px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
            "Early failure: cross + close through 20 + collapse (multiple evidence).",
        )

    if compressed and r_mult + 1e-12 >= protect_r and bearish_cross:
        return _flatten_ai(
            trade, "EMA_COMPRESSION_EXIT", score, state, r_mult, runner_lock,
            protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
            px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
            "EMA cluster knotted after the trade was already working.",
        )

    if ll and bearish_cross and close_broke_20:
        return _flatten_ai(
            trade, "LOWER_LOW_BREAK", score, state, r_mult, runner_lock,
            protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
            px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
            "Lower low plus completed 9/20 failure.",
        )

    if score >= exit_score:
        return _flatten_ai(
            trade, "MOMENTUM_DEATH", score, state, r_mult, runner_lock,
            protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
            px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
            "Momentum score at exit threshold.",
        )

    if isinstance(zone, BarrierZone) and zone.found:
        why = rejection_exit_reason(zone, cfg)
        if why:
            return _flatten_ai(
                trade, why, score, state, r_mult, runner_lock,
                protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime,
                px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed,
                "Completed-bar rejection at the next key level.",
            )

    maybe_partial_exit(trade, state, cfg)
    trade.ai_exit_state = state
    trade.ema_trade_state = {
        AI_DEVELOPING: "PROBATION",
        AI_PROTECTED: "CONFIRMED",
        AI_RUNNER_HEALTHY: "RUNNER",
        AI_REACCEL: "RUNNER",
        AI_RUNNER_WATCH: "RUNNER",
        AI_DYING: "RUNNER",
    }.get(state, "PROBATION")
    note = "HOLD"
    if isinstance(zone, BarrierZone) and zone.found and zone.breakout:
        note = BARRIER_BREAKOUT_CONTINUE
    elif state == AI_RUNNER_WATCH:
        note = "Momentum weakening, but broader bullish structure remains intact."
    elif state == AI_REACCEL:
        note = "Spread/slope reaccelerated. MFE floor stays ratcheted."
    elif state == AI_DYING:
        note = "Momentum dying — waiting for structure/score exit, floor still holds."
    elif state == AI_RUNNER_HEALTHY:
        note = "Healthy runner. Expansion intact."
    elif state == AI_PROTECTED:
        note = "Protected. Room to develop; no single-bar panic."
    if isinstance(zone, BarrierZone) and zone.found:
        hold_decision = BARRIER_BREAKOUT_CONTINUE if zone.breakout else (
            "HOLD" if score < dying_score else "WATCH"
        )
        note = format_hold_log(
            zone=zone,
            momentum_score=score,
            spread_regime=regime,
            decision=hold_decision,
            note=note,
        )
    snap = _snap(
        trade, state=state, score=score, decision="HOLD" if score < dying_score else "WATCH",
        reason="", r_mult=r_mult, runner_lock=float(runner_lock or protect),
        protect=protect, slope9=slope9, slope20=slope20, slope50=slope50,
        gap_now=gap_now, atr_v=atr_v, vel=(gap_now - gap_prev) / atr_v, tot=tot,
        regime=regime, px_gt_9=px_gt_9, px_gt_20=px_gt_20, bearish_cross=bearish_cross,
        lh=lh, ll=ll, compressed=compressed, note=note,
    )
    _log_snapshot(trade, snap)
    if exit_armed and _cfg_bool(cfg, "EMA_OPPOSITE_CROSS_EXIT", False):
        return True, "OPPOSITE_EMA_CROSS", EngineState.EXIT
    return False, "", _ema_engine_state(trade)


def _snap(trade, **kw) -> AiExitSnapshot:
    from .ema_strategy import _one_r_points

    one_r = max(_one_r_points(trade), 1e-9)
    return AiExitSnapshot(
        state=kw["state"],
        score=int(kw["score"]),
        decision=kw["decision"],
        reason=kw["reason"],
        r_mult=float(kw["r_mult"]),
        mfe_pts=float(getattr(trade, "mfe", 0) or 0),
        mfe_r=float(getattr(trade, "mfe", 0) or 0) / one_r,
        runner_floor=float(kw["runner_lock"]),
        protect_floor=float(kw["protect"]),
        slope9=float(kw["slope9"]),
        slope20=float(kw["slope20"]),
        slope50=float(kw["slope50"]),
        gap_9_20=float(kw["gap_now"]),
        gap_9_20_atr=float(kw["gap_now"]) / max(float(kw["atr_v"]), 1e-9),
        spread_velocity=float(kw["vel"]),
        total_spread=float(kw["tot"]),
        spread_regime=str(kw["regime"]),
        price_gt_9=bool(kw["px_gt_9"]),
        price_gt_20=bool(kw["px_gt_20"]),
        bearish_cross=bool(kw["bearish_cross"]),
        lower_high=bool(kw["lh"]),
        lower_low=bool(kw["ll"]),
        compressed=bool(kw["compressed"]),
        note=str(kw["note"]),
    )


def _flatten_ai(trade, why, score, state, r_mult, runner_lock, protect, slope9, slope20, slope50, gap_now, atr_v, gap_prev, tot, regime, px_gt_9, px_gt_20, bearish_cross, lh, ll, compressed, note):
    trade.ema_trade_state = AI_EXIT
    trade.ai_exit_state = AI_EXIT
    snap = _snap(
        trade, state=AI_EXIT, score=score, decision="EXIT", reason=why, r_mult=r_mult,
        runner_lock=float(runner_lock or protect), protect=protect, slope9=slope9,
        slope20=slope20, slope50=slope50, gap_now=gap_now, atr_v=atr_v,
        vel=(gap_now - gap_prev) / atr_v, tot=tot, regime=regime, px_gt_9=px_gt_9,
        px_gt_20=px_gt_20, bearish_cross=bearish_cross, lh=lh, ll=ll,
        compressed=compressed, note=note,
    )
    _log_snapshot(trade, snap)
    return True, why, EngineState.EXIT
