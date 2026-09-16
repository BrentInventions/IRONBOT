"""Entry/exit emails to a dedicated mailbox. Credentials stay in mark2_email.json."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import threading
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import _writable_dir

EMAIL_PATH = _writable_dir() / "mark2_email.json"
ET = ZoneInfo("America/New_York")


@dataclass
class EmailSettings:
    enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to_addr: str = ""

    def ready(self) -> bool:
        return bool(
            self.enabled
            and self.smtp_host
            and self.smtp_port
            and self.username
            and self.password
            and (self.to_addr or self.username)
        )


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def load_email_settings(path: Path | None = None) -> EmailSettings:
    if path is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return EmailSettings()
    p = path or EMAIL_PATH
    data: dict[str, Any] = {}
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError):
            data = {}
    user = str(data.get("username") or _env("IMPULSE_TRADE_EMAIL_USER")).strip()
    password = str(data.get("password") or _env("IMPULSE_TRADE_EMAIL_PASSWORD")).strip()
    to_addr = str(data.get("to_addr") or data.get("to") or user).strip()
    from_addr = str(data.get("from_addr") or data.get("from") or user).strip()
    host = str(data.get("smtp_host") or _env("IMPULSE_TRADE_EMAIL_HOST") or "smtp.gmail.com").strip()
    try:
        port = int(data.get("smtp_port") or _env("IMPULSE_TRADE_EMAIL_PORT") or 587)
    except (TypeError, ValueError):
        port = 587
    enabled = bool(data.get("enabled", False))
    return EmailSettings(
        enabled=enabled,
        smtp_host=host,
        smtp_port=port,
        username=user,
        password=password,
        from_addr=from_addr,
        to_addr=to_addr,
    )


def _stamp(ts: float | None = None) -> str:
    if ts and ts > 0:
        dt = datetime.fromtimestamp(ts, tz=ET)
    else:
        dt = datetime.now(tz=ET)
    return dt.strftime("%Y-%m-%d %I:%M:%S %p ET")


def _hold(sec: float) -> str:
    s = max(0, int(sec))
    m, r = divmod(s, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h {m}m {r}s"
    if m:
        return f"{m}m {r}s"
    return f"{r}s"


def _deliver(settings: EmailSettings, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.from_addr or settings.username
    msg["To"] = settings.to_addr or settings.username
    msg.set_content(body)
    ctx = ssl.create_default_context()
    if int(settings.smtp_port) == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=ctx) as smtp:
            smtp.login(settings.username, settings.password)
            smtp.send_message(msg)
        return
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ctx)
        smtp.login(settings.username, settings.password)
        smtp.send_message(msg)


class TradeMailer:
    def __init__(self, settings: EmailSettings | None = None) -> None:
        self.settings = settings or load_email_settings()
        self._lock = threading.Lock()
        self._warned = False
        if self.settings.ready():
            print(
                f"TRADE EMAIL ON  to={self.settings.to_addr or self.settings.username}",
                flush=True,
            )
        elif self.settings.enabled and not self._warned:
            self._warned = True
            print("TRADE EMAIL OFF  fill mark2_email.json (see mark2_email.example.json)", flush=True)

    @classmethod
    def load(cls, path: Path | None = None) -> TradeMailer:
        return cls(load_email_settings(path))

    def send_async(self, subject: str, body: str) -> None:
        if not self.settings.ready():
            return
        settings = self.settings

        def _run() -> None:
            try:
                _deliver(settings, subject, body)
            except Exception as exc:
                print(f"TRADE EMAIL FAIL  {type(exc).__name__}: {exc}", flush=True)

        threading.Thread(target=_run, name="trade-email", daemon=True).start()

    def notify_entry(
        self,
        *,
        side: str,
        price: float,
        stop: float,
        qty: int,
        tag: str = "",
        mode: str = "",
        symbol: str = "",
        ts: float = 0.0,
    ) -> None:
        sym = symbol or "MNQ"
        subj = f"Recon Sniper · {side} ENTRY · {sym}"
        body = "\n".join(
            [
                f"ENTERED {side}",
                f"Symbol: {sym}",
                f"Qty: {qty}",
                f"Entry: {price:.2f}",
                f"Stop: {stop:.2f}",
                f"Tag: {tag or '—'}",
                f"Mode: {mode or '—'}",
                f"Time: {_stamp(ts)}",
            ]
        )
        self.send_async(subj, body)

    def notify_exit(
        self,
        *,
        side: str,
        entry: float,
        exit_px: float,
        qty: int,
        pts: float,
        pnl: float,
        reason: str = "",
        mfe: float = 0.0,
        mae: float = 0.0,
        hold_sec: float = 0.0,
        tag: str = "",
        mode: str = "",
        symbol: str = "",
        ts: float = 0.0,
    ) -> None:
        sym = symbol or "MNQ"
        sign = "+" if pnl >= 0 else ""
        subj = f"Recon Sniper · {side} EXIT · {reason or 'FLAT'} · {sign}${pnl:.2f}"
        body = "\n".join(
            [
                f"EXIT {side}",
                f"Reason: {reason or '—'}",
                f"Symbol: {sym}",
                f"Qty: {qty}",
                f"P&L: {sign}${pnl:.2f}",
                f"Points: {pts:+.2f}",
                f"Entry: {entry:.2f}",
                f"Exit: {exit_px:.2f}",
                f"Hold: {_hold(hold_sec)}",
                f"MFE: {mfe:.2f}   MAE: {mae:.2f}",
                f"Tag: {tag or '—'}",
                f"Mode: {mode or '—'}",
                f"Time: {_stamp(ts)}",
            ]
        )
        self.send_async(subj, body)


def send_test(path: Path | None = None) -> str:
    mailer = TradeMailer.load(path)
    if not mailer.settings.ready():
        return "NOT_CONFIGURED"
    try:
        _deliver(
            mailer.settings,
            "Recon Sniper · TEST EMAIL",
            "If you got this, trade entry/exit emails are working.\nKeep this mailbox off your main inbox.",
        )
    except Exception as exc:
        return f"FAIL {type(exc).__name__}: {exc}"
    return "SENT"


if __name__ == "__main__":
    print(send_test())
