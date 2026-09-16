"""Entry gate tuning — master strictness + per-knob overrides for the HUD."""

from __future__ import annotations

from typing import Any

from .config import Mark2Config

STRICTNESS_MIN = 40.0
STRICTNESS_MAX = 75.0
STRICTNESS_DEFAULT = 45.0

# strictness 40 = loose (more trades), 50 = factory, 75 = strict (fewer / pickier)
_TREND_AT_40 = {
    "confidence": 50.0,
    "opportunity": 45.0,
    "conf_velocity": 0.20,
    "max_extension": 85.0,
    "build_ticks": 2,
    "tick_velocity": 0.05,
}
_TREND_AT_50 = {
    "confidence": 58.0,
    "opportunity": 52.0,
    "conf_velocity": 0.35,
    "max_extension": 72.0,
    "build_ticks": 3,
    "tick_velocity": 0.08,
}
_TREND_AT_75 = {
    "confidence": 68.0,
    "opportunity": 62.0,
    "conf_velocity": 0.50,
    "max_extension": 58.0,
    "build_ticks": 4,
    "tick_velocity": 0.12,
}
_CHOP_AT_40 = {
    "chop_confidence": 48.0,
    "chop_opportunity": 55.0,
    "chop_conf_velocity": 0.12,
    "chop_max_extension": 62.0,
    "chop_build_ticks": 1,
}
_CHOP_AT_50 = {
    "chop_confidence": 52.0,
    "chop_opportunity": 55.0,
    "chop_conf_velocity": 0.18,
    "chop_max_extension": 55.0,
    "chop_build_ticks": 2,
}
_CHOP_AT_75 = {
    "chop_confidence": 58.0,
    "chop_opportunity": 68.0,
    "chop_conf_velocity": 0.28,
    "chop_max_extension": 48.0,
    "chop_build_ticks": 3,
}

_GATE_LIMITS: dict[str, tuple[float, float, str]] = {
    "confidence": (45.0, 75.0, "float"),
    "opportunity": (40.0, 70.0, "float"),
    "conf_velocity": (0.05, 0.65, "float"),
    "max_extension": (45.0, 95.0, "float"),
    "build_ticks": (1.0, 6.0, "int"),
    "tick_velocity": (0.0, 0.25, "float"),
    "chop_confidence": (42.0, 70.0, "float"),
    "chop_opportunity": (45.0, 75.0, "float"),
    "chop_conf_velocity": (0.05, 0.45, "float"),
    "chop_max_extension": (40.0, 75.0, "float"),
    "chop_build_ticks": (1.0, 4.0, "int"),
}


def _clamp_strictness(value: float) -> float:
    return max(STRICTNESS_MIN, min(STRICTNESS_MAX, float(value)))


def _piecewise(s: float, at40: float, at50: float, at75: float) -> float:
    s = _clamp_strictness(s)
    if s <= 50.0:
        return at40 + (s - 40.0) / 10.0 * (at50 - at40)
    return at50 + (s - 50.0) / 25.0 * (at75 - at50)


def gates_from_strictness(strictness: float) -> dict[str, float | int]:
    s = _clamp_strictness(strictness)
    out: dict[str, float | int] = {}
    for key in _TREND_AT_50:
        out[key] = _piecewise(
            s, _TREND_AT_40[key], _TREND_AT_50[key], _TREND_AT_75[key]
        )
        if key == "build_ticks":
            out[key] = int(round(out[key]))
    for key in _CHOP_AT_50:
        out[key] = _piecewise(
            s, _CHOP_AT_40[key], _CHOP_AT_50[key], _CHOP_AT_75[key]
        )
        if key == "chop_build_ticks":
            out[key] = int(round(out[key]))
    return out


def _clamp_gate(name: str, value: float | int) -> float | int:
    lo, hi, kind = _GATE_LIMITS[name]
    if kind == "int":
        return int(max(lo, min(hi, round(float(value)))))
    return round(max(lo, min(hi, float(value))), 2)


def apply_gates(cfg: Mark2Config, gates: dict[str, Any]) -> None:
    mapping = {
        "confidence": (
            "LONG_CONFIDENCE_THRESHOLD",
            "SHORT_CONFIDENCE_THRESHOLD",
        ),
        "opportunity": (
            "LONG_OPPORTUNITY_THRESHOLD",
            "SHORT_OPPORTUNITY_THRESHOLD",
        ),
        "conf_velocity": ("MIN_CONFIDENCE_VELOCITY",),
        "max_extension": ("MAX_EXTENSION_RISK",),
        "build_ticks": ("MOMENTUM_BUILD_TICKS",),
        "tick_velocity": ("MIN_TICK_VELOCITY",),
        "chop_confidence": ("CHOP_SCALP_CONFIDENCE",),
        "chop_opportunity": ("CHOP_SCALP_OPPORTUNITY",),
        "chop_conf_velocity": ("CHOP_SCALP_MIN_CONF_VEL",),
        "chop_max_extension": ("CHOP_SCALP_MAX_EXTENSION",),
        "chop_build_ticks": ("CHOP_SCALP_BUILD_TICKS",),
    }
    for key, val in gates.items():
        if key not in mapping or val is None:
            continue
        clamped = _clamp_gate(key, val)
        for attr in mapping[key]:
            setattr(cfg, attr, clamped)


def apply_strictness(cfg: Mark2Config, strictness: float, *, custom: bool = False) -> float:
    s = _clamp_strictness(strictness)
    cfg.ENTRY_STRICTNESS = s
    cfg.ENTRY_TUNING_CUSTOM = bool(custom)
    if not custom:
        apply_gates(cfg, gates_from_strictness(s))
    return s


def apply_custom_gate(cfg: Mark2Config, name: str, value: float | int) -> float | int:
    if name not in _GATE_LIMITS:
        raise ValueError(f"unknown gate: {name}")
    clamped = _clamp_gate(name, value)
    apply_gates(cfg, {name: clamped})
    cfg.ENTRY_TUNING_CUSTOM = True
    return clamped


def apply_toggles(cfg: Mark2Config, toggles: dict[str, Any]) -> None:
    if "require_trending" in toggles:
        cfg.REQUIRE_TRENDING = bool(toggles["require_trending"])
    if "chop_scalp" in toggles:
        cfg.ENABLE_CHOP_SCALP = bool(toggles["chop_scalp"])
    if "choppy_bias" in toggles:
        cfg.ENABLE_CHOPPY_BIAS = bool(toggles["choppy_bias"])
    if "chaotic_bank" in toggles:
        cfg.ENABLE_CHAOTIC_BANK = bool(toggles["chaotic_bank"])
    if "candle_align" in toggles:
        cfg.REQUIRE_CANDLE_ALIGNMENT = bool(toggles["candle_align"])
    if "book_patterns" in toggles:
        cfg.ENABLE_BOOK_PATTERNS = bool(toggles["book_patterns"])
    if "exhaustion_filter" in toggles:
        cfg.ENABLE_EXHAUSTION_FILTER = bool(toggles["exhaustion_filter"])
    if "ema_strategy" in toggles:
        cfg.ENABLE_EMA_STRATEGY = bool(toggles["ema_strategy"])
    if "grow_mode" in toggles:
        cfg.ENABLE_GROW_MODE = bool(toggles["grow_mode"])
    # Book mode owns the gate set — keep conflicting filters off, RSI override on.
    if bool(getattr(cfg, "ENABLE_BOOK_PATTERNS", False)):
        enforce_book_mode_gates(cfg)
    if bool(getattr(cfg, "ENABLE_EMA_STRATEGY", False)):
        enforce_ema_mode_gates(cfg)


def capture_book_mode_restore(cfg: Mark2Config) -> dict[str, bool]:
    return {
        "require_trending": bool(cfg.REQUIRE_TRENDING),
        "candle_align": bool(cfg.REQUIRE_CANDLE_ALIGNMENT),
        "chop_scalp": bool(getattr(cfg, "ENABLE_CHOP_SCALP", False)),
        "choppy_bias": bool(getattr(cfg, "ENABLE_CHOPPY_BIAS", False)),
        "chaotic_bank": bool(getattr(cfg, "ENABLE_CHAOTIC_BANK", True)),
        "experimental_profile": bool(getattr(cfg, "ENABLE_EXPERIMENTAL_PROFILE", False)),
        "exhaustion_filter": bool(getattr(cfg, "ENABLE_EXHAUSTION_FILTER", False)),
        "ema_strategy": bool(getattr(cfg, "ENABLE_EMA_STRATEGY", False)),
        "deep_hold": bool(getattr(cfg, "ENABLE_DEEP_HOLD", False)),
    }


def enforce_book_mode_gates(cfg: Mark2Config) -> None:
    """Book-patterns-only: patterns + RSI 75/25 + deep $300 hold."""
    cfg.ENABLE_BOOK_PATTERNS = True
    cfg.REQUIRE_TRENDING = False
    cfg.REQUIRE_CANDLE_ALIGNMENT = False
    cfg.ENABLE_CHOP_SCALP = False
    cfg.ENABLE_CHOPPY_BIAS = False
    cfg.ENABLE_CHAOTIC_BANK = False
    cfg.ENABLE_EXHAUSTION_FILTER = True
    cfg.ENABLE_EMA_STRATEGY = False
    cfg.ENABLE_EXPERIMENTAL_PROFILE = False
    cfg.ENABLE_DEEP_HOLD = True
    cfg.RSI_OB_LEVEL = max(75.0, float(getattr(cfg, "RSI_OB_LEVEL", 75.0) or 75.0))
    cfg.RSI_OS_LEVEL = min(25.0, float(getattr(cfg, "RSI_OS_LEVEL", 25.0) or 25.0))
    cfg.DEEP_HOLD_ARM_USD = max(
        50.0, float(getattr(cfg, "DEEP_HOLD_ARM_USD", 300.0) or 300.0)
    )


def enter_book_mode(cfg: Mark2Config) -> dict[str, bool]:
    """Enable book mode; return prior gates so exit can restore them."""
    stash = capture_book_mode_restore(cfg)
    enforce_book_mode_gates(cfg)
    return stash


def exit_book_mode(cfg: Mark2Config, stash: dict[str, bool] | None = None) -> None:
    """Leave book mode and restore gates captured at enter (if any)."""
    cfg.ENABLE_BOOK_PATTERNS = False
    if not stash:
        return
    cfg.REQUIRE_TRENDING = bool(stash.get("require_trending", True))
    cfg.REQUIRE_CANDLE_ALIGNMENT = bool(stash.get("candle_align", True))
    cfg.ENABLE_CHOP_SCALP = bool(stash.get("chop_scalp", False))
    cfg.ENABLE_CHOPPY_BIAS = bool(stash.get("choppy_bias", False))
    cfg.ENABLE_CHAOTIC_BANK = bool(stash.get("chaotic_bank", True))
    cfg.ENABLE_EXHAUSTION_FILTER = bool(stash.get("exhaustion_filter", False))
    cfg.ENABLE_EMA_STRATEGY = bool(stash.get("ema_strategy", False))
    cfg.ENABLE_EXPERIMENTAL_PROFILE = bool(stash.get("experimental_profile", False))
    cfg.ENABLE_DEEP_HOLD = bool(stash.get("deep_hold", False))


def reset_to_defaults(cfg: Mark2Config) -> dict[str, Any]:
    apply_strictness(cfg, STRICTNESS_DEFAULT, custom=False)
    cfg.REQUIRE_TRENDING = True
    cfg.ENABLE_CHOP_SCALP = False
    cfg.ENABLE_CHOPPY_BIAS = False
    cfg.ENABLE_CHAOTIC_BANK = True
    cfg.REQUIRE_CANDLE_ALIGNMENT = True
    cfg.ENABLE_BOOK_PATTERNS = False
    cfg.ENABLE_EXHAUSTION_FILTER = False
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.ENABLE_GROW_MODE = False
    return snapshot(cfg)


def enforce_ema_mode_gates(cfg: Mark2Config) -> None:
    """EMA-only: bearish red-through-white+blue long. Event/book/chop paths stay off."""
    cfg.ENABLE_EMA_STRATEGY = True
    cfg.ENABLE_BOOK_PATTERNS = False
    cfg.ENABLE_CHOP_SCALP = False
    cfg.ENABLE_CHOPPY_BIAS = False
    cfg.ENABLE_CHAOTIC_BANK = False
    cfg.ENABLE_EXPERIMENTAL_PROFILE = False


def snapshot(cfg: Mark2Config) -> dict[str, Any]:
    return {
        "strictness": round(float(getattr(cfg, "ENTRY_STRICTNESS", STRICTNESS_DEFAULT)), 1),
        "custom": bool(getattr(cfg, "ENTRY_TUNING_CUSTOM", False)),
        "trend": {
            "confidence": float(cfg.LONG_CONFIDENCE_THRESHOLD),
            "opportunity": float(cfg.LONG_OPPORTUNITY_THRESHOLD),
            "conf_velocity": float(cfg.MIN_CONFIDENCE_VELOCITY),
            "max_extension": float(cfg.MAX_EXTENSION_RISK),
            "build_ticks": int(cfg.MOMENTUM_BUILD_TICKS),
            "tick_velocity": float(cfg.MIN_TICK_VELOCITY),
        },
        "chop": {
            "confidence": float(getattr(cfg, "CHOP_SCALP_CONFIDENCE", 52.0)),
            "opportunity": float(getattr(cfg, "CHOP_SCALP_OPPORTUNITY", 60.0)),
            "conf_velocity": float(getattr(cfg, "CHOP_SCALP_MIN_CONF_VEL", 0.18)),
            "max_extension": float(getattr(cfg, "CHOP_SCALP_MAX_EXTENSION", 55.0)),
            "build_ticks": int(getattr(cfg, "CHOP_SCALP_BUILD_TICKS", 2)),
        },
        "toggles": {
            "require_trending": bool(cfg.REQUIRE_TRENDING),
            "chop_scalp": bool(getattr(cfg, "ENABLE_CHOP_SCALP", False)),
            "choppy_bias": bool(getattr(cfg, "ENABLE_CHOPPY_BIAS", False)),
            "chaotic_bank": bool(getattr(cfg, "ENABLE_CHAOTIC_BANK", True)),
            "candle_align": bool(cfg.REQUIRE_CANDLE_ALIGNMENT),
            "experimental_profile": bool(getattr(cfg, "ENABLE_EXPERIMENTAL_PROFILE", False)),
            "book_patterns": bool(getattr(cfg, "ENABLE_BOOK_PATTERNS", False)),
            "exhaustion_filter": bool(getattr(cfg, "ENABLE_EXHAUSTION_FILTER", False)),
            "ema_strategy": bool(getattr(cfg, "ENABLE_EMA_STRATEGY", False)),
            "grow_mode": bool(getattr(cfg, "ENABLE_GROW_MODE", False)),
        },
        "limits": {
            k: {"min": v[0], "max": v[1], "step": 1 if v[2] == "int" else 0.01}
            for k, v in _GATE_LIMITS.items()
        },
    }
