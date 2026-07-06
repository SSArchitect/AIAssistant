from __future__ import annotations
import json
import logging
import os
import threading
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


def _load_yaml_config() -> dict:
    """Load config from config.yaml, searching up from agent/ to project root."""
    paths = [
        Path(__file__).parent.parent / "config" / "config.yaml",
        Path(__file__).parent / "config.yaml",
    ]
    for p in paths:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml_config()
_llm_cfg = _yaml.get("llm", {})
_providers = _llm_cfg.get("providers", {})
_aigc_cfg = _yaml.get("aigc", {})
_aigc_minimax_cfg = _aigc_cfg.get("minimax", {})
_search_cfg = _yaml.get("search", {})
_search_minimax_cfg = _search_cfg.get("minimax", {})
_search_broad_cfg = _search_cfg.get("broad_retrieval", {})
_database_cfg = _yaml.get("database", {})


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 9090

    # Shared app database
    assistant_database_path: str = _database_cfg.get("path", "./data/assistant.db")

    # LLM
    default_provider: str = _llm_cfg.get("default_provider", "claude")

    # Claude - API key from env var ANTHROPIC_API_KEY
    anthropic_api_key: str = ""
    claude_model: str = _providers.get("claude", {}).get("model", "claude-sonnet-4-20250514")

    # OpenAI - API key from env var OPENAI_API_KEY
    openai_api_key: str = ""
    openai_model: str = _providers.get("openai", {}).get("model", "gpt-4o")

    # Gemini - API key from env var GOOGLE_API_KEY
    google_api_key: str = ""
    gemini_model: str = _providers.get("gemini", {}).get("model", "gemini-2.0-flash")

    # DeepSeek - API key from env var DEEPSEEK_API_KEY
    deepseek_api_key: str = ""
    deepseek_model: str = _providers.get("deepseek", {}).get("model", "deepseek-chat")

    # Doubao - API key from env var DOUBAO_API_KEY
    doubao_api_key: str = ""
    doubao_model: str = _providers.get("doubao", {}).get("model", "doubao-1-5-pro-256k-250115")

    # MiniMax - API key from env var MINIMAX_API_KEY
    minimax_api_key: str = ""
    minimax_base_url: str = _providers.get("minimax", {}).get("base_url", "https://api.minimaxi.com/v1")
    minimax_model: str = _providers.get("minimax", {}).get("model", "MiniMax-M3")
    minimax_thinking: str = _providers.get("minimax", {}).get("thinking", "disabled")
    minimax_timeout: str = str(_providers.get("minimax", {}).get("timeout", 1800))

    # MiniMax AIGC defaults
    minimax_image_model: str = _aigc_minimax_cfg.get("image_model", "image-01")
    minimax_speech_model: str = _aigc_minimax_cfg.get("speech_model", "speech-2.8-turbo")
    minimax_voice_id: str = _aigc_minimax_cfg.get("voice_id", "male-qn-qingse")
    minimax_aigc_base_url: str = _aigc_minimax_cfg.get("base_url", "https://api.minimaxi.com")

    # Ollama
    ollama_base_url: str = _providers.get("ollama", {}).get("base_url", "http://localhost:11434")
    ollama_model: str = _providers.get("ollama", {}).get("model", "llama3")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


class RuntimeConfig:
    """Dynamic runtime configuration that can be updated via API."""

    def __init__(self):
        self._lock = threading.Lock()
        # Initialize from static settings
        self._data = {
            "llm.default_provider": settings.default_provider,
            "llm.claude.api_key": settings.anthropic_api_key,
            "llm.claude.model": settings.claude_model,
            "llm.openai.api_key": settings.openai_api_key,
            "llm.openai.model": settings.openai_model,
            "llm.openai.base_url": "",
            "llm.gemini.api_key": settings.google_api_key,
            "llm.gemini.model": settings.gemini_model,
            "llm.deepseek.api_key": settings.deepseek_api_key,
            "llm.deepseek.model": settings.deepseek_model,
            "llm.doubao.api_key": settings.doubao_api_key,
            "llm.doubao.model": settings.doubao_model,
            "llm.minimax.api_key": settings.minimax_api_key,
            "llm.minimax.base_url": settings.minimax_base_url,
            "llm.minimax.model": settings.minimax_model,
            "llm.minimax.thinking": settings.minimax_thinking,
            "llm.minimax.timeout": settings.minimax_timeout,
            "aigc.minimax.base_url": settings.minimax_aigc_base_url,
            "aigc.minimax.image_model": settings.minimax_image_model,
            "aigc.minimax.speech_model": settings.minimax_speech_model,
            "aigc.minimax.voice_id": settings.minimax_voice_id,
            "search.minimax.enabled": str(_search_minimax_cfg.get("enabled", True)).lower(),
            "search.minimax.command": _search_minimax_cfg.get("command", "uvx"),
            "search.minimax.args": json.dumps(
                _search_minimax_cfg.get("args", ["minimax-coding-plan-mcp", "-y"])
            ),
            "search.minimax.api_host": _search_minimax_cfg.get("api_host", "https://api.minimaxi.com"),
            "search.minimax.timeout": str(_search_minimax_cfg.get("timeout", 60)),
            "search.min_provider_coverage": str(_search_broad_cfg.get("min_provider_coverage", 2)),
            "search.provider_limit_multiplier": str(_search_broad_cfg.get("provider_limit_multiplier", 2)),
            "search.recall.max_queries": str(_search_broad_cfg.get("recall_max_queries", 2)),
            "search.recall.timeout_seconds": str(_search_broad_cfg.get("recall_timeout_seconds", 10)),
            "search.rerank.enabled": str(_search_broad_cfg.get("rerank_enabled", True)).lower(),
            "search.rerank.provider": str(_search_broad_cfg.get("rerank_provider", "")),
            "search.rerank.max_candidates": str(_search_broad_cfg.get("rerank_max_candidates", 10)),
            "search.rerank.timeout_seconds": str(_search_broad_cfg.get("rerank_timeout_seconds", 20)),
            "search.rerank.min_score": str(_search_broad_cfg.get("rerank_min_score", 0.5)),
            "llm.ollama.base_url": settings.ollama_base_url,
            "llm.ollama.model": settings.ollama_model,
        }

    def get(self, key: str, default: str = "") -> str:
        with self._lock:
            return self._data.get(key, default)

    def update(self, new_settings: dict[str, str]) -> None:
        with self._lock:
            for key, value in new_settings.items():
                if key.startswith(("llm.", "aigc.", "search.", "mcp.", "tool.")):
                    self._data[key] = value
        logger.info(f"Runtime config updated with {len(new_settings)} settings")

    def get_all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._data)

    @property
    def default_provider(self) -> str:
        return self.get("llm.default_provider", "claude")

    @property
    def claude_api_key(self) -> str:
        return self.get("llm.claude.api_key")

    @property
    def claude_model(self) -> str:
        return self.get("llm.claude.model", "claude-sonnet-4-20250514")

    @property
    def openai_api_key(self) -> str:
        return self.get("llm.openai.api_key")

    @property
    def openai_model(self) -> str:
        return self.get("llm.openai.model", "gpt-4o")

    @property
    def openai_base_url(self) -> str:
        return self.get("llm.openai.base_url")

    @property
    def gemini_api_key(self) -> str:
        return self.get("llm.gemini.api_key")

    @property
    def gemini_model(self) -> str:
        return self.get("llm.gemini.model", "gemini-2.0-flash")

    @property
    def deepseek_api_key(self) -> str:
        return self.get("llm.deepseek.api_key")

    @property
    def deepseek_model(self) -> str:
        return self.get("llm.deepseek.model", "deepseek-chat")

    @property
    def doubao_api_key(self) -> str:
        return self.get("llm.doubao.api_key")

    @property
    def doubao_model(self) -> str:
        return self.get("llm.doubao.model", "doubao-1-5-pro-256k-250115")

    @property
    def minimax_api_key(self) -> str:
        return self.get("llm.minimax.api_key")

    @property
    def minimax_base_url(self) -> str:
        return self.get("llm.minimax.base_url", "https://api.minimaxi.com/v1")

    @property
    def minimax_model(self) -> str:
        return self.get("llm.minimax.model", "MiniMax-M3")

    @property
    def minimax_thinking(self) -> str:
        return self.get("llm.minimax.thinking", "disabled")

    @property
    def minimax_timeout(self) -> float:
        value = self.get("llm.minimax.timeout", "1800")
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 1800.0
        return parsed if parsed > 0 else 1800.0

    @property
    def minimax_aigc_base_url(self) -> str:
        return self.get("aigc.minimax.base_url", "https://api.minimaxi.com")

    @property
    def minimax_image_model(self) -> str:
        return self.get("aigc.minimax.image_model", "image-01")

    @property
    def minimax_speech_model(self) -> str:
        return self.get("aigc.minimax.speech_model", "speech-2.8-turbo")

    @property
    def minimax_voice_id(self) -> str:
        return self.get("aigc.minimax.voice_id", "male-qn-qingse")

    @property
    def ollama_base_url(self) -> str:
        return self.get("llm.ollama.base_url", "http://localhost:11434")

    @property
    def ollama_model(self) -> str:
        return self.get("llm.ollama.model", "llama3")


runtime_config = RuntimeConfig()
