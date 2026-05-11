from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.llm.deepseek_client import LLMResponse


@dataclass
class AgentOutput:
    agent: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float
    finish_reason: str

    @classmethod
    def from_response(cls, agent: str, response: LLMResponse) -> "AgentOutput":
        return cls(
            agent=agent,
            content=response.content,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            latency_seconds=response.latency_seconds,
            finish_reason=response.finish_reason,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "content": self.content,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_seconds": round(self.latency_seconds, 3),
            "finish_reason": self.finish_reason,
        }


class BaseAgent:
    def __init__(self, client: Any, name: str, system_prompt: str):
        self.client = client
        self.name = name
        self.system_prompt = system_prompt.strip()

    def _run_prompt(self, user_prompt: str) -> AgentOutput:
        response = self.client.chat(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt.strip()},
            ]
        )
        return AgentOutput.from_response(self.name, response)


def aggregate_usage(outputs: List[AgentOutput]) -> Dict[str, Any]:
    return {
        "prompt_tokens": sum(output.prompt_tokens for output in outputs),
        "completion_tokens": sum(output.completion_tokens for output in outputs),
        "total_tokens": sum(output.total_tokens for output in outputs),
        "num_model_calls": len(outputs),
        "model_call_details": [
            {
                "agent": output.agent,
                "prompt_tokens": output.prompt_tokens,
                "completion_tokens": output.completion_tokens,
                "total_tokens": output.total_tokens,
                "latency_seconds": round(output.latency_seconds, 3),
                "finish_reason": output.finish_reason,
            }
            for output in outputs
        ],
        "hit_token_limit": any(output.finish_reason == "length" for output in outputs),
    }


def format_task_context(task: Dict[str, Any]) -> str:
    parts = [f"任务说明：\n{task['input']}"]
    material_content = str(task.get("material_content") or "").strip()
    if material_content:
        material_file = str(task.get("material_file") or "previous material")
        parts.append(
            "\n".join(
                [
                    f"你上一版写给我的材料（{material_file}）：",
                    material_content,
                    "",
                    "材料使用要求：请把以上内容当作你已经写给我的上一版材料，在此基础上继续处理；不要假设还有其他未提供的上游输出。",
                ]
            )
        )
    return "\n\n".join(parts)
