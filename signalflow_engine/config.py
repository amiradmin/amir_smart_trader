"""Runtime configuration loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    log_level: str
    data_dir: Path
    decisions_path: Path
    symbols: tuple[str, ...]
    timeframe: str
    poll_seconds: int

    @classmethod
    def from_env(cls) -> "Config":
        root = Path(os.getenv("APP_ROOT", "/app"))
        data_dir = Path(os.getenv("DATA_DIR", root / "data"))
        return cls(
            log_level=os.getenv("SIGNALFLOW_LOG_LEVEL", "INFO"),
            data_dir=data_dir,
            decisions_path=Path(
                os.getenv("DECISIONS_PATH", data_dir / "decisions.jsonl")
            ),
            symbols=tuple(
                s.strip().upper()
                for s in os.getenv("SYMBOLS", "XAUUSD,EURUSD,GBPUSD").split(",")
                if s.strip()
            ),
            timeframe=os.getenv("TIMEFRAME", "M15"),
            poll_seconds=int(os.getenv("POLL_SECONDS", "60")),
        )
