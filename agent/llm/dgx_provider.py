from __future__ import annotations

from .openai_provider import OpenAIProvider


class DGXSparkProvider(OpenAIProvider):
    """OpenAI-compatible models served from the local DGX Spark gateway."""

    def __init__(
        self,
        api_key: str,
        model: str = "huihui-qwen38-27b-q6xl",
        base_url: str = "https://sleeve-sizes-col-salmon.trycloudflare.com/v1",
        max_tokens: int = 10000,
        streaming_enabled: bool = True,
        timeout_seconds: float | None = 1800,
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            provider_label="DGX Spark",
            max_tokens=max_tokens,
            streaming_enabled=streaming_enabled,
            supports_streaming_tool_calls=True,
        )
        self.provider_name = "dgx"

    def _extra_chat_kwargs(self, *, thinking_enabled: bool | None = None) -> dict:
        if thinking_enabled is None:
            return {}
        return {
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": thinking_enabled,
                },
            },
        }
