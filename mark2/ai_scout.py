"""AI Scout — second set of eyes on the same 9 / 20 / 50 intersection.

Take a 9/50 confirm, including leftover stacked longs that are still rising.
Leftover shorts stay HOLD.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Mark2Config
from .ema_strategy import (
    EmaStack,
    intersection_status,
    red_above_white_and_blue,
    red_below_white_and_blue,
    red_falling,
    red_rising,
)
from .types import Side

_OVERRIDE_FIRE = {
    "EMA_SNIPER_LONG",
    "EMA_SNIPER_SHORT",
    "EMA_INTERSECTION_LONG",
    "EMA_INTERSECTION_SHORT",
    "ENTER LONG",
    "ENTER SHORT",
}


@dataclass
class ScoutView:
    side: Side = Side.NONE
    action: str = "HOLD"
    why: str = ""
    confidence: float = 0.0
    bullets: list[str] = field(default_factory=list)
    miss: bool = False

    def hud(self) -> dict:
        return {
            "side": self.side.value if self.side != Side.NONE else "",
            "action": self.action,
            "why": self.why,
            "confidence": round(float(self.confidence), 1),
            "bullets": list(self.bullets),
            "miss": bool(self.miss),
        }


def _ext_atr(price: float, stack: EmaStack, atr: float, side: Side) -> float:
    atr_v = max(float(atr), 1e-9)
    if side == Side.LONG:
        return max(0.0, float(price) - float(stack.ema20)) / atr_v
    if side == Side.SHORT:
        return max(0.0, float(stack.ema20) - float(price)) / atr_v
    return 0.0


def _hold(bullets: list[str], *, why: str = "") -> ScoutView:
    return ScoutView(action="HOLD", why=why, bullets=bullets or ["READING 9 / 20 / 50"])


def _was_real_fire(missed_why: str) -> bool:
    tag = str(missed_why or "").upper()
    return any(key in tag for key in _OVERRIDE_FIRE)


def _fresh_long(stack: EmaStack, atr: float, cfg: Mark2Config, bars: list | None = None) -> bool:
    st = intersection_status(stack, cfg, atr, bars=bars)
    return st.fire and st.side == "LONG" and red_rising(stack)


def _fresh_short(stack: EmaStack, atr: float, cfg: Mark2Config, bars: list | None = None) -> bool:
    st = intersection_status(stack, cfg, atr, bars=bars)
    return st.fire and st.side == "SHORT" and red_falling(stack)


def scout_opportunity(
    *,
    stack: EmaStack | None,
    price: float,
    atr: float,
    bot_watch: str = "",
    missed_side: Side = Side.NONE,
    missed_why: str = "",
    cfg: Mark2Config | None = None,
    in_trade: bool = False,
    scout_long_taken: bool = False,
    scout_short_taken: bool = False,
) -> ScoutView:
    """HOLD / TAKE / OVERRIDE — longs can take a stacked rising 9. Short leftovers stay HOLD."""
    cfg = cfg or Mark2Config()
    if not bool(getattr(cfg, "ENABLE_AI_SCOUT", True)):
        return _hold(["SCOUT OFF"])
    if in_trade:
        return _hold(["IN TRADE · SCOUT STANDS DOWN"], why="IN_TRADE")
    if stack is None or float(stack.ema50) <= 0:
        return _hold(["WARMING UP BLUE"])

    allow_long = bool(getattr(cfg, "AI_SCOUT_LONG", True))
    allow_short = bool(getattr(cfg, "AI_SCOUT_SHORT", False))
    allow_override = bool(getattr(cfg, "AI_SCOUT_OVERRIDE_MISSED", True))
    max_ext = float(getattr(cfg, "AI_SCOUT_MAX_EXT_ATR", 2.8) or 2.8)
    take_ext = float(getattr(cfg, "MAX_ENTRY_EXTENSION_ATR", 0.60) or 0.60)
    watch = str(bot_watch or "").upper()
    px = float(price)
    ix = intersection_status(stack, cfg, atr)
    fresh_long = _fresh_long(stack, atr, cfg)
    fresh_short = _fresh_short(stack, atr, cfg)

    if allow_override and missed_side == Side.LONG and allow_long and not scout_long_taken:
        if _was_real_fire(missed_why) and fresh_long:
            ext = _ext_atr(px, stack, atr, Side.LONG)
            if ext <= max_ext + 1e-12:
                return ScoutView(
                    side=Side.LONG,
                    action="OVERRIDE",
                    why="AI_SCOUT_OVERRIDE_LONG",
                    confidence=88.0,
                    miss=True,
                    bullets=[
                        f"BOT FIRED {missed_why or 'LONG'} AND DID NOT HOLD",
                        "FRESH INTERSECTION STILL THROUGH",
                        "SCOUT TAKES THE MISS",
                    ],
                )

    if allow_override and missed_side == Side.SHORT and allow_short and not scout_short_taken:
        if _was_real_fire(missed_why) and fresh_short:
            ext = _ext_atr(px, stack, atr, Side.SHORT)
            if ext <= max_ext + 1e-12:
                return ScoutView(
                    side=Side.SHORT,
                    action="OVERRIDE",
                    why="AI_SCOUT_OVERRIDE_SHORT",
                    confidence=88.0,
                    miss=True,
                    bullets=[
                        f"BOT FIRED {missed_why or 'SHORT'} AND DID NOT HOLD",
                        "FRESH INTERSECTION STILL UNDER",
                        "SCOUT TAKES THE MISS",
                    ],
                )

    if allow_long and not scout_long_taken and fresh_long:
        ext = _ext_atr(px, stack, atr, Side.LONG)
        if ext <= max_ext + 1e-12:
            return ScoutView(
                side=Side.LONG,
                action="TAKE",
                why="AI_SCOUT_LONG",
                confidence=80.0,
                bullets=[
                    "EMA_INTERSECTION_LONG · 9 ABOVE WHITE AND BLUE",
                    f"PRE-CROSS SEP {ix.pre_sep_atr:.2f} ATR",
                    f"BOT SAID {watch or 'WAIT'} · EXT {ext:.2f} ATR",
                ],
            )

    if allow_short and not scout_short_taken and fresh_short:
        ext = _ext_atr(px, stack, atr, Side.SHORT)
        if ext <= take_ext + 1e-12:
            return ScoutView(
                side=Side.SHORT,
                action="TAKE",
                why="AI_SCOUT_SHORT",
                confidence=78.0,
                bullets=[
                    "EMA_INTERSECTION_SHORT · 9/50 CONFIRM",
                    f"PRE-CROSS SEP {ix.pre_sep_atr:.2f} ATR",
                    f"BOT SAID {watch or 'WAIT'} · EXT {ext:.2f} ATR",
                ],
            )

    hud = ix.hud()
    bullets = [
        f"SEP {hud['sepAtr']:.2f} ATR {hud['sepMark']}",
        f"9/20 {hud['cross920']} · 9/50 {hud['cross950']}",
        f"TIGHT {str(hud['tight']).upper()} · BOT {watch or 'WAIT'}",
    ]
    if red_above_white_and_blue(stack) and not fresh_long:
        bullets.append("STACKED LONG · WAITING FOR 9 TO RISE")
    elif red_below_white_and_blue(stack) and not fresh_short:
        bullets.append("STACKED UNDER · NOT A NEW INTERSECTION · HOLD")
    elif ix.tight:
        bullets.append("TIGHT STRUCTURE · NO TRADE")
    elif ix.armed_920:
        bullets.append("WAITING FOR 9/50 CONFIRM")
    else:
        bullets.append("WAITING FOR SPREAD 9/20 THEN 9/50")
    return _hold(bullets, why="WAIT_CROSS")
