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

    @classmethod
    def from_response(cls, agent: str, response: LLMResponse) -> "AgentOutput":
        return cls(
            agent=agent,
            content=response.content,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            latency_seconds=response.latency_seconds,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "content": self.content,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_seconds": round(self.latency_seconds, 3),
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


def aggregate_usage(outputs: List[AgentOutput]) -> Dict[str, int]:
    return {
        "prompt_tokens": sum(output.prompt_tokens for output in outputs),
        "completion_tokens": sum(output.completion_tokens for output in outputs),
        "total_tokens": sum(output.total_tokens for output in outputs),
        "num_model_calls": len(outputs),
    }
