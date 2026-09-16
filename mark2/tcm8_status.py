"""Live 8TCM state-machine board. Written by the bot, read by an external CMD."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .tcm8 import (
    REJ_ARMED,
    REJ_BARRIER,
    REJ_BRIDGE,
    REJ_CHASE,
    REJ_COOLDOWN,
    REJ_EARLY,
    REJ_SIDE,
    REJ_STOP,
    REJ_TARGET_R,
    ST_EMA8_REJECTION_CONFIRMED,
    ST_EMA8_TESTING,
    ST_READY_TO_EXECUTE,
    ST_RUNNER_ACTIVE,
    ST_TARGET_REACHED,
    ST_TRADE_ACTIVE,
    ST_TRADE_COMPLETE,
    ST_TREND_CONFIRMED,
    ST_WAITING_FOR_REJECTION,
    ST_WAITING_FOR_RETRACEMENT,
    ST_WAITING_FOR_TREND,
    tcm8_enabled,
)

STEP_WAITING_TREND = "WAITING_FOR_TREND"
STEP_TREND = "TREND_CONFIRMED (HH/HL or LH/LL)"
STEP_RETRACE = "WAITING_FOR_RETRACEMENT"
STEP_TEST = "EMA8_TESTING"
STEP_WAIT_REJ = "WAITING_FOR_REJECTION"
STEP_REJ = "EMA8_REJECTION_CONFIRMED (close back on trend side)"
STEP_GATES = "room / chase / stop / ARM / NT / flat"
STEP_READY = "READY_TO_EXECUTE"
STEP_TRADE = "TRADE_ACTIVE (initial stop only)"
STEP_TARGET = "PRIMARY TARGET"

STEPS: tuple[str, ...] = (
    STEP_WAITING_TREND,
    STEP_TREND,
    STEP_RETRACE,
    STEP_TEST,
    STEP_WAIT_REJ,
    STEP_REJ,
    STEP_GATES,
    STEP_READY,
    STEP_TRADE,
    STEP_TARGET,
)

_GATE_REASONS = {
    REJ_CHASE,
    REJ_BARRIER,
    REJ_TARGET_R,
    REJ_STOP,
    REJ_ARMED,
    REJ_BRIDGE,
    REJ_COOLDOWN,
    REJ_SIDE,
    REJ_EARLY,
}

_last_stamp = ""
_last_write = 0.0


def _under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "pytest" in sys.modules


def _pytest_scratch_dir() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or os.getcwd())


def tcm8_status_path() -> Path:
    override = os.environ.get("MARK2_TCM8_STATUS")
    if override:
        return Path(override)
    if _under_pytest():
        return _pytest_scratch_dir() / "tcm8_status_pytest.json"
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.getcwd()
    from .config import settings_app_name

    folder = Path(base) / settings_app_name()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "tcm8_status.json"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_tcm8_status() -> dict[str, Any]:
    path = tcm8_status_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def pipeline_index(
    *,
    state: str,
    reason: str = "",
    accept: bool = False,
    in_trade: bool = False,
    runner: bool = False,
    primary_hit: bool = False,
    complete: bool = False,
) -> int:
    """Current step in STEPS. Done steps are everything before this index."""
    if complete:
        return len(STEPS) - 1
    if in_trade:
        if runner or primary_hit or state in (ST_RUNNER_ACTIVE, ST_TARGET_REACHED):
            return STEPS.index(STEP_TARGET)
        return STEPS.index(STEP_TRADE)
    if accept or state == ST_READY_TO_EXECUTE:
        return STEPS.index(STEP_READY)
    if reason in _GATE_REASONS:
        return STEPS.index(STEP_GATES)
    st = str(state or ST_WAITING_FOR_TREND)
    mapping = {
        ST_WAITING_FOR_TREND: STEP_WAITING_TREND,
        ST_TREND_CONFIRMED: STEP_TREND,
        ST_WAITING_FOR_RETRACEMENT: STEP_RETRACE,
        ST_EMA8_TESTING: STEP_TEST,
        ST_WAITING_FOR_REJECTION: STEP_WAIT_REJ,
        ST_EMA8_REJECTION_CONFIRMED: STEP_REJ,
        ST_READY_TO_EXECUTE: STEP_READY,
        ST_TRADE_ACTIVE: STEP_TRADE,
        ST_TARGET_REACHED: STEP_TARGET,
        ST_RUNNER_ACTIVE: STEP_TARGET,
        ST_TRADE_COMPLETE: STEP_TARGET,
    }
    label = mapping.get(st, STEP_WAITING_TREND)
    return STEPS.index(label)


def build_tcm8_board(
    *,
    enabled: bool,
    row: dict[str, Any] | None = None,
    trade: Any = None,
    armed: bool = False,
    connected: bool = False,
    flat: bool = True,
    runner_enabled: bool = False,
    mode: str = "",
    price: float = 0.0,
    exit_reason: str = "",
) -> dict[str, Any]:
    row = dict(row or {})
    in_trade = trade is not None and bool(getattr(trade, "tcm8", False))
    runner = bool(in_trade and getattr(trade, "tcm8_runner", False))
    primary_hit = bool(in_trade and getattr(trade, "tcm8_primary_hit", False))
    complete = str(row.get("state") or "") == ST_TRADE_COMPLETE or bool(exit_reason)
    state = str(row.get("state") or ST_WAITING_FOR_TREND)
    if in_trade:
        if runner or primary_hit:
            state = ST_RUNNER_ACTIVE if runner else ST_TARGET_REACHED
        else:
            state = ST_TRADE_ACTIVE
    reason = str(exit_reason or row.get("reason") or "")
    idx = pipeline_index(
        state=state,
        reason=reason,
        accept=bool(row.get("accept")),
        in_trade=in_trade,
        runner=runner,
        primary_hit=primary_hit,
        complete=complete,
    )
    trend = str(row.get("trend") or "")
    direction = str(row.get("direction") or "")
    if in_trade:
        direction = str(getattr(getattr(trade, "side", None), "value", "") or direction)
    target_note = ""
    if in_trade or complete:
        if runner_enabled or runner:
            target_note = "runner on  ->  RUNNER_ACTIVE (Recon trail, stop only tightens)"
        else:
            target_note = "runner off  ->  flatten 8TCM_KEY_LEVEL_TARGET"
    gates = {
        "room": reason not in (REJ_BARRIER, REJ_TARGET_R),
        "chase": reason != REJ_CHASE,
        "stop": reason != REJ_STOP,
        "arm": bool(armed) and reason != REJ_ARMED,
        "nt": bool(connected) and reason != REJ_BRIDGE,
        "flat": bool(flat),
    }
    return {
        "ts": time.time(),
        "enabled": bool(enabled),
        "state": state,
        "step": STEPS[idx],
        "step_index": idx,
        "steps": list(STEPS),
        "reason": reason,
        "accept": bool(row.get("accept")),
        "trend": trend,
        "sequence": str(row.get("sequence") or ""),
        "swings": str(row.get("swings") or ""),
        "source": str(row.get("trend_source") or row.get("source") or ""),
        "direction": direction,
        "price": round(float(price or row.get("close") or row.get("entry") or 0), 2),
        "ema8": round(float(row.get("ema8") or 0), 2),
        "atr": round(float(row.get("atr") or 0), 4),
        "distance_ema_atr": row.get("distance_ema_atr"),
        "tested": bool(row.get("tested")),
        "retracement": bool(row.get("retracement") or row.get("pullback")),
        "rejection": str(row.get("rejection_type") or ""),
        "close_side": str(row.get("close_side") or ""),
        "entry": float(row.get("entry") or (getattr(trade, "entry", 0) if trade else 0) or 0),
        "stop": float(row.get("stop") or (getattr(trade, "stop", 0) if trade else 0) or 0),
        "target": float(
            row.get("primary_target_price")
            or row.get("barrier_price")
            or (getattr(trade, "target", 0) if trade else 0)
            or 0
        ),
        "target_type": str(row.get("primary_target_type") or row.get("barrier_type") or ""),
        "target_r": row.get("target_r"),
        "in_trade": in_trade,
        "runner": runner,
        "runner_enabled": bool(runner_enabled),
        "primary_hit": primary_hit,
        "complete": complete,
        "target_note": target_note,
        "armed": bool(armed),
        "connected": bool(connected),
        "flat": bool(flat),
        "mode": str(mode or ""),
        "gates": gates,
        "htf_1h": str(row.get("htf_1h") or ""),
        "htf_4h": str(row.get("htf_4h") or ""),
    }


def publish_tcm8_status(board: dict[str, Any], *, force: bool = False) -> Path | None:
    """Write the board for the external CMD. Throttled unless force=True."""
    global _last_stamp, _last_write
    key = (
        f"{board.get('enabled')}|{board.get('state')}|{board.get('step_index')}|"
        f"{board.get('reason')}|{board.get('trend')}|{board.get('direction')}|"
        f"{board.get('in_trade')}|{board.get('runner')}|{board.get('primary_hit')}|"
        f"{board.get('price')}|{board.get('accept')}"
    )
    now = time.time()
    if not force and key == _last_stamp and (now - _last_write) < 0.25:
        return None
    _last_stamp = key
    _last_write = now
    path = tcm8_status_path()
    try:
        _atomic_write(path, json.dumps(board, default=str, indent=0))
    except OSError:
        return None
    return path


def publish_from_engine(engine: Any, *, extra: dict[str, Any] | None = None, force: bool = False) -> None:
    cfg = getattr(engine, "cfg", None)
    row = dict(getattr(engine, "_tcm8_last", None) or {})
    if extra:
        row.update(extra)
    snap = getattr(engine, "last_snap", None)
    price = float(getattr(snap, "price", 0) or 0) if snap is not None else 0.0
    risk = getattr(engine, "risk", None)
    open_side = getattr(risk, "open_side", None)
    from .types import Side

    flat = getattr(engine, "paper", None) is None and (
        open_side is None or open_side == Side.NONE
    )
    board = build_tcm8_board(
        enabled=tcm8_enabled(cfg),
        row=row,
        trade=getattr(engine, "paper", None),
        armed=bool(getattr(cfg, "MARK2_ENABLED", False)),
        connected=bool(getattr(risk, "connected", False)),
        flat=flat,
        runner_enabled=bool(getattr(cfg, "ENABLE_8TCM_RUNNER", False)),
        mode=str(getattr(cfg, "MODE", "") or ""),
        price=price,
        exit_reason=str((extra or {}).get("exit_reason") or ""),
    )
    attach_ledger(board, engine=engine, price=price)
    # Watcher reads the ledger file for the blotter. Never bake session rows
    # into the live status file — pytest used to poison the CMD that way.
    board.pop("session", None)
    board.pop("trades", None)
    publish_tcm8_status(board, force=force)


LEDGER_MAX = 24
_ET = None


def _et_zone():
    global _ET
    if _ET is None:
        from zoneinfo import ZoneInfo

        _ET = ZoneInfo("America/New_York")
    return _ET


def _today_et() -> str:
    from datetime import datetime

    return datetime.now(_et_zone()).date().isoformat()


def tcm8_ledger_path() -> Path:
    override = os.environ.get("MARK2_TCM8_LEDGER")
    if override:
        return Path(override)
    if _under_pytest():
        return _pytest_scratch_dir() / "tcm8_ledger_pytest.json"
    return tcm8_status_path().with_name("tcm8_ledger.json")


def _empty_ledger() -> dict[str, Any]:
    return {
        "date": _today_et(),
        "open": None,
        "trades": [],
        "session": {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "net": 0.0,
            "gross_win": 0.0,
            "gross_loss": 0.0,
            "pts": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "pf": 0.0,
        },
    }


def _session_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) < 0]
    net = sum(float(t.get("pnl") or 0) for t in trades)
    gw = sum(float(t.get("pnl") or 0) for t in wins)
    gl = abs(sum(float(t.get("pnl") or 0) for t in losses))
    pts = sum(float(t.get("pts") or 0) for t in trades)
    n = len(trades)
    wr = (100.0 * len(wins) / n) if n else 0.0
    avg_w = (gw / len(wins)) if wins else 0.0
    avg_l = (gl / len(losses)) if losses else 0.0
    pf = (gw / gl) if gl > 1e-9 else (99.99 if gw > 0 else 0.0)
    fees = sum(float(t.get("fees") or 0) for t in trades)
    pnls = [float(t.get("pnl") or 0) for t in trades]
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "net": round(net, 2),
        "gross_win": round(gw, 2),
        "gross_loss": round(gl, 2),
        "pts": round(pts, 2),
        "win_rate": round(wr, 1),
        "avg_win": round(avg_w, 2),
        "avg_loss": round(avg_l, 2),
        "pf": round(min(pf, 99.99), 2),
        "fees": round(fees, 2),
        "best": round(max(pnls), 2) if pnls else 0.0,
        "worst": round(min(pnls), 2) if pnls else 0.0,
    }


def read_tcm8_ledger() -> dict[str, Any]:
    path = tcm8_ledger_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return _empty_ledger()
    if not isinstance(raw, dict):
        return _empty_ledger()
    if str(raw.get("date") or "") != _today_et():
        return _empty_ledger()
    raw.setdefault("open", None)
    raw.setdefault("trades", [])
    raw["session"] = _session_from_trades(list(raw.get("trades") or []))
    return raw


def write_tcm8_ledger(data: dict[str, Any]) -> None:
    data = dict(data)
    data["date"] = str(data.get("date") or _today_et())
    data["session"] = _session_from_trades(list(data.get("trades") or []))
    try:
        _atomic_write(tcm8_ledger_path(), json.dumps(data, default=str, indent=2))
    except OSError:
        return


def ledger_record_open(row: dict[str, Any]) -> dict[str, Any]:
    data = read_tcm8_ledger()
    data["open"] = dict(row)
    write_tcm8_ledger(data)
    return data


def ledger_record_close(row: dict[str, Any]) -> dict[str, Any]:
    data = read_tcm8_ledger()
    data["open"] = None
    trades = list(data.get("trades") or [])
    trades.insert(0, dict(row))
    data["trades"] = trades[:LEDGER_MAX]
    write_tcm8_ledger(data)
    return data


def attach_ledger(board: dict[str, Any], *, engine: Any = None, price: float = 0.0) -> dict[str, Any]:
    data = read_tcm8_ledger()
    board["session"] = data.get("session") or {}
    board["trades"] = list(data.get("trades") or [])
    board["date"] = data.get("date") or _today_et()
    trade = getattr(engine, "paper", None) if engine is not None else None
    if trade is not None and bool(getattr(trade, "tcm8", False)):
        side = str(getattr(getattr(trade, "side", None), "value", "") or "")
        entry = float(getattr(trade, "entry", 0) or 0)
        qty = max(1, int(getattr(trade, "qty", 1) or 1))
        pv = 2.0
        cfg = getattr(engine, "cfg", None)
        if cfg is not None:
            pv = max(float(getattr(cfg, "POINT_VALUE", 2.0) or 2.0), 1e-9)
        now = float(price or 0)
        if side == "LONG":
            pts = now - entry
        elif side == "SHORT":
            pts = entry - now
        else:
            pts = 0.0
        board["open_trade"] = {
            "side": side,
            "qty": qty,
            "entry": entry,
            "stop": float(getattr(trade, "stop", 0) or 0),
            "hard": float(getattr(trade, "hard_stop", 0) or 0),
            "target": float(getattr(trade, "target", 0) or 0),
            "price": now,
            "pts": round(pts, 2),
            "usd": round(pts * pv * qty, 2),
            "mfe": round(float(getattr(trade, "mfe", 0) or 0), 2),
            "mae": round(float(getattr(trade, "mae", 0) or 0), 2),
            "runner": bool(getattr(trade, "tcm8_runner", False)),
            "primary": bool(getattr(trade, "tcm8_primary_hit", False)),
        }
    else:
        board["open_trade"] = None
    return board


def _usd(n: float) -> str:
    v = float(n or 0)
    sign = "+" if v >= 0 else "-"
    return f"{sign}${abs(v):,.2f}"


def _clock(ts: float) -> str:
    from datetime import datetime

    try:
        val = float(ts or 0)
        if val < 1_000_000_000:
            return "--:--"
        return datetime.fromtimestamp(val, _et_zone()).strftime("%H:%M")
    except (OSError, OverflowError, ValueError, TypeError):
        return "--:--"


def _why(raw: str) -> str:
    return str(raw or "—").replace("8TCM_", "").replace("REJECT_", "")[:18]


def format_tcm8_cmd_tables(board: dict[str, Any] | None) -> str:
    """Monospace session blotter + last-exit breakdown for the watcher CMD."""
    board = dict(board or {})
    sess = dict(board.get("session") or {})
    trades = list(board.get("trades") or [])
    lines = [
        "  ============================================================",
        f"  SESSION  {board.get('date') or _today_et()}",
        (
            f"  {int(sess.get('trades') or 0)} trades   "
            f"{int(sess.get('wins') or 0)}W / {int(sess.get('losses') or 0)}L   "
            f"wr {float(sess.get('win_rate') or 0):.0f}%   "
            f"NET {_usd(float(sess.get('net') or 0))}   "
            f"PF {float(sess.get('pf') or 0):.2f}"
        ),
        (
            f"  pts {float(sess.get('pts') or 0):+.2f}   "
            f"avg W {_usd(float(sess.get('avg_win') or 0))}   "
            f"avg L -${abs(float(sess.get('avg_loss') or 0)):,.2f}"
        ),
        (
            f"  fees -${abs(float(sess.get('fees') or 0)):,.2f}   "
            f"best {_usd(float(sess.get('best') or 0))}   "
            f"worst {_usd(float(sess.get('worst') or 0))}"
        ),
        "  ------------------------------------------------------------",
        "  #  CLOCK  SIDE QTY   ENTRY      EXIT       PTS      PNL        WHY",
    ]
    if not trades:
        lines.append("  —  no closed 8TCM trades yet today")
    for i, t in enumerate(trades[:12], start=1):
        n = len(trades) - i + 1
        lines.append(
            f"  {n:<2} {_clock(float(t.get('clock_ts') or t.get('ts') or 0)):<6} "
            f"{str(t.get('side') or '—')[:5]:<5} {int(t.get('qty') or 1):<3} "
            f"{float(t.get('entry') or 0):<10.2f} {float(t.get('exit') or 0):<10.2f} "
            f"{float(t.get('pts') or 0):>+7.2f} {_usd(float(t.get('pnl') or 0)):>10}  "
            f"{_why(str(t.get('reason') or ''))}"
        )
    last = trades[0] if trades else None
    if last:
        pv = float(last.get("point_value") or 2.0)
        qty = max(1, int(last.get("qty") or 1))
        mfe = float(last.get("mfe") or 0)
        peak_usd = mfe * pv * qty
        hold = float(last.get("hold_sec") or 0)
        if hold >= 60:
            hold_s = f"{int(hold // 60)}m {int(hold % 60)}s"
        else:
            hold_s = f"{hold:.0f}s"
        lines.extend(
            [
                "  ------------------------------------------------------------",
                "  LAST EXIT BREAKDOWN",
                f"  {last.get('side')} x{qty}   {_why(str(last.get('reason') or ''))}   {hold_s}",
                f"  entry  {float(last.get('entry') or 0):.2f}   exit  {float(last.get('exit') or 0):.2f}",
                f"  stop   {float(last.get('stop') or 0):.2f}   target {float(last.get('target') or 0):.2f}",
                f"  pts    {float(last.get('pts') or 0):+.2f}   R {float(last.get('r_mult') or 0):+.2f}",
                f"  PNL    {_usd(float(last.get('pnl') or 0))}   fees {_usd(float(last.get('fees') or 0))}",
                f"  MFE    {mfe:.2f} pts   peak {_usd(peak_usd)}",
                f"  MAE    {float(last.get('mae') or 0):.2f} pts",
                f"  giveback  peak {_usd(peak_usd)}  ->  closed {_usd(float(last.get('pnl') or 0))}",
            ]
        )
    open_t = board.get("open_trade")
    if open_t:
        lines.extend(
            [
                "  ------------------------------------------------------------",
                (
                    f"  OPEN  {open_t.get('side')} x{open_t.get('qty')}  @ {float(open_t.get('entry') or 0):.2f}"
                ),
                (
                    f"  now   {float(open_t.get('price') or 0):.2f}   "
                    f"open {float(open_t.get('pts') or 0):+.2f} pts   "
                    f"{_usd(float(open_t.get('usd') or 0))}"
                ),
                (
                    f"  stop  {float(open_t.get('stop') or 0):.2f}   "
                    f"hard {float(open_t.get('hard') or 0):.2f}   "
                    f"tgt {float(open_t.get('target') or 0):.2f}   "
                    f"MFE {float(open_t.get('mfe') or 0):.2f}"
                ),
                (
                    f"  trail {'ON' if open_t.get('runner') else 'OFF'}   "
                    f"green {'HIT' if open_t.get('primary') else 'ARMED'}"
                ),
            ]
        )
    lines.append("  ============================================================")
    return "\n".join(lines)
