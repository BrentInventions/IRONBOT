"""JSONL logger must not crash the net thread on Windows/OneDrive."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark2.logger import AnalyticsLogger
from mark2.net import Mark2Net


def test_write_appends_json_line(tmp_path):
    path = tmp_path / "d.jsonl"
    log = AnalyticsLogger(path)
    log.write("MARK2_CONNECTION", connected=True)
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["event"] == "MARK2_CONNECTION"
    assert row["connected"] is True


def test_onedrive_log_path_moves_to_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    cloud = (
        tmp_path
        / "OneDrive"
        / "Desktop"
        / "Recon-Sniper"
        / "mark2"
        / "logs"
        / "mark2_decisions.jsonl"
    )
    log = AnalyticsLogger(cloud)
    assert log.path == tmp_path / "local" / "ReconSniper" / "logs" / "mark2_decisions.jsonl"
    log.write("MARK2_CONNECTION", connected=False)
    row = json.loads(log.path.read_text(encoding="utf-8").strip())
    assert row["event"] == "MARK2_CONNECTION"
    assert row["connected"] is False


def test_write_swallows_errno_22(tmp_path, monkeypatch):
    log = AnalyticsLogger(tmp_path / "d.jsonl")

    def boom(*_args, **_kwargs):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(Path, "open", boom)
    log.write("MARK2_CONNECTION", connected=True)


def test_connection_callback_oserror_is_isolated():
    hits: list[bool] = []

    def bad(ok: bool) -> None:
        hits.append(ok)
        raise OSError(22, "Invalid argument")

    net = Mark2Net(on_connection=bad)
    net._notify_connection(True)
    net._notify_connection(False)
    assert hits == [True, False]
