from __future__ import annotations

from typing import Any


def _message_role(message: Any) -> str:
    message_type = type(message).__name__.lower()
    if "human" in message_type:
        return "user"
    if "tool" in message_type:
        return "tool"
    if "system" in message_type:
        return "system"
    if "ai" in message_type:
        return "assistant"
    return "unknown"


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
                elif "content" in item:
                    text_parts.append(str(item.get("content", "")))
        return "\n".join(part for part in text_parts if part)
    if content is None:
        return ""
    return str(content)


def _token_usage(message: Any) -> dict[str, Any] | None:
    response_metadata = getattr(message, "response_metadata", None) or {}
    usage = response_metadata.get("token_usage") if isinstance(response_metadata, dict) else None
    if usage:
        return usage

    usage_metadata = getattr(message, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        return {
            "prompt_tokens": usage_metadata.get("input_tokens"),
            "completion_tokens": usage_metadata.get("output_tokens"),
            "total_tokens": usage_metadata.get("total_tokens"),
        }
    return None


def format_message(message: Any) -> dict[str, Any]:
    """Format a single LangChain/OpenAI-style message into a compact dict.

    Useful fields retained:
    - role, content
    - tool_calls / invalid_tool_calls / tool_call_id / tool_name
    - model/provider ids and finish reason (when present)
    - token usage
    - message id
    """

    role = _message_role(message)
    response_metadata = getattr(message, "response_metadata", None) or {}

    formatted: dict[str, Any] = {
        "role": role,
        "id": getattr(message, "id", None),
        "content": _normalize_content(getattr(message, "content", None)),
    }

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        formatted["tool_calls"] = tool_calls

    invalid_tool_calls = getattr(message, "invalid_tool_calls", None)
    if invalid_tool_calls:
        formatted["invalid_tool_calls"] = invalid_tool_calls

    tool_call_id = getattr(message, "tool_call_id", None)
    if tool_call_id:
        formatted["tool_call_id"] = tool_call_id

    tool_name = getattr(message, "name", None)
    if tool_name and role == "tool":
        formatted["tool_name"] = tool_name

    if isinstance(response_metadata, dict) and response_metadata:
        model_name = response_metadata.get("model_name")
        if model_name:
            formatted["model_name"] = model_name

        model_provider = response_metadata.get("model_provider")
        if model_provider:
            formatted["model_provider"] = model_provider

        finish_reason = response_metadata.get("finish_reason")
        if finish_reason:
            formatted["finish_reason"] = finish_reason

        openai_response_id = response_metadata.get("id")
        if openai_response_id:
            formatted["openai_response_id"] = openai_response_id

    usage = _token_usage(message)
    if usage:
        formatted["token_usage"] = usage

    content_text = formatted.get("content", "") or ""
    formatted["has_text_content"] = bool(str(content_text).strip())

    if role == "assistant":
        finish_reason = formatted.get("finish_reason")
        has_tool_calls = bool(formatted.get("tool_calls"))
        formatted["is_final_response_candidate"] = bool(
            formatted["has_text_content"]
            and not has_tool_calls
            and finish_reason in {None, "stop", "length"}
        )

    return formatted


def _extract_final_response(
    formatted_messages: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    assistant_messages = [
        message
        for message in formatted_messages
        if message.get("role") == "assistant" and message.get("has_text_content")
    ]
    if not assistant_messages:
        return None, None

    preferred = [
        message for message in assistant_messages if message.get("is_final_response_candidate")
    ]
    chosen = preferred[-1] if preferred else assistant_messages[-1]
    return chosen.get("content"), chosen.get("id")


def format_messages(
    messages: list[Any],
    *,
    as_list: bool = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Format LangChain/OpenAI-style messages and extract final assistant response.

    Args:
        messages: Raw messages returned by an agent/model call.
        as_list: If True, return only the formatted list (legacy behavior).

    Returns:
        Default (`as_list=False`):
            {
              "messages": [...],
              "has_valid_response": bool,
              "final_response": str | None,
              "final_response_message_id": str | None,
            }
        Legacy (`as_list=True`):
            [...formatted messages...]
    """

    formatted_messages = [format_message(message) for message in messages]
    if as_list:
        return formatted_messages

    final_response, final_response_message_id = _extract_final_response(formatted_messages)
    return {
        "messages": formatted_messages,
        "has_valid_response": final_response is not None,
        "final_response": final_response,
        "final_response_message_id": final_response_message_id,
    }
