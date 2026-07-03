from __future__ import annotations

from dataclasses import dataclass

from .base import Usage


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m: float
    output_per_1m: float


PRICING: dict[str, ModelPricing] = {
    "gemini-3.1-flash-lite": ModelPricing(0.075, 0.30),
    "gemini-3.1-flash": ModelPricing(0.30, 2.50),
    "gemini-2.5-pro": ModelPricing(1.25, 5.00),
    "gemini-2.5-flash": ModelPricing(0.30, 2.50),
    "gpt-4o": ModelPricing(2.50, 10.00),
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00),
    "claude-sonnet-4-6": ModelPricing(3.00, 15.00),
}


def cost_usd(model: str, usage: Usage) -> float:
    pricing = PRICING.get(model)
    if pricing is None:
        return 0.0
    return round(
        usage.input_tokens / 1_000_000 * pricing.input_per_1m
        + usage.output_tokens / 1_000_000 * pricing.output_per_1m,
        6,
    )
