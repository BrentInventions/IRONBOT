"""Goal clock pressure — hunt opens entry gates so the bot can trade."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.engine import Mark2Engine
from mark2.goal_pressure import compute_goal_pressure, clock_pressure_frac
from mark2.state_machine import Mark2StateMachine
from mark2.types import EventRecord, EventType, MarketSnapshot, RejectReason, ScoreBundle, Side


def test_hunt_opens_gates_immediately():
    cfg = Mark2Config()
    cfg.GOAL_WINDOW_HOURS = 1.0
    cfg.GOAL_HUNT_OPEN_GATES = True
    early = compute_goal_pressure(cfg, started_ts=0.0, now_ts=60.0, session_pnl=0.0)
    late = compute_goal_pressure(cfg, started_ts=0.0, now_ts=3300.0, session_pnl=0.0)
    assert early.active and late.active
    assert early.pressure >= 0.35
    assert late.pressure >= early.pressure
    assert early.bypass_candle is True
    assert early.bypass_volume is True
    assert early.bypass_regime is True
    assert early.force_chop is True
    assert early.bank_dollars == 15.0


def test_open_gates_can_be_disabled():
    cfg = Mark2Config()
    cfg.GOAL_WINDOW_HOURS = 1.0
    cfg.GOAL_HUNT_OPEN_GATES = False
    pressure = compute_goal_pressure(cfg, started_ts=0.0, now_ts=100.0, session_pnl=0.0)
    assert pressure.pressure < 0.25
    assert pressure.force_chop is False
    assert pressure.bypass_candle is False


def test_pressure_mild_gate_ease_late():
    cfg = Mark2Config()
    cfg.GOAL_WINDOW_HOURS = 1.0
    cfg.GOAL_HUNT_OPEN_GATES = False
    cfg.LONG_CONFIDENCE_THRESHOLD = 58.0
    cfg.LONG_OPPORTUNITY_THRESHOLD = 52.0
    cfg.MIN_CONFIDENCE_VELOCITY = 0.35
    cfg.MOMENTUM_BUILD_TICKS = 3
    cfg.REQUIRE_TRENDING = False
    pressure = compute_goal_pressure(cfg, started_ts=0.0, now_ts=3500.0, session_pnl=0.0)
    assert pressure.pressure > 0.7
    sm = Mark2StateMachine(cfg)
    scores = ScoreBundle(
        long_confidence=54.0,
        short_confidence=40.0,
        long_conf_velocity=0.25,
        short_conf_velocity=0.0,
        long_opportunity=50.0,
        short_opportunity=40.0,
    )
    ev = EventRecord(
        event_id=1,
        event_type=EventType.MOMENTUM_EXPANSION,
        direction=Side.LONG,
        started_ts=1.0,
        started_bar_time="b1",
        started_price=20000.0,
    )
    st, rej = RejectReason.NONE, RejectReason.NONE
    for _ in range(3):
        st, rej = sm.evaluate_entry(
            ts=1.0,
            event=ev,
            scores=scores,
            extension_blocks=False,
            volume_ok=True,
            structure_ok=True,
            trend_ok=True,
            candle_ok=True,
            goal_pressure=pressure,
        )
    assert st.value == "TRADE_ARMED"
    assert rej == RejectReason.NONE


def test_engine_pressure_in_snapshot():
    cfg = Mark2Config()
    cfg.GOAL_WINDOW_HOURS = 1.0
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng._goal_started_ts = 100.0
        eng.last_snap = MarketSnapshot(
            ts=100.0 + 3200.0,
            price=20000.0,
            completed_bars=[],
            forming_bar=None,
            atr=4.0,
        )
        g = eng._goal_snapshot()
        assert g["hunting"] is True
        assert g["pressure"] > 50.0
        assert g["huntBank"] == 15.0


def test_no_window_still_hunts_with_open_gates():
    cfg = Mark2Config()
    cfg.GOAL_WINDOW_HOURS = 0.0
    cfg.GOAL_HUNT_OPEN_GATES = True
    assert clock_pressure_frac(cfg, started_ts=0.0, now_ts=9999.0) == 0.0
    p = compute_goal_pressure(cfg, started_ts=0.0, now_ts=9999.0)
    assert p.active is True
    assert p.pressure >= 0.35
    assert p.bypass_candle is True
