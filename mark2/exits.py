"""Give the entry room, trail 5.5 after it works, then bank $25 and never give it back."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Mark2Config
from .trade_abort import check_thesis_abort
from .types import EngineState, ScoreBundle, Side


@dataclass
class PaperTrade:
    side: Side
    entry: float
    entry_ts: float
    stop: float
    target: float
    peak: float
    trough: float
    qty: int = 1
    mfe: float = 0.0
    mae: float = 0.0
    runner: bool = False
    target_touched: bool = False
    event_id: int = 0
    event_type: str = ""
    fees: float = 0.0
    peak_health: float = 0.0
    thesis_bad_streak: int = 0
    entry_confidence: float = 0.0
    chop_scalp: bool = False
    chaotic_bank: bool = False
    experimental: bool = False
    was_green: bool = False
    entry_opportunity: float = 0.0
    entry_rvol: float = 0.0
    entry_impulse: float = 0.0
    entry_velocity: float = 0.0
    entry_regime: str = ""
    entry_bias: str = ""
    entry_extension: float = 0.0
    time_to_mfe_2: float | None = None
    time_to_mfe_4: float | None = None
    time_to_bank: float | None = None
    peak_mfe_after_bank: float = 0.0
    manual_entry: bool = False
    goal_hunt: bool = False
    bank_dollars_locked: float = 0.0
    # Frozen risk stop (red chart line). Tip trail moves `stop` (purple).
    hard_stop: float = 0.0
    deep_hold: bool = False
    flip_armed: bool = False
    early_trail: bool = False
    tip_ts: float = 0.0
    last_peak: float = 0.0
    stall_score: float = 0.0
    stall_tight: bool = False
    ema_strategy: bool = False
    ema_trade_state: str = "WAITING"
    atr_at_entry: float = 0.0
    runner_trail_on: bool = False
    runner_trail_atr: float = 0.0
    runner_spread_atr: float | None = None
    runner_anchor: float = 0.0
    tip_trail_pts: float = 0.0
    tip_target_pts: float = 0.0
    ema_entry_tag: str = ""
    rsi_peak: float = 0.0
    rsi_floor: float = 0.0
    spread_peak: float = 0.0
    entry_spread: float = 0.0
    ema_lost_20: bool = False
    ema_lost_key: str = ""
    ema9_warn: bool = False
    giveback_floor_pts: float = 0.0
    trail_ratchet_usd: float = 0.0
    ai_exit_state: str = ""
    ai_momentum_score: int = 0
    ai_runner_floor: float = 0.0
    ai_protect_floor: float = 0.0
    ai_ema9: float = 0.0
    ai_ema20: float = 0.0
    ai_ema50: float = 0.0
    ai_lower_high: bool = False
    ai_lower_low: bool = False
    ai_last_log_key: object | None = None
    tcm8: bool = False
    tcm8_hold: bool = False
    tcm8_grade: str = ""
    tcm8_rejection: str = ""
    tcm8_target_r: float = 0.0
    tcm8_barrier_type: str = ""
    tcm8_primary_hit: bool = False
    tcm8_runner: bool = False


def goal_hunting(cfg: Mark2Config, *, goal_met: bool = False) -> bool:
    """True when daily-goal mode should use the short hunt bank."""
    if goal_met:
        return False
    if not bool(getattr(cfg, "ENABLE_DAILY_GOAL", False)):
        return False
    return float(getattr(cfg, "DAILY_GOAL_DOLLARS", 0) or 0) > 0


def trail_arm_usd(cfg: Mark2Config, *, trade: PaperTrade | None = None) -> float:
    """Total open-profit $ that arms the tip trail (scales with contract count)."""
    if trade is not None and float(getattr(trade, "bank_dollars_locked", 0) or 0) > 0:
        return max(1.0, float(trade.bank_dollars_locked))
    if trade is not None and bool(getattr(trade, "deep_hold", False)):
        return max(1.0, float(getattr(cfg, "DEEP_HOLD_ARM_USD", 300.0) or 300.0))
    if bool(getattr(cfg, "ENABLE_DEEP_HOLD", False)):
        return max(1.0, float(getattr(cfg, "DEEP_HOLD_ARM_USD", 300.0) or 300.0))
    return max(1.0, float(getattr(cfg, "TRAIL_ARM_USD", 15.0) or 15.0))


def deep_hold_active(cfg: Mark2Config, trade: PaperTrade | None = None) -> bool:
    if trade is not None and bool(getattr(trade, "deep_hold", False)):
        return True
    return bool(getattr(cfg, "ENABLE_DEEP_HOLD", False))


def market_flipped_against(
    trade: PaperTrade,
    *,
    snap,
    cfg: Mark2Config,
) -> bool:
    """True when RSI flips hard against the open side (wide 75/25 margin)."""
    try:
        from .exhaustion import read_exhaustion, rsi_ob_level, rsi_os_level

        reading = read_exhaustion(snap, cfg)
        ob = rsi_ob_level(cfg)
        os_lvl = rsi_os_level(cfg)
        if trade.side == Side.LONG and reading.rsi >= ob:
            return True
        if trade.side == Side.SHORT and reading.rsi <= os_lvl:
            return True
    except Exception:
        pass
    # Velocity slam against the trade
    vel = float(getattr(snap, "velocity", 0) or 0)
    if trade.side == Side.LONG and vel < -abs(float(getattr(cfg, "MIN_TICK_VELOCITY", 0.08) or 0.08)) * 4:
        return True
    if trade.side == Side.SHORT and vel > abs(float(getattr(cfg, "MIN_TICK_VELOCITY", 0.08) or 0.08)) * 4:
        return True
    return False


def _apply_flip_trail(trade: PaperTrade, cfg: Mark2Config, *, tick: float) -> None:
    """Market flipped before $300 — tip trail with floor at entry (never go red)."""
    trade.flip_armed = True
    trade.runner = True
    room = max(tick, float(getattr(cfg, "DEEP_HOLD_FLIP_TRAIL", 5.5) or 5.5))
    if trade.side == Side.LONG:
        trade.stop = max(float(trade.entry), float(trade.peak) - room)
    else:
        trade.stop = min(float(trade.entry), float(trade.peak) + room)


def early_trail_arm_usd(cfg: Mark2Config) -> float:
    return max(1.0, float(getattr(cfg, "EARLY_TRAIL_ARM_USD", 15.0) or 15.0))


def early_arm_points(cfg: Mark2Config, trade: PaperTrade) -> float:
    pv = max(float(cfg.POINT_VALUE), 1e-9)
    qty = max(1, int(getattr(trade, "qty", 1) or 1))
    return early_trail_arm_usd(cfg) / (pv * qty)


def early_lock_price(trade: PaperTrade, cfg: Mark2Config) -> float:
    pts = early_arm_points(cfg, trade)
    if trade.side == Side.LONG:
        return float(trade.entry) + pts
    return float(trade.entry) - pts


def open_profit_usd(trade: PaperTrade, price: float, cfg: Mark2Config) -> float:
    pts = _open_points(trade, price)
    return pts * float(cfg.POINT_VALUE) * max(1, int(trade.qty))


def _track_tip_time(trade: PaperTrade, *, ts: float) -> None:
    """Record when the tip (peak) last made a new extreme."""
    if trade.last_peak <= 0:
        trade.last_peak = float(trade.peak)
        trade.tip_ts = float(ts)
        return
    moved = False
    if trade.side == Side.LONG and float(trade.peak) > float(trade.last_peak) + 1e-9:
        moved = True
    if trade.side == Side.SHORT and float(trade.peak) < float(trade.last_peak) - 1e-9:
        moved = True
    if moved:
        trade.last_peak = float(trade.peak)
        trade.tip_ts = float(ts)


def stall_reversal_score(
    trade: PaperTrade,
    *,
    price: float,
    atr: float,
    snap,
    cfg: Mark2Config,
    hold_sec: float,
) -> float:
    """0–1: candle stuck / chopping after a push — likely reversal risk."""
    if snap is None:
        return 0.0
    tick = max(float(cfg.TICK_SIZE), 0.25)
    atr = max(float(atr), tick)
    score = 0.0

    # Time since last new tip (absolute clock)
    tip_age = 0.0
    if trade.tip_ts > 0:
        tip_age = max(0.0, float(getattr(snap, "ts", 0) or 0) - float(trade.tip_ts))
    stall_sec = max(2.0, float(getattr(cfg, "STALL_SEC", 6.0) or 6.0))
    if tip_age >= stall_sec * 0.45:
        score += min(0.45, tip_age / stall_sec * 0.45)

    # Forming bar range collapsed (fluctuating in place)
    form = getattr(snap, "forming_bar", None)
    if isinstance(form, dict):
        hi = float(form.get("high") or 0)
        lo = float(form.get("low") or 0)
        if hi > lo > 0:
            span = hi - lo
            frac = span / atr
            lim = float(getattr(cfg, "STALL_BAR_ATR_FRAC", 0.32) or 0.32)
            if frac <= lim:
                score += 0.35 * (1.0 - frac / max(lim, 1e-9))

    # Distance from tip — sitting off the high without making new highs
    if trade.side == Side.LONG:
        pull = max(0.0, float(trade.peak) - float(price))
    else:
        pull = max(0.0, float(price) - float(trade.peak))
    if pull >= tick and pull <= atr * 0.55:
        score += 0.15

    # Velocity dead / against the trade
    vel = float(getattr(snap, "velocity", 0) or 0)
    signed = vel if trade.side == Side.LONG else -vel
    if signed <= 0:
        score += 0.25
    elif signed < abs(float(getattr(cfg, "MIN_TICK_VELOCITY", 0.08) or 0.08)) * 0.5:
        score += 0.12

    del hold_sec
    return max(0.0, min(1.0, score))


def _stall_trail_room(cfg: Mark2Config, trade: PaperTrade, *, tick: float) -> float:
    """Normal runner room → aggressive squeeze as stall_score rises."""
    base = _runner_trail_points(cfg, trade)
    tight = max(tick, float(getattr(cfg, "STALL_TRAIL_ROOM", 0.75) or 0.75))
    s = max(0.0, min(1.0, float(getattr(trade, "stall_score", 0) or 0)))
    # Curve: mild until ~0.4, then slam shut
    if s < 0.35:
        blend = s / 0.35 * 0.25
    else:
        blend = 0.25 + (s - 0.35) / 0.65 * 0.75
    room = base * (1.0 - blend) + tight * blend
    return max(tick, room)


def _apply_stall_aware_trail(
    trade: PaperTrade,
    floor: float,
    cfg: Mark2Config,
    *,
    tick: float,
) -> None:
    """Tip trail with stall squeeze; never below `floor`."""
    trade.runner = True
    room = _stall_trail_room(cfg, trade, tick=tick)
    trade.stall_tight = float(getattr(trade, "stall_score", 0) or 0) >= 0.55
    if trade.side == Side.LONG:
        trail = float(trade.peak) - room
        trade.stop = max(float(floor), trail)
    else:
        trail = float(trade.peak) + room
        trade.stop = min(float(floor), trail)


def goal_hunt_bank_dollars(cfg: Mark2Config, *, session_pnl: float = 0.0) -> float:
    """Total open $ to arm trail while hunting the daily goal."""
    goal = float(getattr(cfg, "DAILY_GOAL_DOLLARS", 350.0) or 350.0)
    hunt = float(getattr(cfg, "TRAIL_ARM_USD", getattr(cfg, "GOAL_HUNT_BANK_DOLLARS", 15.0)) or 15.0)
    near_band = float(getattr(cfg, "GOAL_NEAR_DOLLARS", 30.0) or 30.0)
    near_bank = float(getattr(cfg, "GOAL_NEAR_BANK_DOLLARS", 10.0) or 10.0)
    remaining = goal - float(session_pnl)
    if remaining <= near_band:
        return max(5.0, min(near_bank, remaining if remaining > 5 else near_bank))
    return max(5.0, hunt)


def _bank_dollars_total(trade: PaperTrade | None, cfg: Mark2Config) -> float:
    """Total open-$ arm threshold for this trade (tip trail trigger)."""
    if trade is not None and float(getattr(trade, "bank_dollars_locked", 0) or 0) > 0:
        return max(1.0, float(trade.bank_dollars_locked))
    # Universal tip-trail arm: total open profit dollars.
    return trail_arm_usd(cfg, trade=trade)


def bank_points(cfg: Mark2Config, *, trade: PaperTrade | None = None) -> float:
    """MFE points needed to hit the total-$ trail arm."""
    pv = max(float(cfg.POINT_VALUE), 1e-9)
    qty = max(1, int(getattr(trade, "qty", 1) or 1)) if trade is not None else 1
    return _bank_dollars_total(trade, cfg) / (pv * qty)


def bank_dollars(qty: int, cfg: Mark2Config, *, trade: PaperTrade | None = None) -> float:
    """HUD / green-line dollars — total open $ to arm trail."""
    if trade is not None:
        return _bank_dollars_total(trade, cfg)
    return trail_arm_usd(cfg)


def lock_price(
    entry: float, side: Side, cfg: Mark2Config, *, trade: PaperTrade | None = None
) -> float:
    pts = bank_points(cfg, trade=trade)
    if side == Side.LONG:
        return entry + pts
    return entry - pts


def _approach_trail_points(cfg: Mark2Config, trade: PaperTrade | None = None) -> float:
    tick = max(float(cfg.TICK_SIZE), 0.25)
    if trade is not None and trade.chaotic_bank:
        return max(tick, float(getattr(cfg, "CHAOTIC_BANK_APPROACH_TRAIL", 3.0)))
    return max(tick, float(getattr(cfg, "APPROACH_TRAIL_POINTS", 5.5)))


def _trail_arm_points(cfg: Mark2Config, trade: PaperTrade | None = None) -> float:
    """MFE required before the approach trail moves the stop."""
    tick = max(float(cfg.TICK_SIZE), 0.25)
    if trade is not None and trade.chaotic_bank:
        raw = float(getattr(cfg, "CHAOTIC_BANK_TRAIL_ARM", 1.0))
        return max(tick, raw)
    raw = float(getattr(cfg, "TRAIL_ARM_POINTS", 6.0))
    return max(tick, raw)


def _runner_trail_points(cfg: Mark2Config, trade: PaperTrade | None = None) -> float:
    tick = max(float(cfg.TICK_SIZE), 0.25)
    if trade is not None and trade.chaotic_bank:
        return max(tick, float(getattr(cfg, "CHAOTIC_BANK_RUNNER_TRAIL", 3.0)))
    return max(tick, float(cfg.RUNNER_TRAIL_POINTS))


def _trail_points(trade: PaperTrade, cfg: Mark2Config) -> float:
    """Post-bank runner trail — always the normal runner distance."""
    return _runner_trail_points(cfg, trade)


def _dynamic_trail_room(trade: PaperTrade, cfg: Mark2Config) -> float:
    """Trail distance — full room until near bank, then tighten, then runner."""
    tick = max(float(cfg.TICK_SIZE), 0.25)
    if trade.target_touched:
        return _runner_trail_points(cfg, trade)
    approach = _approach_trail_points(cfg, trade)
    bank_pts = bank_points(cfg, trade=trade)
    if bank_pts <= tick:
        return approach
    buffer = max(tick, float(getattr(cfg, "TRAIL_TIGHTEN_BUFFER", 1.0)))
    if trade.mfe < bank_pts - buffer:
        return approach
    tighten = float(getattr(cfg, "TRAIL_TIGHTEN_AT_TARGET", 0.35))
    late = min(1.0, (trade.mfe - (bank_pts - buffer)) / buffer)
    return max(tick, approach * (1.0 - tighten * late))


def _apply_positive_trail(
    trade: PaperTrade, lock: float, cfg: Mark2Config, *, tick: float
) -> None:
    """After bank arm: tip trail floored at bank lock, stall-squeeze when choppy."""
    if trade.mfe <= 0:
        return
    trade.was_green = True
    if not trade.target_touched:
        return
    _apply_stall_aware_trail(trade, float(lock), cfg, tick=tick)


def manage_paper(
    trade: PaperTrade,
    *,
    price: float,
    atr: float,
    health: float,
    hold_sec: float,
    cfg: Mark2Config,
    scores: ScoreBundle | None = None,
    snap=None,
    event_alive: bool = True,
) -> tuple[bool, str, EngineState]:
    """Return (exit, reason, state)."""
    prev_peak = float(trade.peak)
    _mfe_mae(trade, price)
    trade.peak_health = max(trade.peak_health, health)
    _track_mfe_milestones(trade, hold_sec=hold_sec, cfg=cfg)

    tick = max(float(cfg.TICK_SIZE), 0.25)
    lock = lock_price(trade.entry, trade.side, cfg, trade=trade)
    early_lock = early_lock_price(trade, cfg)
    deep = deep_hold_active(cfg, trade)
    ts = float(getattr(snap, "ts", 0) or 0) if snap is not None else float(trade.entry_ts) + hold_sec
    if trade.tip_ts <= 0:
        trade.tip_ts = ts
        trade.last_peak = float(trade.peak)
    elif trade.side == Side.LONG and float(trade.peak) > prev_peak + 1e-12:
        trade.tip_ts = ts
        trade.last_peak = float(trade.peak)
    elif trade.side == Side.SHORT and float(trade.peak) < prev_peak - 1e-12:
        trade.tip_ts = ts
        trade.last_peak = float(trade.peak)

    # +$15 open profit → early tip trail (even during deep hold)
    early_pts = early_arm_points(cfg, trade)
    if not trade.early_trail and trade.mfe + 1e-12 >= early_pts:
        trade.early_trail = True
        trade.was_green = True

    # Stall / reverse-look score after we're green
    if trade.early_trail or trade.target_touched or trade.flip_armed:
        trade.stall_score = stall_reversal_score(
            trade,
            price=price,
            atr=float(atr) if atr else tick * 8,
            snap=snap,
            cfg=cfg,
            hold_sec=hold_sec,
        )
    else:
        trade.stall_score = 0.0

    # Deep hold: market flip against us → tip trail before $300 arm.
    if (
        deep
        and snap is not None
        and not trade.manual_entry
        and not trade.target_touched
        and not trade.flip_armed
        and market_flipped_against(trade, snap=snap, cfg=cfg)
    ):
        _apply_flip_trail(trade, cfg, tick=tick)

    if trade.mfe > 0 and bool(getattr(cfg, "ENABLE_GREEN_FLOOR", True)):
        if trade.target_touched:
            _apply_stall_aware_trail(trade, float(lock), cfg, tick=tick)
        elif trade.flip_armed:
            floor = float(trade.entry)
            # Still squeeze if stalled after flip
            room = _stall_trail_room(cfg, trade, tick=tick)
            trade.runner = True
            if trade.side == Side.LONG:
                trade.stop = max(floor, float(trade.peak) - room)
            else:
                trade.stop = min(floor, float(trade.peak) + room)
        elif trade.early_trail:
            # After +$15: trail with floor at $15 lock; stall → aggressive close-up
            _apply_stall_aware_trail(trade, float(early_lock), cfg, tick=tick)
        elif not deep:
            _apply_positive_trail(trade, lock, cfg, tick=tick)
        if trade.early_trail or trade.target_touched or trade.flip_armed:
            from .ema_strategy import apply_profit_keep_stop

            trade.stop = apply_profit_keep_stop(trade, float(trade.stop), cfg)

    if scores is not None and snap is not None and not trade.manual_entry and not deep:
        armed = trade.mfe >= _trail_arm_points(cfg, trade) or trade.early_trail
        allow_abort = armed and (
            trade.was_green or not bool(getattr(cfg, "ABORT_REQUIRES_GREEN", True))
        )
        if allow_abort:
            abort, detail, streak = check_thesis_abort(
                cfg=cfg,
                snap=snap,
                scores=scores,
                side=trade.side,
                health=health,
                peak_health=trade.peak_health,
                hold_sec=hold_sec,
                bad_streak=trade.thesis_bad_streak,
                event_alive=event_alive,
                chop_scalp=trade.chop_scalp,
            )
            trade.thesis_bad_streak = streak
        else:
            abort, detail = False, ""
            trade.thesis_bad_streak = 0
        if abort and trade.was_green and _open_points(trade, price) < 0:
            abort = False
        if abort:
            why = f"FAILED_EVENT:{detail}" if detail else "FAILED_EVENT"
            return True, why, EngineState.FAILED_EVENT

    if not trade.target_touched:
        pts_arm = bank_points(cfg, trade=trade)
        if trade.side == Side.LONG:
            hit_tgt = price >= trade.target or trade.mfe + 1e-12 >= pts_arm
        else:
            hit_tgt = price <= trade.target or trade.mfe + 1e-12 >= pts_arm
        if hit_tgt:
            trade.target_touched = True
            _apply_stall_aware_trail(trade, float(lock), cfg, tick=tick)
            return False, "", EngineState.TRADE_PROFITABLE

        # Early trail live (+$15): exit on tip trail / stall squeeze
        if trade.early_trail:
            floor = early_lock
            if _broke_bank_or_trail(trade, price, floor, tick):
                if trade.stall_tight:
                    why = "STALL_TRAIL"
                elif abs(trade.stop - floor) <= tick * 0.51:
                    why = "EARLY_BANK"
                else:
                    why = "TRAIL"
                return True, why, EngineState.EXIT
            return False, "", EngineState.TRADE_PROFITABLE

        # Deep hold + not flipped + not early: ignore hard stop until $300.
        if deep and not trade.flip_armed:
            return False, "", EngineState.TRADE_INITIAL

        if deep and trade.flip_armed:
            if _stop_hit(trade, price):
                if abs(trade.stop - trade.entry) <= tick * 0.51:
                    why = "FLIP_BE"
                else:
                    why = "FLIP_TRAIL"
                return True, why, EngineState.EXIT
            return False, "", EngineState.TRADE_PROFITABLE

        if _stop_hit(trade, price):
            if trade.was_green and abs(trade.stop - trade.entry) <= tick * 0.51:
                why = "BREAKEVEN"
            else:
                why = "STOP"
            return True, why, EngineState.EXIT
        return False, "", EngineState.TRADE_INITIAL

    pts = bank_points(cfg, trade=trade)
    if trade.mfe >= pts + tick:
        trade.runner = True
    if _broke_bank_or_trail(trade, price, lock, tick):
        if trade.side == Side.LONG:
            through_lock = price <= lock - tick
        else:
            through_lock = price >= lock + tick
        if trade.stall_tight:
            why = "STALL_TRAIL"
        elif through_lock or abs(trade.stop - lock) <= tick * 0.51:
            why = "BANK"
        else:
            why = "TRAIL"
        return True, why, EngineState.EXIT
    if trade.runner:
        return False, "", EngineState.RUNNER_MANAGEMENT
    return False, "", EngineState.TRADE_PROFITABLE

def _mfe_mae(trade: PaperTrade, price: float) -> None:
    if trade.side == Side.LONG:
        trade.peak = max(trade.peak, price)
        trade.trough = min(trade.trough, price)
        trade.mfe = max(0.0, trade.peak - trade.entry)
        trade.mae = max(0.0, trade.entry - trade.trough)
    else:
        trade.peak = min(trade.peak, price)
        trade.trough = max(trade.trough, price)
        trade.mfe = max(0.0, trade.entry - trade.peak)
        trade.mae = max(0.0, trade.trough - trade.entry)


def stop_points(cfg: Mark2Config, *, chop_scalp: bool = False, chaotic_bank: bool = False) -> float:
    tick = max(float(cfg.TICK_SIZE), 0.25)
    if bool(getattr(cfg, "ENABLE_DEEP_HOLD", False)):
        raw = float(getattr(cfg, "DEEP_HOLD_STOP_POINTS", 180.0) or 180.0)
        return max(tick * 4, min(400.0, raw))
    if chaotic_bank:
        raw = float(getattr(cfg, "CHAOTIC_BANK_STOP_POINTS", 14.0) or 0)
    elif chop_scalp:
        raw = float(getattr(cfg, "CHOP_SCALP_STOP_POINTS", 10.0) or 0)
    else:
        raw = float(getattr(cfg, "INITIAL_STOP_POINTS", 0) or 0)
    if raw > 0:
        return max(tick * 4, min(80.0, raw))
    return max(tick * 4, 20.0)


def initial_stop(
    entry: float,
    side: Side,
    atr: float,
    cfg: Mark2Config,
    *,
    chop_scalp: bool = False,
    chaotic_bank: bool = False,
) -> float:
    del atr
    gap = stop_points(cfg, chop_scalp=chop_scalp, chaotic_bank=chaotic_bank)
    if side == Side.LONG:
        return entry - gap
    return entry + gap


def initial_target(
    entry: float,
    side: Side,
    atr: float,
    cfg: Mark2Config,
    *,
    chop_scalp: bool = False,
    chaotic_bank: bool = False,
    goal_hunt: bool = False,
    bank_dollars_locked: float = 0.0,
) -> float:
    del atr
    trade = PaperTrade(
        side=side,
        entry=entry,
        entry_ts=0.0,
        stop=entry,
        target=entry,
        peak=entry,
        trough=entry,
        chop_scalp=chop_scalp,
        chaotic_bank=chaotic_bank,
        goal_hunt=goal_hunt,
        bank_dollars_locked=float(bank_dollars_locked or 0),
    )
    return lock_price(entry, side, cfg, trade=trade)


def _stop_hit(trade: PaperTrade, price: float) -> bool:
    if trade.side == Side.LONG:
        return price <= trade.stop
    return price >= trade.stop


def nt_stop_for_broker(
    side: Side, stop: float, market: float, tick: float
) -> tuple[float | None, bool]:
    """Validate a stop price before sending to NinjaTrader.

    Returns (price_to_send, flatten_now). NT rejects short cover stops at/below
    market and long stops at/above market — usually when trail ratchets while
    price bounces.
    """
    tick = max(float(tick), 0.25)
    stop = float(stop)
    market = float(market)
    # Require a tick through the stop — sitting on the bank floor (stop == market)
    # must not flatten; manage_paper owns that exit path.
    eps = tick * 0.51
    if side == Side.SHORT:
        if market >= stop + eps:
            return None, True
        if stop <= market + tick * 0.01:
            return None, False
        return stop, False
    if market <= stop - eps:
        return None, True
    if stop >= market - tick * 0.01:
        return None, False
    return stop, False


def broker_stop_for_nt(
    trade: PaperTrade,
    stop: float,
    market: float,
    lock: float,
    cfg: Mark2Config,
) -> tuple[float | None, bool]:
    """Clamp post-bank stops for NT and never emergency-flatten after bank touch.

    Once tip trail is armed ($15 total open profit): follow tip by runner room,
    floored at the bank lock so the $15 floor cannot collapse to breakeven.
    """
    tick = max(float(cfg.TICK_SIZE), 0.25)
    stop = float(stop)
    market = float(market)
    lock = float(lock)
    room = _runner_trail_points(cfg, trade)
    if trade.target_touched:
        if trade.side == Side.LONG:
            stop = max(lock, float(trade.peak) - room)
        else:
            stop = min(lock, float(trade.peak) + room)
        broker_stop, flatten = nt_stop_for_broker(trade.side, stop, market, tick)
        if flatten:
            flatten = False
        return broker_stop, flatten

    broker_stop, flatten = nt_stop_for_broker(trade.side, stop, market, tick)
    return broker_stop, flatten


def _open_points(trade: PaperTrade, price: float) -> float:
    if trade.side == Side.LONG:
        return price - trade.entry
    return trade.entry - price


def _apply_green_floor(trade: PaperTrade, tick: float, *, cfg: Mark2Config) -> None:
    """Legacy hook — marks green; stop placement is the 5.5 approach trail."""
    del tick, cfg
    if trade.mfe > 0:
        trade.was_green = True


def _track_mfe_milestones(trade: PaperTrade, *, hold_sec: float, cfg: Mark2Config) -> None:
    if trade.time_to_mfe_2 is None and trade.mfe >= 2.0:
        trade.time_to_mfe_2 = hold_sec
    if trade.time_to_mfe_4 is None and trade.mfe >= 4.0:
        trade.time_to_mfe_4 = hold_sec
    if trade.target_touched:
        if trade.time_to_bank is None:
            trade.time_to_bank = hold_sec
        trade.peak_mfe_after_bank = max(trade.peak_mfe_after_bank, trade.mfe)


def manage_manual_hold(
    trade: PaperTrade,
    *,
    price: float,
    cfg: Mark2Config,
) -> tuple[bool, str, EngineState]:
    """Operator-owned HUD trade: track MFE/MAE; exit only on frozen hard stop.

    Tip trail / bank / thesis exits must not steal a discretionary manual entry.
    """
    _mfe_mae(trade, price)
    hard = float(getattr(trade, "hard_stop", 0) or 0)
    if hard <= 0:
        hard = float(trade.stop)
    trade.hard_stop = hard
    # Keep the live stop parked on the hard risk line — never tip-trail a manual.
    trade.stop = hard
    tick = max(float(cfg.TICK_SIZE), 0.25)
    if trade.side == Side.LONG:
        hit = price <= hard + 1e-12
    else:
        hit = price >= hard - 1e-12
    if hit:
        why = "BREAKEVEN" if abs(hard - trade.entry) <= tick * 0.51 else "STOP"
        return True, why, EngineState.EXIT
    if trade.mfe > 0:
        return False, "", EngineState.TRADE_PROFITABLE
    return False, "", EngineState.TRADE_INITIAL


def _broke_bank_or_trail(trade: PaperTrade, price: float, lock: float, tick: float) -> bool:
    """$25 bank soft floor. Sitting on it does not flatten; one tick through does.

    Tip trail only exits once stop has ratcheted past the floor (tip ran room past lock).
    """
    if trade.side == Side.LONG:
        if price <= lock - tick:
            return True
        if trade.stop > lock + tick * 0.51:
            return price <= trade.stop
        return False
    if price >= lock + tick:
        return True
    if trade.stop < lock - tick * 0.51:
        return price >= trade.stop
    if trade.stop >= lock + tick * 0.51:
        return price >= trade.stop
    return False


def _apply_tip_trail(
    trade: PaperTrade, lock: float, cfg: Mark2Config, *, floor_active: bool
) -> None:
    """Trail stop N points behind the tip (peak for long, trough for short)."""
    room = _runner_trail_points(cfg, trade)
    tick = max(float(cfg.TICK_SIZE), 0.25)
    pts = bank_points(cfg, trade=trade)
    if trade.mfe >= pts + tick:
        trade.runner = True
    if trade.side == Side.LONG:
        trail = trade.peak - room
        if floor_active:
            trade.stop = max(lock, trail)
        else:
            trade.stop = max(trade.stop, trail)
    else:
        trail = trade.peak + room
        if floor_active:
            trade.stop = min(lock, trail)
        else:
            trade.stop = min(trade.stop, trail)


def _apply_bank_trail(trade: PaperTrade, lock: float, cfg: Mark2Config) -> None:
    _apply_tip_trail(trade, lock, cfg, floor_active=True)
