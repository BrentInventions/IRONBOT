from __future__ import annotations

from mark2.config import Mark2Config
from mark2.impulse_lead import leader_enabled, maybe_publish, publish_now
from mark2.net import Mark2Net


def test_leader_hook_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("IMPULSE_PRO_LEADER", raising=False)
    monkeypatch.setattr("mark2.impulse_lead._cfg", lambda: Mark2Config())
    cfg = Mark2Config()
    assert cfg.IMPULSE_PRO_LEADER is False
    assert leader_enabled(cfg) is False
    assert publish_now({"action": "BUY", "quantity": 1}, cfg) is False


def test_url_env_does_not_enable_leader(monkeypatch) -> None:
    monkeypatch.delenv("IMPULSE_PRO_LEADER", raising=False)
    monkeypatch.setenv("IMPULSE_PRO_URL", "http://127.0.0.1:8790")
    monkeypatch.setattr("mark2.impulse_lead._cfg", lambda: Mark2Config())
    assert leader_enabled() is False


def test_publish_in_process_no_cloud(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IMPULSE_PRO_LEADER", "1")
    monkeypatch.setenv("IMPULSE_PRO_PORT", "0")
    monkeypatch.setenv("IMPULSE_PRO_DATA", str(tmp_path))
    monkeypatch.setattr("mark2.impulse_lead._cfg", lambda: Mark2Config())
    assert publish_now({"action": "BUY", "quantity": 2, "stop_loss": 1.0}) is True
    maybe_publish({"action": "SELL", "quantity": 1})


def test_send_order_still_fires_if_dongle_host_down(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IMPULSE_PRO_LEADER", "1")
    monkeypatch.setenv("IMPULSE_PRO_PORT", "0")
    monkeypatch.setenv("IMPULSE_PRO_DATA", str(tmp_path))
    monkeypatch.setattr("mark2.licensing.manager.is_authorized", lambda: True)
    sent: list[dict] = []
    net = Mark2Net()
    net.send = lambda msg: sent.append(msg) or True  # type: ignore[method-assign]
    net.send_order("BUY", quantity=2, stop_loss=21000.0)
    assert sent and sent[0]["action"] == "BUY"
    assert sent[0]["quantity"] == 2
