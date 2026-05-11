from __future__ import annotations

from typing import Any, Dict

from src.agents.base_agent import AgentOutput, BaseAgent


class PlannerAgent(BaseAgent):
    def __init__(self, client: Any):
        super().__init__(
            client=client,
            name="Planner",
            system_prompt="""
你是一个任务规划 Agent。
你的职责是理解任务、拆解步骤、明确输出结构和质量检查点。
只输出计划，不直接完成最终答案。
""",
        )

    def plan(self, task: Dict[str, Any]) -> AgentOutput:
        prompt = f"""
任务类别：{task.get("category", "")}

任务内容：
{task["input"]}

请输出一个执行计划，包含：
1. 目标理解。
2. 关键子问题。
3. 建议输出结构。
4. 容易遗漏的风险点。
5. 最终答案的质量标准。
"""
        return self._run_prompt(prompt)
