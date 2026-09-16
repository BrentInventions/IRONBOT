"""Product identity overlays. Tiante is a paid Recon duplicate — not Willie."""

from __future__ import annotations

import os
from typing import Any

TIANTE_PORT = 5566

TIANTE: dict[str, Any] = {
    "PRODUCT_NAME": "TIANTE SNIPER",
    "PRODUCT_ENGINE": "TianteSniper",
    "KICKER_LONG": "TIANTE LONG",
    "KICKER_SHORT": "TIANTE SHORT",
    "BRIDGE_NAME": "TianteSniperBridge",
    "BRIDGE_PORT": TIANTE_PORT,
    "IMPULSE_PRO_LEADER": False,
    "IMPULSE_PRO_URL": "",
    "IMPULSE_PRO_TOKEN": "",
    "LICENSE_SERVER_URL": "",
}

RECON: dict[str, Any] = {
    "PRODUCT_NAME": "RECON SNIPER",
    "PRODUCT_ENGINE": "ReconSniper",
    "KICKER_LONG": "RECON LONG",
    "KICKER_SHORT": "RECON SHORT",
    "BRIDGE_NAME": "ReconSniperBridge",
    "BRIDGE_PORT": 5564,
}


def product_key() -> str:
    raw = (os.environ.get("MARK2_PRODUCT") or "").strip().upper()
    if raw in {"TIANTE", "TIANTE_SNIPER", "TIANTESNIPER"}:
        return "TIANTE"
    return "RECON"


def apply_product(cfg: Any) -> Any:
    """Force identity after load_config so a copied settings JSON cannot steal the other bot."""
    overlay = TIANTE if product_key() == "TIANTE" else None
    if overlay is None:
        return cfg
    for key, value in overlay.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg
