"""Research-only EMA crossover detector for closed OHLC candles.

Expected CSV: DATA_DIR/raw/{SYMBOL}_{TIMEFRAME}.csv
Required columns (case-insensitive): open, high, low, close.
Optional timestamp column: time, timestamp, or datetime. Rows must be oldest first.
This module never places orders.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    result: list[float] = []
    for value in values:
        result.append(value if not result else alpha * value + (1.0 - alpha) * result[-1])
    return result


def _load_bars(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            return []
        names = {name.strip().lower(): name for name in reader.fieldnames if name}
        required = {"open", "high", "low", "close"}
        if not required.issubset(names):
            return []
        time_key = next((names[k] for k in ("time", "timestamp", "datetime") if k in names), None)
        bars = []
        for row_index, row in enumerate(reader):
            try:
                bar = {key: float(row[names[key]]) for key in required}
                if not all(math.isfinite(v) and v > 0 for v in bar.values()):
                    continue
                if bar["high"] < max(bar["open"], bar["close"], bar["low"]):
                    continue
                if bar["low"] > min(bar["open"], bar["close"], bar["high"]):
                    continue
                bar["time"] = (row.get(time_key, "").strip() if time_key else "") or f"row-{row_index}"
                bars.append(bar)
            except (TypeError, ValueError):
                continue
    return bars


def detect_from_bars(bars: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    """Return a candidate only when a 9/21 EMA crossover is present on latest bars."""
    if len(bars) < 30:
        return []

    closes = [float(bar["close"]) for bar in bars]
    if any(not math.isfinite(price) or price <= 0 for price in closes):
        return []
    fast, slow = _ema(closes, 9), _ema(closes, 21)

    # ATR(14), using the latest 14 true ranges.
    true_ranges = []
    for i in range(1, len(bars)):
        high, low, previous_close = float(bars[i]["high"]), float(bars[i]["low"]), closes[i - 1]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    if len(true_ranges) < 14:
        return []
    atr = sum(true_ranges[-14:]) / 14.0
    if not math.isfinite(atr) or atr <= 0:
        return []

    previous_gap = fast[-2] - slow[-2]
    current_gap = fast[-1] - slow[-1]
    side = None
    if previous_gap <= 0 < current_gap:
        side = "buy"
    elif previous_gap >= 0 > current_gap:
        side = "sell"
    if side is None:
        return []

    entry = closes[-1]
    stop_distance = 1.5 * atr
    reward_risk = 1.8
    if side == "buy":
        sl, tp = entry - stop_distance, entry + stop_distance * reward_risk
    else:
        sl, tp = entry + stop_distance, entry - stop_distance * reward_risk
    if min(entry, sl, tp) <= 0:
        return []

    # Confidence is a transparent heuristic, not a calibrated probability.
    normalized_gap = abs(current_gap) / atr
    confidence = min(0.80, 0.55 + 0.25 * normalized_gap)
    latest = bars[-1]
    return [{
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "confidence": confidence,
        "strategy": "ema9_21_atr14_research",
        "bar_time": str(latest.get("time", "")),
        "features": {
            "ema_fast": fast[-1],
            "ema_slow": slow[-1],
            "atr14": atr,
            "reward_risk": reward_risk,
            "confidence_type": "heuristic_not_probability",
        },
    }]


def detect_from_csv(data_dir: Path, symbol: str, timeframe: str) -> list[dict[str, Any]]:
    """Read closed-candle CSV data and detect a research candidate."""
    path = Path(data_dir) / "raw" / f"{symbol}_{timeframe}.csv"
    return detect_from_bars(_load_bars(path), symbol)
