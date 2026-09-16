"""Live brain unwrap. A patched authorized flag still gets the decoy numbers."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .paths import bundle_root, frozen
from .validator import LicenseResult


# Looks like Recon. Fires leftover knots, then yanks. Used when unwrap fails.
DECOY: dict[str, Any] = {
    "EMA_REQUIRE_SEP": False,
    "EMA_MIN_SEP_ATR": 0.01,
    "EMA_MIN_SEP_POINTS": 0.25,
    "EMA_SEP_MIN_BARS": 1,
    "EMA_SETUP_MAX_BARS": 2,
    "EMA_THROUGH_SLACK": 6.0,
    "EMA_INTERSECT_ATR": 0.12,
    "MAX_ENTRY_EXTENSION_ATR": 3.5,
    "EMA_HARD_STOP_POINTS": 1.5,
    "INITIAL_STOP_ATR": 0.35,
    "CATASTROPHIC_STOP_ATR": 0.40,
    "INITIAL_STOP_POINTS": 1.5,
    "DOLLAR_LOCK_1_TRIGGER": 8000.0,
    "DOLLAR_LOCK_1_PROFIT": 0.5,
    "DOLLAR_LOCK_2_TRIGGER": 8000.0,
    "TIP_TRAIL_ARM_USD": 8000.0,
    "ADVERSE_STACK_BARS": 1,
    "ADVERSE_STACK_MIN_USD": 0.0,
    "CONFIRMED_STOP_ATR_FROM_ENTRY": 0.05,
    "MFE_GIVEBACK_FRAC": 0.02,
    "ENABLE_GROW_MODE": False,
    "ENABLE_PULLBACK_ENTRY": False,
    "OPPOSITE_CROSS_REQUIRES_CONFIRM": False,
    "EMA_OPPOSITE_CROSS_EXIT": True,
    "CONTRACTS": 1,
}

_SALT = b"recon-runtime-v1"


def runtime_key_path() -> Path:
    override = os.environ.get("RECON_LICENSING_HOME", "").strip()
    home = Path(override) if override else Path(os.environ.get("USERPROFILE") or Path.home()) / ".recon-licensing"
    return home / "runtime.key"


def load_runtime_key() -> bytes | None:
    env = os.environ.get("RECON_RUNTIME_KEY_HEX", "").strip()
    if env:
        try:
            raw = bytes.fromhex(env)
        except ValueError:
            return None
        return raw if len(raw) == 32 else None
    path = runtime_key_path()
    if not path.is_file():
        return None
    raw = path.read_bytes().strip()
    if len(raw) == 32:
        return raw
    try:
        decoded = bytes.fromhex(raw.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return None
    return decoded if len(decoded) == 32 else None


def ensure_runtime_key() -> bytes:
    existing = load_runtime_key()
    if existing:
        return existing
    path = runtime_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    path.write_bytes(key)
    return key


def _kek(machine_id: str) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=_SALT, info=b"wrap").derive(
        machine_id.encode("ascii")
    )


def wrap_runtime_key(machine_id: str, runtime_key: bytes) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_kek(machine_id)).encrypt(nonce, runtime_key, b"recon-wrap")
    return base64.b64encode(nonce + ct).decode("ascii")


def unwrap_runtime_key(machine_id: str, wrap_b64: str) -> bytes | None:
    try:
        raw = base64.b64decode(wrap_b64, validate=True)
        if len(raw) < 13:
            return None
        key = AESGCM(_kek(machine_id)).decrypt(raw[:12], raw[12:], b"recon-wrap")
    except Exception:
        return None
    return key if len(key) == 32 else None


def encrypt_overlay(overlay: dict[str, Any], runtime_key: bytes) -> bytes:
    nonce = os.urandom(12)
    body = json.dumps(overlay, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return nonce + AESGCM(runtime_key).encrypt(nonce, body, b"recon-brain")


def decrypt_overlay(blob: bytes, runtime_key: bytes) -> dict[str, Any] | None:
    if len(blob) < 13:
        return None
    try:
        raw = AESGCM(runtime_key).decrypt(blob[:12], blob[12:], b"recon-brain")
        doc = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def blob_path() -> Path:
    env = os.environ.get("RECON_RUNTIME_BLOB", "").strip()
    if env:
        return Path(env)
    return bundle_root() / "licensing" / "runtime.bin"


def apply_overlay(cfg: Any, overlay: dict[str, Any]) -> None:
    weights = overlay.get("weights") if isinstance(overlay.get("weights"), dict) else {}
    events = overlay.get("events") if isinstance(overlay.get("events"), dict) else {}
    for key, value in overlay.items():
        if key in {"weights", "events"}:
            continue
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    for key, value in weights.items():
        if hasattr(cfg, "weights") and hasattr(cfg.weights, key):
            setattr(cfg.weights, key, float(value))
    for key, value in events.items():
        if hasattr(cfg, "events") and hasattr(cfg.events, key):
            setattr(cfg.events, key, bool(value))


def unlock_overlay() -> dict[str, Any] | None:
    from .validator import last_document

    doc = last_document()
    if not isinstance(doc, dict):
        return None
    lic = doc.get("license")
    if not isinstance(lic, dict):
        return None
    wrap = str(lic.get("runtime_wrap") or "").strip()
    machine = str(lic.get("machine_id") or "").strip()
    if not wrap or not machine:
        return None
    runtime_key = unwrap_runtime_key(machine, wrap)
    if runtime_key is None:
        return None
    path = blob_path()
    if not path.is_file():
        return None
    try:
        return decrypt_overlay(path.read_bytes(), runtime_key)
    except OSError:
        return None


def bind_runtime(cfg: Any, result: LicenseResult) -> None:
    """Frozen customer: real numbers only after a cryptographic unwrap."""
    from .manager import pytest_bypass

    if pytest_bypass():
        return
    from .manager import offline_ok

    if offline_ok():
        return
    if not frozen():
        return
    overlay = unlock_overlay() if result.valid else None
    apply_overlay(cfg, overlay if overlay else DECOY)
