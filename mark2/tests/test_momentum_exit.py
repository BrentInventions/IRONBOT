"""Momentum/confidence thesis abort exits."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.exits import PaperTrade, manage_paper
from mark2.types import MarketSnapshot, ScoreBundle, Side


def _snap(*, vel: float, acc: float = 0.0) -> MarketSnapshot:
    return MarketSnapshot(
        ts=1.0,
        price=20000.0,
        completed_bars=[],
        forming_bar={"open": 20000.0, "high": 20001.0, "low": 19999.0},
        atr=4.0,
        velocity=vel,
        acceleration=acc,
        relative_volume=1.0,
        impulse_score=60.0,
        trend_bias="BULLISH",
        trend_regime="TRENDING",
        structure_state="HH_HL",
        longs_allowed=True,
        shorts_allowed=False,
        vwap_distance_atr=0.0,
        volume_acceleration=0.0,
        swing_high=0.0,
        swing_low=0.0,
    )


def _scores(*, long_c: float = 65.0, long_cv: float = 0.3, short_c: float = 40.0) -> ScoreBundle:
    return ScoreBundle(
        long_confidence=long_c,
        short_confidence=short_c,
        long_conf_velocity=long_cv,
        short_conf_velocity=-0.1,
        long_conf_accel=0.0,
        short_conf_accel=0.0,
    )


def test_aborts_long_when_velocity_and_confidence_fade():
    cfg = Mark2Config()
    cfg.ENABLE_MOMENTUM_EXIT = True
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=0.0,
        stop=19980.0,
        target=20012.5,
        peak=20000.0,
        trough=20000.0,
    )
    snap = _snap(vel=-0.2)
    scores = _scores(long_cv=-0.25)
    manage_paper(
        trade,
        price=20002.0,
        atr=4.0,
        health=60.0,
        hold_sec=0.0,
        cfg=cfg,
        scores=scores,
        snap=snap,
        event_alive=True,
    )
    assert trade.was_green is True
    done = False
    why = ""
    for i in range(3):
        done, why, _ = manage_paper(
            trade,
            price=20002.0,
            atr=4.0,
            health=55.0,
            hold_sec=float(i + 1),
            cfg=cfg,
            scores=scores,
            snap=snap,
            event_alive=True,
        )
        if done:
            break
    assert done
    assert why.startswith("FAILED_EVENT")


def test_aborts_immediately_on_health_collapse():
    cfg = Mark2Config()
    cfg.ENABLE_MOMENTUM_EXIT = True
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=0.0,
        stop=19980.0,
        target=20012.5,
        peak=20000.0,
        trough=20000.0,
        peak_health=70.0,
    )
    snap = _snap(vel=-0.15)
    scores = _scores()
    manage_paper(
        trade,
        price=20002.0,
        atr=4.0,
        health=60.0,
        hold_sec=0.0,
        cfg=cfg,
        scores=scores,
        snap=snap,
        event_alive=True,
    )
    done, why, _ = manage_paper(
        trade,
        price=20002.0,
        atr=4.0,
        health=24.0,
        hold_sec=3.0,
        cfg=cfg,
        scores=scores,
        snap=snap,
        event_alive=True,
    )
    assert done
    assert "health_low" in why


def test_bank_trail_still_works_without_scores():
    cfg = Mark2Config()
    cfg.ENABLE_MOMENTUM_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=0.0,
        stop=20012.5,
        target=20012.5,
        peak=20020.0,
        trough=20000.0,
        target_touched=True,
        runner=True,
    )
    done, why, _ = manage_paper(
        trade,
        price=20014.0,
        atr=4.0,
        health=80.0,
        hold_sec=30.0,
        cfg=cfg,
    )
    assert done
    assert why == "TRAIL"
