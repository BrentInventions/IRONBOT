"""Recon Sniper enums, snapshots, and event identity — no Mark 1 types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class RunMode(str, Enum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    PAPER_TRADE = "PAPER_TRADE"
    LIVE = "LIVE"


class EngineState(str, Enum):
    IDLE = "IDLE"
    WATCHING = "WATCHING"
    EVENT_DETECTED = "EVENT_DETECTED"
    MOMENTUM_BUILDING = "MOMENTUM_BUILDING"
    TRADE_ARMED = "TRADE_ARMED"
    EXECUTE = "EXECUTE"
    TRADE_INITIAL = "TRADE_INITIAL"
    TRADE_PROFITABLE = "TRADE_PROFITABLE"
    RUNNER_DETECTED = "RUNNER_DETECTED"
    RUNNER_MANAGEMENT = "RUNNER_MANAGEMENT"
    FAILED_EVENT = "FAILED_EVENT"
    EXIT = "EXIT"
    COOLDOWN = "COOLDOWN"


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class EventType(str, Enum):
    MOMENTUM_EXPANSION = "MOMENTUM_EXPANSION"
    VOLUME_EXPANSION = "VOLUME_EXPANSION"
    BREAKOUT = "BREAKOUT"
    PULLBACK_CONTINUATION = "PULLBACK_CONTINUATION"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"
    IMPULSE = "IMPULSE"
    EMA_CROSS = "EMA_CROSS"
    TCM8 = "8TCM"
    NONE = "NONE"


class TargetMode(str, Enum):
    HARD = "HARD"
    CHECKPOINT = "CHECKPOINT"
    OFF = "OFF"


class TrailMode(str, Enum):
    ATR_ADAPTIVE = "ATR_ADAPTIVE"
    FIXED = "FIXED"


class RejectReason(str, Enum):
    NONE = ""
    REJECT_EXTENSION = "REJECT_EXTENSION"
    REJECT_LOW_VOLUME = "REJECT_LOW_VOLUME"
    REJECT_CONFIDENCE_FADING = "REJECT_CONFIDENCE_FADING"
    REJECT_LOW_OPPORTUNITY = "REJECT_LOW_OPPORTUNITY"
    REJECT_STRUCTURE = "REJECT_STRUCTURE"
    REJECT_RISK = "REJECT_RISK"
    REJECT_DUPLICATE_EVENT = "REJECT_DUPLICATE_EVENT"
    REJECT_LOW_CONFIDENCE = "REJECT_LOW_CONFIDENCE"
    REJECT_LOW_VELOCITY = "REJECT_LOW_VELOCITY"
    REJECT_DIRECTION_CONFLICT = "REJECT_DIRECTION_CONFLICT"
    REJECT_NOT_ARMED = "REJECT_NOT_ARMED"
    REJECT_COOLDOWN = "REJECT_COOLDOWN"
    REJECT_MODE = "REJECT_MODE"
    REJECT_INSUFFICIENT_DATA = "REJECT_INSUFFICIENT_DATA"
    REJECT_REGIME = "REJECT_REGIME"
    REJECT_CANDLE_DIRECTION = "REJECT_CANDLE_DIRECTION"
    REJECT_QUALITY = "REJECT_QUALITY"
    REJECT_SIDE_AGREEMENT = "REJECT_SIDE_AGREEMENT"
    REJECT_BOOK_PATTERN = "REJECT_BOOK_PATTERN"
    REJECT_EXHAUSTION = "REJECT_EXHAUSTION"
    REJECT_EMA = "REJECT_EMA"
    REJECT_LICENSE = "REJECT_LICENSE"
    REJECT_NEAR_MOMENTUM_BARRIER = "REJECT_NEAR_MOMENTUM_BARRIER"
    REJECT_8TCM_HTF_TREND = "REJECT_8TCM_HTF_TREND"
    REJECT_8TCM_RANGE = "REJECT_8TCM_RANGE"
    REJECT_NO_PULLBACK = "REJECT_NO_PULLBACK"
    REJECT_NO_REJECTION = "REJECT_NO_REJECTION"
    REJECT_EMA_STRUCTURE_FAILURE = "REJECT_EMA_STRUCTURE_FAILURE"
    REJECT_8TCM_CHASE = "REJECT_8TCM_CHASE"
    REJECT_INSUFFICIENT_TARGET_R = "REJECT_INSUFFICIENT_TARGET_R"
    REJECT_INVALID_STOP = "REJECT_INVALID_STOP"
    REJECT_BRIDGE_DISCONNECTED = "REJECT_BRIDGE_DISCONNECTED"


@dataclass
class Tick:
    """One market update. Forming-bar fields are as-of this timestamp only."""

    ts: float
    price: float
    volume: float = 0.0
    bar_time: str = ""
    forming_open: float = 0.0
    forming_high: float = 0.0
    forming_low: float = 0.0
    forming_volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0


@dataclass
class EventRecord:
    event_id: int
    event_type: EventType
    direction: Side
    started_ts: float
    started_bar_time: str
    started_price: float = 0.0
    peak_confidence: float = 0.0
    peak_opportunity: float = 0.0
    entry_taken: bool = False
    logged_opportunity: bool = False
    ended: bool = False
    end_ts: float = 0.0
    end_reason: str = ""

    def identity_key(self) -> tuple:
        return (
            self.event_type.value,
            self.direction.value,
            self.started_bar_time or f"{self.started_ts:.0f}",
        )


@dataclass
class ScoreBundle:
    long_confidence: float = 0.0
    short_confidence: float = 0.0
    long_conf_velocity: float = 0.0
    short_conf_velocity: float = 0.0
    long_conf_accel: float = 0.0
    short_conf_accel: float = 0.0
    long_opportunity: float = 0.0
    short_opportunity: float = 0.0
    extension_risk_long: float = 0.0
    extension_risk_short: float = 0.0
    trade_health: float = 0.0
    contributors: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketSnapshot:
    """Everything Recon Sniper may use at timestamp T. No future bar OHLC."""

    ts: float
    price: float
    completed_bars: list[dict]
    forming_bar: Optional[dict]
    atr: float = 0.0
    ema: float = 0.0
    vwap: float = 0.0
    volume: float = 0.0
    relative_volume: float = 0.0
    volume_acceleration: float = 0.0
    velocity: float = 0.0
    acceleration: float = 0.0
    impulse_score: float = 0.0
    trend_bias: str = "NEUTRAL"
    trend_regime: str = "QUIET"
    trend_strength: float = 0.0
    longs_allowed: bool = False
    shorts_allowed: bool = False
    nearest_support: float | None = None
    nearest_resistance: float | None = None
    session: str = ""
    hour_et: int = -1
    structure_state: str = "MIXED"
    volatility_state: str = "stable"
    vwap_distance_atr: float = 0.0
    ema_distance_atr: float = 0.0
    swing_high: float = 0.0
    swing_low: float = 0.0
