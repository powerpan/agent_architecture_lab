from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.evaluation.metrics import aggregate_by_architecture


def generate_summary_report(
    records: List[Dict[str, Any]],
    experiment_config: Dict[str, Any],
    output_path: str,
) -> Path:
    report_path = Path(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    rows = aggregate_by_architecture(records)
    table = _to_markdown_table(rows)

    lines = [
        "# Agent Architecture Lab Summary",
        "",
        "## 实验配置",
        "",
        f"- Architectures: {', '.join(experiment_config.get('architectures', []))}",
        f"- Task file: `{experiment_config.get('task_file')}`",
        f"- Output dir: `{experiment_config.get('output_dir')}`",
        f"- Model config: `{experiment_config.get('model_config')}`",
        f"- Pricing config: `{experiment_config.get('pricing_config')}`",
        f"- Judge enabled: `{experiment_config.get('judge_enabled')}`",
        "",
        "## 架构统计",
        "",
        table,
        "",
        "## 简短结论",
        "",
        "第一版报告只提供基础统计。建议结合各任务的 `final_answer` 和 `intermediate_outputs` 继续人工分析质量差异。",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _to_markdown_table(rows: List[Dict[str, Any]]) -> str:
    normalized = []
    for row in rows:
        normalized.append(
            {
                "architecture": row["architecture"],
                "task_count": row["task_count"],
                "success_count": row["success_count"],
                "error_count": row["error_count"],
                "avg_latency_seconds": round(row["avg_latency_seconds"], 3),
                "avg_total_tokens": round(row["avg_total_tokens"], 1),
                "avg_estimated_cost": round(row["avg_estimated_cost"], 8),
            }
        )

    headers = [
        "architecture",
        "task_count",
        "success_count",
        "error_count",
        "avg_latency_seconds",
        "avg_total_tokens",
        "avg_estimated_cost",
    ]
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    header = "| " + " | ".join(headers) + " |"
    body = [
        "| " + " | ".join(str(row.get(header_name, "")) for header_name in headers) + " |"
        for row in normalized
    ]
    return "\n".join([header, separator] + body)
