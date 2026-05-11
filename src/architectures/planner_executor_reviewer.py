from __future__ import annotations

from typing import Any, Dict

from src.agents.base_agent import aggregate_usage
from src.agents.executor import ExecutorAgent
from src.agents.planner import PlannerAgent
from src.agents.reviewer import ReviewerAgent


class PlannerExecutorReviewerArchitecture:
    name = "planner_executor_reviewer"

    def __init__(self, client: Any):
        self.client = client

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        planner_output = PlannerAgent(self.client).plan(task)
        draft_output = ExecutorAgent(self.client).execute(task, plan=planner_output.content)
        review_output = ReviewerAgent(self.client).review(
            task=task,
            plan=planner_output.content,
            draft=draft_output.content,
        )
        final_output = ExecutorAgent(self.client).execute(
            task=task,
            plan=planner_output.content,
            draft=draft_output.content,
            review=review_output.content,
        )
        usage = aggregate_usage([planner_output, draft_output, review_output, final_output])
        return {
            "final_answer": final_output.content,
            "intermediate_outputs": {
                "plan": planner_output.to_dict(),
                "executor_draft": draft_output.to_dict(),
                "review": review_output.to_dict(),
            },
            **usage,
        }
