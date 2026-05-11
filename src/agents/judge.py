from __future__ import annotations

from typing import Any, Dict

from src.agents.base_agent import AgentOutput, BaseAgent


class JudgeAgent(BaseAgent):
    def __init__(self, client: Any):
        super().__init__(
            client=client,
            name="Judge",
            system_prompt="""
你是一个裁判 Agent。
你的职责是比较不同候选答案，综合其优点，产出更稳健的最终答案。
如果用于评分，你必须严格按要求输出 JSON。
""",
        )

    def synthesize(self, task: Dict[str, Any], answer_a: str, answer_b: str) -> AgentOutput:
        prompt = f"""
任务类别：{task.get("category", "")}

原始任务：
{task["input"]}

候选答案 A：
{answer_a}

候选答案 B：
{answer_b}

请比较两个候选答案，综合优点并修正不足，输出最终答案。
要求：
1. 不要简单拼接。
2. 保留更可靠、更具体的内容。
3. 明确结论和结构。
"""
        return self._run_prompt(prompt)

    def evaluate_quality(self, task: Dict[str, Any], final_answer: str) -> AgentOutput:
        prompt = f"""
请评价下面答案相对于任务的质量。

任务类别：{task.get("category", "")}

任务内容：
{task["input"]}

待评价答案：
{final_answer}

请只输出 JSON，不要输出 Markdown，不要添加额外解释。JSON 格式如下：
{{
  "accuracy": 1,
  "completeness": 1,
  "structure": 1,
  "actionability": 1,
  "insight": 1,
  "overall_comment": "一句简短评价"
}}

评分要求：
- 每个维度为 1 到 5 的整数。
- accuracy 表示准确性。
- completeness 表示覆盖完整度。
- structure 表示结构清晰度。
- actionability 表示可执行性。
- insight 表示洞察力。
"""
        return self._run_prompt(prompt)
