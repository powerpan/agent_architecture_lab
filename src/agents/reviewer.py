from __future__ import annotations

from typing import Any, Dict

from src.agents.base_agent import AgentOutput, BaseAgent, format_task_context


class ReviewerAgent(BaseAgent):
    def __init__(self, client: Any):
        super().__init__(
            client=client,
            name="Reviewer",
            system_prompt="""
你是一个审查 Agent。
你的职责是审查草稿是否完整、准确、结构清晰，并指出可执行的修改建议。
不要重写全文，只输出审查意见。
""",
        )

    def review(self, task: Dict[str, Any], plan: str, draft: str) -> AgentOutput:
        prompt = f"""
任务类别：{task.get("category", "")}

原始任务：
{format_task_context(task)}

计划：
{plan}

Executor 草稿：
{draft}

请审查草稿，重点关注：
1. 是否回答了原始任务。
2. 是否遗漏关键点。
3. 结构是否清晰。
4. 是否存在空泛、错误或不可执行内容。
5. 给出具体修改建议。
"""
        return self._run_prompt(prompt)
