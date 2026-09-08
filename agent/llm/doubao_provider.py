from __future__ import annotations

from urllib.parse import urlsplit

from .openai_provider import OpenAIProvider


# Text-generation models from the official Agent Plan catalog, checked 2026-09-08:
# https://docs.volcengine.com/docs/82379/2366394
# Plan has no OpenAI /models endpoint. This is a catalog, not account entitlements.
PLAN_MODELS = (
    "doubao-seed-2.1-turbo",
    "doubao-seed-2.0-mini",
    "doubao-seed-2.0-lite",
    "doubao-seed-evolving",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "glm-5.3-flash",
    "glm-5.3",
    "minimax-m3",
    "kimi-k2.7-code",
    "kimi-k3",
)


def is_agent_plan_url(base_url: str) -> bool:
    url = urlsplit(base_url.strip())
    return (
        url.scheme == "https"
        and url.netloc == "ark.cn-beijing.volces.com"
        and url.path.rstrip("/") == "/api/plan/v3"
        and not url.query
        and not url.fragment
    )


class DoubaoProvider(OpenAIProvider):
    """Volcengine ARK provider, retaining the existing doubao configuration key."""

    def __init__(
        self,
        api_key: str,
        model: str = "doubao-1-5-pro-256k-250115",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    ):
        super().__init__(api_key=api_key, model=model, base_url=base_url, provider_label="Volcengine")
        self.provider_name = "doubao"
