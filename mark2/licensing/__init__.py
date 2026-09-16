"""Machine-bound Recon license. Possession of files is not authorization."""

from .manager import LicenseResult, evaluate, is_authorized, license_hud, reset_for_tests
from .machine import machine_id

__all__ = [
    "LicenseResult",
    "evaluate",
    "is_authorized",
    "license_hud",
    "machine_id",
    "reset_for_tests",
]
