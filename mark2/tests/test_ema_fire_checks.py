"""Redundancy checks: one long per stack, no falling-red or white-only fires.

July 8 2026 MNQ stacks from the replay log. Signal, arm gate, and engine
must agree on every row. Already-stacked rising longs fire once, then STACK_USED.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.ema_strategy import (
    EmaStack,
    bullish_fade_short_reason,
    ema_entry_signal,
    ema_long_arm_ok,
    ema_long_decision,
    ema_long_signal_why,
    ema_short_arm_ok,
    manage_ema_hold,
    red_above_white_and_blue,
    red_clears_under_white_and_blue,
    red_clears_white_and_blue,
    red_falling,
    red_rising,
    stack_lock_should_clear,
    ema_fire_gates,
    IntersectionStatus,
)
from mark2.exits import PaperTrade
from mark2.types import Side

# Completed-bar stacks from mark2_decisions.jsonl (2026-07-08).
JUL08_0323_WHITE_ONLY = EmaStack(
    ema9=29305.2396,
    ema20=29305.7527,
    ema50=29312.6445,
    prev9=29303.5495,
    prev20=29305.0951,
    prev50=29312.6708,
)
JUL08_0324_THROUGH_WHITE = EmaStack(
    ema9=29309.4917,
    ema20=29307.7286,
    ema50=29313.1878,
    prev9=29305.2396,
    prev20=29305.7527,
    prev50=29312.6445,
)
JUL08_0325_SNIPER = EmaStack(
    ema9=29315.8434,
    ema20=29310.9211,
    ema50=29314.2883,
    prev9=29309.4917,
    prev20=29307.7286,
    prev50=29313.1878,
)
JUL08_0326_LEFTOVER = EmaStack(
    ema9=29321.3747,
    ema20=29314.0239,
    ema50=29315.4338,
    prev9=29315.8434,
    prev20=29310.9211,
    prev50=29314.2883,
)
JUL08_0402_DIP = EmaStack(
    ema9=29377.5170,
    ema20=29378.5309,
    ema50=29364.8001,
    prev9=29380.5213,
    prev20=29379.9026,
    prev50=29364.7715,
)
JUL08_0411_UNDER_WHITE = EmaStack(
    ema9=29366.8316,
    ema20=29369.1001,
    ema50=29363.8247,
    prev9=29359.5655,
    prev20=29367.5209,
    prev50=29362.6300,
)
JUL08_0412_BULL = EmaStack(
    ema9=29374.4652,
    ema20=29372.5191,
    ema50=29365.4394,
    prev9=29366.8316,
    prev20=29369.1001,
    prev50=29363.8247,
)
JUL08_0413_LEFTOVER = EmaStack(
    ema9=29380.6722,
    ema20=29375.6601,
    ema50=29367.0104,
    prev9=29374.4652,
    prev20=29372.5191,
    prev50=29365.4394,
)
FALLING_THROUGH_BOTH = EmaStack(
    ema9=29340.0,
    ema20=29310.0,
    ema50=29320.0,
    prev9=29348.0,
    prev20=29311.0,
    prev50=29320.0,
)


def _cfg() -> Mark2Config:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.EMA_ALLOW_LONG = True
    cfg.EMA_ALLOW_SHORT = True
    cfg.EMA_LONG_SNIPER = True
    cfg.EMA_RSI_LONG = False
    cfg.EMA_CHOP_LONG = False
    cfg.EMA_BULL_FADE_SHORT = False
    cfg.EMA_LONG_REQUIRES_BEARISH = False
    cfg.ACCOUNT_RISK_PROFILE = "OFF"
    return cfg


def _engine():
    from mark2.engine import Mark2Engine

    cfg = _cfg()
    cfg.ALLOW_LEGACY_ENTRIES = False
    cfg.MARK2_ENABLED = True
    cfg.MODE = "PAPER_TRADE"
    cfg.MAX_ENTRY_EXTENSION_ATR = 0.60
    eng = Mark2Engine(cfg)
    eng._ema_armed = True
    eng.completed_bars = [
        {"time": "t0", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10}
    ]
    eng.context._cache["atr"] = 30.0
    eng._ema_atr = lambda: 30.0  # type: ignore[method-assign]
    eng._ema_stop_atr = lambda: 30.0  # type: ignore[method-assign]
    return eng


def _armed(eng) -> bool:
    return eng.paper is not None or eng._ema_pending_side != Side.NONE or eng._ema_pullback is not None


# (name, stack, stack_taken, expect_fire, expect_why_or_reason)
TAPE = (
    ("03:23 red still under white", JUL08_0323_WHITE_ONLY, False, False, "NO_SNIPER"),
    ("03:24 through white, not blue", JUL08_0324_THROUGH_WHITE, False, False, "WHITE_ONLY"),
    ("03:25 first through-both while 20/50 bearish", JUL08_0325_SNIPER, False, True, "EMA_INTERSECTION_LONG"),
    ("03:26 leftover same stack", JUL08_0326_LEFTOVER, True, False, "STACK_USED"),
    ("04:02 red dips under white", JUL08_0402_DIP, True, False, "RED_FALLING"),
    ("04:11 red still under white", JUL08_0411_UNDER_WHITE, False, False, "NO_SNIPER"),
    ("04:12 white recross already through blue", JUL08_0412_BULL, False, True, "EMA_INTERSECTION_LONG"),
    ("04:12 recross after a dip even if lock still set", JUL08_0412_BULL, True, True, "EMA_INTERSECTION_LONG"),
    ("04:13 leftover after the 04:12 long", JUL08_0413_LEFTOVER, True, False, "STACK_USED"),
    ("falling red already through both", FALLING_THROUGH_BOTH, False, False, "RED_FALLING"),
)


def test_july8_tape_decision_table() -> None:
    cfg = _cfg()
    for name, stack, taken, expect_fire, tag in TAPE:
        fire, reason, why = ema_long_decision(stack, cfg, stack_taken=taken)
        if expect_fire:
            assert fire is True, f"{name}: expected fire, got {reason}/{why}"
            assert why == tag, f"{name}: why {why} != {tag}"
            assert reason == ""
        else:
            assert fire is False, f"{name}: should not fire ({why})"
            assert reason == tag, f"{name}: reason {reason} != {tag}"


def test_signal_and_arm_gate_never_disagree_on_fire() -> None:
    cfg = _cfg()
    for name, stack, taken, expect_fire, _tag in TAPE:
        why, reject = ema_long_signal_why(stack, cfg)
        ok, reason = ema_long_arm_ok(stack, why, cfg, stack_taken=taken)
        fire, dec_reason, dec_why = ema_long_decision(stack, cfg, stack_taken=taken)
        if expect_fire:
            assert why == "EMA_INTERSECTION_LONG", name
            assert reject == ""
            assert ok is True and fire is True
            assert dec_why == why
        else:
            assert ok is False or why == ""
            assert fire is False
            assert dec_reason == (reason if why else reject)


def test_engine_matches_decision_on_july8_tape() -> None:
    cfg = _cfg()
    for name, stack, taken, expect_fire, _tag in TAPE:
        fire, _reason, why = ema_long_decision(stack, cfg, stack_taken=taken)
        eng = _engine()
        eng._ema_long_stack_taken = taken
        close = float(stack.ema9) + 8.0
        eng.completed_bars[-1]["close"] = close
        if why:
            eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why=why)
        else:
            eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why="EMA_SNIPER_LONG")
        got = _armed(eng)
        assert got is fire, f"{name}: engine armed={got} decision fire={fire}"


def test_live_tick_never_fires_bull_or_unconfirmed_sniper() -> None:
    cfg = _cfg()
    fire, reason, why = ema_long_decision(
        JUL08_0412_BULL,
        cfg,
        live_tick=True,
    )
    assert fire is False
    assert why == "EMA_INTERSECTION_LONG"
    assert reason == "WAIT_CLOSE"

    fire, reason, why = ema_long_decision(
        JUL08_0325_SNIPER,
        cfg,
        completed=JUL08_0324_THROUGH_WHITE,
        live_tick=True,
    )
    assert fire is False
    assert why == "EMA_INTERSECTION_LONG"
    assert reason == "WAIT_CLOSE"


def test_live_scan_agrees_with_arm_gate() -> None:
    from mark2 import engine as engine_mod

    cases = (
        (JUL08_0412_BULL, JUL08_0324_THROUGH_WHITE, "EMA_INTERSECTION_LONG", "WAIT_CLOSE"),
        (JUL08_0325_SNIPER, JUL08_0324_THROUGH_WHITE, "EMA_INTERSECTION_LONG", "WAIT_CLOSE"),
        (JUL08_0326_LEFTOVER, JUL08_0326_LEFTOVER, "EMA_INTERSECTION_LONG", "STACK_USED"),
    )
    for live, done, why, block in cases:
        eng = _engine()
        eng._ema_long_stack_taken = block == "STACK_USED"
        eng.completed_bars = [
            {"time": f"t{i}", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10}
            for i in range(16)
        ]
        orig_read = engine_mod.read_ema_stack
        orig_sig = engine_mod.ema_entry_signal

        def _read(bars, cfg, _live=live, _done=done, _eng=eng):
            if bars is _eng.completed_bars:
                return _done
            return _live

        engine_mod.read_ema_stack = _read
        engine_mod.ema_entry_signal = lambda *a, **k: (Side.LONG, why)
        try:
            eng._ema_scan_live_long()
        finally:
            engine_mod.read_ema_stack = orig_read
            engine_mod.ema_entry_signal = orig_sig
        assert _armed(eng) is False
        assert eng._ema_watch == block


def test_one_long_per_stack_then_fresh_punch_after_dip() -> None:
    cfg = _cfg()
    first, _, why1 = ema_long_decision(JUL08_0325_SNIPER, cfg, stack_taken=False)
    assert first is True and why1 == "EMA_INTERSECTION_LONG"
    leftover, reason, _ = ema_long_decision(JUL08_0326_LEFTOVER, cfg, stack_taken=True)
    assert leftover is False and reason == "STACK_USED"
    assert stack_lock_should_clear(JUL08_0402_DIP) is True
    second, reason2, why2 = ema_long_decision(JUL08_0412_BULL, cfg, stack_taken=True)
    assert second is True and why2 == "EMA_INTERSECTION_LONG" and reason2 == ""


def test_leftover_spray_cannot_arm_three_times() -> None:
    eng = _engine()
    eng.completed_bars[-1]["close"] = 29326.5
    eng._ema_try_arm_signal(Side.LONG, JUL08_0325_SNIPER, allow_entry=True, why="EMA_SNIPER_LONG")
    assert _armed(eng) is True
    fills = 0
    for _ in range(3):
        eng.paper = None
        eng._ema_clear_setup()
        eng._ema_try_arm_signal(Side.LONG, JUL08_0326_LEFTOVER, allow_entry=True, why="EMA_SNIPER_LONG")
        if _armed(eng):
            fills += 1
    assert fills == 0
    assert eng._ema_long_stack_taken is True


def test_fresh_sniper_then_leftover_is_one_fill() -> None:
    eng = _engine()
    eng.completed_bars[-1]["close"] = 29326.5
    eng._ema_try_arm_signal(Side.LONG, JUL08_0325_SNIPER, allow_entry=True, why="EMA_SNIPER_LONG")
    assert _armed(eng) is True
    eng.paper = None
    eng._ema_clear_setup()
    eng._ema_try_arm_signal(Side.LONG, JUL08_0326_LEFTOVER, allow_entry=True, why="EMA_SNIPER_LONG")
    assert _armed(eng) is False
    assert eng._ema_long_stack_taken is True


def test_seed_bars_do_not_arm() -> None:
    eng = _engine()
    eng._ema_armed = False
    eng.completed_bars[-1]["time"] = "2026-07-08T03:25:00"
    from mark2 import engine as engine_mod

    orig_read = engine_mod.read_ema_stack
    orig_sig = engine_mod.ema_entry_signal
    engine_mod.read_ema_stack = lambda bars, cfg: JUL08_0325_SNIPER
    engine_mod.ema_entry_signal = lambda *a, **k: (Side.LONG, "EMA_SNIPER_LONG")
    try:
        eng._ema_on_completed_bar(allow_entry=False)
    finally:
        engine_mod.read_ema_stack = orig_read
        engine_mod.ema_entry_signal = orig_sig
    assert _armed(eng) is False
    assert eng._ema_long_stack_taken is False


def test_rewind_gap_clears_lock_and_fresh_punch_can_fire() -> None:
    eng = _engine()
    eng._ema_long_stack_taken = True
    eng._ema_last_bar_time = "2026-07-08T04:16:00"
    eng.completed_bars[-1]["time"] = "2026-07-08T03:25:00"
    from mark2 import engine as engine_mod

    orig_read = engine_mod.read_ema_stack
    orig_sig = engine_mod.ema_entry_signal
    engine_mod.read_ema_stack = lambda bars, cfg: JUL08_0325_SNIPER
    engine_mod.ema_entry_signal = lambda *a, **k: (Side.LONG, "EMA_SNIPER_LONG")
    try:
        eng._ema_on_completed_bar(allow_entry=True)
    finally:
        engine_mod.read_ema_stack = orig_read
        engine_mod.ema_entry_signal = orig_sig
    assert eng._ema_long_stack_taken is False or _armed(eng) is True


def test_july8_0042_leftover_stack_is_not_a_short() -> None:
    """Replay 00:42 short: already under both, cluster just squeezed under 30."""
    from mark2.ema_strategy import just_hit_intersection, short_sniper_reason

    cfg = _cfg()
    leftover = EmaStack(
        ema9=29411.8444,
        ema20=29422.6685,
        ema50=29441.3766,
        prev9=29412.7256,
        prev20=29425.3873,
        prev50=29443.9796,
    )
    assert just_hit_intersection(leftover, 11.82, cfg) is True
    assert red_clears_under_white_and_blue(leftover) is False
    assert short_sniper_reason(leftover, cfg, atr=11.82) == "STACK_STALE"
    eng = _engine()
    eng.completed_bars[-1]["close"] = 29408.5
    eng._ema_try_arm_signal(Side.SHORT, leftover, allow_entry=True, why="EMA_SNIPER_SHORT")
    assert _armed(eng) is False


def test_shorts_arm_on_intersection_down() -> None:
    eng = _engine()
    down = EmaStack(
        ema9=29300.0,
        ema20=29320.0,
        ema50=29310.0,
        prev9=29330.0,
        prev20=29321.0,
        prev50=29309.0,
    )
    eng.completed_bars[-1]["close"] = 29290.0
    eng._ema_try_arm_signal(Side.SHORT, down, allow_entry=True, why="EMA_SNIPER_SHORT")
    assert _armed(eng) is True


def test_chaotic_requires_red_through_white_and_blue() -> None:
    cfg = _cfg()
    fire, reason, why = ema_long_decision(JUL08_0324_THROUGH_WHITE, cfg, regime="CHAOTIC")
    assert fire is False
    assert why == ""
    fire, reason, why = ema_long_decision(JUL08_0325_SNIPER, cfg, regime="CHAOTIC")
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"
    fire, reason, why = ema_long_decision(JUL08_0412_BULL, cfg, regime="CHAOTIC")
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"


def test_choppy_does_not_take_white_only() -> None:
    cfg = _cfg()
    fire, reason, why = ema_long_decision(JUL08_0324_THROUGH_WHITE, cfg, regime="CHOPPY")
    assert fire is False
    assert reason == "WHITE_ONLY"
    fire, reason, why = ema_long_decision(JUL08_0325_SNIPER, cfg, regime="CHOPPY")
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"
    fire, reason, why = ema_long_decision(JUL08_0412_BULL, cfg, regime="CHOPPY")
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"


def test_engine_arms_choppy_through_both() -> None:
    from mark2.types import MarketSnapshot

    eng = _engine()
    eng.last_snap = MarketSnapshot(
        ts=1.0,
        price=29341.25,
        completed_bars=eng.completed_bars,
        forming_bar=None,
        trend_bias="BEARISH",
        trend_regime="CHOPPY",
    )
    eng.completed_bars[-1]["close"] = 29341.25
    eng._ema_try_arm_signal(Side.LONG, JUL08_0325_SNIPER, allow_entry=True, why="EMA_SNIPER_LONG")
    assert _armed(eng) is True


def test_engine_arms_chaotic_through_both() -> None:
    from mark2.types import MarketSnapshot

    eng = _engine()
    eng.last_snap = MarketSnapshot(
        ts=1.0,
        price=29341.25,
        completed_bars=eng.completed_bars,
        forming_bar=None,
        trend_bias="BEARISH",
        trend_regime="CHAOTIC",
    )
    eng.completed_bars[-1]["close"] = 29341.25
    eng._ema_try_arm_signal(Side.LONG, JUL08_0325_SNIPER, allow_entry=True, why="EMA_SNIPER_LONG")
    assert _armed(eng) is True
    eng2 = _engine()
    eng2.last_snap = MarketSnapshot(
        ts=1.0,
        price=29309.5,
        completed_bars=eng2.completed_bars,
        forming_bar=None,
        trend_bias="BEARISH",
        trend_regime="CHAOTIC",
    )
    eng2._ema_try_arm_signal(Side.LONG, JUL08_0324_THROUGH_WHITE, allow_entry=True, why="EMA_CHOP_LONG")
    assert _armed(eng2) is False


def test_engine_arms_choppy_white_cross() -> None:
    from mark2.types import MarketSnapshot

    eng = _engine()
    eng.last_snap = MarketSnapshot(
        ts=1.0,
        price=29309.5,
        completed_bars=eng.completed_bars,
        forming_bar=None,
        trend_bias="BEARISH",
        trend_regime="CHOPPY",
    )
    eng.completed_bars[-1]["close"] = 29309.5
    eng._ema_try_arm_signal(Side.LONG, JUL08_0324_THROUGH_WHITE, allow_entry=True, why="EMA_CHOP_LONG")
    assert _armed(eng) is False


def test_trending_or_high_vol_still_fire() -> None:
    cfg = _cfg()
    fire, reason, why = ema_long_decision(JUL08_0325_SNIPER, cfg, regime="HIGH_VOL")
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"
    fire, reason, why = ema_long_decision(JUL08_0412_BULL, cfg, regime="TRENDING")
    assert fire is True
    assert why == "EMA_INTERSECTION_LONG"


def test_punch_helpers_match_tape() -> None:
    assert red_above_white_and_blue(JUL08_0324_THROUGH_WHITE) is False
    assert red_clears_white_and_blue(JUL08_0325_SNIPER) is True
    assert red_above_white_and_blue(JUL08_0325_SNIPER) is True
    assert red_clears_white_and_blue(JUL08_0326_LEFTOVER) is False
    assert red_falling(JUL08_0402_DIP) is True
    assert red_rising(JUL08_0412_BULL) is True
    assert red_clears_white_and_blue(JUL08_0412_BULL) is True
    assert stack_lock_should_clear(JUL08_0402_DIP) is True
    assert stack_lock_should_clear(JUL08_0412_BULL) is True
    assert stack_lock_should_clear(JUL08_0326_LEFTOVER) is False


INTERSECT_DOWN = EmaStack(
    ema9=100.0,
    ema20=100.4,
    ema50=100.2,
    prev9=120.0,
    prev20=90.0,
    prev50=85.0,
)
WHITE_DOWN_NO_KNOT = EmaStack(
    ema9=100.0,
    ema20=100.5,
    ema50=99.0,
    prev9=100.8,
    prev20=100.4,
    prev50=98.9,
)


def test_bullish_fade_short_waits_for_intersection_down() -> None:
    cfg = _cfg()
    cfg.EMA_BULL_FADE_SHORT = True
    assert (
        bullish_fade_short_reason(
            INTERSECT_DOWN,
            cfg,
            bias="BULLISH",
            atr=10.0,
            rsi=64.0,
            rsi_prev=70.0,
            rsi_peak=72.0,
        )
        == ""
    )
    assert (
        bullish_fade_short_reason(
            WHITE_DOWN_NO_KNOT,
            cfg,
            bias="BULLISH",
            atr=10.0,
            rsi=64.0,
            rsi_prev=70.0,
            rsi_peak=72.0,
            regime="CHOPPY",
        )
        == "NO_INTERSECT"
    )
    assert (
        bullish_fade_short_reason(
            INTERSECT_DOWN,
            cfg,
            bias="BULLISH",
            atr=10.0,
            rsi=64.0,
            rsi_prev=70.0,
            rsi_peak=72.0,
            fade_ready=False,
        )
        == "WAIT_BREAK"
    )
    assert (
        bullish_fade_short_reason(
            INTERSECT_DOWN, cfg, bias="BEARISH", atr=10.0, rsi=64.0, rsi_prev=70.0, rsi_peak=72.0
        )
        == "NOT_BULLISH"
    )
    assert (
        bullish_fade_short_reason(
            INTERSECT_DOWN, cfg, bias="BULLISH", atr=10.0, rsi=70.0, rsi_prev=69.0, rsi_peak=72.0
        )
        == "RSI_NOT_DYING"
    )
    assert (
        bullish_fade_short_reason(
            JUL08_0324_THROUGH_WHITE,
            cfg,
            bias="BULLISH",
            atr=10.0,
            rsi=64.0,
            rsi_prev=70.0,
            rsi_peak=72.0,
        )
        == "RED_RISING"
    )
    leftover_under = EmaStack(
        ema9=90.0,
        ema20=110.0,
        ema50=105.0,
        prev9=91.0,
        prev20=109.5,
        prev50=104.8,
    )
    assert (
        bullish_fade_short_reason(
            leftover_under,
            cfg,
            bias="BULLISH",
            atr=10.0,
            rsi=64.0,
            rsi_prev=70.0,
            rsi_peak=72.0,
        )
        == "NO_INTERSECT"
    )


def test_entry_signal_hunts_fade_short_when_bullish() -> None:
    from mark2 import ema_strategy as strat

    cfg = _cfg()
    cfg.EMA_BULL_FADE_SHORT = True
    bars = [
        {"time": "t0", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 10},
        {"time": "t1", "open": 101.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 10},
    ]
    orig = strat.read_ema_stack
    strat.read_ema_stack = lambda *a, **k: INTERSECT_DOWN
    try:
        side, why = ema_entry_signal(
            bars,
            cfg,
            atr=10.0,
            bias="BULLISH",
            regime="CHOPPY",
            rsi=64.0,
            rsi_prev=70.0,
            rsi_peak=72.0,
        )
        assert side == Side.SHORT
        assert why == "EMA_FADE_SHORT"
        side, why = ema_entry_signal(
            bars,
            cfg,
            atr=10.0,
            bias="BULLISH",
            regime="TRENDING",
            rsi=64.0,
            rsi_prev=70.0,
            rsi_peak=72.0,
        )
        assert side == Side.SHORT
        assert why == "EMA_FADE_SHORT"
    finally:
        strat.read_ema_stack = orig


def test_engine_skips_fade_short_on_the_long_exit_bar() -> None:
    from mark2.types import MarketSnapshot

    eng = _engine()
    eng.last_snap = MarketSnapshot(
        ts=1.0,
        price=100.0,
        completed_bars=eng.completed_bars,
        forming_bar=None,
        trend_bias="BULLISH",
        trend_regime="CHOPPY",
    )
    eng._ema_rsi_state = lambda bars=None: (64.0, 70.0, 72.0)  # type: ignore[method-assign]
    eng._ema_fade_armed = True
    eng._ema_fade_block_bar_i = max(0, len(eng.completed_bars) - 1)
    eng._ema_try_arm_signal(Side.SHORT, INTERSECT_DOWN, allow_entry=True, why="EMA_FADE_SHORT")
    assert _armed(eng) is False


def test_engine_arms_bullish_fade_short() -> None:
    from mark2.types import MarketSnapshot

    eng = _engine()
    eng.cfg.EMA_BULL_FADE_SHORT = True
    eng.last_snap = MarketSnapshot(
        ts=1.0,
        price=100.0,
        completed_bars=eng.completed_bars,
        forming_bar=None,
        trend_bias="BULLISH",
        trend_regime="CHOPPY",
    )
    eng._ema_rsi_state = lambda bars=None: (64.0, 70.0, 72.0)  # type: ignore[method-assign]
    eng._ema_fade_armed = True
    eng._ema_fade_block_bar_i = -1
    eng._ema_try_arm_signal(Side.SHORT, INTERSECT_DOWN, allow_entry=True, why="EMA_FADE_SHORT")
    assert _armed(eng) is True
    assert eng._ema_pending_why == "EMA_FADE_SHORT" or (
        eng.paper is not None and str(getattr(eng.paper, "ema_entry_tag", "") or "") in ("", "EMA_FADE_SHORT")
    )


def test_engine_fade_short_waits_for_completed_intersection() -> None:
    from mark2.types import MarketSnapshot

    eng = _engine()
    eng.cfg.EMA_BULL_FADE_SHORT = True
    eng.last_snap = MarketSnapshot(
        ts=1.0,
        price=100.0,
        completed_bars=eng.completed_bars,
        forming_bar=None,
        trend_bias="BULLISH",
        trend_regime="TRENDING",
    )
    eng._ema_rsi_state = lambda bars=None: (64.0, 70.0, 72.0)  # type: ignore[method-assign]
    ok, reason = ema_short_arm_ok(
        INTERSECT_DOWN,
        "EMA_FADE_SHORT",
        eng.cfg,
        completed=JUL08_0325_SNIPER,
        live_tick=True,
        bias="BULLISH",
        atr=10.0,
        rsi=64.0,
        rsi_prev=70.0,
        rsi_peak=72.0,
        regime="TRENDING",
        fade_ready=True,
    )
    assert ok is False
    assert reason == "WAIT_CLOSE"
    ok, reason = ema_short_arm_ok(
        INTERSECT_DOWN,
        "EMA_FADE_SHORT",
        eng.cfg,
        completed=INTERSECT_DOWN,
        live_tick=True,
        bias="BULLISH",
        atr=10.0,
        rsi=64.0,
        rsi_prev=70.0,
        rsi_peak=72.0,
        regime="TRENDING",
        fade_ready=True,
    )
    assert ok is True


def test_ema_fire_gates_hot_when_armed_for_50() -> None:
    ix = IntersectionStatus(
        side="LONG",
        sep_ok=True,
        cross_920=True,
        armed_920=True,
        fire=False,
        stage="WAIT_9_50",
        sep_now_pts=8.0,
    )
    gates = {g["id"]: g for g in ema_fire_gates(ix)}
    assert gates["spread"]["status"] == "pass"
    assert gates["x920"]["status"] == "pass"
    assert gates["x950"]["hot"] is True
    ix.fire = True
    go = {g["id"]: g for g in ema_fire_gates(ix)}
    assert go["fire"]["status"] == "pass"
    assert go["fire"]["hot"] is True
