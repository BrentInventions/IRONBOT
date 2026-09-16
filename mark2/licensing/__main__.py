"""Print this PC's machine fingerprint hash (no raw serials)."""

from __future__ import annotations

from .machine import machine_id


def main() -> int:
    print(machine_id())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
