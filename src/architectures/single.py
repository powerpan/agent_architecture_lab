from __future__ import annotations

from typing import Any, Dict

from src.agents.base_agent import aggregate_usage
from src.agents.single_agent import SingleAgent


class SingleArchitecture:
    name = "single"

    def __init__(self, client: Any):
        self.client = client

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        output = SingleAgent(self.client).run(task)
        usage = aggregate_usage([output])
        return {
            "final_answer": output.content,
            "intermediate_outputs": {},
            **usage,
        }
