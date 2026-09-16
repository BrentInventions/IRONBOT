"""Machine fingerprint is cached and never flashes a console over the HUD."""

from __future__ import annotations

import subprocess

from mark2.licensing.machine import machine_id, reset_machine_cache
from mark2.licensing.manager import license_hud, reset_for_tests
from mark2.licensing.register import _write_license_document
from mark2.licensing.validator import LicenseResult


def test_machine_id_cached_skips_second_wmi(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_wmi() -> list[str]:
        calls["n"] += 1
        return ["UUID-ONE"]

    reset_machine_cache()
    monkeypatch.delenv("RECON_MACHINE_ID", raising=False)
    monkeypatch.setattr("mark2.licensing.machine._wmi_lines", fake_wmi)
    first = machine_id()
    second = machine_id()
    assert first == second
    assert calls["n"] == 1


def test_machine_id_env_change_busts_cache(monkeypatch) -> None:
    reset_machine_cache()
    monkeypatch.setenv("RECON_MACHINE_ID", "alpha-box")
    a = machine_id()
    monkeypatch.setenv("RECON_MACHINE_ID", "bravo-box")
    b = machine_id()
    assert a != b


def test_hidden_powershell_sets_no_window(monkeypatch) -> None:
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs

        class _P:
            stdout = ""

        return _P()

    monkeypatch.setattr(subprocess, "run", fake_run)
    from mark2.licensing import machine as machine_mod

    machine_mod._hidden_powershell("Write-Output 1")
    assert "-WindowStyle" in seen["cmd"]
    assert "Hidden" in seen["cmd"]
    flags = seen["kwargs"].get("creationflags", 0)
    assert flags & 0x08000000
    startup = seen["kwargs"].get("startupinfo")
    assert startup is not None
    assert startup.dwFlags & subprocess.STARTF_USESHOWWINDOW


def test_license_hud_does_not_call_machine_id(monkeypatch) -> None:
    reset_for_tests()
    from mark2.licensing import manager as mgr

    mgr.adopt_result(LicenseResult(valid=True, license_id="RECON-TEST", reason="AUTHORIZED"))

    def boom(*_a, **_k):
        raise AssertionError("HUD must not fingerprint")

    monkeypatch.setattr("mark2.licensing.machine.machine_id", boom)
    monkeypatch.setattr("mark2.licensing.manager.machine_id", boom)
    hud = license_hud()
    assert hud["valid"] is True
    assert hud["status"] == "AUTHORIZED"


def test_write_license_skips_identical_bytes(tmp_path) -> None:
    path = tmp_path / "recon.license"
    doc = {"license": {"machine_id": "x"}, "ok": True}
    assert _write_license_document(path, doc) is True
    first = path.read_bytes()
    path.write_bytes(first)  # same content
    mtime = path.stat().st_mtime_ns
    assert _write_license_document(path, doc) is True
    assert path.stat().st_mtime_ns == mtime
    assert path.read_bytes() == first
