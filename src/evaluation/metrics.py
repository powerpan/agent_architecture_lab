from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List


def aggregate_by_architecture(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["architecture"]].append(record)

    rows: List[Dict[str, Any]] = []
    for architecture, items in grouped.items():
        success_items = [item for item in items if item.get("success")]
        rows.append(
            {
                "architecture": architecture,
                "task_count": len(items),
                "success_count": len(success_items),
                "error_count": len(items) - len(success_items),
                "avg_latency_seconds": _mean([item.get("latency_seconds", 0.0) for item in success_items]),
                "avg_total_tokens": _mean([item.get("total_tokens", 0) for item in success_items]),
                "avg_estimated_cost": _mean([item.get("estimated_cost", 0.0) for item in success_items]),
            }
        )
    return sorted(rows, key=lambda row: row["architecture"])


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
