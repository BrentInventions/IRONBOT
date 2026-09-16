"""Decision + trade JSONL logger. Rejected entries are first-class."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .types import EventRecord, MarketSnapshot, RejectReason, ScoreBundle, Side


_CLOUD_MARKERS = ("onedrive", "dropbox", "google drive")


def _cloud_synced(path: Path) -> bool:
    return any(
        any(marker in part.lower() for marker in _CLOUD_MARKERS) for part in path.parts
    )


def local_app_log_path(name: str) -> Path:
    from mark2.config import settings_app_name

    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.getcwd()
    return Path(base) / settings_app_name() / "logs" / name


class AnalyticsLogger:
    def __init__(self, path: Path) -> None:
        self._lock = threading.Lock()
        self._warned = False
        self.path = self._prepare(Path(path))

    def _prepare(self, path: Path) -> Path:
        if _cloud_synced(path):
            path = local_app_log_path(path.name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            fallback = local_app_log_path(path.name)
            fallback.parent.mkdir(parents=True, exist_ok=True)
            return fallback

    def write(self, event: str, **payload: Any) -> None:
        row = {"ts_wall": time.time(), "event": event, **payload}
        data = (json.dumps(row, default=str) + "\n").encode("utf-8")
        with self._lock:
            if self._append(self.path, data):
                return
            fallback = local_app_log_path(self.path.name)
            if fallback != self.path:
                try:
                    fallback.parent.mkdir(parents=True, exist_ok=True)
                except OSError:
                    fallback = None
                if fallback is not None and self._append(fallback, data):
                    self.path = fallback
                    self._warn(f"log moved to {fallback}")
                    return
            self._warn("decision log write failed; continuing without file log")

    def _append(self, path: Path, data: bytes) -> bool:
        try:
            with path.open("ab") as f:
                f.write(data)
            return True
        except OSError:
            try:
                time.sleep(0.05)
                with path.open("ab") as f:
                    f.write(data)
                return True
            except OSError:
                return False

    def _warn(self, msg: str) -> None:
        if self._warned:
            return
        self._warned = True
        print(f"[M2] {msg}", flush=True)

    def decision(
        self,
        *,
        snap: MarketSnapshot,
        scores: ScoreBundle,
        state: str,
        event: EventRecord | None,
        direction: Side,
        entry_decision: str,
        rejection: RejectReason,
        extra: dict | None = None,
    ) -> None:
        rec = extra or {}
        self.write(
            "MARK2_DECISION",
            timestamp=snap.ts,
            price=snap.price,
            direction=direction.value,
            state=state,
            eventType=event.event_type.value if event else "",
            eventId=event.event_id if event else 0,
            LongConfidence=round(scores.long_confidence, 3),
            ShortConfidence=round(scores.short_confidence, 3),
            ConfidenceVelocity=round(
                scores.long_conf_velocity
                if direction == Side.LONG
                else scores.short_conf_velocity,
                4,
            ),
            ConfidenceAcceleration=round(
                scores.long_conf_accel
                if direction == Side.LONG
                else scores.short_conf_accel,
                4,
            ),
            OpportunityScore=round(
                scores.long_opportunity
                if direction == Side.LONG
                else scores.short_opportunity,
                3,
            ),
            ExtensionRisk=round(
                scores.extension_risk_long
                if direction == Side.LONG
                else scores.extension_risk_short,
                3,
            ),
            MomentumHealth=round(scores.trade_health, 3),
            volume=snap.volume,
            relativeVolume=round(snap.relative_volume, 4),
            volumeAcceleration=round(snap.volume_acceleration, 4),
            velocity=round(snap.velocity, 4),
            acceleration=round(snap.acceleration, 4),
            ATR=round(snap.atr, 4),
            volatilityState=snap.volatility_state,
            VWAPDistance=round(snap.vwap_distance_atr, 4),
            structureState=snap.structure_state,
            trendBias=snap.trend_bias,
            trendRegime=snap.trend_regime,
            session=snap.session,
            entryDecision=entry_decision,
            rejectionReason=rejection.value if rejection else "",
            weights=scores.contributors.get("weights") if scores.contributors else None,
            **rec,
        )
