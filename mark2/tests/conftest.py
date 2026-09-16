"""Existing trading tests stay licensed. Licensing tests clear this env."""

from __future__ import annotations

import os

os.environ.setdefault("RECON_LICENSE_BYPASS", "1")

from pathlib import Path

_scratch = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")
os.environ.setdefault("MARK2_TCM8_LEDGER", str(_scratch / "tcm8_ledger_pytest.json"))
os.environ.setdefault("MARK2_TCM8_STATUS", str(_scratch / "tcm8_status_pytest.json"))
