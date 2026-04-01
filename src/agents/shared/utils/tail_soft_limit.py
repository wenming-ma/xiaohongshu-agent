from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart


def build_soft_limit_message(output_name: str) -> str:
    return (
        "URGENT: The context window is nearly full.\n"
        "STOP all browsing and tool calls immediately.\n"
        f"Output your {output_name} NOW with all data collected so far."
    )


def build_tail_soft_limit_history_processor(*, output_name: str, threshold: int = 50):
    soft_limit_message = build_soft_limit_message(output_name)

    async def processor(ctx: RunContext[Any], messages: list[ModelMessage]) -> list[ModelMessage]:
        if ctx.usage.requests < threshold:
            return messages

        if _has_trailing_soft_limit_prompt(messages, soft_limit_message):
            return messages

        return [*messages, ModelRequest(parts=[UserPromptPart(content=soft_limit_message)])]

    return processor


def _has_trailing_soft_limit_prompt(messages: list[ModelMessage], prompt: str) -> bool:
    if not messages or not isinstance(messages[-1], ModelRequest):
        return False

    parts = messages[-1].parts
    return len(parts) == 1 and isinstance(parts[0], UserPromptPart) and parts[0].content == prompt
