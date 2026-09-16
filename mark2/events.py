"""Market events, not candles. One identity per developing opportunity."""

from __future__ import annotations

from .config import Mark2Config
from .types import EventRecord, EventType, MarketSnapshot, ScoreBundle, Side


class EventDetector:
    def __init__(self, cfg: Mark2Config) -> None:
        self.cfg = cfg
        self._next_id = 1
        self.active: EventRecord | None = None
        self._fade_streak = 0

    def detect(
        self, snap: MarketSnapshot, scores: ScoreBundle
    ) -> tuple[EventRecord | None, str]:
        """Return (active_or_new_event, reject_or_status)."""
        direction, etype = self._classify(snap, scores)
        conf = scores.long_confidence if direction == Side.LONG else scores.short_confidence
        opp = scores.long_opportunity if direction == Side.LONG else scores.short_opportunity

        if self.active and not self.active.ended:
            if self._same_event(self.active, direction, etype, snap):
                self.active.peak_confidence = max(self.active.peak_confidence, conf)
                self.active.peak_opportunity = max(self.active.peak_opportunity, opp)
                if conf < self.cfg.EVENT_RESET_THRESHOLD or abs(float(snap.velocity)) < 0.18:
                    self._fade_streak += 1
                else:
                    self._fade_streak = 0
                if self._fade_streak >= int(self.cfg.EVENT_END_STREAK):
                    self.active.ended = True
                    self.active.end_ts = snap.ts
                    self.active.end_reason = "CONFIDENCE_RESET"
                    self._fade_streak = 0
                    return self.active, "EVENT_ENDED"
                return self.active, "EVENT_CONTINUING"
            # Different event while one is open — only start new if old ended
            if not self.active.ended:
                if self.active.entry_taken or self.active.logged_opportunity:
                    return self.active, "REJECT_DUPLICATE_EVENT"
                # Weak untraded event can be replaced by a stronger independent one
                if opp + conf < (
                    self.active.peak_opportunity + self.active.peak_confidence
                ) * 0.9:
                    return self.active, "REJECT_DUPLICATE_EVENT"
                self.active.ended = True
                self.active.end_ts = snap.ts
                self.active.end_reason = "SUPERSEDED"

        if direction == Side.NONE or etype == EventType.NONE:
            return None, ""

        rec = EventRecord(
            event_id=self._next_id,
            event_type=etype,
            direction=direction,
            started_ts=snap.ts,
            started_price=float(snap.price),
            started_bar_time=str((snap.forming_bar or {}).get("time") or ""),
            peak_confidence=conf,
            peak_opportunity=opp,
        )
        self._next_id += 1
        self.active = rec
        self._fade_streak = 0
        return rec, "EVENT_DETECTED"

    def mark_consumed(self, *, taken: bool) -> None:
        if self.active is None:
            return
        if taken:
            self.active.entry_taken = True
        else:
            self.active.logged_opportunity = True

    def release_after_trade(self, ts: float, event_id: int = 0) -> None:
        """End the impulse that opened a trade so post-exit ticks can form new events."""
        if self.active is None:
            return
        if event_id and self.active.event_id != event_id:
            return
        self.active.ended = True
        self.active.end_ts = ts
        self.active.end_reason = "TRADE_CLOSED"
        self._fade_streak = 0

    def _same_event(
        self,
        rec: EventRecord,
        direction: Side,
        etype: EventType,
        snap: MarketSnapshot,
    ) -> bool:
        if rec.direction != direction:
            return False
        bar_t = str((snap.forming_bar or {}).get("time") or "")
        if rec.started_bar_time and bar_t and rec.started_bar_time == bar_t:
            return True
        # Same direction continuing within a few seconds is the same impulse
        if etype == rec.event_type or etype == EventType.NONE:
            return (snap.ts - rec.started_ts) < 45.0
        return False

    def _classify(
        self, snap: MarketSnapshot, scores: ScoreBundle
    ) -> tuple[Side, EventType]:
        long_ok = scores.long_opportunity >= scores.short_opportunity
        side = Side.LONG if long_ok else Side.SHORT
        conf = scores.long_confidence if side == Side.LONG else scores.short_confidence
        opp = scores.long_opportunity if side == Side.LONG else scores.short_opportunity
        if conf < 40 and opp < 45:
            return Side.NONE, EventType.NONE

        ev = self.cfg.events
        signed_vel = snap.velocity if side == Side.LONG else -snap.velocity
        candidates: list[tuple[float, EventType]] = []
        if ev.volume_expansion and snap.relative_volume >= 1.15:
            candidates.append((snap.relative_volume, EventType.VOLUME_EXPANSION))
        if ev.momentum_expansion and signed_vel > 0.4:
            candidates.append((abs(snap.velocity), EventType.MOMENTUM_EXPANSION))
        if ev.impulse and snap.impulse_score >= self.cfg.IMPULSE_MIN:
            candidates.append((snap.impulse_score / 100.0, EventType.IMPULSE))
        if ev.volatility_expansion and snap.volatility_state == "expanding":
            candidates.append((0.8, EventType.VOLATILITY_EXPANSION))
        if ev.breakout:
            if side == Side.LONG and snap.swing_high > 0 and snap.price > snap.swing_high:
                candidates.append((1.0, EventType.BREAKOUT))
            if side == Side.SHORT and snap.swing_low > 0 and snap.price < snap.swing_low:
                candidates.append((1.0, EventType.BREAKOUT))
        if ev.pullback_continuation:
            form = snap.forming_bar or {}
            fo = float(form.get("open") or snap.price)
            if side == Side.LONG and snap.trend_bias in ("BULLISH", "BULL") and snap.price >= fo:
                if snap.ema_distance_atr <= 0.35:
                    candidates.append((0.7, EventType.PULLBACK_CONTINUATION))
            if side == Side.SHORT and snap.trend_bias in ("BEARISH", "BEAR") and snap.price <= fo:
                if snap.ema_distance_atr >= -0.35:
                    candidates.append((0.7, EventType.PULLBACK_CONTINUATION))

        if not candidates:
            return Side.NONE, EventType.NONE
        candidates.sort(key=lambda x: x[0], reverse=True)
        return side, candidates[0][1]
