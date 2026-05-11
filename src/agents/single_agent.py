from __future__ import annotations

from typing import Any, Dict

from src.agents.base_agent import AgentOutput, BaseAgent, format_task_context


class SingleAgent(BaseAgent):
    def __init__(self, client: Any):
        super().__init__(
            client=client,
            name="SingleAgent",
            system_prompt="""
你是一个用于多 Agent 架构实验的单 Agent。
你的目标是直接完成任务，输出结构清晰、内容扎实、可执行的最终答案。
不要描述你自己的内部推理过程。
""",
        )

    def run(self, task: Dict[str, Any]) -> AgentOutput:
        prompt = f"""
任务类别：{task.get("category", "")}

任务内容：
{format_task_context(task)}

请直接给出最终答案。要求：
1. 结构清晰。
2. 观点明确。
3. 尽量覆盖关键风险和落地细节。
"""
        return self._run_prompt(prompt)
