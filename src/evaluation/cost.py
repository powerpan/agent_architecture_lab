from __future__ import annotations

from typing import Any, Dict


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    pricing_config: Dict[str, Any],
) -> float:
    model_pricing = pricing_config.get("models", {}).get(model, {})
    input_per_1m = float(model_pricing.get("input_per_1m_tokens", 0.0))
    output_per_1m = float(model_pricing.get("output_per_1m_tokens", 0.0))

    input_cost = prompt_tokens / 1_000_000 * input_per_1m
    output_cost = completion_tokens / 1_000_000 * output_per_1m
    return round(input_cost + output_cost, 8)
