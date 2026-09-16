"""AI Scout: stacked rising longs are a take. Leftover shorts stay HOLD."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.ai_scout import scout_opportunity
from mark2.config import Mark2Config
from mark2.ema_strategy import EmaStack
from mark2.types import ScoreBundle, Side, Tick


def _leftover_long() -> EmaStack:
    """Already stacked and still rising — valid leftover long."""
    return EmaStack(
        ema9=28989.10,
        ema20=28977.94,
        ema50=28974.53,
        prev9=28984.00,
        prev20=28974.00,
        prev50=28972.00,
    )


def _sniper_long() -> EmaStack:
    """Red through both this bar."""
    return EmaStack(
        ema9=28970.12,
        ema20=28962.26,
        ema50=28968.55,
        prev9=28963.22,
        prev20=28958.53,
        prev50=28967.36,
    )


def _bear_short() -> EmaStack:
    """Already under both — leftover."""
    return EmaStack(
        ema9=28940.00,
        ema20=28955.00,
        ema50=28970.00,
        prev9=28948.00,
        prev20=28958.00,
        prev50=28971.00,
    )


def _fresh_short() -> EmaStack:
    return EmaStack(
        ema9=28940.00,
        ema20=28955.00,
        ema50=28948.00,
        prev9=28972.00,
        prev20=28956.00,
        prev50=28947.00,
    )


def test_scout_overrides_missed_long_fire() -> None:
    view = scout_opportunity(
        stack=_sniper_long(),
        price=28970.50,
        atr=18.18,
        bot_watch="CHOPPY",
        missed_side=Side.LONG,
        missed_why="EMA_SNIPER_LONG",
    )
    assert view.action == "OVERRIDE"
    assert view.side == Side.LONG
    assert view.miss is True
    assert view.why == "AI_SCOUT_OVERRIDE_LONG"


def test_scout_overrides_missed_leftover_long() -> None:
    view = scout_opportunity(
        stack=_leftover_long(),
        price=29020.00,
        atr=16.80,
        bot_watch="NOT_BEARISH",
        missed_side=Side.LONG,
        missed_why="EMA_INTERSECTION_LONG",
    )
    assert view.action == "OVERRIDE"
    assert view.side == Side.LONG
    assert view.why == "AI_SCOUT_OVERRIDE_LONG"


def test_scout_takes_leftover_bull_stack() -> None:
    view = scout_opportunity(
        stack=_leftover_long(),
        price=29020.00,
        atr=16.80,
        bot_watch="NOT_BEARISH",
    )
    assert view.action == "TAKE"
    assert view.side == Side.LONG
    assert view.why == "AI_SCOUT_LONG"


def test_scout_takes_fresh_intersection_long() -> None:
    view = scout_opportunity(
        stack=_sniper_long(),
        price=28970.50,
        atr=18.18,
        bot_watch="WAIT",
    )
    assert view.action == "TAKE"
    assert view.side == Side.LONG
    assert view.why == "AI_SCOUT_LONG"


def test_scout_holds_cluster_squeeze_leftover_short() -> None:
    """July 8 00:42 — already under both, cluster ticked under 30 pts."""
    leftover = EmaStack(
        ema9=29411.8444,
        ema20=29422.6685,
        ema50=29441.3766,
        prev9=29412.7256,
        prev20=29425.3873,
        prev50=29443.9796,
    )
    view = scout_opportunity(
        stack=leftover,
        price=29408.50,
        atr=11.82,
        bot_watch="WAIT",
    )
    assert view.action == "HOLD"
    assert view.why == "WAIT_CROSS"


def test_scout_holds_leftover_bear_stack() -> None:
    view = scout_opportunity(
        stack=_bear_short(),
        price=28935.00,
        atr=18.00,
        bot_watch="WAIT_BREAK",
    )
    assert view.action == "HOLD"
    assert view.why == "WAIT_CROSS"


def test_scout_takes_fresh_intersection_short() -> None:
    cfg = Mark2Config()
    cfg.AI_SCOUT_SHORT = True
    view = scout_opportunity(
        stack=_fresh_short(),
        price=28950.00,
        atr=18.00,
        bot_watch="WAIT",
        cfg=cfg,
    )
    assert view.action == "TAKE"
    assert view.side == Side.SHORT
    assert view.why == "AI_SCOUT_SHORT"


def test_scout_off() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_AI_SCOUT = False
    view = scout_opportunity(
        stack=_sniper_long(),
        price=28970.50,
        atr=18.18,
        cfg=cfg,
    )
    assert view.action == "HOLD"


def _engine(**kwargs):
    from mark2.engine import Mark2Engine

    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.ALLOW_LEGACY_ENTRIES = False
    cfg.MARK2_ENABLED = True
    cfg.MODE = "PAPER_TRADE"
    cfg.ENABLE_AI_SCOUT = True
    cfg.AI_SCOUT_PAPER_FALLBACK = True
    cfg.EMA_ALLOW_SHORT = True
    cfg.ACCOUNT_RISK_PROFILE = "OFF"
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    eng = Mark2Engine(cfg)
    eng._ema_armed = True
    eng.completed_bars = [
        {"time": "t0", "open": 28990.0, "high": 29020.0, "low": 28980.0, "close": 29000.0, "volume": 10}
    ]
    return eng


def test_live_reject_does_not_fake_paper() -> None:
    eng = _engine(MODE="LIVE", AI_SCOUT_PAPER_FALLBACK=False)
    eng.risk.connected = False
    eng.execution.sink = None
    tick = Tick(ts=1.0, price=28997.75)
    from mark2.types import EventRecord, EventType

    ev = EventRecord(
        event_id=1,
        event_type=EventType.EMA_CROSS,
        direction=Side.LONG,
        started_ts=1.0,
        started_bar_time="t1",
        started_price=28997.75,
    )
    eng.events.active = ev
    eng._last_entry_tags = {"trigger": "EMA_SNIPER_LONG", "book": "", "rsi": ""}
    from mark2.types import MarketSnapshot

    snap = MarketSnapshot(ts=1.0, price=28997.75, completed_bars=[], forming_bar=None, atr=18.18)
    result = eng._arm_and_maybe_execute(tick, snap, ScoreBundle(), ev)
    assert result == "REJECT_RISK"
    assert eng.paper is None


def test_paper_fallback_still_optional() -> None:
    eng = _engine(MODE="LIVE", AI_SCOUT_PAPER_FALLBACK=True)
    eng.risk.connected = False
    eng.execution.sink = None
    tick = Tick(ts=1.0, price=28997.75)
    from mark2.types import EventRecord, EventType

    ev = EventRecord(
        event_id=1,
        event_type=EventType.EMA_CROSS,
        direction=Side.LONG,
        started_ts=1.0,
        started_bar_time="t1",
        started_price=28997.75,
    )
    eng.events.active = ev
    eng._last_entry_tags = {"trigger": "EMA_SNIPER_LONG", "book": "", "rsi": ""}
    from mark2.types import MarketSnapshot

    snap = MarketSnapshot(ts=1.0, price=28997.75, completed_bars=[], forming_bar=None, atr=18.18)
    result = eng._arm_and_maybe_execute(tick, snap, ScoreBundle(), ev)
    assert result == "PAPER_EXECUTE"
    assert eng.paper is not None
    assert eng.paper.side == Side.LONG


def test_scout_override_leftover_long_enters() -> None:
    eng = _engine()
    tick = Tick(ts=1.0, price=29020.00)
    from mark2.types import MarketSnapshot

    snap = MarketSnapshot(ts=1.0, price=29020.00, completed_bars=[], forming_bar=None, atr=16.80)
    eng._ema_watch = "NOT_BEARISH"
    eng._ema_atr = lambda: 16.80  # type: ignore[method-assign]
    eng._scout_missed_side = Side.LONG
    eng._scout_missed_why = "EMA_INTERSECTION_LONG"
    out = eng._scout_on_flat(tick, snap, ScoreBundle(), _leftover_long())
    assert out is not None
    assert out["decision"] == "PAPER_EXECUTE"
    assert out["reject"] == ""
    assert eng.paper is not None
    assert eng.paper.side == Side.LONG
    assert eng._scout_view.action == "OVERRIDE"
    assert eng.paper.ema_entry_tag == "AI_SCOUT_OVERRIDE_LONG"


def test_live_override_reject_does_not_keep_hud_override() -> None:
    eng = _engine(MODE="LIVE", AI_SCOUT_PAPER_FALLBACK=False)
    eng.risk.connected = False
    eng.execution.sink = None
    tick = Tick(ts=1.0, price=29020.00)
    from mark2.types import MarketSnapshot

    snap = MarketSnapshot(ts=1.0, price=29020.00, completed_bars=[], forming_bar=None, atr=16.80)
    eng._ema_atr = lambda: 16.80  # type: ignore[method-assign]
    eng._scout_missed_side = Side.LONG
    eng._scout_missed_why = "EMA_SNIPER_LONG"
    out = eng._scout_on_flat(tick, snap, ScoreBundle(), _leftover_long())
    assert eng.paper is None
    assert out is not None
    assert out["reject"] == "REJECT_RISK"
    assert eng._scout_view.action == "HOLD"
    assert eng._scout_view.why == "REJECT_RISK"
    assert eng._scout_view.miss is False
    hud = eng._scout_view.hud()
    assert hud["action"] == "HOLD"
    assert hud["miss"] is False


def test_scout_takes_leftover_long_stack() -> None:
    eng = _engine()
    tick = Tick(ts=1.0, price=29020.00)
    from mark2.types import MarketSnapshot

    snap = MarketSnapshot(ts=1.0, price=29020.00, completed_bars=[], forming_bar=None, atr=16.80)
    eng._ema_watch = "NOT_BEARISH"
    eng._ema_atr = lambda: 16.80  # type: ignore[method-assign]
    out = eng._scout_on_flat(tick, snap, ScoreBundle(), _leftover_long())
    assert out is not None
    assert eng.paper is not None
    assert eng.paper.side == Side.LONG


def test_scout_puts_engine_in_fresh_long() -> None:
    eng = _engine()
    tick = Tick(ts=1.0, price=28970.50)
    from mark2.types import MarketSnapshot

    snap = MarketSnapshot(ts=1.0, price=28970.50, completed_bars=[], forming_bar=None, atr=18.18)
    eng._ema_watch = "WAIT"
    eng._ema_atr = lambda: 18.18  # type: ignore[method-assign]
    out = eng._scout_on_flat(tick, snap, ScoreBundle(), _sniper_long())
    assert out is not None
    assert eng.paper is not None
    assert eng.paper.side == Side.LONG
    assert eng.paper.ema_entry_tag == "AI_SCOUT_LONG"


def test_five_second_gap_blocks_back_to_back() -> None:
    import time

    eng = _engine()
    tick = Tick(ts=1.0, price=28970.50)
    from mark2.types import MarketSnapshot

    snap = MarketSnapshot(ts=1.0, price=28970.50, completed_bars=[], forming_bar=None, atr=18.18)
    eng._ema_atr = lambda: 18.18  # type: ignore[method-assign]
    eng._last_exit_wall = time.time()
    out = eng._scout_on_flat(tick, snap, ScoreBundle(), _sniper_long())
    assert out is None
    assert eng.paper is None
    assert eng._scout_view.why == "COOLDOWN"
    eng._last_exit_wall = time.time() - 6.0
    out2 = eng._scout_on_flat(tick, snap, ScoreBundle(), _sniper_long())
    assert out2 is not None
    assert eng.paper is not None
