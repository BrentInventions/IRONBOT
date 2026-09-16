"""Structure alignment gate — blocks counter-structure entries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import MarketSnapshot, Side

if TYPE_CHECKING:
    from .bias_entry import BiasEntryGates
    from .config import Mark2Config


def structure_blocks_entry(
    snap: MarketSnapshot,
    side: Side,
    cfg: Mark2Config,
    *,
    bias_gates: BiasEntryGates | None = None,
) -> bool:
    """True when structure state hard-blocks this side."""
    if not bool(getattr(cfg, "REQUIRE_STRUCTURE_ALIGNMENT", True)):
        return False
    if (
        bias_gates is not None
        and bias_gates.active
        and bool(getattr(bias_gates, "relax_structure", False))
    ):
        return False
    st = (snap.structure_state or "MIXED").upper()
    if side == Side.LONG and st == "LH_LL":
        return True
    if side == Side.SHORT and st == "HH_HL":
        return True
    return False
