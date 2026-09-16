"""Daily-goal clock pressure — mild late-window push; keep smart entry filters."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Mark2Config
from .exits import goal_hunt_bank_dollars, goal_hunting


@dataclass(frozen=True)
class GoalPressure:
    """Live overrides while hunting under a time clock. pressure 0=calm … 1=full push."""

    active: bool = False
    pressure: float = 0.0
    bank_dollars: float = 0.0
    conf_delta: float = 0.0
    opp_delta: float = 0.0
    conf_vel_delta: float = 0.0
    build_ticks_delta: int = 0
    gap_delta: float = 0.0
    force_chop: bool = False
    relax_candle: bool = False
    bypass_candle: bool = False
    bypass_volume: bool = False
    bypass_structure: bool = False
    bypass_regime: bool = False
    bypass_quality: bool = False
    cooldown_sec: float | None = None
    conf_floor: float = 48.0
    opp_floor: float = 45.0
    conf_vel_floor: float = 0.08

    @property
    def pct(self) -> float:
        return round(100.0 * self.pressure, 1)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def clock_pressure_frac(
    cfg: Mark2Config,
    *,
    started_ts: float | None,
    now_ts: float,
    goal_met: bool = False,
) -> float:
    """0 early → 1 near deadline. No hard floor — keep early trades selective."""
    if goal_met or not goal_hunting(cfg, goal_met=goal_met):
        return 0.0
    if not bool(getattr(cfg, "GOAL_PRESSURE_ENABLED", True)):
        return 0.0
    try:
        window_h = float(getattr(cfg, "GOAL_WINDOW_HOURS", 0) or 0)
    except (TypeError, ValueError):
        window_h = 0.0
    if window_h <= 0:
        return 0.0
    if started_ts is None or now_ts <= 0:
        return 0.0
    window_sec = max(1.0, window_h * 3600.0)
    elapsed = max(0.0, float(now_ts) - float(started_ts))
    frac = _clamp01(elapsed / window_sec)
    # Ease-in: stay selective early, push only in the back half.
    return _clamp01(frac ** 1.25)


def compute_goal_pressure(
    cfg: Mark2Config,
    *,
    started_ts: float | None,
    now_ts: float,
    session_pnl: float = 0.0,
    goal_met: bool = False,
) -> GoalPressure:
    if not goal_hunting(cfg, goal_met=goal_met):
        return GoalPressure()
    p = clock_pressure_frac(
        cfg, started_ts=started_ts, now_ts=now_ts, goal_met=goal_met
    )
    bank = goal_hunt_bank_dollars(cfg, session_pnl=session_pnl)

    # Mild cuts only — filters stay on; no bypass of candle/volume/regime.
    conf_cut = float(getattr(cfg, "GOAL_PRESSURE_CONF_CUT", 6.0) or 6.0)
    opp_cut = float(getattr(cfg, "GOAL_PRESSURE_OPP_CUT", 5.0) or 5.0)
    vel_cut = float(getattr(cfg, "GOAL_PRESSURE_VEL_CUT", 0.12) or 0.12)
    build_cut = int(getattr(cfg, "GOAL_PRESSURE_BUILD_CUT", 1) or 1)
    gap_cut = float(getattr(cfg, "GOAL_PRESSURE_GAP_CUT", 2.0) or 2.0)
    chop_at = float(getattr(cfg, "GOAL_PRESSURE_CHOP_AT", 0.65) or 0.65)
    candle_at = float(getattr(cfg, "GOAL_PRESSURE_CANDLE_AT", 0.7) or 0.7)
    # Keep a real post-exit pause so the next entry is a new decision.
    cool_floor = float(getattr(cfg, "GOAL_PRESSURE_COOLDOWN_SEC", 2.5) or 2.5)
    cool_base = float(getattr(cfg, "DEFAULT_EXIT_COOLDOWN_SEC", 3.0) or 3.0)
    conf_floor = float(getattr(cfg, "GOAL_PRESSURE_CONF_FLOOR", 48.0))
    opp_floor = float(getattr(cfg, "GOAL_PRESSURE_OPP_FLOOR", 45.0))
    try:
        vel_floor = float(getattr(cfg, "GOAL_PRESSURE_VEL_FLOOR", 0.08))
    except (TypeError, ValueError):
        vel_floor = 0.08

    open_gates = bool(getattr(cfg, "GOAL_HUNT_OPEN_GATES", True))
    # Hunt mode: open the gates that otherwise leave the bot flat all session.
    push = max(p, 0.35) if open_gates else p
    return GoalPressure(
        active=True,
        pressure=push,
        bank_dollars=round(bank, 2),
        conf_delta=-conf_cut * push,
        opp_delta=-opp_cut * push,
        conf_vel_delta=-vel_cut * push,
        build_ticks_delta=-max(0, int(round(build_cut * push))),
        gap_delta=-gap_cut * push,
        force_chop=True if open_gates else push >= chop_at,
        relax_candle=True if open_gates else push >= candle_at,
        bypass_candle=open_gates,
        bypass_volume=open_gates,
        bypass_structure=open_gates,
        bypass_regime=open_gates,
        bypass_quality=True if open_gates else push >= 0.85,
        cooldown_sec=max(cool_floor, cool_base + (cool_floor - cool_base) * push),
        conf_floor=conf_floor,
        opp_floor=opp_floor,
        conf_vel_floor=vel_floor,
    )


def apply_pressure_to_chop_needs(
    cfg: Mark2Config,
    pressure: GoalPressure,
) -> tuple[float, float, float, float, float]:
    """Return (conf, opp, tick_vel, conf_vel, gap) loosened by clock pressure."""
    need_conf = float(getattr(cfg, "CHOP_SCALP_CONFIDENCE", 52.0))
    need_opp = float(getattr(cfg, "CHOP_SCALP_OPPORTUNITY", 60.0))
    need_vel = float(getattr(cfg, "CHOP_SCALP_MIN_TICK_VEL", 0.35))
    need_conf_v = float(getattr(cfg, "CHOP_SCALP_MIN_CONF_VEL", 0.18))
    gap = float(getattr(cfg, "CHOP_SCALP_DIRECTION_GAP", 10.0))
    if not pressure.active or pressure.pressure <= 0:
        return need_conf, need_opp, need_vel, need_conf_v, gap
    p = pressure.pressure
    return (
        max(pressure.conf_floor, need_conf + pressure.conf_delta),
        max(pressure.opp_floor, need_opp + pressure.opp_delta),
        max(0.15, need_vel * (1.0 - 0.35 * p)),
        max(pressure.conf_vel_floor, need_conf_v + pressure.conf_vel_delta),
        max(5.0, gap + pressure.gap_delta),
    )
