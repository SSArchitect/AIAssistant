from __future__ import annotations

from .openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider — uses OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com/v1",
    ):
        super().__init__(api_key=api_key, model=model, base_url=base_url, provider_label="DeepSeek")
