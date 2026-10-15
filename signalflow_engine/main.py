"""
SignalFlow decision engine entry point.

Pipeline:
    MarketData -> Detector -> Validator -> Strategy -> decisions.jsonl

The MT5 bridge consumes decisions.jsonl and executes them.
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
    side: str          # "buy" | "sell" | "flat"
    entry: float | None
    sl: float | None
    tp: float | None
    confidence: float
    strategy: str
    features: dict[str, Any]


# ---------------------------------------------------------------------------
# Detector — replace with your real detectors (ML models, indicators, etc.)
# ---------------------------------------------------------------------------
def detect(symbol: str, timeframe: str) -> list[dict]:
    """
    Return candidate signals. Empty list = no opportunity right now.

    TODO: plug in your SignalFlow detectors / ML models here.
    Example shape:
        {"side": "buy", "entry": 2400.5, "sl": 2390.0, "tp": 2425.0,
         "features": {"rsi": 32.1, "atr": 8.4}}
    """
    return []


# ---------------------------------------------------------------------------
# Validator — meta-labeling filter. Only pass high-confidence signals.
# ---------------------------------------------------------------------------
def validate(candidate: dict) -> tuple[bool, float]:
    """
    Return (ok, confidence). Confidence in [0, 1].

    TODO: load your trained LightGBM/XGBoost validator and score here.
    """
    confidence = float(candidate.get("confidence", 0.5))
    min_conf = 0.55
    return confidence >= min_conf, confidence


def _stable_signal_id(symbol: str, side: str, ts: str) -> str:
    return f"{symbol}-{side}-{ts}".replace(":", "").replace("+", "")


def _emit(decisions_path: Path, d: Decision) -> None:
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with decisions_path.open("a") as f:
        f.write(json.dumps(asdict(d)) + "\n")
        f.flush()


def run_once(cfg: Config) -> int:
    emitted = 0
    now = datetime.now(timezone.utc).isoformat()
    for symbol in cfg.symbols:
        for cand in detect(symbol, cfg.timeframe):
            ok, conf = validate(cand)
            if not ok:
                log.debug("Rejected %s %s (conf=%.2f)", symbol, cand.get("side"), conf)
                continue
            side = cand["side"]
            decision = Decision(
                ts=now,
                signal_id=_stable_signal_id(symbol, side, now),
                symbol=symbol,
                side=side,
                entry=cand.get("entry"),
                sl=cand.get("sl"),
                tp=cand.get("tp"),
                confidence=conf,
                strategy=cand.get("strategy", "default"),
                features=cand.get("features", {}),
            )
            _emit(cfg.decisions_path, decision)
            log.info("Emitted %s %s conf=%.2f", symbol, side, conf)
            emitted += 1
    return emitted


def main() -> int:
    cfg = Config.from_env()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info("SignalFlow starting | symbols=%s tf=%s poll=%ss",
             ",".join(cfg.symbols), cfg.timeframe, cfg.poll_seconds)
    log.info("Decisions -> %s", cfg.decisions_path)

    os_signal.signal(os_signal.SIGTERM, _handle_signal)
    os_signal.signal(os_signal.SIGINT, _handle_signal)

    while not _shutdown:
        try:
            n = run_once(cfg)
            if n:
                log.info("Cycle emitted %d decisions", n)
        except Exception:
            log.exception("Cycle error (continuing)")
        # sleep in small slices so shutdown is responsive
        for _ in range(cfg.poll_seconds):
            if _shutdown:
                break
            time.sleep(1)

    log.info("SignalFlow stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
