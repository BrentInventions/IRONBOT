"""Tests for optional Simple Trading Book candle patterns."""

from __future__ import annotations

from mark2.book_patterns import (
    BookPatternDetector,
    book_pattern_entry_ok,
    is_bearish_engulfing,
    is_bullish_engulfing,
    is_dark_cloud_cover,
    is_evening_star,
    is_hammer,
    is_morning_star,
    is_piercing_line,
    is_shooting_star,
    is_three_black_crows,
    is_three_white_soldiers,
)
from mark2.config import Mark2Config
from mark2.entry_tuning import apply_toggles, snapshot
from mark2.types import Side


def bar(o, h, l, c) -> dict:
    return {"open": o, "high": h, "low": l, "close": c}


class TestPatternShapes:
    def test_hammer(self) -> None:
        assert is_hammer(bar(100, 100.2, 90, 100.1), wick_body_mult=2.0)

    def test_shooting_star(self) -> None:
        assert is_shooting_star(bar(100, 110, 99.9, 100.1), wick_body_mult=2.0)

    def test_bullish_engulfing(self) -> None:
        prev = bar(105, 106, 100, 101)
        cur = bar(100.5, 108, 100, 107)
        assert is_bullish_engulfing(prev, cur)

    def test_bearish_engulfing(self) -> None:
        prev = bar(100, 106, 99, 105)
        cur = bar(105.5, 106, 98, 99)
        assert is_bearish_engulfing(prev, cur)

    def test_morning_star(self) -> None:
        a = bar(110, 111, 100, 101)
        b = bar(100.5, 102, 99, 100.2)
        c = bar(100.5, 112, 100, 111)
        assert is_morning_star(a, b, c)

    def test_evening_star(self) -> None:
        a = bar(100, 111, 99, 110)
        b = bar(109.5, 111, 109, 110.2)
        c = bar(109.5, 110, 98, 99)
        assert is_evening_star(a, b, c)

    def test_three_white_soldiers(self) -> None:
        a = bar(100, 105, 99, 104)
        b = bar(104, 109, 103, 108)
        c = bar(108, 113, 107, 112)
        assert is_three_white_soldiers(a, b, c)

    def test_three_black_crows(self) -> None:
        a = bar(112, 113, 107, 108)
        b = bar(108, 109, 103, 104)
        c = bar(104, 105, 99, 100)
        assert is_three_black_crows(a, b, c)

    def test_piercing_line(self) -> None:
        prev = bar(110, 111, 100, 101)
        cur = bar(100, 108, 99, 107)
        assert is_piercing_line(prev, cur)

    def test_dark_cloud_cover(self) -> None:
        prev = bar(100, 111, 99, 110)
        cur = bar(111, 112, 102, 103)
        assert is_dark_cloud_cover(prev, cur)


class TestFilterToggle:
    def test_disabled_never_blocks(self) -> None:
        det = BookPatternDetector(enabled=False)
        bars = [bar(100, 101, 99, 100.5), bar(100.5, 101, 100, 100.2)]
        ok, why = det.allows_side(Side.LONG, bars)
        assert ok
        assert "not filtering" in why

    def test_enabled_blocks_without_pattern(self) -> None:
        det = BookPatternDetector(enabled=True)
        bars = [
            bar(100, 101, 99.5, 100.2),
            bar(100.2, 101.0, 99.8, 100.4),
        ]
        ok, why = det.allows_side(Side.LONG, bars)
        assert not ok
        assert "book filter" in why

    def test_enabled_allows_matching_engulfing(self) -> None:
        det = BookPatternDetector(enabled=True)
        bars = [
            bar(105, 106, 100, 101),
            bar(100.5, 108, 100, 107),
        ]
        ok, why = det.allows_side(Side.LONG, bars)
        assert ok
        assert "Bullish Engulfing" in why

    def test_enabled_allows_three_black_crows(self) -> None:
        det = BookPatternDetector(enabled=True)
        bars = [
            bar(112, 113, 107, 108),
            bar(108, 109, 103, 104),
            bar(104, 105, 99, 100),
        ]
        ok, why = det.allows_side(Side.SHORT, bars)
        assert ok
        assert "Three Black Crows" in why

    def test_enabled_blocks_opposing_engulfing(self) -> None:
        det = BookPatternDetector(enabled=True)
        bars = [
            bar(105, 106, 100, 101),
            bar(100.5, 108, 100, 107),
        ]
        ok, why = det.allows_side(Side.SHORT, bars)
        assert not ok
        assert "Bullish Engulfing" in why


class TestEntryTuning:
    def test_book_patterns_toggle_in_entry_tuning(self) -> None:
        cfg = Mark2Config()
        apply_toggles(cfg, {"book_patterns": True})
        assert cfg.ENABLE_BOOK_PATTERNS is True
        snap = snapshot(cfg)
        assert snap["toggles"]["book_patterns"] is True

    def test_book_mode_clears_conflicting_gates_keeps_rsi(self) -> None:
        from mark2.entry_tuning import enter_book_mode, exit_book_mode

        cfg = Mark2Config()
        cfg.REQUIRE_TRENDING = True
        cfg.REQUIRE_CANDLE_ALIGNMENT = True
        cfg.ENABLE_CHAOTIC_BANK = True
        cfg.ENABLE_EXPERIMENTAL_PROFILE = True
        cfg.ENABLE_EXHAUSTION_FILTER = True
        stash = enter_book_mode(cfg)
        assert cfg.ENABLE_BOOK_PATTERNS is True
        assert cfg.REQUIRE_TRENDING is False
        assert cfg.REQUIRE_CANDLE_ALIGNMENT is False
        assert cfg.ENABLE_CHAOTIC_BANK is False
        assert cfg.ENABLE_CHOP_SCALP is False
        assert cfg.ENABLE_CHOPPY_BIAS is False
        assert cfg.ENABLE_EXPERIMENTAL_PROFILE is False
        assert cfg.ENABLE_EXHAUSTION_FILTER is True
        exit_book_mode(cfg, stash)
        assert cfg.ENABLE_BOOK_PATTERNS is False
        assert cfg.REQUIRE_TRENDING is True
        assert cfg.REQUIRE_CANDLE_ALIGNMENT is True
        assert cfg.ENABLE_CHAOTIC_BANK is True
        assert cfg.ENABLE_EXPERIMENTAL_PROFILE is True
        assert cfg.ENABLE_EXHAUSTION_FILTER is True


class TestEngineWrapper:
    def test_wrapper_zero_overhead_when_off(self) -> None:
        cfg = Mark2Config()
        cfg.ENABLE_BOOK_PATTERNS = False
        ok, detail = book_pattern_entry_ok(cfg, [], Side.LONG)
        assert ok
        assert detail == ""

    def test_wrapper_blocks_when_on_and_no_pattern(self) -> None:
        cfg = Mark2Config()
        cfg.ENABLE_BOOK_PATTERNS = True
        bars = [bar(100, 101, 99.5, 100.2), bar(100.2, 101.0, 99.8, 100.4)]
        ok, detail = book_pattern_entry_ok(cfg, bars, Side.LONG)
        assert not ok
        assert "book filter" in detail
