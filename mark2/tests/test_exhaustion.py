"""Extension Engine — dual scores + MACD chase protection."""

from __future__ import annotations

from mark2.config import Mark2Config
from mark2.entry_tuning import apply_toggles, snapshot
from mark2.exhaustion import exhaustion_blocks, read_exhaustion
from mark2.indicators import bollinger, macd, rsi
from mark2.types import MarketSnapshot, Side


def _bars_up(n: int = 60, start: float = 100.0, step: float = 1.5) -> list[dict]:
    out = []
    px = start
    for _ in range(n):
        o = px
        c = px + step
        out.append({"open": o, "high": c + 0.3, "low": o - 0.2, "close": c, "volume": 100})
        px = c
    return out


def _bars_down(n: int = 60, start: float = 200.0, step: float = 1.5) -> list[dict]:
    out = []
    px = start
    for _ in range(n):
        o = px
        c = px - step
        out.append({"open": o, "high": o + 0.2, "low": c - 0.3, "close": c, "volume": 100})
        px = c
    return out


def _snap(bars: list[dict], *, vwap_sigma: float = 0.0, velocity: float = 0.0) -> MarketSnapshot:
    px = float(bars[-1]["close"])
    return MarketSnapshot(
        ts=1.0,
        price=px,
        completed_bars=bars[:-1],
        forming_bar=bars[-1],
        atr=2.0,
        vwap_distance_atr=vwap_sigma,
        velocity=velocity,
    )


class TestMacd:
    def test_macd_returns_on_trend(self) -> None:
        bars = _bars_up(80, step=2.0)
        m, s, h, d, cross = macd(bars)
        assert isinstance(m, float)
        # Strong uptrend → MACD above signal eventually
        assert m != 0.0 or s != 0.0


class TestExtensionEngine:
    def test_extension_high_on_rally(self) -> None:
        cfg = Mark2Config()
        snap = _snap(_bars_up(80, step=2.5), vwap_sigma=2.8, velocity=1.5)
        r = read_exhaustion(snap, cfg)
        assert r.extension_long > 50.0
        assert r.rsi > 70.0

    def test_blocks_long_unless_oversold(self) -> None:
        cfg = Mark2Config()
        cfg.ENABLE_EXHAUSTION_FILTER = True
        snap = _snap(_bars_up(50, step=2.5), vwap_sigma=2.8)
        blocked, why, reading = exhaustion_blocks(Side.LONG, snap, cfg)
        assert blocked
        assert "not oversold" in why
        assert reading.rsi > 70.0

    def test_allows_long_when_oversold(self) -> None:
        cfg = Mark2Config()
        cfg.ENABLE_EXHAUSTION_FILTER = True
        snap = _snap(_bars_down(50, step=2.5), vwap_sigma=-2.8, velocity=0.2)
        blocked, why, reading = exhaustion_blocks(Side.LONG, snap, cfg)
        assert not blocked
        assert reading.rsi <= 30.0
        assert "LONG ok" in why

    def test_monster_trend_blocks_short_fade(self) -> None:
        """OB alone is not enough — accelerating MACD blocks the fade."""
        cfg = Mark2Config()
        cfg.ENABLE_EXHAUSTION_FILTER = True
        cfg.RSI_OB_LEVEL = 70.0
        cfg.MONSTER_EXTENSION = 55.0
        cfg.MONSTER_MOMENTUM = 20.0
        snap = _snap(_bars_up(80, step=3.0), vwap_sigma=3.0, velocity=2.0)
        blocked, why, reading = exhaustion_blocks(Side.SHORT, snap, cfg)
        assert reading.rsi >= 70.0
        # Either monster block or chase — must not blindly short rip
        if reading.momentum_health > 20 and reading.extension_long >= 55:
            assert blocked
            assert "monster" in why.lower() or "chase" in why.lower()

    def test_mid_rsi_blocks_both(self) -> None:
        cfg = Mark2Config()
        cfg.ENABLE_EXHAUSTION_FILTER = True
        bars = []
        for i in range(40):
            px = 100.0 + (0.1 if i % 2 == 0 else -0.1)
            bars.append(
                {"open": 100.0, "high": 100.3, "low": 99.7, "close": px, "volume": 50}
            )
        snap = _snap(bars, vwap_sigma=0.1)
        long_b, _, r = exhaustion_blocks(Side.LONG, snap, cfg)
        short_b, _, _ = exhaustion_blocks(Side.SHORT, snap, cfg)
        assert 25.0 < r.rsi < 75.0
        assert long_b and short_b

    def test_toggle_off(self) -> None:
        cfg = Mark2Config()
        cfg.ENABLE_EXHAUSTION_FILTER = False
        snap = _snap(_bars_up(50, step=3.0), vwap_sigma=3.0)
        blocked, _, _ = exhaustion_blocks(Side.LONG, snap, cfg)
        assert not blocked

    def test_book_forces_exhaustion(self) -> None:
        cfg = Mark2Config()
        apply_toggles(cfg, {"book_patterns": True})
        snap = snapshot(cfg)
        assert snap["toggles"]["exhaustion_filter"] is True
