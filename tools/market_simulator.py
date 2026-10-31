#!/usr/bin/env python3
"""Generate synthetic OHLCV bars for Smart Trader pipeline testing.

This tool writes CSV and JSONL files only. It does not connect to MT5,
SignalFlow, a broker, or any order-execution interface.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREFIX = ROOT / "data" / "raw" / "synthetic_xauusd_m15"
FIELDS = (
    "timestamp",
    "symbol",
    "timeframe",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)


class MarketSimulator:
    """Simple reproducible random-walk market-data generator."""

    def __init__(
        self,
        *,
        symbol: str,
        timeframe_minutes: int,
        start_price: float,
        volatility: float,
        trend: float,
        spread: float,
        seed: int | None,
    ) -> None:
        if timeframe_minutes <= 0:
            raise ValueError("timeframe_minutes must be positive")
        if start_price <= 0:
            raise ValueError("start_price must be positive")
        if volatility < 0:
            raise ValueError("volatility cannot be negative")
        if spread < 0:
            raise ValueError("spread cannot be negative")

        self.symbol = symbol.upper()
        self.timeframe_minutes = timeframe_minutes
        self.price = start_price
        self.volatility = volatility
        self.trend = trend
        self.spread = spread
        self.rng = random.Random(seed)

    def generate_bar(self, timestamp: datetime) -> dict:
        timestamp = timestamp.astimezone(timezone.utc)
        open_price = self.price
        close_price = max(
            0.01,
            open_price + self.rng.gauss(self.trend, self.volatility),
        )
        wick_scale = self.volatility * 0.35
        high = max(open_price, close_price) + abs(self.rng.gauss(0, wick_scale))
        low = min(open_price, close_price) - abs(self.rng.gauss(0, wick_scale))
        self.price = close_price

        return {
            "timestamp": timestamp.isoformat(timespec="seconds"),
            "symbol": self.symbol,
            "timeframe": f"M{self.timeframe_minutes}",
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(max(0.01, low), 2),
            "close": round(close_price, 2),
            "tick_volume": self.rng.randint(80, 1200),
            "spread": round(self.spread, 2),
            "real_volume": 0,
        }


def aligned_utc_now(timeframe_minutes: int) -> datetime:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    minute = (now.minute // timeframe_minutes) * timeframe_minutes
    return now.replace(minute=minute)


def write_bar(
    bar: dict,
    csv_writer: csv.DictWriter,
    csv_file: TextIO,
    jsonl_file: TextIO,
) -> None:
    csv_writer.writerow(bar)
    csv_file.flush()
    jsonl_file.write(json.dumps(bar, separators=(",", ":")) + "\n")
    jsonl_file.flush()


def simulate(args: argparse.Namespace) -> int:
    prefix = Path(args.output_prefix).expanduser()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    csv_path = prefix.with_suffix(".csv")
    jsonl_path = prefix.with_suffix(".jsonl")

    simulator = MarketSimulator(
        symbol=args.symbol,
        timeframe_minutes=args.timeframe,
        start_price=args.price,
        volatility=args.volatility,
        trend=args.trend,
        spread=args.spread,
        seed=args.seed,
    )

    interval = timedelta(minutes=args.timeframe)
    now = aligned_utc_now(args.timeframe)
    if args.start_time:
        start = datetime.fromisoformat(args.start_time.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        start = start.astimezone(timezone.utc)
    elif args.count > 0:
        start = now - interval * (args.count - 1)
    else:
        start = now

    mode = "a" if args.append else "w"
    csv_exists = csv_path.exists() and csv_path.stat().st_size > 0
    write_header = not (args.append and csv_exists)

    print(f"Symbol:       {args.symbol.upper()}")
    print(f"Timeframe:    M{args.timeframe}")
    print(f"CSV output:   {csv_path}")
    print(f"JSONL output: {jsonl_path}")
    print("File generation only; no MT5 connection or order execution.")

    generated = 0
    try:
        with csv_path.open(mode, newline="", encoding="utf-8") as csv_file, \
             jsonl_path.open(mode, encoding="utf-8") as jsonl_file:
            writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
            if write_header:
                writer.writeheader()

            while args.count == 0 or generated < args.count:
                timestamp = start + interval * generated
                bar = simulator.generate_bar(timestamp)
                write_bar(bar, writer, csv_file, jsonl_file)
                generated += 1

                print(
                    f"{bar['timestamp']} {bar['symbol']} "
                    f"O={bar['open']:.2f} H={bar['high']:.2f} "
                    f"L={bar['low']:.2f} C={bar['close']:.2f}"
                )

                if args.count == 0 or generated < args.count:
                    time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user.")

    print(f"Generated {generated} bars.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate synthetic OHLCV market data for Smart Trader."
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", type=int, default=15, help="Bar size in minutes")
    parser.add_argument("--price", type=float, default=4000.0, help="Initial price")
    parser.add_argument("--volatility", type=float, default=2.5, help="Price-change std dev")
    parser.add_argument("--trend", type=float, default=0.0, help="Mean price change per bar")
    parser.add_argument("--spread", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42, help="Random seed; use 'none' for random")
    parser.add_argument("--count", type=int, default=100, help="Bars to generate; 0 runs continuously")
    parser.add_argument("--interval", type=float, default=0.0, help="Delay between bars in seconds")
    parser.add_argument(
        "--start-time",
        help="First bar timestamp in ISO-8601 (default: calculated from current UTC time)",
    )
    parser.add_argument(
        "--output-prefix",
        default=str(DEFAULT_PREFIX),
        help="Output path without extension; creates .csv and .jsonl",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing files instead of replacing them",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.timeframe <= 0:
        parser.error("--timeframe must be greater than zero")
    if args.count < 0:
        parser.error("--count cannot be negative")
    if args.interval < 0:
        parser.error("--interval cannot be negative")
    if args.price <= 0 or args.volatility < 0 or args.spread < 0:
        parser.error("--price must be positive; volatility and spread cannot be negative")

    if args.seed == "none":
        args.seed = None
    else:
        try:
            args.seed = int(args.seed)
        except (TypeError, ValueError):
            parser.error("--seed must be an integer or 'none'")

    try:
        return simulate(args)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
