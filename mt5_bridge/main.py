"""
MT5 execution bridge.

Tails decisions.jsonl produced by the SignalFlow engine, translates each
decision into an MT5 order request, and logs the outcome to trade_outcomes.jsonl.

MT5 connection:
    - The bridge talks to a `mt5-remote` server running inside Wine,
      OR to the Windows `MetaTrader5` package if this process runs in Wine.
    - Both are exposed via the same API, so `_get_mt5()` hides the difference.
"""
from __future__ import annotations

import json
import logging
import os
import signal as os_signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mt5_bridge.config import Config

log = logging.getLogger("mt5_bridge")
_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    log.info("Received signal %s, shutting down...", signum)
    _shutdown = True


# ---------------------------------------------------------------------------
# MT5 adapter — works with mt5-remote OR native MetaTrader5 (in Wine)
# ---------------------------------------------------------------------------
class MT5Adapter:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.mt5 = self._load()

    def _load(self):
        # 1) mt5-remote (Linux client -> Wine server)
        try:
            from mt5_remote import MetaTrader5 as MT5Remote  # type: ignore
            client = MT5Remote(host=self.cfg.mt5_host, port=self.cfg.mt5_port)
            log.info("Using mt5-remote at %s:%s", self.cfg.mt5_host, self.cfg.mt5_port)
            return client
        except ImportError:
            pass
        # 2) native MetaTrader5 (only importable inside Wine)
        try:
            import MetaTrader5 as MT5Native  # type: ignore
            log.info("Using native MetaTrader5 (Wine)")
            return MT5Native
        except ImportError:
            log.warning("No MT5 backend available. Running in stub mode.")
            return None

    def initialize(self) -> bool:
        if self.mt5 is None:
            return False
        kwargs: dict[str, Any] = {}
        if self.cfg.mt5_login:
            kwargs.update(
                login=self.cfg.mt5_login,
                password=self.cfg.mt5_password,
                server=self.cfg.mt5_server,
            )
        ok = self.mt5.initialize(**kwargs) if kwargs else self.mt5.initialize()
        if not ok:
            log.error("MT5 initialize failed: %s", getattr(self.mt5, "last_error", lambda: None)())
            return False
        info = self.mt5.terminal_info()
        log.info("MT5 connected: %s", getattr(info, "name", "unknown"))
        return True

    def shutdown(self) -> None:
        if self.mt5 is not None:
            try:
                self.mt5.shutdown()
            except Exception:
                log.exception("MT5 shutdown error")

    # -----------------------------------------------------------------
    # Order sizing — very basic. Replace with your risk manager.
    # -----------------------------------------------------------------
    def _lots(self, symbol: str, entry: float, sl: float) -> float:
        if self.mt5 is None:
            return 0.01
        info = self.mt5.symbol_info(symbol)
        account = self.mt5.account_info()
        if info is None or account is None or sl == entry:
            return 0.01

        # risk in account currency
        risk_amount = account.balance * (self.cfg.risk_percent / 100.0)
        # value per point per lot
        tick_value = info.trade_tick_value
        tick_size = info.trade_tick_size or info.point
        if tick_value <= 0 or tick_size <= 0:
            return 0.01
        sl_points = abs(entry - sl) / tick_size
        loss_per_lot = sl_points * tick_value
        if loss_per_lot <= 0:
            return 0.01
        lots = risk_amount / loss_per_lot
        # clamp to broker limits
        lots = max(info.volume_min, min(info.volume_max, lots))
        step = info.volume_step or 0.01
        lots = round(lots / step) * step
        return round(lots, 2)

    def send_order(self, decision: dict) -> dict:
        symbol = decision["symbol"]
        side = decision["side"]
        entry = decision.get("entry")
        sl = decision.get("sl")
        tp = decision.get("tp")

        if self.mt5 is None or self.cfg.dry_run:
            log.info("[DRY_RUN] Would send %s %s entry=%s sl=%s tp=%s",
                     side, symbol, entry, sl, tp)
            return {"retcode": 0, "comment": "dry_run", "symbol": symbol}

        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"retcode": -1, "comment": f"no tick for {symbol}"}

        is_buy = side.lower() in ("buy", "long")
        price = tick.ask if is_buy else tick.bid
        order_type = (
            self.mt5.ORDER_TYPE_BUY if is_buy else self.mt5.ORDER_TYPE_SELL
        )
        volume = self._lots(symbol, price, float(sl) if sl else price)

        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "deviation": self.cfg.deviation,
            "magic": self.cfg.magic,
            "comment": decision.get("signal_id", "")[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }
        log.info("Sending order: %s", request)
        result = self.mt5.order_send(request)
        return {
            "retcode": getattr(result, "retcode", -1),
            "order": getattr(result, "order", None),
            "comment": getattr(result, "comment", ""),
            "price": getattr(result, "price", price),
            "volume": volume,
            "symbol": symbol,
        }


# ---------------------------------------------------------------------------
# Decision tailer
# ---------------------------------------------------------------------------
def _read_new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    if not path.exists():
        return [], offset
    lines: list[str] = []
    with path.open() as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
        new_offset = f.tell()
    return lines, new_offset


def _log_outcome(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()


def main() -> int:
    cfg = Config.from_env()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info("MT5 bridge starting | dry_run=%s decisions=%s",
             cfg.dry_run, cfg.decisions_path)

    os_signal.signal(os_signal.SIGTERM, _handle_signal)
    os_signal.signal(os_signal.SIGINT, _handle_signal)

    adapter = MT5Adapter(cfg)
    if not adapter.initialize():
        log.warning("MT5 not connected — running in stub mode (dry_run forced)")
        cfg = Config(**{**cfg.__dict__, "dry_run": True})

    # Skip anything already in the file when we start
    _, offset = _read_new_lines(cfg.decisions_path, 0)

    try:
        while not _shutdown:
            lines, offset = _read_new_lines(cfg.decisions_path, offset)
            for line in lines:
                try:
                    decision = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("Bad decision line: %s", line[:120])
                    continue
                try:
                    result = adapter.send_order(decision)
                except Exception:
                    log.exception("send_order failed")
                    result = {"retcode": -1, "comment": "exception"}
                outcome = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "signal_id": decision.get("signal_id"),
                    "symbol": decision.get("symbol"),
                    "side": decision.get("side"),
                    "entry_requested": decision.get("entry"),
                    "sl": decision.get("sl"),
                    "tp": decision.get("tp"),
                    "confidence": decision.get("confidence"),
                    "execution": result,
                    "outcome": "open" if result.get("retcode") == 0 else "rejected",
                }
                _log_outcome(cfg.outcomes_path, outcome)
            for _ in range(2):
                if _shutdown:
                    break
                time.sleep(1)
    finally:
        adapter.shutdown()
    log.info("MT5 bridge stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
