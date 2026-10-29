"""Unit tests for the research-only EMA/ATR detector."""
from __future__ import annotations

import unittest

from signalflow_engine.main import validate
from signalflow_engine.research_detector import detect_from_bars


def make_bars(closes: list[float]) -> list[dict]:
    bars = []
    previous = closes[0]
    for index, close in enumerate(closes):
        bars.append({
            "time": f"2026-01-01T00:{index:02d}:00Z",
            "open": previous,
            "high": max(previous, close) + 1.0,
            "low": min(previous, close) - 1.0,
            "close": close,
        })
        previous = close
    return bars


class ResearchDetectorTests(unittest.TestCase):
    def test_insufficient_history_produces_no_candidate(self):
        self.assertEqual(detect_from_bars(make_bars([100.0] * 20), "XAUUSD_o"), [])

    def test_upward_ema_cross_has_valid_buy_levels(self):
        closes = [130.0 - i for i in range(29)] + [120.0]
        candidates = detect_from_bars(make_bars(closes), "XAUUSD_o")
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["side"], "buy")
        self.assertLess(candidate["sl"], candidate["entry"])
        self.assertGreater(candidate["tp"], candidate["entry"])
        self.assertTrue(candidate["bar_time"])
        self.assertTrue(validate(candidate)[0])
        self.assertEqual(candidate["features"]["confidence_type"], "heuristic_not_probability")

    def test_validator_rejects_wrong_buy_stop_direction(self):
        candidate = {
            "side": "buy", "entry": 100.0, "sl": 101.0, "tp": 110.0,
            "confidence": 0.8,
        }
        self.assertFalse(validate(candidate)[0])

    def test_validator_rejects_low_reward_risk(self):
        candidate = {
            "side": "buy", "entry": 100.0, "sl": 90.0, "tp": 105.0,
            "confidence": 0.8,
        }
        self.assertFalse(validate(candidate)[0])


if __name__ == "__main__":
    unittest.main()
