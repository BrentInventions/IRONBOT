"""Event-driven Recon Sniper state machine. Candle close is not an entry event."""

from __future__ import annotations

from .bias_entry import BiasEntryGates
from .config import Mark2Config
from .goal_pressure import GoalPressure
from .types import EngineState, EventRecord, RejectReason, RunMode, ScoreBundle, Side


class Mark2StateMachine:
    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg
        self.state = EngineState.IDLE
        self.armed_side = Side.NONE
        self.cooldown_until = 0.0
        self._building_ticks = 0

    def reset(self) -> None:
        self.state = EngineState.IDLE
        self.armed_side = Side.NONE
        self._building_ticks = 0

    def on_ready(self) -> EngineState:
        if self.state == EngineState.IDLE:
            self.state = EngineState.WATCHING
        return self.state

    def evaluate_entry(
        self,
        *,
        ts: float,
        event: EventRecord | None,
        scores: ScoreBundle,
        extension_blocks: bool,
        volume_ok: bool,
        structure_ok: bool,
        trend_ok: bool = True,
        candle_ok: bool = True,
        entry_profile: str = "default",
        bias_gates: BiasEntryGates | None = None,
        goal_pressure: GoalPressure | None = None,
    ) -> tuple[EngineState, RejectReason]:
        if not self.cfg.MARK2_ENABLED:
            return self.state, RejectReason.REJECT_MODE
        if ts < self.cooldown_until:
            self.state = EngineState.COOLDOWN
            return self.state, RejectReason.REJECT_COOLDOWN
        if self.state in (
            EngineState.TRADE_INITIAL,
            EngineState.TRADE_PROFITABLE,
            EngineState.RUNNER_DETECTED,
            EngineState.RUNNER_MANAGEMENT,
        ):
            return self.state, RejectReason.NONE
        if self.state == EngineState.IDLE:
            self.state = EngineState.WATCHING

        if event is None:
            self.state = EngineState.WATCHING
            self._building_ticks = 0
            return self.state, RejectReason.NONE

        if event.entry_taken or event.logged_opportunity:
            return self.state, RejectReason.REJECT_DUPLICATE_EVENT

        side = event.direction
        conf = scores.long_confidence if side == Side.LONG else scores.short_confidence
        vel = scores.long_conf_velocity if side == Side.LONG else scores.short_conf_velocity
        opp = scores.long_opportunity if side == Side.LONG else scores.short_opportunity
        need_c = (
            self.cfg.LONG_CONFIDENCE_THRESHOLD
            if side == Side.LONG
            else self.cfg.SHORT_CONFIDENCE_THRESHOLD
        )
        need_o = (
            self.cfg.LONG_OPPORTUNITY_THRESHOLD
            if side == Side.LONG
            else self.cfg.SHORT_OPPORTUNITY_THRESHOLD
        )
        min_vel = float(self.cfg.MIN_CONFIDENCE_VELOCITY)
        build_ticks = max(1, int(self.cfg.MOMENTUM_BUILD_TICKS))
        if entry_profile == "chop_scalp":
            need_c = float(getattr(self.cfg, "CHOP_SCALP_CONFIDENCE", 52.0))
            need_o = float(getattr(self.cfg, "CHOP_SCALP_OPPORTUNITY", 60.0))
            min_vel = float(getattr(self.cfg, "CHOP_SCALP_MIN_CONF_VEL", 0.18))
            build_ticks = max(1, int(getattr(self.cfg, "CHOP_SCALP_BUILD_TICKS", 2)))
        elif entry_profile == "chaotic_bank":
            need_c = float(getattr(self.cfg, "CHAOTIC_BANK_CONFIDENCE", 55.0))
            need_o = float(getattr(self.cfg, "CHAOTIC_BANK_OPPORTUNITY", 54.0))
            min_vel = float(getattr(self.cfg, "CHAOTIC_BANK_MIN_CONF_VEL", 0.22))
            build_ticks = max(1, int(getattr(self.cfg, "CHAOTIC_BANK_BUILD_TICKS", 2)))
        elif bias_gates is not None and bias_gates.active:
            if bias_gates.conf_threshold is not None:
                need_c = bias_gates.conf_threshold
            if bias_gates.opp_threshold is not None:
                need_o = bias_gates.opp_threshold
            if bias_gates.min_conf_vel is not None:
                min_vel = bias_gates.min_conf_vel
            if bias_gates.build_ticks is not None:
                build_ticks = max(1, int(bias_gates.build_ticks))

        if goal_pressure is not None and goal_pressure.active and goal_pressure.pressure > 0:
            need_c = max(float(goal_pressure.conf_floor), float(need_c) + goal_pressure.conf_delta)
            need_o = max(float(goal_pressure.opp_floor), float(need_o) + goal_pressure.opp_delta)
            # Mild velocity ease — still require positive/near-positive slope.
            eased = float(min_vel) + float(goal_pressure.conf_vel_delta)
            min_vel = max(float(goal_pressure.conf_vel_floor), eased)
            build_ticks = max(1, int(build_ticks) + int(goal_pressure.build_ticks_delta))

        self.state = EngineState.EVENT_DETECTED
        skip_regime = bool(
            goal_pressure is not None and goal_pressure.active and goal_pressure.bypass_regime
        )
        if (
            self.cfg.REQUIRE_TRENDING
            and not trend_ok
            and not skip_regime
            and entry_profile not in (
                "chop_scalp",
                "chaotic_bank",
            )
        ):
            return self.state, RejectReason.REJECT_REGIME
        if not volume_ok:
            return self.state, RejectReason.REJECT_LOW_VOLUME
        if not structure_ok:
            return self.state, RejectReason.REJECT_STRUCTURE
        if extension_blocks:
            return self.state, RejectReason.REJECT_EXTENSION
        if not candle_ok:
            return self.state, RejectReason.REJECT_CANDLE_DIRECTION
        if conf < need_c:
            return self.state, RejectReason.REJECT_LOW_CONFIDENCE
        if vel < min_vel:
            self.state = EngineState.MOMENTUM_BUILDING
            return self.state, RejectReason.REJECT_CONFIDENCE_FADING if vel < 0 else RejectReason.REJECT_LOW_VELOCITY
        if opp < need_o:
            return self.state, RejectReason.REJECT_LOW_OPPORTUNITY
        if scores.long_confidence > 50 and scores.short_confidence > 50:
            if entry_profile == "chop_scalp":
                gap_need = float(getattr(self.cfg, "CHOP_SCALP_DIRECTION_GAP", 10.0))
            elif entry_profile == "chaotic_bank":
                gap_need = float(getattr(self.cfg, "CHAOTIC_BANK_DIRECTION_GAP", 8.0))
            elif bool(getattr(self.cfg, "ENABLE_EXPERIMENTAL_PROFILE", False)):
                gap_need = float(getattr(self.cfg, "EXPERIMENTAL_DIRECTION_GAP", 10.0))
            elif bias_gates is not None and bias_gates.active and bias_gates.direction_gap is not None:
                gap_need = float(bias_gates.direction_gap)
            else:
                gap_need = 8.0
            if goal_pressure is not None and goal_pressure.active:
                gap_need = max(4.0, gap_need + goal_pressure.gap_delta)
            if abs(scores.long_confidence - scores.short_confidence) < gap_need:
                return self.state, RejectReason.REJECT_DIRECTION_CONFLICT

        self._building_ticks += 1
        self.state = EngineState.MOMENTUM_BUILDING
        if self._building_ticks < build_ticks:
            return self.state, RejectReason.NONE
        self.state = EngineState.TRADE_ARMED
        self.armed_side = side
        return self.state, RejectReason.NONE

    def execute(self) -> EngineState:
        self.state = EngineState.EXECUTE
        return self.state

    def enter_management(self) -> EngineState:
        self.state = EngineState.TRADE_INITIAL
        self._building_ticks = 0
        return self.state

    def observe_consume(self) -> EngineState:
        """OBSERVE_ONLY: log the opportunity, do not open a position."""
        self.state = EngineState.WATCHING
        self.armed_side = Side.NONE
        self._building_ticks = 0
        return self.state

    def begin_cooldown(self, ts: float, seconds: float = 3.0) -> EngineState:
        self.cooldown_until = ts + seconds
        self.state = EngineState.COOLDOWN
        self.armed_side = Side.NONE
        self._building_ticks = 0
        return self.state

    def maybe_rearm(self, ts: float) -> EngineState:
        if self.state == EngineState.COOLDOWN and ts >= self.cooldown_until:
            self.state = EngineState.WATCHING
        return self.state
