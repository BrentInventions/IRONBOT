"""Chaotic quick-bank mode — bias-aligned entries in CHAOTIC regime."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.chaotic_bank import chaotic_entry_ok
from mark2.config import Mark2Config
from mark2.exits import PaperTrade, bank_points, initial_stop, manage_paper, stop_points
from mark2.state_machine import Mark2StateMachine
from mark2.types import EventRecord, EventType, MarketSnapshot, RejectReason, ScoreBundle, Side


def _snap(**kw) -> MarketSnapshot:
    base = dict(
        ts=1.0,
        price=20000.0,
        completed_bars=[],
        forming_bar={"open": 20000.0, "high": 20001.0, "low": 19999.0},
        atr=42.0,
        velocity=-0.35,
        acceleration=0.0,
        relative_volume=1.2,
        impulse_score=60.0,
        trend_bias="BEARISH",
        trend_regime="CHAOTIC",
        structure_state="MIXED",
        longs_allowed=False,
        shorts_allowed=False,
        vwap_distance_atr=0.0,
        volume_acceleration=0.0,
        swing_high=0.0,
        swing_low=0.0,
    )
    base.update(kw)
    return MarketSnapshot(**base)


def _scores(**kw) -> ScoreBundle:
    base = dict(
        long_confidence=40.0,
        short_confidence=58.0,
        long_opportunity=30.0,
        short_opportunity=56.0,
        long_conf_velocity=0.1,
        short_conf_velocity=0.25,
    )
    base.update(kw)
    return ScoreBundle(**base)


def test_chaotic_blocks_counter_trend_long():
    cfg = Mark2Config()
    ok, why = chaotic_entry_ok(_snap(), _scores(), Side.LONG, cfg)
    assert ok is False
    assert "bias" in why


def test_chaotic_allows_bearish_short():
    cfg = Mark2Config()
    ok, why = chaotic_entry_ok(_snap(), _scores(), Side.SHORT, cfg)
    assert ok is True
    assert why == "chaotic_ok"


def test_chaotic_state_machine_bypasses_regime():
    cfg = Mark2Config()
    sm = Mark2StateMachine(cfg)
    ev = EventRecord(
        event_id=1,
        event_type=EventType.VOLUME_EXPANSION,
        direction=Side.SHORT,
        started_ts=1.0,
        started_bar_time="t1",
        peak_confidence=58.0,
    )
    scores = _scores()
    st, reject = sm.evaluate_entry(
        ts=10.0,
        event=ev,
        scores=scores,
        extension_blocks=False,
        volume_ok=True,
        structure_ok=True,
        trend_ok=True,
        candle_ok=True,
        entry_profile="chaotic_bank",
    )
    assert reject == RejectReason.NONE
    assert st.value == "MOMENTUM_BUILDING"


def test_chaotic_exit_profile():
    cfg = Mark2Config()
    entry = 20000.0
    assert stop_points(cfg, chaotic_bank=True) == 14.0
    assert initial_stop(entry, Side.SHORT, 42.0, cfg, chaotic_bank=True) == 20014.0
    trade = PaperTrade(
        side=Side.SHORT,
        entry=entry,
        entry_ts=0.0,
        stop=entry + 14.0,
        target=entry - bank_points(cfg, trade=PaperTrade(
            side=Side.SHORT,
            entry=entry,
            entry_ts=0.0,
            stop=entry,
            target=entry,
            peak=entry,
            trough=entry,
            chaotic_bank=True,
        )),
        peak=entry,
        trough=entry,
        chaotic_bank=True,
    )
    manage_paper(trade, price=entry - 1.5, atr=42.0, health=80.0, hold_sec=1.0, cfg=cfg)
    assert trade.stop <= entry
