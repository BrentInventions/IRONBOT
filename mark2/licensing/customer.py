"""Customer profile shipped next to the exe. auto_bind never issues a license."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .paths import app_home, frozen

WILLIE_CUSTOMER = "WILLIE"


@dataclass(frozen=True)
class CustomerProfile:
    customer_id: str
    license_id: str
    auto_bind: bool
    license_server_url: str

    @property
    def willie_autobind(self) -> bool:
        """Kept for compatibility. Does not grant a license."""
        return False


def is_loopback_server_url(url: str) -> bool:
    """True for 127.0.0.1 / localhost / ::1."""
    text = (url or "").strip()
    if not text:
        return False
    if "://" not in text:
        text = "http://" + text
    try:
        host = (urlparse(text).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _usable_server_url(url: str) -> str:
    text = (url or "").strip().rstrip("/")
    if not text or is_loopback_server_url(text):
        return ""
    return text


def load_profile(path: Path | None = None) -> CustomerProfile:
    target = path or (app_home() / "recon_customer.json")
    raw: dict = {}
    if target.is_file():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, json.JSONDecodeError):
            raw = {}
    json_url = str(raw.get("license_server_url") or "").strip()
    url = json_url
    # Notepad-safe .txt first. Legacy .url is a fallback only — Windows
    # treats *.url as an Internet Shortcut, so do not ship that name.
    # Localhost / empty address files are ignored — they would make a
    # customer exe talk to itself instead of the owner's server.
    for name in ("license_server.txt", "license_server.url"):
        candidate = app_home() / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text and not is_loopback_server_url(text):
            url = text
            break
    if frozen():
        url = _usable_server_url(url) or _usable_server_url(json_url)
    return CustomerProfile(
        customer_id=str(raw.get("customer_id") or "").strip(),
        license_id=str(raw.get("license_id") or "RECON-WILLIE-001").strip(),
        auto_bind=bool(raw.get("auto_bind")),
        license_server_url=url.rstrip("/"),
    )
