"""ENTRY / EXIT strategy knobs for the HUD. Wired to live ema_strategy / engine config."""

from __future__ import annotations

from typing import Any

from .config import Mark2Config

_BOOL_KEYS = {
    "leftover_long": "EMA_LEFTOVER_LONG",
    "allow_long": "EMA_ALLOW_LONG",
    "allow_short": "EMA_ALLOW_SHORT",
    "long_sniper": "EMA_LONG_SNIPER",
    "short_sniper": "EMA_SHORT_SNIPER",
    "rsi_long": "EMA_RSI_LONG",
    "chop_long": "EMA_CHOP_LONG",
    "scout": "ENABLE_AI_SCOUT",
    "one_per_stack": "EMA_ONE_PER_STACK",
    "ema_quality_filter": "ENABLE_EMA_QUALITY_FILTER",
    "ai_exit_engine": "ENABLE_AI_EXIT_ENGINE",
    "momentum_score": "ENABLE_MOMENTUM_SCORE",
    "mfe_runner": "ENABLE_MFE_RUNNER",
    "structure_override": "ENABLE_STRUCTURE_OVERRIDE",
    "momentum_reacceleration": "ENABLE_MOMENTUM_REACCELERATION",
    "grow_mode": "ENABLE_GROW_MODE",
    "breakout_413": "ENABLE_413_BREAKOUT",
    "momentum_barriers": "ENABLE_MOMENTUM_BARRIERS",
    "tcm8": "ENABLE_8TCM",
    "tcm8_longs": "ENABLE_8TCM_LONGS",
    "tcm8_shorts": "ENABLE_8TCM_SHORTS",
    "tcm8_classic_target": "ENABLE_8TCM_CLASSIC_TARGET",
    "tcm8_ai_exit": "ENABLE_8TCM_AI_EXIT",
    "tcm8_runner": "ENABLE_8TCM_RUNNER",
}

_NUM_KEYS = {
    "min_sep_atr": ("EMA_MIN_SEP_ATR", 0.0, 3.0, False),
    "min_sep_points": ("EMA_MIN_SEP_POINTS", 0.0, 40.0, False),
    "max_entry_ext_atr": ("MAX_ENTRY_EXTENSION_ATR", 0.10, 4.0, False),
    "contracts": ("CONTRACTS", 1.0, 50.0, True),
    "mfe_keep_pct": ("MFE_KEEP_PCT", 50.0, 95.0, False),
    "tip_trail_arm_usd": ("TIP_TRAIL_ARM_USD", 15.0, 400.0, False),
    "probation_atr": ("INITIAL_STOP_ATR", 0.25, 4.0, False),
    "confirm_1r_atr": ("CONFIRMED_TREND_TRIGGER_ATR", 0.25, 4.0, False),
    "catastrophic_atr": ("CATASTROPHIC_STOP_ATR", 0.40, 5.0, False),
    "reentry_cooldown": ("EMA_REENTRY_COOLDOWN_SEC", 0.0, 60.0, False),
    "daily_goal": ("DAILY_GOAL_DOLLARS", 0.0, 5000.0, False),
    "breakout_413_max_stop": ("BREAKOUT_413_MAX_STOP_PTS", 8.0, 80.0, False),
    "tcm8_ema_period": ("TCM8_EMA_PERIOD", 2.0, 20.0, True),
    "tcm8_trend_slope_lookback": ("TCM8_TREND_SLOPE_LOOKBACK", 2.0, 20.0, True),
    "tcm8_min_trend_slope_atr": ("TCM8_MIN_TREND_SLOPE_ATR", 0.01, 0.50, False),
    "tcm8_pullback_max_distance_atr": ("TCM8_PULLBACK_MAX_DISTANCE_ATR", 0.05, 0.50, False),
    "tcm8_ema_touch_tolerance_atr": ("TCM8_EMA_TOUCH_TOLERANCE_ATR", 0.05, 0.50, False),
    "tcm8_max_ema_penetration_atr": ("TCM8_MAX_EMA_PENETRATION_ATR", 0.05, 1.00, False),
    "tcm8_max_entry_distance_from_ema_atr": ("TCM8_MAX_ENTRY_DISTANCE_FROM_EMA_ATR", 0.10, 1.00, False),
    "tcm8_strong_wick_body_ratio": ("TCM8_STRONG_WICK_BODY_RATIO", 1.00, 4.00, False),
    "tcm8_pin_bar_wick_body_ratio": ("TCM8_PIN_BAR_WICK_BODY_RATIO", 1.00, 5.00, False),
    "tcm8_min_rejection_body_atr": ("TCM8_MIN_REJECTION_BODY_ATR", 0.05, 1.00, False),
    "tcm8_barrier_proximity_block_atr": ("TCM8_BARRIER_PROXIMITY_BLOCK_ATR", 0.05, 1.00, False),
    "tcm8_consolidation_lookback": ("TCM8_CONSOLIDATION_LOOKBACK", 4.0, 30.0, True),
    "tcm8_swing_strength": ("TCM8_SWING_STRENGTH", 1.0, 5.0, True),
    "tcm8_consolidation_max_range_atr": ("TCM8_CONSOLIDATION_MAX_RANGE_ATR", 0.25, 3.00, False),
    "tcm8_stop_buffer_atr": ("TCM8_STOP_BUFFER_ATR", 0.02, 0.50, False),
    "tcm8_minimum_target_r": ("TCM8_MINIMUM_TARGET_R", 0.25, 2.00, False),
    "tcm8_preferred_target_r": ("TCM8_PREFERRED_TARGET_R", 0.50, 4.00, False),
}

_RISK_PROFILES = ("OFF", "SMALL_250", "STANDARD")


def _mfe_keep_pct(cfg: Mark2Config) -> float:
    give = float(getattr(cfg, "MFE_GIVEBACK_FRAC", 0.30) or 0.30)
    return round(max(0.0, min(100.0, (1.0 - give) * 100.0)), 1)


def _ema_92050_live(cfg: Mark2Config) -> bool:
    if not bool(getattr(cfg, "ENABLE_EMA_STRATEGY", False)):
        return False
    return bool(
        getattr(cfg, "EMA_LONG_SNIPER", True)
        or getattr(cfg, "EMA_SHORT_SNIPER", True)
        or getattr(cfg, "EMA_LEFTOVER_LONG", False)
    )


def _set_mfe_keep_pct(cfg: Mark2Config, pct: float) -> None:
    keep = max(50.0, min(95.0, float(pct)))
    cfg.MFE_GIVEBACK_FRAC = round(1.0 - (keep / 100.0), 4)
    cfg.RUNNER_MFE_RETAIN = round(keep / 100.0, 4)


def snapshot(cfg: Mark2Config) -> dict[str, Any]:
    risk = str(getattr(cfg, "ACCOUNT_RISK_PROFILE", "OFF") or "OFF").upper()
    if risk not in _RISK_PROFILES:
        risk = "OFF"
    return {
        "leftover_long": bool(getattr(cfg, "EMA_LEFTOVER_LONG", True)),
        "allow_long": bool(getattr(cfg, "EMA_ALLOW_LONG", True)),
        "allow_short": bool(getattr(cfg, "EMA_ALLOW_SHORT", False)),
        "long_sniper": bool(getattr(cfg, "EMA_LONG_SNIPER", True)),
        "short_sniper": bool(getattr(cfg, "EMA_SHORT_SNIPER", True)),
        "rsi_long": bool(getattr(cfg, "EMA_RSI_LONG", False)),
        "chop_long": bool(getattr(cfg, "EMA_CHOP_LONG", False)),
        "scout": bool(getattr(cfg, "ENABLE_AI_SCOUT", True)),
        "one_per_stack": bool(getattr(cfg, "EMA_ONE_PER_STACK", True)),
        "ema_quality_filter": bool(getattr(cfg, "ENABLE_EMA_QUALITY_FILTER", True)),
        "ai_exit_engine": bool(getattr(cfg, "ENABLE_AI_EXIT_ENGINE", False)),
        "momentum_score": bool(getattr(cfg, "ENABLE_MOMENTUM_SCORE", True)),
        "mfe_runner": bool(getattr(cfg, "ENABLE_MFE_RUNNER", True)),
        "structure_override": bool(getattr(cfg, "ENABLE_STRUCTURE_OVERRIDE", True)),
        "momentum_reacceleration": bool(getattr(cfg, "ENABLE_MOMENTUM_REACCELERATION", True)),
        "grow_mode": bool(getattr(cfg, "ENABLE_GROW_MODE", False)),
        "breakout_413": bool(getattr(cfg, "ENABLE_413_BREAKOUT", False)),
        "momentum_barriers": bool(getattr(cfg, "ENABLE_MOMENTUM_BARRIERS", False)),
        "ema_92050": _ema_92050_live(cfg),
        "tcm8": bool(getattr(cfg, "ENABLE_8TCM", False)),
        "tcm8_longs": bool(getattr(cfg, "ENABLE_8TCM_LONGS", True)),
        "tcm8_shorts": bool(getattr(cfg, "ENABLE_8TCM_SHORTS", False)),
        "tcm8_classic_target": bool(getattr(cfg, "ENABLE_8TCM_CLASSIC_TARGET", True)),
        "tcm8_ai_exit": bool(getattr(cfg, "ENABLE_8TCM_AI_EXIT", False)),
        "tcm8_runner": bool(getattr(cfg, "ENABLE_8TCM_RUNNER", True)),
        "tcm8_ema_period": int(getattr(cfg, "TCM8_EMA_PERIOD", 8) or 8),
        "tcm8_trend_slope_lookback": int(getattr(cfg, "TCM8_TREND_SLOPE_LOOKBACK", 5) or 5),
        "tcm8_min_trend_slope_atr": float(getattr(cfg, "TCM8_MIN_TREND_SLOPE_ATR", 0.05) or 0.05),
        "tcm8_pullback_max_distance_atr": float(getattr(cfg, "TCM8_PULLBACK_MAX_DISTANCE_ATR", 0.15) or 0.15),
        "tcm8_ema_touch_tolerance_atr": float(getattr(cfg, "TCM8_EMA_TOUCH_TOLERANCE_ATR", 0.10) or 0.10),
        "tcm8_max_ema_penetration_atr": float(getattr(cfg, "TCM8_MAX_EMA_PENETRATION_ATR", 0.20) or 0.20),
        "tcm8_max_entry_distance_from_ema_atr": float(getattr(cfg, "TCM8_MAX_ENTRY_DISTANCE_FROM_EMA_ATR", 0.30) or 0.30),
        "tcm8_strong_wick_body_ratio": float(getattr(cfg, "TCM8_STRONG_WICK_BODY_RATIO", 1.50) or 1.50),
        "tcm8_pin_bar_wick_body_ratio": float(getattr(cfg, "TCM8_PIN_BAR_WICK_BODY_RATIO", 2.00) or 2.00),
        "tcm8_min_rejection_body_atr": float(getattr(cfg, "TCM8_MIN_REJECTION_BODY_ATR", 0.15) or 0.15),
        "tcm8_barrier_proximity_block_atr": float(getattr(cfg, "TCM8_BARRIER_PROXIMITY_BLOCK_ATR", 0.25) or 0.25),
        "tcm8_consolidation_lookback": int(getattr(cfg, "TCM8_CONSOLIDATION_LOOKBACK", 10) or 10),
        "tcm8_swing_strength": int(getattr(cfg, "TCM8_SWING_STRENGTH", 2) or 2),
        "tcm8_consolidation_max_range_atr": float(getattr(cfg, "TCM8_CONSOLIDATION_MAX_RANGE_ATR", 1.00) or 1.00),
        "tcm8_stop_buffer_atr": float(getattr(cfg, "TCM8_STOP_BUFFER_ATR", 0.10) or 0.10),
        "tcm8_minimum_target_r": float(getattr(cfg, "TCM8_MINIMUM_TARGET_R", 0.75) or 0.75),
        "tcm8_preferred_target_r": float(getattr(cfg, "TCM8_PREFERRED_TARGET_R", 1.50) or 1.50),
        "breakout_413_mode": str(getattr(cfg, "BREAKOUT_413_MODE", "BREAKOUT") or "BREAKOUT").upper(),
        "breakout_413_max_stop": float(getattr(cfg, "BREAKOUT_413_MAX_STOP_PTS", 40.0) or 40.0),
        "min_sep_atr": float(getattr(cfg, "EMA_MIN_SEP_ATR", 0.20) or 0.20),
        "min_sep_points": float(getattr(cfg, "EMA_MIN_SEP_POINTS", 3.0) or 3.0),
        "max_entry_ext_atr": float(getattr(cfg, "MAX_ENTRY_EXTENSION_ATR", 0.60) or 0.60),
        "contracts": int(cfg.contracts()),
        "account_risk": risk,
        "mfe_keep_pct": _mfe_keep_pct(cfg),
        "tip_trail_arm_usd": float(getattr(cfg, "TIP_TRAIL_ARM_USD", 100.0) or 100.0),
        "probation_atr": float(getattr(cfg, "INITIAL_STOP_ATR", 1.50) or 1.50),
        "confirm_1r_atr": float(getattr(cfg, "CONFIRMED_TREND_TRIGGER_ATR", 1.0) or 1.0),
        "catastrophic_atr": float(getattr(cfg, "CATASTROPHIC_STOP_ATR", 1.50) or 1.50),
        "reentry_cooldown": float(getattr(cfg, "EMA_REENTRY_COOLDOWN_SEC", 5.0) or 0.0),
        "daily_goal": float(getattr(cfg, "DAILY_GOAL_DOLLARS", 350.0) or 0.0),
    }


def apply_momentum_barrier_pack(cfg: Mark2Config, enabled: bool) -> None:
    """One HUD switch. On = this strategy alone + AI exit/trail. Off = old Recon entries."""
    cfg.ENABLE_MOMENTUM_BARRIERS = bool(enabled)
    if enabled:
        cfg.ENABLE_8TCM = False
        cfg.ENABLE_BARRIER_STRATEGY_ONLY = True
        cfg.ENABLE_BARRIER_ENTRY_FILTER = True
        cfg.ENABLE_BARRIER_REJECTION_EXIT = True
        cfg.ENABLE_CLASSIC_KEY_LEVEL_TARGET = False
        cfg.ENABLE_HARD_BARRIER_TARGET = False
        cfg.ENABLE_AI_EXIT_ENGINE = True
        cfg.ENABLE_MOMENTUM_SCORE = True
        cfg.ENABLE_MFE_RUNNER = True
        return
    cfg.ENABLE_BARRIER_STRATEGY_ONLY = False


def apply_92050_pack(cfg: Mark2Config, enabled: bool) -> None:
    """HUD master for EMA 9/20/50. Off = this method does not fire. Independent of 8TCM."""
    if enabled:
        cfg.ENABLE_EMA_STRATEGY = True
        cfg.EMA_LONG_SNIPER = True
        cfg.EMA_SHORT_SNIPER = True
        cfg.EMA_ALLOW_LONG = True
        cfg.EMA_ALLOW_SHORT = True
        cfg.EMA_LEFTOVER_LONG = False
        cfg.EMA_RSI_LONG = False
        cfg.EMA_CHOP_LONG = False
        cfg.ENABLE_AI_SCOUT = False
        cfg.ENABLE_413_BREAKOUT = False
        cfg.EMA_ONE_PER_STACK = True
        cfg.ENABLE_EMA_QUALITY_FILTER = True
        cfg.ALLOW_LEGACY_ENTRIES = False
        cfg.ENABLE_MOMENTUM_BARRIERS = False
        cfg.ENABLE_BARRIER_STRATEGY_ONLY = False
        cfg.ENABLE_AI_EXIT_ENGINE = True
        cfg.ENABLE_MOMENTUM_SCORE = True
        cfg.ENABLE_MFE_RUNNER = True
        cfg.ENABLE_STRUCTURE_OVERRIDE = True
        cfg.ENABLE_MOMENTUM_REACCELERATION = True
        return
    cfg.EMA_LONG_SNIPER = False
    cfg.EMA_SHORT_SNIPER = False
    cfg.EMA_ALLOW_LONG = False
    cfg.EMA_ALLOW_SHORT = False
    cfg.EMA_LEFTOVER_LONG = False
    cfg.EMA_RSI_LONG = False
    cfg.EMA_CHOP_LONG = False
    cfg.ENABLE_AI_SCOUT = False
    cfg.ENABLE_413_BREAKOUT = False


def apply_8tcm_pack(cfg: Mark2Config, enabled: bool) -> None:
    """HUD master for 8TCM. Independent of 9/20/50. One open trade total."""
    cfg.ENABLE_8TCM = bool(enabled)
    if not enabled:
        return
    cfg.ENABLE_8TCM_LONGS = True
    cfg.ENABLE_8TCM_SHORTS = False
    cfg.ENABLE_8TCM_CLASSIC_TARGET = True
    cfg.ENABLE_8TCM_AI_EXIT = False
    cfg.ENABLE_8TCM_RUNNER = True
    cfg.ENABLE_8TCM_EARLY_ENTRY = False
    cfg.ALLOW_LEGACY_ENTRIES = False
    cfg.ENABLE_MOMENTUM_BARRIERS = False
    cfg.ENABLE_BARRIER_STRATEGY_ONLY = False
    cfg.ENABLE_413_BREAKOUT = False


def apply_strategy(cfg: Mark2Config, payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    for key, attr in _BOOL_KEYS.items():
        if key in data:
            setattr(cfg, attr, bool(data[key]))
    if "momentum_barriers" in data:
        apply_momentum_barrier_pack(cfg, bool(data["momentum_barriers"]))
    if "ema_92050" in data:
        apply_92050_pack(cfg, bool(data["ema_92050"]))
    if "tcm8" in data:
        apply_8tcm_pack(cfg, bool(data["tcm8"]))
    if "account_risk" in data:
        raw = str(data.get("account_risk") or "OFF").upper().strip()
        cfg.ACCOUNT_RISK_PROFILE = raw if raw in _RISK_PROFILES else "OFF"
    if "breakout_413_mode" in data:
        raw = str(data.get("breakout_413_mode") or "BREAKOUT").upper().strip()
        cfg.BREAKOUT_413_MODE = "PULLBACK" if raw.startswith("P") else "BREAKOUT"
    if "mfe_keep_pct" in data:
        try:
            _set_mfe_keep_pct(cfg, float(data["mfe_keep_pct"]))
        except (TypeError, ValueError):
            pass
    for key, (attr, lo, hi, as_int) in _NUM_KEYS.items():
        if key in {"mfe_keep_pct"} or key not in data:
            continue
        try:
            val = float(data[key])
        except (TypeError, ValueError):
            continue
        val = max(lo, min(hi, val))
        if as_int:
            cap = max(1, int(getattr(cfg, "MAX_CONTRACTS", 50) or 50))
            setattr(cfg, attr, max(1, min(cap, int(round(val)))))
        else:
            setattr(cfg, attr, round(val, 4))
    if "daily_goal" in data:
        goal = float(getattr(cfg, "DAILY_GOAL_DOLLARS", 0) or 0)
        cfg.ENABLE_DAILY_GOAL = goal > 0
    return snapshot(cfg)
