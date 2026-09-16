"""Legacy name. Registration never issues a license — owner must approve."""

from __future__ import annotations

from pathlib import Path

from .customer import CustomerProfile
from .register import request_register, try_register_and_fetch
from .validator import LicenseResult


def request_willie_bind(
    *,
    machine_hash: str,
    profile: CustomerProfile,
    timeout: float = 8.0,
) -> dict | None:
    return request_register(machine_hash=machine_hash, profile=profile, timeout=timeout)


def try_willie_autobind(
    *,
    machine_hash: str,
    profile: CustomerProfile,
    dest: Path | None = None,
) -> LicenseResult | None:
    return try_register_and_fetch(machine_hash=machine_hash, profile=profile, dest=dest)
