"""Canonical license JSON for Ed25519 sign / verify."""

from __future__ import annotations

import json
from typing import Any


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
