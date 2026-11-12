"""Thin wrapper around the Anthropic API.

Structured output is done with *forced tool use*: we give Claude a single tool whose input schema
is our Pydantic model and force it to call that tool. The tool "arguments" are our JSON.
"""

import time
from dataclasses import dataclass
from typing import TypeVar

from anthropic import Anthropic
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMCallStats:
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class LLMClient:
    def __init__(self, model: str | None = None, client: Anthropic | None = None):
        settings = get_settings()
        self.model = model or settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        self._client = client or Anthropic(api_key=settings.anthropic_api_key or None)

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        tool_name: str,
        tool_description: str,
    ) -> tuple[T, LLMCallStats]:
        tool = {
            "name": tool_name,
            "description": tool_description,
            "input_schema": schema.model_json_schema(),
        }
        start = time.perf_counter()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        tool_input = next(
            (b.input for b in response.content if b.type == "tool_use" and b.name == tool_name),
            None,
        )
        if tool_input is None:
            raise ValueError("Model did not call the structured-output tool")

        # Pydantic validation is our guardrail: malformed output raises here.
        parsed = schema.model_validate(tool_input)
        stats = LLMCallStats(
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
        )
        return parsed, stats
