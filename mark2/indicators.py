"""Recon Sniper indicators — self-contained. No Impulse / TradeChampion imports."""

from __future__ import annotations

from typing import Sequence


def ema(values: Sequence[float], period: int) -> list[float]:
    """NinjaTrader EMA: SMA seed over `period`, then k = 2/(period+1)."""
    if not values:
        return []
    n = max(1, int(period))
    xs = [float(v) for v in values]
    alpha = 2.0 / (n + 1)
    if len(xs) < n:
        out = [xs[0]]
        for v in xs[1:]:
            out.append(alpha * v + (1.0 - alpha) * out[-1])
        return out
    out: list[float] = []
    running = 0.0
    for i, v in enumerate(xs):
        running += v
        if i + 1 < n:
            out.append(running / (i + 1))
            continue
        if i + 1 == n:
            out.append(running / n)
            continue
        out.append(alpha * v + (1.0 - alpha) * out[-1])
    return out


def atr(bars: Sequence[dict], period: int = 14) -> list[float]:
    if not bars:
        return []
    trs: list[float] = []
    for i, bar in enumerate(bars):
        high = float(bar["high"])
        low = float(bar["low"])
        if i == 0:
            trs.append(high - low)
        else:
            prev_close = float(bars[i - 1]["close"])
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    n = max(1, int(period))
    out = [trs[0]]
    for i in range(1, len(trs)):
        if i < n:
            out.append(sum(trs[: i + 1]) / (i + 1))
        else:
            out.append((out[-1] * (n - 1) + trs[i]) / n)
    return out


def atr_regime(
    atrs: Sequence[float],
    *,
    lookback: int = 14,
    expand_ratio: float = 1.15,
    shrink_ratio: float = 0.85,
) -> str:
    n = max(2, int(lookback))
    if len(atrs) < 2:
        return "stable"
    if len(atrs) < n + 2:
        recent = float(atrs[-1])
        prior = float(atrs[max(0, len(atrs) - 1 - n)])
    else:
        recent = sum(float(x) for x in atrs[-n:]) / n
        prior = sum(float(x) for x in atrs[-2 * n : -n]) / n
    if prior <= 1e-9:
        return "stable"
    ratio = recent / prior
    if ratio >= expand_ratio:
        return "expanding"
    if ratio <= shrink_ratio:
        return "shrinking"
    return "stable"


def vwap(bars: Sequence[dict], lookback: int = 80) -> float:
    window = list(bars[-lookback:]) if bars else []
    if not window:
        return 0.0
    num = den = 0.0
    for b in window:
        h = float(b["high"])
        lo = float(b["low"])
        c = float(b["close"])
        vol = float(b.get("volume") or b.get("vol") or 1.0)
        if vol <= 0:
            vol = 1.0
        num += ((h + lo + c) / 3.0) * vol
        den += vol
    return num / den if den > 0 else float(window[-1]["close"])


def _closes(bars: Sequence[dict]) -> list[float]:
    return [float(b.get("close") or 0) for b in bars]


def _rsi_from_closes(closes: Sequence[float], period: int = 14) -> float:
    n = max(2, int(period))
    if len(closes) < n + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        d = float(closes[i]) - float(closes[i - 1])
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_gain = gains / n
    avg_loss = losses / n
    if avg_loss <= 1e-12:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return max(0.0, min(100.0, 100.0 - (100.0 / (1.0 + rs))))


def rsi(bars: Sequence[dict], period: int = 14) -> float:
    """RSI(14) on closes. Returns 50 when insufficient data."""
    return _rsi_from_closes(_closes(bars), period)


def stoch_rsi(bars: Sequence[dict], period: int = 14) -> float:
    """Stochastic RSI %K (0–100). Faster stretch detector than raw RSI."""
    closes = _closes(bars)
    n = max(2, int(period))
    if len(closes) < n * 2 + 1:
        return 50.0
    rsis: list[float] = []
    for end in range(n + 1, len(closes) + 1):
        rsis.append(_rsi_from_closes(closes[:end], n))
    if len(rsis) < n:
        return 50.0
    window = rsis[-n:]
    lo, hi = min(window), max(window)
    if hi - lo <= 1e-12:
        return 50.0
    return max(0.0, min(100.0, 100.0 * (window[-1] - lo) / (hi - lo)))


def bollinger(
    bars: Sequence[dict], period: int = 20, num_std: float = 2.0
) -> tuple[float, float, float, float]:
    """Return (mid, upper, lower, pct_b). pct_b: 0 at lower, 1 at upper, >1 above."""
    closes = _closes(bars)
    n = max(2, int(period))
    if len(closes) < n:
        px = closes[-1] if closes else 0.0
        return px, px, px, 0.5
    window = closes[-n:]
    mid = sum(window) / n
    var = sum((x - mid) ** 2 for x in window) / n
    std = var ** 0.5
    upper = mid + float(num_std) * std
    lower = mid - float(num_std) * std
    px = window[-1]
    width = upper - lower
    if width <= 1e-12:
        pct_b = 0.5
    else:
        pct_b = (px - lower) / width
    return mid, upper, lower, pct_b


def williams_r(bars: Sequence[dict], period: int = 14) -> float:
    """Williams %R in [-100, 0]. Above -20 overbought, below -80 oversold."""
    n = max(2, int(period))
    if len(bars) < n:
        return -50.0
    window = list(bars[-n:])
    hh = max(float(b.get("high") or 0) for b in window)
    ll = min(float(b.get("low") or 0) for b in window)
    c = float(window[-1].get("close") or 0)
    if hh - ll <= 1e-12:
        return -50.0
    return max(-100.0, min(0.0, -100.0 * (hh - c) / (hh - ll)))


def cci(bars: Sequence[dict], period: int = 20) -> float:
    """Commodity Channel Index. ±100 stretch, ±200 extreme."""
    n = max(2, int(period))
    if len(bars) < n:
        return 0.0
    tps = [
        (float(b.get("high") or 0) + float(b.get("low") or 0) + float(b.get("close") or 0))
        / 3.0
        for b in bars[-n:]
    ]
    sma = sum(tps) / n
    mad = sum(abs(x - sma) for x in tps) / n
    if mad <= 1e-12:
        return 0.0
    return (tps[-1] - sma) / (0.015 * mad)


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    n = max(1, int(period))
    alpha = 2.0 / (n + 1)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * float(v) + (1.0 - alpha) * out[-1])
    return out


def macd(
    bars: Sequence[dict],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float, float, str]:
    """Return (macd, signal, hist, hist_delta, cross).

    cross: \"bull\", \"bear\", or \"\".
    hist_delta: change in histogram vs prior bar (acceleration).
    """
    closes = _closes(bars)
    need = max(int(slow), int(fast)) + int(signal) + 2
    if len(closes) < need:
        return 0.0, 0.0, 0.0, 0.0, ""
    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    sig_line = _ema_series(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, sig_line)]
    m0, s0, h0 = macd_line[-1], sig_line[-1], hist[-1]
    h1 = hist[-2] if len(hist) > 1 else h0
    delta = h0 - h1
    cross = ""
    if len(macd_line) >= 2 and len(sig_line) >= 2:
        prev_m, prev_s = macd_line[-2], sig_line[-2]
        if prev_m <= prev_s and m0 > s0:
            cross = "bull"
        elif prev_m >= prev_s and m0 < s0:
            cross = "bear"
    return float(m0), float(s0), float(h0), float(delta), cross


def swing_pivots(bars: Sequence[dict], *, strength: int = 1) -> tuple[list[float], list[float]]:
    s = max(1, int(strength))
    highs: list[float] = []
    lows: list[float] = []
    if len(bars) < s * 2 + 1:
        return highs, lows
    for i in range(s, len(bars) - s):
        h = float(bars[i]["high"])
        lo = float(bars[i]["low"])
        if all(
            h >= float(bars[i - j]["high"]) and h >= float(bars[i + j]["high"])
            for j in range(1, s + 1)
        ):
            highs.append(h)
        if all(
            lo <= float(bars[i - j]["low"]) and lo <= float(bars[i + j]["low"])
            for j in range(1, s + 1)
        ):
            lows.append(lo)
    return highs, lows


def volume_ratio(bars: Sequence[dict], *, lookback: int = 20) -> tuple[float, float, float]:
    if not bars:
        return 0.0, 0.0, 0.0
    lookback = max(2, int(lookback))
    vols = [float(b.get("volume") or b.get("vol") or 0) for b in bars[-(lookback + 1) :]]
    ref = vols[-1]
    prior = vols[:-1]
    avg = (sum(prior) / len(prior)) if prior else ref
    if avg <= 0:
        return ref, 0.0, 1.0 if ref > 0 else 0.0
    return ref, avg, ref / avg


def aggregate_5m(bars_1m: Sequence[dict]) -> list[dict]:
    """Completed 5m bars from complete groups of five 1m bars. No partial candle."""
    if len(bars_1m) < 5:
        return []
    n = (len(bars_1m) // 5) * 5
    out: list[dict] = []
    for i in range(0, n, 5):
        chunk = list(bars_1m[i : i + 5])
        out.append(
            {
                "time": chunk[-1].get("time"),
                "open": float(chunk[0]["open"]),
                "high": max(float(x["high"]) for x in chunk),
                "low": min(float(x["low"]) for x in chunk),
                "close": float(chunk[-1]["close"]),
                "volume": sum(float(x.get("volume") or x.get("vol") or 0) for x in chunk),
            }
        )
    return out


def directional_efficiency(bars: Sequence[dict], lookback: int = 8) -> float:
    if len(bars) < lookback + 1:
        return 0.0
    window = list(bars[-(lookback + 1) :])
    net = abs(float(window[-1]["close"]) - float(window[0]["close"]))
    path = sum(
        abs(float(window[i]["close"]) - float(window[i - 1]["close"]))
        for i in range(1, len(window))
    )
    return net / max(path, 1e-9)
