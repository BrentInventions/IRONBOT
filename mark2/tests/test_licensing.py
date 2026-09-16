"""Machine-bound license: authorized trade path vs copy-to-other-PC."""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mark2.config import Mark2Config
from mark2.engine import Mark2Engine
from mark2.licensing.manager import evaluate, is_authorized, reset_for_tests
from mark2.licensing.notify import reset_notify_for_tests, server_url
from mark2.licensing.sign import build_license
from mark2.licensing.validator import verify_document, verify_file
from mark2.net import Mark2Net
from mark2.risk import RiskGate
from mark2.types import RejectReason


def _real_mode(monkeypatch) -> Ed25519PrivateKey:
    monkeypatch.delenv("RECON_LICENSE_BYPASS", raising=False)
    reset_for_tests()
    reset_notify_for_tests()
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv("RECON_PUBLIC_KEY_HEX", pub.hex())
    monkeypatch.setenv("RECON_MACHINE_ID", "alpha-box")
    return key


def _write_license(path: Path, key: Ed25519PrivateKey, _unused: str = "") -> None:
    from mark2.licensing.machine import machine_id as mid

    doc = build_license(
        machine_id=mid(),
        license_id="RECON-TEST-001",
        customer_id="TEST",
        private_key=key,
    )
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_a_valid_license_authorizes_arm(tmp_path: Path, monkeypatch) -> None:
    key = _real_mode(monkeypatch)
    lic = tmp_path / "recon.license"
    _write_license(lic, key, "alpha-box")
    monkeypatch.setenv("RECON_LICENSE_PATH", str(lic))
    reset_for_tests()
    result = evaluate(notify=False)
    assert result.valid is True
    assert result.reason == "AUTHORIZED"
    cfg = Mark2Config()
    cfg.MARK2_ENABLED = False
    eng = Mark2Engine(cfg, log_path=tmp_path / "d.jsonl", persist_path=tmp_path / "s.json")
    assert eng.set_enabled(True, persist=False) is True


def test_b_other_machine_mismatch(tmp_path: Path, monkeypatch) -> None:
    key = _real_mode(monkeypatch)
    lic = tmp_path / "recon.license"
    _write_license(lic, key, "alpha-box")
    monkeypatch.setenv("RECON_LICENSE_PATH", str(lic))
    monkeypatch.setenv("RECON_MACHINE_ID", "other-pc")
    reset_for_tests()
    result = evaluate(notify=False)
    assert result.valid is False
    assert result.reason == "MACHINE_MISMATCH"
    cfg = Mark2Config()
    eng = Mark2Engine(cfg, log_path=tmp_path / "d.jsonl", persist_path=tmp_path / "s.json")
    assert eng.set_enabled(True, persist=False) is False
    assert eng.cfg.MARK2_ENABLED is False


def test_c_tampered_machine_field(tmp_path: Path, monkeypatch) -> None:
    key = _real_mode(monkeypatch)
    lic = tmp_path / "recon.license"
    _write_license(lic, key, "alpha-box")
    doc = json.loads(lic.read_text(encoding="utf-8"))
    doc["license"]["machine_id"] = "0" * 64
    lic.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("RECON_LICENSE_PATH", str(lic))
    reset_for_tests()
    result = verify_file(lic)
    assert result.reason == "SIGNATURE_INVALID"
    assert result.valid is False


def test_d_fake_signature(tmp_path: Path, monkeypatch) -> None:
    key = _real_mode(monkeypatch)
    lic = tmp_path / "recon.license"
    _write_license(lic, key, "alpha-box")
    doc = json.loads(lic.read_text(encoding="utf-8"))
    doc["signature"] = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
    lic.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("RECON_LICENSE_PATH", str(lic))
    from mark2.licensing.machine import machine_id as mid

    result = verify_document(doc, current_machine=mid())
    assert result.valid is False
    assert result.reason == "SIGNATURE_INVALID"


def test_expired_license_fails_verify(tmp_path: Path, monkeypatch) -> None:
    key = _real_mode(monkeypatch)
    from mark2.licensing.machine import machine_id as mid

    doc = build_license(
        machine_id=mid(),
        license_id="RECON-TEST-001",
        customer_id="TEST",
        private_key=key,
        expires_at="2020-01-01T00:00:00Z",
    )
    lic = tmp_path / "recon.license"
    lic.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("RECON_LICENSE_PATH", str(lic))
    reset_for_tests()
    result = verify_file(lic, current_machine=mid())
    assert result.valid is False
    assert result.reason == "LICENSE_EXPIRED"
    result = evaluate(notify=False)
    assert result.valid is False
    assert result.reason == "LICENSE_EXPIRED"


def test_e_missing_license(tmp_path: Path, monkeypatch) -> None:
    _real_mode(monkeypatch)
    monkeypatch.setenv("RECON_LICENSE_PATH", str(tmp_path / "nope.license"))
    reset_for_tests()
    result = evaluate(notify=False)
    assert result.valid is False
    assert result.reason == "LICENSE_MISSING"


def test_f_corrupt_license(tmp_path: Path, monkeypatch) -> None:
    _real_mode(monkeypatch)
    lic = tmp_path / "recon.license"
    lic.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("RECON_LICENSE_PATH", str(lic))
    reset_for_tests()
    result = evaluate(notify=False)
    assert result.valid is False
    assert result.reason == "LICENSE_INVALID"


def test_g_authorized_does_not_need_server(tmp_path: Path, monkeypatch) -> None:
    key = _real_mode(monkeypatch)
    lic = tmp_path / "recon.license"
    _write_license(lic, key, "alpha-box")
    monkeypatch.setenv("RECON_LICENSE_PATH", str(lic))
    monkeypatch.delenv("LICENSE_SERVER_URL", raising=False)
    reset_for_tests()
    assert evaluate(notify=False).valid is True
    assert server_url() == ""
    cfg = Mark2Config()
    risk = RiskGate(cfg)
    ok, why = risk.allow_entry(ts=1.0, qty=1, stop_points=4.0)
    assert ok is True


def test_unauthorized_pings_owner_server(tmp_path: Path, monkeypatch) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import time

    hits: list[dict] = []

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            hits.append(json.loads(self.rfile.read(n)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        _real_mode(monkeypatch)
        monkeypatch.setenv("RECON_LICENSE_PATH", str(tmp_path / "missing.license"))
        monkeypatch.setenv("LICENSE_SERVER_URL", f"http://127.0.0.1:{httpd.server_address[1]}")
        reset_for_tests()
        evaluate(notify=True)
        for _ in range(40):
            if any(h.get("event") == "NEW_MACHINE" for h in hits):
                break
            time.sleep(0.05)
        alert = next(h for h in hits if h.get("event") == "NEW_MACHINE")
        assert alert["reason"] == "LICENSE_MISSING"
    finally:
        httpd.shutdown()


def test_live_send_blocked_without_license(tmp_path: Path, monkeypatch) -> None:
    _real_mode(monkeypatch)
    monkeypatch.setenv("RECON_LICENSE_PATH", str(tmp_path / "missing.license"))
    reset_for_tests()
    evaluate(notify=False)
    assert is_authorized() is False
    net = Mark2Net()
    net._sock = object()  # type: ignore[attr-defined]
    sent: list[dict] = []

    def _capture(msg: dict) -> None:
        sent.append(msg)

    net.send = _capture  # type: ignore[method-assign]
    net.send_order("BUY", quantity=1)
    net.send_stop(100.0)
    assert sent == []
    cfg = Mark2Config()
    risk = RiskGate(cfg)
    ok, why = risk.allow_manual_entry(ts=1.0, qty=1, stop_points=4.0)
    assert ok is False
    assert why == RejectReason.REJECT_LICENSE


def _start_owner_server(tmp_path: Path, monkeypatch):
    import sys
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import Request, urlopen

    from cryptography.hazmat.primitives import serialization

    home = tmp_path / "lic-home"
    home.mkdir()
    key = Ed25519PrivateKey.generate()
    (home / "ed25519.pem").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("RECON_LICENSING_HOME", str(home))
    monkeypatch.setenv("RECON_PUBLIC_KEY_HEX", key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex())
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import license_server.app as app

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path: str, payload: dict):
        req = Request(
            url + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())

    return httpd, url, post


def _write_customer(tmp_path: Path, url: str, customer_id: str = "WILLIE", auto_bind: bool = True) -> None:
    (tmp_path / "recon_customer.json").write_text(
        json.dumps(
            {
                "customer_id": customer_id,
                "license_id": f"RECON-{customer_id}-001",
                "auto_bind": auto_bind,
                "license_server_url": url,
            }
        ),
        encoding="utf-8",
    )


def test_willie_first_start_registers_not_authorized(tmp_path: Path, monkeypatch) -> None:
    from mark2.licensing.machine import machine_id as mid

    _real_mode(monkeypatch)
    httpd, url, post = _start_owner_server(tmp_path, monkeypatch)
    monkeypatch.setenv("RECON_APP_HOME", str(tmp_path))
    monkeypatch.setenv("RECON_LICENSE_PATH", str(tmp_path / "recon.license"))
    try:
        _write_customer(tmp_path, url, "WILLIE", auto_bind=True)
        reset_for_tests()
        result = evaluate(notify=False)
        assert result.valid is False
        assert result.reason == "LICENSE_MISSING"
        assert not (tmp_path / "recon.license").exists()

        approved = post("/api/approve", {"machine_id": mid()})
        assert approved["ok"] is True
        assert approved["document"]["license"]["machine_id"] == mid()

        reset_for_tests()
        result = evaluate(notify=False)
        assert result.valid is True
        assert result.license_id
        assert (tmp_path / "recon.license").is_file()
        assert verify_file(tmp_path / "recon.license", current_machine=mid()).valid
    finally:
        httpd.shutdown()


def test_other_customer_register_does_not_authorize(tmp_path: Path, monkeypatch) -> None:
    _real_mode(monkeypatch)
    monkeypatch.setenv("RECON_APP_HOME", str(tmp_path))
    monkeypatch.setenv("RECON_LICENSE_PATH", str(tmp_path / "missing.license"))
    _write_customer(tmp_path, "http://127.0.0.1:1", "CUSTOMER-002", auto_bind=True)
    reset_for_tests()
    result = evaluate(notify=False)
    assert result.valid is False
    assert result.reason == "LICENSE_MISSING"


def test_second_machine_stays_unauthorized_until_approved(tmp_path: Path, monkeypatch) -> None:
    from mark2.licensing.machine import machine_id as mid

    _real_mode(monkeypatch)
    httpd, url, post = _start_owner_server(tmp_path, monkeypatch)
    monkeypatch.setenv("RECON_APP_HOME", str(tmp_path))
    first_lic = tmp_path / "first.license"
    second_lic = tmp_path / "second.license"
    try:
        monkeypatch.setenv("RECON_MACHINE_ID", "alpha-box")
        monkeypatch.setenv("RECON_LICENSE_PATH", str(first_lic))
        _write_customer(tmp_path, url, "WILLIE")
        reset_for_tests()
        assert evaluate(notify=False).valid is False
        first = mid()
        post("/api/approve", {"machine_id": first})
        reset_for_tests()
        assert evaluate(notify=False).valid is True

        monkeypatch.setenv("RECON_MACHINE_ID", "bravo-box")
        monkeypatch.setenv("RECON_LICENSE_PATH", str(second_lic))
        reset_for_tests()
        result = evaluate(notify=False)
        assert result.valid is False
        assert result.reason == "LICENSE_MISSING"
        assert not second_lic.exists()
    finally:
        httpd.shutdown()


def test_expired_then_extend_evaluate_picks_up(tmp_path: Path, monkeypatch) -> None:
    from mark2.licensing.machine import machine_id as mid

    _real_mode(monkeypatch)
    httpd, url, post = _start_owner_server(tmp_path, monkeypatch)
    monkeypatch.setenv("RECON_APP_HOME", str(tmp_path))
    lic = tmp_path / "recon.license"
    monkeypatch.setenv("RECON_LICENSE_PATH", str(lic))
    try:
        _write_customer(tmp_path, url, "CUSTOMER-002")
        reset_for_tests()
        assert evaluate(notify=False).valid is False
        post("/api/approve", {"machine_id": mid(), "expires_at": "2020-01-01T00:00:00Z"})
        reset_for_tests()
        expired = evaluate(notify=False)
        assert expired.valid is False
        post("/api/extend", {"machine_id": mid(), "days": 30})
        reset_for_tests()
        result = evaluate(notify=False)
        assert result.valid is True
        assert verify_file(lic, current_machine=mid()).valid
    finally:
        httpd.shutdown()


def test_rejected_customer_evaluate_stays_unauthorized(tmp_path: Path, monkeypatch) -> None:
    from mark2.licensing.machine import machine_id as mid

    _real_mode(monkeypatch)
    httpd, url, post = _start_owner_server(tmp_path, monkeypatch)
    monkeypatch.setenv("RECON_APP_HOME", str(tmp_path))
    monkeypatch.setenv("RECON_LICENSE_PATH", str(tmp_path / "recon.license"))
    try:
        _write_customer(tmp_path, url, "CUSTOMER-002")
        reset_for_tests()
        assert evaluate(notify=False).valid is False
        post("/api/reject", {"machine_id": mid()})
        reset_for_tests()
        result = evaluate(notify=False)
        assert result.valid is False
        assert not (tmp_path / "recon.license").exists()
    finally:
        httpd.shutdown()

