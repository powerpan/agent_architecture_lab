from __future__ import annotations

from typing import Any, Dict, Optional

from src.agents.base_agent import AgentOutput, BaseAgent


class ExecutorAgent(BaseAgent):
    def __init__(self, client: Any, name: str = "Executor", system_prompt: Optional[str] = None):
        super().__init__(
            client=client,
            name=name,
            system_prompt=system_prompt
            or """
你是一个执行 Agent。
你的职责是根据任务、计划和审查意见产出最终答案。
输出要完整、具体、可读，避免空泛表述。
""",
        )

    def execute(
        self,
        task: Dict[str, Any],
        plan: Optional[str] = None,
        draft: Optional[str] = None,
        review: Optional[str] = None,
    ) -> AgentOutput:
        if review and draft:
            prompt = f"""
任务类别：{task.get("category", "")}

原始任务：
{task["input"]}

计划：
{plan or "无"}

上一版草稿：
{draft}

Reviewer 审查意见：
{review}

请根据审查意见生成最终答案。要求保留草稿中的有效内容，修正明显缺口，并输出可直接使用的最终版本。
"""
            return self._run_prompt(prompt)

        prompt = f"""
任务类别：{task.get("category", "")}

原始任务：
{task["input"]}

计划：
{plan or "无"}

请根据计划完成任务，输出最终答案。
"""
        return self._run_prompt(prompt)

    def propose_for_debate(self, task: Dict[str, Any], angle: str) -> AgentOutput:
        prompt = f"""
任务类别：{task.get("category", "")}

任务内容：
{task["input"]}

请从以下角度给出一份独立方案：
{angle}

要求：
1. 明确你的核心判断。
2. 给出结构化论证。
3. 说明方案的优势、风险和适用边界。
"""
        return self._run_prompt(prompt)
