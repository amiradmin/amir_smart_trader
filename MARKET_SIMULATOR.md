# Synthetic Market Data Simulator

The Smart Trader repository currently has a file-based pipeline: SignalFlow is configured to write decisions to `data/decisions.jsonl`, and the MT5 bridge tails that file. There is no Django ingestion API in this repository.

`tools/market_simulator.py` creates synthetic OHLCV market data for offline development. It writes two files:

- `data/raw/synthetic_xauusd_m15.csv`
- `data/raw/synthetic_xauusd_m15.jsonl`

The simulator does **not** connect to MT5, SignalFlow, a broker, or an order endpoint. It does not place trades. A separate market-data reader still needs to be implemented to feed these files into the SignalFlow detector.

## Quick start

From the repository root:

```bash
python3 tools/market_simulator.py --count 100
```

Generate 500 M15 bars quickly with a deterministic random seed:

```bash
python3 tools/market_simulator.py \
  --symbol XAUUSD \
  --timeframe 15 \
  --price 4000 \
  --volatility 2.5 \
  --trend 0.05 \
  --count 500 \
  --interval 0
```

Run continuously, generating one new simulated bar every two seconds:

```bash
python3 tools/market_simulator.py --count 0 --interval 2
```

Use a different output prefix to preserve previous generated data:

```bash
python3 tools/market_simulator.py \
  --output-prefix data/raw/experiment_01 \
  --count 200
```

By default, output files are replaced on each run. Pass `--append` to append instead. When appending, choose a fresh or chronologically compatible output prefix to avoid mixing datasets.

## Options

| Option | Default | Description |
|---|---:|---|
| `--symbol` | `XAUUSD` | Instrument label |
| `--timeframe` | `15` | Candle duration in minutes |
| `--price` | `4000.0` | Initial price |
| `--volatility` | `2.5` | Standard deviation of per-bar price changes |
| `--trend` | `0.0` | Mean per-bar price change |
| `--spread` | `0.25` | Synthetic spread value |
| `--seed` | `42` | Reproducible random seed; use `none` for a random seed |
| `--count` | `100` | Number of bars; `0` means continuous |
| `--interval` | `0.0` | Real seconds between generated bars |
| `--start-time` | calculated | First timestamp in ISO-8601 format |
| `--output-prefix` | `data/raw/synthetic_xauusd_m15` | Output path without extension |
| `--append` | off | Append instead of replacing files |

All timestamps are written in UTC. This is synthetic test data, not a historical market feed or a trading recommendation.
