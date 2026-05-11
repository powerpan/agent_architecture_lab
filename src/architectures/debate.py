from __future__ import annotations

from typing import Any, Dict

from src.agents.base_agent import aggregate_usage
from src.agents.executor import ExecutorAgent
from src.agents.judge import JudgeAgent


class DebateArchitecture:
    name = "debate"

    def __init__(self, client: Any):
        self.client = client

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        debater_a = ExecutorAgent(
            self.client,
            name="DebaterA",
            system_prompt="""
你是 Debate 架构中的候选方案 Agent A。
你的风格偏工程落地，重视可执行步骤、成本和稳定性。
""",
        )
        debater_b = ExecutorAgent(
            self.client,
            name="DebaterB",
            system_prompt="""
你是 Debate 架构中的候选方案 Agent B。
你的风格偏批判分析，重视边界条件、风险和长期演化。
""",
        )

        answer_a = debater_a.propose_for_debate(task, "工程落地、步骤拆解、成本控制、稳定运行")
        answer_b = debater_b.propose_for_debate(task, "批判审查、风险识别、边界条件、长期维护")
        judge_output = JudgeAgent(self.client).synthesize(task, answer_a.content, answer_b.content)
        usage = aggregate_usage([answer_a, answer_b, judge_output])
        return {
            "final_answer": judge_output.content,
            "intermediate_outputs": {
                "debater_a": answer_a.to_dict(),
                "debater_b": answer_b.to_dict(),
            },
            **usage,
        }
