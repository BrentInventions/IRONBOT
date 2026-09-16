"""Deterministic Windows machine fingerprint. Hash only — no raw serials logged."""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
from typing import Iterable


_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ids = @()
$csp = Get-CimInstance -ClassName Win32_ComputerSystemProduct
if ($csp -and $csp.UUID) { $ids += [string]$csp.UUID }
$bios = Get-CimInstance -ClassName Win32_BIOS
if ($bios -and $bios.SerialNumber) { $ids += [string]$bios.SerialNumber }
$board = Get-CimInstance -ClassName Win32_BaseBoard
if ($board -and $board.SerialNumber) { $ids += [string]$board.SerialNumber }
$ids -join "`n"
"""

_cache_lock = threading.Lock()
_cached_id: str | None = None
_cached_env: str | None = None


def reset_machine_cache() -> None:
    global _cached_id, _cached_env
    with _cache_lock:
        _cached_id = None
        _cached_env = None


def _normalize(value: str) -> str:
    text = (value or "").strip().upper()
    if not text:
        return ""
    junk = {"NONE", "TO BE FILLED BY O.E.M.", "DEFAULT STRING", "N/A", "NA", "0", "NULL"}
    if text in junk:
        return ""
    return " ".join(text.split())


def _hidden_powershell(command: str) -> subprocess.CompletedProcess[str]:
    """Run PowerShell without flashing a console over the HUD."""
    kwargs: dict = {
        "capture_output": True,
        "text": True,
        "timeout": 12,
        "check": False,
    }
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs["creationflags"] = flags
        kwargs["startupinfo"] = startup
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
        **kwargs,
    )


def _wmi_lines() -> list[str]:
    override = os.environ.get("RECON_MACHINE_ID", "").strip()
    if override:
        return [override]
    try:
        proc = _hidden_powershell(_PS)
    except (OSError, subprocess.TimeoutExpired):
        return []
    raw = (proc.stdout or "").replace("\r\n", "\n")
    return [_normalize(line) for line in raw.split("\n") if _normalize(line)]


def fingerprint_parts(parts: Iterable[str] | None = None) -> list[str]:
    if parts is None:
        parts = _wmi_lines()
    return [p for p in (_normalize(p) for p in parts) if p]


def machine_id(parts: Iterable[str] | None = None) -> str:
    """SHA-256 of normalized hardware identifiers. Empty parts are skipped."""
    global _cached_id, _cached_env
    env = os.environ.get("RECON_MACHINE_ID", "").strip()
    if parts is None:
        with _cache_lock:
            if _cached_id is not None and _cached_env == env:
                return _cached_id
    joined = "|".join(fingerprint_parts(parts))
    if not joined:
        joined = "RECON-UNKNOWN-MACHINE"
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    if parts is None:
        with _cache_lock:
            _cached_id = digest
            _cached_env = env
    return digest
