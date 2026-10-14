#!/usr/bin/env python3
"""
Close the learning loop.

Reads every runtime/*/decisions.jsonl and joins with data/trade_outcomes.jsonl
(or per-strategy trade_outcomes.jsonl if present), computes per-signal PnL,
and writes a training dataset to artifacts/learning_loop/.

Usage:
    python scripts/close_learning_loop.py
    python scripts/close_learning_loop.py --strategy xauusd --min-trades 30
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("learning_loop")

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
GLOBAL_OUTCOMES = ROOT / "data" / "trade_outcomes.jsonl"
OUT_DIR = ROOT / "artifacts" / "learning_loop"


@dataclass
class JoinedRecord:
    strategy: str
    signal_id: str
    symbol: str
    side: str
    ts_open: str
    ts_close: str | None
    entry: float | None
    exit: float | None
    sl: float | None
    tp: float | None
    confidence: float | None
    pnl: float | None
    pnl_r: float | None
    outcome: str  # win | loss | breakeven | open | unmatched
    features: dict[str, Any]


def _iter_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("Skipping malformed line in %s", path)


def _load_outcomes(strategy_dir: Path) -> dict[str, dict]:
    """Prefer per-strategy outcomes, fall back to global."""
    candidates = [
        strategy_dir / "trade_outcomes.jsonl",
        strategy_dir / "data" / "trade_outcomes.jsonl",
        GLOBAL_OUTCOMES,
    ]
    merged: dict[str, dict] = {}
    for path in candidates:
        for rec in _iter_jsonl(path):
            sid = rec.get("signal_id") or rec.get("id")
            if sid:
                merged[sid] = rec
    return merged


def _pnl_r(entry: float, sl: float, exit_price: float, side: str) -> float | None:
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    direction = 1 if side.lower() in ("buy", "long") else -1
    return direction * (exit_price - entry) / risk


def _classify(pnl: float | None, eps: float = 1e-9) -> str:
    if pnl is None:
        return "unmatched"
    if pnl > eps:
        return "win"
    if pnl < -eps:
        return "loss"
    return "breakeven"


def join_strategy(strategy_dir: Path) -> list[JoinedRecord]:
    strategy = strategy_dir.name
    decisions_path = strategy_dir / "decisions.jsonl"
    if not decisions_path.exists():
        return []

    outcomes = _load_outcomes(strategy_dir)
    rows: list[JoinedRecord] = []

    for d in _iter_jsonl(decisions_path):
        sid = d.get("signal_id") or d.get("id") or d.get("decision_id")
        if not sid:
            continue
        o = outcomes.get(sid, {})

        entry = d.get("entry") or d.get("price")
        sl = d.get("sl") or d.get("stop_loss")
        tp = d.get("tp") or d.get("take_profit")
        side = d.get("side") or d.get("action") or "unknown"

        exit_price = o.get("exit_price") or o.get("close_price")
        pnl = o.get("pnl")
        pnl_r = None
        if entry and sl and exit_price:
            pnl_r = _pnl_r(float(entry), float(sl), float(exit_price), side)

        rows.append(
            JoinedRecord(
                strategy=strategy,
                signal_id=str(sid),
                symbol=d.get("symbol", ""),
                side=side,
                ts_open=str(d.get("ts") or d.get("timestamp") or ""),
                ts_close=str(o.get("ts_close") or o.get("closed_at") or ""),
                entry=entry,
                exit=exit_price,
                sl=sl,
                tp=tp,
                confidence=d.get("confidence"),
                pnl=pnl,
                pnl_r=pnl_r,
                outcome=o.get("outcome") or _classify(pnl if pnl is not None else None),
                features=d.get("features") or {},
            )
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", help="Only process this runtime/*/ folder")
    ap.add_argument("--min-trades", type=int, default=0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: list[JoinedRecord] = []
    for strat_dir in sorted(p for p in RUNTIME.iterdir() if p.is_dir()):
        if args.strategy and strat_dir.name != args.strategy:
            continue
        rows = join_strategy(strat_dir)
        if not rows:
            continue
        if len(rows) < args.min_trades:
            log.info("Skip %s (%d rows < min %d)", strat_dir.name, len(rows), args.min_trades)
            continue
        all_rows.extend(rows)
        log.info("%s: %d joined records", strat_dir.name, len(rows))

    if not all_rows:
        log.warning("No joined records produced.")
        return

    df = pd.DataFrame([asdict(r) for r in all_rows])
    # flatten features
    feat_df = pd.json_normalize(df["features"]).add_prefix("f_")
    df = pd.concat([df.drop(columns=["features"]), feat_df], axis=1)

    out_parquet = OUT_DIR / "joined_decisions.parquet"
    out_csv = OUT_DIR / "joined_decisions.csv"
    df.to_parquet(out_parquet, index=False)
    df.to_csv(out_csv, index=False)

    # Summary per strategy
    summary = (
        df.groupby("strategy")
        .agg(
            n=("signal_id", "count"),
            wins=("outcome", lambda s: (s == "win").sum()),
            losses=("outcome", lambda s: (s == "loss").sum()),
            unmatched=("outcome", lambda s: (s == "unmatched").sum()),
            avg_pnl_r=("pnl_r", "mean"),
            total_pnl=("pnl", "sum"),
        )
        .reset_index()
    )
    summary["win_rate"] = summary["wins"] / (summary["wins"] + summary["losses"]).replace(0, pd.NA)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)

    log.info("Wrote %s", out_parquet)
    log.info("Wrote %s", out_csv)
    log.info("Wrote %s", OUT_DIR / "summary.csv")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
