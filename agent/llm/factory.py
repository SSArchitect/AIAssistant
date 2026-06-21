from __future__ import annotations
from .base import LLMProvider
from .claude_provider import ClaudeProvider
from .deepseek_provider import DeepSeekProvider
from .doubao_provider import DoubaoProvider
from .gemini_provider import GeminiProvider
from .minimax_provider import MiniMaxProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider
from agent.config import runtime_config


def create_provider(name: str | None = None) -> LLMProvider:
    """Create an LLM provider by name. Defaults to the configured default.

    Supports "provider:model" format to override the model, e.g. "doubao:doubao-seed-2-0-pro-260215".
    """
    provider_name = name or runtime_config.default_provider
    model_override = None

    # Support "provider:model" format
    if provider_name and ':' in provider_name:
        provider_name, model_override = provider_name.split(':', 1)

    if provider_name == "claude":
        return ClaudeProvider(
            api_key=runtime_config.claude_api_key,
            model=model_override or runtime_config.claude_model,
        )
    elif provider_name == "openai":
        return OpenAIProvider(
            api_key=runtime_config.openai_api_key,
            model=model_override or runtime_config.openai_model,
            base_url=runtime_config.openai_base_url or None,
        )
    elif provider_name == "gemini":
        return GeminiProvider(
            api_key=runtime_config.gemini_api_key,
            model=model_override or runtime_config.gemini_model,
        )
    elif provider_name == "deepseek":
        return DeepSeekProvider(
            api_key=runtime_config.deepseek_api_key,
            model=model_override or runtime_config.deepseek_model,
        )
    elif provider_name == "doubao":
        return DoubaoProvider(
            api_key=runtime_config.doubao_api_key,
            model=model_override or runtime_config.doubao_model,
        )
    elif provider_name == "minimax":
        return MiniMaxProvider(
            api_key=runtime_config.minimax_api_key,
            model=model_override or runtime_config.minimax_model,
            base_url=runtime_config.minimax_base_url,
            thinking=runtime_config.minimax_thinking,
        )
    elif provider_name == "ollama":
        return OllamaProvider(
            model=model_override or runtime_config.ollama_model,
            base_url=runtime_config.ollama_base_url,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
