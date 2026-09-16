"""Live NT reject must not leave a phantom paper trade that blocks new orders."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config
from mark2.engine import Mark2Engine
from mark2.exits import PaperTrade
from mark2.types import MarketSnapshot, RunMode, Side, Tick


def test_abort_unfilled_live_clears_paper() -> None:
    with tempfile.TemporaryDirectory() as td:
        cfg = Mark2Config()
        cfg.MODE = RunMode.LIVE.value
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng.paper = PaperTrade(
            side=Side.LONG,
            entry=29413.0,
            entry_ts=1.0,
            stop=29400.0,
            target=0.0,
            peak=29413.0,
            trough=29413.0,
            ema_strategy=True,
        )
        eng.risk.open_side = Side.LONG
        eng._ema_long_stack_taken = True
        assert eng.abort_unfilled_live("margin") is True
        assert eng.paper is None
        assert eng.risk.open_side == Side.NONE
        assert eng._ema_long_stack_taken is False


def test_heartbeat_flat_aborts_stale_live_paper() -> None:
    with tempfile.TemporaryDirectory() as td:
        cfg = Mark2Config()
        cfg.MODE = RunMode.LIVE.value
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng.paper = PaperTrade(
            side=Side.LONG,
            entry=29413.0,
            entry_ts=1.0,
            stop=29400.0,
            target=0.0,
            peak=29413.0,
            trough=29413.0,
            ema_strategy=True,
        )
        eng.risk.open_side = Side.LONG
        eng._live_entry_wall = time.time() - 5.0
        eng.apply_account({"type": "heartbeat", "position": 0, "cash_value": 165})
        assert eng.paper is None
        assert eng.risk.open_side == Side.NONE


def test_abort_filled_live_books_pnl() -> None:
    with tempfile.TemporaryDirectory() as td:
        cfg = Mark2Config()
        cfg.MODE = RunMode.LIVE.value
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng.paper = PaperTrade(
            side=Side.LONG,
            entry=29413.0,
            entry_ts=1.0,
            stop=29400.0,
            target=0.0,
            peak=29420.0,
            trough=29410.0,
            qty=1,
            ema_strategy=True,
        )
        eng.risk.open_side = Side.LONG
        eng._live_filled = True
        eng.last_snap = MarketSnapshot(
            ts=2.0,
            price=29420.0,
            completed_bars=[],
            forming_bar=None,
        )
        assert eng.abort_unfilled_live("NT_FLAT") is False
        assert eng.paper is None
        assert eng.risk.open_side == Side.NONE
        assert len(eng.closed_trades) == 1
        assert eng.stats.trades == 1
        assert eng.closed_trades[0]["reason"] == "NT_FLAT"


def test_heartbeat_flat_after_fill_books_pnl() -> None:
    with tempfile.TemporaryDirectory() as td:
        cfg = Mark2Config()
        cfg.MODE = RunMode.LIVE.value
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng.paper = PaperTrade(
            side=Side.LONG,
            entry=29413.0,
            entry_ts=1.0,
            stop=29400.0,
            target=0.0,
            peak=29420.0,
            trough=29410.0,
            qty=1,
            ema_strategy=True,
        )
        eng.risk.open_side = Side.LONG
        eng._live_filled = True
        eng.last_snap = MarketSnapshot(
            ts=2.0,
            price=29420.0,
            completed_bars=[],
            forming_bar=None,
        )
        eng.apply_account({"type": "heartbeat", "position": 0, "cash_value": 165})
        assert eng.paper is None
        assert len(eng.closed_trades) == 1
        assert eng.stats.trades == 1


class _LiveSink:
    def __init__(self) -> None:
        self.orders: list[dict] = []
        self.flats: list[str] = []
        self.stops: list[tuple[float, str]] = []
        self.levels: list[dict] = []

    def send_order(self, action, *, quantity=1, stop_loss=None, reason=""):
        self.orders.append(
            {"action": action, "quantity": quantity, "stop": stop_loss, "reason": reason}
        )

    def send_flat(self, reason=""):
        self.flats.append(reason)

    def send_stop(self, price, reason=""):
        self.stops.append((float(price), str(reason)))

    def send_levels(self, **payload):
        self.levels.append(payload)

    def send_ema_overlay(self, **payload):
        return None


def _ema_manual_engine(td: str, *, sink=None) -> Mark2Engine:
    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.ALLOW_LEGACY_ENTRIES = False
    cfg.MODE = RunMode.LIVE.value
    cfg.MARK2_ENABLED = False
    eng = Mark2Engine(
        cfg,
        log_path=Path(td) / "d.jsonl",
        persist_path=Path(td) / "s.json",
        sink=sink,
    )
    for i in range(20):
        eng.completed_bars.append(
            {
                "time": f"b{i}",
                "open": 29400.0,
                "high": 29420.0,
                "low": 29390.0,
                "close": 29413.0,
                "volume": 500,
            }
        )
    eng.last_snap = MarketSnapshot(
        ts=1.0,
        price=29413.0,
        completed_bars=list(eng.completed_bars),
        forming_bar=None,
        atr=10.0,
    )
    eng.risk.connected = True
    return eng


def test_manual_ema_buy_joins_live_hold() -> None:
    """HUD BUY in EMA mode books the leftover-style ticket; NT fill starts hold."""
    sink = _LiveSink()
    with tempfile.TemporaryDirectory() as td:
        eng = _ema_manual_engine(td, sink=sink)
        out = eng.manual_order("BUY")
        assert out["ok"] is True, out
        assert out.get("error") != "EMA_ONLY"
        assert eng.paper is not None
        assert eng.paper.side == Side.LONG
        assert eng.paper.manual_entry is True
        assert eng.paper.ema_strategy is True
        assert eng.paper.ema_trade_state == "PROBATION"
        assert eng.paper.event_type == "HUD_MANUAL"
        assert float(eng.paper.target) == 0.0
        assert eng._live_filled is False
        assert eng._live_entry_wall > 0
        assert sink.orders and sink.orders[0]["action"] == "BUY"
        assert int(sink.orders[0]["quantity"]) == int(eng.cfg.contracts())
        eng.note_nt_fill({"order_name": "entry", "price": 29413.0, "position": 1})
        assert eng._live_filled is True
        tick = Tick(
            ts=2.0,
            price=29420.0,
            volume=800,
            bar_time="live-m",
            forming_open=29413.0,
            forming_high=29420.0,
            forming_low=29410.0,
            forming_volume=800,
        )
        out2 = eng.on_tick(tick)
        assert eng.paper is not None
        assert bool(getattr(eng.paper, "ema_strategy", False))
        assert out2 is not None
        assert out2.get("decision") != "REJECT"
        eng.flatten_now("HUD_FLAT")
        assert eng.paper is None
        assert sink.flats


def test_manual_buy_uses_ai_exit_not_a_target() -> None:
    """HUD BUY must not publish a green profit target; AI hold owns the exit."""
    sink = _LiveSink()
    with tempfile.TemporaryDirectory() as td:
        eng = _ema_manual_engine(td, sink=sink)
        eng.cfg.ENABLE_AI_EXIT_ENGINE = True
        out = eng.manual_order("BUY")
        assert out["ok"] is True, out
        assert eng.paper is not None
        assert float(eng.paper.target) == 0.0
        assert eng.paper.ema_strategy is True
        eng.note_nt_fill({"order_name": "entry", "price": 29413.0, "position": 1})
        tick = Tick(
            ts=2.0,
            price=29420.0,
            volume=800,
            bar_time="live-m",
            forming_open=29413.0,
            forming_high=29420.0,
            forming_low=29410.0,
            forming_volume=800,
        )
        out2 = eng.on_tick(tick)
        assert eng.paper is not None
        assert out2 is not None
        assert out2.get("decision") != "EXIT" or "TARGET" not in str(out2.get("reject") or "")
        assert float(eng.paper.target) == 0.0
        eng.flatten_now("HUD_FLAT")


def test_manual_ema_short_fill_then_unfilled_abort() -> None:
    """SHORT fill marks live; a later flat heartbeat books PnL. No-fill aborts."""
    sink = _LiveSink()
    with tempfile.TemporaryDirectory() as td:
        eng = _ema_manual_engine(td, sink=sink)
        out = eng.manual_order("SHORT")
        assert out["ok"] is True, out
        assert eng.paper is not None
        assert eng.paper.side == Side.SHORT
        assert sink.orders[0]["action"] == "SELL"
        eng.note_nt_fill({"order_name": "entry", "price": 29413.0, "position": -1})
        assert eng._live_filled is True
        eng.last_snap = MarketSnapshot(
            ts=2.0,
            price=29400.0,
            completed_bars=[],
            forming_bar=None,
        )
        eng.apply_account({"type": "heartbeat", "position": 0, "cash_value": 165})
        assert eng.paper is None
        assert len(eng.closed_trades) == 1

        eng2 = _ema_manual_engine(td, sink=_LiveSink())
        out2 = eng2.manual_order("BUY")
        assert out2["ok"] is True, out2
        eng2._live_entry_wall = time.time() - 5.0
        eng2.apply_account({"type": "heartbeat", "position": 0, "cash_value": 165})
        assert eng2.paper is None
        assert eng2.risk.open_side == Side.NONE
        assert eng2._live_filled is False
