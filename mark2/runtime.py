"""Standalone Recon Sniper host. Connects to ReconSniperBridge on its own port."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Mark2Config, load_config, SETTINGS_PATH
from .engine import Mark2Engine
from .net import Mark2Net
from .types import Tick


_WALLET_KEYS = (
    "cash_value",
    "cash",
    "net_liquidation",
    "equity",
    "sod_cash",
    "buying_power",
)


def _has_wallet_fields(msg: dict) -> bool:
    return any(k in msg for k in _WALLET_KEYS)


def _ts(msg: dict) -> float:
    raw = msg.get("time") or msg.get("timestamp")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time()


class Mark2Runtime:
    def __init__(
        self,
        cfg: Mark2Config | None = None,
        *,
        persist_path: Path | None = None,
    ) -> None:
        self.cfg = cfg or load_config(persist_path or SETTINGS_PATH)
        logs = Path(__file__).resolve().parent / "logs"
        self.engine = Mark2Engine(
            self.cfg,
            log_path=logs / "mark2_decisions.jsonl",
            persist_path=persist_path or SETTINGS_PATH,
        )
        self.net = Mark2Net(
            host="127.0.0.1",
            port=int(self.cfg.BRIDGE_PORT),
            on_message=self._on_message,
            on_connection=self._on_conn,
        )
        self.engine.execution.sink = self.net
        self._running = False
        self._seed_done = False
        self._nt_cash_logged = False
        self._nt_cash_zero_logged = False

    def start(self) -> None:
        self._running = True
        self.net.start()

    def stop(self) -> None:
        self._running = False
        self.net.stop()

    def _on_conn(self, ok: bool) -> None:
        self.engine.risk.connected = bool(ok)
        try:
            self.engine.log.write("MARK2_CONNECTION", connected=ok)
        except OSError:
            pass
        if ok:
            self._seed_done = False
            if self.engine.paper is None:
                self.engine.completed_bars.clear()
                self.engine._tcm8_bars_1m.clear()
            self.net.send(
                {
                    "type": "config",
                    "execution_mode": "tick",
                    "seed_bars": 400,
                    "tick_throttle_ms": 50,
                }
            )
            self.net.send({"type": "request_seed", "seed_bars": 400})
            self.net.send(
                {
                    "type": "config",
                    "execution_mode": "tick",
                    "seed_bars": 400,
                    "tick_throttle_ms": 50,
                }
            )
            self.net.send({"type": "request_seed", "seed_bars": 400})

    def _on_message(self, msg: dict) -> None:
        t = str(msg.get("type") or "")
        if t == "tick":
            self.engine.risk.connected = True
            px = float(msg.get("last") or msg.get("price") or 0)
            if px <= 0:
                return
            tick = Tick(
                ts=_ts(msg),
                price=px,
                volume=float(msg.get("volume") or 0),
                bar_time=str(msg.get("bar_time") or ""),
                forming_open=float(msg.get("open") or px),
                forming_high=float(msg.get("high") or px),
                forming_low=float(msg.get("low") or px),
                forming_volume=float(msg.get("volume") or 0),
                bid=float(msg.get("bid") or 0),
                ask=float(msg.get("ask") or 0),
            )
            self.engine.on_tick(tick)
            return
        if t in ("bar", "seed_bar"):
            self.engine.risk.connected = True
            bar = {
                "time": str(msg.get("time") or ""),
                "open": float(msg.get("open") or 0),
                "high": float(msg.get("high") or 0),
                "low": float(msg.get("low") or 0),
                "close": float(msg.get("close") or 0),
                "volume": float(msg.get("volume") or 0),
            }
            explicit_seed = t == "seed_bar" or bool(msg.get("seed"))
            catchup = msg.get("realtime") is False and not self._seed_done
            seed = explicit_seed or catchup
            self.engine.on_bar_close(bar, seed=seed)
            if not seed and bar["close"] > 0:
                self.engine.on_tick(
                    Tick(
                        ts=_ts(msg),
                        price=float(bar["close"]),
                        volume=float(bar["volume"]),
                        bar_time=str(bar["time"]),
                        forming_open=float(bar["open"]),
                        forming_high=float(bar["high"]),
                        forming_low=float(bar["low"]),
                        forming_volume=float(bar["volume"]),
                    )
                )
            return
        if t in ("bar_htf", "seed_bar_htf"):
            self.engine.risk.connected = True
            minutes = int(msg.get("timeframe") or msg.get("minutes") or 0)
            if minutes <= 0:
                return
            bar = {
                "time": str(msg.get("time") or ""),
                "open": float(msg.get("open") or 0),
                "high": float(msg.get("high") or 0),
                "low": float(msg.get("low") or 0),
                "close": float(msg.get("close") or 0),
                "volume": float(msg.get("volume") or 0),
            }
            seed = t == "seed_bar_htf" or bool(msg.get("seed"))
            self.engine.on_htf_bar(bar, minutes=minutes, seed=seed)
            return
        if t == "seed_done":
            self._seed_done = True
            self.engine.clear_ema_pending()
            print("EMA SEED DONE — next intersection is live", flush=True)
            return
        if t in ("heartbeat", "account", "pong") or _has_wallet_fields(msg):
            self.engine.risk.connected = True
            self.engine.apply_account(msg)
            self._log_first_cash(msg)
            # Wallet / connection only. Never synthesize a tape print from
            # heartbeat last — Market Replay pause still fires the 1s timer,
            # and Close[0] can be a different print than the last tick (or
            # keep moving). That made open PnL tick while paused and could
            # paint a winner red, or even stop the paper trade out.
            return
        if t == "fill":
            if "realized_pnl" in msg or "unrealized_pnl" in msg:
                self.engine.apply_account(msg)
            try:
                self.engine.log.write("MARK2_FILL", **{k: msg.get(k) for k in msg})
            except OSError:
                pass

    def _log_first_cash(self, msg: dict) -> None:
        acct = self.engine.account or {}
        eq = float(acct.get("equity") or 0)
        cash = float(acct.get("cash") or 0)
        shown = eq if eq > 0 else cash
        if shown > 0:
            if self._nt_cash_logged:
                return
            self._nt_cash_logged = True
            print(
                f"[M2] NT cash sync ${shown:,.2f}  "
                f"cash_value={msg.get('cash_value')} net_liquidation={msg.get('net_liquidation')} "
                f"sod_cash={msg.get('sod_cash')} buying_power={msg.get('buying_power')}",
                flush=True,
            )
            return
        if self._nt_cash_zero_logged or not _has_wallet_fields(msg):
            return
        self._nt_cash_zero_logged = True
        print(
            f"[M2] NT heartbeat wallet keys present but all ~0  "
            f"cash_value={msg.get('cash_value')} net_liquidation={msg.get('net_liquidation')} "
            f"sod_cash={msg.get('sod_cash')} buying_power={msg.get('buying_power')}",
            flush=True,
        )


def main() -> None:
    cfg = load_config()
    rt = Mark2Runtime(cfg)
    print("Recon Sniper")
    print(f"  mode = {cfg.mode().value}")
    print(f"  port = {cfg.BRIDGE_PORT}")
    print("  LIVE — ARM sends NT orders; DISARM pauses new entries")
    rt.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        rt.stop()


if __name__ == "__main__":
    main()
