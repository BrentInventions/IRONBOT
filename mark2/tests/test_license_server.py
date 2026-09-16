"""Owner server: register stays pending until approve; poll delivers the license."""

from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mark2.licensing.validator import verify_document


def _machine(n: int) -> str:
    return f"{n:064x}"


def _start_server(tmp_path: Path, monkeypatch):
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
    monkeypatch.setenv(
        "RECON_PUBLIC_KEY_HEX",
        key.public_key()
        .public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        .hex(),
    )
    import license_server.app as app

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _post(url: str, payload: dict, path: str):
    req = Request(
        url + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode())


def _get(url: str, path: str):
    with urlopen(url + path, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode())


def test_register_does_not_return_document(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        first = _machine(1)
        status, body = _post(
            url,
            {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": first},
            "/v1/register",
        )
        assert status == 200
        assert body["ok"] is True
        assert body["status"] == "PENDING"
        assert body.get("document") is None

        status, poll = _get(url, f"/v1/license?machine_id={first}")
        assert status == 200
        assert poll["ok"] is False
        assert poll["status"] == "PENDING"
        assert poll.get("document") is None
    finally:
        httpd.shutdown()


def test_autobind_is_register_alias_no_document(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        first = _machine(1)
        status, body = _post(
            url,
            {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": first},
            "/v1/autobind",
        )
        assert status == 200
        assert body["ok"] is True
        assert body["status"] == "PENDING"
        assert body.get("document") is None
    finally:
        httpd.shutdown()


def test_approve_then_poll_returns_signed_license(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        first = _machine(1)
        _post(
            url,
            {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": first},
            "/v1/register",
        )
        status, approved = _post(url, {"machine_id": first}, "/api/approve")
        assert status == 200
        assert approved["ok"] is True
        assert approved["document"]["license"]["machine_id"] == first

        status, poll = _get(url, f"/v1/license?machine_id={first}")
        assert status == 200
        assert poll["ok"] is True
        assert poll["document"]["license"]["machine_id"] == first
        assert poll["document"]["license"]["customer_id"] == "WILLIE"
    finally:
        httpd.shutdown()


def test_second_machine_stays_pending_until_approved(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        first, second = _machine(1), _machine(2)
        _post(url, {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": first}, "/v1/register")
        _post(url, {"machine_id": first}, "/api/approve")
        status, body = _post(
            url,
            {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": second},
            "/v1/register",
        )
        assert status == 200
        assert body["status"] == "PENDING"
        assert body.get("document") is None
        status, poll = _get(url, f"/v1/license?machine_id={second}")
        assert poll["ok"] is False
        assert poll["status"] == "PENDING"
        assert poll.get("document") is None
    finally:
        httpd.shutdown()


def test_rejected_machine_gets_no_document(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        mid = _machine(9)
        _post(url, {"customer_id": "CUSTOMER-002", "license_id": "RECON-C2", "machine_id": mid}, "/v1/register")
        status, body = _post(url, {"machine_id": mid}, "/api/reject")
        assert status == 200
        assert body["status"] == "REJECTED"
        status, poll = _get(url, f"/v1/license?machine_id={mid}")
        assert poll["ok"] is False
        assert poll["status"] == "REJECTED"
        assert poll.get("document") is None
    finally:
        httpd.shutdown()


def test_reset_clears_rejected_so_register_is_pending(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        mid = _machine(21)
        _post(url, {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": mid}, "/v1/register")
        _post(url, {"machine_id": mid}, "/api/reject")
        status, body = _post(url, {"machine_id": mid}, "/v1/register")
        assert body["status"] == "REJECTED"

        status, reset = _post(url, {"machine_id": mid}, "/api/reset")
        assert status == 200
        assert reset["ok"] is True
        assert reset["status"] == "CLEARED"
        assert reset["deleted"] == 1

        status, poll = _get(url, f"/v1/license?machine_id={mid}")
        assert poll["ok"] is False
        assert poll["status"] == "MISSING"

        status, body = _post(
            url,
            {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": mid},
            "/v1/register",
        )
        assert status == 200
        assert body["status"] == "PENDING"
        status, poll = _get(url, f"/v1/license?machine_id={mid}")
        assert poll["status"] == "PENDING"
        assert poll.get("document") is None

        status, licenses = _get(url, "/api/licenses")
        assert licenses == []
    finally:
        httpd.shutdown()


def test_register_does_not_reset_approved_or_rejected(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        mid = _machine(3)
        _post(url, {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": mid}, "/v1/register")
        _post(url, {"machine_id": mid}, "/api/approve")
        status, body = _post(
            url,
            {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": mid},
            "/v1/register",
        )
        assert body["ok"] is True
        assert body["status"] == "APPROVED"
        assert body.get("document") is None

        other = _machine(4)
        _post(url, {"customer_id": "CUSTOMER-002", "machine_id": other}, "/v1/register")
        _post(url, {"machine_id": other}, "/api/reject")
        status, body = _post(url, {"customer_id": "CUSTOMER-002", "machine_id": other}, "/v1/register")
        assert body["status"] == "REJECTED"
    finally:
        httpd.shutdown()


def test_formal_issue_signs_any_customer_including_willie(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        willie = _machine(3)
        status, body = _post(
            url,
            {"customer_id": "WILLIE", "license_id": "RECON-WILLIE-001", "machine_id": willie},
            "/api/issue",
        )
        assert status == 200
        assert body["ok"] is True
        assert body["document"]["license"]["customer_id"] == "WILLIE"
        assert body["document"]["license"]["machine_id"] == willie

        status, body = _post(
            url,
            {
                "customer_id": "CUSTOMER-002",
                "license_id": "RECON-CUSTOMER-002",
                "machine_id": _machine(4),
            },
            "/api/issue",
        )
        assert status == 200
        assert body["ok"] is True
        assert body["document"]["license"]["customer_id"] == "CUSTOMER-002"
        status, poll = _get(url, f"/v1/license?machine_id={_machine(4)}")
        assert poll["ok"] is True
        assert poll["document"]["license"]["customer_id"] == "CUSTOMER-002"
    finally:
        httpd.shutdown()


def test_alert_records_new_machine(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        mid = _machine(77)
        status, body = _post(
            url,
            {"event": "NEW_MACHINE", "reason": "LICENSE_MISSING", "machine_id": mid, "license_id": ""},
            "/v1/alert",
        )
        assert status == 200
        assert body["ok"] is True
        status, alerts = _get(url, "/api/alerts")
        assert status == 200
        assert any(a["machine_id"] == mid and a["reason"] == "LICENSE_MISSING" for a in alerts)
    finally:
        httpd.shutdown()


def test_extend_reissue_poll_later_expiry(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        mid = _machine(11)
        _post(url, {"customer_id": "CUSTOMER-002", "license_id": "RECON-C2", "machine_id": mid}, "/v1/register")
        status, approved = _post(url, {"machine_id": mid, "days": 1}, "/api/approve")
        assert status == 200
        first_exp = approved["document"]["license"]["expires_at"]
        assert first_exp
        assert verify_document(approved["document"], current_machine=mid).valid is True

        status, extended = _post(url, {"machine_id": mid, "days": 30}, "/api/extend")
        assert status == 200
        later = extended["document"]["license"]["expires_at"]
        assert later > first_exp
        assert verify_document(extended["document"], current_machine=mid).valid is True

        status, poll = _get(url, f"/v1/license?machine_id={mid}")
        assert poll["ok"] is True
        assert poll["document"]["license"]["expires_at"] == later
        assert verify_document(poll["document"], current_machine=mid).valid is True

        status, listing = _get(url, "/api/licenses")
        assert listing[0]["expires_at"]
        assert listing[0]["days_left"] is not None
        assert listing[0]["status"] == "ACTIVE"
    finally:
        httpd.shutdown()


def test_revoke_poll_does_not_authorize(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        mid = _machine(12)
        _post(url, {"customer_id": "CUSTOMER-002", "machine_id": mid}, "/v1/register")
        _post(url, {"machine_id": mid, "days": 30}, "/api/approve")
        status, poll = _get(url, f"/v1/license?machine_id={mid}")
        assert poll["ok"] is True

        status, body = _post(url, {"machine_id": mid}, "/api/revoke")
        assert status == 200
        assert body["status"] == "REVOKED"
        status, poll = _get(url, f"/v1/license?machine_id={mid}")
        assert poll["ok"] is False
        assert poll["status"] == "REVOKED"
        assert poll.get("document") is None
    finally:
        httpd.shutdown()


def test_expired_then_extend_authorizes_again(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        mid = _machine(13)
        _post(url, {"customer_id": "CUSTOMER-002", "machine_id": mid}, "/v1/register")
        _post(url, {"machine_id": mid, "expires_at": "2020-01-01T00:00:00Z"}, "/api/approve")
        status, poll = _get(url, f"/v1/license?machine_id={mid}")
        assert poll["ok"] is False
        assert poll["status"] == "EXPIRED"
        assert poll.get("document") is None

        status, listing = _get(url, "/api/licenses")
        assert listing[0]["status"] == "EXPIRED"
        assert listing[0]["days_left"] == 0

        _post(url, {"machine_id": mid, "days": 14}, "/api/extend")
        status, poll = _get(url, f"/v1/license?machine_id={mid}")
        assert poll["ok"] is True
        assert poll["document"]["license"]["expires_at"] > "2020-01-01T00:00:00Z"
        assert verify_document(poll["document"], current_machine=mid).valid is True
    finally:
        httpd.shutdown()


def test_dashboard_html_generic_titles(tmp_path: Path, monkeypatch) -> None:
    httpd, url = _start_server(tmp_path, monkeypatch)
    try:
        with urlopen(url + "/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
        assert "PENDING REQUESTS" in html
        assert "ISSUED LICENSES" in html
        assert "NEW MACHINE ALERTS" in html
        assert "WILLIE AUTO-BIND" not in html
        assert "Willie auto-bind" not in html
        assert "Willie auto-binds" not in html
        assert "flash-blue" in html
    finally:
        httpd.shutdown()
