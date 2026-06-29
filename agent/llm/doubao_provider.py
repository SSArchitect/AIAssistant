from __future__ import annotations

from .openai_provider import OpenAIProvider


class DoubaoProvider(OpenAIProvider):
    """Doubao (豆包) provider — uses Volcengine ARK OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str = "doubao-1-5-pro-256k-250115",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    ):
        super().__init__(api_key=api_key, model=model, base_url=base_url, provider_label="Doubao")
