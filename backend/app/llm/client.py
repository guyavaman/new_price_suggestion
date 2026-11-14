"""Thin wrapper around the Anthropic API.

Structured output is done with *forced tool use*: we give Claude a single tool whose input schema
is our Pydantic model and force it to call that tool. The tool "arguments" are our JSON.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

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


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    fn: Callable[[dict], Any]


@dataclass
class AgentRun:
    final_text: str
    tool_calls: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    stopped_early: bool = False


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

    def run_agent(
        self,
        *,
        system: str,
        user: str | None = None,
        tools: list[ToolSpec],
        max_steps: int = 8,
        history: list[dict] | None = None,
    ) -> AgentRun:
        """Classic tool-use loop: the model calls our functions until it answers in text.

        Tool errors are returned to the model as `is_error` results so it can recover.
        `max_steps` caps the loop, so a confused model can never run forever.
        """
        by_name = {t.name: t for t in tools}
        api_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        messages: list[dict] = list(history or [])
        if user is not None:
            messages.append({"role": "user", "content": user})
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("Conversation must end with a user message")
        run = AgentRun(final_text="")
        start = time.perf_counter()

        for _ in range(max_steps):
            response = self._client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system,
                tools=api_tools, messages=messages,
            )
            run.input_tokens += response.usage.input_tokens
            run.output_tokens += response.usage.output_tokens
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                run.final_text = "".join(
                    b.text for b in response.content if b.type == "text"
                ).strip()
                break

            messages.append({"role": "assistant", "content": [
                b.model_dump() if hasattr(b, "model_dump") else vars(b)
                for b in response.content
            ]})
            results = []
            for tu in tool_uses:
                spec = by_name.get(tu.name)
                try:
                    if spec is None:
                        raise ValueError(f"Unknown tool {tu.name}")
                    output = spec.fn(dict(tu.input))
                    is_error = False
                except Exception as e:  # report to the model, don't crash the run
                    output, is_error = f"Error: {e}", True
                run.tool_calls.append(
                    {"tool": tu.name, "input": dict(tu.input), "output": output, "error": is_error}
                )
                results.append({
                    "type": "tool_result", "tool_use_id": tu.id, "is_error": is_error,
                    "content": output if isinstance(output, str)
                    else json.dumps(output, ensure_ascii=False),
                })
            messages.append({"role": "user", "content": results})
        else:
            run.stopped_early = True

        run.latency_ms = int((time.perf_counter() - start) * 1000)
        return run
