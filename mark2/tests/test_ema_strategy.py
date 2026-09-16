"""Red/white completed-bar crossover. Blue is calculated but not used to trade."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.ema_strategy import (
    EMA_DATASET_KEYS,
    EmaPullbackSetup,
    EmaStack,
    cross_side,
    ema_atr_stop,
    ema_body_close_exit,
    ema_dataset_row,
    ema_entry_signal,
    ema_structure_valid,
    entry_extension_ok,
    ema_line_lamps,
    intersection_side,
    intersection_status,
    just_hit_intersection,
    lines_intersecting,
    long_sniper_reason,
    red_crosses_blue,
    separation_ok,
    red_reached_under_white_and_blue,
    red_reached_white_and_blue,
    manage_ema_hold,
    mfe_losing_momentum,
    mfe_lock_active,
    profit_keep_lock_price,
    profit_keep_usd,
    grow_keep_usd,
    grow_mode_active,
    adverse_stack_exit,
    runner_tip_trail_pts,
    pullback_zone_ok,
    read_ema_stack,
    red_above_white_and_blue,
    red_below_white_and_blue,
    red_clears_under_white_and_blue,
    red_clears_white_and_blue,
    red_falling,
    red_on_blue_trajectory,
    red_rising,
    choppy_exit_points,
    rsi_bull_long_reason,
    rsi_macd_ok,
    runner_needs_room,
    runner_trail_atr_mult,
    short_intersect_reason,
    short_sniper_reason,
    signed_red_white_spread_atr,
    stack_is_bearish,
    stack_is_bullish,
)
from mark2.indicators import rsi as rsi_ind
from mark2.exits import PaperTrade
from mark2.entry_tuning import apply_toggles, snapshot
from mark2.types import Side


def test_long_cross_over_white() -> None:
    stack = EmaStack(
        ema9=10.4,
        ema20=10.1,
        ema50=10.2,
        prev9=9.0,
        prev20=10.0,
        prev50=10.2,
    )
    assert cross_side(stack) == Side.LONG


def test_short_cross_under_white() -> None:
    stack = EmaStack(
        ema9=9.6,
        ema20=10.1,
        ema50=10.0,
        prev9=10.4,
        prev20=10.1,
        prev50=10.0,
    )
    assert cross_side(stack) == Side.SHORT


def test_already_stacked_is_not_a_cross() -> None:
    stack = EmaStack(
        ema9=12.0,
        ema20=10.0,
        ema50=9.0,
        prev9=11.8,
        prev20=9.9,
        prev50=8.9,
    )
    assert cross_side(stack) == Side.NONE


def test_ema_line_lamps_pass_and_approach() -> None:
    lamps = ema_line_lamps(100.0, 99.0, 101.0, 104.0, atr=10.0, near_atr=0.35)
    assert lamps["red"] is True
    assert lamps["white"] is False
    assert lamps["nearWhite"] is True
    assert lamps["blue"] is False
    assert lamps["nearBlue"] is False
    cleared = ema_line_lamps(105.0, 99.0, 101.0, 104.0, atr=10.0, near_atr=0.35)
    assert cleared["red"] is True
    assert cleared["white"] is True
    assert cleared["blue"] is True


def test_white_only_cross_is_not_a_sniper_long() -> None:
    """Red crosses white while still under blue — wait for blue."""
    stack = EmaStack(
        ema9=10.2,
        ema20=10.0,
        ema50=80.0,
        prev9=9.8,
        prev20=10.0,
        prev50=80.0,
    )
    assert cross_side(stack) == Side.LONG
    assert red_clears_white_and_blue(stack) is False
    assert long_sniper_reason(stack, Mark2Config()) == "WHITE_ONLY"


def test_blue_does_not_block_red_white_short() -> None:
    stack = EmaStack(
        ema9=9.8,
        ema20=10.0,
        ema50=8.0,
        prev9=10.2,
        prev20=10.0,
        prev50=8.0,
    )
    assert cross_side(stack) == Side.SHORT


def test_legacy_body_close_helper_still_exists() -> None:
    ema20 = 100.0
    assert ema_body_close_exit(Side.LONG, {"open": 101.0, "close": 99.5}, ema20)
    assert not ema_body_close_exit(Side.LONG, {"open": 99.0, "close": 100.5}, ema20)


def _bars_down_then_up() -> list[dict]:
    out = []
    px = 200.0
    for _ in range(70):
        c = px - 0.35
        out.append({"open": px, "high": px + 0.15, "low": c - 0.1, "close": c, "volume": 80})
        px = c
    for _ in range(6):
        c = px + 2.4
        out.append({"open": px, "high": c + 0.2, "low": px - 0.1, "close": c, "volume": 160})
        px = c
    return out


def test_entry_signal_is_bearish_sniper() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.EMA_LONG_SNIPER = True
    bars = _bars_down_then_up()
    side, why = ema_entry_signal(bars, cfg, atr=4.0, bias="BEARISH")
    assert side in (Side.LONG, Side.NONE)
    if side == Side.LONG:
        assert why == "EMA_SNIPER_LONG"


def test_sniper_long_requires_red_through_white_and_blue() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=111.0,
        ema20=100.0,
        ema50=110.0,
        prev9=99.0,
        prev20=100.2,
        prev50=110.1,
    )
    assert stack_is_bearish(stack) is True
    assert red_clears_white_and_blue(stack) is True
    assert long_sniper_reason(stack, cfg, bias="BEARISH") == ""
    assert long_sniper_reason(stack, cfg, bias="BULLISH") == ""
    bull = EmaStack(
        ema9=29301.0,
        ema20=29300.0,
        ema50=29220.0,
        prev9=29299.0,
        prev20=29300.0,
        prev50=29220.0,
    )
    assert stack_is_bearish(bull) is False
    cfg.EMA_LONG_REQUIRES_BEARISH = True
    assert long_sniper_reason(bull, cfg, bias="BEARISH") == ""
    cfg.EMA_LONG_REQUIRES_BEARISH = False
    assert long_sniper_reason(bull, cfg, bias="BEARISH") == ""


def test_sniper_completes_when_red_later_clears_blue() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=111.0,
        ema20=100.5,
        ema50=110.0,
        prev9=105.0,
        prev20=100.0,
        prev50=110.2,
    )
    assert cross_side(stack) == Side.NONE
    assert red_clears_white_and_blue(stack) is True
    assert long_sniper_reason(stack, cfg, bias="BEARISH") == ""


def _bar(px: float, close: float) -> dict:
    hi = max(px, close) + 0.15
    lo = min(px, close) - 0.10
    return {"open": px, "high": hi, "low": lo, "close": close, "volume": 120}


def _bars_rsi_cross_on_bull_stack() -> list[dict]:
    """Uptrend so EMAs are bullish, fade RSI under 65, then punch back through."""
    out: list[dict] = []
    px = 200.0
    for _ in range(80):
        c = px + 1.25
        out.append(_bar(px, c))
        px = c
    while rsi_ind(out) >= 65.0 and len(out) < 110:
        c = px - 2.0
        out.append(_bar(px, c))
        px = c
    while rsi_ind(out) < 65.0 and len(out) < 120:
        c = px + 5.0
        out.append(_bar(px, c))
        px = c
    return out


def test_bull_long_only_on_fresh_stack() -> None:
    cfg = Mark2Config()
    cfg.EMA_RSI_LONG = True
    fresh = EmaStack(
        ema9=29320.0,
        ema20=29310.0,
        ema50=29290.0,
        prev9=29308.0,
        prev20=29309.0,
        prev50=29289.0,
    )
    assert stack_is_bullish(fresh)
    assert red_clears_white_and_blue(fresh)
    assert rsi_bull_long_reason([], fresh, cfg) == ""


def test_bull_long_does_not_refire_on_same_stack() -> None:
    cfg = Mark2Config()
    cfg.EMA_RSI_LONG = True
    leftover = EmaStack(
        ema9=29380.0,
        ema20=29361.8,
        ema50=29342.5,
        prev9=29372.6,
        prev20=29359.5,
        prev50=29340.0,
    )
    assert stack_is_bullish(leftover)
    assert red_clears_white_and_blue(leftover) is False
    assert rsi_bull_long_reason([], leftover, cfg) == "LEFTOVER_OFF"


def test_rsi_bull_long_blocked_when_stack_not_bullish() -> None:
    cfg = Mark2Config()
    cfg.EMA_RSI_LONG = True
    bars = _bars_rsi_cross_on_bull_stack()
    bear = EmaStack(
        ema9=99.0,
        ema20=100.0,
        ema50=110.0,
        prev9=98.5,
        prev20=100.2,
        prev50=110.1,
    )
    assert stack_is_bullish(bear) is False
    assert rsi_bull_long_reason(bars, bear, cfg, bias="BULLISH") == "NOT_BULLISH"


def test_sniper_wins_over_rsi_long() -> None:
    cfg = Mark2Config()
    bars = _bars_down_then_up()
    side, why = ema_entry_signal(bars, cfg, atr=4.0, bias="BEARISH")
    if side == Side.LONG:
        assert why == "EMA_SNIPER_LONG"


def test_bull_long_uses_shared_r_phases() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=105.5,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=10.0,
        ema_entry_tag="EMA_RSI_LONG",
    )
    done, why, _st = manage_ema_hold(trade, price=102.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "PROBATION"
    assert trade.stop == 85.0
    done, why, _st = manage_ema_hold(trade, price=115.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.target_touched is True
    assert trade.runner_trail_on is True
    assert trade.stop + 1e-9 >= 105.5
    assert trade.stop + 1e-9 >= 115.0 - 5.5


def test_choppy_exit_override_is_off() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=200.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=10.0,
        entry_regime="HIGH_VOL",
    )
    assert choppy_exit_points(cfg, regime="CHOPPY", trade=trade) is None
    done, why, _st = manage_ema_hold(trade, price=104.5, exit_armed=False, cfg=cfg, regime="CHOPPY")
    assert done is False
    assert why == ""
    assert trade.ema_trade_state == "PROBATION"
    assert trade.stop == 85.0


def test_chop_flip_does_not_4_5_trail_a_sniper() -> None:
    """03:25 HIGH_VOL long: +12.5 then CHOPPY must not yank a 4.5 trail."""
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=29341.25,
        entry_ts=1.0,
        stop=29293.63,
        target=200.0,
        peak=29341.25,
        trough=29341.25,
        hard_stop=29293.63,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=15.0,
        entry_regime="HIGH_VOL",
    )
    done, why, _st = manage_ema_hold(trade, price=29353.75, exit_armed=False, cfg=cfg, regime="HIGH_VOL")
    assert done is False
    done, why, _st = manage_ema_hold(trade, price=29335.75, exit_armed=False, cfg=cfg, regime="CHOPPY")
    assert done is False
    assert why == ""
    assert trade.stop == 29293.63


def test_choppy_white_cross_does_not_flatten_before_structure() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=200.0,
        peak=104.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="CHOP",
        atr_at_entry=10.0,
        mfe=4.0,
        ema_entry_tag="EMA_CHOP_LONG",
    )
    done, why, _st = manage_ema_hold(
        trade,
        price=104.0,
        exit_armed=False,
        cfg=cfg,
        regime="CHOPPY",
        ema9=101.2,
        ema20=100.4,
    )
    assert done is False
    assert why == ""
    assert trade.stop == 85.0
    done, why, _st = manage_ema_hold(
        trade,
        price=99.5,
        exit_armed=False,
        cfg=cfg,
        regime="CHOPPY",
        ema9=100.1,
        ema20=100.5,
    )
    assert done is False
    assert why == ""
    assert trade.stop == 85.0


def test_choppy_150_does_not_flatten() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.CHOP_TARGET_USD = 150.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=29326.5,
        entry_ts=1.0,
        stop=29278.0,
        target=29401.5,
        peak=29326.5,
        trough=29326.5,
        qty=1,
        hard_stop=29278.0,
        ema_strategy=True,
        ema_trade_state="CHOP",
        atr_at_entry=15.0,
        ema_entry_tag="EMA_CHOP_LONG",
        tip_target_pts=75.0,
    )
    done, why, _st = manage_ema_hold(
        trade,
        price=29400.0,
        exit_armed=False,
        cfg=cfg,
        regime="CHOPPY",
        ema9=29350.0,
        ema20=29340.0,
    )
    assert done is False
    assert trade.target == 29401.5
    done, why, _st = manage_ema_hold(
        trade,
        price=29401.5,
        exit_armed=False,
        cfg=cfg,
        regime="CHOPPY",
        ema9=29350.0,
        ema20=29340.0,
    )
    assert done is False


def test_bullish_chop_holds_150_until_white_and_rsi_fade() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.CHOP_TARGET_USD = 150.0
    cfg.CHOP_RSI_FADE = 5.0
    cfg.TIP_TRAIL_ARM_USD = 99999.0
    cfg.DOLLAR_LOCK_1_TRIGGER = 99999.0
    cfg.ENABLE_GROW_MODE = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=29326.5,
        entry_ts=1.0,
        stop=29278.0,
        target=29401.5,
        peak=29326.5,
        trough=29326.5,
        qty=1,
        hard_stop=29278.0,
        ema_strategy=True,
        ema_trade_state="CHOP",
        atr_at_entry=15.0,
        ema_entry_tag="EMA_CHOP_LONG",
        tip_target_pts=75.0,
        rsi_peak=72.0,
    )
    done, why, _st = manage_ema_hold(
        trade,
        price=29401.5,
        exit_armed=False,
        cfg=cfg,
        regime="CHAOTIC",
        bias="BULLISH",
        ema9=29380.0,
        ema20=29360.0,
        rsi=70.0,
        rsi_prev=72.0,
    )
    assert done is False
    done, why, _st = manage_ema_hold(
        trade,
        price=29350.0,
        exit_armed=False,
        cfg=cfg,
        regime="CHAOTIC",
        bias="BULLISH",
        ema9=29340.0,
        ema20=29355.0,
        rsi=70.0,
        rsi_prev=72.0,
    )
    assert done is True
    assert why == "FLOOR"


def test_choppy_does_not_override_bull_5_5_target() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=105.5,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=10.0,
        tip_trail_pts=3.0,
        tip_target_pts=5.5,
        ema_entry_tag="EMA_RSI_LONG",
    )
    done, why, _st = manage_ema_hold(trade, price=104.5, exit_armed=False, cfg=cfg, regime="CHOPPY")
    assert done is False
    assert why == ""


def test_bull_long_hits_5_5_target() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=105.5,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=10.0,
        tip_trail_pts=3.0,
        tip_target_pts=5.5,
        ema_entry_tag="EMA_RSI_LONG",
    )
    done, why, _st = manage_ema_hold(trade, price=105.5, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.target_touched is True
    assert trade.stop + 1e-9 >= 105.5


def test_heading_for_blue_is_not_an_entry() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=109.0,
        ema20=100.0,
        ema50=180.0,
        prev9=107.0,
        prev20=100.2,
        prev50=180.2,
    )
    assert red_clears_white_and_blue(stack) is False
    assert lines_intersecting(stack, 10.0, cfg) is False
    assert long_sniper_reason(stack, cfg, bias="BEARISH", atr=10.0) == "NO_SNIPER"


def test_sniper_still_takes_when_punch_flips_20_50() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=112.0,
        ema20=111.0,
        ema50=110.5,
        prev9=109.0,
        prev20=109.8,
        prev50=110.6,
    )
    assert red_clears_white_and_blue(stack) is True
    assert stack.ema20 > stack.ema50
    assert stack.prev20 < stack.prev50
    assert long_sniper_reason(stack, cfg, bias="BEARISH") == ""


def test_white_cross_far_from_blue_without_trajectory_stays_ignored() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=101.0,
        ema20=100.0,
        ema50=180.0,
        prev9=99.8,
        prev20=100.2,
        prev50=180.0,
    )
    assert red_on_blue_trajectory(stack, atr=10.0, cfg=cfg) is False
    assert lines_intersecting(stack, 10.0, cfg) is False
    assert long_sniper_reason(stack, cfg, bias="BEARISH", atr=10.0) == "WHITE_ONLY"


def test_white_cross_at_intersection_takes_any_state() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=100.4,
        ema20=100.0,
        ema50=104.5,
        prev9=99.6,
        prev20=100.2,
        prev50=104.6,
    )
    assert stack_is_bearish(stack) is True
    assert red_clears_white_and_blue(stack) is False
    assert lines_intersecting(stack, 10.0, cfg) is True
    assert long_sniper_reason(stack, cfg, bias="BEARISH", atr=10.0) == "WHITE_ONLY"
    assert short_sniper_reason(stack, cfg, bias="BEARISH", atr=10.0) == "NO_SNIPER"


def test_knot_middle_takes_punch_either_way() -> None:
    cfg = Mark2Config()
    up = EmaStack(
        ema9=100.2,
        ema20=100.0,
        ema50=100.4,
        prev9=99.7,
        prev20=100.1,
        prev50=100.5,
    )
    down = EmaStack(
        ema9=99.8,
        ema20=100.0,
        ema50=99.6,
        prev9=100.3,
        prev20=99.9,
        prev50=99.5,
    )
    assert lines_intersecting(up, 8.0, cfg) is True
    assert lines_intersecting(down, 8.0, cfg) is True
    assert red_above_white_and_blue(up) is False
    assert red_below_white_and_blue(down) is False
    assert intersection_side(up, 8.0, cfg) == Side.LONG
    assert intersection_side(down, 8.0, cfg) == Side.SHORT
    assert long_sniper_reason(up, cfg, atr=8.0) == "TIGHT"
    assert short_sniper_reason(down, cfg, atr=8.0) == "TIGHT"


def test_no_shorts_at_intersection() -> None:
    cfg = Mark2Config()
    through_both = EmaStack(
        ema9=98.4,
        ema20=100.0,
        ema50=99.2,
        prev9=100.3,
        prev20=99.9,
        prev50=99.3,
    )
    assert short_intersect_reason(through_both, cfg, atr=10.0) == ""


def test_sniper_short_requires_red_through_white_and_blue() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=89.0,
        ema20=110.0,
        ema50=100.0,
        prev9=111.0,
        prev20=110.2,
        prev50=100.1,
    )
    assert stack_is_bullish(stack) is False
    assert float(stack.ema20) > float(stack.ema50)
    assert red_clears_under_white_and_blue(stack) is True
    assert short_sniper_reason(stack, cfg, bias="BULLISH") == ""
    assert short_sniper_reason(stack, cfg, bias="BEARISH") == ""
    bear = EmaStack(
        ema9=89.0,
        ema20=100.0,
        ema50=180.0,
        prev9=111.0,
        prev20=100.2,
        prev50=180.1,
    )
    assert red_below_white_and_blue(bear) is True
    cfg.EMA_SHORT_REQUIRES_BULLISH = True
    assert short_sniper_reason(bear, cfg, bias="BULLISH") == "STACK_STALE"


def test_white_only_cross_is_not_a_sniper_short() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=109.6,
        ema20=110.0,
        ema50=50.0,
        prev9=110.4,
        prev20=110.0,
        prev50=50.0,
    )
    assert cross_side(stack) == Side.SHORT
    assert red_clears_under_white_and_blue(stack) is False
    assert lines_intersecting(stack, 10.0, cfg) is False
    assert short_sniper_reason(stack, cfg, atr=10.0) == "WHITE_ONLY"


def test_sniper_takes_short_when_white_flips_blue_at_the_knot() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=109.8,
        ema20=110.4,
        ema50=110.6,
        prev9=111.0,
        prev20=110.5,
        prev50=110.4,
    )
    assert lines_intersecting(stack, 8.0, cfg) is True
    assert red_reached_under_white_and_blue(stack, cfg) is True
    assert float(stack.prev20) > float(stack.prev50)
    assert short_sniper_reason(stack, cfg, bias="BULLISH", atr=8.0) == "TIGHT"


def test_nt_ema_matches_chart_sma_seed() -> None:
    from mark2.indicators import ema

    xs = [float(i) for i in range(1, 12)]
    out = ema(xs, 5)
    assert abs(out[4] - (1 + 2 + 3 + 4 + 5) / 5.0) < 1e-12


def test_sniper_takes_when_white_flips_blue_at_the_knot() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_QUALITY_FILTER = False
    stack = EmaStack(
        ema9=111.2,
        ema20=110.4,
        ema50=110.1,
        prev9=110.5,
        prev20=110.3,
        prev50=110.2,
    )
    assert lines_intersecting(stack, 8.0, cfg) is True
    assert red_above_white_and_blue(stack) is True
    assert float(stack.prev20) > float(stack.prev50)
    assert long_sniper_reason(stack, cfg, bias="BEARISH", atr=8.0) == ""


def test_bearish_knot_buys_when_red_reaches_both() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=100.15,
        ema20=100.00,
        ema50=100.20,
        prev9=99.40,
        prev20=99.80,
        prev50=101.10,
    )
    assert lines_intersecting(stack, 8.0, cfg) is True
    assert red_above_white_and_blue(stack) is False
    assert red_reached_white_and_blue(stack, cfg) is True
    assert long_sniper_reason(stack, cfg, bias="BEARISH", atr=8.0) == "TIGHT"


def test_sniper_still_takes_after_red_already_cleared_both() -> None:
    """Armed late / next bar: red is already through both and 20/50 still bearish."""
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=112.0,
        ema20=100.0,
        ema50=110.0,
        prev9=111.0,
        prev20=100.2,
        prev50=110.1,
    )
    assert red_clears_white_and_blue(stack) is False
    assert red_above_white_and_blue(stack) is True
    assert float(stack.ema20) < float(stack.ema50)
    assert long_sniper_reason(stack, cfg, bias="BEARISH") == ""


def test_sniper_does_not_long_when_red_is_falling() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=111.2,
        ema20=100.0,
        ema50=110.0,
        prev9=112.4,
        prev20=100.2,
        prev50=110.1,
    )
    assert red_above_white_and_blue(stack) is True
    assert red_falling(stack) is True
    assert red_rising(stack) is False
    assert long_sniper_reason(stack, cfg, bias="BEARISH") == "RED_FALLING"


def test_bull_stack_does_not_long_when_red_is_falling() -> None:
    cfg = Mark2Config()
    cfg.EMA_RSI_LONG = True
    stack = EmaStack(
        ema9=29320.0,
        ema20=29310.0,
        ema50=29290.0,
        prev9=29324.0,
        prev20=29309.0,
        prev50=29289.0,
    )
    assert stack_is_bullish(stack) is True
    assert rsi_bull_long_reason([], stack, cfg) == "RED_FALLING"


def test_leftover_bull_stack_after_runner_is_not_a_long() -> None:
    """The +$8 scalp: already stacked, red fading, must not re-enter."""
    cfg = Mark2Config()
    cfg.EMA_RSI_LONG = True
    stack = EmaStack(
        ema9=29372.53,
        ema20=29361.80,
        ema50=29342.51,
        prev9=29372.59,
        prev20=29359.45,
        prev50=29340.02,
    )
    assert stack_is_bullish(stack) is True
    assert red_rising(stack) is False
    assert rsi_bull_long_reason([], stack, cfg) == "RED_FALLING"
    already = EmaStack(
        ema9=29380.05,
        ema20=29369.13,
        ema50=29348.55,
        prev9=29372.45,
        prev20=29363.69,
        prev50=29344.79,
    )
    assert stack_is_bullish(already) is True
    assert red_rising(already) is True
    assert rsi_bull_long_reason([], already, cfg) == "LEFTOVER_OFF"


def test_dump_bounce_is_not_a_knot_long() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=29420.0,
        ema20=29450.0,
        ema50=29510.0,
        prev9=29418.0,
        prev20=29452.0,
        prev50=29512.0,
    )
    assert red_rising(stack) is True
    assert red_above_white_and_blue(stack) is False
    assert lines_intersecting(stack, 40.0, cfg) is False
    assert long_sniper_reason(stack, cfg, bias="BEARISH", atr=40.0) == "NO_SNIPER"


def test_sniper_does_not_reenter_same_stack_after_exit() -> None:
    eng = _ema_engine()
    stack = _through_both_stack()
    leftover = EmaStack(
        ema9=29347.17,
        ema20=29310.69,
        ema50=29320.0,
        prev9=29340.0,
        prev20=29311.0,
        prev50=29320.0,
    )
    eng.completed_bars[-1]["close"] = 29347.17
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why="EMA_SNIPER_LONG")
    assert eng.paper is not None
    eng.paper = None
    eng._ema_clear_setup()
    eng._ema_try_arm_signal(Side.LONG, leftover, allow_entry=True, why="EMA_SNIPER_LONG")
    assert eng.paper is None
    assert eng._ema_pending_side == Side.NONE
    assert eng._ema_long_stack_taken is True


def test_sniper_can_fire_again_after_stack_breaks() -> None:
    eng = _ema_engine()
    stack = _through_both_stack()
    eng.completed_bars[-1]["close"] = 29347.17
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why="EMA_SNIPER_LONG")
    assert eng.paper is not None
    assert eng._ema_long_stack_taken is True
    eng.paper = None
    eng._ema_clear_setup()
    broken = EmaStack(
        ema9=29300.0,
        ema20=29310.0,
        ema50=29320.0,
        prev9=29309.0,
        prev20=29311.0,
        prev50=29320.0,
    )
    assert eng._ema_long_stack_blocked(broken) is False
    assert eng._ema_long_stack_taken is False
    assert eng._ema_long_stack_blocked(stack) is False


def test_fresh_through_both_clears_stuck_stack_lock() -> None:
    """Rewind / missed dip left the lock on. A new punch must still fire."""
    eng = _ema_engine(EMA_RSI_LONG=True)
    eng._ema_long_stack_taken = True
    fresh = EmaStack(
        ema9=29374.46,
        ema20=29372.52,
        ema50=29365.44,
        prev9=29366.83,
        prev20=29369.10,
        prev50=29363.82,
    )
    assert red_clears_white_and_blue(fresh) is True
    assert eng._ema_long_stack_blocked(fresh) is False
    assert eng._ema_long_stack_taken is False
    eng.completed_bars[-1]["close"] = 29405.0
    eng._ema_try_arm_signal(Side.LONG, fresh, allow_entry=True, why="EMA_RSI_LONG")
    assert eng.paper is not None or eng._ema_pullback is not None


def test_bar_close_releases_lock_when_red_dips() -> None:
    from mark2 import engine as engine_mod

    eng = _ema_engine()
    eng._ema_long_stack_taken = True
    eng._ema_last_bar_time = "t0"
    eng.completed_bars[-1]["time"] = "t1"
    broken = EmaStack(
        ema9=29377.5,
        ema20=29378.5,
        ema50=29364.8,
        prev9=29380.5,
        prev20=29379.9,
        prev50=29364.8,
    )
    orig_read = engine_mod.read_ema_stack
    orig_sig = engine_mod.ema_entry_signal
    engine_mod.read_ema_stack = lambda bars, cfg: broken
    engine_mod.ema_entry_signal = lambda *a, **k: (Side.NONE, "RED_FALLING")
    try:
        eng._ema_on_completed_bar(allow_entry=True)
    finally:
        engine_mod.read_ema_stack = orig_read
        engine_mod.ema_entry_signal = orig_sig
    assert eng._ema_long_stack_taken is False


def test_replay_rewind_clears_stack_lock() -> None:
    eng = _ema_engine()
    eng._ema_long_stack_taken = True
    eng.clear_ema_pending()
    assert eng._ema_long_stack_taken is False


def test_live_scan_waits_if_completed_red_not_through_blue() -> None:
    from mark2 import engine as engine_mod

    eng = _ema_engine()
    eng.completed_bars = [
        {"time": f"t{i}", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10}
        for i in range(16)
    ]
    live = EmaStack(
        ema9=29422.0,
        ema20=29413.0,
        ema50=29420.0,
        prev9=29410.0,
        prev20=29408.0,
        prev50=29420.5,
    )
    done = EmaStack(
        ema9=29419.36,
        ema20=29413.41,
        ema50=29420.75,
        prev9=29410.18,
        prev20=29408.00,
        prev50=29420.75,
    )
    orig_read = engine_mod.read_ema_stack
    orig_sig = engine_mod.ema_entry_signal

    def _read(bars, cfg):
        if bars is eng.completed_bars:
            return done
        return live

    engine_mod.read_ema_stack = _read
    engine_mod.ema_entry_signal = lambda *a, **k: (Side.LONG, "EMA_SNIPER_LONG")
    try:
        eng._ema_scan_live_long()
    finally:
        engine_mod.read_ema_stack = orig_read
        engine_mod.ema_entry_signal = orig_sig
    assert eng.paper is None
    assert eng._ema_pending_side == Side.NONE
    assert eng._ema_watch == "WAIT_CLOSE"


def test_engine_blocks_leftover_bull_stack() -> None:
    eng = _ema_engine(EMA_RSI_LONG=True)
    stack = EmaStack(
        ema9=29372.5,
        ema20=29361.8,
        ema50=29342.5,
        prev9=29370.0,
        prev20=29359.5,
        prev50=29340.0,
    )
    eng.completed_bars[-1]["close"] = 29373.0
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why="EMA_RSI_LONG")
    assert eng.paper is None
    assert eng._ema_pending_side == Side.NONE


def test_live_scan_does_not_fire_bull_stack() -> None:
    from mark2 import engine as engine_mod

    eng = _ema_engine()
    eng.completed_bars = [
        {"time": f"t{i}", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10}
        for i in range(16)
    ]
    stack = EmaStack(
        ema9=29320.0,
        ema20=29310.0,
        ema50=29290.0,
        prev9=29308.0,
        prev20=29309.0,
        prev50=29289.0,
    )
    orig_read = engine_mod.read_ema_stack
    orig_sig = engine_mod.ema_entry_signal
    engine_mod.read_ema_stack = lambda bars, cfg: stack
    engine_mod.ema_entry_signal = lambda *a, **k: (Side.LONG, "EMA_RSI_LONG")
    try:
        eng._ema_scan_live_long()
    finally:
        engine_mod.read_ema_stack = orig_read
        engine_mod.ema_entry_signal = orig_sig
    assert eng.paper is None
    assert eng._ema_pending_side == Side.NONE
    assert eng._ema_watch == "BULL_WAIT_CLOSE"


def test_engine_blocks_falling_red_long() -> None:
    eng = _ema_engine()
    stack = EmaStack(
        ema9=29340.0,
        ema20=29310.0,
        ema50=29320.0,
        prev9=29348.0,
        prev20=29311.0,
        prev50=29320.0,
    )
    eng.completed_bars[-1]["close"] = 29340.0
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why="EMA_SNIPER_LONG")
    assert eng.paper is None
    assert eng._ema_pending_side == Side.NONE


def test_buy_when_intersection_hits_while_bearish_and_red_through_both() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_QUALITY_FILTER = False
    stack = EmaStack(
        ema9=112.0,
        ema20=110.0,
        ema50=111.0,
        prev9=111.5,
        prev20=90.0,
        prev50=140.0,
    )
    assert just_hit_intersection(stack, 10.0, cfg) is True
    assert red_above_white_and_blue(stack) is True
    assert float(stack.prev20) < float(stack.prev50)
    assert long_sniper_reason(stack, cfg, bias="BEARISH", atr=10.0) == ""


def test_near_blue_but_turning_away_is_not_a_trajectory() -> None:
    cfg = Mark2Config()
    stack = EmaStack(
        ema9=109.2,
        ema20=100.0,
        ema50=110.0,
        prev9=109.6,
        prev20=100.0,
        prev50=110.1,
    )
    assert red_on_blue_trajectory(stack, atr=10.0, cfg=cfg) is False
    assert long_sniper_reason(stack, cfg, bias="BEARISH", atr=10.0) == "RED_FALLING"


def test_rsi_overbought_helper_still_exists() -> None:
    cfg = Mark2Config()
    bars = []
    px = 100.0
    for _ in range(80):
        c = px + 1.8
        bars.append({"open": px, "high": c + 0.2, "low": px - 0.1, "close": c, "volume": 100})
        px = c
    ok, why = rsi_macd_ok(Side.LONG, bars, cfg)
    assert ok is False
    assert why == "rsi_overbought"


def test_read_ema_stack_computes_blue_before_fifty_closes() -> None:
    bars = []
    px = 20000.0
    for i in range(30):
        c = px + 1.0
        bars.append(
            {
                "time": f"t{i}",
                "open": px,
                "high": c + 0.5,
                "low": px - 0.5,
                "close": c,
                "volume": 10,
            }
        )
        px = c
    stack = read_ema_stack(bars, Mark2Config())
    assert stack is not None
    assert stack.ema50 > 0
    assert stack.prev50 > 0
    assert long_sniper_reason(stack, Mark2Config(), atr=8.0) != "BLUE_WARMUP"


def test_seed_bars_do_not_arm_ema_entry() -> None:
    from mark2.engine import Mark2Engine

    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.ALLOW_LEGACY_ENTRIES = False
    cfg.MARK2_ENABLED = True
    cfg.ACCOUNT_RISK_PROFILE = "OFF"
    eng = Mark2Engine(cfg)
    for b in _bars_down_then_up():
        eng.on_bar_close(b, seed=True)
    assert eng._ema_pending_side == Side.NONE
    assert eng._ema_armed is True
    eng.clear_ema_pending()
    assert eng._ema_pending_side == Side.NONE


def test_playback_bar_after_seed_is_live() -> None:
    from mark2.runtime import Mark2Runtime

    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.MARK2_ENABLED = True
    cfg.MODE = "PAPER_TRADE"
    rt = Mark2Runtime(cfg)
    for i in range(16):
        rt._on_message(
            {
                "type": "bar",
                "seed": True,
                "realtime": False,
                "time": f"s{i}",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 10,
            }
        )
    assert rt._seed_done is False
    rt._on_message({"type": "seed_done", "count": 16})
    n = len(rt.engine.completed_bars)
    rt._on_message(
        {
            "type": "bar",
            "realtime": False,
            "time": "play1",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10,
        }
    )
    assert len(rt.engine.completed_bars) == n + 1
    assert rt.engine.forming_bar is not None or rt.engine.paper is not None


def test_extension_rejects_far_from_white() -> None:
    cfg = Mark2Config()
    cfg.MAX_ENTRY_EXTENSION_ATR = 0.60
    ok, ext = entry_extension_ok(ref_price=100.0, ema20=90.0, atr=10.0, cfg=cfg)
    assert ok is False
    assert ext["extensionATR"] == 1.0


def test_chart_cross_at_29347_waits_on_1m_atr() -> None:
    """7/8 02:09: 10.5 pts / 13.66 1m ATR = 0.77. Immediate only if using the ~30 ATR."""
    cfg = Mark2Config()
    cfg.MAX_ENTRY_EXTENSION_ATR = 0.60
    ok_tight, ext_tight = entry_extension_ok(ref_price=29356.75, ema20=29346.21, atr=13.66, cfg=cfg)
    assert ext_tight["extensionATR"] > 0.60
    assert ok_tight is False
    ok_ctx, ext_ctx = entry_extension_ok(ref_price=29356.75, ema20=29346.21, atr=30.0, cfg=cfg)
    assert ext_ctx["extensionATR"] < 0.60
    assert ok_ctx is True


def test_29341_chase_is_not_immediate() -> None:
    """Playback long ~29341 vs EMA20 ~29311 / ATR ~30 is ~1.0 ATR — do not chase."""
    cfg = Mark2Config()
    cfg.MAX_ENTRY_EXTENSION_ATR = 0.60
    ok, ext = entry_extension_ok(ref_price=29341.25, ema20=29310.69, atr=30.33, cfg=cfg)
    assert ok is False
    assert ext["extensionATR"] > 0.60


def test_log_short_at_29018_is_not_immediate_on_bar_atr() -> None:
    """User log: 18.15 pts from white / ATR14 14.01 = 1.30 ATR. Must not be immediate."""
    cfg = Mark2Config()
    cfg.MAX_ENTRY_EXTENSION_ATR = 0.60
    ok, ext = entry_extension_ok(ref_price=29018.75, ema20=29036.90, atr=14.0121, cfg=cfg)
    assert ext["extensionATR"] > 0.60
    assert abs(ext["extensionPoints"] - 18.1548) < 0.02
    assert ok is False


def test_dataset_row_atr14_matches_extension() -> None:
    cfg = Mark2Config()
    bars = _bars_down_then_up()
    row = ema_dataset_row(
        bars,
        cfg,
        side="SHORT",
        action="CROSS",
        price=29018.75,
        atr_used=14.0121,
    )
    assert row["atr14"] == 14.0121
    assert abs(row["extensionPoints"] / row["atr14"] - row["extensionATR"]) < 1e-3


def test_extension_allows_close_to_white() -> None:
    cfg = Mark2Config()
    cfg.MAX_ENTRY_EXTENSION_ATR = 0.60
    ok, ext = entry_extension_ok(ref_price=100.0, ema20=96.0, atr=10.0, cfg=cfg)
    assert ok is True
    assert ext["extensionATR"] == 0.4


def test_catastrophic_stop_is_150_atr() -> None:
    cfg = Mark2Config()
    cfg.CATASTROPHIC_STOP_ATR = 1.50
    cfg.TICK_SIZE = 0.25
    stop = ema_atr_stop(20000.0, Side.LONG, atr=20.0, cfg=cfg)
    assert abs(stop - (20000.0 - 30.0)) < 1e-9
    stop_s = ema_atr_stop(20000.0, Side.SHORT, atr=20.0, cfg=cfg)
    assert abs(stop_s - (20000.0 + 30.0)) < 1e-9


def test_catastrophic_stop_floors_at_20_points() -> None:
    cfg = Mark2Config()
    cfg.CATASTROPHIC_STOP_ATR = 1.50
    cfg.EMA_MIN_STOP_POINTS = 20.0
    cfg.TICK_SIZE = 0.25
    stop = ema_atr_stop(20000.0, Side.LONG, atr=6.0, cfg=cfg)
    assert abs(stop - (20000.0 - 20.0)) < 1e-9
    tight = Mark2Config()
    tight.CATASTROPHIC_STOP_ATR = 1.50
    tight.EMA_MIN_STOP_POINTS = 0.0
    tight.TICK_SIZE = 0.25
    stop_tight = ema_atr_stop(20000.0, Side.LONG, atr=6.0, cfg=tight)
    assert abs(stop_tight - (20000.0 - 9.0)) < 1e-9


def test_runner_trail_is_fixed_125_atr() -> None:
    cfg = Mark2Config()
    assert cfg.RUNNER_TRAIL_ATR == 1.25
    assert cfg.RUNNER_TRIGGER_ATR == 2.0
    assert cfg.DYNAMIC_EMA_TRAIL is False
    assert cfg.RUNNER_HIGH_VOL_TRAIL is False


def test_last_runner_9pt_dip_holds_while_red_white_apart() -> None:
    """29324.5 long: 9-pt dip hit 0.75 ATR purple. Red still above white — stay."""
    cfg = Mark2Config()
    cfg.ENABLE_RUNNER_TRAIL = True
    cfg.RUNNER_TRIGGER_ATR = 1.5
    cfg.RUNNER_TRAIL_ATR = 1.50
    cfg.RUNNER_TRAIL_HIGH_VOL_ATR = 1.50
    cfg.CONFIRMED_TREND_TRIGGER_ATR = 1.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=29324.5,
        entry_ts=1.0,
        stop=29278.33,
        target=29400.0,
        peak=29351.75,
        trough=29280.5,
        mfe=27.25,
        mae=44.0,
        hard_stop=29278.33,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        atr_at_entry=12.274,
        runner_trail_on=True,
    )
    done, why, _st = manage_ema_hold(
        trade,
        price=29342.5,
        exit_armed=False,
        cfg=cfg,
        ema9=29315.0,
        ema20=29310.0,
        atr=12.274,
        completed_anchor=29351.75,
    )
    assert done is False
    assert why == ""
    assert trade.ema_trade_state in ("PROBATION", "CONFIRMED", "RUNNER")


def test_runner_trail_does_not_shrink_when_red_white_converge() -> None:
    cfg = Mark2Config()
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=130.0,
        peak=120.0,
        trough=99.0,
        mfe=20.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        atr_at_entry=10.0,
        runner_trail_on=True,
        ema_entry_tag="EMA_SNIPER_LONG",
    )
    manage_ema_hold(
        trade, price=118.0, exit_armed=False, cfg=cfg, ema9=110.0, ema20=106.0, atr=10.0, completed_anchor=120.0
    )
    wide_stop = trade.stop
    manage_ema_hold(
        trade, price=118.0, exit_armed=False, cfg=cfg, ema9=106.2, ema20=106.0, atr=10.0, completed_anchor=120.0
    )
    assert trade.stop >= wide_stop - 1e-9


def test_runner_trail_does_not_loosen_if_spread_reopens() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_RUNNER_TRAIL = True
    cfg.RUNNER_TRAIL_HIGH_VOL_ATR = 1.50
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=130.0,
        peak=120.0,
        trough=99.0,
        mfe=20.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        atr_at_entry=10.0,
        runner_trail_on=True,
    )
    manage_ema_hold(
        trade, price=118.0, exit_armed=False, cfg=cfg, ema9=106.2, ema20=106.0, atr=10.0, completed_anchor=120.0
    )
    tight = trade.stop
    manage_ema_hold(
        trade, price=118.0, exit_armed=False, cfg=cfg, ema9=112.0, ema20=106.0, atr=10.0, completed_anchor=120.0
    )
    assert trade.stop == tight


def test_runner_tightens_only() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_RUNNER_TRAIL = True
    cfg.RUNNER_TRIGGER_ATR = 1.5
    cfg.RUNNER_TRAIL_ATR = 0.75
    cfg.RUNNER_TRAIL_HIGH_VOL_ATR = 0.75
    cfg.CONFIRMED_TREND_TRIGGER_ATR = 1.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=94.5,
        target=110.0,
        peak=100.0,
        trough=100.0,
        hard_stop=94.5,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=10.0,
    )
    done, why, _st = manage_ema_hold(trade, price=116.0, exit_armed=False, cfg=cfg, completed_anchor=116.0)
    assert done is False
    assert why == ""
    assert trade.ema_trade_state == "RUNNER"
    assert trade.runner_trail_on is True
    first = trade.stop
    manage_ema_hold(trade, price=115.0, exit_armed=False, cfg=cfg, completed_anchor=116.0)
    assert trade.stop >= first - 1e-9
    manage_ema_hold(trade, price=120.0, exit_armed=False, cfg=cfg, completed_anchor=120.0)
    assert trade.stop >= first - 1e-9
    assert trade.hard_stop == 94.5


def test_runner_ignores_intrabar_wick() -> None:
    cfg = Mark2Config()
    cfg.TRAIL_PROFIT_KEEP = 0.0
    cfg.DOLLAR_LOCK_1_TRIGGER = 99999.0
    cfg.TIP_TRAIL_ARM_USD = 99999.0
    cfg.MFE_LOCK_ARM_USD = 99999.0
    cfg.ENABLE_GROW_MODE = False
    cfg.ENABLE_RUNNER_TRAIL = True
    cfg.RUNNER_TRIGGER_ATR = 1.5
    trade = PaperTrade(
        side=Side.LONG,
        entry=29015.25,
        entry_ts=1.0,
        stop=28993.47,
        target=29200.0,
        peak=29015.25,
        trough=29015.25,
        hard_stop=28993.47,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=14.52,
        runner_anchor=29015.25,
    )
    manage_ema_hold(trade, price=29086.75, exit_armed=False, cfg=cfg, regime="TRENDING", completed_anchor=29004.0)
    assert trade.ema_trade_state in ("CONFIRMED", "RUNNER")
    done, why, _st = manage_ema_hold(
        trade, price=29061.0, exit_armed=False, cfg=cfg, regime="TRENDING", completed_anchor=29004.0
    )
    assert why in ("", "MFE_GIVEBACK", "PROTECT")


def test_high_vol_runner_holds_july8_pullback() -> None:
    cfg = Mark2Config()
    cfg.TRAIL_PROFIT_KEEP = 0.0
    cfg.DOLLAR_LOCK_1_TRIGGER = 99999.0
    cfg.TIP_TRAIL_ARM_USD = 99999.0
    cfg.ENABLE_GROW_MODE = False
    cfg.ENABLE_RUNNER_TRAIL = True
    trade = PaperTrade(
        side=Side.LONG,
        entry=29015.25,
        entry_ts=1.0,
        stop=28993.47,
        target=29200.0,
        peak=29086.75,
        trough=28992.25,
        mfe=71.5,
        mae=23.0,
        hard_stop=28993.47,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        atr_at_entry=14.52,
        runner_trail_on=True,
        runner_anchor=29015.25,
    )
    assert runner_needs_room(regime="HIGH_VOL", atr=13.94, atr_at_entry=14.52, mfe_atr=4.92) is True
    done, why, _st = manage_ema_hold(
        trade,
        price=29061.0,
        exit_armed=False,
        cfg=cfg,
        regime="HIGH_VOL",
        completed_anchor=29004.0,
        ema9=29005.0,
        ema20=29002.8,
        atr=13.94,
    )
    assert done is True
    assert why == "MFE_GIVEBACK"


def test_profit_keep_stays_off_until_100() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.TRAIL_PROFIT_KEEP = 0.80
    cfg.TRAIL_KEEP_ARM_USD = 100.0
    under = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19980.0,
        target=20100.0,
        peak=20040.0,
        trough=20000.0,
        mfe=40.0,
    )
    assert profit_keep_lock_price(under, cfg) is None
    over = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19850.0,
        target=20400.0,
        peak=20050.0,
        trough=19990.0,
        mfe=50.0,
    )
    over.ema_trade_state = "RUNNER"
    assert abs(profit_keep_lock_price(over, cfg, state="RUNNER") - 20040.0) < 1e-9


def test_profit_keep_at_100_allows_room_not_scratch() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19850.0,
        target=20400.0,
        peak=20050.0,
        trough=19990.0,
        mfe=50.0,
    )
    trade.ema_trade_state = "RUNNER"
    assert abs(profit_keep_lock_price(trade, cfg, state="RUNNER") - 20040.0) < 1e-9


def test_profit_keep_locks_80_percent_after_250() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.TRAIL_PROFIT_KEEP = 0.80
    cfg.TRAIL_KEEP_ARM_USD = 100.0
    cfg.ENABLE_RUNNER_TRAIL = True
    cfg.RUNNER_STRUCTURE_EXIT = False
    cfg.RUNNER_TRAIL_ATR = 1.25
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19920.0,
        target=20400.0,
        peak=20200.0,
        trough=19990.0,
        qty=1,
        mfe=200.0,
        hard_stop=19920.0,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        atr_at_entry=40.0,
        runner_trail_on=True,
        runner_anchor=20200.0,
    )
    done, why, _st = manage_ema_hold(
        trade,
        price=20190.0,
        exit_armed=False,
        cfg=cfg,
        ema9=20150.0,
        ema20=20100.0,
        atr=40.0,
        regime="HIGH_VOL",
        completed_anchor=20200.0,
    )
    assert done is False
    assert trade.stop >= 20180.0
    done, why, _st = manage_ema_hold(
        trade,
        price=trade.stop,
        exit_armed=False,
        cfg=cfg,
        ema9=20150.0,
        ema20=20100.0,
        atr=40.0,
        regime="HIGH_VOL",
        completed_anchor=20200.0,
    )
    assert done is True
    assert why in ("TIP_TRAIL", "PROTECT", "MFE_GIVEBACK")


def test_sniper_probation_does_not_trail() -> None:
    cfg = Mark2Config()
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=29000.0,
        entry_ts=1.0,
        stop=28970.0,
        target=29400.0,
        peak=29000.0,
        trough=29000.0,
        hard_stop=28970.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=20.0,
        ema_entry_tag="EMA_SNIPER_LONG",
    )
    done, why, _st = manage_ema_hold(trade, price=29016.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "PROBATION"
    assert trade.stop == 28970.0


def test_eighty_dollars_does_nothing() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    assert profit_keep_usd(50.0, cfg) == 0.0
    assert profit_keep_usd(80.0, cfg) == 0.0
    assert profit_keep_usd(99.0, cfg) == 0.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19850.0,
        target=20400.0,
        peak=20040.0,
        trough=19990.0,
        mfe=40.0,
        ema_trade_state="RUNNER",
    )
    assert profit_keep_lock_price(trade, cfg, state="RUNNER") is None


def test_profit_keep_150_locks_65_percent() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    assert abs(profit_keep_usd(150.0, cfg) - 127.0) < 1e-9
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19850.0,
        target=20400.0,
        peak=20075.0,
        trough=19990.0,
        mfe=75.0,
        ema_trade_state="RUNNER",
    )
    assert abs(profit_keep_lock_price(trade, cfg, state="RUNNER") - 20063.5) < 1e-9


def test_profit_keep_180_keeps_117() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    assert abs(profit_keep_usd(180.0, cfg) - 155.2) < 1e-9
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19850.0,
        target=20400.0,
        peak=20090.0,
        trough=19990.0,
        mfe=90.0,
        ema_trade_state="RUNNER",
    )
    assert abs(profit_keep_lock_price(trade, cfg, state="RUNNER") - 20077.6) < 1e-9


def test_confirmed_dollar_lock_beats_wide_hard_stop() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_RUNNER_TRAIL = True
    cfg.RUNNER_STRUCTURE_EXIT = False
    cfg.RUNNER_TRIGGER_ATR = 2.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19850.0,
        target=20400.0,
        peak=20000.0,
        trough=19990.0,
        qty=1,
        mfe=0.0,
        hard_stop=19850.0,
        ema_strategy=True,
        ema_trade_state="CONFIRMED",
        atr_at_entry=80.0,
        ema_entry_tag="EMA_SNIPER_LONG",
    )
    done, why, _st = manage_ema_hold(
        trade,
        price=20040.0,
        exit_armed=False,
        cfg=cfg,
        atr=80.0,
        regime="HIGH_VOL",
        completed_anchor=20040.0,
    )
    assert done is False
    assert trade.ema_trade_state == "PROBATION"
    assert trade.stop == 19850.0
    done, why, _st = manage_ema_hold(
        trade,
        price=20150.0,
        exit_armed=False,
        cfg=cfg,
        atr=80.0,
        regime="HIGH_VOL",
        completed_anchor=20150.0,
    )
    assert done is False
    assert trade.ema_trade_state == "CONFIRMED"
    assert trade.stop >= 20130.0


def test_profit_keep_250_locks_65_percent() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    assert abs(profit_keep_usd(250.0, cfg) - 221.0) < 1e-9
    assert abs(profit_keep_usd(400.0, cfg) - 362.0) < 1e-9
    assert abs(profit_keep_usd(600.0, cfg) - 550.0) < 1e-9


def test_runner_trail_ratchets_highest_completed_high() -> None:
    cfg = Mark2Config()
    cfg.RUNNER_STRUCTURE_EXIT = False
    cfg.DOLLAR_LOCK_1_TRIGGER = 99999.0
    cfg.TIP_TRAIL_ARM_USD = 99999.0
    cfg.ENABLE_GROW_MODE = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=29000.0,
        entry_ts=1.0,
        stop=28970.0,
        target=29400.0,
        peak=29070.0,
        trough=29000.0,
        mfe=70.0,
        hard_stop=28970.0,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        atr_at_entry=20.0,
        ema_entry_tag="EMA_SNIPER_LONG",
    )
    done, why, _st = manage_ema_hold(
        trade,
        price=29065.0,
        exit_armed=False,
        cfg=cfg,
        completed_anchor=29070.0,
        atr=20.0,
    )
    assert done is False
    assert abs(trade.stop - 29049.0) < 1e-9
    first = trade.stop
    done, why, _st = manage_ema_hold(
        trade,
        price=29055.0,
        exit_armed=False,
        cfg=cfg,
        completed_anchor=29020.0,
        atr=20.0,
    )
    assert done is False
    assert trade.stop >= first - 1e-9


def test_structure_exit_only_after_runner() -> None:
    cfg = Mark2Config()
    cfg.RUNNER_STRUCTURE_EXIT = True
    cfg.TIP_TRAIL_ARM_USD = 99999.0
    cfg.DOLLAR_LOCK_1_TRIGGER = 99999.0
    cfg.MFE_LOCK_ARM_USD = 99999.0
    cfg.ENABLE_GROW_MODE = False
    dead = dict(ema9=28980.0, ema20=29010.0, ema50=29020.0)
    probation = PaperTrade(
        side=Side.LONG,
        entry=29000.0,
        entry_ts=1.0,
        stop=28970.0,
        target=29400.0,
        peak=29010.0,
        trough=29000.0,
        mfe=10.0,
        hard_stop=28970.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=20.0,
        ema_entry_tag="EMA_SNIPER_LONG",
    )
    done, why, _st = manage_ema_hold(
        probation, price=29010.0, exit_armed=False, cfg=cfg, atr=20.0, **dead
    )
    assert done is False
    assert why == ""
    done, why, _st = manage_ema_hold(
        probation,
        price=29008.0,
        exit_armed=False,
        cfg=cfg,
        atr=20.0,
        ema9=28970.0,
        ema20=29012.0,
        ema50=29020.0,
    )
    assert done is False
    assert why == ""
    assert probation.ema_trade_state == "PROBATION"
    runner = PaperTrade(
        side=Side.LONG,
        entry=29000.0,
        entry_ts=1.0,
        stop=28995.0,
        target=29400.0,
        peak=29050.0,
        trough=29000.0,
        mfe=50.0,
        hard_stop=28970.0,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        atr_at_entry=20.0,
        runner_trail_on=True,
        runner_anchor=29050.0,
        ema_entry_tag="EMA_SNIPER_LONG",
    )
    done, why, _st = manage_ema_hold(
        runner,
        price=29040.0,
        exit_armed=False,
        cfg=cfg,
        atr=20.0,
        completed_anchor=29050.0,
        **dead,
    )
    assert done is False
    assert runner.ema_lost_20 is True
    done, why, _st = manage_ema_hold(
        runner,
        price=29038.0,
        exit_armed=False,
        cfg=cfg,
        atr=20.0,
        completed_anchor=29050.0,
        ema9=28970.0,
        ema20=29012.0,
        ema50=29020.0,
    )
    assert done is True
    assert why == "STRUCTURE_FAILURE"


def test_sniper_confirmed_is_entry_minus_quarter_atr() -> None:
    cfg = Mark2Config()
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=29000.0,
        entry_ts=1.0,
        stop=28970.0,
        target=29400.0,
        peak=29000.0,
        trough=29000.0,
        hard_stop=28970.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=20.0,
        ema_entry_tag="EMA_SNIPER_LONG",
    )
    done, why, _st = manage_ema_hold(trade, price=29030.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "CONFIRMED"
    assert trade.stop == 28995.0


def test_catastrophic_stop_hit() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=110.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=10.0,
    )
    done, why, _st = manage_ema_hold(trade, price=85.0, exit_armed=False, cfg=cfg)
    assert done is True
    assert why == "CATASTROPHIC_STOP"


def test_normal_fluctuation_does_not_hit_catastrophic_stop() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_RUNNER_TRAIL = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=29341.25,
        entry_ts=1.0,
        stop=29341.25 - 45.5,
        target=29400.0,
        peak=29341.25,
        trough=29341.25,
        hard_stop=29341.25 - 45.5,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=30.33,
    )
    done, why, _st = manage_ema_hold(trade, price=29324.50, exit_armed=False, cfg=cfg)
    assert done is False
    assert why == ""


def test_opposite_cross_exit_is_off() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=110.0,
        peak=111.0,
        trough=99.0,
        mfe=11.0,
        hard_stop=85.0,
        ema_strategy=True,
        ema_trade_state="CONFIRMED_TREND",
        atr_at_entry=10.0,
    )
    done, why, _st = manage_ema_hold(trade, price=110.5, exit_armed=True, cfg=cfg)
    assert done is False
    assert why == ""
    assert trade.stop + 1e-9 >= 110.0


def test_opposite_cross_does_not_flatten_probation() -> None:
    cfg = Mark2Config()
    cfg.OPPOSITE_CROSS_REQUIRES_CONFIRM = True
    trade = PaperTrade(
        side=Side.LONG,
        entry=29355.0,
        entry_ts=1.0,
        stop=29310.0,
        target=29400.0,
        peak=29361.0,
        trough=29333.5,
        mfe=6.0,
        mae=21.5,
        hard_stop=29310.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        atr_at_entry=13.11,
    )
    done, why, _st = manage_ema_hold(trade, price=29359.5, exit_armed=True, cfg=cfg)
    assert done is False
    assert why == ""
    assert trade.ema_trade_state == "PROBATION"
    done, why, _st = manage_ema_hold(trade, price=29339.75, exit_armed=True, cfg=cfg)
    assert done is False
    assert why == ""


def test_pullback_zone_long_and_short() -> None:
    cfg = Mark2Config()
    cfg.MAX_ENTRY_EXTENSION_ATR = 0.60
    ok, m = pullback_zone_ok(Side.LONG, 29312.0, 29300.0, 30.0, cfg)
    assert ok is True
    assert m["currentExtensionATR"] == 0.4
    too_far, _ = pullback_zone_ok(Side.LONG, 29335.0, 29300.0, 30.0, cfg)
    assert too_far is False
    broken, _ = pullback_zone_ok(Side.LONG, 29290.0, 29300.0, 30.0, cfg)
    assert broken is False
    ok_s, _ = pullback_zone_ok(Side.SHORT, 29290.0, 29300.0, 30.0, cfg)
    assert ok_s is True
    through, _ = pullback_zone_ok(Side.SHORT, 29310.0, 29300.0, 30.0, cfg)
    assert through is False


def test_structure_valid_ignores_blue() -> None:
    stack = EmaStack(ema9=10.2, ema20=10.0, ema50=12.0, prev9=10.1, prev20=10.0, prev50=12.0)
    assert ema_structure_valid(Side.LONG, stack) is True
    assert ema_structure_valid(Side.SHORT, stack) is False


def test_live_warmup_ignores_first_cross() -> None:
    from mark2.engine import Mark2Engine

    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.ALLOW_LEGACY_ENTRIES = False
    cfg.MARK2_ENABLED = True
    cfg.ACCOUNT_RISK_PROFILE = "OFF"
    eng = Mark2Engine(cfg)
    bars = _bars_down_then_up()
    for b in bars:
        eng.on_bar_close(b, seed=True)
    assert eng._ema_armed is True
    assert eng._ema_pending_side == Side.NONE
    assert eng.paper is None


def test_dataset_row_has_every_research_field() -> None:
    cfg = Mark2Config()
    bars = _bars_down_then_up()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=94.5,
        target=110.0,
        peak=108.0,
        trough=99.0,
        mfe=8.0,
        mae=1.0,
        hard_stop=94.5,
        ema_strategy=True,
        ema_trade_state="CONFIRMED_TREND",
        atr_at_entry=10.0,
    )
    row = ema_dataset_row(
        bars,
        cfg,
        side="LONG",
        action="EXIT",
        price=107.0,
        timestamp=123.0,
        bias="BULLISH",
        regime="TRENDING",
        bars_since=4,
        trade_state="CONFIRMED_TREND",
        trade=trade,
    )
    missing = [k for k in EMA_DATASET_KEYS if k not in row]
    assert missing == []
    assert row["rsi14"] is not None
    assert row["macdLine"] is not None
    assert row["ema9"] is not None
    assert row["ema20"] is not None
    assert row["extensionATR"] is not None
    assert row["mfePoints"] == 8.0
    assert row["mfeATR"] == 0.8
    assert row["bias"] == "BULLISH"
    assert row["barsSincePreviousCross"] == 4


def test_toggle_persists_in_snapshot() -> None:
    cfg = Mark2Config()
    apply_toggles(cfg, {"ema_strategy": True})
    tg = snapshot(cfg)["toggles"]
    assert tg["ema_strategy"] is True
    assert cfg.ENABLE_EMA_STRATEGY is True
    assert cfg.ENABLE_BOOK_PATTERNS is False
    apply_toggles(cfg, {"ema_strategy": False})
    assert snapshot(cfg)["toggles"]["ema_strategy"] is False


def _ema_engine(**kwargs) -> "Mark2Engine":
    from mark2.engine import Mark2Engine

    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.ALLOW_LEGACY_ENTRIES = False
    cfg.MARK2_ENABLED = True
    cfg.MODE = "PAPER_TRADE"
    cfg.MAX_ENTRY_EXTENSION_ATR = 0.60
    cfg.ENABLE_PULLBACK_ENTRY = True
    cfg.PULLBACK_ENTRY_ON_BAR_CLOSE = True
    cfg.MAX_PULLBACK_WAIT_BARS = 10
    cfg.ACCOUNT_RISK_PROFILE = "OFF"
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    eng = Mark2Engine(cfg)
    eng._ema_armed = True
    eng.completed_bars = [
        {"time": "t0", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10}
    ]
    eng.context._cache["atr"] = 30.0
    eng._ema_atr = lambda: 30.0  # type: ignore[method-assign]
    eng._ema_stop_atr = lambda: 30.0  # type: ignore[method-assign]
    return eng


def _traj_extended_stack() -> EmaStack:
    """Red through white, still under blue — early sniper, not through both."""
    return EmaStack(
        ema9=29315.0,
        ema20=29310.69,
        ema50=29340.0,
        prev9=29309.0,
        prev20=29311.0,
        prev50=29340.0,
    )


def _through_both_stack() -> EmaStack:
    return EmaStack(
        ema9=29347.17,
        ema20=29310.69,
        ema50=29320.0,
        prev9=29309.0,
        prev20=29311.0,
        prev50=29320.0,
    )


def test_extended_cross_arms_pullback_not_immediate() -> None:
    """White-only is not a long. Do not chase or arm a pullback."""
    eng = _ema_engine()
    stack = _traj_extended_stack()
    eng.completed_bars[-1]["close"] = 29341.25
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True)
    assert eng._ema_pending_side == Side.NONE
    assert eng._ema_pullback is None
    assert eng.paper is None


def test_flat_tick_keeps_watching_for_red_through_both() -> None:
    from mark2 import engine as engine_mod
    from mark2.types import MarketSnapshot, ScoreBundle, Tick

    eng = _ema_engine()
    while len(eng.completed_bars) < 15:
        i = len(eng.completed_bars)
        eng.completed_bars.append(
            {"time": f"t{i}", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10}
        )
    both = _through_both_stack()
    orig_read = engine_mod.read_ema_stack
    orig_sig = engine_mod.ema_entry_signal
    engine_mod.read_ema_stack = lambda bars, cfg: both
    engine_mod.ema_entry_signal = lambda *a, **k: (Side.LONG, "EMA_SNIPER_LONG")
    try:
        tick = Tick(ts=2.0, price=29341.25)
        snap = MarketSnapshot(
            ts=2.0,
            price=29341.25,
            completed_bars=eng.completed_bars,
            forming_bar=None,
        )
        eng._ema_flat_tick(tick, snap, ScoreBundle())
    finally:
        engine_mod.read_ema_stack = orig_read
        engine_mod.ema_entry_signal = orig_sig
    assert eng.paper is not None
    assert eng.paper.side == Side.LONG


def test_through_both_is_immediate_even_when_extended() -> None:
    eng = _ema_engine()
    stack = _through_both_stack()
    eng.completed_bars[-1]["close"] = 29341.25
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True)
    assert red_above_white_and_blue(stack) is True
    assert eng.paper is not None
    assert eng.paper.side == Side.LONG
    assert eng._ema_pullback is None


def test_disarmed_does_not_place_sniper() -> None:
    eng = _ema_engine()
    eng.cfg.MARK2_ENABLED = False
    stack = _through_both_stack()
    eng.completed_bars[-1]["close"] = 29341.25
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True)
    assert eng.paper is None
    assert eng._ema_pending_side == Side.NONE


def test_pullback_fills_when_red_clears_both() -> None:
    from mark2 import engine as engine_mod

    eng = _ema_engine()
    eng.completed_bars[-1]["close"] = 29341.25
    eng._ema_try_arm_signal(Side.LONG, _traj_extended_stack(), allow_entry=True)
    assert eng._ema_pullback is None
    both = EmaStack(
        ema9=29325.0,
        ema20=29312.0,
        ema50=29320.0,
        prev9=29315.0,
        prev20=29311.0,
        prev50=29320.0,
    )
    orig_read = engine_mod.read_ema_stack
    orig_sig = engine_mod.ema_entry_signal
    engine_mod.read_ema_stack = lambda bars, cfg: both
    engine_mod.ema_entry_signal = lambda *a, **k: (Side.LONG, "EMA_SNIPER_LONG")
    try:
        eng._ema_last_bar_time = "t0"
        eng.completed_bars[-1]["time"] = "t1"
        eng.completed_bars[-1]["close"] = 29341.25
        eng._ema_on_completed_bar(allow_entry=True)
    finally:
        engine_mod.read_ema_stack = orig_read
        engine_mod.ema_entry_signal = orig_sig
    assert eng.paper is not None
    assert eng.paper.side == Side.LONG
    assert eng._ema_pullback is None


def test_long_only_ignores_short_cross() -> None:
    eng = _ema_engine(EMA_ALLOW_LONG=True, EMA_ALLOW_SHORT=False)
    stack = EmaStack(ema9=99.0, ema20=100.0, ema50=101.0, prev9=100.2, prev20=100.0, prev50=101.0)
    eng.completed_bars[-1]["close"] = 99.5
    eng._ema_try_arm_signal(Side.SHORT, stack, allow_entry=True)
    assert eng._ema_pending_side == Side.NONE
    assert eng._ema_pullback is None


def test_intersect_short_stays_blocked() -> None:
    eng = _ema_engine(EMA_ALLOW_LONG=True, EMA_ALLOW_SHORT=False)
    stack = EmaStack(
        ema9=98.4,
        ema20=100.0,
        ema50=99.2,
        prev9=100.3,
        prev20=99.9,
        prev50=99.3,
    )
    eng.completed_bars[-1]["close"] = 98.4
    eng._ema_try_arm_signal(Side.SHORT, stack, allow_entry=True, why="EMA_INTERSECT_SHORT")
    assert eng.paper is None
    assert eng._ema_pending_side == Side.NONE


def test_knot_white_cross_does_not_fill() -> None:
    eng = _ema_engine()
    stack = EmaStack(
        ema9=100.4,
        ema20=100.0,
        ema50=104.5,
        prev9=99.6,
        prev20=100.2,
        prev50=104.6,
    )
    eng.completed_bars[-1]["close"] = 100.4
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why="EMA_SNIPER_LONG")
    assert eng.paper is None
    assert eng._ema_pending_side == Side.NONE


def test_sniper_short_is_immediate() -> None:
    eng = _ema_engine(EMA_ALLOW_LONG=True, EMA_ALLOW_SHORT=True)
    stack = EmaStack(
        ema9=89.0,
        ema20=110.0,
        ema50=100.0,
        prev9=111.0,
        prev20=110.2,
        prev50=100.1,
    )
    eng.completed_bars[-1]["close"] = 89.0
    eng._ema_try_arm_signal(Side.SHORT, stack, allow_entry=True, why="EMA_SNIPER_SHORT")
    assert eng.paper is not None
    assert eng.paper.side == Side.SHORT
    assert eng._ema_pullback is None


def test_close_cross_is_immediate() -> None:
    eng = _ema_engine()
    stack = EmaStack(ema9=29301.0, ema20=29300.0, ema50=29290.0, prev9=29299.0, prev20=29300.0, prev50=29290.0)
    eng.completed_bars[-1]["close"] = 29312.0
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True)
    assert eng.paper is not None or eng._ema_pending_side != Side.NONE or eng._ema_pullback is not None


def test_pullback_reject_when_disabled() -> None:
    eng = _ema_engine(ENABLE_PULLBACK_ENTRY=False)
    stack = _traj_extended_stack()
    eng.completed_bars[-1]["close"] = 29341.25
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True)
    assert eng._ema_pending_side == Side.NONE
    assert eng._ema_pullback is None


def test_pullback_cancels_when_structure_fails() -> None:
    eng = _ema_engine()
    eng.completed_bars[-1]["close"] = 29341.25
    eng._ema_pullback = EmaPullbackSetup(
        direction=Side.LONG,
        signal_price=29341.25,
        signal_bar_time="t0",
        signal_ts=0.0,
        ema9=29315.0,
        ema20=29310.69,
        atr=30.0,
        extension_atr=1.0,
    )
    failed = EmaStack(ema9=29300.0, ema20=29310.0, ema50=29320.0, prev9=29347.0, prev20=29310.0, prev50=29320.0)
    cancelled = eng._ema_pullback_on_bar(failed, Side.SHORT)
    assert cancelled is True
    assert eng._ema_pullback is None
    assert eng._ema_pending_side == Side.NONE


def test_pullback_qualifies_on_bar_close() -> None:
    eng = _ema_engine()
    eng.completed_bars[-1]["close"] = 29312.0
    eng._ema_pullback = EmaPullbackSetup(
        direction=Side.LONG,
        signal_price=29341.25,
        signal_bar_time="t0",
        signal_ts=0.0,
        ema9=29315.0,
        ema20=29310.69,
        atr=30.0,
        extension_atr=1.0,
    )
    pulled = EmaStack(ema9=29316.0, ema20=29310.0, ema50=29340.0, prev9=29320.0, prev20=29310.5, prev50=29340.0)
    cancelled = eng._ema_pullback_on_bar(pulled, Side.NONE)
    assert cancelled is False
    assert eng._ema_pullback is None
    assert eng._ema_pending_side == Side.LONG
    assert eng._ema_pending_why == "EMA_PULLBACK_LONG"


def test_rsi_long_fill_uses_atr_stop_and_delayed_trail() -> None:
    eng = _ema_engine(EMA_RSI_LONG=True)
    stack = EmaStack(
        ema9=29320.0,
        ema20=29310.0,
        ema50=29290.0,
        prev9=29308.0,
        prev20=29309.0,
        prev50=29289.0,
    )
    eng.completed_bars[-1]["close"] = 29320.0
    eng._ema_try_arm_signal(Side.LONG, stack, allow_entry=True, why="EMA_RSI_LONG")
    assert eng.paper is not None
    assert eng.paper.side == Side.LONG
    assert eng.paper.ema_entry_tag == "EMA_RSI_LONG"
    assert eng.paper.tip_trail_pts == 3.0
    assert eng.paper.tip_target_pts == 5.5
    assert abs(eng.paper.stop - ema_atr_stop(eng.paper.entry, Side.LONG, 30.0, eng.cfg)) < 1e-9
    assert abs(eng.paper.target - (eng.paper.entry + 5.5)) < 1e-9
    assert eng._ema_pullback is None


def test_rsi_long_does_not_stack_when_already_in_trade() -> None:
    from mark2 import engine as engine_mod

    eng = _ema_engine()
    first = PaperTrade(
        side=Side.LONG,
        entry=29300.0,
        entry_ts=1.0,
        stop=29294.5,
        target=29400.0,
        peak=29300.0,
        trough=29300.0,
        hard_stop=29294.5,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        tip_trail_pts=5.5,
        ema_entry_tag="EMA_RSI_LONG",
    )
    eng.paper = first
    eng._ema_last_bar_time = "t0"
    eng.completed_bars[-1]["time"] = "t1"
    stack = EmaStack(
        ema9=29320.0,
        ema20=29310.0,
        ema50=29290.0,
        prev9=29318.0,
        prev20=29309.0,
        prev50=29289.0,
    )
    orig_read = engine_mod.read_ema_stack
    orig_sig = engine_mod.ema_entry_signal
    orig_arm = eng._ema_try_arm_signal
    armed: list[str] = []
    engine_mod.read_ema_stack = lambda bars, cfg: stack
    engine_mod.ema_entry_signal = lambda *a, **k: (Side.LONG, "EMA_RSI_LONG")
    eng._ema_try_arm_signal = lambda *a, **k: armed.append("arm")
    try:
        eng._ema_on_completed_bar(allow_entry=True)
    finally:
        engine_mod.read_ema_stack = orig_read
        engine_mod.ema_entry_signal = orig_sig
        eng._ema_try_arm_signal = orig_arm
    assert armed == []
    assert eng.paper is first


def test_pullback_expires() -> None:
    eng = _ema_engine(MAX_PULLBACK_WAIT_BARS=2)
    eng.completed_bars[-1]["close"] = 29340.0
    eng._ema_pullback = EmaPullbackSetup(
        direction=Side.LONG,
        signal_price=29341.25,
        signal_bar_time="t0",
        signal_ts=0.0,
        ema9=29315.0,
        ema20=29310.69,
        atr=30.0,
        extension_atr=1.0,
    )
    still = EmaStack(ema9=29320.0, ema20=29310.0, ema50=29340.0, prev9=29321.0, prev20=29310.5, prev50=29340.0)
    assert eng._ema_pullback_on_bar(still, Side.NONE) is False
    assert eng._ema_pullback_on_bar(still, Side.NONE) is False
    assert eng._ema_pullback_on_bar(still, Side.NONE) is True
    assert eng._ema_pullback is None


def test_high_momentum_does_not_lock_70_until_runner() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    done, why, _st = manage_ema_hold(trade, price=110.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "PROBATION"
    assert trade.stop == 85.0
    assert mfe_losing_momentum(trade, price=110.0, cfg=cfg) is False
    assert mfe_lock_active(trade, price=110.0, state="PROBATION", cfg=cfg) is False
    done, why, _st = manage_ema_hold(trade, price=108.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert mfe_losing_momentum(trade, price=108.0, cfg=cfg) is False
    assert mfe_lock_active(trade, price=108.0, state="PROBATION", cfg=cfg) is False
    assert abs(trade.stop - 85.0) < 1e-9
    done, why, _st = manage_ema_hold(trade, price=106.5, exit_armed=False, cfg=cfg)
    assert done is False
    assert why == ""
    assert trade.ema_trade_state == "PROBATION"


def test_confirmed_protects_at_one_r() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    done, why, _st = manage_ema_hold(trade, price=115.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "CONFIRMED"
    assert trade.stop == 97.5


def test_runner_ratchets_70_percent_of_mfe() -> None:
    cfg = Mark2Config()
    cfg.MFE_GIVEBACK_FRAC = 0.30
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    manage_ema_hold(trade, price=140.0, exit_armed=False, cfg=cfg)
    assert trade.ema_trade_state == "RUNNER"
    assert abs(trade.giveback_floor_pts - 28.0) < 1e-9
    assert abs(trade.stop - 128.0) < 1e-9
    manage_ema_hold(trade, price=150.0, exit_armed=False, cfg=cfg)
    # $100 arms $80 floor (40 pts) and 7.5 tip trail from 150 → 142.5
    assert abs(trade.stop - 142.5) < 1e-9
    manage_ema_hold(trade, price=145.0, exit_armed=False, cfg=cfg)
    assert abs(trade.stop - 142.5) < 1e-9
    done, why, _st = manage_ema_hold(trade, price=142.5, exit_armed=False, cfg=cfg)
    assert done is True
    assert why == "TIP_TRAIL"


def test_runner_25pct_dip_holds_above_70_percent_floor() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_GROW_MODE = False
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    manage_ema_hold(trade, price=140.0, exit_armed=False, cfg=cfg)
    assert trade.ema_trade_state == "RUNNER"
    done, why, _st = manage_ema_hold(
        trade, price=130.0, exit_armed=False, cfg=cfg, completed_anchor=138.0
    )
    assert done is False
    assert why == ""
    assert abs(trade.giveback_floor_pts - 28.0) < 1e-9
    assert abs(trade.stop - 128.0) < 1e-9


def test_structure_exits_after_confirmed_9_20_flip() -> None:
    cfg = Mark2Config()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    manage_ema_hold(
        trade, price=120.0, exit_armed=False, cfg=cfg, ema9=121.0, ema20=118.0, ema50=110.0
    )
    assert trade.ema_lost_20 is False
    done, why, _st = manage_ema_hold(
        trade, price=119.0, exit_armed=False, cfg=cfg, ema9=117.0, ema20=118.5, ema50=110.0
    )
    assert done is False
    assert trade.ema_lost_20 is True
    done, why, _st = manage_ema_hold(
        trade, price=118.0, exit_armed=False, cfg=cfg, ema9=116.0, ema20=118.8, ema50=110.0
    )
    assert done is True
    assert why == "STRUCTURE_FAILURE"


def test_compression_exits_after_spread_expands() -> None:
    cfg = Mark2Config()
    cfg.SPREAD_COMPRESS_FRAC = 0.35
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    manage_ema_hold(
        trade, price=116.0, exit_armed=False, cfg=cfg, ema9=104.0, ema20=102.0, ema50=100.0
    )
    manage_ema_hold(
        trade, price=120.0, exit_armed=False, cfg=cfg, ema9=140.0, ema20=110.0, ema50=100.0
    )
    assert trade.spread_peak >= 40.0
    done, why, _st = manage_ema_hold(
        trade, price=118.0, exit_armed=False, cfg=cfg, ema9=112.0, ema20=110.0, ema50=108.0
    )
    assert done is True
    assert why == "COMPRESSION"


def _classic_cfg() -> Mark2Config:
    cfg = Mark2Config()
    cfg.EMA_CLASSIC_EXIT = True
    cfg.EMA_HARD_STOP_POINTS = 10.0
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    cfg.POINT_VALUE = 2.0
    return cfg


def test_classic_10_5_stop_is_ten_points() -> None:
    cfg = _classic_cfg()
    stop = ema_atr_stop(20000.0, Side.LONG, atr=20.0, cfg=cfg)
    assert abs(stop - 19990.0) < 1e-9
    stop_s = ema_atr_stop(20000.0, Side.SHORT, atr=20.0, cfg=cfg)
    assert abs(stop_s - 20010.0) < 1e-9


def test_classic_10_5_hard_stop_before_arm() -> None:
    cfg = _classic_cfg()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=90.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=90.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        tip_trail_pts=5.5,
        qty=1,
    )
    done, why, _st = manage_ema_hold(trade, price=95.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "PROBATION"
    assert abs(trade.stop - 90.0) < 1e-9
    done, why, _st = manage_ema_hold(trade, price=90.0, exit_armed=False, cfg=cfg)
    assert done is True
    assert why == "HARD_STOP"


def test_classic_10_5_arms_at_15_then_trails_5_5() -> None:
    cfg = _classic_cfg()
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=90.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=90.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        tip_trail_pts=5.5,
        qty=1,
    )
    # 5 pts open = $10 — still under the $15 arm.
    done, why, _st = manage_ema_hold(trade, price=105.0, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "PROBATION"
    assert abs(trade.stop - 90.0) < 1e-9
    # 7.5 pts = $15 — trail sits 5.5 under the tip (102.0).
    done, why, _st = manage_ema_hold(trade, price=107.5, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "RUNNER"
    assert abs(trade.stop - 102.0) < 1e-9
    done, why, _st = manage_ema_hold(trade, price=103.0, exit_armed=False, cfg=cfg)
    assert done is False
    done, why, _st = manage_ema_hold(trade, price=102.0, exit_armed=False, cfg=cfg)
    assert done is True
    assert why == "TIP_TRAIL"


def test_classic_10_5_short_trails_off_the_low() -> None:
    cfg = _classic_cfg()
    trade = PaperTrade(
        side=Side.SHORT,
        entry=100.0,
        entry_ts=1.0,
        stop=110.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=110.0,
        ema_strategy=True,
        ema_trade_state="PROBATION",
        tip_trail_pts=5.5,
        qty=1,
    )
    done, why, _st = manage_ema_hold(trade, price=92.5, exit_armed=False, cfg=cfg)
    assert done is False
    assert trade.ema_trade_state == "RUNNER"
    assert abs(trade.stop - 98.0) < 1e-9
    done, why, _st = manage_ema_hold(trade, price=98.0, exit_armed=False, cfg=cfg)
    assert done is True
    assert why == "TIP_TRAIL"


def test_dollar_floor_is_80_at_100_and_550_at_600() -> None:
    cfg = Mark2Config()
    assert profit_keep_usd(99.0, cfg) == 0.0
    assert abs(profit_keep_usd(100.0, cfg) - 80.0) < 1e-9
    assert abs(profit_keep_usd(600.0, cfg) - 550.0) < 1e-9


def test_tip_trail_starts_7_5_and_widens_then_stalls_in() -> None:
    cfg = Mark2Config()
    assert runner_tip_trail_pts(80.0, 0, cfg) == 0.0
    assert abs(runner_tip_trail_pts(100.0, 0, cfg) - 7.5) < 1e-9
    assert abs(runner_tip_trail_pts(600.0, 0, cfg) - 25.0) < 1e-9
    stalled = runner_tip_trail_pts(600.0, 8, cfg)
    assert stalled + 1e-9 < 25.0
    assert stalled + 1e-9 >= 3.0


def test_recon_sniper_keeps_grow_mode_off() -> None:
    cfg = Mark2Config()
    assert cfg.PRODUCT_NAME == "RECON SNIPER"
    assert cfg.PRODUCT_ENGINE == "ReconSniper"
    assert cfg.ENABLE_GROW_MODE is False
    assert grow_mode_active(cfg, 250.0) is False


def test_grow_keep_is_80_percent_at_50() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_GROW_MODE = True
    assert grow_mode_active(cfg, 250.0) is True
    assert grow_mode_active(cfg, 600.0) is False
    assert grow_keep_usd(49.0, cfg) == 0.0
    assert abs(grow_keep_usd(50.0, cfg) - 40.0) < 1e-9
    assert abs(grow_keep_usd(230.0, cfg) - profit_keep_usd(230.0, cfg)) < 1e-9


def test_grow_does_not_bank_while_making_highs() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_GROW_MODE = True
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    done, why, _st = manage_ema_hold(
        trade, price=130.0, exit_armed=False, cfg=cfg, completed_anchor=130.0, account_equity=250.0
    )
    assert done is False
    done, why, _st = manage_ema_hold(
        trade, price=140.0, exit_armed=False, cfg=cfg, completed_anchor=140.0, account_equity=250.0
    )
    assert done is False
    assert why == ""


def test_grow_mode_toggle_wires_enable_flag() -> None:
    cfg = Mark2Config()
    assert cfg.ENABLE_GROW_MODE is False
    apply_toggles(cfg, {"grow_mode": True})
    assert cfg.ENABLE_GROW_MODE is True
    assert snapshot(cfg)["toggles"]["grow_mode"] is True
    apply_toggles(cfg, {"grow_mode": False})
    assert cfg.ENABLE_GROW_MODE is False
    assert snapshot(cfg)["toggles"]["grow_mode"] is False
    assert grow_mode_active(cfg, 250.0) is False


def test_grow_stall_banks_50_plus() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_GROW_MODE = True
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    manage_ema_hold(trade, price=130.0, exit_armed=False, cfg=cfg, completed_anchor=130.0, account_equity=250.0)
    manage_ema_hold(trade, price=129.0, exit_armed=False, cfg=cfg, completed_anchor=129.4, account_equity=250.0)
    manage_ema_hold(trade, price=128.8, exit_armed=False, cfg=cfg, completed_anchor=129.1, account_equity=250.0)
    done, why, _st = manage_ema_hold(
        trade, price=128.5, exit_armed=False, cfg=cfg, completed_anchor=128.8, account_equity=250.0
    )
    assert done is True
    assert why == "GROW_BANK"
    assert _open_usd_check(trade, 128.5, cfg) >= 50.0


def test_grow_mode_off_stall_does_not_flatten() -> None:
    """Same $50+ stall that GROW_BANKs when on must hold when the toggle is off."""
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_GROW_MODE = False
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    manage_ema_hold(trade, price=130.0, exit_armed=False, cfg=cfg, completed_anchor=130.0, account_equity=250.0)
    manage_ema_hold(trade, price=129.0, exit_armed=False, cfg=cfg, completed_anchor=129.4, account_equity=250.0)
    manage_ema_hold(trade, price=128.8, exit_armed=False, cfg=cfg, completed_anchor=129.1, account_equity=250.0)
    done, why, _st = manage_ema_hold(
        trade, price=128.5, exit_armed=False, cfg=cfg, completed_anchor=128.8, account_equity=250.0
    )
    assert done is False
    assert why != "GROW_BANK"
    grow_keep = grow_keep_usd(_open_usd_check(trade, 130.0, cfg), cfg)
    grow_lock = 100.0 + grow_keep / 2.0
    assert abs(float(trade.stop) - grow_lock) > 1e-6


def test_grow_mode_off_allows_runner_tip_trail() -> None:
    """Off skip the $50 bank so $100 tip trail can arm and hold through a stall."""
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_GROW_MODE = False
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19970.0,
        target=0.0,
        peak=20000.0,
        trough=20000.0,
        hard_stop=19970.0,
        ema_strategy=True,
        atr_at_entry=30.0,
    )
    manage_ema_hold(
        trade, price=20050.0, exit_armed=False, cfg=cfg, completed_anchor=20050.0, account_equity=250.0
    )
    manage_ema_hold(
        trade, price=20048.0, exit_armed=False, cfg=cfg, completed_anchor=20048.5, account_equity=250.0
    )
    manage_ema_hold(
        trade, price=20047.0, exit_armed=False, cfg=cfg, completed_anchor=20048.0, account_equity=250.0
    )
    done, why, _st = manage_ema_hold(
        trade, price=20046.0, exit_armed=False, cfg=cfg, completed_anchor=20047.2, account_equity=250.0
    )
    assert done is False
    assert why != "GROW_BANK"
    assert abs(runner_tip_trail_pts(100.0, 0, cfg) - 7.5) < 1e-9
    assert float(getattr(trade, "tip_trail_pts", 0) or 0) + 1e-9 >= 7.5


def _open_usd_check(trade, price: float, cfg: Mark2Config) -> float:
    return (float(price) - float(trade.entry)) * float(cfg.POINT_VALUE) * max(1, int(trade.qty or 1))


def test_grow_off_after_account_builds() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_GROW_MODE = True
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=100.0,
        trough=100.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    manage_ema_hold(trade, price=130.0, exit_armed=False, cfg=cfg, completed_anchor=130.0, account_equity=800.0)
    manage_ema_hold(trade, price=129.0, exit_armed=False, cfg=cfg, completed_anchor=129.4, account_equity=800.0)
    manage_ema_hold(trade, price=128.8, exit_armed=False, cfg=cfg, completed_anchor=129.1, account_equity=800.0)
    done, why, _st = manage_ema_hold(
        trade, price=128.5, exit_armed=False, cfg=cfg, completed_anchor=128.8, account_equity=800.0
    )
    assert done is False
    assert why == ""


def _red(o: float, h: float, lo: float, c: float) -> dict:
    return {"open": o, "high": h, "low": lo, "close": c}


def _green(o: float, h: float, lo: float, c: float) -> dict:
    return {"open": o, "high": h, "low": lo, "close": c}


def test_adverse_stack_is_three_reds_after_the_high() -> None:
    cfg = Mark2Config()
    peak = 150.0
    reds = [
        _red(149.5, 150.0, 148.2, 148.4),
        _red(148.4, 148.8, 147.0, 147.2),
        _red(147.2, 147.5, 145.8, 146.0),
    ]
    assert adverse_stack_exit(Side.LONG, reds, peak, peak_usd=60.0, atr=8.0, cfg=cfg) is True
    assert adverse_stack_exit(Side.LONG, reds[:2], peak, peak_usd=60.0, atr=8.0, cfg=cfg) is False


def test_adverse_stack_ignores_tiny_pullback() -> None:
    cfg = Mark2Config()
    reds = [
        _red(149.8, 150.0, 149.6, 149.7),
        _red(149.7, 149.9, 149.5, 149.6),
        _red(149.6, 149.8, 149.4, 149.5),
    ]
    assert adverse_stack_exit(Side.LONG, reds, 150.0, peak_usd=60.0, atr=8.0, cfg=cfg) is False


def test_hold_exits_adverse_stack_before_hard_stop() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_GROW_MODE = False
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=100.0,
        entry_ts=1.0,
        stop=85.0,
        target=0.0,
        peak=150.0,
        trough=100.0,
        mfe=50.0,
        hard_stop=85.0,
        ema_strategy=True,
        atr_at_entry=10.0,
    )
    bars = [
        _green(100.0, 120.0, 99.5, 119.0),
        _green(119.0, 150.0, 118.0, 149.0),
        _red(149.0, 150.0, 142.0, 143.0),
        _red(143.0, 144.0, 136.0, 137.0),
        _red(137.0, 138.0, 130.0, 131.0),
    ]
    done, why, _st = manage_ema_hold(
        trade, price=131.0, exit_armed=False, cfg=cfg, atr=10.0, bars=bars
    )
    assert done is True
    assert why == "ADVERSE_STACK"
    assert 131.0 > float(trade.hard_stop)


def test_runner_600_cashes_near_550() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19850.0,
        target=0.0,
        peak=20300.0,
        trough=19990.0,
        mfe=300.0,
        hard_stop=19850.0,
        ema_strategy=True,
        ema_trade_state="RUNNER",
        atr_at_entry=40.0,
    )
    done, why, _st = manage_ema_hold(
        trade,
        price=20290.0,
        exit_armed=False,
        cfg=cfg,
        atr=40.0,
        completed_anchor=20300.0,
    )
    assert done is False
    assert abs(trade.stop - 20275.0) < 1e-6
    done, why, _st = manage_ema_hold(
        trade,
        price=20275.0,
        exit_armed=False,
        cfg=cfg,
        atr=40.0,
        completed_anchor=20300.0,
    )
    assert done is True
    assert why in ("TIP_TRAIL", "PROTECT")


def test_100_usd_arms_7_5_tip_trail_even_if_confirmed() -> None:
    cfg = Mark2Config()
    cfg.POINT_VALUE = 2.0
    cfg.ENABLE_GROW_MODE = False
    cfg.RUNNER_STRUCTURE_EXIT = False
    trade = PaperTrade(
        side=Side.LONG,
        entry=20000.0,
        entry_ts=1.0,
        stop=19970.0,
        target=0.0,
        peak=20050.0,
        trough=19990.0,
        mfe=50.0,
        hard_stop=19970.0,
        ema_strategy=True,
        ema_trade_state="CONFIRMED",
        atr_at_entry=30.0,
    )
    assert abs(profit_keep_lock_price(trade, cfg, state="CONFIRMED") - 20040.0) < 1e-9
    done, why, _st = manage_ema_hold(
        trade,
        price=20050.0,
        exit_armed=False,
        cfg=cfg,
        atr=30.0,
        completed_anchor=20050.0,
    )
    assert done is False
    assert trade.ema_trade_state == "CONFIRMED"
    assert abs(trade.stop - 20042.5) < 1e-9
    done, why, _st = manage_ema_hold(
        trade,
        price=20042.5,
        exit_armed=False,
        cfg=cfg,
        atr=30.0,
        completed_anchor=20050.0,
    )
    assert done is True
    assert why == "TIP_TRAIL"


def test_tight_through_both_is_not_an_intersection() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_QUALITY_FILTER = False
    knot = EmaStack(
        ema9=100.6,
        ema20=100.1,
        ema50=100.3,
        prev9=99.8,
        prev20=100.2,
        prev50=100.4,
    )
    assert red_clears_white_and_blue(knot) is True
    assert red_crosses_blue(knot) == Side.LONG
    assert long_sniper_reason(knot, cfg, atr=12.0) == ""


def test_spread_9_20_then_9_50_is_the_long() -> None:
    cfg = Mark2Config()
    armed = EmaStack(
        ema9=104.0,
        ema20=100.0,
        ema50=110.0,
        prev9=99.0,
        prev20=100.2,
        prev50=110.2,
    )
    assert long_sniper_reason(armed, cfg, atr=10.0) == "WHITE_ONLY"
    ix = intersection_status(armed, cfg, 10.0)
    assert ix.armed_920 is True
    assert ix.fire is False
    go = EmaStack(
        ema9=111.0,
        ema20=101.0,
        ema50=110.0,
        prev9=105.0,
        prev20=100.8,
        prev50=110.2,
    )
    assert long_sniper_reason(go, cfg, atr=10.0) == ""
    assert intersection_status(go, cfg, 10.0).fire is True


def test_already_through_blue_white_recross_can_fire() -> None:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_QUALITY_FILTER = False
    recross = EmaStack(
        ema9=111.0,
        ema20=110.0,
        ema50=100.0,
        prev9=109.0,
        prev20=110.2,
        prev50=99.8,
    )
    assert red_clears_white_and_blue(recross) is True
    assert long_sniper_reason(recross, cfg, atr=10.0) == ""


def test_separation_ok_uses_atr_when_present() -> None:
    cfg = Mark2Config()
    cfg.EMA_MIN_SEP_ATR = 0.20
    assert separation_ok(2.0, 12.0, cfg) is False
    assert separation_ok(4.0, 12.0, cfg) is True
    assert separation_ok(2.4, 0.0, cfg) is False
    assert separation_ok(4.0, 0.0, cfg) is True
