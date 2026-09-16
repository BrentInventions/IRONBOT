"""Process-wide license state. Fail closed. Authorized machines do not phone home."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .machine import machine_id
from .notify import notify_unauthorized, reset_notify_for_tests
from .validator import LicenseResult, verify_file


_last: LicenseResult | None = None


def pytest_bypass() -> bool:
    if os.environ.get("RECON_LICENSE_BYPASS", "").strip() != "1":
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "pytest" in sys.modules


def offline_ok() -> bool:
    """Tiante / local pack: ARM without Brent's recon.license. Never set on Recon desktop."""
    flag = os.environ.get("MARK2_OFFLINE_OK", "").strip().lower()
    return flag in {"1", "true", "yes"}


def reset_for_tests() -> None:
    global _last
    _last = None
    reset_notify_for_tests()
    from .machine import reset_machine_cache
    from .register import reset_register_for_tests

    reset_machine_cache()
    reset_register_for_tests()


def adopt_result(result: LicenseResult) -> None:
    global _last
    _last = result


def evaluate(*, cfg: Any = None, notify: bool = True) -> LicenseResult:
    global _last
    if pytest_bypass():
        _last = LicenseResult(valid=True, license_id="TEST", reason="AUTHORIZED")
        return _last
    if offline_ok():
        _last = LicenseResult(valid=True, license_id="TIANTE-OFFLINE", reason="AUTHORIZED")
        return _last
    try:
        mid = machine_id()
        result = verify_file(current_machine=mid)
        from .customer import load_profile
        from .register import start_retry_loop, try_refresh_from_server, try_register_and_fetch

        profile = load_profile()
        if result.valid:
            refreshed = try_refresh_from_server(machine_hash=mid, profile=profile)
            if refreshed is not None:
                result = refreshed
            start_retry_loop(cfg=cfg)
        else:
            bound = try_register_and_fetch(machine_hash=mid, profile=profile)
            if bound is not None and bound.valid:
                result = bound
            else:
                start_retry_loop(cfg=cfg)
    except Exception:
        result = LicenseResult(valid=False, license_id=None, reason="LICENSE_INVALID")
        mid = ""
    _last = result
    if notify and not result.valid:
        notify_unauthorized(result, cfg=cfg, machine_hash=mid)
    return result


def is_authorized(*, cfg: Any = None) -> bool:
    if _last is None:
        evaluate(cfg=cfg, notify=True)
    return bool(_last and _last.valid)


def current() -> LicenseResult:
    if _last is None:
        return evaluate(notify=False)
    return _last


def _license_no_server() -> bool:
    try:
        from .customer import is_loopback_server_url, load_profile
        from .paths import frozen

        url = (load_profile().license_server_url or "").strip()
        if not url or (frozen() and is_loopback_server_url(url)):
            return True
    except Exception:
        pass
    try:
        from .register import pending_path

        path = pending_path()
        if not path.is_file():
            return False
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            return False
        return str(doc.get("status") or "").upper() == "UNREACHABLE"
    except Exception:
        return False


def license_hud(*, cfg: Any = None) -> dict[str, Any]:
    # Cached state only — never phone home or spawn WMI from the HUD tick.
    result = _last if _last is not None else LicenseResult(
        valid=False, license_id=None, reason="LICENSE_MISSING"
    )
    no_server = (not result.valid) and _license_no_server()
    if result.valid:
        status = result.hud_status()
        message = "LICENSE: AUTHORIZED"
    elif no_server:
        status = "NO SERVER"
        message = "LICENSE: NO SERVER"
    else:
        status = result.hud_status()
        message = "RECON LICENSE REQUIRED — TRADING DISABLED"
    return {
        "valid": bool(result.valid),
        "status": status,
        "licenseId": result.license_id or "",
        "message": message,
    }


def apply_to_engine(engine: Any) -> LicenseResult:
    result = evaluate(cfg=getattr(engine, "cfg", None), notify=True)
    try:
        engine.log.write(
            "LICENSE_AUTHORIZED" if result.valid else f"LICENSE_{result.reason}",
            license_id=result.license_id or "",
        )
    except Exception:
        pass
    if not result.valid:
        engine.cfg.MARK2_ENABLED = False
    return result
