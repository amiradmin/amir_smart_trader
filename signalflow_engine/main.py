"""
SignalFlow decision engine entry point.

Research pipeline:
    closed OHLC CSV -> EMA/ATR detector -> basic risk validation -> research_candidates.jsonl

This version produces research candidates only. The MT5 bridge must remain disabled
until candidates have been backtested and execution safeguards independently reviewed.
"""
from __future__ import annotations

import json
import logging
import signal as os_signal
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signalflow_engine.config import Config
from signalflow_engine.research_detector import detect_from_csv

log = logging.getLogger("signalflow")
_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    log.info("Received signal %s, shutting down...", signum)
    _shutdown = True


@dataclass
class Decision:
    ts: str
    signal_id: str
    symbol: str
    side: str
    entry: float | None
    sl: float | None
    tp: float | None
    confidence: float
    strategy: str
    features: dict[str, Any]


def detect(symbol: str, timeframe: str, data_dir: Path) -> list[dict]:
    """Detect research candidates from data/raw/{SYMBOL}_{TIMEFRAME}.csv."""
    return detect_from_csv(data_dir, symbol, timeframe)


def validate(candidate: dict) -> tuple[bool, float]:
    """Apply basic shape, direction, stop/target and confidence checks."""
    try:
        side = candidate["side"]
        entry = float(candidate["entry"])
        sl = float(candidate["sl"])
        tp = float(candidate["tp"])
        confidence = float(candidate["confidence"])
    except (KeyError, TypeError, ValueError):
        return False, 0.0
    if side not in {"buy", "sell"}:
        return False, confidence if "confidence" in candidate else 0.0
    if not all(map(lambda x: x > 0 and x < float("inf"), (entry, sl, tp, confidence))):
        return False, confidence
    if confidence < 0.55 or confidence > 1.0:
        return False, confidence
    if side == "buy" and not (sl < entry < tp):
        return False, confidence
    if side == "sell" and not (tp < entry < sl):
        return False, confidence
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0 or reward / risk < 1.2:
        return False, confidence
    return True, confidence


def _stable_signal_id(symbol: str, side: str, bar_time: str) -> str:
    identity = bar_time.strip() or "unknown-bar"
    return f"{symbol}-{side}-{identity}".replace(":", "").replace("+", "").replace(" ", "_")


def _existing_signal_ids(path: Path) -> set[str]:
    """Load previously emitted IDs so polling/restarts don't duplicate a bar signal."""
    seen: set[str] = set()
    if not path.is_file():
        return seen
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                    if item.get("signal_id"):
                        seen.add(str(item["signal_id"]))
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        log.exception("Could not read prior decisions from %s", path)
    return seen


def _emit(decisions_path: Path, decision: Decision) -> None:
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with decisions_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(decision), allow_nan=False) + "\n")
        stream.flush()


def run_once(cfg: Config) -> int:
    emitted = 0
    now = datetime.now(timezone.utc).isoformat()
    # Deliberately separate from decisions.jsonl, which the legacy bridge may execute.\n    output_path = cfg.data_dir / "research_candidates.jsonl"\n    seen = _existing_signal_ids(output_path)
    for symbol in cfg.symbols:
        for candidate in detect(symbol, cfg.timeframe, cfg.data_dir):
            ok, confidence = validate(candidate)
            if not ok:
                log.debug("Rejected %s %s by validation", symbol, candidate.get("side"))
                continue
            side = candidate["side"]
            bar_time = str(candidate.get("bar_time") or "")
            if not bar_time:
                log.warning("Skipping %s candidate without a stable candle timestamp", symbol)
                continue
            signal_id = _stable_signal_id(symbol, side, bar_time)
            if signal_id in seen:
                continue
            decision = Decision(
                ts=now,
                signal_id=signal_id,
                symbol=symbol,
                side=side,
                entry=float(candidate["entry"]),
                sl=float(candidate["sl"]),
                tp=float(candidate["tp"]),
                confidence=confidence,
                strategy=str(candidate.get("strategy", "ema9_21_atr14_research")),
                features=candidate.get("features", {}),
            )
            _emit(output_path, decision)
            seen.add(signal_id)
            log.info("Emitted research candidate %s %s conf=%.2f", symbol, side, confidence)
            emitted += 1
    return emitted


def main() -> int:
    cfg = Config.from_env()
    if cfg.poll_seconds < 1:
        raise ValueError("POLL_SECONDS must be at least 1")
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info("SignalFlow research mode | symbols=%s tf=%s poll=%ss",
             ",".join(cfg.symbols), cfg.timeframe, cfg.poll_seconds)
    log.info("Closed-candle CSV input: %s/raw/{SYMBOL}_{TIMEFRAME}.csv", cfg.data_dir)
    log.info("Research-only output -> %s/research_candidates.jsonl", cfg.data_dir)

    os_signal.signal(os_signal.SIGTERM, _handle_signal)
    os_signal.signal(os_signal.SIGINT, _handle_signal)
    while not _shutdown:
        try:
            count = run_once(cfg)
            if count:
                log.info("Cycle emitted %d research candidate(s)", count)
        except Exception:
            log.exception("Cycle error (continuing)")
        for _ in range(cfg.poll_seconds):
            if _shutdown:
                break
            time.sleep(1)
    log.info("SignalFlow stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
