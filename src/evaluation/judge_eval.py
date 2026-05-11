from __future__ import annotations

import json
import re
from typing import Any, Dict, Tuple

from src.agents.base_agent import aggregate_usage
from src.agents.judge import JudgeAgent


def evaluate_with_judge(client: Any, task: Dict[str, Any], final_answer: str) -> Tuple[Dict[str, Any], Dict[str, int]]:
    output = JudgeAgent(client).evaluate_quality(task, final_answer)
    usage = aggregate_usage([output])
    parsed = _parse_json_object(output.content)
    return {
        "scores": parsed,
        "raw_output": output.content,
    }, usage


def _parse_json_object(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Judge did not return JSON: {text[:200]}")
        return json.loads(match.group(0))
