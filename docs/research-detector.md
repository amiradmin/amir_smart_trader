# Research-only EMA/ATR detector

This branch adds a deterministic baseline detector to SignalFlow. It is for research and
paper evaluation only; it is not a validated profitable strategy or a calibrated ML model.

## Input data

Place a CSV file at:

`data/raw/XAUUSD_o_M15.csv`

The filename is `{SYMBOL}_{TIMEFRAME}.csv`. Required case-insensitive columns are
`open,high,low,close`. Include a candle time column named `time`, `timestamp`, or
`datetime` for stable signal IDs. Rows must be ordered oldest first and should contain
closed candles only. At least 30 valid rows are required. Example:

```csv
time,open,high,low,close
2026-10-28T09:00:00Z,2750.0,2752.0,2748.0,2751.0
```

The detector does not connect to MT5 and does not fetch market data by itself. A separate
data-export step must populate the CSV with your broker's exact symbol and correctly
timestamped candles.

## Baseline rules

- Buy when EMA(9) crosses above EMA(21) between the previous and latest row.
- Sell when EMA(9) crosses below EMA(21).
- ATR(14) is the simple mean of the last 14 true ranges.
- Stop distance is 1.5 × ATR; target distance is 1.8 × stop distance (nominal RR 1.8:1).
- Candidate confidence is a transparent heuristic, not a probability and not an ML score.
- Basic validation checks direction of stop/target, positive finite prices, confidence
  range and minimum reward/risk of 1.2:1.

## Output and execution safety

Candidates are appended to `data/research_candidates.jsonl`. They are intentionally kept
separate from `data/decisions.jsonl`, which the legacy bridge may consume for execution.
This detector does not place orders. Do not connect its output to a live execution path.

## Tests

From the repository root:

```bash
python -m unittest discover -s tests -v
```

Before any execution integration, add broker spread/commission/slippage assumptions, robust
out-of-sample and walk-forward backtests, data-quality checks, drawdown/position sizing rules,
and paper-trading verification. No profitability claim is made by this baseline.
