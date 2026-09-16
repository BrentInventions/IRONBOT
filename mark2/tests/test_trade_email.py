"""Dedicated trade-alert mailbox. Does not send during pytest unless a path is given."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.trade_email import TradeMailer, load_email_settings, send_test


def test_disabled_file_is_not_ready(tmp_path: Path) -> None:
    path = tmp_path / "mail.json"
    path.write_text(json.dumps({"enabled": False, "username": "a@b.c", "password": "x"}), encoding="utf-8")
    assert load_email_settings(path).ready() is False


def test_ready_when_gmail_fields_filled(tmp_path: Path) -> None:
    path = tmp_path / "mail.json"
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "username": "bot.alerts@gmail.com",
                "password": "abcd efgh ijkl mnop",
                "to_addr": "bot.alerts@gmail.com",
            }
        ),
        encoding="utf-8",
    )
    s = load_email_settings(path)
    assert s.ready() is True
    assert s.to_addr == "bot.alerts@gmail.com"


def test_notify_entry_sends_subject(tmp_path: Path) -> None:
    path = tmp_path / "mail.json"
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "username": "bot.alerts@gmail.com",
                "password": "secret",
                "to_addr": "bot.alerts@gmail.com",
            }
        ),
        encoding="utf-8",
    )
    mailer = TradeMailer.load(path)
    captured: dict[str, str] = {}

    def _fake(settings, subject, body):
        captured["subject"] = subject
        captured["body"] = body

    with patch("mark2.trade_email.threading.Thread") as th:
        th.side_effect = lambda target=None, name=None, daemon=None: MagicMock(
            start=lambda: target()
        )
        with patch("mark2.trade_email._deliver", side_effect=_fake):
            mailer.notify_entry(
                side="LONG",
                price=20150.25,
                stop=20135.0,
                qty=1,
                tag="EMA_INTERSECTION_LONG",
                mode="LIVE",
                symbol="MNQ",
                ts=1.0,
            )
    assert "LONG ENTRY" in captured["subject"]
    assert "20150.25" in captured["body"]
    assert "EMA_INTERSECTION_LONG" in captured["body"]


def test_notify_exit_includes_pnl(tmp_path: Path) -> None:
    path = tmp_path / "mail.json"
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "username": "bot.alerts@gmail.com",
                "password": "secret",
                "to_addr": "bot.alerts@gmail.com",
            }
        ),
        encoding="utf-8",
    )
    mailer = TradeMailer.load(path)
    captured: dict[str, str] = {}

    def _fake(settings, subject, body):
        captured["subject"] = subject
        captured["body"] = body

    with patch("mark2.trade_email.threading.Thread") as th:
        th.side_effect = lambda target=None, name=None, daemon=None: MagicMock(
            start=lambda: target()
        )
        with patch("mark2.trade_email._deliver", side_effect=_fake):
            mailer.notify_exit(
                side="LONG",
                entry=20150.0,
                exit_px=20170.0,
                qty=1,
                pts=20.0,
                pnl=40.0,
                reason="MFE_GIVEBACK",
                mfe=28.0,
                mae=4.0,
                hold_sec=95.0,
                tag="EMA_INTERSECTION_LONG",
                mode="LIVE",
                symbol="MNQ",
                ts=100.0,
            )
    assert "EXIT" in captured["subject"]
    assert "+$40.00" in captured["subject"]
    assert "MFE_GIVEBACK" in captured["body"]
    assert "1m 35s" in captured["body"]


def test_send_test_not_configured(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    assert send_test(path) == "NOT_CONFIGURED"
