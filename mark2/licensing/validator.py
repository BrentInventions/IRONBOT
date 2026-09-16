"""Load and verify recon.license. Fail closed. No raw hardware in results."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .canon import canonical_bytes
from .keys import public_key_bytes
from .machine import machine_id


PRODUCT = "RECON"

_last_doc: dict[str, Any] | None = None


def last_document() -> dict[str, Any] | None:
    return _last_doc


@dataclass(frozen=True)
class LicenseResult:
    valid: bool
    license_id: str | None
    reason: str

    def hud_status(self) -> str:
        return "AUTHORIZED" if self.valid else "REQUIRED"


def license_path() -> Path:
    env = os.environ.get("RECON_LICENSE_PATH", "").strip()
    if env:
        return Path(env)
    from .paths import app_home, bundle_root

    candidates = [
        app_home() / "recon.license",
        Path.cwd() / "recon.license",
        bundle_root() / "recon.license",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return app_home() / "recon.license"


def _invalid(reason: str, license_id: str | None = None) -> LicenseResult:
    return LicenseResult(valid=False, license_id=license_id, reason=reason)


def parse_expires_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def verify_document(
    doc: dict[str, Any],
    *,
    current_machine: str,
    public_key: bytes | None = None,
) -> LicenseResult:
    lic = doc.get("license")
    sig_b64 = doc.get("signature")
    if not isinstance(lic, dict) or not isinstance(sig_b64, str) or not sig_b64.strip():
        return _invalid("LICENSE_INVALID")
    license_id = str(lic.get("license_id") or "") or None
    required = ("product", "license_id", "customer_id", "machine_id", "status", "issued_at", "license_version")
    if any(k not in lic for k in required):
        return _invalid("LICENSE_INVALID", license_id)
    if str(lic.get("product") or "") != PRODUCT:
        return _invalid("LICENSE_INVALID", license_id)
    if str(lic.get("status") or "").upper() != "ACTIVE":
        return _invalid("LICENSE_INACTIVE", license_id)
    try:
        sig = base64.b64decode(sig_b64, validate=True)
        key = Ed25519PublicKey.from_public_bytes(public_key or public_key_bytes())
        key.verify(sig, canonical_bytes(lic))
    except (InvalidSignature, ValueError, TypeError):
        return _invalid("SIGNATURE_INVALID", license_id)
    except Exception:
        return _invalid("LICENSE_INVALID", license_id)
    if str(lic.get("machine_id") or "") != current_machine:
        return _invalid("MACHINE_MISMATCH", license_id)
    raw_exp = lic.get("expires_at")
    if raw_exp not in (None, ""):
        exp = parse_expires_at(raw_exp)
        if exp is None:
            return _invalid("LICENSE_INVALID", license_id)
        if datetime.now(timezone.utc) > exp:
            return _invalid("LICENSE_EXPIRED", license_id)
    return LicenseResult(valid=True, license_id=license_id, reason="AUTHORIZED")


def verify_file(
    path: Path | None = None,
    *,
    current_machine: str | None = None,
    public_key: bytes | None = None,
) -> LicenseResult:
    global _last_doc
    _last_doc = None
    target = path or license_path()
    try:
        if not target.is_file():
            return _invalid("LICENSE_MISSING")
        raw = target.read_text(encoding="utf-8")
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            return _invalid("LICENSE_INVALID")
        mid = current_machine if current_machine is not None else machine_id()
        result = verify_document(doc, current_machine=mid, public_key=public_key)
        if result.valid:
            _last_doc = doc
        return result
    except json.JSONDecodeError:
        return _invalid("LICENSE_INVALID")
    except OSError:
        return _invalid("LICENSE_MISSING")
    except Exception:
        return _invalid("LICENSE_INVALID")
