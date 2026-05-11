from __future__ import annotations

from typing import Any, Dict

from src.agents.base_agent import aggregate_usage
from src.agents.executor import ExecutorAgent
from src.agents.planner import PlannerAgent


class PlannerExecutorArchitecture:
    name = "planner_executor"

    def __init__(self, client: Any):
        self.client = client

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        planner_output = PlannerAgent(self.client).plan(task)
        executor_output = ExecutorAgent(self.client).execute(task, plan=planner_output.content)
        usage = aggregate_usage([planner_output, executor_output])
        return {
            "final_answer": executor_output.content,
            "intermediate_outputs": {
                "plan": planner_output.to_dict(),
            },
            **usage,
        }
