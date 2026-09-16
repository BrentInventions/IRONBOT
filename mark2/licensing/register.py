"""Customer registration. Never issues a license — owner must approve."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .customer import CustomerProfile, is_loopback_server_url, load_profile
from .machine import machine_id
from .paths import app_home, frozen
from .validator import LicenseResult, license_path, verify_file

DEFAULT_SERVER = "http://127.0.0.1:8787"
RETRY_SEC = 30.0

_retry_lock = threading.Lock()
_retry_thread: threading.Thread | None = None
_retry_stop = threading.Event()
_retry_cfg: Any = None


def reset_register_for_tests() -> None:
    global _retry_thread, _retry_cfg
    _retry_stop.set()
    _retry_thread = None
    _retry_cfg = None
    _retry_stop.clear()


def _server(profile: CustomerProfile) -> str:
    url = (profile.license_server_url or "").strip().rstrip("/")
    if frozen():
        if not url or is_loopback_server_url(url):
            return ""
        return url
    return url or DEFAULT_SERVER.rstrip("/")


def pending_path() -> Path:
    return app_home() / "recon_license_pending.json"


def _write_pending(payload: dict[str, Any]) -> None:
    path = pending_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _clear_pending() -> None:
    try:
        pending_path().unlink(missing_ok=True)
    except OSError:
        pass


def request_register(
    *,
    machine_hash: str,
    profile: CustomerProfile,
    timeout: float = 8.0,
    hostname: str | None = None,
) -> dict[str, Any] | None:
    if not machine_hash or not profile.customer_id:
        return None
    url = _server(profile)
    if not url:
        return None
    host = hostname if hostname is not None else socket.gethostname()
    body = json.dumps(
        {
            "customer_id": profile.customer_id,
            "license_id": profile.license_id,
            "machine_id": machine_hash,
            "hostname": host,
            "reason": "REGISTER",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url + "/v1/register",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        _write_pending(
            {
                "pending": True,
                "customer_id": profile.customer_id,
                "machine_id": machine_hash,
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": "UNREACHABLE",
            }
        )
        return None
    if not isinstance(doc, dict):
        return None
    _write_pending(
        {
            "pending": True,
            "customer_id": profile.customer_id,
            "machine_id": machine_hash,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": str(doc.get("status") or "PENDING"),
        }
    )
    return doc


def poll_license(
    *,
    machine_hash: str,
    profile: CustomerProfile,
    timeout: float = 8.0,
) -> dict[str, Any] | None:
    if not machine_hash:
        return None
    url = _server(profile)
    if not url:
        return None
    qs = urllib.parse.urlencode({"machine_id": machine_hash})
    req = urllib.request.Request(url + "/v1/license?" + qs, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def try_register_and_fetch(
    *,
    machine_hash: str,
    profile: CustomerProfile,
    dest: Path | None = None,
) -> LicenseResult | None:
    """Register (best-effort), then poll. Writes recon.license only after owner approve."""
    request_register(machine_hash=machine_hash, profile=profile)
    return _apply_poll(machine_hash=machine_hash, profile=profile, dest=dest, allow_disarm=False)


def try_refresh_from_server(
    *,
    machine_hash: str,
    profile: CustomerProfile,
    dest: Path | None = None,
) -> LicenseResult | None:
    """Poll for an extension or revoke. None = unreachable / no change."""
    return _apply_poll(machine_hash=machine_hash, profile=profile, dest=dest, allow_disarm=True)


def _remove_license_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_license_document(path: Path, document: dict[str, Any]) -> bool:
    text = json.dumps(document, indent=2)
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def _apply_poll(
    *,
    machine_hash: str,
    profile: CustomerProfile,
    dest: Path | None,
    allow_disarm: bool,
) -> LicenseResult | None:
    reply = poll_license(machine_hash=machine_hash, profile=profile)
    if reply is None:
        return None
    path = dest or license_path()
    if reply.get("ok") and isinstance(reply.get("document"), dict):
        if not _write_license_document(path, reply["document"]):
            return None
        result = verify_file(path, current_machine=machine_hash)
        if result.valid:
            _clear_pending()
        elif allow_disarm:
            _remove_license_file(path)
        return result
    status = str(reply.get("status") or "").upper()
    if allow_disarm and status in ("REVOKED", "EXPIRED"):
        _remove_license_file(path)
        _write_pending(
            {
                "pending": True,
                "customer_id": profile.customer_id,
                "machine_id": machine_hash,
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": status,
            }
        )
        return LicenseResult(valid=False, license_id=None, reason=f"LICENSE_{status}")
    return None


def start_retry_loop(*, cfg: Any = None) -> None:
    """One daemon thread: poll every ~30s for approve, extend, or revoke."""
    global _retry_thread, _retry_cfg
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _retry_lock:
        _retry_cfg = cfg
        if _retry_thread is not None and _retry_thread.is_alive():
            return
        _retry_stop.clear()
        _retry_thread = threading.Thread(
            target=_retry_loop,
            name="recon-license-register",
            daemon=True,
        )
        _retry_thread.start()


def _disarm_cfg() -> None:
    cfg = _retry_cfg
    if cfg is None:
        return
    try:
        cfg.MARK2_ENABLED = False
    except Exception:
        pass


def _retry_loop() -> None:
    from .manager import adopt_result, current

    while not _retry_stop.wait(RETRY_SEC):
        try:
            mid = machine_id()
            profile = load_profile()
            if current().valid:
                refreshed = try_refresh_from_server(machine_hash=mid, profile=profile)
                if refreshed is not None:
                    prev = current()
                    if (
                        refreshed.valid == prev.valid
                        and refreshed.license_id == prev.license_id
                        and refreshed.reason == prev.reason
                    ):
                        continue
                    adopt_result(refreshed)
                    if not refreshed.valid:
                        _disarm_cfg()
                continue
            bound = try_register_and_fetch(machine_hash=mid, profile=profile)
            if bound is not None and bound.valid:
                adopt_result(bound)
        except Exception:
            continue
