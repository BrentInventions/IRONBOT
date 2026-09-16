"""Unit tests for Recon Sniper Stage 1 — LIVE default, anti-spam, no look-ahead."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config, load_config
from mark2.engine import Mark2Engine
from mark2.analytics import EngineStats
from mark2.events import EventDetector
from mark2.exits import PaperTrade
from mark2.runtime import Mark2Runtime
from mark2.types import EventType, RunMode, ScoreBundle, Side, Tick
from mark2.types import MarketSnapshot


def _bars_compressed(n: int = 80, start: float = 20000.0) -> list[dict]:
    """Mean-reverting tape so a later impulse is not already extended."""
    out = []
    for i in range(n):
        wobble = (i % 6 - 3) * 0.35
        o = start + wobble
        c = start - wobble * 0.4
        h = max(o, c) + 0.6
        lo = min(o, c) - 0.6
        out.append(
            {
                "time": f"bar-{i}",
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": 500 + (i % 5) * 20,
            }
        )
    return out


def _seed(eng: Mark2Engine, bars: list[dict]) -> None:
    for b in bars:
        eng.on_bar_close(b)


def _tick(
    ts: float,
    price: float,
    bar_time: str,
    *,
    o: float,
    h: float,
    lo: float,
    vol: float,
) -> Tick:
    return Tick(
        ts=ts,
        price=price,
        volume=vol,
        bar_time=bar_time,
        forming_open=o,
        forming_high=h,
        forming_low=lo,
        forming_volume=vol,
    )


def _open_gates(cfg: Mark2Config) -> Mark2Config:
    cfg.LONG_CONFIDENCE_THRESHOLD = 0.0
    cfg.SHORT_CONFIDENCE_THRESHOLD = 0.0
    cfg.LONG_OPPORTUNITY_THRESHOLD = 0.0
    cfg.SHORT_OPPORTUNITY_THRESHOLD = 0.0
    cfg.MIN_CONFIDENCE_VELOCITY = -100.0
    cfg.MAX_EXTENSION_RISK = 99.5
    cfg.EVENT_END_STREAK = 99
    cfg.REQUIRE_TRENDING = False
    cfg.REQUIRE_CANDLE_ALIGNMENT = False
    return cfg


def test_default_mode_is_live():
    assert Mark2Config().mode() == RunMode.LIVE
    cfg = load_config()
    assert cfg.mode() == RunMode.LIVE
    assert cfg.MARK2_ENABLED is True


def test_disable_stays_live():
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(
            cfg,
            log_path=Path(td) / "d.jsonl",
            persist_path=Path(td) / "cfg.json",
        )
        eng.cfg.MARK2_ENABLED = False
        assert eng.cfg.mode() == RunMode.LIVE
        snap = eng.hud_snapshot()
        assert snap["mode"] == "LIVE"
        assert snap["enabled"] is False
        eng.set_mode("bogus")
        assert eng.cfg.mode() == RunMode.LIVE


def test_observe_never_submits_orders():
    cfg = _open_gates(Mark2Config())
    cfg.MODE = RunMode.OBSERVE_ONLY.value
    cfg.ENABLE_EMA_STRATEGY = False
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        _seed(eng, _bars_compressed())
        o = 20000.0
        px = o
        for i in range(40):
            px += 0.35
            t = 1_700_000_000.0 + 80 + i * 0.1
            eng.on_tick(_tick(t, px, "live-1", o=o, h=px, lo=o - 0.4, vol=900 + i * 30))
        assert eng.orders_submitted == 0
        assert eng.paper is not None
        assert eng.paper.side in (Side.LONG, Side.SHORT)


def test_forming_bar_has_no_lookahead():
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        _seed(eng, _bars_compressed())
        t0 = 1_700_000_100.0
        eng.on_tick(_tick(t0, 20000.0, "live-2", o=20000.0, h=20000.0, lo=20000.0, vol=100))
        assert eng.forming_bar is not None
        hi_at_t0 = float(eng.forming_bar["high"])
        eng.on_tick(
            _tick(t0 + 0.2, 20008.0, "live-2", o=20000.0, h=20008.0, lo=19999.0, vol=180)
        )
        hi_later = float(eng.forming_bar["high"])
        assert hi_at_t0 == 20000.0
        assert hi_later == 20008.0
        assert hi_at_t0 < hi_later


def test_duplicate_event_does_not_rearm_every_tick():
    cfg = _open_gates(Mark2Config())
    cfg.MODE = RunMode.OBSERVE_ONLY.value
    cfg.ENABLE_EMA_STRATEGY = False
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        _seed(eng, _bars_compressed())
        o = 20000.0
        px = o
        executes = 0
        manages = 0
        for i in range(30):
            px += 0.4
            t = 1_700_000_200.0 + i * 0.1
            out = eng.on_tick(
                _tick(t, px, "live-3", o=o, h=px, lo=o - 0.25, vol=1400 + i * 40)
            )
            if not out:
                continue
            if out["decision"] == "OBSERVE_EXECUTE":
                executes += 1
            if out["decision"] == "MANAGE":
                manages += 1
        assert executes == 1
        assert manages >= 1
        assert eng.paper is not None
        assert eng.orders_submitted == 0


def test_event_identity_in_isolation():
    cfg = Mark2Config()
    det = EventDetector(cfg)
    snap = MarketSnapshot(
        ts=10.0,
        price=20010.0,
        completed_bars=[],
        forming_bar={"time": "b1", "open": 20000.0, "high": 20010.0, "low": 19999.0},
        atr=4.0,
        velocity=2.0,
        relative_volume=1.8,
        impulse_score=70.0,
        trend_bias="BULLISH",
        structure_state="HH_HL",
    )
    scores = ScoreBundle(
        long_confidence=80.0,
        short_confidence=20.0,
        long_opportunity=75.0,
        short_opportunity=10.0,
        long_conf_velocity=3.0,
    )
    rec, status = det.detect(snap, scores)
    assert rec is not None
    assert rec.event_type != EventType.NONE
    assert status == "EVENT_DETECTED"
    det.mark_consumed(taken=True)
    rec2, status2 = det.detect(
        MarketSnapshot(
            ts=10.2,
            price=20012.0,
            completed_bars=[],
            forming_bar={"time": "b1"},
            atr=4.0,
            velocity=2.2,
            relative_volume=1.9,
            impulse_score=72.0,
            trend_bias="BULLISH",
        ),
        scores,
    )
    assert rec2 is rec
    assert status2 == "EVENT_CONTINUING"
    assert rec2.entry_taken is True


def test_release_after_trade_allows_new_event():
    cfg = Mark2Config()
    det = EventDetector(cfg)
    snap = MarketSnapshot(
        ts=10.0,
        price=20010.0,
        completed_bars=[],
        forming_bar={"time": "b1", "open": 20000.0, "high": 20010.0, "low": 19999.0},
        atr=4.0,
        velocity=2.0,
        relative_volume=1.8,
        impulse_score=70.0,
        trend_bias="BULLISH",
        structure_state="HH_HL",
    )
    scores = ScoreBundle(
        long_confidence=80.0,
        short_confidence=20.0,
        long_opportunity=75.0,
        short_opportunity=10.0,
        long_conf_velocity=3.0,
    )
    rec, _ = det.detect(snap, scores)
    assert rec is not None
    det.mark_consumed(taken=True)
    det.release_after_trade(110.0, rec.event_id)
    assert det.active is not None
    assert det.active.ended is True
    assert det.active.end_reason == "TRADE_CLOSED"
    rec2, status2 = det.detect(
        MarketSnapshot(
            ts=111.0,
            price=20014.0,
            completed_bars=[],
            forming_bar={"time": "b2", "open": 20012.0, "high": 20014.0, "low": 20011.0},
            atr=4.0,
            velocity=2.5,
            relative_volume=1.9,
            impulse_score=72.0,
            trend_bias="BULLISH",
            structure_state="HH_HL",
        ),
        scores,
    )
    assert rec2 is not None
    assert rec2.event_id != rec.event_id
    assert status2 == "EVENT_DETECTED"


def test_close_position_releases_event_for_next_trade():
    """After one scalp exits, the consumed event must end or the bot freezes on DUPLICATE."""
    from mark2.exits import PaperTrade

    cfg = Mark2Config()
    cfg.MARK2_ENABLED = True
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", persist_path=Path(td) / "s.json")
        eng.set_mode("PAPER_TRADE")
        snap = MarketSnapshot(
            ts=50.0,
            price=20010.0,
            completed_bars=[],
            forming_bar={"time": "b1"},
            atr=4.0,
            velocity=-1.0,
            relative_volume=1.5,
            impulse_score=70.0,
            trend_bias="BEARISH",
            trend_regime="HIGH_VOL",
            shorts_allowed=True,
        )
        scores = ScoreBundle(
            long_confidence=30.0,
            short_confidence=70.0,
            short_opportunity=70.0,
            short_conf_velocity=0.5,
        )
        eng.last_snap = snap
        eng.last_scores = scores
        rec, _ = eng.events.detect(snap, scores)
        assert rec is not None
        eng.events.mark_consumed(taken=True)
        eng.paper = PaperTrade(
            side=Side.SHORT,
            entry=20010.0,
            entry_ts=50.0,
            stop=20030.0,
            target=20004.0,
            peak=20010.0,
            trough=20010.0,
            qty=1,
            event_id=rec.event_id,
            event_type=rec.event_type.value,
        )
        eng.risk.note_open(Side.SHORT)
        tick = Tick(ts=55.0, price=20004.0)
        eng._close_position(tick, snap, scores, "TRAIL")
        assert eng.events.active is not None
        assert eng.events.active.ended is True
        assert eng.events.active.end_reason == "TRADE_CLOSED"
        snap2 = MarketSnapshot(
            ts=56.0,
            price=20002.0,
            completed_bars=[],
            forming_bar={"time": "b2"},
            atr=4.0,
            velocity=-1.2,
            relative_volume=1.6,
            impulse_score=72.0,
            trend_bias="BEARISH",
            trend_regime="HIGH_VOL",
            shorts_allowed=True,
        )
        rec2, status2 = eng.events.detect(snap2, scores)
        assert status2 == "EVENT_DETECTED"
        assert rec2 is not None
        assert rec2.event_id != rec.event_id
        assert rec2.entry_taken is False


def test_paper_mode_can_open_and_track_mfe():
    cfg = _open_gates(Mark2Config())
    cfg.MODE = RunMode.PAPER_TRADE.value
    cfg.SCRATCH_THRESHOLD = 0.0
    cfg.SCRATCH_MAX_SECONDS = 0.0
    cfg.ENABLE_MOMENTUM_EXIT = False
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        _seed(eng, _bars_compressed())
        o = 20000.0
        px = o
        opened = False
        for i in range(40):
            px += 0.45
            t = 1_700_000_300.0 + i * 0.1
            eng.on_tick(_tick(t, px, "live-4", o=o, h=px, lo=o - 0.2, vol=1600 + i * 30))
            if eng.paper is not None:
                opened = True
                break
        assert opened
        assert eng.paper.side in (Side.LONG, Side.SHORT)
        assert eng.orders_submitted == 0


def test_live_without_bridge_does_not_submit():
    cfg = Mark2Config()
    cfg.MODE = RunMode.LIVE.value
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        assert eng.mode == RunMode.LIVE
        eng.risk.connected = False
        assert eng.orders_submitted == 0


def test_package_does_not_import_mark1():
    import ast

    root = Path(__file__).resolve().parents[1]
    forbidden = {
        "htf_context",
        "impulse_engine",
        "tradechampion",
        "live_ai",
        "v3_pipeline",
        "classic_long_live",
        "shorts_bot",
        "brain",
        "BridgeClient",
        "ImpulseRuntime",
    }
    for path in root.rglob("*.py"):
        if path.name.startswith("test"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                assert name not in forbidden, f"{path.name} imports {name}"


def test_vwap_distance_does_not_hard_block():
    from mark2.extension import ExtensionFilter
    from mark2.types import EventRecord

    cfg = Mark2Config()
    filt = ExtensionFilter(cfg)
    ev = EventRecord(
        event_id=1,
        event_type=EventType.MOMENTUM_EXPANSION,
        direction=Side.SHORT,
        started_ts=1.0,
        started_bar_time="b1",
        started_price=30170.0,
    )
    snap = MarketSnapshot(
        ts=1.2,
        price=30168.0,
        completed_bars=[],
        forming_bar={"time": "b1", "open": 30170.0, "high": 30172.0, "low": 30160.0},
        atr=32.0,
        vwap_distance_atr=-1.87,
        velocity=-8.0,
        acceleration=-1.0,
    )
    scores = ScoreBundle()
    filt.update(snap, scores, event=ev)
    assert scores.extension_risk_short < cfg.MAX_EXTENSION_RISK
    assert not filt.blocks(Side.SHORT, scores)


def test_this_impulse_extension_blocks_late_chase():
    from mark2.extension import ExtensionFilter
    from mark2.types import EventRecord

    cfg = Mark2Config()
    filt = ExtensionFilter(cfg)
    ev = EventRecord(
        event_id=2,
        event_type=EventType.MOMENTUM_EXPANSION,
        direction=Side.SHORT,
        started_ts=1.0,
        started_bar_time="b1",
        started_price=30220.0,
    )
    snap = MarketSnapshot(
        ts=8.0,
        price=30150.0,
        completed_bars=[],
        forming_bar={"time": "b1", "open": 30220.0, "high": 30222.0, "low": 30148.0},
        atr=32.0,
        vwap_distance_atr=-1.9,
        velocity=-4.0,
        acceleration=1.2,
    )
    scores = ScoreBundle()
    filt.update(snap, scores, event=ev)
    assert filt.blocks(Side.SHORT, scores)


def test_hud_snapshot_shape():
    cfg = _open_gates(Mark2Config())
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        snap = eng.hud_snapshot()
        assert snap["mode"] == "LIVE"
        assert "long" in snap and "short" in snap
        assert "log" in snap
        assert "trades" in snap
        assert snap["trades"] == []
        assert snap["pnlLog"]["count"] == 0
        assert snap["pnlLog"]["inTrade"] is False
        assert snap["sessionPnl"] == 0
        assert snap["accountSynced"] is False
        assert snap["equity"] == 0
        assert snap["state"] == "IDLE"


def test_observe_snapshot_includes_live_pnl():
    cfg = _open_gates(Mark2Config())
    cfg.MODE = RunMode.OBSERVE_ONLY.value
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        _seed(eng, _bars_compressed())
        o = 20000.0
        px = o
        for i in range(40):
            px += 0.45
            t = 1_700_000_400.0 + i * 0.1
            eng.on_tick(_tick(t, px, "live-5", o=o, h=px, lo=o - 0.2, vol=1600 + i * 30))
            if eng.paper is not None:
                break
        assert eng.paper is not None
        hud = eng.hud_snapshot()
        trade = hud["trade"]
        assert trade is not None
        assert trade["entry"] > 0
        assert "pnl" in trade
        assert "points" in trade
        assert trade["simulated"] is True
        assert eng.orders_submitted == 0
        rows = hud["trades"]
        assert rows and rows[0]["open"] is True
        assert rows[0]["side"] == trade["side"]
        assert rows[0]["entry"] == trade["entry"]
        assert hud["pnlLog"]["inTrade"] is True
        assert hud["pnlLog"]["count"] == 0


def test_levels_sent_on_observe_entry():
    class _Sink:
        def __init__(self) -> None:
            self.levels: list[dict] = []

        def send_order(self, *a, **k):
            return None

        def send_flat(self, *a, **k):
            return None

        def send_levels(self, **payload):
            self.levels.append(payload)

    cfg = _open_gates(Mark2Config())
    cfg.MODE = RunMode.OBSERVE_ONLY.value
    sink = _Sink()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", sink=sink)
        _seed(eng, _bars_compressed())
        o = 20000.0
        px = o
        for i in range(40):
            px += 0.45
            t = 1_700_000_500.0 + i * 0.1
            eng.on_tick(_tick(t, px, "live-6", o=o, h=px, lo=o - 0.2, vol=1600 + i * 30))
            if eng.paper is not None:
                break
        assert eng.paper is not None
        drawn = [x for x in sink.levels if not x.get("clear")]
        assert drawn
        assert drawn[0]["entry"] == eng.paper.entry
        assert drawn[0]["simulate"] is True
        eng.flatten_now()
        assert any(x.get("clear") for x in sink.levels)


def test_contracts_scale_bank_dollars():
    from mark2.exits import bank_dollars, bank_points

    cfg = Mark2Config()
    cfg.ENABLE_DAILY_GOAL = False
    cfg.TRAIL_ARM_USD = 15.0
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        assert eng.set_contracts(1, persist=False) == 1
        assert bank_dollars(1, cfg) == 15.0
        assert bank_points(cfg) == 7.5
        assert eng.set_contracts(3, persist=False) == 3
        # Total arm stays $15; points shrink with size
        assert bank_dollars(eng.cfg.contracts(), cfg) == 15.0
        trade = __import__("mark2.exits", fromlist=["PaperTrade"]).PaperTrade(
            side=Side.LONG,
            entry=20000.0,
            entry_ts=0.0,
            stop=19980.0,
            target=20000.0,
            peak=20000.0,
            trough=20000.0,
            qty=3,
            bank_dollars_locked=15.0,
        )
        assert abs(bank_points(cfg, trade=trade) - 2.5) < 1e-9
        snap = eng.hud_snapshot()
        assert snap["contracts"] == 3
        assert abs(float(snap["bankDollars"]) - 15.0) < 1e-6


def test_bank_then_trail_never_gives_back_twenty_five():
    from mark2.exits import PaperTrade, manage_paper

    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    entry = 20000.0
    arm = entry + 7.5
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=1.0,
        stop=19980.0,
        target=arm,
        peak=entry,
        trough=entry,
        qty=1,
        bank_dollars_locked=15.0,
    )
    done, _, _ = manage_paper(trade, price=arm, atr=20.0, health=90.0, hold_sec=20.0, cfg=cfg)
    assert done is False
    assert trade.target_touched is True
    # At bank print, stop floors at the $15 lock (not BE)
    assert abs(trade.stop - arm) < 1e-9
    # Tip runs — trail 5.5 behind, never below bank lock
    done, _, _ = manage_paper(trade, price=20020.0, atr=20.0, health=90.0, hold_sec=21.0, cfg=cfg)
    assert done is False
    assert trade.runner is True
    assert trade.stop == 20020.0 - 5.5
    assert trade.stop >= arm
    done, why, _ = manage_paper(
        trade, price=trade.stop, atr=20.0, health=90.0, hold_sec=22.0, cfg=cfg
    )
    assert done is True
    assert why == "TRAIL"
    pts = trade.stop - entry
    assert pts * cfg.POINT_VALUE >= 15.0


def test_multi_contract_bank_floor_not_breakeven():
    """5 contracts: $15 bank is only 1.5 pts — must floor at lock, not entry."""
    from mark2.exits import PaperTrade, bank_points, manage_paper

    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    cfg.POINT_VALUE = 2.0
    entry = 20000.0
    trade = PaperTrade(
        side=Side.LONG,
        entry=entry,
        entry_ts=1.0,
        stop=entry - 10.0,
        target=entry,
        peak=entry,
        trough=entry,
        qty=5,
        bank_dollars_locked=15.0,
    )
    arm_pts = bank_points(cfg, trade=trade)
    assert abs(arm_pts - 1.5) < 1e-9
    arm = entry + arm_pts
    trade.target = arm
    done, _, _ = manage_paper(trade, price=arm, atr=20.0, health=90.0, hold_sec=5.0, cfg=cfg)
    assert done is False
    assert trade.target_touched is True
    assert abs(trade.stop - arm) < 1e-9
    assert trade.stop > entry + 0.5
    # Pullback to bank lock exits BANK (~$15), not BREAKEVEN
    done, why, _ = manage_paper(
        trade, price=arm, atr=20.0, health=90.0, hold_sec=6.0, cfg=cfg
    )
    # sitting on lock does not flatten; one tick through does
    assert done is False
    done, why, _ = manage_paper(
        trade, price=arm - 0.25, atr=20.0, health=90.0, hold_sec=7.0, cfg=cfg
    )
    assert done is True
    assert why == "BANK"
    assert (arm - entry) * cfg.POINT_VALUE * 5 >= 14.0


def test_bank_print_does_not_flatten():
    """Touching the $15 arm must not flatten — trail rides until tip pullback."""
    from mark2.exits import PaperTrade, manage_paper

    cfg = Mark2Config()
    cfg.TRAIL_ARM_USD = 15.0
    cfg.RUNNER_TRAIL_POINTS = 5.5
    entry = 20100.0
    arm = entry - 7.5
    trade = PaperTrade(
        side=Side.SHORT,
        entry=entry,
        entry_ts=1.0,
        stop=20120.0,
        target=arm,
        peak=entry,
        trough=entry,
        qty=1,
        bank_dollars_locked=15.0,
    )
    done, _, st = manage_paper(trade, price=arm, atr=20.0, health=90.0, hold_sec=10.0, cfg=cfg)
    assert done is False
    assert trade.target_touched is True
    # tip-trail = arm+5.5 would be looser than bank lock → floor at lock
    assert abs(trade.stop - arm) < 1e-9
    for i in range(12):
        done, why, _ = manage_paper(
            trade, price=arm, atr=20.0, health=90.0, hold_sec=11.0 + i, cfg=cfg
        )
        assert done is False, why
    # Tip runs further, then trail hit
    manage_paper(trade, price=arm - 10.0, atr=20.0, health=90.0, hold_sec=25.0, cfg=cfg)
    assert trade.stop <= arm
    done, why, _ = manage_paper(
        trade, price=trade.stop, atr=20.0, health=90.0, hold_sec=30.0, cfg=cfg
    )
    assert done is True
    assert why in ("TRAIL", "BANK", "BREAKEVEN", "FLOOR")

def test_push_levels_does_not_flatten_short_at_bank():
    """Regression: bank touch logged MANAGE then _push_levels must not CLOSE."""
    from mark2.exits import lock_price

    class _Sink:
        def __init__(self) -> None:
            self.stops: list[float] = []
            self.flats: list[str] = []

        def send_order(self, *a, **k):
            return None

        def send_flat(self, reason: str = "") -> None:
            self.flats.append(reason)

        def send_levels(self, **payload):
            return None

        def send_stop(self, stop: float, reason: str = "") -> None:
            self.stops.append(float(stop))

    cfg = Mark2Config()
    cfg.MODE = RunMode.LIVE.value
    sink = _Sink()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", sink=sink)
        eng.risk.connected = True
        entry = 29586.75
        lock = lock_price(entry, Side.SHORT, cfg)
        from mark2.exits import PaperTrade

        eng.paper = PaperTrade(
            side=Side.SHORT,
            entry=entry,
            entry_ts=1.0,
            stop=29611.75,
            target=lock,
            peak=entry,
            trough=entry,
            qty=3,
            target_touched=True,
            mfe=12.5,
        )
        eng.paper.peak = lock
        eng.paper.stop = lock
        eng.last_snap = eng.last_snap or __import__("mark2.types", fromlist=["MarketSnapshot"]).MarketSnapshot(
            ts=2.0,
            price=lock,
            completed_bars=[],
            forming_bar=None,
        )
        eng._last_levels = None
        eng._push_levels()
        assert eng.paper is not None
        assert sink.flats == []
        assert sink.stops
        assert sink.stops[-1] >= lock - 0.01


def test_push_levels_sends_ema_protect_when_stop_moves():
    """$100 trail must reach NT — do not keep the original catastrophic stop."""

    class _Sink:
        def __init__(self) -> None:
            self.stops: list[float] = []

        def send_levels(self, **payload):
            return None

        def send_stop(self, stop: float, reason: str = "") -> None:
            self.stops.append(float(stop))

    cfg = Mark2Config()
    cfg.MODE = RunMode.LIVE.value
    sink = _Sink()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", sink=sink)
        from mark2.exits import PaperTrade

        eng.paper = PaperTrade(
            side=Side.LONG,
            entry=29336.50,
            entry_ts=1.0,
            stop=29259.75,
            target=0.0,
            peak=29336.50,
            trough=29336.50,
            hard_stop=29259.75,
            ema_strategy=True,
            ema_trade_state="CONFIRMED",
            runner_trail_on=True,
        )
        eng._last_levels = None
        eng._push_levels()
        assert sink.stops[-1] == 29259.75
        eng.paper.stop = 29401.75
        eng._push_levels()
        assert abs(sink.stops[-1] - 29401.75) < 1e-9
        n = len(sink.stops)
        eng._push_levels()
        assert len(sink.stops) == n


def test_choppy_regime_does_not_arm():
    from mark2.state_machine import Mark2StateMachine
    from mark2.types import EventRecord, RejectReason as RR

    cfg = Mark2Config()
    cfg.REQUIRE_TRENDING = True
    cfg.ENABLE_CHOP_SCALP = False
    sm = Mark2StateMachine(cfg)
    ev = EventRecord(
        event_id=1,
        event_type=EventType.MOMENTUM_EXPANSION,
        direction=Side.SHORT,
        started_ts=1.0,
        started_bar_time="b1",
        started_price=30170.0,
    )
    scores = ScoreBundle(
        long_confidence=20.0,
        short_confidence=90.0,
        short_opportunity=90.0,
        short_conf_velocity=5.0,
    )
    state, reject = sm.evaluate_entry(
        ts=10.0,
        event=ev,
        scores=scores,
        extension_blocks=False,
        volume_ok=True,
        structure_ok=True,
        trend_ok=False,
    )
    assert reject == RR.REJECT_REGIME
    assert state.value != "TRADE_ARMED"


def test_classify_chop_blocks_longs_and_shorts():
    from mark2.context import classify_trend

    bars = []
    px = 20000.0
    for i in range(40):
        px = 20000.0 + (12.0 if i % 2 == 0 else -12.0)
        bars.append(
            {
                "time": f"c{i}",
                "open": px,
                "high": px + 4,
                "low": px - 4,
                "close": px,
                "volume": 400,
            }
        )
    out = classify_trend(bars, ema_period=20, atr_period=14)
    assert out["regime"] == "CHOPPY"
    assert out["longs"] is False
    assert out["shorts"] is False


def test_stop_points_drive_initial_stop_and_hud():
    from mark2.exits import initial_stop, stop_points

    cfg = Mark2Config()
    cfg.INITIAL_STOP_POINTS = 12.0
    assert stop_points(cfg) == 12.0
    assert initial_stop(20000.0, Side.LONG, 40.0, cfg) == 19988.0
    assert initial_stop(20000.0, Side.SHORT, 40.0, cfg) == 20012.0
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        assert eng.set_stop_points(25, persist=False) == 25.0
        snap = eng.hud_snapshot()
        assert snap["stopPoints"] == 25.0
        assert snap["stopDollars"] == 25.0 * cfg.POINT_VALUE * eng.cfg.contracts()


def test_closed_observe_trade_appears_in_snapshot_ledger():
    cfg = _open_gates(Mark2Config())
    cfg.MODE = RunMode.OBSERVE_ONLY.value
    cfg.ENABLE_MOMENTUM_EXIT = False
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        _seed(eng, _bars_compressed())
        o = 20000.0
        px = o
        opened_at = None
        for i in range(40):
            px += 0.45
            t = 1_700_000_700.0 + i * 0.1
            eng.on_tick(_tick(t, px, "live-8", o=o, h=px, lo=o - 0.2, vol=1600 + i * 30))
            if eng.paper is not None:
                opened_at = t
                break
        assert eng.paper is not None
        side = eng.paper.side
        entry = eng.paper.entry
        qty = eng.paper.qty
        stop = eng.paper.stop
        eng.on_tick(
            _tick(
                opened_at + 0.2,
                stop,
                "live-8",
                o=o,
                h=max(px, stop),
                lo=min(o, stop),
                vol=1800,
            )
        )
        assert eng.paper is None
        hud = eng.hud_snapshot()
        trades = hud["trades"]
        assert trades
        row = trades[0]
        assert row["open"] is False
        assert row["side"] == side.value
        assert row["entry"] == round(entry, 2)
        assert row["exit"] == round(stop, 2)
        assert row["qty"] == qty
        assert row["reason"] in ("STOP", "ATR_STOP", "CATASTROPHIC_STOP")
        assert "pnl" in row
        assert "pts" in row
        assert hud["pnlLog"]["count"] == 1
        assert hud["stats"]["trades"] == 1
        if row["pnl"] > 0:
            assert hud["pnlLog"]["wins"] == 1
        elif row["pnl"] < 0:
            assert hud["pnlLog"]["losses"] == 1


def test_engine_stats_clear_session():
    st = EngineStats(engine="ReconSniper")
    st.record(
        side="LONG",
        pnl=12.5,
        points=6.25,
        fees=2.48,
        mfe=8.0,
        mae=1.0,
        hold_sec=12.0,
        scratch=False,
        hour=10,
        event_type="IMPULSE",
        confidence=70.0,
        opportunity=65.0,
    )
    assert st.trades == 1
    assert st.wins == 1
    assert st.net_pnl == 12.5
    st.clear_session()
    s = st.summary()
    assert s["trades"] == 0
    assert s["wins"] == 0
    assert s["losses"] == 0
    assert s["net_pnl_after_fees"] == 0.0
    assert s["by_hour"] == {}
    assert s["by_event"] == {}


def test_clear_session_zeros_hud_ledger():
    cfg = Mark2Config()
    assert cfg.mode() == RunMode.LIVE
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        eng.stats.record(
            side="SHORT",
            pnl=-8.0,
            points=-4.0,
            fees=2.48,
            mfe=1.0,
            mae=5.0,
            hold_sec=9.0,
            scratch=False,
            hour=11,
            event_type="BREAKOUT",
            confidence=60.0,
            opportunity=55.0,
        )
        eng.closed_trades.appendleft({"pnl": -8.0, "open": False, "side": "SHORT"})
        eng.risk.daily_pnl = -8.0
        hud = eng.hud_snapshot()
        assert hud["stats"]["trades"] == 1
        assert hud["pnlLog"]["net"] == -8.0
        out = eng.clear_session()
        assert out["trades"] == 0
        hud2 = eng.hud_snapshot()
        assert hud2["stats"]["trades"] == 0
        assert hud2["stats"]["wins"] == 0
        assert hud2["stats"]["losses"] == 0
        assert hud2["stats"]["net_pnl_after_fees"] == 0.0
        assert hud2["pnlLog"]["net"] == 0.0
        assert hud2["pnlLog"]["count"] == 0
        assert hud2["sessionPnl"] == 0.0
        assert [r for r in hud2["trades"] if not r.get("open")] == []
        assert eng.risk.daily_pnl == 0.0
        assert eng.cfg.mode() == RunMode.LIVE


def test_apply_account_heartbeat_reaches_snapshot():
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        hud = eng.hud_snapshot()
        assert hud["equity"] == 0
        assert hud["accountSynced"] is False
        assert hud["sessionPnl"] == 0
        eng.apply_account(
            {
                "type": "heartbeat",
                "account": "Sim101",
                "cash_value": 50123.45,
                "net_liquidation": 50200.10,
                "unrealized_pnl": 76.65,
                "buying_power": 100000,
                "instrument": "MNQ JUN26",
            }
        )
        hud = eng.hud_snapshot()
        assert hud["cash"] == 50123.45
        assert hud["equity"] == 50200.10
        assert hud["net_liquidation"] == 50200.10
        assert hud["unrealized"] == 76.65
        assert hud["buying_power"] == 100000
        assert hud["accountSynced"] is True
        assert hud["account"] == "Sim101"
        assert hud["instrument"] == "MNQ JUN26"
        eng.apply_account({"type": "heartbeat", "position": 0, "last": 20100})
        hud2 = eng.hud_snapshot()
        assert hud2["equity"] == 50200.10
        assert hud2["cash"] == 50123.45
        assert hud2["accountSynced"] is True
        # Heartbeats always send wallet keys; 0 must not wipe a real balance
        eng.apply_account(
            {
                "type": "heartbeat",
                "account": "Sim101",
                "cash_value": 0,
                "net_liquidation": 0,
                "sod_cash": 0,
                "buying_power": 0,
            }
        )
        hud_keep = eng.hud_snapshot()
        assert hud_keep["equity"] == 50200.10
        assert hud_keep["cash"] == 50123.45
        eng.stats.record(
            side="LONG",
            pnl=12.5,
            points=6.25,
            fees=2.48,
            mfe=8.0,
            mae=1.0,
            hold_sec=12.0,
            scratch=False,
            hour=10,
            event_type="IMPULSE",
            confidence=70.0,
            opportunity=65.0,
        )
        hud3 = eng.hud_snapshot()
        assert hud3["pnlLog"]["net"] == 12.5
        assert hud3["pnlLog"]["botNet"] == 12.5
        # Session net follows NT (realized+unrealized), not bot ledger only.
        assert hud3["sessionPnl"] == 76.65
        assert hud3["pnlLog"]["session"] == 76.65
        assert hud3["pnlLog"]["fromNt"] is True


def test_heartbeat_last_does_not_reprice_open_trade():
    """Paused replay still heartbeats Close[0]; that must not move open PnL."""
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        rt = Mark2Runtime(cfg, persist_path=Path(td) / "s.json")
        for bar in _bars_compressed(20, start=29200.0):
            rt.engine.on_bar_close(bar, seed=True)
        rt.engine.paper = PaperTrade(
            side=Side.LONG,
            entry=29253.50,
            entry_ts=1_700_000_000.0,
            stop=29205.50,
            target=29400.0,
            peak=29280.0,
            trough=29240.0,
            qty=1,
            mfe=26.5,
            mae=13.5,
            hard_stop=29205.50,
        )
        rt._on_message({"type": "tick", "last": 29266.75, "time": 1_700_000_100.0})
        hud = rt.engine.hud_snapshot()
        assert hud["trade"] is not None
        assert hud["trade"]["price"] == 29266.75
        profit = hud["trade"]["pnl"]
        assert profit > 0
        rt._on_message(
            {
                "type": "heartbeat",
                "last": 29100.0,
                "position": 0,
                "realized_pnl": 0,
                "unrealized_pnl": -200.0,
                "cash_value": 100000,
                "net_liquidation": 100000,
            }
        )
        hud2 = rt.engine.hud_snapshot()
        assert rt.engine.paper is not None
        assert hud2["trade"]["price"] == 29266.75
        assert hud2["trade"]["pnl"] == profit
        assert hud2["sessionPnl"] == profit
        assert hud2["pnlLog"]["fromNt"] is False


def test_paper_only_session_pnl_follows_tape():
    """Scout / replay paper fills are not on the NT book — hero follows the tape."""
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        eng.paper = PaperTrade(
            side=Side.LONG,
            entry=29253.50,
            entry_ts=1.0,
            stop=29205.50,
            target=29400.0,
            peak=29266.75,
            trough=29253.50,
            qty=1,
        )
        eng.last_snap = MarketSnapshot(
            ts=2.0,
            price=29266.75,
            completed_bars=[],
            forming_bar=None,
            ema=29250.0,
            vwap=29240.0,
            atr=50.0,
        )
        eng.apply_account(
            {
                "type": "heartbeat",
                "position": 0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "cash_value": 100000,
                "net_liquidation": 100000,
            }
        )
        hud = eng.hud_snapshot()
        assert hud["trade"]["pnl"] == 26.5
        assert hud["sessionPnl"] == 26.5
        assert hud["pnlLog"]["fromNt"] is False


def test_nt_session_pnl_includes_manual_trades():
    """HUD session net uses NT account PnL so manual chart fills count."""
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        eng.apply_account(
            {
                "type": "heartbeat",
                "account": "Sim101",
                "cash_value": 50000,
                "net_liquidation": 50000,
                "realized_pnl": 42.50,
                "unrealized_pnl": 18.25,
                "instrument": "MNQ JUN26",
            }
        )
        hud = eng.hud_snapshot()
        assert hud["sessionPnl"] == 60.75
        assert hud["pnlLog"]["net"] == 0.0
        assert hud["pnlLog"]["fromNt"] is True
        assert hud["realized"] == 42.50
        assert hud["unrealized"] == 18.25
        eng.apply_account(
            {
                "type": "fill",
                "order_name": "Manual Buy",
                "realized_pnl": 55.00,
                "unrealized_pnl": 12.00,
            }
        )
        hud2 = eng.hud_snapshot()
        assert hud2["sessionPnl"] == 67.0
        assert hud2["pnlLog"]["net"] == 0.0


def test_clear_session_rebaselines_nt_session_pnl():
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        eng.apply_account(
            {
                "type": "heartbeat",
                "account": "Sim101",
                "realized_pnl": 100.0,
                "unrealized_pnl": 25.0,
            }
        )
        assert eng.hud_snapshot()["sessionPnl"] == 125.0
        eng.clear_session()
        assert eng.hud_snapshot()["sessionPnl"] == 0.0
        eng.apply_account({"type": "heartbeat", "realized_pnl": 130.0, "unrealized_pnl": 10.0})
        assert eng.hud_snapshot()["sessionPnl"] == 15.0


def test_apply_account_zero_net_uses_cash():
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        eng.apply_account(
            {
                "type": "heartbeat",
                "account": "Sim101",
                "cash_value": 50123.45,
                "net_liquidation": 0,
                "sod_cash": 0,
                "buying_power": 0,
            }
        )
        hud = eng.hud_snapshot()
        assert hud["cash"] == 50123.45
        assert hud["equity"] == 50123.45
        assert hud["accountSynced"] is True


def test_apply_account_buying_power_fallback():
    cfg = Mark2Config()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        eng.apply_account(
            {
                "type": "heartbeat",
                "account": "Sim101",
                "cash_value": 0,
                "net_liquidation": 0,
                "sod_cash": 0,
                "buying_power": 100000,
            }
        )
        hud = eng.hud_snapshot()
        assert hud["equity"] == 100000
        assert hud["buying_power"] == 100000
        assert hud["accountSynced"] is True


def test_manual_buy_works_when_disarmed():
    cfg = _open_gates(Mark2Config())
    cfg.ENABLE_EMA_STRATEGY = False
    cfg.ALLOW_LEGACY_ENTRIES = True
    cfg.MODE = RunMode.OBSERVE_ONLY.value
    cfg.MARK2_ENABLED = False
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl")
        _seed(eng, _bars_compressed())
        o = 20000.0
        px = o
        for i in range(20):
            px += 0.1
            t = 1_700_001_000.0 + i * 0.1
            eng.on_tick(_tick(t, px, "live-m", o=o, h=px, lo=o - 0.2, vol=900))
        out = eng.manual_order("BUY")
        assert out["ok"] is True
        assert eng.paper is not None
        assert eng.paper.side == Side.LONG
        assert eng.paper.event_type == "HUD_MANUAL"
        blocked = eng.manual_order("SELL")
        assert blocked["ok"] is False
        assert blocked["error"] == "IN_TRADE"
        eng.flatten_now("HUD_FLAT")
        assert eng.paper is None


def test_manual_live_sends_order():
    class _Sink:
        def __init__(self):
            self.orders = []
            self.flats = []

        def send_order(self, action, *, quantity=1, stop_loss=None, reason=""):
            self.orders.append(
                {"action": action, "quantity": quantity, "stop": stop_loss, "reason": reason}
            )

        def send_flat(self, reason=""):
            self.flats.append(reason)

    cfg = Mark2Config()
    cfg.ENABLE_EMA_STRATEGY = False
    cfg.ALLOW_LEGACY_ENTRIES = True
    cfg.MARK2_ENABLED = False
    sink = _Sink()
    with tempfile.TemporaryDirectory() as td:
        eng = Mark2Engine(cfg, log_path=Path(td) / "d.jsonl", sink=sink)
        _seed(eng, _bars_compressed())
        o = 20000.0
        eng.on_tick(_tick(1_700_001_100.0, o, "live-m2", o=o, h=o, lo=o - 1, vol=800))
        out = eng.manual_order("SELL")
        assert out["ok"] is True
        assert len(sink.orders) == 1
        assert sink.orders[0]["action"] == "SELL"
        eng.flatten_now()
        assert sink.flats


if __name__ == "__main__":
    test_default_mode_is_live()
    test_disable_stays_live()
    test_observe_never_submits_orders()
    test_forming_bar_has_no_lookahead()
    test_event_identity_in_isolation()
    test_duplicate_event_does_not_rearm_every_tick()
    test_paper_mode_can_open_and_track_mfe()
    test_live_without_bridge_does_not_submit()
    test_package_does_not_import_mark1()
    test_vwap_distance_does_not_hard_block()
    test_this_impulse_extension_blocks_late_chase()
    test_hud_snapshot_shape()
    test_observe_snapshot_includes_live_pnl()
    test_levels_sent_on_observe_entry()
    test_contracts_scale_bank_dollars()
    test_bank_then_trail_never_gives_back_twenty_five()
    test_bank_print_does_not_flatten()
    test_choppy_regime_does_not_arm()
    test_classify_chop_blocks_longs_and_shorts()
    test_stop_points_drive_initial_stop_and_hud()
    test_closed_observe_trade_appears_in_snapshot_ledger()
    test_engine_stats_clear_session()
    test_clear_session_zeros_hud_ledger()
    test_apply_account_heartbeat_reaches_snapshot()
    test_heartbeat_last_does_not_reprice_open_trade()
    test_paper_only_session_pnl_follows_tape()
    test_nt_session_pnl_includes_manual_trades()
    test_clear_session_rebaselines_nt_session_pnl()
    test_apply_account_zero_net_uses_cash()
    test_apply_account_buying_power_fallback()
    print("mark2 tests passed")
