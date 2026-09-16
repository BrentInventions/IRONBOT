"""Replay Recon Sniper against 2Brains MNQ .Last.txt (1-second) holdout data."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.config import Mark2Config, load_config
from mark2.engine import Mark2Engine
from mark2.experimental import apply_experimental_profile, restore_factory_profile
from mark2.types import RunMode, Tick

TWOBRAINS = Path(r"C:\Users\TheRe\OneDrive\Desktop\2Brains")
MANIFEST = TWOBRAINS / "strategies" / "frozen" / "champion_67_7pct_20260729" / "validation_manifest.json"
ET = ZoneInfo("America/New_York")


def load_paths(limit: int | None = None, dates: list[str] | None = None) -> list[Path]:
    if MANIFEST.is_file():
        rows = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
        paths = [Path(r["path"]) for r in rows if Path(r["path"]).is_file()]
    else:
        paths = []
    data = TWOBRAINS / "data"
    if not paths:
        paths = sorted(data.glob("MNQ *.Last.txt"))
    if dates:
        wanted: list[Path] = []
        seen: set[str] = set()
        for day in dates:
            hit = next((p for p in paths if day in p.name), None)
            if hit is None:
                hit = data / f"MNQ {day}.Last.txt"
            if hit.is_file() and hit.name not in seen:
                wanted.append(hit)
                seen.add(hit.name)
        paths = wanted
    if limit:
        paths = paths[:limit]
    return paths


def parse_last_file(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(";")
        if len(parts) < 6:
            continue
        try:
            dt = datetime.strptime(parts[0].strip(), "%Y%m%d %H%M%S").replace(tzinfo=ET)
            o, h, lo, c, vol = (float(parts[i]) for i in range(1, 6))
        except ValueError:
            continue
        rows.append(
            {
                "ts": dt.timestamp(),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": vol,
                "minute": dt.strftime("%Y%m%d%H%M"),
            }
        )
    return rows


def synthesize_intrabar_ticks(bar: dict, *, ticks_per_bar: int = 24) -> list[dict]:
    """Expand one OHLC minute into sub-minute ticks so velocity/build gates can fire."""
    n = max(4, int(ticks_per_bar))
    o = float(bar["open"])
    h = float(bar["high"])
    lo = float(bar["low"])
    c = float(bar["close"])
    vol = float(bar["volume"])
    start_ts = float(bar["ts"])
    bar_time = str(bar["time"])
    span = max(59.0, 60.0 - (60.0 / n))
    if c >= o:
        anchors = [o, h, lo, c]
    else:
        anchors = [o, lo, h, c]

    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    prices: list[float] = []
    seg = len(anchors) - 1
    for i in range(n):
        t = i / max(n - 1, 1)
        pos = t * seg
        idx = min(int(pos), seg - 1)
        frac = pos - idx
        prices.append(_lerp(anchors[idx], anchors[idx + 1], frac))

    out: list[dict] = []
    for i, px in enumerate(prices):
        ts = start_ts + (span * i / max(n - 1, 1))
        forming_vol = vol * (i + 1) / n
        out.append(
            {
                "ts": ts,
                "price": px,
                "volume": vol / n,
                "bar_time": bar_time,
                "forming_open": o,
                "forming_high": max(prices[: i + 1]),
                "forming_low": min(prices[: i + 1]),
                "forming_volume": forming_vol,
            }
        )
    return out


def aggregate_minutes(seconds: list[dict]) -> list[dict]:
    if not seconds:
        return []
    out: list[dict] = []
    cur_key = seconds[0]["minute"]
    o = seconds[0]["open"]
    h = seconds[0]["high"]
    lo = seconds[0]["low"]
    c = seconds[0]["close"]
    vol = seconds[0]["volume"]
    ts = seconds[0]["ts"]
    for row in seconds[1:]:
        if row["minute"] != cur_key:
            out.append(
                {
                    "time": cur_key,
                    "ts": ts,
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": c,
                    "volume": vol,
                }
            )
            cur_key = row["minute"]
            o, h, lo, c, vol, ts = (
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["volume"],
                row["ts"],
            )
        else:
            h = max(h, row["high"])
            lo = min(lo, row["low"])
            c = row["close"]
            vol += row["volume"]
            ts = row["ts"]
    out.append(
        {
            "time": cur_key,
            "ts": ts,
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": vol,
        }
    )
    return out


def make_engine(cfg: Mark2Config, *, tag: str = "run") -> Mark2Engine:
    log = Path(__file__).resolve().parent / "logs" / f"replay_{tag}.jsonl"
    eng = Mark2Engine(cfg, log_path=log, persist_path=log)
    eng.cfg.MODE = RunMode.PAPER_TRADE.value
    eng.risk.connected = True
    eng.risk.enabled = True
    eng.cfg.MARK2_ENABLED = True
    return eng


def replay_file(
    eng: Mark2Engine,
    path: Path,
    *,
    warmup_minutes: int = 20,
    ticks_per_bar: int = 24,
) -> list[dict]:
    seconds = parse_last_file(path)
    if len(seconds) < 60:
        return []
    minutes = aggregate_minutes(seconds)
    trades_before = len(eng.closed_trades)

    for mi, bar in enumerate(minutes):
        bar_time = str(bar["time"])
        synth = synthesize_intrabar_ticks(bar, ticks_per_bar=ticks_per_bar)
        for s in synth:
            tick = Tick(
                ts=s["ts"],
                price=s["price"],
                volume=s["volume"],
                bar_time=bar_time,
                forming_open=s["forming_open"],
                forming_high=s["forming_high"],
                forming_low=s["forming_low"],
                forming_volume=s["forming_volume"],
            )
            if mi >= warmup_minutes:
                eng.on_tick(tick)
        eng.on_bar_close(
            {
                "time": bar_time,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
            }
        )

    if eng.paper is not None and eng.last_snap is not None and eng.last_scores is not None:
        px = float(eng.last_snap.price)
        eng._close_position(
            Tick(ts=float(eng.last_snap.ts), price=px),
            eng.last_snap,
            eng.last_scores,
            "REPLAY_EOD",
        )

    new_trades = list(eng.closed_trades)[trades_before:]
    for t in new_trades:
        t["file"] = path.name
    return new_trades


def make_cfg(*, experimental: bool) -> Mark2Config:
    cfg = load_config()
    cfg.MODE = RunMode.PAPER_TRADE.value
    cfg.MARK2_ENABLED = True
    cfg.ENABLE_CHOP_SCALP = False
    if experimental:
        apply_experimental_profile(cfg)
    else:
        restore_factory_profile(cfg)
    return cfg


def make_ema_cfg() -> Mark2Config:
    """Current Mark II EMA path: longs only, pullback, cat stop, dynamic purple trail."""
    cfg = load_config()
    cfg.MODE = RunMode.PAPER_TRADE.value
    cfg.MARK2_ENABLED = True
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.ALLOW_LEGACY_ENTRIES = False
    cfg.ENABLE_EXPERIMENTAL_PROFILE = False
    cfg.ENABLE_CHOP_SCALP = False
    cfg.ENABLE_CHOPPY_BIAS = False
    cfg.ENABLE_CHAOTIC_BANK = False
    cfg.ENABLE_BOOK_PATTERNS = False
    cfg.ENABLE_EXHAUSTION_FILTER = False
    cfg.ENABLE_DAILY_GOAL = False
    cfg.EMA_ALLOW_LONG = True
    cfg.EMA_ALLOW_SHORT = False
    cfg.EMA_LONG_SNIPER = True
    cfg.EMA_LONG_REQUIRES_BEARISH = True
    cfg.EMA_SHORT_SNIPER = True
    cfg.EMA_SHORT_REQUIRES_BULLISH = True
    cfg.ENABLE_PULLBACK_ENTRY = True
    cfg.PULLBACK_ENTRY_ON_BAR_CLOSE = True
    cfg.ENABLE_RUNNER_TRAIL = True
    return cfg


def summarize_file(trades: list[dict]) -> dict:
    n = len(trades)
    pnls = [float(t.get("pnl") or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    return {
        "file": trades[0].get("file") if trades else "",
        "trades": n,
        "wins": len(wins),
        "losses": n - len(wins),
        "net_pnl": round(sum(pnls), 2) if n else 0.0,
        "win_rate": round(len(wins) / n, 3) if n else 0.0,
    }


def summarize(label: str, trades: list[dict], cfg: Mark2Config) -> dict:
    n = len(trades)
    if n == 0:
        return {"label": label, "trades": 0, "net_pnl": 0.0, "by_exit": {}, "by_event": {}}
    pnls = [float(t.get("pnl") or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    mfe_sum = sum(float(t.get("mfe") or 0) for t in trades)
    mae_sum = sum(float(t.get("mae") or 0) for t in trades)
    capture = []
    for t in trades:
        mfe = float(t.get("mfe") or 0)
        pts = float(t.get("pts") or 0)
        if mfe > 0 and pts > 0:
            capture.append(pts / mfe * 100.0)
    exits = Counter(str(t.get("reason") or "?") for t in trades)
    events = Counter(str(t.get("event_type") or "?") for t in trades)
    banked = sum(1 for t in trades if float(t.get("mfe") or 0) >= 12.5)
    by_file: dict[str, list[dict]] = {}
    for t in trades:
        by_file.setdefault(str(t.get("file") or "?"), []).append(t)
    left_on_table = []
    for t in trades:
        mfe = float(t.get("mfe") or 0)
        pts = float(t.get("pts") or 0)
        if mfe > pts:
            left_on_table.append(mfe - pts)
    return {
        "label": label,
        "profile": (
            "ema_longs"
            if bool(getattr(cfg, "ENABLE_EMA_STRATEGY", False))
            else ("experimental_phase1" if cfg.ENABLE_EXPERIMENTAL_PROFILE else "factory")
        ),
        "contracts": int(cfg.contracts()),
        "files_replayed": len({t.get("file") for t in trades}),
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n, 3),
        "net_pnl": round(sum(pnls), 2),
        "expectancy": round(sum(pnls) / n, 2),
        "profit_factor": round(pf, 2),
        "avg_winner": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loser": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "avg_mfe_pts": round(mfe_sum / n, 2),
        "avg_mae_pts": round(mae_sum / n, 2),
        "mfe_capture_pct": round(sum(capture) / len(capture), 1) if capture else 0.0,
        "avg_left_on_table_pts": round(sum(left_on_table) / len(left_on_table), 2) if left_on_table else 0.0,
        "bank_reached_est": banked,
        "by_exit": dict(exits),
        "by_event": dict(events),
        "by_file": [summarize_file(rows) for rows in by_file.values()],
        "trail_arm_pts": float(getattr(cfg, "TRAIL_ARM_POINTS", 2.0)),
        "conf_threshold": float(cfg.LONG_CONFIDENCE_THRESHOLD),
    }


def run_profile(label: str, *, experimental: bool, paths: list[Path]) -> dict:
    cfg = make_cfg(experimental=experimental)
    all_trades: list[dict] = []
    for path in paths:
        tag = f"{label}_{path.stem.replace(' ', '_')}"
        eng = make_engine(cfg, tag=tag)
        all_trades.extend(replay_file(eng, path))
    summary = summarize(label, all_trades, cfg)
    summary["trades_sample"] = all_trades[:8]
    return summary


def run_ema_profile(paths: list[Path]) -> dict:
    cfg = make_ema_cfg()
    all_trades: list[dict] = []
    for i, path in enumerate(paths, 1):
        print(f"  [{i}/{len(paths)}] {path.name}", flush=True)
        tag = f"ema_{path.stem.replace(' ', '_')}"
        eng = make_engine(cfg, tag=tag)
        day = replay_file(eng, path)
        print(f"      {len(day)} trades  net {sum(float(t.get('pnl') or 0) for t in day):+.2f}", flush=True)
        all_trades.extend(day)
    summary = summarize("ema_longs", all_trades, cfg)
    summary["trades_all"] = all_trades
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Replay Recon Sniper on 2Brains MNQ holdouts")
    ap.add_argument("--limit", type=int, default=0, help="Max day files (0 = all manifest)")
    ap.add_argument("--dates", default="", help="Comma-separated YYYY-MM-DD chart dates")
    ap.add_argument("--ema", action="store_true", help="Current EMA longs-only strategy")
    ap.add_argument("--factory-only", action="store_true")
    ap.add_argument("--experimental-only", action="store_true")
    args = ap.parse_args()

    dates = [d.strip() for d in str(args.dates or "").split(",") if d.strip()]
    limit = args.limit if args.limit > 0 else None
    paths = load_paths(limit, dates or None)
    if not paths:
        print(f"No data files found under {TWOBRAINS / 'data'}")
        return 1

    print(f"2Brains replay · {len(paths)} MNQ day files · PAPER mode")
    results: dict = {"files": [p.name for p in paths], "runs": []}

    if args.ema:
        print("\nEMA longs-only (pullback + cat stop + dynamic runner trail)…")
        ema = run_ema_profile(paths)
        results["runs"].append({k: v for k, v in ema.items() if k != "trades_all"})
        results["trades"] = ema.get("trades_all") or []
        print(json.dumps({k: v for k, v in ema.items() if k != "trades_all"}, indent=2))
    else:
        if not args.experimental_only:
            print("\n[1/2] Factory profile…")
            factory = run_profile("factory", experimental=False, paths=paths)
            results["runs"].append(factory)
            print(json.dumps({k: v for k, v in factory.items() if k != "trades_sample"}, indent=2))

        if not args.factory_only:
            print("\n[2/2] Mark II experimental (Phase 1)…")
            exp = run_profile("experimental", experimental=True, paths=paths)
            results["runs"].append(exp)
            print(json.dumps({k: v for k, v in exp.items() if k != "trades_sample"}, indent=2))

    out = Path(__file__).resolve().parent / "logs" / "replay_2brains_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
