"""HUD manual entry must not thesis-abort with FAILED_EVENT."""

from __future__ import annotations

from mark2.config import Mark2Config
from mark2.exits import PaperTrade, manage_paper
from mark2.types import MarketSnapshot, ScoreBundle, Side


def _snap(*, vel: float = 0.0, price: float = 20000.0) -> MarketSnapshot:
    return MarketSnapshot(
        ts=1.0,
        price=price,
        completed_bars=[],
        forming_bar={"open": price, "high": price + 1, "low": price - 1},
        atr=4.0,
        velocity=vel,
        acceleration=0.0,
        relative_volume=1.0,
        impulse_score=60.0,
        trend_bias="BULLISH",
        trend_regime="TRENDING",
        structure_state="HH_HL",
        longs_allowed=True,
        shorts_allowed=False,
    )


def _scores(*, long_cv: float = -0.25) -> ScoreBundle:
    return ScoreBundle(
        long_confidence=65.0,
        short_confidence=40.0,
        long_conf_velocity=long_cv,
        short_conf_velocity=-0.1,
    )


def test_manual_pre_target_no_failed_event():
    cfg = Mark2Config()
    cfg.ENABLE_MOMENTUM_EXIT = True
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=0.0,
        stop=entry - 25.0,
        target=entry + 12.5,
        peak=entry,
        trough=entry,
        manual_entry=True,
    )
    snap = _snap(vel=-0.2, price=entry + 2.0)
    scores = _scores(long_cv=-0.25)
    for _ in range(5):
        done, why, _ = manage_paper(
            trade,
            price=entry + 2.0,
            atr=4.0,
            health=20.0,
            hold_sec=3.0,
            cfg=cfg,
            scores=scores,
            snap=snap,
            event_alive=False,
        )
    assert done is False
    assert "FAILED_EVENT" not in why
