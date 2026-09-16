"""Recon Sniper safety gates. Independent of TradeChampion _submit()."""

from __future__ import annotations

from .config import Mark2Config
from .licensing.manager import is_authorized
from .types import RejectReason, Side


class RiskGate:
    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg
        self.daily_pnl = 0.0
        self.open_side = Side.NONE
        self.pending = False
        self.connected = True
        self.enabled = True
        self.kill = False
        self.goal_met = False
        self._order_times: list[float] = []

    def note_fill_pnl(self, pnl: float) -> None:
        self.daily_pnl += float(pnl)
        self.open_side = Side.NONE
        self.pending = False

    def note_open(self, side: Side) -> None:
        self.open_side = side
        self.pending = False

    def _entry_common(
        self, *, ts: float, qty: int, stop_points: float
    ) -> tuple[bool, RejectReason]:
        if self.goal_met:
            return False, RejectReason.REJECT_RISK
        if self.kill:
            return False, RejectReason.REJECT_RISK
        if not self.connected:
            return False, RejectReason.REJECT_RISK
        if self.pending or self.open_side != Side.NONE:
            return False, RejectReason.REJECT_DUPLICATE_EVENT
        qty = max(1, int(qty))
        if qty > int(self.cfg.MAX_CONTRACTS):
            return False, RejectReason.REJECT_RISK
        risk_usd = abs(stop_points) * float(self.cfg.POINT_VALUE) * qty
        if risk_usd > float(self.cfg.MAX_LOSS_DOLLARS):
            return False, RejectReason.REJECT_RISK
        if self.daily_pnl <= -abs(float(self.cfg.MAX_LOSS_DOLLARS)):
            return False, RejectReason.REJECT_RISK
        self._order_times = [t for t in self._order_times if ts - t <= 20.0]
        if len(self._order_times) >= 4:
            self.kill = True
            return False, RejectReason.REJECT_RISK
        return True, RejectReason.NONE

    def allow_entry(self, *, ts: float, qty: int, stop_points: float) -> tuple[bool, RejectReason]:
        if not is_authorized(cfg=self.cfg):
            return False, RejectReason.REJECT_LICENSE
        if not self.enabled or not self.cfg.MARK2_ENABLED:
            return False, RejectReason.REJECT_MODE
        return self._entry_common(ts=ts, qty=qty, stop_points=stop_points)

    def allow_manual_entry(
        self, *, ts: float, qty: int, stop_points: float
    ) -> tuple[bool, RejectReason]:
        """HUD operator orders — allowed even when auto-arm is off."""
        if not is_authorized(cfg=self.cfg):
            return False, RejectReason.REJECT_LICENSE
        return self._entry_common(ts=ts, qty=qty, stop_points=stop_points)

    def note_order(self, ts: float) -> None:
        self._order_times.append(ts)
        self.pending = True
