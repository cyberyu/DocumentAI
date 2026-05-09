"""
LLM configuration utilities for SurfSense agents.

This module provides functions for loading LLM configurations from:
1. Auto mode (ID 0) - Uses LiteLLM Router for load balancing
2. YAML files (global configs with negative IDs)
3. Database NewLLMConfig table (user-created configs with positive IDs)

It also provides utilities for creating ChatLiteLLM instances and
managing prompt configurations.
"""

import json as _json
import re as _re
import uuid as _uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages.tool import ToolCallChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_litellm import ChatLiteLLM
from litellm import get_model_info
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_router_service import (
    AUTO_MODE_ID,
    ChatLiteLLMRouter,
    LLMRouterService,
    _sanitize_content,
    get_auto_mode_llm,
    is_auto_mode,
)


# Keys in AIMessage.additional_kwargs that some providers (e.g. DeepSeek) return
# as part of reasoning/thinking responses and REQUIRE to be echoed back verbatim
# in subsequent API turns.  langchain_litellm's _convert_message_to_dict does not
# include these by default, so SanitizedChatLiteLLM._create_message_dicts injects
# them back.  Add provider-specific keys here as needed.
_REASONING_PASSTHROUGH_KWARGS: frozenset[str] = frozenset(
    ["reasoning_content"]
)


def _clone_message(msg: BaseMessage) -> BaseMessage:
    """Return a deep copy of a message compatible with pydantic v1/v2."""
    if hasattr(msg, "model_copy"):
        return msg.model_copy(deep=True)  # type: ignore[call-arg]
    if hasattr(msg, "copy"):
        return msg.copy(deep=True)  # type: ignore[call-arg]
    return msg


def _extract_reasoning_content_from_blocks(content: Any) -> str | None:
    """Extract DeepSeek reasoning text from assistant content blocks."""
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "thinking":
            thinking = block.get("thinking")
            if isinstance(thinking, str) and thinking.strip():
                parts.append(thinking)

    if not parts:
        return None
    merged = "".join(parts).strip()
    return merged or None


# ---------------------------------------------------------------------------
# Text-form tool call parsing (for models like Gemma 4 via vLLM pythonic parser)
#
# vLLM with --tool-call-parser pythonic returns tool calls as text content in
# the deepagents format: call:funcname{key:val, key2:val2}
# LangChain needs proper tool_calls on the AIMessage to route to the tool node.
# ---------------------------------------------------------------------------

# Matches: [thought\n]call:funcname{key:val, key2:val2}
_TEXT_TOOL_CALL_RE = _re.compile(
    r"(?:thought\s+)?call:([a-zA-Z_][a-zA-Z0-9_]*)\{([^}]*)\}",
    _re.MULTILINE,
)


def _parse_deepagents_call_args(args_str: str) -> dict:
    """Parse 'key1:val1, key2:val2' deepagents call format into a dict.

    Values may contain colons (e.g. file paths), so we split on ', identifier:'
    boundaries rather than any comma.
    """
    result: dict[str, str] = {}
    parts = _re.split(r",\s*(?=[a-zA-Z_]\w*:)", args_str)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        colon_idx = part.find(":")
        if colon_idx == -1:
            continue
        key = part[:colon_idx].strip()
        value = part[colon_idx + 1 :].strip()
        if key:
            result[key] = value
    return result


def _patch_ai_message_text_tool_calls(msg: AIMessage) -> AIMessage:
    """If *msg* has no structured tool_calls but its content contains
    call:funcname{...} patterns, convert them to proper tool_calls.

    Returns the original message unchanged if no patching is needed.
    """
    if msg.tool_calls:
        return msg
    content = msg.content
    if not isinstance(content, str):
        return msg
    matches = list(_TEXT_TOOL_CALL_RE.finditer(content))
    if not matches:
        return msg

    tool_calls = [
        {
            "id": f"call_{_uuid.uuid4().hex[:12]}",
            "name": m.group(1),
            "args": _parse_deepagents_call_args(m.group(2)),
            "type": "tool_call",
        }
        for m in matches
    ]

    # Strip the tool call patterns (and orphaned "thought" lines) from content.
    remaining = _TEXT_TOOL_CALL_RE.sub("", content)
    remaining = _re.sub(r"^thought\s*$", "", remaining, flags=_re.MULTILINE).strip()

    return AIMessage(
        content=remaining or "",
        tool_calls=tool_calls,  # type: ignore[arg-type]
        additional_kwargs=msg.additional_kwargs or {},
        response_metadata=getattr(msg, "response_metadata", {}) or {},
    )


def _sanitize_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Return sanitized message copies safe for provider serialization.

    Handles three cross-provider incompatibilities:
    - List content with provider-specific blocks (e.g. ``thinking``)
    - List content with bare strings or empty text blocks
    - AI messages with empty content + tool calls: some providers (Bedrock)
      convert ``""`` to ``[{"type":"text","text":""}]`` server-side then
      reject the blank text.  The OpenAI spec says ``content`` should be
      ``null`` when an assistant message only carries tool calls.
    """
    sanitized: list[BaseMessage] = []
    for original in messages:
        msg = _clone_message(original)
        if isinstance(msg.content, list):
            msg.content = _sanitize_content(msg.content)
        if (
            isinstance(msg, AIMessage)
            and (not msg.content or msg.content == "")
            and getattr(msg, "tool_calls", None)
        ):
            msg.content = None  # type: ignore[assignment]
        sanitized.append(msg)
    return sanitized


class SanitizedChatLiteLLM(ChatLiteLLM):
    """ChatLiteLLM subclass that strips provider-specific content blocks
    (e.g. ``thinking`` from reasoning models) and normalises bare strings
    in content arrays before forwarding to the underlying provider.

    Also rescues provider reasoning passthrough fields (e.g. ``reasoning_content``
    for DeepSeek) that langchain_litellm's _convert_message_to_dict silently
    drops from AIMessage.additional_kwargs when serializing conversation history
    for multi-turn calls.
    """

    def _create_message_dicts(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None,
    ) -> tuple[list[dict], dict]:
        sanitized_messages = _sanitize_messages(messages)
        message_dicts, params = super()._create_message_dicts(
            sanitized_messages, stop
        )
        # langchain_litellm's _convert_message_to_dict drops extra fields like
        # reasoning_content from additional_kwargs.  DeepSeek requires these to
        # be echoed back verbatim in subsequent turns or it raises:
        #   "reasoning_content in thinking mode must be passed back to the API"
        # Rescue them here by copying from the original unsanitized AIMessage.
        for msg, msg_dict in zip(messages, message_dicts):
            if isinstance(msg, AIMessage):
                extra = getattr(msg, "additional_kwargs", {}) or {}
                for key in _REASONING_PASSTHROUGH_KWARGS:
                    if key in extra and extra[key]:
                        msg_dict[key] = extra[key]
                if "reasoning_content" not in msg_dict:
                    inferred = _extract_reasoning_content_from_blocks(msg.content)
                    if inferred:
                        msg_dict["reasoning_content"] = inferred
                if (
                    "reasoning_content" not in msg_dict
                    and msg_dict.get("tool_calls")
                ):
                    # Last-resort guardrail for providers that require this key.
                    # Some streaming paths lose the original value upstream.
                    msg_dict["reasoning_content"] = "[missing_reasoning_content]"
        return message_dicts, params

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        result = super()._generate(messages, stop, run_manager, **kwargs)
        # Patch text-form tool calls (e.g. Gemma 4 via vLLM pythonic parser).
        patched_gens = []
        for gen in result.generations:
            msg = getattr(gen, "message", None)
            if isinstance(msg, AIMessage):
                patched = _patch_ai_message_text_tool_calls(msg)
                if patched is not msg:
                    gen = ChatGeneration(
                        message=patched,
                        text=patched.content if isinstance(patched.content, str) else "",
                    )
            patched_gens.append(gen)
        result.generations[:] = patched_gens
        return result

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        # Buffer all chunks so we can detect text-form tool calls.
        # If text-form calls are found we SUPPRESS the original text content
        # (so it never reaches text-delta events / benchmark collection) and
        # emit a synthetic chunk with proper tool_call_chunks instead.
        chunks: list[ChatGenerationChunk] = []
        has_structured = False
        accumulated = ""

        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            chunks.append(chunk)
            msg_chunk = getattr(chunk, "message", None)
            if isinstance(msg_chunk, AIMessageChunk):
                if getattr(msg_chunk, "tool_call_chunks", None):
                    has_structured = True
                if isinstance(msg_chunk.content, str):
                    accumulated += msg_chunk.content

        # If already has structured tool calls, yield unchanged.
        if has_structured or not accumulated:
            for chunk in chunks:
                yield chunk
            return

        matches = list(_TEXT_TOOL_CALL_RE.finditer(accumulated))

        if not matches:
            # Normal text response — yield as-is.
            for chunk in chunks:
                yield chunk
            return

        # Text-form tool calls detected:
        # 1. Yield each chunk but blank out any text content (suppress call: text
        #    so it never appears as a text-delta event).
        # 2. Append a synthetic chunk carrying the structured tool_call_chunks.
        for chunk in chunks:
            msg_chunk = getattr(chunk, "message", None)
            if isinstance(msg_chunk, AIMessageChunk) and isinstance(msg_chunk.content, str) and msg_chunk.content:
                yield ChatGenerationChunk(message=AIMessageChunk(content=""))
            else:
                yield chunk

        tc_chunks = [
            ToolCallChunk(
                id=f"call_{_uuid.uuid4().hex[:12]}",
                name=m.group(1),
                args=_json.dumps(_parse_deepagents_call_args(m.group(2))),
                index=i,
            )
            for i, m in enumerate(matches)
        ]
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", tool_call_chunks=tc_chunks)
        )


# Provider mapping for LiteLLM model string construction
PROVIDER_MAP = {
    "OPENAI": "openai",
    "ANTHROPIC": "anthropic",
    "GROQ": "groq",
    "COHERE": "cohere",
    "GOOGLE": "gemini",
    "OLLAMA": "ollama_chat",
    "MISTRAL": "mistral",
    "AZURE_OPENAI": "azure",
    "OPENROUTER": "openrouter",
    "XAI": "xai",
    "BEDROCK": "bedrock",
    "VERTEX_AI": "vertex_ai",
    "TOGETHER_AI": "together_ai",
    "FIREWORKS_AI": "fireworks_ai",
    "DEEPSEEK": "openai",
    "ALIBABA_QWEN": "openai",
    "MOONSHOT": "openai",
    "ZHIPU": "openai",
    "GITHUB_MODELS": "github",
    "REPLICATE": "replicate",
    "PERPLEXITY": "perplexity",
    "ANYSCALE": "anyscale",
    "DEEPINFRA": "deepinfra",
    "CEREBRAS": "cerebras",
    "SAMBANOVA": "sambanova",
    "AI21": "ai21",
    "CLOUDFLARE": "cloudflare",
    "DATABRICKS": "databricks",
    "COMETAPI": "cometapi",
    "HUGGINGFACE": "huggingface",
    "MINIMAX": "openai",
    "CUSTOM": "custom",
}


def _attach_model_profile(llm: ChatLiteLLM, model_string: str) -> None:
    """Attach a ``profile`` dict to ChatLiteLLM with model context metadata."""
    try:
        info = get_model_info(model_string)
        max_input_tokens = info.get("max_input_tokens")
        if isinstance(max_input_tokens, int) and max_input_tokens > 0:
            llm.profile = {
                "max_input_tokens": max_input_tokens,
                "max_input_tokens_upper": max_input_tokens,
                "token_count_model": model_string,
                "token_count_models": [model_string],
            }
    except Exception:
        return


@dataclass
class AgentConfig:
    """
    Complete configuration for the SurfSense agent.

    This combines LLM settings with prompt configuration from NewLLMConfig.
    Supports Auto mode (ID 0) which uses LiteLLM Router for load balancing.
    """

    # LLM Model Settings
    provider: str
    model_name: str
    api_key: str
    api_base: str | None = None
    custom_provider: str | None = None
    litellm_params: dict | None = None

    # Prompt Configuration
    system_instructions: str | None = None
    use_default_system_instructions: bool = True
    citations_enabled: bool = True

    # Metadata
    config_id: int | None = None
    config_name: str | None = None

    # Auto mode flag
    is_auto_mode: bool = False

    # Token quota and policy
    billing_tier: str = "free"
    is_premium: bool = False
    anonymous_enabled: bool = False
    quota_reserve_tokens: int | None = None

    @classmethod
    def from_auto_mode(cls) -> "AgentConfig":
        """
        Create an AgentConfig for Auto mode (LiteLLM Router load balancing).

        Returns:
            AgentConfig instance configured for Auto mode
        """
        return cls(
            provider="AUTO",
            model_name="auto",
            api_key="",  # Not needed for router
            api_base=None,
            custom_provider=None,
            litellm_params=None,
            system_instructions=None,
            use_default_system_instructions=True,
            citations_enabled=True,
            config_id=AUTO_MODE_ID,
            config_name="Auto (Fastest)",
            is_auto_mode=True,
            billing_tier="free",
            is_premium=False,
            anonymous_enabled=False,
            quota_reserve_tokens=None,
        )

    @classmethod
    def from_new_llm_config(cls, config) -> "AgentConfig":
        """
        Create an AgentConfig from a NewLLMConfig database model.

        Args:
            config: NewLLMConfig database model instance

        Returns:
            AgentConfig instance
        """
        # For Qwen3 models, prepend /nothink to disable chain-of-thought in the
        # system prompt so the model emits clean tool calls without leaking reasoning.
        system_instructions = config.system_instructions
        model_name_lower = (config.model_name or "").lower()
        if "qwen3" in model_name_lower or "qwen/qwen3" in model_name_lower:
            from app.agents.new_chat.system_prompt import SURFSENSE_SYSTEM_INSTRUCTIONS
            base = (system_instructions or "").strip() or SURFSENSE_SYSTEM_INSTRUCTIONS.strip()
            if not base.startswith("/nothink"):
                # /nothink disables chain-of-thought for Qwen3.
                # The search cap instruction prevents infinite tool loops.
                system_instructions = (
                    "/nothink\n\n"
                    "IMPORTANT RULE: Call search_documents at most 8 times per question. "
                    "After gathering results from up to 8 searches, you MUST stop searching "
                    "and write your final answer based on what you found. "
                    "Do not keep searching indefinitely.\n\n"
                    + base
                )

        return cls(
            provider=config.provider.value
            if hasattr(config.provider, "value")
            else str(config.provider),
            model_name=config.model_name,
            api_key=config.api_key,
            api_base=config.api_base,
            custom_provider=config.custom_provider,
            litellm_params=config.litellm_params,
            system_instructions=system_instructions,
            use_default_system_instructions=config.use_default_system_instructions,
            citations_enabled=config.citations_enabled,
            config_id=config.id,
            config_name=config.name,
            is_auto_mode=False,
            billing_tier="free",
            is_premium=False,
            anonymous_enabled=False,
            quota_reserve_tokens=None,
        )

    @classmethod
    def from_yaml_config(cls, yaml_config: dict) -> "AgentConfig":
        """
        Create an AgentConfig from a YAML configuration dictionary.

        YAML configs now support the same prompt configuration fields as NewLLMConfig:
        - system_instructions: Custom system instructions (empty string uses defaults)
        - use_default_system_instructions: Whether to use default instructions
        - citations_enabled: Whether citations are enabled

        Args:
            yaml_config: Configuration dictionary from YAML file

        Returns:
            AgentConfig instance
        """
        # Get system instructions from YAML, default to empty string
        system_instructions = yaml_config.get("system_instructions", "")

        return cls(
            provider=yaml_config.get("provider", "").upper(),
            model_name=yaml_config.get("model_name", ""),
            api_key=yaml_config.get("api_key", ""),
            api_base=yaml_config.get("api_base"),
            custom_provider=yaml_config.get("custom_provider"),
            litellm_params=yaml_config.get("litellm_params"),
            # Prompt configuration from YAML (with defaults for backwards compatibility)
            system_instructions=system_instructions if system_instructions else None,
            use_default_system_instructions=yaml_config.get(
                "use_default_system_instructions", True
            ),
            citations_enabled=yaml_config.get("citations_enabled", True),
            config_id=yaml_config.get("id"),
            config_name=yaml_config.get("name"),
            is_auto_mode=False,
            billing_tier=yaml_config.get("billing_tier", "free"),
            is_premium=yaml_config.get("billing_tier", "free") == "premium",
            anonymous_enabled=yaml_config.get("anonymous_enabled", False),
            quota_reserve_tokens=yaml_config.get("quota_reserve_tokens"),
        )


def load_llm_config_from_yaml(llm_config_id: int = -1) -> dict | None:
    """
    Load a specific LLM config from global_llm_config.yaml.

    Args:
        llm_config_id: The id of the config to load (default: -1)

    Returns:
        LLM config dict or None if not found
    """
    # Get the config file path
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    config_file = base_dir / "app" / "config" / "global_llm_config.yaml"

    # Fallback to example file if main config doesn't exist
    if not config_file.exists():
        config_file = base_dir / "app" / "config" / "global_llm_config.example.yaml"
        if not config_file.exists():
            print("Error: No global_llm_config.yaml or example file found")
            return None

    try:
        with open(config_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            configs = data.get("global_llm_configs", [])
            for cfg in configs:
                if isinstance(cfg, dict) and cfg.get("id") == llm_config_id:
                    return cfg

            print(f"Error: Global LLM config id {llm_config_id} not found")
            return None
    except Exception as e:
        print(f"Error loading config: {e}")
        return None


def load_global_llm_config_by_id(llm_config_id: int) -> dict | None:
    """
    Load a global LLM config by ID, checking in-memory configs first.

    This handles both static YAML configs and dynamically injected configs
    (e.g. OpenRouter integration models that only exist in memory).

    Args:
        llm_config_id: The negative ID of the global config to load

    Returns:
        LLM config dict or None if not found
    """
    from app.config import config as app_config

    for cfg in app_config.GLOBAL_LLM_CONFIGS:
        if cfg.get("id") == llm_config_id:
            return cfg
    # Fallback to YAML file read (covers edge cases like hot-reload)
    return load_llm_config_from_yaml(llm_config_id)


async def load_new_llm_config_from_db(
    session: AsyncSession,
    config_id: int,
) -> "AgentConfig | None":
    """
    Load a NewLLMConfig from the database by ID.

    Args:
        session: AsyncSession for database access
        config_id: The ID of the NewLLMConfig to load

    Returns:
        AgentConfig instance or None if not found
    """
    # Import here to avoid circular imports
    from app.db import NewLLMConfig

    try:
        result = await session.execute(
            select(NewLLMConfig).filter(NewLLMConfig.id == config_id)
        )
        config = result.scalars().first()

        if not config:
            print(f"Error: NewLLMConfig with id {config_id} not found")
            return None

        return AgentConfig.from_new_llm_config(config)
    except Exception as e:
        print(f"Error loading NewLLMConfig from database: {e}")
        return None


async def load_agent_llm_config_for_search_space(
    session: AsyncSession,
    search_space_id: int,
) -> "AgentConfig | None":
    """
    Load the agent LLM configuration for a search space.

    This loads the LLM config based on the search space's agent_llm_id setting:
    - Positive ID: Load from NewLLMConfig database table
    - Negative ID: Load from YAML global configs
    - None: Falls back to first global config (id=-1)

    Args:
        session: AsyncSession for database access
        search_space_id: The search space ID

    Returns:
        AgentConfig instance or None if not found
    """
    # Import here to avoid circular imports
    from app.db import SearchSpace

    try:
        # Get the search space to check its agent_llm_id preference
        result = await session.execute(
            select(SearchSpace).filter(SearchSpace.id == search_space_id)
        )
        search_space = result.scalars().first()

        if not search_space:
            print(f"Error: SearchSpace with id {search_space_id} not found")
            return None

        # Use agent_llm_id from search space, fallback to -1 (first global config)
        config_id = (
            search_space.agent_llm_id if search_space.agent_llm_id is not None else -1
        )

        # Load the config using the unified loader
        return await load_agent_config(session, config_id, search_space_id)
    except Exception as e:
        print(f"Error loading agent LLM config for search space {search_space_id}: {e}")
        return None


async def load_agent_config(
    session: AsyncSession,
    config_id: int,
    search_space_id: int | None = None,
) -> "AgentConfig | None":
    """
    Load an agent configuration, supporting Auto mode, YAML, and database configs.

    This is the main entry point for loading configurations:
    - ID 0: Auto mode (uses LiteLLM Router for load balancing)
    - Negative IDs: Load from YAML file (global configs)
    - Positive IDs: Load from NewLLMConfig database table

    Args:
        session: AsyncSession for database access
        config_id: The config ID (0 for Auto, negative for YAML, positive for database)
        search_space_id: Optional search space ID for context

    Returns:
        AgentConfig instance or None if not found
    """
    # Auto mode (ID 0) - use LiteLLM Router
    if is_auto_mode(config_id):
        if not LLMRouterService.is_initialized():
            print("Error: Auto mode requested but LLM Router not initialized")
            return None
        return AgentConfig.from_auto_mode()

    if config_id < 0:
        # Check in-memory configs first (includes static YAML + dynamic OpenRouter)
        from app.config import config as app_config

        for cfg in app_config.GLOBAL_LLM_CONFIGS:
            if cfg.get("id") == config_id:
                return AgentConfig.from_yaml_config(cfg)
        # Fallback to YAML file read for safety
        yaml_config = load_llm_config_from_yaml(config_id)
        if yaml_config:
            return AgentConfig.from_yaml_config(yaml_config)
        return None
    else:
        # Load from database (NewLLMConfig)
        return await load_new_llm_config_from_db(session, config_id)


def create_chat_litellm_from_config(llm_config: dict) -> ChatLiteLLM | None:
    """
    Create a ChatLiteLLM instance from a global LLM config dictionary.

    Args:
        llm_config: LLM configuration dictionary from YAML

    Returns:
        ChatLiteLLM instance or None on error
    """
    # Build the model string
    if llm_config.get("custom_provider"):
        model_string = f"{llm_config['custom_provider']}/{llm_config['model_name']}"
    else:
        provider = llm_config.get("provider", "").upper()
        provider_prefix = PROVIDER_MAP.get(provider, provider.lower())
        model_string = f"{provider_prefix}/{llm_config['model_name']}"

    # Create ChatLiteLLM instance with streaming enabled
    litellm_kwargs = {
        "model": model_string,
        "api_key": llm_config.get("api_key"),
        "streaming": True,  # Enable streaming for real-time token streaming
    }

    # Add optional parameters
    if llm_config.get("api_base"):
        litellm_kwargs["api_base"] = llm_config["api_base"]

    # Add any additional litellm parameters
    if llm_config.get("litellm_params"):
        litellm_kwargs.update(llm_config["litellm_params"])

    llm = SanitizedChatLiteLLM(**litellm_kwargs)
    _attach_model_profile(llm, model_string)
    return llm


def create_chat_litellm_from_agent_config(
    agent_config: AgentConfig,
) -> ChatLiteLLM | ChatLiteLLMRouter | None:
    """
    Create a ChatLiteLLM or ChatLiteLLMRouter instance from an AgentConfig.

    For Auto mode configs, returns a ChatLiteLLMRouter that uses LiteLLM Router
    for automatic load balancing across available providers.

    Args:
        agent_config: AgentConfig instance

    Returns:
        ChatLiteLLM or ChatLiteLLMRouter instance, or None on error
    """
    # Handle Auto mode - return ChatLiteLLMRouter
    if agent_config.is_auto_mode:
        if not LLMRouterService.is_initialized():
            print("Error: Auto mode requested but LLM Router not initialized")
            return None
        try:
            return get_auto_mode_llm()
        except Exception as e:
            print(f"Error creating ChatLiteLLMRouter: {e}")
            return None

    # Build the model string
    if agent_config.custom_provider:
        model_string = f"{agent_config.custom_provider}/{agent_config.model_name}"
    else:
        provider_prefix = PROVIDER_MAP.get(
            agent_config.provider, agent_config.provider.lower()
        )
        model_string = f"{provider_prefix}/{agent_config.model_name}"

    # Create ChatLiteLLM instance with streaming enabled
    litellm_kwargs = {
        "model": model_string,
        "api_key": agent_config.api_key,
        "streaming": True,  # Enable streaming for real-time token streaming
    }

    # Add optional parameters
    if agent_config.api_base:
        litellm_kwargs["api_base"] = agent_config.api_base

    # Add any additional litellm parameters
    if agent_config.litellm_params:
        litellm_kwargs.update(agent_config.litellm_params)

    llm = SanitizedChatLiteLLM(**litellm_kwargs)
    _attach_model_profile(llm, model_string)
    return llm
