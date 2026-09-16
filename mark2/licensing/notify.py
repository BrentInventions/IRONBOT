"""Unauthorized machines ping the owner's license server. Never grants ARM."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any

from .validator import LicenseResult

_sent = False
_lock = threading.Lock()


def reset_notify_for_tests() -> None:
    global _sent
    _sent = False


def server_url(cfg: Any = None) -> str:
    env = os.environ.get("LICENSE_SERVER_URL", "").strip()
    if env:
        return env.rstrip("/")
    try:
        from .customer import load_profile

        prof = load_profile()
        if prof.license_server_url:
            return prof.license_server_url
    except Exception:
        pass
    if cfg is not None:
        return str(getattr(cfg, "LICENSE_SERVER_URL", "") or "").strip().rstrip("/")
    return ""


def notify_unauthorized(result: LicenseResult, *, cfg: Any = None, machine_hash: str = "") -> None:
    """Best-effort one-shot alert. Failure never affects trading."""
    global _sent
    if result.valid:
        return
    url = server_url(cfg)
    if not url:
        return
    with _lock:
        if _sent:
            return
        _sent = True
    payload = {
        "event": "NEW_MACHINE",
        "reason": result.reason,
        "license_id": result.license_id,
        "machine_id": machine_hash,
        "product": "RECON",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url + "/v1/alert",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _post() -> None:
        try:
            urllib.request.urlopen(req, timeout=4)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass

    threading.Thread(target=_post, name="recon-license-alert", daemon=True).start()
