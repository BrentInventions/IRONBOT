"""Tests for entry tuning strictness + custom gates."""

from __future__ import annotations

from mark2.config import Mark2Config
from mark2.entry_tuning import (
    apply_custom_gate,
    apply_strictness,
    apply_toggles,
    gates_from_strictness,
    reset_to_defaults,
    snapshot,
)


def test_strictness_45_matches_new_factory_defaults():
    gates = gates_from_strictness(45)
    assert gates["confidence"] == 54.0
    assert gates["chop_opportunity"] == 55.0


def test_strictness_50_matches_mid_defaults():
    gates = gates_from_strictness(50)
    assert gates["confidence"] == 58.0
    assert gates["opportunity"] == 52.0
    assert gates["build_ticks"] == 3
    assert gates["chop_confidence"] == 52.0


def test_strictness_loose_vs_strict():
    loose = gates_from_strictness(40)
    strict = gates_from_strictness(75)
    assert loose["confidence"] < strict["confidence"]
    assert loose["max_extension"] > strict["max_extension"]


def test_apply_strictness_updates_cfg():
    cfg = Mark2Config()
    apply_strictness(cfg, 65, custom=False)
    assert cfg.LONG_CONFIDENCE_THRESHOLD == cfg.SHORT_CONFIDENCE_THRESHOLD
    assert cfg.LONG_CONFIDENCE_THRESHOLD > 58.0
    assert cfg.ENTRY_TUNING_CUSTOM is False


def test_custom_gate_marks_custom():
    cfg = Mark2Config()
    apply_strictness(cfg, 50, custom=False)
    apply_custom_gate(cfg, "confidence", 61.0)
    assert cfg.ENTRY_TUNING_CUSTOM is True
    assert cfg.LONG_CONFIDENCE_THRESHOLD == 61.0


def test_reset_to_defaults():
    cfg = Mark2Config()
    apply_custom_gate(cfg, "confidence", 70.0)
    apply_toggles(cfg, {"grow_mode": True})
    reset_to_defaults(cfg)
    snap = snapshot(cfg)
    assert snap["trend"]["confidence"] == 54.0
    assert snap["custom"] is False
    assert snap["toggles"]["grow_mode"] is False
    assert cfg.ENABLE_GROW_MODE is False
