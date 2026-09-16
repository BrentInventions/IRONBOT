"""Market Extension Engine for MNQ — chase protection, not auto-entries.

Two scores:
  EXTENSION (0–100)     — how stretched is price (RSI/Stoch/Williams/VWAP/BB/CCI)
  MOMENTUM HEALTH (−100…+100) — is the move still accelerating or dying (MACD-led)

MACD is confirmation: direction, histogram growth/shrink, crossovers, simple divergence.
Never: MACD bullish → BUY. Use with extension to block tip-chase / falling knives
while allowing monster trends that are still accelerating.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Mark2Config
from .indicators import bollinger, cci, macd, rsi, stoch_rsi, williams_r
from .types import MarketSnapshot, Side


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


def _clamp_mom(x: float) -> float:
    return max(-100.0, min(100.0, float(x)))


@dataclass(frozen=True)
class ExhaustionReading:
    rsi: float = 50.0
    stoch_rsi: float = 50.0
    bb_pct_b: float = 0.5
    vwap_sigma: float = 0.0
    williams_r: float = -50.0
    cci: float = 0.0
    # Dual engine
    extension_long: float = 0.0  # 0–100 upside stretch
    extension_short: float = 0.0  # 0–100 downside stretch
    momentum_health: float = 0.0  # −100…+100 (bullish +)
    # MACD
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    macd_hist_delta: float = 0.0
    macd_cross: str = ""
    macd_div: str = ""  # "bear" | "bull" | ""
    # Combined chase risk (extension × dying momentum)
    long_chase: float = 0.0
    short_chase: float = 0.0

    @property
    def extreme_ob(self) -> bool:
        return self.rsi >= 80.0 or self.extension_long >= 85.0

    @property
    def extreme_os(self) -> bool:
        return self.rsi <= 20.0 or self.extension_short >= 85.0


def _macd_divergence(closes: list[float], hists: list[float]) -> str:
    """Simple bearish/bullish hist divergence vs price over last ~20 bars."""
    n = min(len(closes), len(hists), 24)
    if n < 12:
        return ""
    c = closes[-n:]
    h = hists[-n:]
    # Split halves
    mid = n // 2
    px_hi1, px_hi2 = max(c[:mid]), max(c[mid:])
    hx1 = max(h[:mid])
    hx2 = max(h[mid:])
    px_lo1, px_lo2 = min(c[:mid]), min(c[mid:])
    hn1 = min(h[:mid])
    hn2 = min(h[mid:])
    # Bearish: price higher high, hist lower high
    if px_hi2 > px_hi1 * 1.0001 and hx2 < hx1:
        return "bear"
    # Bullish: price lower low, hist higher low
    if px_lo2 < px_lo1 * 0.9999 and hn2 > hn1:
        return "bull"
    return ""


def read_exhaustion(
    snap: MarketSnapshot,
    cfg: Mark2Config,
) -> ExhaustionReading:
    bars = list(snap.completed_bars or [])
    form = snap.forming_bar
    if form and float(form.get("close") or form.get("open") or 0) > 0:
        bars = bars + [form]
    rsi_n = int(getattr(cfg, "RSI_PERIOD", 14) or 14)
    bb_n = int(getattr(cfg, "BB_PERIOD", 20) or 20)
    macd_fast = int(getattr(cfg, "MACD_FAST", 12) or 12)
    macd_slow = int(getattr(cfg, "MACD_SLOW", 26) or 26)
    macd_sig = int(getattr(cfg, "MACD_SIGNAL", 9) or 9)

    r = rsi(bars, rsi_n)
    sr = stoch_rsi(bars, rsi_n)
    _mid, _up, _lo, pct_b = bollinger(bars, bb_n, float(getattr(cfg, "BB_STD", 2.0) or 2.0))
    wr = williams_r(bars, rsi_n)
    cc = cci(bars, bb_n)
    vwap_sig = float(getattr(snap, "vwap_distance_atr", 0.0) or 0.0)
    m_line, m_sig, m_hist, m_delta, m_cross = macd(
        bars, fast=macd_fast, slow=macd_slow, signal=macd_sig
    )

    # Rebuild hist series for divergence (lightweight)
    closes = [float(b.get("close") or 0) for b in bars]
    from .indicators import _ema_series

    div = ""
    if len(closes) >= macd_slow + macd_sig + 5:
        ef = _ema_series(closes, macd_fast)
        es = _ema_series(closes, macd_slow)
        ml = [a - b for a, b in zip(ef, es)]
        sg = _ema_series(ml, macd_sig)
        hs = [a - b for a, b in zip(ml, sg)]
        div = _macd_divergence(closes, hs)

    # ——— EXTENSION SCORE (0–100) per side ———
    rsi_ob = _clamp((r - 50.0) / 30.0, 0.0, 1.0)
    rsi_os = _clamp((50.0 - r) / 30.0, 0.0, 1.0)
    if r >= 80.0:
        rsi_ob = min(1.0, rsi_ob + 0.25)
    if r <= 20.0:
        rsi_os = min(1.0, rsi_os + 0.25)

    stoch_ob = _clamp((sr - 50.0) / 40.0, 0.0, 1.0)
    stoch_os = _clamp((50.0 - sr) / 40.0, 0.0, 1.0)
    if sr >= 80.0:
        stoch_ob = max(stoch_ob, 0.85)
    if sr <= 20.0:
        stoch_os = max(stoch_os, 0.85)

    bb_ob = _clamp((pct_b - 0.5) / 0.75, 0.0, 1.0)
    bb_os = _clamp((0.5 - pct_b) / 0.75, 0.0, 1.0)

    # VWAP σ bands: 1 / 2 / 3
    vwap_ob = _clamp(vwap_sig / 3.0, 0.0, 1.0)
    vwap_os = _clamp((-vwap_sig) / 3.0, 0.0, 1.0)

    wr_ob = _clamp((wr + 20.0) / 20.0, 0.0, 1.0) if wr >= -20.0 else 0.0
    wr_os = _clamp((-80.0 - wr) / 20.0, 0.0, 1.0) if wr <= -80.0 else 0.0

    cci_ob = _clamp((cc - 100.0) / 100.0, 0.0, 1.0)
    cci_os = _clamp((-100.0 - cc) / 100.0, 0.0, 1.0)

    ext_long = 100.0 * (
        0.28 * vwap_ob
        + 0.22 * rsi_ob
        + 0.18 * bb_ob
        + 0.14 * stoch_ob
        + 0.10 * wr_ob
        + 0.08 * cci_ob
    )
    ext_short = 100.0 * (
        0.28 * vwap_os
        + 0.22 * rsi_os
        + 0.18 * bb_os
        + 0.14 * stoch_os
        + 0.10 * wr_os
        + 0.08 * cci_os
    )

    # ——— MOMENTUM HEALTH (−100…+100) — MACD-led ———
    atr = max(float(getattr(snap, "atr", 0) or 0), float(getattr(cfg, "TICK_SIZE", 0.25) or 0.25))
    # Normalize hist / delta vs ATR so MNQ scale is stable
    hist_n = _clamp(m_hist / max(atr * 0.15, 0.25), -1.5, 1.5) / 1.5
    delta_n = _clamp(m_delta / max(atr * 0.08, 0.15), -1.5, 1.5) / 1.5

    mom = 0.0
    # 1) MACD vs signal
    if m_line > m_sig:
        mom += 32.0
    elif m_line < m_sig:
        mom -= 32.0
    # 2) Histogram level + acceleration
    mom += 28.0 * hist_n
    mom += 30.0 * delta_n
    # 3) Fresh crossover
    if m_cross == "bull":
        mom += 18.0
    elif m_cross == "bear":
        mom -= 18.0
    # 4) Divergence
    if div == "bull":
        mom += 22.0
    elif div == "bear":
        mom -= 22.0
    # Blend a touch of tape velocity
    vel = float(getattr(snap, "velocity", 0) or 0)
    mom += _clamp(vel / max(atr * 0.2, 0.5), -1.0, 1.0) * 12.0
    mom = _clamp_mom(mom)

    # ——— CHASE RISK: stretched + momentum dying in that direction ———
    # Longing an exhausted tip: high upside extension + bullish momentum dying
    dying_up = _clamp((25.0 - mom) / 80.0, 0.0, 1.0)  # mom low → dying upside
    dying_down = _clamp((mom + 25.0) / 80.0, 0.0, 1.0)  # mom high → dying downside move
    # Accelerating monster: high extension but mom still strong → LOW chase for fade
    accel_up = _clamp((mom - 20.0) / 60.0, 0.0, 1.0)
    accel_down = _clamp((-mom - 20.0) / 60.0, 0.0, 1.0)

    # long_chase = risk of BUYING into tip (OB + dying) OR catching falling knife (OS + still crashing)
    long_chase = _clamp(
        0.55 * ext_long * dying_up  # tip buy
        + 0.45 * ext_short * accel_down  # falling knife
    )
    short_chase = _clamp(
        0.55 * ext_short * dying_down  # tip sell washout
        + 0.45 * ext_long * accel_up  # shorting monster rip
    )

    return ExhaustionReading(
        rsi=round(r, 2),
        stoch_rsi=round(sr, 2),
        bb_pct_b=round(pct_b, 3),
        vwap_sigma=round(vwap_sig, 3),
        williams_r=round(wr, 2),
        cci=round(cc, 2),
        extension_long=_clamp(ext_long),
        extension_short=_clamp(ext_short),
        momentum_health=round(mom, 1),
        macd=round(m_line, 4),
        macd_signal=round(m_sig, 4),
        macd_hist=round(m_hist, 4),
        macd_hist_delta=round(m_delta, 4),
        macd_cross=m_cross,
        macd_div=div,
        long_chase=round(long_chase, 1),
        short_chase=round(short_chase, 1),
    )


def rsi_ob_level(cfg: Mark2Config) -> float:
    return float(getattr(cfg, "RSI_OB_LEVEL", 75.0) or 75.0)


def rsi_os_level(cfg: Mark2Config) -> float:
    return float(getattr(cfg, "RSI_OS_LEVEL", 25.0) or 25.0)


def exhaustion_blocks(
    side: Side,
    snap: MarketSnapshot,
    cfg: Mark2Config,
) -> tuple[bool, str, ExhaustionReading]:
    """RSI zone gate + Extension Engine chase protection.

    Zone: OS → LONG only, OB → SHORT only (flash required).
    Chase: block fades into monster trends (high extension + accelerating MACD)
    and block knife-catch / tip-chase when momentum is dying the wrong way.
    """
    reading = read_exhaustion(snap, cfg)
    if not bool(getattr(cfg, "ENABLE_EXHAUSTION_FILTER", True)):
        return False, "", reading

    ob = rsi_ob_level(cfg)
    os_lvl = rsi_os_level(cfg)
    r = float(reading.rsi)
    mom = float(reading.momentum_health)
    ext_up = float(reading.extension_long)
    ext_dn = float(reading.extension_short)
    chase_lim = float(getattr(cfg, "EXHAUSTION_BLOCK_SCORE", 72.0) or 72.0)
    monster_ext = float(getattr(cfg, "MONSTER_EXTENSION", 70.0) or 70.0)
    monster_mom = float(getattr(cfg, "MONSTER_MOMENTUM", 35.0) or 35.0)

    if side == Side.LONG:
        if r > os_lvl:
            return (
                True,
                f"RSI {r:.0f} not oversold — need ≤{os_lvl:.0f} to LONG "
                f"(flash OS before buy)",
                reading,
            )
        # Falling knife: still crashing
        if ext_dn >= monster_ext and mom < -monster_mom:
            return (
                True,
                f"falling knife — ext↓ {ext_dn:.0f} · mom {mom:+.0f} "
                f"(MACD still accelerating down)",
                reading,
            )
        if reading.long_chase >= chase_lim:
            return (
                True,
                f"chase LONG {reading.long_chase:.0f} — ext↑{ext_up:.0f}/↓{ext_dn:.0f} "
                f"mom {mom:+.0f} histΔ {reading.macd_hist_delta:+.3f}",
                reading,
            )
        tag = f"RSI {r:.0f} OS · ext {ext_dn:.0f} · mom {mom:+.0f}"
        if reading.macd_cross:
            tag += f" · MACD {reading.macd_cross}"
        return False, f"{tag} · LONG ok", reading

    if side == Side.SHORT:
        if r < ob:
            return (
                True,
                f"RSI {r:.0f} not overbought — need ≥{ob:.0f} to SHORT "
                f"(flash OB before sell)",
                reading,
            )
        # Monster trend: still ripping — do NOT auto-short OB alone
        if ext_up >= monster_ext and mom > monster_mom:
            return (
                True,
                f"monster trend — ext↑ {ext_up:.0f} · mom {mom:+.0f} "
                f"(MACD hist still expanding — no fade)",
                reading,
            )
        if reading.short_chase >= chase_lim:
            return (
                True,
                f"chase SHORT {reading.short_chase:.0f} — ext↑{ext_up:.0f}/↓{ext_dn:.0f} "
                f"mom {mom:+.0f} histΔ {reading.macd_hist_delta:+.3f}",
                reading,
            )
        tag = f"RSI {r:.0f} OB · ext {ext_up:.0f} · mom {mom:+.0f}"
        if reading.macd_div == "bear":
            tag += " · MACD bear-div"
        if reading.macd_cross:
            tag += f" · MACD {reading.macd_cross}"
        return False, f"{tag} · SHORT ok", reading

    return True, "RSI zone — no side", reading


def blend_extension_with_exhaustion(
    impulse_risk: float,
    chase_score: float,
    *,
    weight: float = 0.55,
) -> float:
    """Raise displayed extension risk when exhaustion chase is hot."""
    return _clamp(
        max(
            float(impulse_risk),
            float(chase_score) * float(weight) + float(impulse_risk) * (1.0 - weight),
        )
    )
