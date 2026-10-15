from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    mt5_host: str
    mt5_port: int
    mt5_login: int | None
    mt5_password: str | None
    mt5_server: str | None

    decisions_path: Path
    outcomes_path: Path

    magic: int
    deviation: int
    risk_percent: float
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Config":
        root = Path(os.getenv("APP_ROOT", "/app"))
        data_dir = Path(os.getenv("DATA_DIR", root / "data"))
        login = os.getenv("MT5_LOGIN")
        return cls(
            mt5_host=os.getenv("MT5_HOST", "host.docker.internal"),
            mt5_port=int(os.getenv("MT5_PORT", "18812")),
            mt5_login=int(login) if login else None,
            mt5_password=os.getenv("MT5_PASSWORD"),
            mt5_server=os.getenv("MT5_SERVER"),
            decisions_path=Path(os.getenv("DECISIONS_PATH", data_dir / "decisions.jsonl")),
            outcomes_path=Path(os.getenv("OUTCOMES_PATH", data_dir / "trade_outcomes.jsonl")),
            magic=int(os.getenv("MT5_MAGIC", "20250101")),
            deviation=int(os.getenv("MT5_DEVIATION", "20")),
            risk_percent=float(os.getenv("RISK_PERCENT", "0.5")),
            dry_run=os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes"),
        )
