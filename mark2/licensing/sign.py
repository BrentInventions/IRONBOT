"""Sign a license payload. Used by the owner server / tests — not shipped as a customer tool."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .canon import canonical_bytes


def build_license(
    *,
    machine_id: str,
    license_id: str,
    customer_id: str,
    private_key: Ed25519PrivateKey,
    expires_at: str | None = None,
) -> dict[str, Any]:
    payload = {
        "product": "RECON",
        "license_id": license_id,
        "customer_id": customer_id,
        "machine_id": machine_id,
        "status": "ACTIVE",
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (expires_at or "").strip(),
        "license_version": 1,
    }
    sig = private_key.sign(canonical_bytes(payload))
    return {"license": payload, "signature": base64.b64encode(sig).decode("ascii")}
