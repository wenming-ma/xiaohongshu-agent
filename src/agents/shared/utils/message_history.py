"""Shared helpers for safe message history truncation."""

from __future__ import annotations

from dataclasses import replace

from pydantic_ai.messages import (
    BaseToolCallPart,
    BaseToolReturnPart,
    ModelMessage,
    ModelRequest,
    RetryPromptPart,
    UserPromptPart,
)


def truncate_history_by_rounds(
    history: list[ModelMessage],
    *,
    max_rounds: int,
    keep_first_round: bool,
) -> list[ModelMessage]:
    """Trim message history by complete user-prompt rounds.

    The result is additionally sanitized so any tool call / tool return pair
    crossing the truncation boundary is removed together.
    """
    if not history or max_rounds <= 0:
        return []

    rounds = _split_history_rounds(history)
    if len(rounds) <= max_rounds:
        return _sanitize_tool_message_pairs(history)

    if keep_first_round:
        if max_rounds == 1:
            selected_rounds = [rounds[0]]
        else:
            selected_rounds = [rounds[0]] + rounds[-(max_rounds - 1):]
    else:
        selected_rounds = rounds[-max_rounds:]

    selected_history = [msg for round_messages in selected_rounds for msg in round_messages]
    return _sanitize_tool_message_pairs(selected_history)


def _split_history_rounds(history: list[ModelMessage]) -> list[list[ModelMessage]]:
    run_boundaries = [
        idx
        for idx, msg in enumerate(history)
        if isinstance(msg, ModelRequest)
        and any(isinstance(part, UserPromptPart) for part in msg.parts)
    ]

    if not run_boundaries:
        return [history]

    rounds: list[list[ModelMessage]] = []
    prefix = history[: run_boundaries[0]]
    for i, start in enumerate(run_boundaries):
        end = run_boundaries[i + 1] if i + 1 < len(run_boundaries) else len(history)
        round_messages = history[start:end]
        if i == 0 and prefix:
            round_messages = prefix + round_messages
        rounds.append(round_messages)
    return rounds


def _sanitize_tool_message_pairs(messages: list[ModelMessage]) -> list[ModelMessage]:
    valid_tool_call_ids = _collect_causally_matched_tool_call_ids(messages)
    if not valid_tool_call_ids:
        return [
            message
            for message in (
                _filter_message_parts(message, valid_tool_call_ids, set()) for message in messages
            )
            if message is not None
        ]

    seen_tool_calls: set[str] = set()
    return [
        message
        for message in (
            _filter_message_parts(message, valid_tool_call_ids, seen_tool_calls) for message in messages
        )
        if message is not None
    ]


def _collect_causally_matched_tool_call_ids(messages: list[ModelMessage]) -> set[str]:
    """Collect tool ids where a call appears before a matching result.

    Anthropic-compatible providers require every retained tool result to refer to an
    earlier tool call in the submitted history. A plain set intersection is not enough:
    it can still preserve out-of-order pairs. We therefore collect ids by scanning the
    history backwards and only mark calls that have a matching result later in the
    retained message sequence.
    """
    future_tool_result_ids: set[str] = set()
    matched_ids: set[str] = set()

    for message in reversed(messages):
        for part in reversed(message.parts):
            tool_result_id = _tool_result_id(part)
            if tool_result_id:
                future_tool_result_ids.add(tool_result_id)
                continue

            tool_call_id = _tool_call_id(part)
            if tool_call_id and tool_call_id in future_tool_result_ids:
                matched_ids.add(tool_call_id)

    return matched_ids


def _filter_message_parts(
    message: ModelMessage,
    valid_tool_call_ids: set[str],
    seen_tool_calls: set[str],
) -> ModelMessage | None:
    filtered_parts = []
    for part in message.parts:
        tool_call_id = _tool_call_id(part)
        if tool_call_id:
            if tool_call_id in valid_tool_call_ids:
                filtered_parts.append(part)
                seen_tool_calls.add(tool_call_id)
            continue

        tool_result_id = _tool_result_id(part)
        if tool_result_id:
            if tool_result_id in valid_tool_call_ids and tool_result_id in seen_tool_calls:
                filtered_parts.append(part)
            continue

        filtered_parts.append(part)

    if not filtered_parts:
        return None
    if len(filtered_parts) == len(message.parts):
        return message
    return replace(message, parts=filtered_parts)


def _tool_call_id(part: object) -> str | None:
    if isinstance(part, BaseToolCallPart):
        return part.tool_call_id
    return None


def _tool_result_id(part: object) -> str | None:
    if isinstance(part, BaseToolReturnPart):
        return part.tool_call_id
    if isinstance(part, RetryPromptPart) and part.tool_name:
        return part.tool_call_id
    return None
