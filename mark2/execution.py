"""Mode-aware execution: OBSERVE_ONLY, PAPER_TRADE, LIVE.

LIVE talks to the configured local bridge (ReconSniperBridge 5564 or TradeChampionBridge 5560).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from .config import Mark2Config
from .risk import RiskGate
from .types import RunMode, Side


class OrderSink(Protocol):
    def send_order(
        self,
        action: str,
        *,
        quantity: int = 1,
        stop_loss: float | None = None,
        reason: str = "",
        take_profit: float | None = None,
    ) -> None: ...

    def send_flat(self, reason: str = "") -> None: ...


@dataclass
class Intent:
    side: Side
    price: float
    stop: float
    quantity: int
    reason: str
    ts: float
    # HUD manual entries skip the NT stop on submit; Python owns the stop.
    attach_stop: bool = True
    take_profit: float | None = None


class ExecutionEngine:
    def __init__(
        self,
        cfg: Mark2Config,
        risk: RiskGate,
        sink: Optional[OrderSink] = None,
    ) -> None:
        self.cfg = cfg
        self.risk = risk
        self.sink = sink
        self.orders_submitted = 0
        self.last_action = ""

    @property
    def mode(self) -> RunMode:
        try:
            return RunMode(str(self.cfg.MODE))
        except ValueError:
            return RunMode.LIVE

    def enter(self, intent: Intent) -> str:
        stop_pts = abs(intent.price - intent.stop)
        ok, why = self.risk.allow_entry(
            ts=intent.ts, qty=intent.quantity, stop_points=stop_pts
        )
        if not ok:
            return why.value or "REJECT_RISK"
        return self._submit(intent)

    def manual_enter(self, intent: Intent) -> str:
        stop_pts = abs(intent.price - intent.stop)
        ok, why = self.risk.allow_manual_entry(
            ts=intent.ts, qty=intent.quantity, stop_points=stop_pts
        )
        if not ok:
            return why.value or "REJECT_RISK"
        return self._submit(intent)

    def _submit(self, intent: Intent) -> str:
        mode = self.mode
        if mode == RunMode.OBSERVE_ONLY:
            self.risk.note_order(intent.ts)
            self.risk.note_open(intent.side)
            self.last_action = "OBSERVE_EXECUTE"
            return "OBSERVE_EXECUTE"
        if mode == RunMode.PAPER_TRADE:
            self.risk.note_order(intent.ts)
            self.risk.note_open(intent.side)
            self.last_action = "PAPER_EXECUTE"
            return "PAPER_EXECUTE"
        if mode == RunMode.LIVE:
            if self.sink is None or not self.risk.connected:
                return "REJECT_RISK"
            action = "BUY" if intent.side == Side.LONG else "SELL"
            self.risk.note_order(intent.ts)
            tick = 0.25
            try:
                tick = max(float(getattr(self.cfg, "TICK_SIZE", 0.25) or 0.25), 0.25)
            except Exception:
                tick = 0.25
            stop_loss = None
            if bool(getattr(intent, "attach_stop", True)):
                stop_loss = round(round(float(intent.stop) / tick) * tick, 2)
            take_profit = None
            raw_tp = getattr(intent, "take_profit", None)
            if raw_tp is not None:
                try:
                    tp = float(raw_tp)
                except (TypeError, ValueError):
                    tp = 0.0
                if tp > 0:
                    take_profit = round(round(tp / tick) * tick, 2)
            kwargs = {
                "quantity": intent.quantity,
                "stop_loss": stop_loss,
                "reason": intent.reason,
            }
            if take_profit is not None:
                kwargs["take_profit"] = take_profit
            self.sink.send_order(action, **kwargs)
            self.orders_submitted += 1
            self.last_action = "LIVE_EXECUTE"
            return "LIVE_EXECUTE"
        return "REJECT_MODE"

    def flatten(self, reason: str, *, ts: float) -> None:
        if self.mode == RunMode.LIVE and self.sink is not None:
            self.sink.send_flat(reason)
        self.risk.open_side = Side.NONE
        self.risk.pending = False
