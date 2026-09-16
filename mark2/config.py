"""Centralized Recon Sniper configuration. Do not scatter experimental thresholds."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .types import RunMode, TargetMode, TrailMode

_CLOUD_MARKERS = ("onedrive", "dropbox", "google drive")


def _cloud_synced(path: Path) -> bool:
    return any(
        any(marker in part.lower() for marker in _CLOUD_MARKERS) for part in Path(path).parts
    )


def settings_app_name() -> str:
    """LocalAppData folder. Tiante launch sets MARK2_APP_NAME so she never shares Recon."""
    env = (os.environ.get("MARK2_APP_NAME") or os.environ.get("RECON_APP_NAME") or "").strip()
    if env:
        return env
    product = (os.environ.get("MARK2_PRODUCT") or "").strip().upper()
    if product == "TIANTE":
        return "TianteSniper"
    return "ReconSniper"


def local_app_settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.getcwd()
    return Path(base) / settings_app_name() / "mark2_settings.json"


def _settings_write_path(path: Path) -> Path:
    return local_app_settings_path() if _cloud_synced(path) else Path(path)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        bundled = meipass / "mark2"
        return bundled if bundled.is_dir() else meipass
    return Path(__file__).resolve().parent


def _writable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DEFAULTS_PATH = _bundle_dir() / "mark2_defaults.json"
SETTINGS_PATH = _writable_dir() / "mark2_settings.json"


@dataclass
class ConfidenceWeights:
    trend_alignment: float = 0.18
    trend_strength: float = 0.08
    momentum: float = 0.14
    impulse: float = 0.12
    relative_volume: float = 0.08
    volume_acceleration: float = 0.08
    velocity: float = 0.10
    acceleration: float = 0.08
    breakout_quality: float = 0.06
    structure: float = 0.04
    volatility_state: float = 0.02
    vwap_relationship: float = 0.02

    def normalized(self) -> dict[str, float]:
        raw = asdict(self)
        total = sum(max(0.0, float(v)) for v in raw.values()) or 1.0
        return {k: max(0.0, float(v)) / total for k, v in raw.items()}


@dataclass
class EventToggles:
    momentum_expansion: bool = True
    volume_expansion: bool = True
    breakout: bool = True
    pullback_continuation: bool = True
    volatility_expansion: bool = True
    impulse: bool = True


@dataclass
class Mark2Config:
    MARK2_ENABLED: bool = True
    MODE: str = RunMode.LIVE.value

    LONG_CONFIDENCE_THRESHOLD: float = 58.0
    SHORT_CONFIDENCE_THRESHOLD: float = 58.0
    MIN_CONFIDENCE_VELOCITY: float = 0.35
    MOMENTUM_BUILD_TICKS: int = 3
    REQUIRE_CANDLE_ALIGNMENT: bool = True
    CANDLE_ALIGN_LOOKBACK: int = 3
    CANDLE_ALIGN_MIN_BARS: int = 1
    CANDLE_RELAX_IN_CHOPPY: bool = True
    CANDLE_MIN_FORMING_BODY_RATIO: float = 0.2
    REQUIRE_TICK_VELOCITY: bool = True
    MIN_TICK_VELOCITY: float = 0.08
    LONG_OPPORTUNITY_THRESHOLD: float = 52.0
    SHORT_OPPORTUNITY_THRESHOLD: float = 52.0
    MAX_EXTENSION_RISK: float = 72.0
    EVENT_RESET_THRESHOLD: float = 42.0
    EVENT_END_STREAK: int = 4
    REQUIRE_TRENDING: bool = True
    REQUIRE_STRUCTURE_ALIGNMENT: bool = True
    ENTRY_STRICTNESS: float = 45.0
    ENTRY_TUNING_CUSTOM: bool = False
    MIN_RELATIVE_VOLUME: float = 0.45
    MIN_RELATIVE_VOLUME_TREND: float = 0.35
    MIN_RELATIVE_VOLUME_HIGH_VOL: float = 0.32
    VOLUME_VEL_BYPASS: float = 0.25
    BIAS_STRONG_TICK_VEL: float = 0.25
    BIAS_ALLOW_ZERO_BARS: bool = True
    CHOP_CANDLE_MIN_BARS: int = 0

    VOLATILITY_TRAIL_MULTIPLIER: float = 1.6
    RUNNER_THRESHOLD: float = 70.0
    SCRATCH_THRESHOLD: float = 28.0
    SCRATCH_MAX_SECONDS: float = 0.0
    ENABLE_MOMENTUM_EXIT: bool = False
    MOMENTUM_EXIT_VEL: float = -0.12
    MOMENTUM_EXIT_CONF_VEL: float = -0.15
    MOMENTUM_EXIT_OPP_LEAD: float = 10.0
    MOMENTUM_EXIT_STREAK: int = 2
    MOMENTUM_EXIT_HEALTH_DROP: float = 22.0
    ENABLE_CHOP_SCALP: bool = False
    ENABLE_CHOPPY_BIAS: bool = False
    ENABLE_BOOK_PATTERNS: bool = False
    ENABLE_EXHAUSTION_FILTER: bool = False
    ENABLE_EMA_STRATEGY: bool = True
    # False = EMA is the only auto/manual entry path (product). Tests leave True.
    ALLOW_LEGACY_ENTRIES: bool = False
    EMA_FAST: int = 9
    EMA_MID: int = 20
    EMA_SLOW: int = 50
    EMA_INTERSECT_POINTS: float = 30.0
    EMA_INTERSECT_ATR: float = 2.0
    EMA_THROUGH_SLACK: float = 0.25
    EMA_INTERSECT_SHORT: bool = True
    # Intersection setup: 20/50 must already be spread before the 9/20 cross.
    # Score is |EMA20-EMA50| / ATR. 0.20 is the starting floor so replay can
    # compare runner rates; raise toward 0.60 if the tape shows it.
    EMA_REQUIRE_SEP: bool = True
    EMA_MIN_SEP_ATR: float = 0.20
    EMA_MIN_SEP_POINTS: float = 3.0
    EMA_SEP_LOOKBACK: int = 8
    EMA_SEP_MIN_BARS: int = 3
    EMA_SETUP_MAX_BARS: int = 16
    # EMA 9/20 playback refinements. Blue (EMA_SLOW) stays plot/log only.
    FAST_EMA: int = 9
    SLOW_EMA: int = 20
    REFERENCE_EMA: int = 50
    MAX_ENTRY_EXTENSION_ATR: float = 0.60
    EMA_ALLOW_LONG: bool = True
    EMA_ALLOW_SHORT: bool = False  # Longs only. Shorts stay armed in sniper logic, not taken.
    # Already-stacked rising leftover longs. Default ON (desktop Recon).
    EMA_LEFTOVER_LONG: bool = True
    # One leftover / sniper fill per stack until red loses white+blue or punches again.
    EMA_ONE_PER_STACK: bool = True
    # Post-trigger MNQ long quality. False = identical to pre-filter sniper/leftover fires.
    ENABLE_EMA_QUALITY_FILTER: bool = True
    # Red-white daylight. 0.03 ATR (~0.4-0.9 MNQ pts at typical 12-30 ATR) cuts a
    # touch/wiggle without waiting for a late fan. 03:25 sniper still clears this.
    MIN_9_20_GAP_ATR: float = 0.03
    # White-blue gap. Default 0: sniper fires while 20/50 are still close/bearish.
    # Raise toward 0.08 only if leftover mash still leaks.
    MIN_20_50_GAP_ATR: float = 0.0
    # 9/20/50 cluster width. 0.10 ATR blocks a mashed trio without requiring a
    # full 9>20>50 expansion (that would enter after the move is gone).
    MIN_TOTAL_EMA_SPREAD_ATR: float = 0.10
    # True = 9-20 gap must be opening (not 20/50). One tiny contraction is tolerated.
    REQUIRE_EXPANDING_SPREAD: bool = True
    EMA_SPREAD_LOOKBACK_BARS: int = 3
    # Ignore a 9-20 dip smaller than this (ATR). One-bar noise must not reject.
    EMA_SPREAD_EXPAND_TOLERANCE_ATR: float = 0.02
    # EMA9 slope in ATR/bar. 0.04 is more than a tick of noise, less than a late chase.
    MIN_EMA9_SLOPE: float = 0.04
    # EMA20 slope in ATR/bar. -0.03 allows a one-tick white pause on the 9/50
    # confirm bar; a white that is actually rolling over fails.
    MIN_EMA20_SLOPE: float = -0.03
    # Floor on EMA50 slope (ATR/bar). Sniper often prints while blue still drifts
    # down from the prior trend; -0.08 allows that, a waterfall fails.
    MAX_NEGATIVE_EMA50_SLOPE: float = -0.08
    # Knot: cluster/ATR below this is tangled. 0.15 cuts 1-pt mash at ATR 12
    # while a real 03:25 through-both (~0.16 at inflated test ATR 30) still passes.
    EMA_COMPRESSION_ATR: float = 0.15
    # AI momentum exit. False = existing tip-trail / dollar-lock / MFE path exactly.
    ENABLE_AI_EXIT_ENGINE: bool = False
    ENABLE_MOMENTUM_SCORE: bool = True
    ENABLE_MFE_RUNNER: bool = True
    ENABLE_STRUCTURE_OVERRIDE: bool = True
    ENABLE_MOMENTUM_REACCELERATION: bool = True
    # 413 LONG — MNQ 1-minute developing bullish breakout (independent of sniper).
    ENABLE_413_BREAKOUT: bool = False
    BREAKOUT_413_MODE: str = "BREAKOUT"  # BREAKOUT | PULLBACK
    BREAKOUT_413_MAX_STOP_PTS: float = 40.0
    BREAKOUT_413_TARGET_R: float = 2.0
    BREAKOUT_413_MAX_PER_SEQUENCE: int = 2
    BREAKOUT_413_DAILY_LOSS_USD: float = 0.0
    BREAKOUT_413_START_ET: str = ""
    BREAKOUT_413_END_ET: str = ""
    BREAKOUT_413_EMA50_TOL_ATR: float = 0.02
    # Momentum barriers (PDH/PDL, swings, consolidation). Off = old Recon.
    ENABLE_MOMENTUM_BARRIERS: bool = False
    # 8TCM — independent of EMA9/20/50 sniper, 413, and scout. Baseline playback numbers.
    ENABLE_8TCM: bool = False
    ENABLE_8TCM_LONGS: bool = True
    ENABLE_8TCM_SHORTS: bool = False
    ENABLE_8TCM_CLASSIC_TARGET: bool = True
    ENABLE_8TCM_AI_EXIT: bool = False
    ENABLE_8TCM_RUNNER: bool = True
    ENABLE_8TCM_EARLY_ENTRY: bool = False
    TCM8_ENTRY_MODE: str = "CLOSED_BAR"
    TCM8_SWING_STRENGTH: int = 2
    TCM8_EMA_PERIOD: int = 8
    TCM8_TREND_SLOPE_LOOKBACK: int = 5
    TCM8_MIN_TREND_SLOPE_ATR: float = 0.05
    TCM8_PULLBACK_MAX_DISTANCE_ATR: float = 0.15
    TCM8_EMA_TOUCH_TOLERANCE_ATR: float = 0.10
    TCM8_MAX_EMA_PENETRATION_ATR: float = 0.20
    TCM8_MAX_ENTRY_DISTANCE_FROM_EMA_ATR: float = 0.30
    TCM8_STRONG_WICK_BODY_RATIO: float = 1.50
    TCM8_PIN_BAR_WICK_BODY_RATIO: float = 2.00
    TCM8_MIN_REJECTION_BODY_ATR: float = 0.15
    TCM8_BARRIER_PROXIMITY_BLOCK_ATR: float = 0.25
    TCM8_CONSOLIDATION_LOOKBACK: int = 10
    TCM8_CONSOLIDATION_MAX_RANGE_ATR: float = 1.00
    TCM8_STOP_BUFFER_ATR: float = 0.10
    TCM8_MINIMUM_TARGET_R: float = 0.75
    TCM8_PREFERRED_TARGET_R: float = 1.50
    # Bank / arm this many points in front of the raw key level. MNQ often
    # stalls 1 tick short of the exact swing and then gives the trade back.
    TCM8_TARGET_FRONT_RUN_POINTS: float = 1.5
    # Total open $ to arm purple before the green key level. Not leftover $15 —
    # that is ~2 pts on 4 MNQ and shakes a continuation. $50 ≈ 6 pts on 4-lot.
    TCM8_TRAIL_ARM_USD: float = 50.0
    # Leftover purple distance: 5.5 points behind the live candle tip.
    TCM8_TRAIL_POINTS: float = 5.5
    # When on with the master toggle: pause EMA/413/scout entries; AI exit still runs.
    ENABLE_BARRIER_STRATEGY_ONLY: bool = True
    ENABLE_BARRIER_ENTRY_FILTER: bool = True
    ENABLE_BARRIER_REJECTION_EXIT: bool = True
    ENABLE_CLASSIC_KEY_LEVEL_TARGET: bool = False
    ENABLE_HARD_BARRIER_TARGET: bool = False
    # MNQ 1m: 8 pts is $16/contract; 0.35 ATR rejects the 4-pt PDH example (~0.15 ATR).
    MIN_ROOM_TO_BARRIER_POINTS: float = 8.0
    MIN_ROOM_TO_BARRIER_ATR: float = 0.35
    BARRIER_APPROACH_ATR: float = 0.40
    BARRIER_TEST_TOLERANCE_ATR: float = 0.12
    BARRIER_CLUSTER_TOLERANCE_ATR: float = 0.15
    BARRIER_APPROACH_TRAIL_ATR: float = 0.70
    BARRIER_TEST_TRAIL_ATR: float = 0.40
    SWING_LEFT_BARS: int = 3
    SWING_RIGHT_BARS: int = 3
    CONSOLIDATION_LOOKBACK: int = 12
    CONSOLIDATION_MAX_RANGE_ATR: float = 0.85
    MIN_CONSOLIDATION_BARS: int = 6
    PROTECT_AT_R: float = 1.0
    PROTECT_ATR_CUSHION: float = 0.25
    RUNNER_START_R: float = 2.0
    RUNNER_MFE_RETAIN: float = 0.70
    SPREAD_LOOKBACK_BARS: int = 4
    EARLY_FAILURE_MIN_EVIDENCE: int = 3
    MOMENTUM_WATCH_SCORE: int = 3
    MOMENTUM_DYING_SCORE: int = 5
    MOMENTUM_EXIT_SCORE: int = 7
    MOM_W_EMA9_SLOPE_NEG: int = 1
    MOM_W_SPREAD_CONTRACT: int = 1
    MOM_W_SPREAD_COLLAPSE: int = 2
    MOM_W_CLOSE_BELOW_9: int = 1
    MOM_W_CLOSE_BELOW_20: int = 2
    MOM_W_BEARISH_CROSS: int = 3
    MOM_W_LOWER_HIGH: int = 1
    MOM_W_LOWER_LOW: int = 2
    MOM_W_COMPRESSION: int = 2
    MOM_W_BEARISH_BAR: int = 2
    # Second eyes on 9/20/50. Can hold a missed fire and take shorts the sniper skips.
    ENABLE_AI_SCOUT: bool = True
    AI_SCOUT_LONG: bool = True
    AI_SCOUT_SHORT: bool = False
    AI_SCOUT_OVERRIDE_MISSED: bool = True
    AI_SCOUT_PAPER_FALLBACK: bool = False
    AI_SCOUT_MAX_EXT_ATR: float = 2.8
    # Wall-clock pause after a flatten so the next hop is not the same trade.
    EMA_REENTRY_COOLDOWN_SEC: float = 5.0
    # Intersection only. Leftover stacks, chop whites, and fade shorts stay off.
    EMA_BULL_FADE_SHORT: bool = False
    EMA_LONG_SNIPER: bool = True
    EMA_LONG_REQUIRES_BEARISH: bool = False
    EMA_SHORT_SNIPER: bool = True
    EMA_SHORT_REQUIRES_BULLISH: bool = False
    EMA_RSI_LONG: bool = False
    RSI_LONG_LEVEL: float = 65.0
    RSI_LONG_TRAIL_POINTS: float = 3.0
    BULL_LONG_TARGET_POINTS: float = 5.5
    BULL_TRAIL_ARM_POINTS: float = 3.0
    BULL_TRAIL_POINTS: float = 3.0
    BULL_USE_SNIPER_DOLLAR_LOCK: bool = False
    # Choppy: red/white cross only. $150 take-profit, else hold to white down-cross.
    EMA_CHOP_LONG: bool = False
    CHOP_TARGET_USD: float = 150.0
    CHOP_RSI_FADE: float = 5.0
    # Unused. Old 4.5 chop yank stays off.
    CHOPPY_TARGET_POINTS: float = 4.5
    CHOPPY_TRAIL_POINTS: float = 4.5
    # Kept for logs / HUD. Not an entry trigger.
    EMA_BLUE_APPROACH_ATR: float = 0.35
    ENABLE_PULLBACK_ENTRY: bool = True
    PULLBACK_ENTRY_ON_BAR_CLOSE: bool = True
    MAX_PULLBACK_WAIT_BARS: int = 10
    CATASTROPHIC_STOP_ATR: float = 1.50
    INITIAL_STOP_ATR: float = 1.50
    # 10-5 exit: 10-pt hard stop, $15 arm, 5.5-pt tip trail.
    EMA_CLASSIC_EXIT: bool = False
    EMA_HARD_STOP_POINTS: float = 10.0
    # ATR catastrophic stop never tighter than this. 10 pts was clipping every trade.
    EMA_MIN_STOP_POINTS: float = 20.0
    CONFIRMED_TREND_TRIGGER_ATR: float = 1.0
    CONFIRMED_STOP_ATR_FROM_ENTRY: float = 0.25
    # Runner: keep 70% of MFE. Floor only ratchets up. Same as Willie Recon Sniper GitHub.
    MFE_GIVEBACK_FRAC: float = 0.30
    MFE_FADE_LOCK: bool = False
    MFE_LOCK_ARM_USD: float = 100.0
    MFE_FADE_GIVE_FRAC: float = 0.15
    MFE_FADE_STALL_BARS: int = 2
    MFE_FADE_RSI_DROP: float = 5.0
    # Exit when EMA cluster loses this fraction of its peak spread.
    SPREAD_COMPRESS_FRAC: float = 0.35
    OPPOSITE_CROSS_REQUIRES_CONFIRM: bool = True
    # Off until we want red/white flip to flatten.
    EMA_OPPOSITE_CROSS_EXIT: bool = False
    ENABLE_RUNNER_TRAIL: bool = True
    RUNNER_TRIGGER_ATR: float = 2.0
    RUNNER_TRAIL_ATR: float = 1.25
    RUNNER_STRUCTURE_EXIT: bool = True
    DYNAMIC_EMA_TRAIL: bool = False
    RUNNER_HIGH_VOL_TRAIL: bool = False
    DOLLAR_LOCK_1_TRIGGER: float = 100.0
    DOLLAR_LOCK_1_PROFIT: float = 80.0
    DOLLAR_LOCK_2_TRIGGER: float = 150.0
    DOLLAR_LOCK_2_PROFIT: float = 97.5
    DOLLAR_LOCK_3_TRIGGER: float = 250.0
    DOLLAR_LOCK_3_PERCENT: float = 0.80
    TRAIL_PROFIT_KEEP: float = 0.80
    RUNNER_KEEP_HIGH_USD: float = 550.0
    RUNNER_KEEP_HIGH_PEAK_USD: float = 600.0
    TIP_TRAIL_ARM_USD: float = 100.0
    TIP_TRAIL_STEP_USD: float = 25.0
    TIP_TRAIL_START_POINTS: float = 7.5
    TIP_TRAIL_HIGH_POINTS: float = 25.0
    TIP_TRAIL_STALL_POINTS: float = 3.0
    TIP_TRAIL_STALL_BARS: int = 4
    # Recon Sniper HUD grow_mode toggle. Off = $100 tip trail / 70% MFE runner. On = $50 stall bank.
    ENABLE_GROW_MODE: bool = False
    STARTING_EQUITY_USD: float = 250.0
    GROW_UNTIL_USD: float = 600.0
    GROW_GRAB_USD: float = 50.0
    GROW_KEEP_FRAC: float = 0.80
    GROW_STALL_BARS: int = 3
    GROW_STALL_KEEP_FRAC: float = 0.75
    # After a peak: 3 reds (long) / 3 greens (short) + real giveback → flatten.
    ADVERSE_STACK_BARS: int = 3
    ADVERSE_STACK_MIN_USD: float = 20.0
    ADVERSE_STACK_GIVE_ATR: float = 0.25
    TRAIL_PROFIT_KEEP_EARLY: float = 0.0
    TRAIL_KEEP_ARM_USD: float = 100.0
    TRAIL_KEEP_TIGHT_USD: float = 250.0
    TRAIL_KEEP_FLOOR_USD: float = 20.0
    RUNNER_TRAIL_MIN_ATR: float = 1.25
    RUNNER_TRAIL_WIDE_SPREAD_ATR: float = 0.35
    RUNNER_TRAIL_TIGHT_SPREAD_ATR: float = 0.08
    RUNNER_TRAIL_HIGH_VOL_ATR: float = 1.25
    MIN_BARS_SINCE_LAST_CROSS: int = 0
    EXHAUSTION_BLOCK_SCORE: float = 72.0
    RSI_PERIOD: int = 14
    RSI_OB_LEVEL: float = 75.0
    RSI_OS_LEVEL: float = 25.0
    BB_PERIOD: int = 20
    BB_STD: float = 2.0
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9
    MONSTER_EXTENSION: float = 70.0
    MONSTER_MOMENTUM: float = 35.0
    # Deep hold: no real stop until $300 open profit (or market flip → tip trail).
    ENABLE_DEEP_HOLD: bool = False
    DEEP_HOLD_ARM_USD: float = 300.0
    DEEP_HOLD_STOP_POINTS: float = 180.0
    DEEP_HOLD_FLIP_TRAIL: float = 5.5
    # After +$15: tip trail on. Stall/chop → aggressively tighten.
    EARLY_TRAIL_ARM_USD: float = 15.0
    STALL_TRAIL_ROOM: float = 0.75
    STALL_SEC: float = 6.0
    STALL_BAR_ATR_FRAC: float = 0.32
    STALL_VEL_FRAC: float = 0.12
    CHOP_SCALP_CONFIDENCE: float = 52.0
    CHOP_SCALP_OPPORTUNITY: float = 55.0
    CHOP_SCALP_MIN_TICK_VEL: float = 0.20
    CHOP_SCALP_MIN_CONF_VEL: float = 0.18
    CHOP_SCALP_DIRECTION_GAP: float = 10.0
    CHOP_SCALP_BUILD_TICKS: int = 2
    CHOP_SCALP_MAX_EXTENSION: float = 55.0
    CHOP_SCALP_BANK_DOLLARS: float = 15.0
    CHOP_SCALP_STOP_POINTS: float = 10.0
    CHOP_SCALP_TRAIL_POINTS: float = 3.0
    APPROACH_TRAIL_POINTS: float = 5.5
    TRAIL_ARM_POINTS: float = 6.0
    TRAIL_TIGHTEN_AT_TARGET: float = 0.35
    TRAIL_TIGHTEN_BUFFER: float = 1.0
    CHOP_SCALP_COOLDOWN_SEC: float = 1.5
    CHOP_SCALP_EXIT_HEALTH: float = 35.0
    CHOP_SCALP_EXIT_VEL: float = -0.08
    CHOP_SCALP_EXIT_CONF_VEL: float = -0.1
    CHOP_SCALP_EXIT_OPP_LEAD: float = 8.0
    CHOP_SCALP_EXIT_HEALTH_DROP: float = 15.0
    CHOP_SCALP_EXIT_STREAK: int = 1
    ENABLE_CHAOTIC_BANK: bool = True
    CHAOTIC_BANK_CONFIDENCE: float = 55.0
    CHAOTIC_BANK_OPPORTUNITY: float = 54.0
    CHAOTIC_BANK_MIN_TICK_VEL: float = 0.28
    CHAOTIC_BANK_MIN_CONF_VEL: float = 0.22
    CHAOTIC_BANK_DIRECTION_GAP: float = 8.0
    CHAOTIC_BANK_BUILD_TICKS: int = 2
    CHAOTIC_BANK_MAX_EXTENSION: float = 65.0
    CHAOTIC_BANK_BANK_DOLLARS: float = 25.0
    CHAOTIC_BANK_STOP_POINTS: float = 14.0
    CHAOTIC_BANK_APPROACH_TRAIL: float = 3.0
    CHAOTIC_BANK_RUNNER_TRAIL: float = 3.0
    CHAOTIC_BANK_TRAIL_ARM: float = 1.0
    CHAOTIC_BANK_GREEN_LOCK: float = 1.0
    CHAOTIC_BANK_COOLDOWN_SEC: float = 2.0
    CHAOTIC_CANDLE_MIN_BARS: int = 0
    ENABLE_EXPERIMENTAL_PROFILE: bool = False
    EXPERIMENTAL_DIRECTION_GAP: float = 8.0
    EXPERIMENTAL_REQUIRE_QUALITY: bool = True
    EXPERIMENTAL_REQUIRE_SIDE_AGREEMENT: bool = True
    ENABLE_BIAS_ENTRY_ADJUST: bool = True
    BIAS_SHORT_CONF_DELTA: float = 4.0
    BIAS_SHORT_OPP_DELTA: float = 2.0
    BIAS_SHORT_CONF_VEL_DELTA: float = 0.12
    BIAS_LONG_CONF_DELTA: float = 4.0
    BIAS_LONG_OPP_DELTA: float = 2.0
    BIAS_LONG_CONF_VEL_DELTA: float = 0.12
    BIAS_RELAX_CANDLES: bool = True
    BIAS_MIN_TICK_VEL: float = 0.05
    BIAS_BUILD_TICKS: int = 2
    BIAS_DIRECTION_GAP: float = 6.0
    BIAS_HIGH_VOL_CONF_DELTA: float = 2.0
    BIAS_HIGH_VOL_OPP_DELTA: float = 1.0
    BIAS_HIGH_VOL_TICK_VEL: float = 0.02
    BIAS_HIGH_VOL_MIN_RVOL: float = 0.18
    BIAS_HIGH_VOL_CONF_FLOOR: float = 46.0
    BIAS_HIGH_VOL_RELAX_FORMING: bool = True
    BIAS_HIGH_VOL_RELAX_STRUCTURE: bool = True
    ENTRY_GRACE_SECONDS: float = 0.0
    ABORT_REQUIRES_GREEN: bool = True
    ENABLE_GREEN_FLOOR: bool = True
    THESIS_ABORT_COOLDOWN_SEC: float = 10.0
    DEFAULT_EXIT_COOLDOWN_SEC: float = 3.0
    TARGET_MODE: str = TargetMode.CHECKPOINT.value
    TRAIL_MODE: str = TrailMode.ATR_ADAPTIVE.value
    INITIAL_TARGET_ATR_MULT: float = 1.1
    BANK_DOLLARS_PER_CONTRACT: float = 25.0
    # Total open-profit $ to arm tip trail (NOT per-contract). 3 MNQ @ $15 ≈ 2.5 pts.
    TRAIL_ARM_USD: float = 15.0
    RUNNER_TRAIL_POINTS: float = 5.5
    CONTRACTS: int = 1
    INITIAL_STOP_POINTS: float = 20.0

    VELOCITY_WINDOW_SEC: float = 2.0
    ACCEL_WINDOW_SEC: float = 1.0
    CONFIDENCE_SMOOTH_ALPHA: float = 0.35
    CONFIDENCE_DERIV_WINDOW: int = 6
    OPPORTUNITY_BASELINE_BARS: int = 20
    TICK_BUFFER: int = 80

    CONTEXT_REFRESH_SEC: float = 5.0
    ATR_PERIOD: int = 14
    EMA_PERIOD: int = 20
    VWAP_LOOKBACK: int = 80
    VOLUME_LOOKBACK: int = 20

    MOMENTUM_Z: float = 1.4
    VOLUME_Z: float = 1.3
    VELOCITY_Z: float = 1.4
    IMPULSE_MIN: float = 55.0

    MAX_CONTRACTS: int = 50
    MAX_LOSS_DOLLARS: float = 50000.0
    # Account-level risk (independent of Recon entries / runner hold).
    # SMALL_250 | STANDARD | OFF. Tune the dollar caps below; do not shrink stops to fit.
    ACCOUNT_RISK_PROFILE: str = "OFF"
    ACCOUNT_MAX_CONTRACTS: int = 1
    ACCOUNT_MAX_RISK_PER_TRADE_USD: float = 50.0
    ACCOUNT_MAX_DAILY_LOSS_USD: float = 75.0
    ACCOUNT_MAX_CONSECUTIVE_LOSSES: int = 3
    ACCOUNT_EQUITY_FLOOR_USD: float = 100.0
    ACCOUNT_STALE_DATA_SEC: float = 8.0
    ACCOUNT_KILL_SWITCH: bool = True
    ACCOUNT_DAILY_LOCKOUT: bool = True
    ENABLE_DAILY_GOAL: bool = True
    DAILY_GOAL_DOLLARS: float = 350.0
    # Hunt green-line / trail arm — total open $ (same idea as TRAIL_ARM_USD).
    GOAL_HUNT_BANK_DOLLARS: float = 15.0
    GOAL_NEAR_DOLLARS: float = 30.0
    GOAL_NEAR_BANK_DOLLARS: float = 10.0
    GOAL_WINDOW_HOURS: float = 2.0
    GOAL_PRESSURE_ENABLED: bool = True
    GOAL_HUNT_OPEN_GATES: bool = True
    GOAL_PRESSURE_HUNT_FLOOR: float = 0.0
    GOAL_PRESSURE_MIN_BANK: float = 15.0
    GOAL_PRESSURE_CONF_CUT: float = 6.0
    GOAL_PRESSURE_OPP_CUT: float = 5.0
    GOAL_PRESSURE_VEL_CUT: float = 0.12
    GOAL_PRESSURE_BUILD_CUT: int = 1
    GOAL_PRESSURE_GAP_CUT: float = 2.0
    GOAL_PRESSURE_CHOP_AT: float = 0.65
    GOAL_PRESSURE_CANDLE_AT: float = 0.7
    GOAL_PRESSURE_COOLDOWN_SEC: float = 2.5
    GOAL_PRESSURE_CONF_FLOOR: float = 48.0
    GOAL_PRESSURE_OPP_FLOOR: float = 45.0
    GOAL_PRESSURE_VEL_FLOOR: float = 0.08
    POINT_VALUE: float = 2.0
    TICK_SIZE: float = 0.25
    BRIDGE_PORT: int = 5564
    LICENSE_SERVER_URL: str = ""
    PRODUCT_NAME: str = "RECON SNIPER"
    PRODUCT_ENGINE: str = "ReconSniper"
    KICKER_LONG: str = "RECON LONG"
    KICKER_SHORT: str = "RECON SHORT"
    BRIDGE_NAME: str = "ReconSniperBridge"
    # Copy-out to follower dongles on THIS PC. Default OFF — Willie is never a leader.
    IMPULSE_PRO_LEADER: bool = False
    IMPULSE_PRO_URL: str = ""
    IMPULSE_PRO_TOKEN: str = ""
    IMPULSE_PRO_SYMBOL: str = ""

    weights: ConfidenceWeights = field(default_factory=ConfidenceWeights)
    events: EventToggles = field(default_factory=EventToggles)

    def contracts(self) -> int:
        cap = max(1, int(self.MAX_CONTRACTS))
        try:
            n = int(self.CONTRACTS)
        except (TypeError, ValueError):
            n = 1
        return max(1, min(cap, n))

    def mode(self) -> RunMode:
        try:
            return RunMode(str(self.MODE or "LIVE"))
        except ValueError:
            return RunMode.LIVE

    def target_mode(self) -> TargetMode:
        try:
            return TargetMode(str(self.TARGET_MODE or "CHECKPOINT"))
        except ValueError:
            return TargetMode.CHECKPOINT

    def trail_mode(self) -> TrailMode:
        try:
            return TrailMode(str(self.TRAIL_MODE or "ATR_ADAPTIVE"))
        except ValueError:
            return TrailMode.ATR_ADAPTIVE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _apply_json_dict(cfg: Mark2Config, raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    weights = data.pop("weights", None) or {}
    events = data.pop("events", None) or {}
    for k, v in data.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    for k, v in weights.items():
        if hasattr(cfg.weights, k):
            setattr(cfg.weights, k, float(v))
    for k, v in events.items():
        if hasattr(cfg.events, k):
            setattr(cfg.events, k, bool(v))
    return raw


def _apply_json_file(cfg: Mark2Config, path: Path) -> dict[str, Any]:
    return _apply_json_dict(cfg, _read_json_file(path))


def _settings_read_candidates(path: Path) -> list[Path]:
    primary = Path(path)
    if _cloud_synced(primary):
        return [local_app_settings_path(), primary]
    return [primary]


def load_config(path: Path | None = None) -> Mark2Config:
    cfg = Mark2Config()
    _apply_json_file(cfg, DEFAULTS_PATH)
    settings = Path(path) if path is not None else SETTINGS_PATH
    user_raw: dict[str, Any] = {}
    for candidate in _settings_read_candidates(settings):
        raw = _read_json_file(candidate)
        if raw:
            user_raw = raw
            _apply_json_dict(cfg, raw)
            break
    if bool(getattr(cfg, "ENABLE_EXPERIMENTAL_PROFILE", False)):
        from .experimental import EXPERIMENTAL_PROFILE, apply_experimental_profile

        apply_experimental_profile(cfg)
        # Saved settings for EXP gate keys win over baked Phase 1 defaults.
        for key in EXPERIMENTAL_PROFILE:
            if key in user_raw and hasattr(cfg, key):
                setattr(cfg, key, user_raw[key])
    from .product import apply_product

    apply_product(cfg)
    if bool(getattr(cfg, "ENABLE_EMA_STRATEGY", False)):
        # Empty sniper flags = 9/20/50 never fires. Keep the original method armed.
        if not (
            bool(getattr(cfg, "EMA_LONG_SNIPER", False))
            or bool(getattr(cfg, "EMA_SHORT_SNIPER", False))
            or bool(getattr(cfg, "EMA_LEFTOVER_LONG", False))
        ):
            cfg.EMA_LONG_SNIPER = True
            cfg.EMA_SHORT_SNIPER = True
            cfg.EMA_LEFTOVER_LONG = True
    return cfg


def save_config(cfg: Mark2Config, path: Path | None = None) -> None:
    requested = Path(path) if path is not None else SETTINGS_PATH
    dest = _settings_write_path(requested)
    text = json.dumps(cfg.to_dict(), indent=2)
    targets = [dest]
    fallback = local_app_settings_path()
    if fallback.resolve() != dest.resolve():
        targets.append(fallback)
    for target in targets:
        try:
            _atomic_write_text(target, text)
            return
        except OSError:
            try:
                time.sleep(0.05)
                _atomic_write_text(target, text)
                return
            except OSError:
                continue
