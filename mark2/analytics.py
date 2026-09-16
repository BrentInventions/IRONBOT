"""Recon Sniper vs Mark 1 comparison metrics. Honesty over win-rate theater."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EngineStats:
    engine: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_points: float = 0.0
    fees: float = 0.0
    net_pnl: float = 0.0
    largest_winner: float = 0.0
    largest_loser: float = 0.0
    mfe_sum: float = 0.0
    mae_sum: float = 0.0
    mfe_capture_sum: float = 0.0
    hold_sec_sum: float = 0.0
    long_trades: int = 0
    short_trades: int = 0
    long_pnl: float = 0.0
    short_pnl: float = 0.0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    equity: float = 0.0
    by_hour: dict[str, float] = field(default_factory=dict)
    by_event: dict[str, float] = field(default_factory=dict)
    by_confidence: dict[str, list] = field(default_factory=dict)
    by_opportunity: dict[str, list] = field(default_factory=dict)

    def record(
        self,
        *,
        side: str,
        pnl: float,
        points: float,
        fees: float,
        mfe: float,
        mae: float,
        hold_sec: float,
        scratch: bool,
        hour: int,
        event_type: str,
        confidence: float,
        opportunity: float,
    ) -> None:
        self.trades += 1
        self.fees += fees
        self.net_pnl += pnl
        self.net_points += points
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        dd = self.peak_equity - self.equity
        self.max_drawdown = max(self.max_drawdown, dd)
        self.mfe_sum += mfe
        self.mae_sum += mae
        if mfe > 0:
            self.mfe_capture_sum += (points / mfe) * 100.0
        self.hold_sec_sum += hold_sec
        if scratch:
            self.scratches += 1
        if pnl > 0:
            self.wins += 1
            self.gross_profit += pnl
            self.largest_winner = max(self.largest_winner, pnl)
        elif pnl < 0:
            self.losses += 1
            self.gross_loss += abs(pnl)
            self.largest_loser = min(self.largest_loser, pnl)
        if side == "LONG":
            self.long_trades += 1
            self.long_pnl += pnl
        else:
            self.short_trades += 1
            self.short_pnl += pnl
        hk = str(hour)
        self.by_hour[hk] = self.by_hour.get(hk, 0.0) + pnl
        self.by_event[event_type] = self.by_event.get(event_type, 0.0) + pnl
        self.by_confidence.setdefault(_bucket(confidence), []).append(pnl)
        self.by_opportunity.setdefault(_bucket(opportunity), []).append(pnl)

    def clear_session(self) -> None:
        """Zero live session counters. Persisted calendar archives are not touched."""
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.scratches = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.net_points = 0.0
        self.fees = 0.0
        self.net_pnl = 0.0
        self.largest_winner = 0.0
        self.largest_loser = 0.0
        self.mfe_sum = 0.0
        self.mae_sum = 0.0
        self.mfe_capture_sum = 0.0
        self.hold_sec_sum = 0.0
        self.long_trades = 0
        self.short_trades = 0
        self.long_pnl = 0.0
        self.short_pnl = 0.0
        self.peak_equity = 0.0
        self.max_drawdown = 0.0
        self.equity = 0.0
        self.by_hour.clear()
        self.by_event.clear()
        self.by_confidence.clear()
        self.by_opportunity.clear()

    def summary(self) -> dict[str, Any]:
        n = max(1, self.trades)
        wr = self.wins / n if self.trades else 0.0
        avg_w = self.gross_profit / self.wins if self.wins else 0.0
        avg_l = self.gross_loss / self.losses if self.losses else 0.0
        pf = (self.gross_profit / self.gross_loss) if self.gross_loss > 0 else (
            float("inf") if self.gross_profit > 0 else 0.0
        )
        mfe_cap = self.mfe_capture_sum / n
        return {
            "engine": self.engine,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "scratches": self.scratches,
            "win_rate": wr,
            "average_winner": avg_w,
            "average_loser": avg_l,
            "largest_winner": self.largest_winner,
            "largest_loser": self.largest_loser,
            "net_points": self.net_points,
            "gross_profit": self.gross_profit,
            "gross_loss": self.gross_loss,
            "profit_factor": pf,
            "expectancy_per_trade": self.net_pnl / n if self.trades else 0.0,
            "max_drawdown": self.max_drawdown,
            "mfe_sum": self.mfe_sum,
            "mae_sum": self.mae_sum,
            "mfe_capture_pct": mfe_cap,
            "average_holding_time_sec": self.hold_sec_sum / n if self.trades else 0.0,
            "fees": self.fees,
            "net_pnl_after_fees": self.net_pnl,
            "long_trades": self.long_trades,
            "short_trades": self.short_trades,
            "long_pnl": self.long_pnl,
            "short_pnl": self.short_pnl,
            "by_hour": self.by_hour,
            "by_event": self.by_event,
            "primary_eval": {
                "net_expectancy_after_costs": self.net_pnl / n if self.trades else 0.0,
                "profit_factor": pf,
                "drawdown": self.max_drawdown,
                "mfe_capture_efficiency": mfe_cap,
            },
        }


def _bucket(x: float) -> str:
    if x < 40:
        return "0-40"
    if x < 55:
        return "40-55"
    if x < 70:
        return "55-70"
    if x < 85:
        return "70-85"
    return "85-100"
