from __future__ import annotations

import unittest

from app.llm.base import Usage
from app.llm.pricing import PRICING, cost_usd


class CostUsdTest(unittest.TestCase):
    def test_known_model_is_priced_per_million_tokens(self) -> None:
        cost = cost_usd("gemini-3.1-flash-lite", Usage(1_000_000, 1_000_000, 2_000_000))
        pricing = PRICING["gemini-3.1-flash-lite"]
        self.assertAlmostEqual(cost, pricing.input_per_1m + pricing.output_per_1m, places=6)

    def test_unknown_model_returns_zero(self) -> None:
        self.assertEqual(cost_usd("unknown-model", Usage(1000, 500, 1500)), 0.0)

    def test_zero_usage_costs_zero(self) -> None:
        self.assertEqual(cost_usd("gpt-4o", Usage(0, 0, 0)), 0.0)

    def test_partial_usage_scales_linearly(self) -> None:
        small = cost_usd("gpt-4o", Usage(100, 50, 150))
        big = cost_usd("gpt-4o", Usage(200, 100, 300))
        self.assertAlmostEqual(big, small * 2, places=6)


if __name__ == "__main__":
    unittest.main()
