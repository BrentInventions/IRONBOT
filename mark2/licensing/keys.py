"""Embedded Ed25519 public key. The private key never ships with Recon."""

from __future__ import annotations

import os

# Raw Ed25519 public key (32 bytes), hex. Rotate by issuing new licenses.
PUBLIC_KEY_HEX = "edc601086d1d04b3bc6577b4ac0ed0e7c7ed57f034468e39f62f0b31bf8bb363"


def public_key_bytes() -> bytes:
    override = os.environ.get("RECON_PUBLIC_KEY_HEX", "").strip()
    raw = override or PUBLIC_KEY_HEX
    return bytes.fromhex(raw)
