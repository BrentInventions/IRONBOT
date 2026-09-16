"""Account-level risk. Independent of Recon entry/hold logic.

Strategy decides whether a setup is valid. This module decides whether
*this account* is allowed to take or keep that risk. Strategy cannot
override a lockout, equity kill, or daily loss halt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Mark2Config


STATE_OFF = "OFF"
STATE_ARMED = "ARMED"
STATE_TRADE_BLOCKED = "TRADE_BLOCKED"
STATE_DAILY_LOCKOUT = "DAILY_LOCKOUT"
STATE_EQUITY_KILL = "EQUITY_KILL"
STATE_CONNECTION_FAILSAFE = "CONNECTION_FAILSAFE"

LOCK_STATES = {
    STATE_DAILY_LOCKOUT,
    STATE_EQUITY_KILL,
}

PROFILES: dict[str, dict[str, Any]] = {
    "SMALL_250": {
        "max_contracts": 1,
        "allow_scale_in": False,
        "max_risk_per_trade_usd": 50.0,
        "max_daily_loss_usd": 75.0,
        "max_consecutive_losses": 3,
        "equity_floor_usd": 100.0,
        "stale_sec": 8.0,
        "kill_switch": True,
        "daily_lockout": True,
    },
    "STANDARD": {
        "max_contracts": 4,
        "allow_scale_in": False,
        "max_risk_per_trade_usd": 400.0,
        "max_daily_loss_usd": 800.0,
        "max_consecutive_losses": 8,
        "equity_floor_usd": 0.0,
        "stale_sec": 12.0,
        "kill_switch": True,
        "daily_lockout": True,
    },
}


def planned_risk_usd(
    entry: float,
    stop: float,
    qty: int,
    point_value: float,
) -> float:
    pts = abs(float(entry) - float(stop))
    return pts * float(point_value) * max(1, int(qty))


def _et_day(ts: float) -> str:
    try:
        dt = datetime.fromtimestamp(float(ts), ZoneInfo("America/New_York"))
    except Exception:
        dt = datetime.fromtimestamp(float(ts or 0), timezone.utc)
    return dt.strftime("%Y-%m-%d")


@dataclass
class RiskDecision:
    ok: bool
    state: str
    reason: str
    qty: int
    risk_usd: float
    allowed_usd: float
    message: str
    flatten: bool = False


class AccountRiskManager:
    def __init__(
        self,
        cfg: Mark2Config | None = None,
        *,
        writer: Callable[..., None] | None = None,
    ) -> None:
        self.cfg = cfg
        self._write = writer
        self.state = STATE_ARMED
        self.lock_reason = ""
        self.consecutive_losses = 0
        self.session_day = ""
        self.last_message = ""
        self.last_risk_usd = 0.0
        self.last_allowed_usd = 0.0
        self._last_logged_state = ""
        self._ctx: dict[str, Any] = {}

    def profile_name(self) -> str:
        raw = str(getattr(self.cfg, "ACCOUNT_RISK_PROFILE", "OFF") or "OFF").upper()
        if raw in ("OFF", "NONE", "DISABLE", "DISABLED"):
            return "OFF"
        if raw in PROFILES:
            return raw
        return "OFF"

    def enabled(self) -> bool:
        return self.profile_name() != "OFF"

    def _prof(self) -> dict[str, Any]:
        return dict(PROFILES.get(self.profile_name(), PROFILES["SMALL_250"]))

    def _cfg_float(self, name: str, fallback: float) -> float:
        if self.cfg is None:
            return float(fallback)
        raw = getattr(self.cfg, name, None)
        if raw is None:
            return float(fallback)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return float(fallback)
        if val <= 0:
            return float(fallback)
        return val

    def _cfg_int(self, name: str, fallback: int) -> int:
        if self.cfg is None:
            return int(fallback)
        raw = getattr(self.cfg, name, None)
        if raw is None:
            return int(fallback)
        try:
            val = int(raw)
        except (TypeError, ValueError):
            return int(fallback)
        if val <= 0:
            return int(fallback)
        return val

    def max_contracts(self) -> int:
        p = self._prof()
        return self._cfg_int("ACCOUNT_MAX_CONTRACTS", int(p["max_contracts"]))

    def max_risk_usd(self) -> float:
        p = self._prof()
        return self._cfg_float("ACCOUNT_MAX_RISK_PER_TRADE_USD", float(p["max_risk_per_trade_usd"]))

    def max_daily_loss_usd(self) -> float:
        p = self._prof()
        return self._cfg_float("ACCOUNT_MAX_DAILY_LOSS_USD", float(p["max_daily_loss_usd"]))

    def equity_floor_usd(self) -> float:
        p = self._prof()
        if self.cfg is not None:
            raw = getattr(self.cfg, "ACCOUNT_EQUITY_FLOOR_USD", None)
            if raw is not None:
                try:
                    return max(0.0, float(raw))
                except (TypeError, ValueError):
                    pass
        return float(p["equity_floor_usd"])

    def max_consecutive_losses(self) -> int:
        p = self._prof()
        return self._cfg_int("ACCOUNT_MAX_CONSECUTIVE_LOSSES", int(p["max_consecutive_losses"]))

    def stale_sec(self) -> float:
        p = self._prof()
        return self._cfg_float("ACCOUNT_STALE_DATA_SEC", float(p["stale_sec"]))

    def daily_lockout_on(self) -> bool:
        if not self.enabled():
            return False
        if self.cfg is None:
            return bool(self._prof()["daily_lockout"])
        return bool(getattr(self.cfg, "ACCOUNT_DAILY_LOCKOUT", self._prof()["daily_lockout"]))

    def kill_switch_on(self) -> bool:
        if not self.enabled():
            return False
        if self.cfg is None:
            return bool(self._prof()["kill_switch"])
        return bool(getattr(self.cfg, "ACCOUNT_KILL_SWITCH", self._prof()["kill_switch"]))

    def log(self, message: str, **extra: Any) -> None:
        line = f"[RISK] {message}"
        self.last_message = line
        print(line, flush=True)
        if self._write is not None:
            try:
                self._write(message, **extra)
            except Exception:
                pass

    def maybe_roll_session(self, ts: float) -> None:
        day = _et_day(ts)
        if not self.session_day:
            self.session_day = day
            return
        if day != self.session_day:
            self.session_day = day
            self.reset_session(why="NEW_SESSION")

    def reset_session(self, why: str = "SESSION_RESET") -> None:
        prev = self.state
        self.consecutive_losses = 0
        if self.state in LOCK_STATES or self.state == STATE_TRADE_BLOCKED:
            self.state = STATE_ARMED
            self.lock_reason = ""
            self.log(f"Session unlocked ({why})", reason=why, prior=prev)

    def clamp_qty(self, qty: int) -> int:
        if not self.enabled():
            return max(1, int(qty or 1))
        return max(1, min(int(qty or 1), self.max_contracts()))

    def sync(self, **kwargs: Any) -> None:
        self._ctx.update(kwargs)

    def _lock(self, state: str, why: str) -> None:
        if self.state == state and self.lock_reason == why:
            return
        self.state = state
        self.lock_reason = why
        self.log(why, state=state)

    def approve_entry(
        self,
        *,
        entry: float,
        stop: float,
        qty: int,
        connected: bool | None = None,
        in_trade: bool | None = None,
        daily_pnl: float | None = None,
        equity: float | None = None,
        equity_synced: bool | None = None,
        last_tick_age_sec: float | None = None,
        ts: float = 0.0,
    ) -> RiskDecision:
        ctx = self._ctx
        if connected is None:
            connected = bool(ctx.get("connected", True))
        if in_trade is None:
            in_trade = bool(ctx.get("in_trade", False))
        if daily_pnl is None:
            daily_pnl = float(ctx.get("daily_pnl") or 0)
        if equity is None:
            equity = float(ctx.get("equity") or 0)
        if equity_synced is None:
            equity_synced = bool(ctx.get("equity_synced", False))
        if last_tick_age_sec is None:
            last_tick_age_sec = float(ctx.get("last_tick_age_sec") or 0)
        if ts:
            self.maybe_roll_session(ts)
        allowed = self.max_risk_usd()
        req_qty = max(1, int(qty or 1))
        qty = self.clamp_qty(req_qty)
        risk = planned_risk_usd(entry, stop, qty, float(getattr(self.cfg, "POINT_VALUE", 2.0) or 2.0) if self.cfg else 2.0)
        self.last_risk_usd = risk
        self.last_allowed_usd = allowed

        if not self.enabled():
            self.state = STATE_OFF
            return RiskDecision(True, STATE_OFF, "", req_qty, risk, allowed, "[RISK] Profile OFF")

        if self.state in LOCK_STATES:
            msg = f"Entry rejected — trading locked ({self.state})"
            self.log(msg, reason=self.lock_reason)
            return RiskDecision(False, self.state, self.lock_reason or self.state, qty, risk, allowed, msg)

        if in_trade:
            msg = "Entry rejected — already in a trade (duplicate blocked)"
            self.log(msg, reason="DUPLICATE")
            self.state = STATE_TRADE_BLOCKED
            return RiskDecision(False, STATE_TRADE_BLOCKED, "DUPLICATE", qty, risk, allowed, msg)

        if not connected:
            msg = "Entry rejected — connection failsafe (no new orders while NT is down)"
            self.log(msg, reason="CONNECTION_FAILSAFE")
            self.state = STATE_CONNECTION_FAILSAFE
            return RiskDecision(False, STATE_CONNECTION_FAILSAFE, "CONNECTION_FAILSAFE", qty, risk, allowed, msg)

        if last_tick_age_sec > self.stale_sec():
            msg = f"Entry rejected — stale market data ({last_tick_age_sec:.1f}s)"
            self.log(msg, reason="STALE_DATA")
            self.state = STATE_TRADE_BLOCKED
            return RiskDecision(False, STATE_TRADE_BLOCKED, "STALE_DATA", qty, risk, allowed, msg)

        if req_qty > self.max_contracts():
            self.log(
                f"Quantity rejected — {self.profile_name()} maximum = {self.max_contracts()} (requested {req_qty}); using {qty}",
                reason="QTY_CAP",
                requested=req_qty,
                used=qty,
            )
            risk = planned_risk_usd(
                entry,
                stop,
                qty,
                float(getattr(self.cfg, "POINT_VALUE", 2.0) or 2.0) if self.cfg else 2.0,
            )
            self.last_risk_usd = risk

        if self.daily_lockout_on() and daily_pnl <= -abs(self.max_daily_loss_usd()):
            self._lock(STATE_DAILY_LOCKOUT, "Daily loss threshold reached")
            msg = "Entry rejected — daily lockout"
            return RiskDecision(False, STATE_DAILY_LOCKOUT, "DAILY_LOCKOUT", qty, risk, allowed, msg, flatten=True)

        if (
            self.kill_switch_on()
            and equity_synced
            and self.equity_floor_usd() > 0
            and 0 < equity <= self.equity_floor_usd()
        ):
            self._lock(STATE_EQUITY_KILL, "Account equity kill switch activated")
            msg = f"Entry rejected — equity ${equity:.2f} <= floor ${self.equity_floor_usd():.2f}"
            return RiskDecision(False, STATE_EQUITY_KILL, "EQUITY_KILL", qty, risk, allowed, msg, flatten=True)

        if self.consecutive_losses >= self.max_consecutive_losses():
            self._lock(STATE_DAILY_LOCKOUT, "Trading locked — consecutive losses")
            msg = f"Entry rejected — {self.consecutive_losses} consecutive losses"
            return RiskDecision(False, STATE_DAILY_LOCKOUT, "CONSECUTIVE_LOSSES", qty, risk, allowed, msg)

        if risk > allowed + 1e-9:
            msg = (
                f"Entry rejected — required risk ${risk:.2f} > allowed ${allowed:.2f}"
            )
            self.log(
                msg + "  Reason: ACCOUNT_TOO_SMALL_FOR_SETUP",
                reason="ACCOUNT_TOO_SMALL_FOR_SETUP",
                required=round(risk, 2),
                allowed=round(allowed, 2),
            )
            print(
                f"TRADE REJECTED:\nRequired Risk: ${risk:.2f}\nAllowed Risk: ${allowed:.2f}\n"
                "Reason: ACCOUNT_TOO_SMALL_FOR_SETUP",
                flush=True,
            )
            self.state = STATE_ARMED
            return RiskDecision(
                False,
                STATE_TRADE_BLOCKED,
                "ACCOUNT_TOO_SMALL_FOR_SETUP",
                qty,
                risk,
                allowed,
                msg,
            )

        self.state = STATE_ARMED
        self.log(
            f"Entry approved  risk ${risk:.2f} / allowed ${allowed:.2f}  qty {qty}",
            required=round(risk, 2),
            allowed=round(allowed, 2),
            qty=qty,
        )
        return RiskDecision(True, STATE_ARMED, "", qty, risk, allowed, "[RISK] Entry approved")

    def note_exit(self, pnl: float) -> None:
        if pnl < -1e-9:
            self.consecutive_losses += 1
            self.log(
                f"Loss booked ${pnl:.2f}  consecutive={self.consecutive_losses}",
                pnl=round(pnl, 2),
                consecutive=self.consecutive_losses,
            )
            if self.consecutive_losses >= self.max_consecutive_losses():
                self._lock(STATE_DAILY_LOCKOUT, "Trading locked — consecutive losses")
        else:
            if self.consecutive_losses:
                self.log("Win booked — consecutive loss streak cleared")
            self.consecutive_losses = 0

    def evaluate_open(
        self,
        *,
        daily_pnl: float,
        equity: float = 0.0,
        equity_synced: bool = False,
        in_trade: bool = False,
        connected: bool = True,
        ts: float = 0.0,
    ) -> RiskDecision:
        """In-trade / idle watchdog. May flatten. Never loosens strategy stops."""
        if ts:
            self.maybe_roll_session(ts)
        qty = 1
        allowed = self.max_risk_usd()
        if not self.enabled():
            self.state = STATE_OFF
            return RiskDecision(True, STATE_OFF, "", qty, 0.0, allowed, "")

        if not connected:
            if self.state not in LOCK_STATES:
                if self.state != STATE_CONNECTION_FAILSAFE:
                    self.log("Connection failsafe — no new entries; last NT stop remains if attached")
                self.state = STATE_CONNECTION_FAILSAFE
            return RiskDecision(True, STATE_CONNECTION_FAILSAFE, "CONNECTION_FAILSAFE", qty, 0.0, allowed, "")

        if self.daily_lockout_on() and daily_pnl <= -abs(self.max_daily_loss_usd()):
            self._lock(STATE_DAILY_LOCKOUT, "Daily loss threshold reached")
            return RiskDecision(
                False,
                STATE_DAILY_LOCKOUT,
                "DAILY_LOCKOUT",
                qty,
                0.0,
                allowed,
                "[RISK] Daily loss threshold reached",
                flatten=bool(in_trade),
            )

        if (
            self.kill_switch_on()
            and equity_synced
            and self.equity_floor_usd() > 0
            and 0 < equity <= self.equity_floor_usd()
        ):
            self._lock(STATE_EQUITY_KILL, "Account equity kill switch activated")
            return RiskDecision(
                False,
                STATE_EQUITY_KILL,
                "EQUITY_KILL",
                qty,
                0.0,
                allowed,
                "[RISK] Account equity kill switch activated",
                flatten=bool(in_trade),
            )

        if self.state == STATE_CONNECTION_FAILSAFE:
            self.state = STATE_ARMED if self.state not in LOCK_STATES else self.state
        if self.state not in LOCK_STATES:
            self.state = STATE_ARMED
        return RiskDecision(True, self.state, self.lock_reason, qty, self.last_risk_usd, allowed, "")

    def hud(self, *, equity: float = 0.0, daily_pnl: float = 0.0, contracts: int = 1) -> dict[str, Any]:
        name = self.profile_name()
        return {
            "profile": name,
            "enabled": name != "OFF",
            "state": self.state if name != "OFF" else STATE_OFF,
            "equity": round(float(equity or 0), 2),
            "dailyPnl": round(float(daily_pnl or 0), 2),
            "dailyLossLimit": round(self.max_daily_loss_usd(), 2) if name != "OFF" else 0.0,
            "tradeRisk": round(float(self.last_risk_usd or 0), 2),
            "allowedRisk": round(self.max_risk_usd(), 2) if name != "OFF" else 0.0,
            "contracts": int(contracts),
            "maxContracts": self.max_contracts() if name != "OFF" else int(contracts),
            "consecutiveLosses": int(self.consecutive_losses),
            "lockReason": self.lock_reason,
            "message": self.last_message,
            "emergency": self.state in LOCK_STATES or self.state == STATE_CONNECTION_FAILSAFE,
        }
