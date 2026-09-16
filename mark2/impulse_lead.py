"""Fail-open copy-out from Recon to local dongles. Default OFF. Never blocks Recon."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _truthy(raw: str) -> bool | None:
    val = str(raw or "").strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    return None


def _cfg():
    try:
        from .config import load_config

        return load_config()
    except Exception:
        return None


def leader_enabled(cfg: Any | None = None) -> bool:
    env_flag = _truthy(os.environ.get("IMPULSE_PRO_LEADER", ""))
    if env_flag is False:
        return False
    settings = cfg
    if settings is None and env_flag is None:
        settings = _cfg()
    return bool(env_flag) or bool(getattr(settings, "IMPULSE_PRO_LEADER", False))


def leader_symbol(cfg: Any | None = None) -> str:
    env = os.environ.get("IMPULSE_PRO_SYMBOL", "").strip()
    if env:
        return env.upper()
    settings = cfg if cfg is not None else _cfg()
    return str(getattr(settings, "IMPULSE_PRO_SYMBOL", "") or "NQ").strip().upper() or "NQ"


def _payload_from_order(order: dict[str, Any], cfg: Any | None = None) -> dict[str, Any]:
    action = str(order.get("action") or order.get("side") or "").upper()
    stop = order.get("stop_loss", order.get("stop"))
    try:
        qty = int(order.get("quantity", order.get("qty") or 0))
    except (TypeError, ValueError):
        qty = 0
    return {
        "side": action,
        "qty": qty,
        "ts": time.time(),
        "symbol": str(order.get("symbol") or leader_symbol(cfg)),
        "stop": stop,
    }


def publish_now(order: dict[str, Any], cfg: Any | None = None) -> bool:
    """In-process fanout to dongles connected to this Recon. Never raises."""
    try:
        if not leader_enabled(cfg):
            return False
        from .dongle_host import ingest

        return ingest(_payload_from_order(order, cfg))
    except Exception:
        return False


def maybe_publish(order: dict[str, Any], cfg: Any | None = None) -> None:
    """Background publish. Dongle host down must never delay Recon."""
    try:
        if not leader_enabled(cfg):
            return
        threading.Thread(
            target=publish_now,
            args=(order, cfg),
            daemon=True,
            name="impulse-lead",
        ).start()
    except Exception:
        return
