from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
import logging
import re
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from agent.aigc import (
    MiniMaxAIGCClient,
    apply_text_rendering_guard,
    build_share_card_summary,
    build_structured_share_card_brief,
    is_text_heavy_visual_intent,
    render_share_card_svg,
)
from agent.llm.base import LLMMessage, LLMProvider, LLMResponse, RateLimitError, ToolCall, ToolDefinition
from agent.llm.base import PromptCacheOptions
from agent.llm.factory import create_provider
from agent.memory.conversation import ConversationMemory
from agent.memory.hooks import HeuristicMemoryHook, MemoryHook
from agent.memory.rendering import render_memory_context
from agent.memory.role_store import RoleMemoryStore
from agent.orchestrator.context_builder import ContextBuilder
from agent.runtime.registry import get_agent, list_agents
from agent.schemas.agent import AgentInfo
from agent.schemas.aigc import IMAGE_ASPECT_RATIOS, GeneratedImage, ImageGenerationRequest, ImageGenerationResponse
from agent.schemas.chat import ChatArtifact, ChatAttachment, ChatRequest, ChatResponse, Citation, SkillCallInfo
from agent.schemas.handoff import (
    AGENT_INPUT_PROTOCOL_VERSION,
    AgentHandoffAttachment,
    AgentHandoffMessage,
    AgentHandoffPacket,
    AgentStageContext,
)
from agent.schemas.memory import MemoryCandidate, MemoryContext, MemoryRecord, MemoryUpdateRequest
from agent.search import extract_public_http_urls
from agent.skills.base import SkillResult
from agent.skills.governance import ToolGovernance
from agent.skills.registry import SkillRegistry
from agent.skills.builtin.agent_tool import AgentToolSkill
from agent.skills.builtin.drive import DRIVE_TOOL_NAMES
from agent.skills.builtin.pulse import PULSE_TOOL_NAMES
from agent.skills.builtin.todo import TODO_TOOL_NAMES
from agent.trace import TraceStore
from agent.weight_loss import WeightLossStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个可靠、友好的个人助手，可以使用已接入的工具/技能帮助用户完成任务。

当用户提出请求时，先判断是否有工具能提供更准确或更及时的帮助；需要时主动使用工具，不需要时直接基于已有上下文回答。

如果用户提供明确的 http/https URL，需要读取该页面时优先直接调用 open_url；不要把完整 URL 当作普通搜索关键词。

默认使用中文回答，除非用户明确要求英文或其他语言。回答要简洁、清楚、有帮助。使用工具后，简要说明你做了什么，并清晰呈现结果。"""

MAX_MODEL_ROUNDS = 12
MAX_TOOL_ROUNDS = MAX_MODEL_ROUNDS
MAX_TOOL_CALLS = 48
MAX_FAILED_TOOL_CALLS = 12
PARALLEL_READ_ONLY_TOOL_NAMES = {"search", "open_url"}
MAX_PARALLEL_READ_ONLY_TOOL_CALLS = 4
MODEL_RETRY_MAX_ATTEMPTS = 3
MODEL_RETRY_DELAYS_SECONDS = (0.5, 1.5)
CONVERSATION_COMPACTION_THRESHOLD = 40
CONVERSATION_COMPACTION_KEEP_MESSAGES = 12
CONVERSATION_COMPACTION_MAX_MESSAGES = 80
SUPER_CHAT_AGENT_ID = "super_chat"
RESEARCH_AGENT_ID = "deep_research_v1"
AIGC_AGENT_ID = "image_generation_v1"
WEIGHT_LOSS_AGENT_ID = "weight_loss_v1"
AGENT_LOOP_MODE_ID = "agent_loop"
GENERIC_TOOL_LOOP_WORKFLOW = "generic_tool_loop"
DEEP_RESEARCH_MODE_ID = "deep_research"
REMOVED_SUPER_CHAT_MODE_IDS = {"thinking"}
AIGC_REFINE_MODE_ID = "image_prompt_refine"
AIGC_RESEARCH_MODE_IDS = {"research", "plan"}
AIGC_RESEARCH_TOOL_ROUNDS = 8
AIGC_RESEARCH_SEARCH_LIMIT = 12
AIGC_RESEARCH_SEARCH_MAX_LIMIT = 20
DEEP_RESEARCH_PLAN_MARKER = "<!-- deep_research_plan_v1 -->"
DEEP_RESEARCH_DEFAULT_TARGET_RESULTS = 400
DEEP_RESEARCH_SEARCH_LIMIT = 20
DEEP_RESEARCH_MAX_QUERIES = 24
DEEP_RESEARCH_SUMMARY_CHUNK_SIZE = 40
DEEP_RESEARCH_REPORT_FOLDER_PATH = "/研究报告"
DEEP_RESEARCH_SUPPLEMENTAL_MAX_ROUNDS = 2
DEEP_RESEARCH_SUPPLEMENTAL_MAX_QUERIES = 6
DEEP_RESEARCH_SUPPLEMENTAL_MIN_NEW_SOURCES = 2
THINKING_MAX_PLAN_STEPS = 6
THINKING_SEARCH_LIMIT = 8
THINKING_MAX_SEARCH_STEPS = 4
SUPER_CHAT_AUTO_SEARCH_LIMIT = 10
THINKING_WORKFLOW_NODES = ["analyze", "plan", "execute", "summary"]
AIGC_PLAN_DECOMPOSE_STEP = "task_decomposition"
AIGC_PLAN_CONTEXT_STEP = "context_reuse"
AIGC_PLAN_RETRIEVAL_STEP = "retrieval"
AIGC_PLAN_IMAGE_STEP = "image_generation"
AIGC_PLAN_SUMMARY_STEP = "final_summary"
AIGC_INFORMATION_STRATEGIES = {"direct", "reuse_context", "retrieve", "clarify"}
AIGC_BRIEF_FORMATS = {"none", "markdown", "structured"}
AIGC_GENERATE_COMMANDS = {"generate", "gen", "create", "draw", "image", "生成", "生图", "画图", "画"}
AIGC_REFINE_COMMANDS = {"refine", "polish", "prompt", "rewrite", "修饰", "润色", "专业修饰", "提示词", "优化"}
AIGC_REFERENCE_COMMANDS = {"reference", "references", "ref", "素材", "参考", "参考素材", "参考图"}
AIGC_HELP_COMMANDS = {"help", "h", "?", "帮助", "命令"}
AGENT_TOOL_IDS = {AIGC_AGENT_ID, WEIGHT_LOSS_AGENT_ID}
WEIGHT_LOSS_ANALYSIS_MAX_ATTEMPTS = 5
WEIGHT_LOSS_ANALYSIS_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0, 20.0)


def _safe_trace_node_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    normalized = normalized.strip("_")
    return normalized or "node"


def _trace_status_suffix(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"error", "failed", "failure"}:
        return "failed"
    if normalized in {"partial", "timed_out", "timeout"}:
        return "partial"
    return "completed"


@dataclass
class _AgentLoopToolExecution:
    tool_call: ToolCall
    tool_arguments: dict[str, Any]
    result_text: str
    status: str
    duration_ms: int
    result_data: Any = None


class AgentEngine:
    def __init__(
        self,
        skill_registry: SkillRegistry,
        trace_store: TraceStore | None = None,
        role_memory: RoleMemoryStore | None = None,
        memory_hook: MemoryHook | None = None,
        ai_memory_review_enabled: bool = False,
        conversation_compaction_threshold: int = CONVERSATION_COMPACTION_THRESHOLD,
        conversation_compaction_keep_messages: int = CONVERSATION_COMPACTION_KEEP_MESSAGES,
        weight_loss_store: WeightLossStore | None = None,
    ):
        self.skill_registry = skill_registry
        self._ensure_system_tools_registered()
        self.memory = ConversationMemory(max_messages=CONVERSATION_COMPACTION_MAX_MESSAGES)
        self.role_memory = role_memory or RoleMemoryStore()
        self.memory_hook = memory_hook or HeuristicMemoryHook()
        self.ai_memory_review_enabled = ai_memory_review_enabled
        self.conversation_compaction_threshold = conversation_compaction_threshold
        self.conversation_compaction_keep_messages = conversation_compaction_keep_messages
        self.trace_store = trace_store or TraceStore()
        self.tool_governance = ToolGovernance(self.trace_store)
        self.weight_loss_store = weight_loss_store or WeightLossStore()
        self.context_builder = ContextBuilder(base_system_prompt=SYSTEM_PROMPT)
        self._providers: dict[str, LLMProvider] = {}
        self._postprocess_tasks: set[asyncio.Task[None]] = set()

    def _ensure_system_tools_registered(self) -> None:
        for agent in list_agents():
            if agent.id in AGENT_TOOL_IDS and self.skill_registry.get(agent.id) is None:
                self.skill_registry.register(AgentToolSkill(agent))

    def clear_providers(self) -> None:
        """Clear cached providers so they get recreated with new config."""
        self._providers.clear()
        logger.info("Provider cache cleared")

    def _get_provider(self, name: str | None = None) -> LLMProvider:
        key = name or "default"
        if key not in self._providers:
            self._providers[key] = create_provider(name)
        return self._providers[key]

    def _provider_cache_key(self, model_preference: str | None) -> str:
        return model_preference or "default"

    def _is_transient_model_error(self, error: Exception) -> bool:
        if isinstance(error, RateLimitError):
            return False
        if isinstance(error, (TimeoutError, ConnectionError, OSError)):
            return True
        error_type = type(error).__name__.lower()
        error_module = type(error).__module__.lower()
        if any(
            marker in error_type
            for marker in (
                "connection",
                "connect",
                "disconnect",
                "timeout",
                "readtimeout",
                "remoteprotocol",
                "protocolerror",
                "network",
            )
        ):
            return True
        if any(marker in error_module for marker in ("httpx", "httpcore")):
            return True
        message = " ".join(str(error).lower().split())
        return any(
            marker in message
            for marker in (
                "connection error",
                "connection reset",
                "connection aborted",
                "server disconnected",
                "remote protocol",
                "timed out",
                "timeout",
                "read timeout",
                "connect timeout",
                "network error",
                "endofstream",
            )
        )

    def _model_retry_delay(self, attempt: int) -> float:
        if attempt <= 0:
            return 0.0
        index = min(attempt - 1, len(MODEL_RETRY_DELAYS_SECONDS) - 1)
        return MODEL_RETRY_DELAYS_SECONDS[index]

    async def _chat_with_retry(
        self,
        provider: LLMProvider,
        *,
        request: ChatRequest,
        run_id: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
        retry_context: dict[str, Any] | None = None,
    ) -> LLMResponse:
        current_provider = provider
        provider_key = self._provider_cache_key(request.model_preference)
        for attempt in range(1, MODEL_RETRY_MAX_ATTEMPTS + 1):
            try:
                return await current_provider.chat(
                    messages,
                    tools=tools,
                    temperature=temperature,
                    cache=cache,
                )
            except Exception as error:
                should_retry = (
                    attempt < MODEL_RETRY_MAX_ATTEMPTS
                    and self._is_transient_model_error(error)
                )
                if not should_retry:
                    raise
                delay = self._model_retry_delay(attempt)
                self.trace_store.append_event(
                    run_id,
                    type="model.retrying",
                    status="running",
                    title="Model call retrying after transient error",
                    payload={
                        **(retry_context or {}),
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "max_attempts": MODEL_RETRY_MAX_ATTEMPTS,
                        "retry_delay_seconds": delay,
                        "error_type": type(error).__name__,
                        "error_message": str(error),
                    },
                )
                self._providers.pop(provider_key, None)
                await asyncio.sleep(delay)
                current_provider = self._get_provider(request.model_preference)
        raise RuntimeError("model retry loop exited without a response")

    async def _chat_stream_response_with_retry(
        self,
        provider: LLMProvider,
        *,
        request: ChatRequest,
        run_id: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        retry_context: dict[str, Any] | None = None,
    ) -> LLMResponse:
        current_provider = provider
        provider_key = self._provider_cache_key(request.model_preference)
        for attempt in range(1, MODEL_RETRY_MAX_ATTEMPTS + 1):
            chunks: list[str] = []
            try:
                async for token in current_provider.chat_stream(
                    messages,
                    tools=tools,
                    temperature=temperature,
                    cache=cache,
                ):
                    chunks.append(token)
                    await self._emit_token(on_token, token)
                return LLMResponse(
                    content="".join(chunks),
                    tool_calls=[],
                    model=getattr(current_provider, "model", ""),
                    usage={},
                )
            except Exception as error:
                should_retry = (
                    not chunks
                    and attempt < MODEL_RETRY_MAX_ATTEMPTS
                    and self._is_transient_model_error(error)
                )
                if not should_retry:
                    raise
                delay = self._model_retry_delay(attempt)
                self.trace_store.append_event(
                    run_id,
                    type="model.retrying",
                    status="running",
                    title="Streaming model call retrying after transient error",
                    payload={
                        **(retry_context or {}),
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "max_attempts": MODEL_RETRY_MAX_ATTEMPTS,
                        "retry_delay_seconds": delay,
                        "error_type": type(error).__name__,
                        "error_message": str(error),
                        "streaming": True,
                    },
                )
                self._providers.pop(provider_key, None)
                await asyncio.sleep(delay)
                current_provider = self._get_provider(request.model_preference)
        raise RuntimeError("streaming model retry loop exited without a response")

    def _user_id(self, request: ChatRequest) -> str:
        value = str(getattr(request, "user_id", None) or "0").strip()
        return value or "0"

    def _conversation_memory_id(self, request: ChatRequest) -> str:
        return f"user:{self._user_id(request)}:conversation:{request.conversation_id}"

    def _compact_tool_result_for_memory(self, content: str | list[dict[str, Any]]) -> str:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        try:
            payload = json.loads(text)
        except Exception:
            return str(text)[:4000]
        if not isinstance(payload, dict):
            return json.dumps(payload, ensure_ascii=False)[:4000]

        compact: dict[str, Any] = {}
        for key in ("success", "error"):
            if key in payload:
                compact[key] = payload[key]
        display_text = str(payload.get("display_text") or "").strip()
        if display_text:
            compact["display_text"] = display_text[:1800]

        data = payload.get("data")
        if isinstance(data, dict):
            compact_data: dict[str, Any] = {}
            for key in (
                "agent_id",
                "child_run_id",
                "task",
                "reason",
                "response",
                "skills_used",
                "model_used",
                "tokens_used",
                "error_type",
                "query",
                "url",
                "title",
                "item",
            ):
                if key not in data:
                    continue
                value = data[key]
                if isinstance(value, str):
                    compact_data[key] = value[:4000 if key == "response" else 1000]
                else:
                    compact_data[key] = value
            if isinstance(data.get("results"), list):
                compact_data["results"] = data["results"][:5]
            if isinstance(data.get("citations"), list):
                compact_data["citations"] = data["citations"][:8]
            if isinstance(data.get("artifacts"), list):
                compact_data["artifacts"] = data["artifacts"][:8]
            if compact_data:
                compact["data"] = compact_data
        elif data is not None:
            compact["data"] = str(data)[:2000]

        return json.dumps(compact or payload, ensure_ascii=False)[:6000]

    def _conversation_memory_message(self, message: LLMMessage) -> LLMMessage:
        if message.role != "tool":
            return message
        return message.model_copy(
            update={"content": self._compact_tool_result_for_memory(message.content)}
        )

    def _add_conversation_memory(
        self,
        request: ChatRequest,
        messages: list[LLMMessage],
    ) -> None:
        if not request.memory_enabled or not messages:
            return
        self.memory.add_many(
            self._conversation_memory_id(request),
            [self._conversation_memory_message(message) for message in messages],
        )

    def _resolve_role_id(self, request: ChatRequest, agent_metadata: dict) -> str:
        if request.role_id:
            return request.role_id
        default_role_id = agent_metadata.get("default_role_id") or "default"
        return str(default_role_id)

    def _apply_memory_read_policy(
        self,
        request: ChatRequest,
        role_context: MemoryContext,
    ) -> MemoryContext:
        if request.memory_enabled and role_context.role.memory_enabled:
            return role_context
        visible = MemoryContext(
            role=role_context.role,
            persona_memories=[],
            long_term_memories=[],
        )
        visible.rendered = self.role_memory.render_context(visible)
        return visible

    def _normalize_mode_prompts(self, prompts: list[str] | None) -> list[str]:
        return self.context_builder.normalize_mode_prompts(prompts)

    def _normalize_context_blocks(self, blocks: list[str] | None) -> list[str]:
        return self.context_builder.normalize_context_blocks(blocks)

    def _is_persisted_conversation_context(self, block: str) -> bool:
        return str(block or "").lstrip().startswith(
            ("Persisted conversation history", "持久化会话历史")
        )

    def _context_blocks_for_model(
        self,
        blocks: list[str] | None,
        *,
        history: list[LLMMessage],
    ) -> list[str]:
        normalized = self._normalize_context_blocks(blocks)
        if not history:
            return normalized
        return [
            block
            for block in normalized
            if not self._is_persisted_conversation_context(block)
        ]

    def _memory_retrieval_query(self, request: ChatRequest) -> str:
        parts: list[str] = []
        current_message = " ".join(str(request.message or "").split()).strip()
        if current_message:
            parts.append(current_message[:1200])

        packet = request.agent_input or request.handoff
        if packet is not None:
            for value in (packet.current_request, packet.reason, packet.candidate_context_brief):
                text = " ".join(str(value or "").split()).strip()
                if text:
                    parts.append(text[:2200])
            for message in packet.messages[-4:]:
                text = " ".join(str(message.content or "").split()).strip()
                if text:
                    parts.append(text[:1200])
            for stage in packet.stage_contexts[-4:]:
                text = " ".join(
                    str(value or "").strip()
                    for value in (stage.summary, stage.content)
                    if str(value or "").strip()
                )
                if text:
                    parts.append(text[:1200])

        for block in self._normalize_context_blocks(request.context_blocks):
            text = " ".join(block.split()).strip()
            if text:
                parts.append(text[:2200])

        seen: set[str] = set()
        deduped: list[str] = []
        for part in parts:
            normalized = part.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(part)

        return "\n".join(deduped)[:6000]

    def _agent_system_context(self, agent_id: str) -> str:
        return ""

    def _super_chat_auto_search_required(self, request: ChatRequest) -> bool:
        text = " ".join(
            [
                request.message or "",
                " ".join(request.mode_prompts or []),
            ]
        ).lower()
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized or self._search_explicitly_disabled(normalized):
            return False
        if extract_public_http_urls(normalized):
            return True

        # This is only an engineering fallback for cases where the model skipped an
        # explicit retrieval request. Broad freshness/fact keywords are left for
        # the model to decide through the normal tool-choice path.
        explicit_search_terms = [
            "搜索",
            "搜一下",
            "搜搜",
            "检索",
            "查一下",
            "查查",
            "帮我查",
            "查找",
            "联网",
            "引用来源",
            "核验",
            "验证",
            "sources",
            "citation",
            "search",
            "lookup",
            "look up",
            "browse",
            "google",
        ]
        return any(term in normalized for term in explicit_search_terms)

    def _super_chat_drive_task_without_explicit_retrieval(self, request: ChatRequest) -> bool:
        current_text = " ".join(
            [
                request.message or "",
                " ".join(request.mode_prompts or []),
            ]
        ).lower()
        current_normalized = re.sub(r"\s+", " ", current_text).strip()
        if not current_normalized or self._super_chat_auto_search_required(request):
            return False

        combined_text = " ".join(
            [
                request.message or "",
                " ".join(request.mode_prompts or []),
                " ".join(request.context_blocks or []),
            ]
        ).lower()
        normalized = re.sub(r"\s+", " ", combined_text).strip()
        if not normalized:
            return False

        drive_terms = [
            "网盘",
            "文件夹",
            "根目录",
            "folder_id",
            "save_drive",
            "update_drive",
            "read_drive",
            "mkdir_drive",
            "ls_drive",
            "search_drive",
            "/我的网盘",
        ]
        existing_content_terms = [
            "上一条助手回答",
            "上一条回答",
            "这份报告",
            "这份文件",
            "旧文件",
            "已有文件",
            "复制",
            "拷贝",
            "移动",
            "挪到",
            "放进",
            "新建文件夹",
            "创建文件夹",
            "建文件夹",
            "整理目录",
            "归档",
            "读三份",
            "读取旧文件",
            "目标文件名",
        ]
        short_confirmation = re.fullmatch(
            r"[\s，,。.!！?？]*(?:(?:可以|好|好的|继续|确认|行|嗯|ok|yes)(?:[\s，,]*(?:方案\s*)?[abc123一二三])?|(?:方案\s*)?[abc123一二三])[\s，,。.!！?？]*",
            current_normalized,
            flags=re.IGNORECASE,
        )
        current_has_drive_context = any(term in current_normalized for term in drive_terms)
        current_has_existing_content_task = any(
            term in current_normalized for term in existing_content_terms
        )
        has_drive_context = any(term in normalized for term in drive_terms)
        has_existing_content_task = any(term in normalized for term in existing_content_terms)
        return (
            current_has_drive_context and current_has_existing_content_task
        ) or (
            bool(short_confirmation) and has_drive_context and has_existing_content_task
        )

    def _search_explicitly_disabled(self, normalized_text: str) -> bool:
        disabled_terms = [
            "不要搜索",
            "不用搜索",
            "别搜索",
            "不要联网",
            "不用联网",
            "别联网",
            "不需要搜索",
            "无需搜索",
            "不查外网",
            "不要查外网",
            "without searching",
            "do not search",
            "don't search",
            "no search",
            "without browsing",
            "do not browse",
            "don't browse",
        ]
        return any(term in normalized_text for term in disabled_terms)

    def _super_chat_auto_search_arguments(self, request: ChatRequest) -> dict[str, Any]:
        query_parts = [request.message or ""]
        query_parts.extend(self._normalize_context_blocks(request.context_blocks)[:1])
        query = " ".join(" ".join(part.split()) for part in query_parts if part).strip()
        query = query[:220] or (request.message or "用户请求")
        arguments: dict[str, Any] = {
            "query": query,
            "sources": "web",
            "limit": SUPER_CHAT_AUTO_SEARCH_LIMIT,
        }
        if self._super_chat_auto_search_should_open_results(request):
            arguments.update(
                {
                    "open_results": True,
                    "open_limit": 2,
                    "page_chars": 6000,
                }
            )
        return arguments

    def _request_public_urls(self, request: ChatRequest) -> list[str]:
        values = [
            request.message or "",
            " ".join(request.context_blocks or []),
        ]
        urls: list[str] = []
        seen: set[str] = set()
        for value in values:
            for url in extract_public_http_urls(value):
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
        return urls

    def _super_chat_auto_retrieval_call(
        self,
        request: ChatRequest,
        *,
        round_index: int,
        allowed_tool_names: set[str],
    ) -> ToolCall:
        urls = self._request_public_urls(request)
        if len(urls) == 1 and "open_url" in allowed_tool_names and self.skill_registry.get("open_url") is not None:
            return ToolCall(
                id=f"auto_open_url_{round_index + 1}",
                name="open_url",
                arguments={"url": urls[0], "max_chars": 6000},
            )
        return ToolCall(
            id=f"auto_search_{round_index + 1}",
            name="search",
            arguments=self._super_chat_auto_search_arguments(request),
        )

    def _super_chat_auto_retrieval_available(
        self,
        request: ChatRequest,
        *,
        allowed_tool_names: set[str],
    ) -> bool:
        if "search" in allowed_tool_names and self.skill_registry.get("search") is not None:
            return True
        urls = self._request_public_urls(request)
        return (
            len(urls) == 1
            and "open_url" in allowed_tool_names
            and self.skill_registry.get("open_url") is not None
        )

    def _super_chat_auto_search_should_open_results(self, request: ChatRequest) -> bool:
        text = " ".join(
            [
                request.message or "",
                " ".join(request.mode_prompts or []),
                " ".join(request.context_blocks or []),
            ]
        ).lower()
        normalized = re.sub(r"\s+", " ", text).strip()
        high_confidence_terms = [
            "官网",
            "官方网站",
            "官方文档",
            "说明书",
            "安全",
            "风险",
            "使用方法",
            "维修",
            "保养",
            "兼容",
            "错误码",
            "政策",
            "法规",
            "法律",
            "医疗",
            "药",
            "金融",
            "投资",
            "财报",
            "official",
            "docs",
            "safety",
            "law",
            "legal",
            "medical",
            "finance",
            "filing",
        ]
        return any(term in normalized for term in high_confidence_terms)

    def _render_memory_system(
        self,
        role_context: MemoryContext,
        *,
        short_term_summary: str = "",
    ) -> str:
        return render_memory_context(
            role_context,
            short_term_summary=short_term_summary,
        )

    def _build_context_priority_rules(self) -> str:
        return self.context_builder.build_context_priority_rules()

    def _prompt_section_order(self, system_prompt: str) -> list[str]:
        return self.context_builder.section_order(system_prompt)

    def _build_system_prompt_parts(
        self,
        role_context: MemoryContext,
        mode_prompts: list[str] | None = None,
        context_blocks: list[str] | None = None,
        drive_context: Any | None = None,
        agent_id: str = "general_assistant",
        tool_names: list[str] | None = None,
        short_term_summary: str = "",
    ) -> list[dict[str, Any]]:
        return self.context_builder.build_system_prompt_parts(
            role_context,
            mode_prompts=mode_prompts,
            context_blocks=context_blocks,
            drive_context=drive_context,
            agent_id=agent_id,
            agent_context=self._agent_system_context(agent_id),
            tool_names=tool_names,
            short_term_summary=short_term_summary,
        )

    def _build_system_prompt(
        self,
        role_context: MemoryContext,
        mode_prompts: list[str] | None = None,
        context_blocks: list[str] | None = None,
        drive_context: Any | None = None,
        agent_id: str = "general_assistant",
        tool_names: list[str] | None = None,
        short_term_summary: str = "",
    ) -> str:
        return self._render_prompt_parts(
            self._build_system_prompt_parts(
                role_context,
                mode_prompts=mode_prompts,
                context_blocks=context_blocks,
                drive_context=drive_context,
                agent_id=agent_id,
                tool_names=tool_names,
                short_term_summary=short_term_summary,
            )
        )

    def _render_prompt_parts(self, parts: list[dict[str, Any]]) -> str:
        return self.context_builder.render_prompt_parts(parts)

    def _build_prompt_cache_options(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_id: str,
        prompt_sources: list[dict[str, Any]],
        tool_names: list[str],
    ) -> PromptCacheOptions:
        stable_section_ids = [
            "base_system_prompt",
            "context_priority_rules",
            "system_config",
            "agent_context",
            "role_memory_context",
        ]
        stable_sections = [
            source
            for source in prompt_sources
            if source.get("id") in stable_section_ids
        ]
        stable_prompt = self._render_prompt_parts(stable_sections)
        stable_prompt_hash = hashlib.sha256(
            stable_prompt.encode("utf-8")
        ).hexdigest()
        toolset_hash = hashlib.sha256(
            "\n".join(sorted(tool_names)).encode("utf-8")
        ).hexdigest()
        key_payload = {
            "version": 1,
            "agent_id": agent_id,
            "role_id": role_id,
            "user_id": self._user_id(request),
            "model_preference": request.model_preference or "",
            "stable_prompt_hash": stable_prompt_hash,
            "toolset_hash": toolset_hash,
        }
        key_hash = hashlib.sha256(
            json.dumps(key_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return PromptCacheOptions(
            enabled=True,
            key=f"aa:{key_hash[:40]}",
            cache_system_prompt=True,
            cache_tools=True,
            metadata={
                "stable_section_ids": stable_section_ids,
                "stable_prompt_hash": stable_prompt_hash[:16],
                "stable_prompt_chars": len(stable_prompt),
                "toolset_hash": toolset_hash[:16],
            },
        )

    async def _emit_token(
        self,
        on_token: Callable[[str], Awaitable[None] | None] | None,
        token: str,
    ) -> None:
        if not on_token or not token:
            return
        result = on_token(token)
        if inspect.isawaitable(result):
            await result

    def _tool_budget_finalization_prompt(
        self,
        *,
        reason: str,
        model_rounds: int,
        tool_call_count: int,
        failed_tool_call_count: int,
    ) -> str:
        return (
            "工具预算已经用完，现在禁止再调用任何工具。请基于上文已有的工具结果，"
            "直接给用户一个中文阶段性最终总结。\n\n"
            f"预算停止原因：{reason}\n"
            f"已用模型轮次：{model_rounds}/{MAX_MODEL_ROUNDS}\n"
            f"已执行工具调用：{tool_call_count}/{MAX_TOOL_CALLS}\n"
            f"失败工具调用：{failed_tool_call_count}/{MAX_FAILED_TOOL_CALLS}\n\n"
            "要求：\n"
            "- 只总结已经确认的信息和已经失败的尝试。\n"
            "- 明确说明哪些信息仍未确认，不要编造。\n"
            "- 不要说“我将继续调用工具”或提出新的工具调用计划。\n"
            "- 如果足以回答用户，就给出结论；如果不足，就给出下一步人工可执行建议。"
        )

    def _fallback_tool_budget_summary(
        self,
        *,
        reason: str,
        fallback_content: str,
    ) -> str:
        content = " ".join(str(fallback_content or "").split()).strip()
        if content:
            return f"工具预算已用完（{reason}）。我先基于当前已拿到的信息做阶段性总结：\n\n{content}"
        return f"工具预算已用完（{reason}）。当前轮次没有生成可靠的最终总结，请查看 trace 中已完成和失败的工具调用。"

    def _latest_successful_tool_payload(
        self,
        messages: list[LLMMessage],
    ) -> tuple[str, dict[str, Any]] | None:
        tool_names_by_call_id: dict[str, str] = {}
        for message in messages:
            if message.role != "assistant" or not message.tool_calls:
                continue
            for call in message.tool_calls:
                if not isinstance(call, dict):
                    continue
                call_id = str(call.get("id") or "").strip()
                name = str(call.get("name") or "").strip()
                if call_id and name:
                    tool_names_by_call_id[call_id] = name

        for message in reversed(messages):
            if message.role != "tool" or not isinstance(message.content, str):
                continue
            try:
                payload = json.loads(message.content)
            except ValueError:
                continue
            if not isinstance(payload, dict) or payload.get("success") is not True:
                continue
            tool_name = tool_names_by_call_id.get(str(message.tool_call_id or ""), "")
            return tool_name, payload
        return None

    def _limit_tool_fallback_text(self, value: str, max_chars: int = 30000) -> str:
        text = str(value or "").strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n\n[工具结果过长，以上内容已截断。]"

    def _fallback_after_model_error_with_tool_results(
        self,
        messages: list[LLMMessage],
        *,
        error_message: str,
    ) -> str:
        latest = self._latest_successful_tool_payload(messages)
        if latest is None:
            return ""
        tool_name, payload = latest
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        display_text = str(payload.get("display_text") or "").strip()

        if tool_name == "read_drive" and isinstance(data, dict):
            item = data.get("item") if isinstance(data.get("item"), dict) else {}
            name = str(item.get("name") or "网盘文件").strip()
            path = str(item.get("path") or "").strip()
            content = str(data.get("content") or display_text).strip()
            if content:
                truncated_note = "工具返回结果标记为已截断；下面是已读取到的内容。" if data.get("truncated") else "下面是工具已读取到的内容。"
                location = f"{name}（{path}）" if path else name
                return (
                    f"模型在整理最终回复时连接失败（{error_message}），但 `read_drive` 已经成功读取了文件："
                    f"{location}。\n\n"
                    f"{truncated_note}\n\n"
                    f"{self._limit_tool_fallback_text(content)}"
                )

        fallback_text = self._limit_tool_fallback_text(display_text or json.dumps(data, ensure_ascii=False))
        if not fallback_text:
            return ""
        tool_label = f"`{tool_name}`" if tool_name else "工具"
        return (
            f"模型在整理最终回复时连接失败（{error_message}），但前面的 {tool_label} 调用已经成功。"
            f"先把工具结果直接返回给你：\n\n{fallback_text}"
        )

    def _drive_context_prompt_source(self, drive_context: Any | None) -> dict[str, Any] | None:
        content = self.context_builder.render_drive_context_index(drive_context)
        if not content:
            return None
        return {
            "id": "drive_context",
            "label": "Drive Context Index",
            "content": content,
            "priority": 5,
            "stability": "turn",
        }

    async def _finalize_after_tool_budget_exhausted(
        self,
        *,
        provider: LLMProvider,
        messages: list[LLMMessage],
        prompt_cache: PromptCacheOptions,
        run_id: str,
        request: ChatRequest,
        reason: str,
        error_type: str,
        model_rounds: int,
        tool_call_count: int,
        failed_tool_call_count: int,
        response: LLMResponse | None,
        workflow_context: dict[str, Any] | None = None,
    ) -> tuple[LLMResponse, str]:
        final_messages = list(messages)
        final_messages.append(
            LLMMessage(
                role="user",
                content=self._tool_budget_finalization_prompt(
                    reason=reason,
                    model_rounds=model_rounds,
                    tool_call_count=tool_call_count,
                    failed_tool_call_count=failed_tool_call_count,
                ),
            )
        )
        model_started = perf_counter()
        payload = {
            "round": model_rounds + 1,
            "message_count": len(final_messages),
            "tools_count": 0,
            "model_preference": request.model_preference,
            "finalization": True,
            "reason": reason,
            "error_type": error_type,
        }
        if workflow_context:
            payload.update(workflow_context)
        self.trace_store.append_event(
            run_id,
            type="model.started",
            status="running",
            title="Final summary after tool budget exhausted",
            payload=payload,
        )
        try:
            final_response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=final_messages,
                tools=None,
                cache=prompt_cache,
                retry_context={
                    "scope": "tool_budget_finalization",
                    "finalization": True,
                    "reason": reason,
                    "error_type": error_type,
                    **(workflow_context or {}),
                },
            )
        except Exception as e:
            logger.exception("Final summary after tool budget exhaustion failed")
            duration_ms = int((perf_counter() - model_started) * 1000)
            self.trace_store.append_event(
                run_id,
                type="model.failed",
                status="error",
                title="Final summary after tool budget exhausted failed",
                payload={
                    "error_type": "model_error",
                    "error_message": str(e),
                    "finalization": True,
                    "reason": reason,
                },
                duration_ms=duration_ms,
            )
            fallback = self._fallback_tool_budget_summary(
                reason=reason,
                fallback_content=response.content if response else "",
            )
            return (
                LLMResponse(
                    content=fallback,
                    tool_calls=[],
                    model=response.model if response else getattr(provider, "model", ""),
                    usage=response.usage if response else {},
                ),
                "failed",
            )

        if final_response.tool_calls:
            logger.warning("Provider returned tool calls during tool-budget finalization; ignoring tool calls")
            final_response = LLMResponse(
                content=final_response.content,
                tool_calls=[],
                model=final_response.model,
                usage=final_response.usage,
            )
        if not final_response.content.strip():
            final_response = LLMResponse(
                content=self._fallback_tool_budget_summary(
                    reason=reason,
                    fallback_content=response.content if response else "",
                ),
                tool_calls=[],
                model=final_response.model,
                usage=final_response.usage,
            )
        completed_payload = {
            "round": model_rounds + 1,
            "model": final_response.model,
            "usage": final_response.usage,
            "tool_calls": [],
            "content_preview": final_response.content[:300],
            "finalization": True,
            "reason": reason,
            "error_type": error_type,
        }
        if workflow_context:
            completed_payload.update(workflow_context)
        self.trace_store.append_event(
            run_id,
            type="model.completed",
            status="completed",
            title="Final summary after tool budget exhausted completed",
            payload=completed_payload,
            duration_ms=int((perf_counter() - model_started) * 1000),
        )
        return final_response, "completed"

    def _snapshot_run_events(self, run_id: str) -> list:
        run = self.trace_store.get_run(run_id)
        return list(run.events) if run else []

    def _schedule_memory_postprocess(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_context: MemoryContext,
        assistant_message: str,
        new_messages: list[LLMMessage],
        run_id: str,
    ) -> None:
        if not request.memory_enabled:
            return

        conversation_message_count = len(
            self.memory.get(self._conversation_memory_id(request))
        )
        task = asyncio.create_task(
            self._run_memory_postprocess(
                request=request,
                agent_id=agent_id,
                role_context=role_context,
                assistant_message=assistant_message,
                new_messages=list(new_messages),
                run_id=run_id,
                conversation_message_count=conversation_message_count,
            )
        )
        self._postprocess_tasks.add(task)

        def _discard(done: asyncio.Task[None]) -> None:
            self._postprocess_tasks.discard(done)
            if done.cancelled():
                return
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Memory post-processing task failed")

        task.add_done_callback(_discard)

    async def _run_memory_postprocess(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_context: MemoryContext,
        assistant_message: str,
        new_messages: list[LLMMessage],
        run_id: str,
        conversation_message_count: int,
    ) -> None:
        await self._review_and_store_memories(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=assistant_message,
            new_messages=new_messages,
            run_id=run_id,
        )
        await self._maybe_compact_conversation_memory(
            request=request,
            run_id=run_id,
            expected_message_count=conversation_message_count,
        )

    async def wait_for_postprocessing(self) -> None:
        while self._postprocess_tasks:
            tasks = list(self._postprocess_tasks)
            await asyncio.gather(*tasks, return_exceptions=True)

    def _trace_message(self, message: LLMMessage) -> dict:
        content = message.content
        return {
            "role": message.role,
            "content": content if isinstance(content, str) else content,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }

    def _estimate_tokens(self, value: Any) -> int:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return max(1, len(text) // 4) if text else 0

    def _memory_trace_payload(self, record: MemoryRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "role_id": record.role_id,
            "user_id": record.user_id,
            "kind": record.kind,
            "scope": record.scope,
            "status": record.status,
            "review_state": record.review_state,
            "content": record.content,
            "source": record.source,
            "agent_id": record.agent_id,
            "confidence": record.confidence,
            "tags": record.tags,
            "source_trace": record.source_trace,
            "valid_from": record.valid_from.isoformat() if record.valid_from else None,
            "valid_until": record.valid_until.isoformat() if record.valid_until else None,
            "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
            "ttl_days": record.ttl_days,
            "sensitivity": record.sensitivity,
            "review_notes": record.review_notes,
            "version": record.version,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "metadata": record.metadata,
        }

    def _memory_record_groups_payload(
        self,
        records: list[MemoryRecord],
    ) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        for group in self.role_memory.group_memories_by_date(records):
            group_records = [
                record
                for record in group.get("records", [])
                if isinstance(record, MemoryRecord)
            ]
            groups.append(
                {
                    "date": group["date"],
                    "record_count": len(group_records),
                    "records": [
                        self._memory_trace_payload(record)
                        for record in group_records
                    ],
                }
            )
        return groups

    def _summary_groups_payload(self, summary: str) -> list[dict[str, Any]]:
        text = str(summary or "").strip()
        if not text:
            return []

        groups: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in text.splitlines():
            stripped = line.strip()
            match = re.match(r"^(?P<date>\d{4}-\d{2}-\d{2})[:：]$", stripped)
            if match:
                current = {"date": match.group("date"), "items": []}
                groups.append(current)
                continue
            if current is None:
                current = {"date": "", "items": []}
                groups.append(current)
            item = stripped.lstrip("- ").strip()
            if item:
                current["items"].append(item)

        for group in groups:
            group["summary"] = "\n".join(f"- {item}" for item in group.pop("items"))
            group["token_estimate"] = self._estimate_tokens(group["summary"])
        return [group for group in groups if group.get("summary")]

    def _memory_loaded_payload(
        self,
        *,
        role_id: str,
        user_id: str,
        role_context: MemoryContext,
    ) -> dict[str, Any]:
        return {
            "role_id": role_id,
            "user_id": user_id,
            "persona_count": len(role_context.persona_memories),
            "long_term_count": len(role_context.long_term_memories),
            "context_record_ids": [record.id for record in role_context.records],
            "records": [self._memory_trace_payload(record) for record in role_context.records],
            "record_groups": self._memory_record_groups_payload(role_context.records),
            "long_term_groups": self._memory_record_groups_payload(role_context.long_term_memories),
            "persona_groups": self._memory_record_groups_payload(role_context.persona_memories),
        }

    def _memory_candidate_trace_payload(self, candidate: MemoryCandidate) -> dict[str, Any]:
        return {
            "kind": candidate.kind,
            "content": candidate.content,
            "confidence": candidate.confidence,
            "reason": candidate.reason,
            "tags": candidate.tags,
            "agent_id": candidate.agent_id,
            "action": candidate.action,
            "target_id": candidate.target_id,
            "metadata": candidate.metadata,
        }

    def _prompt_context_nodes(
        self,
        *,
        role_context: MemoryContext,
        messages: list[LLMMessage],
        tools_count: int,
        tool_names: list[str],
        context_blocks: list[str],
        short_term_summary: str,
        system_prompt: str,
        prompt_sources: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        source_by_id = {
            str(source.get("id")): source
            for source in (prompt_sources or [])
            if isinstance(source, dict) and source.get("id")
        }
        section_nodes = [
            {
                "id": f"prompt.section.{name}",
                "type": "prompt_section",
                "label": source_by_id.get(name, {}).get("label") or name,
                "injected": True,
                "priority": source_by_id.get(name, {}).get("priority"),
                "content": source_by_id.get(name, {}).get("content"),
                "chars": len(str(source_by_id.get(name, {}).get("content") or "")),
                "token_estimate": self._estimate_tokens(
                    source_by_id.get(name, {}).get("content") or name
                ),
            }
            for name in self._prompt_section_order(system_prompt)
        ]
        conversation_messages = [
            self._trace_message(message)
            for message in messages
            if message.role != "system"
        ]
        context_block_nodes = [
            {
                "id": f"turn_context.block.{index + 1}",
                "type": "context_block",
                "label": self._context_block_label(block, index),
                "injected": True,
                "chars": len(block),
                "token_estimate": self._estimate_tokens(block),
                "preview": block[:500],
            }
            for index, block in enumerate(context_blocks)
        ]
        return [
            {
                "id": "prompt.system",
                "type": "system_prompt",
                "label": "System / Developer Prompt",
                "injected": True,
                "chars": len(system_prompt),
                "content": system_prompt,
                "token_estimate": self._estimate_tokens(system_prompt),
                "children": section_nodes,
            },
            {
                "id": "memory.long_term",
                "type": "long_term_memory",
                "label": "Long-term Memory",
                "injected": bool(role_context.long_term_memories),
                "persistent": True,
                "record_count": len(role_context.long_term_memories),
                "records": [self._memory_trace_payload(record) for record in role_context.long_term_memories],
                "record_groups": self._memory_record_groups_payload(role_context.long_term_memories),
            },
            {
                "id": "memory.role_persona",
                "type": "role_persona_memory",
                "label": "Role / Persona Memory",
                "injected": True,
                "persistent": True,
                "role": role_context.role.model_dump(mode="json"),
                "record_count": len(role_context.persona_memories),
                "records": [self._memory_trace_payload(record) for record in role_context.persona_memories],
                "record_groups": self._memory_record_groups_payload(role_context.persona_memories),
            },
            {
                "id": "memory.short_term",
                "type": "short_term_memory",
                "label": "Short-term Conversation Memory",
                "injected": bool(short_term_summary),
                "persistent": False,
                "summary": short_term_summary,
                "summary_groups": self._summary_groups_payload(short_term_summary),
                "token_estimate": self._estimate_tokens(short_term_summary),
            },
            {
                "id": "conversation.window",
                "type": "conversation_window",
                "label": "Current Conversation Window",
                "injected": bool(conversation_messages),
                "persistent": False,
                "message_count": len(conversation_messages),
                "messages": conversation_messages,
                "token_estimate": self._estimate_tokens(conversation_messages),
            },
            {
                "id": "turn.context_blocks",
                "type": "turn_context",
                "label": "Turn Context Blocks / Attachments",
                "injected": bool(context_block_nodes),
                "persistent": False,
                "block_count": len(context_block_nodes),
                "children": context_block_nodes,
            },
            {
                "id": "tools.definitions",
                "type": "tool_definitions",
                "label": "Tool Definitions",
                "injected": tools_count > 0,
                "persistent": False,
                "tools_count": tools_count,
                "tool_names": tool_names,
            },
        ]

    def _context_block_label(self, block: str, index: int) -> str:
        normalized = " ".join(block.split())
        if normalized.lower().startswith("persisted conversation history"):
            return "Persisted conversation history"
        if normalized.lower().startswith("regeneration request"):
            return "Regeneration instruction"
        return f"Context block {index + 1}"

    def _append_context_trace(
        self,
        *,
        run_id: str,
        role_id: str,
        role_context: MemoryContext,
        messages: list[LLMMessage],
        tools_count: int,
        tool_names: list[str],
        mode_ids: list[str] | None = None,
        mode_prompts: list[str] | None = None,
        context_blocks: list[str] | None = None,
        short_term_summary: str = "",
        tools: list[Any] | None = None,
        prompt_sources: list[dict[str, Any]] | None = None,
        final_model_request: dict[str, Any] | None = None,
    ) -> None:
        normalized_context_blocks = self._normalize_context_blocks(context_blocks)
        system_prompt = messages[0].content if messages else ""
        context_nodes = self._prompt_context_nodes(
            role_context=role_context,
            messages=messages,
            tools_count=tools_count,
            tool_names=tool_names,
            context_blocks=normalized_context_blocks,
            short_term_summary=short_term_summary,
            system_prompt=system_prompt,
            prompt_sources=prompt_sources,
        )
        tool_definitions = [
            tool.model_dump(mode="json") if hasattr(tool, "model_dump") else tool
            for tool in (tools or [])
        ]
        default_final_model_request = {
            "messages": [self._trace_message(message) for message in messages],
            "tools": tool_definitions,
            "tool_choice": "auto" if tool_definitions else "none",
        }
        self.trace_store.append_event(
            run_id,
            type="context.built",
            status="completed",
            title="Prompt context built",
            payload={
                "role_id": role_id,
                "role_name": role_context.role.name,
                "message_count": len(messages),
                "tools_count": tools_count,
                "tool_names": tool_names,
                "mode_ids": mode_ids or [],
                "mode_prompts": self._normalize_mode_prompts(mode_prompts),
                "context_block_count": len(normalized_context_blocks),
                "context_block_chars": sum(len(block) for block in normalized_context_blocks),
                "system_prompt": system_prompt,
                "prompt_section_order": self._prompt_section_order(system_prompt),
                "prompt_sources": prompt_sources or [],
                "final_model_request": final_model_request or default_final_model_request,
                "context_nodes": context_nodes,
                "role_context": role_context.rendered,
                "short_term_summary": short_term_summary,
                "short_term_summary_groups": self._summary_groups_payload(short_term_summary),
                "memory_records": [
                    self._memory_trace_payload(record)
                    for record in role_context.records
                ],
                "memory_record_groups": self._memory_record_groups_payload(role_context.records),
                "messages": [self._trace_message(message) for message in messages],
            },
        )

    def _memory_message_payload(self, message: LLMMessage, index: int) -> dict[str, Any]:
        content = message.content
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    text_parts.append(str(item.get("text") or ""))
                elif item.get("type") == "image_url":
                    text_parts.append("[image attachment]")
                else:
                    text_parts.append(f"[{item.get('type') or 'attachment'}]")
            content_text = "\n".join(part for part in text_parts if part).strip()
        else:
            content_text = str(content or "").strip()
        return {
            "index": index,
            "role": message.role,
            "content": content_text[:1800],
            "has_tool_calls": bool(message.tool_calls),
            "tool_call_id": message.tool_call_id,
        }

    def _memory_review_messages(
        self,
        *,
        role_context: MemoryContext,
        agent_id: str,
        request: ChatRequest,
        assistant_message: str,
        new_messages: list[LLMMessage],
    ) -> list[LLMMessage]:
        existing_records = [
            {
                "id": record.id,
                "kind": "role" if record.kind == "persona" else record.kind,
                "content": record.content,
                "confidence": record.confidence,
                "tags": record.tags,
                "updated_at": record.updated_at.isoformat(),
            }
            for record in role_context.records
        ]
        turn_messages = [
            self._memory_message_payload(message, index)
            for index, message in enumerate(new_messages)
        ]
        system = (
            "你是长期记忆更新器。你的任务是在一轮对话结束后，判断是否有信息值得跨会话保存或更新。"
            "只返回 JSON 对象，不要 Markdown。\n\n"
            "只保存这些类型：\n"
            "- long_term：稳定的用户事实、偏好、长期项目、持续目标、明确要求记住的信息。\n"
            "- role：用户要求改变助手角色、人设、语气、工作方式或长期交互规则。\n\n"
            "保存标准必须严格：候选记忆应当在明天、下周或另一个新会话中仍然有用；"
            "优先依据用户自己的明确陈述或明确记忆请求，不要从助手回答、工具结果或搜索摘要中推断用户事实。"
            "用户说“帮我/给我/想了解/查询/分析/总结/计划/推荐”通常只是一次性任务，不是长期记忆。"
            "只有当用户明确表达稳定偏好、身份信息、持续项目、长期目标，或明确要求记住时才保存。\n\n"
            "优先更新 existing_memories 中相关的旧记忆：如果新信息是补充、纠正或同一主题进展，"
            "返回 action=update、target_id 和合并后的短句；不要新增一条相近记忆。"
            "不要保存普通问题、一次性任务、临时上下文、模型回答中的猜测、搜索结果摘要、"
            "敏感信息或隐私信息，除非用户明确要求记住。若当前消息与已有记忆重复，返回空数组。"
            "不要保存“用户询问了什么/用户想了解什么/用户需要一份方案”这类任务描述。"
            "记忆 content 要写成可复用事实，而不是对本轮对话的日志。"
            "最多返回 3 条高置信候选；如果没有值得保存的内容，返回空数组。\n\n"
            "例子：\n"
            "- 用户：帮我计划一下澳洲旅行 -> 返回空数组。\n"
            "- 用户：我计划今年 10 月去澳洲旅行，预算 2 万 -> 可保存 long_term。\n"
            "- 用户：我喜欢回答短一点 -> 可保存 long_term。\n"
            "- 用户：以后请用更直接的语气 -> 可保存 role。\n"
        )
        user = json.dumps(
            {
                "output_schema": {
                    "memories": [
                        {
                            "action": "create|update",
                            "target_id": "更新已有记忆时填写 existing_memories.id，否则省略",
                            "kind": "long_term|role",
                            "content": "简短、合并后可直接放入 prompt 的记忆",
                            "confidence": 0.0,
                            "reason": "为什么值得保存",
                            "tags": ["可选标签"],
                        }
                    ]
                },
                "role": role_context.role.model_dump(mode="json"),
                "agent_id": agent_id,
                "conversation_id": request.conversation_id,
                "user_message": request.message,
                "assistant_message": assistant_message[:2000],
                "existing_memories": existing_records,
                "turn_messages": turn_messages,
            },
            ensure_ascii=False,
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

    def _coerce_memory_candidates(
        self,
        raw: dict[str, Any] | None,
    ) -> list[MemoryCandidate]:
        if not isinstance(raw, dict):
            return []
        items = raw.get("memories")
        if not isinstance(items, list):
            items = raw.get("candidates")
        if not isinstance(items, list):
            return []

        candidates: list[MemoryCandidate] = []
        for item in items[:4]:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "create").strip().lower()
            if action in {"skip", "none"}:
                continue
            if action not in {"create", "update"}:
                action = "create"
            target_id = str(item.get("target_id") or item.get("id") or "").strip()
            if action == "update" and not target_id:
                continue
            kind = str(item.get("kind") or "long_term").strip()
            if kind == "persona":
                kind = "role"
            if kind not in {"role", "long_term"}:
                continue
            content = " ".join(str(item.get("content") or "").split()).strip()
            if len(content) < 4:
                continue
            try:
                confidence = float(item.get("confidence", 0.7))
            except (TypeError, ValueError):
                confidence = 0.7
            if confidence < 0.68:
                continue
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []
            reason = str(item.get("reason") or "ai_memory_review").strip()
            candidates.append(
                MemoryCandidate(
                    action=action,  # type: ignore[arg-type]
                    target_id=target_id or None,
                    kind=kind,  # type: ignore[arg-type]
                    content=content[:200],
                    confidence=max(0.0, min(confidence, 1.0)),
                    reason=reason[:160] or "ai_memory_review",
                    tags=[
                        str(tag).strip()[:32]
                        for tag in tags
                        if str(tag).strip()
                    ][:6],
                    metadata={"reviewer": "ai"},
                )
            )
        return candidates

    def _memory_candidate_is_explicit(self, candidate: MemoryCandidate) -> bool:
        markers = " ".join(
            [
                candidate.reason,
                " ".join(candidate.tags),
                str(candidate.metadata.get("reason") or ""),
            ]
        ).lower()
        return any(
            marker in markers
            for marker in [
                "explicit",
                "明确要求记住",
                "用户要求记住",
                "remember_request",
            ]
        )

    def _memory_candidate_rejection_reason(self, candidate: MemoryCandidate) -> str:
        if self._memory_candidate_is_explicit(candidate):
            return ""

        content = " ".join(str(candidate.content or "").split()).strip()
        if not content:
            return "empty_content"
        normalized = content.lower()

        if re.search(r"[？?]\s*$", content):
            return "question_not_memory"
        if re.search(r"(?:本轮|这次|当前|这条|刚才).{0,12}(?:问题|请求|任务|对话|回答|结果)", content):
            return "turn_local_context"
        if re.search(r"(?:搜索|检索|网页|模型|助手|回答|结果|资料).{0,12}(?:显示|认为|猜测|摘要|提到|表明)", content):
            return "derived_or_assistant_claim"
        if re.search(r"(?:可能|似乎|大概|不确定|疑似|看起来|应该是)", content):
            return "uncertain_claim"

        low_signal_request = re.search(
            r"用户(?:询问|问|提问|请求|要求|让|想了解|想知道|需要了解|需要知道|希望了解).{0,36}"
            r"(?:怎么|如何|是否|能否|可以|帮|写|生成|总结|分析|比较|计划|推荐|查询|检索|解释|整理|看)",
            content,
        )
        if low_signal_request:
            return "one_off_request"

        if candidate.kind == "long_term":
            if re.search(r"^用户(?:想|需要|希望).{0,28}(?:了解|知道|查询|看看|帮|生成|写|做|整理|分析|比较)", content):
                return "one_off_intent"
            if re.search(r"^用户(?:正在|计划).{0,28}(?:询问|了解|查询|让|要求|请求)", content):
                return "task_progress_not_user_fact"

        return ""

    def _filter_memory_candidates(
        self,
        candidates: list[MemoryCandidate],
    ) -> tuple[list[MemoryCandidate], list[dict[str, Any]]]:
        kept: list[MemoryCandidate] = []
        rejected: list[dict[str, Any]] = []
        for candidate in candidates:
            reason = self._memory_candidate_rejection_reason(candidate)
            if reason:
                rejected.append(
                    {
                        "reason": reason,
                        "candidate": self._memory_candidate_trace_payload(candidate),
                    }
                )
                continue
            kept.append(candidate)
        return kept, rejected

    async def _review_turn_with_ai(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_context: MemoryContext,
        assistant_message: str,
        new_messages: list[LLMMessage],
        run_id: str,
    ) -> list[MemoryCandidate]:
        provider = self._get_provider(request.model_preference)
        messages = self._memory_review_messages(
            role_context=role_context,
            agent_id=agent_id,
            request=request,
            assistant_message=assistant_message,
            new_messages=new_messages,
        )
        started = perf_counter()
        self.trace_store.append_event(
            run_id,
            type="memory.review.started",
            status="running",
            title="AI memory review started",
            payload={
                "role_id": role_context.role.id,
                "agent_id": agent_id,
                "message_count": len(new_messages),
            },
        )
        response = await self._chat_with_retry(
            provider,
            request=request,
            run_id=run_id,
            messages=messages,
            tools=None,
            temperature=0.1,
            retry_context={"scope": "memory_review"},
        )
        raw = self._extract_json_object(response.content)
        candidates = self._coerce_memory_candidates(raw)
        self.trace_store.append_event(
            run_id,
            type="memory.review.completed",
            status="completed",
            title="AI memory review completed",
            payload={
                "role_id": role_context.role.id,
                "candidate_count": len(candidates),
                "model": response.model,
                "usage": response.usage,
            },
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return candidates

    def _conversation_compaction_messages(
        self,
        *,
        conversation_id: str,
        existing_summary: str,
        history: list[LLMMessage],
        keep_messages: int,
    ) -> list[LLMMessage]:
        payload = {
            "conversation_id": conversation_id,
            "existing_summary": existing_summary,
            "messages": [
                self._memory_message_payload(message, index)
                for index, message in enumerate(history)
            ],
            "max_keep_message_indices": keep_messages,
            "output_schema": {
                "should_compact": True,
                "summary": "本次压缩后的当日短期会话记忆摘要，控制在 900 字以内",
                "keep_message_indices": [0],
            },
        }
        system = (
            "你是会话记忆压缩器。请判断当前会话历史是否需要压缩，并把仍然有用的信息写成短期摘要。"
            "只返回 JSON 对象，不要 Markdown。\n\n"
            "摘要要保留：用户目标、进行中的任务、关键约束、未解决问题、用户明确偏好、最近重要结论。"
            "删除：寒暄、重复内容、工具原始输出、已经过期的一次性细节。"
            "existing_summary 已经按日期保存；summary 只写本次历史压缩后仍需保留或更新的当日内容，"
            "不要原样复制旧日期摘要。相关内容要合并成短句，避免堆叠流水账。"
            "keep_message_indices 只保留需要作为原文继续带入的最近消息，优先保留最新用户请求和助手结论；"
            "不要保留 tool 消息。"
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]

    def _fallback_conversation_summary(
        self,
        *,
        existing_summary: str,
        history: list[LLMMessage],
    ) -> str:
        parts: list[str] = []
        for message in history[-12:]:
            if message.role not in {"user", "assistant"}:
                continue
            payload = self._memory_message_payload(message, 0)
            content = str(payload.get("content") or "").strip()
            if not content:
                continue
            parts.append(f"{message.role}: {content[:260]}")
        if not parts and existing_summary:
            return existing_summary[-1200:].strip()
        return "\n".join(parts)[-1200:].strip()

    def _select_compaction_keep_messages(
        self,
        *,
        raw: dict[str, Any] | None,
        history: list[LLMMessage],
        keep_messages: int,
    ) -> list[LLMMessage]:
        selected: list[LLMMessage] = []
        raw_indices = raw.get("keep_message_indices") if isinstance(raw, dict) else None
        if isinstance(raw_indices, list):
            seen: set[int] = set()
            for value in raw_indices:
                try:
                    index = int(value)
                except (TypeError, ValueError):
                    continue
                if index in seen or index < 0 or index >= len(history):
                    continue
                seen.add(index)
                message = history[index]
                if message.role not in {"user", "assistant"} or message.tool_calls:
                    continue
                selected.append(message)
                if len(selected) >= keep_messages:
                    break

        if selected:
            return selected

        recent = [
            message
            for message in history
            if message.role in {"user", "assistant"} and not message.tool_calls
        ]
        return recent[-keep_messages:]

    async def _maybe_compact_conversation_memory(
        self,
        *,
        request: ChatRequest,
        run_id: str,
        expected_message_count: int | None = None,
    ) -> None:
        if not request.memory_enabled:
            return
        conversation_memory_id = self._conversation_memory_id(request)
        threshold = max(1, self.conversation_compaction_threshold)
        current_message_count = len(self.memory.get(conversation_memory_id))
        if (
            expected_message_count is not None
            and current_message_count != expected_message_count
        ):
            if current_message_count > threshold:
                self.trace_store.append_event(
                    run_id,
                    type="memory.compaction.skipped",
                    status="completed",
                    title="Conversation memory compaction skipped",
                    payload={
                        "reason": "superseded_by_newer_turn",
                        "conversation_id": request.conversation_id,
                        "expected_message_count": expected_message_count,
                        "current_message_count": current_message_count,
                    },
                )
            return
        if not self.memory.needs_compaction(conversation_memory_id, threshold=threshold):
            return

        history = self.memory.get(conversation_memory_id)
        existing_summary = self.memory.get_summary(conversation_memory_id)
        keep_messages = max(2, self.conversation_compaction_keep_messages)
        started = perf_counter()
        self.trace_store.append_event(
            run_id,
            type="memory.compaction.started",
            status="running",
            title="Conversation memory compaction started",
            payload={
                "conversation_id": request.conversation_id,
                "message_count": len(history),
                "existing_summary_chars": len(existing_summary),
            },
        )
        try:
            provider = self._get_provider(request.model_preference)
            response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=self._conversation_compaction_messages(
                    conversation_id=request.conversation_id,
                    existing_summary=existing_summary,
                    history=history,
                    keep_messages=keep_messages,
                ),
                tools=None,
                temperature=0.1,
                retry_context={"scope": "memory_compaction"},
            )
            raw = self._extract_json_object(response.content)
            should_compact = True
            if isinstance(raw, dict) and isinstance(raw.get("should_compact"), bool):
                should_compact = bool(raw["should_compact"])
            if not should_compact:
                self.trace_store.append_event(
                    run_id,
                    type="memory.compaction.skipped",
                    status="completed",
                    title="Conversation memory compaction skipped",
                    payload={"reason": "ai_decision", "model": response.model},
                    duration_ms=int((perf_counter() - started) * 1000),
                )
                return
            summary = (
                str(raw.get("summary") or "").strip()
                if isinstance(raw, dict)
                else ""
            )
            if not summary:
                summary = self._fallback_conversation_summary(
                    existing_summary=existing_summary,
                    history=history,
                )
            summary = summary[:1200]
            kept = self._select_compaction_keep_messages(
                raw=raw,
                history=history,
                keep_messages=keep_messages,
            )
            self.memory.compact(
                conversation_memory_id,
                summary=summary,
                keep_messages=kept,
            )
            self.trace_store.append_event(
                run_id,
                type="memory.compaction.completed",
                status="completed",
                title="Conversation memory compacted",
                payload={
                    "conversation_id": request.conversation_id,
                    "before_count": len(history),
                    "after_count": len(kept),
                    "summary_chars": len(summary),
                    "model": response.model,
                    "usage": response.usage,
                },
                duration_ms=int((perf_counter() - started) * 1000),
            )
        except Exception as e:
            logger.exception("Conversation memory compaction failed")
            summary = self._fallback_conversation_summary(
                existing_summary=existing_summary,
                history=history,
            )
            summary = summary[:1200]
            kept = self._select_compaction_keep_messages(
                raw=None,
                history=history,
                keep_messages=keep_messages,
            )
            self.memory.compact(
                conversation_memory_id,
                summary=summary,
                keep_messages=kept,
            )
            self.trace_store.append_event(
                run_id,
                type="memory.compaction.failed",
                status="error",
                title="Conversation memory compaction failed; fallback used",
                payload={
                    "error_message": str(e),
                    "conversation_id": request.conversation_id,
                    "before_count": len(history),
                    "after_count": len(kept),
                },
                duration_ms=int((perf_counter() - started) * 1000),
            )

    def _collect_search_citations(
        self,
        *,
        result_data,
        citations: list[Citation],
        citation_urls: set[str],
    ) -> list[Citation]:
        if not isinstance(result_data, dict):
            return []

        raw_results = result_data.get("results")
        if not isinstance(raw_results, list):
            return []

        collected: list[Citation] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in citation_urls:
                continue

            citation_urls.add(url)
            citation = Citation(
                index=len(citations) + 1,
                title=str(item.get("title") or url).strip(),
                url=url,
                snippet=str(item.get("snippet") or "").strip(),
                source=str(item.get("source") or "").strip(),
                metadata=self._citation_metadata_from_search_item(item),
            )
            citations.append(citation)
            collected.append(citation)

        return collected

    def _append_search_trace_nodes(
        self,
        run_id: str,
        *,
        tool_call_id: str,
        result_data: Any,
        workflow_context: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(result_data, dict):
            return
        raw_nodes = result_data.get("search_trace")
        nodes = raw_nodes if isinstance(raw_nodes, list) else []
        if not nodes:
            rewrite = result_data.get("query_rewrite")
            if isinstance(rewrite, dict):
                queries = rewrite.get("queries") if isinstance(rewrite.get("queries"), list) else []
                nodes = [
                    {
                        "node": rewrite.get("node") or "query_rewrite",
                        "status": "completed",
                        "strategy": rewrite.get("strategy"),
                        "original_query": rewrite.get("original_query"),
                        "queries": queries,
                        "query_count": len(queries),
                    }
                ]

        for raw_node in nodes:
            if not isinstance(raw_node, dict):
                continue
            node_name = _safe_trace_node_name(str(raw_node.get("node") or "node"))
            status = str(raw_node.get("status") or "completed")
            payload = {
                "name": node_name,
                "tool": "search",
                **raw_node,
                "node": node_name,
            }
            if workflow_context:
                payload.update(workflow_context)
            duration_ms = raw_node.get("duration_ms")
            self.trace_store.append_event(
                run_id,
                type=f"search.{node_name}.{_trace_status_suffix(status)}",
                status=status,
                title=f"Search {node_name} {status}",
                step_id=tool_call_id,
                payload=payload,
                duration_ms=duration_ms if isinstance(duration_ms, int) else None,
            )

    def _collect_open_url_citation(
        self,
        *,
        result_data,
        citations: list[Citation],
        citation_urls: set[str],
    ) -> Citation | None:
        if not isinstance(result_data, dict):
            return None
        page = result_data.get("page")
        if not isinstance(page, dict):
            return None
        url = str(page.get("final_url") or page.get("url") or "").strip()
        if not url or url in citation_urls:
            return None
        citation_urls.add(url)
        citation = Citation(
            index=len(citations) + 1,
            title=str(page.get("title") or url).strip(),
            url=url,
            snippet=str(page.get("description") or page.get("content") or "").strip()[:900],
            source="open_url",
            metadata={
                "status_code": page.get("status_code"),
                "content_type": page.get("content_type"),
                "direct_url_open": True,
            },
        )
        citations.append(citation)
        return citation

    def _citation_metadata_from_search_item(self, item: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
        top_level_map = {
            "image_url": "image_url",
            "imageUrl": "image_url",
            "image": "image_url",
            "thumbnail_url": "thumbnail_url",
            "thumbnailUrl": "thumbnail_url",
            "thumbnail": "thumbnail_url",
            "poster": "thumbnail_url",
            "cover": "thumbnail_url",
            "video_url": "video_url",
            "videoUrl": "video_url",
            "video": "video_url",
            "media_url": "media_url",
            "mediaUrl": "media_url",
            "media_type": "media_type",
        }
        for source_key, target_key in top_level_map.items():
            value = item.get(source_key)
            if value and not metadata.get(target_key):
                metadata[target_key] = value

        if metadata.get("thumbnail_url") and not metadata.get("image_url"):
            metadata["image_url"] = metadata["thumbnail_url"]
        if metadata.get("video_url"):
            metadata.setdefault("media_url", metadata["video_url"])
            metadata.setdefault("media_type", "video")
        elif metadata.get("image_url"):
            metadata.setdefault("media_url", metadata["image_url"])
            metadata.setdefault("media_type", "image")
        return metadata

    async def _review_and_store_memories(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_context: MemoryContext,
        assistant_message: str,
        new_messages: list[LLMMessage],
        run_id: str,
    ) -> list[MemoryRecord]:
        if not request.memory_enabled or not role_context.role.memory_enabled:
            return []

        try:
            if self.ai_memory_review_enabled:
                candidates = await self._review_turn_with_ai(
                    request=request,
                    agent_id=agent_id,
                    role_context=role_context,
                    assistant_message=assistant_message,
                    new_messages=new_messages,
                    run_id=run_id,
                )
            else:
                candidates = await self.memory_hook.review_turn(
                    role=role_context.role,
                    agent_id=agent_id,
                    conversation_id=request.conversation_id,
                    user_message=request.message,
                    assistant_message=assistant_message,
                    new_messages=new_messages,
                )
        except Exception as e:
            logger.exception("AI memory review failed")
            self.trace_store.append_event(
                run_id,
                type="memory.review.failed",
                status="error",
                title="AI memory review failed; memory write skipped",
                payload={"error_message": str(e), "role_id": role_context.role.id},
            )
            return []

        self.trace_store.append_event(
            run_id,
            type="memory.candidates.created",
            status="completed",
            title="Memory candidates created",
            payload={
                "role_id": role_context.role.id,
                "candidate_count": len(candidates),
                "candidates": [
                    self._memory_candidate_trace_payload(candidate)
                    for candidate in candidates
                ],
            },
        )

        candidates, rejected_candidates = self._filter_memory_candidates(candidates)
        if rejected_candidates:
            self.trace_store.append_event(
                run_id,
                type="memory.candidates.filtered",
                status="completed",
                title="Low-signal memory candidates filtered",
                payload={
                    "role_id": role_context.role.id,
                    "rejected_count": len(rejected_candidates),
                    "kept_count": len(candidates),
                    "rejected": rejected_candidates,
                },
            )

        updates: list[MemoryRecord] = []
        for candidate in candidates:
            try:
                source_trace = {
                    "run_id": run_id,
                    "conversation_id": request.conversation_id,
                    "agent_id": agent_id,
                    "role_id": role_context.role.id,
                }
                metadata = {
                    **candidate.metadata,
                    "reason": candidate.reason,
                    "conversation_id": request.conversation_id,
                    "agent_id": agent_id,
                    "memory_action": candidate.action,
                }
                if candidate.action == "update" and candidate.target_id:
                    updates.append(
                        self.role_memory.update_memory(
                            role_id=role_context.role.id,
                            memory_id=candidate.target_id,
                            request=MemoryUpdateRequest(
                                user_id=self._user_id(request),
                                kind=candidate.kind,
                                status="active",
                                review_state="auto_accepted",
                                content=candidate.content,
                                source="hook",
                                agent_id=candidate.agent_id,
                                confidence=candidate.confidence,
                                tags=candidate.tags,
                                source_trace=source_trace,
                                metadata=metadata,
                            ),
                        )
                    )
                else:
                    updates.append(
                        self.role_memory.add_memory(
                            role_id=role_context.role.id,
                            user_id=self._user_id(request),
                            kind=candidate.kind,
                            scope="user",
                            status="active",
                            review_state="auto_accepted",
                            content=candidate.content,
                            source="hook",
                            agent_id=candidate.agent_id,
                            confidence=candidate.confidence,
                            tags=candidate.tags,
                            source_trace=source_trace,
                            metadata=metadata,
                        )
                    )
            except Exception as e:
                logger.exception("Failed to store memory")
                self.trace_store.append_event(
                    run_id,
                    type="memory.failed",
                    status="error",
                    title="Memory store failed",
                    payload={
                        "error_message": str(e),
                        "role_id": role_context.role.id,
                        "candidate": candidate.model_dump(),
                    },
                )

        self.trace_store.append_event(
            run_id,
            type="memory.extracted",
            status="completed",
            title="Memory review completed",
            payload={
                "role_id": role_context.role.id,
                "candidate_count": len(candidates),
                "stored_count": len(updates),
                "memory_ids": [record.id for record in updates],
                "stored_records": [
                    self._memory_trace_payload(record)
                    for record in updates
                ],
            },
        )
        return updates

    def _aigc_professional_mode_enabled(self, request: ChatRequest) -> bool:
        mode_ids = set(request.mode_ids or [])
        if AIGC_REFINE_MODE_ID in mode_ids:
            return True
        mode_text = "\n".join(request.mode_prompts or []).lower()
        return "专业修饰" in mode_text or "prompt refine" in mode_text

    def _parse_aigc_command(
        self,
        request: ChatRequest,
        *,
        allow_prompt_fallback: bool = False,
    ) -> dict[str, Any] | None:
        text = (request.message or "").strip()
        if not text.startswith("/"):
            return None
        match = re.match(r"^/([^\s/]+)(?:\s+([\s\S]*))?$", text)
        if not match:
            return None

        raw_command = match.group(1).strip()
        args = (match.group(2) or "").strip()
        normalized = raw_command.lower()
        command = ""
        if normalized in AIGC_GENERATE_COMMANDS:
            command = "generate"
        elif normalized in AIGC_REFINE_COMMANDS:
            command = "refine"
        elif normalized in AIGC_REFERENCE_COMMANDS:
            command = "reference"
        elif normalized in AIGC_HELP_COMMANDS:
            command = "help"
        elif allow_prompt_fallback:
            command = "generate"
            args = f"{raw_command} {args}".strip()
        else:
            return None

        return {
            "protocol_version": "agent_command.v1",
            "command": command,
            "raw_command": raw_command,
            "args": args,
            "original_message": text,
            "prompt_fallback": command == "generate" and normalized not in AIGC_GENERATE_COMMANDS,
        }

    def _apply_aigc_command_to_request(self, request: ChatRequest, command: dict[str, Any]) -> ChatRequest:
        command_name = str(command.get("command") or "")
        args = str(command.get("args") or "").strip()
        mode_ids = list(request.mode_ids or [])
        mode_prompts = list(request.mode_prompts or [])
        message = args

        if not message and command_name in {"generate", "refine", "reference"}:
            message = self._aigc_attachment_prompt_seed(request.attachments)
        if not message and command_name == "reference":
            message = "请基于上传参考素材生成一张新的图片。"

        if command_name in {"refine", "reference"} and AIGC_REFINE_MODE_ID not in mode_ids:
            mode_ids.append(AIGC_REFINE_MODE_ID)

        return request.model_copy(
            update={
                "message": message,
                "mode_ids": mode_ids,
                "mode_prompts": mode_prompts,
            }
        )

    def _render_aigc_command_help(self) -> str:
        return (
            "AI 生图命令：\n"
            "- `/generate <提示词>`：直接生成图片。\n"
            "- `/refine <提示词>`：先专业修饰提示词，再生成图片。\n"
            "- `/reference <提示词>`：结合上传参考素材生成新图片。\n"
            "- `/help`：查看可用命令。\n\n"
            "在 Super Chat 里也可以使用 `/生图 /generate ...` 或 `/生图 /refine ...`。"
        )

    def _should_delegate_to_deep_research(self, request: ChatRequest, agent_id: str) -> tuple[bool, str, bool]:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return False, "", False
        mode_ids = set(request.mode_ids or [])
        if DEEP_RESEARCH_MODE_ID in mode_ids:
            return True, "mode", True
        return False, "", False

    def _normalize_agent_command_alias(self, value: str) -> str:
        return re.sub(r"[\s_\-]+", "", str(value or "").lower()).strip()

    def _agent_command_aliases(self, agent: AgentInfo) -> set[str]:
        aliases = {
            agent.id,
            agent.id.replace("_v1", ""),
            agent.id.replace("_", "-"),
            agent.name,
        }
        metadata = agent.metadata or {}
        if metadata.get("agent_type"):
            aliases.add(str(metadata["agent_type"]))
        command_protocol = metadata.get("command_protocol") if isinstance(metadata.get("command_protocol"), dict) else {}
        for alias in command_protocol.get("aliases") or []:
            aliases.add(str(alias))
        return {self._normalize_agent_command_alias(alias) for alias in aliases if str(alias).strip()}

    def _agent_command_candidates(self) -> list[AgentInfo]:
        return [
            agent
            for agent in list_agents()
            if agent.id != SUPER_CHAT_AGENT_ID
            and agent.id != RESEARCH_AGENT_ID
            and agent.runtime == "self"
            and bool((agent.metadata or {}).get("command_protocol"))
        ]

    def _parse_agent_command_parts(self, message: str) -> tuple[str, str] | None:
        text = (message or "").strip()
        if not text.startswith("/"):
            return None

        explicit = re.match(r"^/(?:agent|agent:|a)\s+([^\s]+)\s+(.+)$", text, flags=re.IGNORECASE | re.DOTALL)
        if explicit:
            return explicit.group(1).strip(), explicit.group(2).strip()

        nested = re.match(r"^/([^\s/]+)/(.+)$", text, flags=re.DOTALL)
        if nested:
            return nested.group(1).strip(), nested.group(2).strip()

        implicit = re.match(r"^/([^\s/]+)\s+(.+)$", text, flags=re.DOTALL)
        if implicit:
            return implicit.group(1).strip(), implicit.group(2).strip()

        return None

    def _is_deep_research_command_attempt(self, request: ChatRequest, agent_id: str) -> bool:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return False
        parts = self._parse_agent_command_parts(request.message)
        if parts is None:
            return False
        target_token, _command_text = parts
        target_agent = get_agent(RESEARCH_AGENT_ID)
        if target_agent is None:
            return False
        legacy_aliases = {
            self._normalize_agent_command_alias(alias)
            for alias in {
                "research",
                "deep-research",
                "deep_research",
                "researcher",
                "调研",
                "研究",
                "深度研究",
            }
        }
        blocked_aliases = set(self._agent_command_aliases(target_agent)) | legacy_aliases
        return self._normalize_agent_command_alias(target_token) in blocked_aliases

    def _parse_agent_command_protocol(self, request: ChatRequest, agent_id: str) -> dict[str, Any] | None:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return None
        parts = self._parse_agent_command_parts(request.message)
        if parts is None:
            return None
        target_token, command_text = parts
        text = (request.message or "").strip()

        if not command_text.startswith("/"):
            command_text = "/" + command_text
        normalized_target = self._normalize_agent_command_alias(target_token)
        for target_agent in self._agent_command_candidates():
            if normalized_target in self._agent_command_aliases(target_agent):
                command_name = ""
                command_match = re.match(r"^/([^\s/]+)", command_text)
                if command_match:
                    command_name = command_match.group(1).lower()
                return {
                    "protocol_version": "agent_command.v1",
                    "source_agent_id": agent_id,
                    "target_agent_id": target_agent.id,
                    "target_alias": target_token,
                    "command_text": command_text,
                    "command_name": command_name,
                    "original_message": text,
                }
        return None

    def _append_agent_command_route_trace(self, run_id: str, route: dict[str, Any]) -> None:
        self.trace_store.append_event(
            run_id,
            type="agent.command.routed",
            status="completed",
            title="Agent command routed",
            payload=route,
        )

    def _disabled_tool_names(self, request: ChatRequest) -> set[str]:
        return {
            str(name).strip()
            for name in (request.disabled_tools or [])
            if str(name).strip()
        }

    def _tool_definitions_for_agent(
        self,
        agent_id: str,
        disabled_tools: set[str] | list[str] | None = None,
    ) -> list[ToolDefinition]:
        disabled = {
            str(name).strip()
            for name in (disabled_tools or [])
            if str(name).strip()
        }
        return [
            tool
            for tool in self.skill_registry.get_tool_definitions()
            if tool.name not in disabled
            if tool.name not in DRIVE_TOOL_NAMES or agent_id == SUPER_CHAT_AGENT_ID
            if tool.name not in PULSE_TOOL_NAMES or agent_id == SUPER_CHAT_AGENT_ID
            if tool.name not in TODO_TOOL_NAMES or agent_id == SUPER_CHAT_AGENT_ID
            if tool.name not in AGENT_TOOL_IDS or agent_id == SUPER_CHAT_AGENT_ID
        ]

    def _tool_arguments_for_execution(
        self,
        request: ChatRequest,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]:
        tool_arguments = dict(arguments) if isinstance(arguments, dict) else {}
        if (
            tool_name in DRIVE_TOOL_NAMES
            or tool_name in PULSE_TOOL_NAMES
            or tool_name in TODO_TOOL_NAMES
        ):
            tool_arguments["_user_id"] = self._user_id(request)
        if tool_name in TODO_TOOL_NAMES:
            tool_arguments["_conversation_id"] = request.conversation_id
            if request.run_id:
                tool_arguments["_run_id"] = request.run_id
        return tool_arguments

    def _tool_arguments_for_trace(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized = dict(arguments) if isinstance(arguments, dict) else {}
        skill = self.skill_registry.get(tool_name)
        if skill is None:
            return {
                key: value
                for key, value in normalized.items()
                if not key.startswith("_")
            }
        return self.tool_governance.redact_arguments(skill, normalized)

    async def _execute_skill_with_governance(
        self,
        *,
        request: ChatRequest,
        run_id: str,
        skill_name: str,
        arguments: dict[str, Any],
        trusted: bool = False,
        step_id: str | None = None,
    ) -> SkillResult:
        skill = self.skill_registry.get(skill_name)
        if skill is None:
            return SkillResult(success=False, error=f"Unknown skill: {skill_name}")
        return await self.tool_governance.execute(
            skill=skill,
            request=request,
            run_id=run_id,
            arguments=arguments,
            trusted=trusted,
            step_id=step_id,
        )

    def _append_unique_artifact(self, artifacts: list[ChatArtifact], artifact: ChatArtifact | None) -> None:
        if artifact is None:
            return
        if artifact.item_id and any(existing.item_id == artifact.item_id for existing in artifacts):
            return
        artifacts.append(artifact)

    def _merge_agent_tool_payload(
        self,
        *,
        payload: Any,
        skills_used: list[str],
        citations: list[Citation],
        citation_urls: set[str],
        artifacts: list[ChatArtifact],
    ) -> None:
        if not isinstance(payload, dict):
            return
        for skill in payload.get("skills_used") or []:
            skill_name = str(skill or "").strip()
            if skill_name:
                skills_used.append(skill_name)
        for raw_citation in payload.get("citations") or []:
            if not isinstance(raw_citation, dict):
                continue
            try:
                citation = Citation(**raw_citation)
            except Exception:
                continue
            if citation.url and citation.url in citation_urls:
                continue
            if citation.url:
                citation_urls.add(citation.url)
            citations.append(citation)
        for raw_artifact in payload.get("artifacts") or []:
            if not isinstance(raw_artifact, dict):
                continue
            try:
                self._append_unique_artifact(artifacts, ChatArtifact(**raw_artifact))
            except Exception:
                continue

    def _drive_artifact_from_tool_result(
        self,
        tool_name: str,
        result_data: Any,
    ) -> ChatArtifact | None:
        if tool_name not in {
            "save_drive",
            "update_drive",
            "mkdir_drive",
            "archive_url_to_drive",
            "share_drive",
        } or not isinstance(result_data, dict):
            return None
        item = result_data.get("item")
        if not isinstance(item, dict):
            return None
        item_type = str(item.get("type") or "")
        if tool_name in {"save_drive", "archive_url_to_drive", "share_drive"} and item_type != "file":
            return None
        if tool_name == "mkdir_drive" and item_type != "folder":
            return None
        if tool_name == "update_drive" and item_type not in {"file", "folder"}:
            return None
        item_id = str(item.get("id") or "")
        name = str(item.get("name") or "")
        if not item_id and not name:
            return None
        return ChatArtifact(
            type="drive_folder" if item_type == "folder" else "drive_file",
            item_id=item_id,
            name=name,
            title=name,
            mime_type=str(item.get("mime_type") or ""),
            size=int(item.get("size") or 0),
            summary=str(item.get("summary") or ""),
            url=str(result_data.get("share_url") or ""),
            metadata={
                "parent_id": str(item.get("parent_id") or ""),
                "path": str(item.get("path") or ""),
                "updated_at": str(item.get("updated_at") or ""),
                "source_tool": tool_name,
            },
        )

    def _save_drive_tool_definition(self, tools: list[ToolDefinition]) -> ToolDefinition | None:
        for tool in tools:
            if tool.name == "save_drive":
                return tool
        skill = self.skill_registry.get("save_drive")
        if skill is not None:
            definition = skill.to_tool_definition()
            return ToolDefinition(
                name=definition["name"],
                description=definition["description"],
                parameters=definition["parameters"],
            )
        return None

    def _drive_auto_save_candidate(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        final_content: str,
        skills_used: list[str],
        citations: list[Citation],
        existing_artifacts: list[ChatArtifact],
    ) -> bool:
        if agent_id not in {SUPER_CHAT_AGENT_ID, RESEARCH_AGENT_ID}:
            return False
        if any(artifact.type == "drive_file" for artifact in existing_artifacts):
            return False
        content = str(final_content or "").strip()
        if len(content) < 500:
            return False
        message = str(request.message or "").lower()
        negative_save_keywords = [
            "不要保存",
            "不用保存",
            "别保存",
            "不要归档",
            "不用归档",
            "do not save",
            "don't save",
            "do not archive",
            "no need to save",
        ]
        if any(keyword in message for keyword in negative_save_keywords):
            return False
        if agent_id == RESEARCH_AGENT_ID and citations:
            return True
        explicit_save_keywords = [
            "保存到",
            "保存至",
            "请保存",
            "帮我保存",
            "保存一下",
            "并保存",
            "后保存",
            "归档到",
            "请归档",
            "帮我归档",
            "归档一下",
            "存到网盘",
            "存入网盘",
            "写入网盘",
            "放到网盘",
            "写到 drive",
            "save to drive",
            "save this",
            "archive this",
            "archive to drive",
        ]
        return any(keyword in message for keyword in explicit_save_keywords)

    def _drive_auto_save_messages(
        self,
        *,
        request: ChatRequest,
        final_content: str,
        citations: list[Citation],
    ) -> list[LLMMessage]:
        source_lines = []
        for citation in citations[:20]:
            label = citation.title or citation.url
            if label:
                source_lines.append(f"- {label}: {citation.url}")
        source_text = "\n".join(source_lines) or "无结构化来源。"
        system = (
            "你是一个谨慎的网盘归档节点。当前请求已经明确要求保存或归档，调用 save_drive。"
            "生成简洁可读的 Markdown 文件名，默认保存到 /知识库；正文应包含用户问题、"
            "助手最终回答、保存时间和来源列表。不要调用除 save_drive 以外的工具。"
        )
        user = (
            f"用户原始请求：\n{request.message}\n\n"
            f"助手最终回答：\n{final_content[:30000]}\n\n"
            f"来源：\n{source_text}\n\n"
            "请调用 save_drive 保存这份知识文档。"
        )
        return [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)]

    async def _maybe_auto_save_drive_report(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        provider: LLMProvider,
        run_id: str,
        tools: list[ToolDefinition],
        final_content: str,
        skills_used: list[str],
        citations: list[Citation],
        artifacts: list[ChatArtifact],
        plan: list[SkillCallInfo],
    ) -> None:
        save_tool = self._save_drive_tool_definition(tools)
        if save_tool is None or self.skill_registry.get("save_drive") is None:
            return
        if not self._drive_auto_save_candidate(
            request=request,
            agent_id=agent_id,
            final_content=final_content,
            skills_used=skills_used,
            citations=citations,
            existing_artifacts=artifacts,
        ):
            return

        model_started = perf_counter()
        self.trace_store.append_event(
            run_id,
            type="drive.auto_save.model.started",
            status="running",
            title="Drive auto-save decision",
            payload={
                "message_count": 2,
                "tools_count": 1,
                "model_preference": request.model_preference,
                "candidate": True,
            },
        )
        try:
            decision = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=self._drive_auto_save_messages(
                    request=request,
                    final_content=final_content,
                    citations=citations,
                ),
                tools=[save_tool],
                temperature=0.1,
                retry_context={"scope": "drive_auto_save"},
            )
        except Exception as e:
            logger.warning("Drive auto-save decision failed: %s", e)
            self.trace_store.append_event(
                run_id,
                type="drive.auto_save.model.failed",
                status="error",
                title="Drive auto-save decision failed",
                payload={"error_message": str(e)},
                duration_ms=int((perf_counter() - model_started) * 1000),
            )
            return

        self.trace_store.append_event(
            run_id,
            type="drive.auto_save.model.completed",
            status="completed",
            title="Drive auto-save decision completed",
            payload={
                "tool_calls": [{"id": tc.id, "name": tc.name} for tc in decision.tool_calls],
                "content_preview": decision.content[:300],
            },
            duration_ms=int((perf_counter() - model_started) * 1000),
        )
        save_call = next((tc for tc in decision.tool_calls if tc.name == "save_drive"), None)
        if save_call is None:
            return

        tool_started = perf_counter()
        tool_arguments = self._tool_arguments_for_execution(request, save_call.name, save_call.arguments)
        self.trace_store.append_event(
            run_id,
            type="tool.started",
            status="running",
            title="Tool save_drive",
            step_id=save_call.id,
            payload={
                "name": save_call.name,
                "arguments": self._tool_arguments_for_trace(save_call.name, tool_arguments),
                "engine_context": {"user_id": self._user_id(request)},
                "auto_save": True,
            },
        )
        result_text = ""
        status = "error"
        try:
            result = await self._execute_skill_with_governance(
                request=request,
                run_id=run_id,
                skill_name="save_drive",
                arguments=tool_arguments,
                trusted=True,
                step_id=save_call.id,
            )
            result_text = json.dumps(
                {
                    "success": result.success,
                    "data": result.data,
                    "display_text": result.display_text,
                    "error": result.error,
                },
                ensure_ascii=False,
            )
            status = "completed" if result.success else "error"
            if result.success:
                skills_used.append("save_drive")
                self._append_unique_artifact(
                    artifacts,
                    self._drive_artifact_from_tool_result("save_drive", result.data),
                )
        except Exception as e:
            logger.exception("Drive auto-save execution failed")
            result_text = json.dumps({"error": str(e)}, ensure_ascii=False)
            status = "error"

        self.trace_store.append_event(
            run_id,
            type="tool.completed" if status == "completed" else "tool.failed",
            status=status,
            title=f"Tool save_drive {status}",
            step_id=save_call.id,
            payload={
                "name": "save_drive",
                "arguments": self._tool_arguments_for_trace("save_drive", tool_arguments),
                "result_preview": result_text[:500],
                "auto_save": True,
            },
            duration_ms=int((perf_counter() - tool_started) * 1000),
        )
        plan.append(
            SkillCallInfo(
                skill="save_drive",
                action=str(save_call.arguments),
                status=status,
                result_summary=result_text[:200],
            )
        )

    def _agent_tool_target(self, tool_name: str) -> AgentInfo | None:
        if tool_name not in AGENT_TOOL_IDS:
            return None
        agent = get_agent(tool_name)
        if agent is None or not agent.enabled or agent.runtime != "self":
            return None
        return agent

    async def _execute_agent_tool_as_result(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        run_id: str,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, Any],
        tool_started: float,
        workflow_context: dict[str, Any] | None = None,
    ) -> SkillResult:
        target_agent = self._agent_tool_target(tool_name)
        if target_agent is None:
            error_msg = f"Unknown or unavailable agent tool: {tool_name}"
            return SkillResult(
                success=False,
                error=error_msg,
                data={"agent_id": tool_name, "error_type": "unknown_agent_tool"},
                display_text=error_msg,
            )

        task = str(arguments.get("task") or request.message or "").strip() or request.message
        context = str(arguments.get("context") or "").strip()
        reason = str(arguments.get("reason") or f"agent_tool:{target_agent.id}").strip() or f"agent_tool:{target_agent.id}"
        delegated_context_blocks = list(request.context_blocks or [])
        context_lines = [
            "Agent tool context:",
            f"- Source agent: {request.agent_id or SUPER_CHAT_AGENT_ID}",
            f"- Tool/target agent: {target_agent.id}",
            f"- Reason: {reason}",
            "",
            "Original user request:",
            request.message or "",
        ]
        if context:
            context_lines.extend(["", "Additional context:", context])
        delegated_context_blocks.append("\n".join(context_lines).strip())

        workflow = str(workflow_context.get("workflow") or "").strip() if workflow_context else ""
        workflow_node = (
            str(workflow_context.get("node") or workflow_context.get("workflow_node") or "").strip()
            if workflow_context
            else ""
        )
        parent_history = (
            self.memory.get_context(self._conversation_memory_id(request)).messages
            if request.memory_enabled
            else []
        )
        handoff_packet = self._build_agent_handoff_packet(
            request=request.model_copy(update={"context_blocks": delegated_context_blocks}),
            source_agent_id=request.agent_id or SUPER_CHAT_AGENT_ID,
            target_agent_id=target_agent.id,
            history=parent_history,
            delegation_trace={
                "source_agent_id": request.agent_id or SUPER_CHAT_AGENT_ID,
                "target_agent_id": target_agent.id,
                "reason": reason,
                "forced": False,
                "mode_ids": request.mode_ids,
                "protocol_version": "agent_tool.v1",
                "tool_name": target_agent.id,
                "original_message": request.message,
                "task": task,
            },
        )
        child_run = self.trace_store.start_run(
            conversation_id=request.conversation_id,
            user_id=self._user_id(request),
            input_text=task,
            agent_id=target_agent.id,
            runtime=target_agent.runtime,
        )
        parent_delegation_payload = {
            "source_run_id": run_id,
            "child_run_id": child_run.run_id,
            "tool_call_id": tool_call_id,
            "name": target_agent.id,
            "arguments": arguments,
            "target_agent_id": target_agent.id,
            "reason": reason,
            "protocol_version": "agent_tool.v1",
        }
        if workflow:
            parent_delegation_payload["workflow"] = workflow
        if workflow_node:
            parent_delegation_payload["workflow_node"] = workflow_node
        self.trace_store.append_event(
            run_id,
            type="agent.tool.delegated",
            status="completed",
            title=f"Agent tool {target_agent.id} delegated",
            step_id=tool_call_id,
            payload=parent_delegation_payload,
        )

        delegated_request = request.model_copy(
            update={
                "agent_id": target_agent.id,
                "message": task,
                "mode_ids": request.mode_ids,
                "mode_prompts": request.mode_prompts,
                "context_blocks": delegated_context_blocks,
                "agent_input": handoff_packet,
                "handoff": handoff_packet,
                "memory_enabled": False,
            }
        )
        try:
            response = await self._process_target_agent(
                request=delegated_request,
                target_agent=target_agent,
                run_id=child_run.run_id,
                source_role_context=role_context,
                delegation_trace={
                    "source_agent_id": request.agent_id or SUPER_CHAT_AGENT_ID,
                    "source_run_id": run_id,
                    "target_agent_id": target_agent.id,
                    "reason": reason,
                    "forced": False,
                    "mode_ids": request.mode_ids,
                    "protocol_version": "agent_tool.v1",
                    "tool_name": target_agent.id,
                    "tool_call_id": tool_call_id,
                    "original_message": request.message,
                    "task": task,
                },
            )
        except Exception as exc:
            logger.exception("Agent tool workflow failed")
            error_msg = str(exc)
            self.trace_store.fail_run(
                child_run.run_id,
                error_message=error_msg,
                error_type="agent_tool_error",
                output=error_msg,
            )
            return SkillResult(
                success=False,
                error=error_msg,
                data={
                    "agent_id": target_agent.id,
                    "child_run_id": child_run.run_id,
                    "error_type": "agent_tool_error",
                },
                display_text=error_msg,
            )

        payload = {
            "agent_id": target_agent.id,
            "child_run_id": child_run.run_id,
            "task": task,
            "reason": reason,
            "response": response.response[:12000],
            "skills_used": list(dict.fromkeys([target_agent.id, *response.skills_used])),
            "citations": [citation.model_dump(mode="json") for citation in response.citations],
            "artifacts": [artifact.model_dump(mode="json") for artifact in response.artifacts],
            "plan": [item.model_dump(mode="json") for item in (response.plan or [])],
            "model_used": response.model_used,
            "tokens_used": response.tokens_used,
            "error_type": response.error_type,
        }
        return SkillResult(
            success=not bool(response.error_type),
            error=response.error_type,
            data=payload,
            display_text=response.response[:2000],
        )

    async def _execute_agent_tool_with_governance(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        run_id: str,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, Any],
        tool_started: float,
        workflow_context: dict[str, Any] | None = None,
    ) -> SkillResult:
        skill = self.skill_registry.get(tool_name)
        if skill is None:
            return SkillResult(success=False, error=f"Unknown skill: {tool_name}")
        decision = self.tool_governance.authorize(
            skill=skill,
            request=request,
            run_id=run_id,
            arguments=arguments,
            step_id=tool_call_id,
        )
        if not decision.allowed:
            return self.tool_governance.blocked_result(decision)
        timeout_seconds = skill.metadata().timeout_seconds
        try:
            return await asyncio.wait_for(
                self._execute_agent_tool_as_result(
                    request=request,
                    role_context=role_context,
                    run_id=run_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    arguments=arguments,
                    tool_started=tool_started,
                    workflow_context=workflow_context,
                ),
                timeout=timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError):
            return self.tool_governance.record_timeout(
                decision=decision,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                step_id=tool_call_id,
            )

    @staticmethod
    def _skill_result_json(result: SkillResult) -> str:
        return json.dumps(
            {
                "success": result.success,
                "data": result.data,
                "display_text": result.display_text,
                "error": result.error,
            },
            ensure_ascii=False,
        )

    def _agent_loop_tool_workflow_payload(
        self,
        *,
        agent_loop_enabled: bool,
        workflow_name: str,
        workflow_node: str,
        workflow_source: str,
        legacy_workflow: str,
    ) -> dict[str, Any]:
        if not agent_loop_enabled:
            return {}
        return {
            "workflow": workflow_name,
            "workflow_node": workflow_node,
            "workflow_source": workflow_source,
            "legacy_workflow": legacy_workflow,
        }

    def _agent_loop_tool_delegate_context(
        self,
        *,
        agent_loop_enabled: bool,
        workflow_name: str,
        workflow_node: str,
        workflow_node_started: float | None,
        workflow_started: float | None,
        workflow_source: str,
        legacy_workflow: str,
        round_index: int,
    ) -> dict[str, Any] | None:
        if not agent_loop_enabled:
            return None
        return {
            "workflow": workflow_name,
            "node": workflow_node,
            "workflow_node": workflow_node,
            "node_started": workflow_node_started,
            "workflow_started": workflow_started,
            "round": round_index + 1,
            "result": "agent_tool_result",
            "workflow_source": workflow_source,
            "legacy_workflow": legacy_workflow,
        }

    @staticmethod
    def _parallel_read_only_tool_batch(
        tool_calls: list[ToolCall],
        start_index: int,
    ) -> list[ToolCall]:
        first = tool_calls[start_index]
        if first.name not in PARALLEL_READ_ONLY_TOOL_NAMES:
            return [first]
        batch: list[ToolCall] = []
        for tc in tool_calls[start_index:]:
            if tc.name not in PARALLEL_READ_ONLY_TOOL_NAMES:
                break
            if len(batch) >= MAX_PARALLEL_READ_ONLY_TOOL_CALLS:
                break
            batch.append(tc)
        return batch or [first]

    async def _execute_agent_loop_tool_call(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        run_id: str,
        tc: ToolCall,
        allowed_tool_names: set[str],
        agent_loop_enabled: bool,
        workflow_name: str,
        workflow_node: str,
        workflow_node_started: float | None,
        workflow_started: float | None,
        workflow_source: str,
        legacy_workflow: str,
        round_index: int,
    ) -> _AgentLoopToolExecution:
        tool_arguments = self._tool_arguments_for_execution(request, tc.name, tc.arguments)
        tool_started = perf_counter()
        workflow_payload = self._agent_loop_tool_workflow_payload(
            agent_loop_enabled=agent_loop_enabled,
            workflow_name=workflow_name,
            workflow_node=workflow_node,
            workflow_source=workflow_source,
            legacy_workflow=legacy_workflow,
        )
        tool_started_payload = {
            "name": tc.name,
            "arguments": self._tool_arguments_for_trace(tc.name, tool_arguments),
        }
        if (
            tc.name in DRIVE_TOOL_NAMES
            or tc.name in PULSE_TOOL_NAMES
            or tc.name in TODO_TOOL_NAMES
        ):
            tool_started_payload["engine_context"] = {"user_id": self._user_id(request)}
        tool_started_payload.update(workflow_payload)
        self.trace_store.append_event(
            run_id,
            type="tool.started",
            status="running",
            title=f"Tool {tc.name}",
            step_id=tc.id,
            payload=tool_started_payload,
        )

        skill = self.skill_registry.get(tc.name)
        result_text = ""
        status = "error"
        result_data: Any = None
        if tc.name not in allowed_tool_names:
            result_text = json.dumps({"error": f"Tool disabled or unavailable: {tc.name}"})
        elif tc.name in AGENT_TOOL_IDS:
            try:
                result = await self._execute_agent_tool_with_governance(
                    request=request,
                    role_context=role_context,
                    run_id=run_id,
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    arguments=tool_arguments,
                    tool_started=tool_started,
                    workflow_context=self._agent_loop_tool_delegate_context(
                        agent_loop_enabled=agent_loop_enabled,
                        workflow_name=workflow_name,
                        workflow_node=workflow_node,
                        workflow_node_started=workflow_node_started,
                        workflow_started=workflow_started,
                        workflow_source=workflow_source,
                        legacy_workflow=legacy_workflow,
                        round_index=round_index,
                    ),
                )
                result_data = result.data
                result_text = self._skill_result_json(result)
                status = "completed" if result.success else "error"
            except Exception as e:
                logger.exception(f"Agent tool {tc.name} execution failed")
                result_text = json.dumps({"error": str(e)}, ensure_ascii=False)
        elif skill is None:
            result_text = json.dumps({"error": f"Unknown skill: {tc.name}"})
        else:
            try:
                result = await self._execute_skill_with_governance(
                    request=request,
                    run_id=run_id,
                    skill_name=tc.name,
                    arguments=tool_arguments,
                    step_id=tc.id,
                )
                result_data = result.data
                result_text = self._skill_result_json(result)
                status = "completed" if result.success else "error"
            except Exception as e:
                logger.exception(f"Skill {tc.name} execution failed")
                result_text = json.dumps({"error": str(e)})

        return _AgentLoopToolExecution(
            tool_call=tc,
            tool_arguments=tool_arguments,
            result_text=result_text,
            status=status,
            result_data=result_data,
            duration_ms=int((perf_counter() - tool_started) * 1000),
        )

    def _finalize_agent_loop_tool_execution(
        self,
        *,
        run_id: str,
        execution: _AgentLoopToolExecution,
        agent_loop_enabled: bool,
        workflow_name: str,
        workflow_node: str,
        workflow_source: str,
        legacy_workflow: str,
        skills_used: list[str],
        citations: list[Citation],
        citation_urls: set[str],
        artifacts: list[ChatArtifact],
        plan: list[SkillCallInfo],
        messages: list[LLMMessage],
        all_new_messages: list[LLMMessage],
    ) -> None:
        tc = execution.tool_call
        workflow_payload = self._agent_loop_tool_workflow_payload(
            agent_loop_enabled=agent_loop_enabled,
            workflow_name=workflow_name,
            workflow_node=workflow_node,
            workflow_source=workflow_source,
            legacy_workflow=legacy_workflow,
        )

        if execution.status == "completed":
            if tc.name in AGENT_TOOL_IDS:
                self._merge_agent_tool_payload(
                    payload=execution.result_data,
                    skills_used=skills_used,
                    citations=citations,
                    citation_urls=citation_urls,
                    artifacts=artifacts,
                )
            else:
                skills_used.append(tc.name)
                self._append_unique_artifact(
                    artifacts,
                    self._drive_artifact_from_tool_result(tc.name, execution.result_data),
                )
                if tc.name == "search":
                    self._append_search_trace_nodes(
                        run_id,
                        tool_call_id=tc.id,
                        result_data=execution.result_data,
                        workflow_context=workflow_payload or None,
                    )
                    new_citations = self._collect_search_citations(
                        result_data=execution.result_data,
                        citations=citations,
                        citation_urls=citation_urls,
                    )
                    if new_citations:
                        self.trace_store.append_event(
                            run_id,
                            type="citations.collected",
                            status="completed",
                            title="Search citations collected",
                            step_id=tc.id,
                            payload={
                                "count": len(new_citations),
                                "total": len(citations),
                                "urls": [citation.url for citation in new_citations],
                            },
                        )
                elif tc.name == "open_url":
                    citation = self._collect_open_url_citation(
                        result_data=execution.result_data,
                        citations=citations,
                        citation_urls=citation_urls,
                    )
                    if citation:
                        self.trace_store.append_event(
                            run_id,
                            type="citations.collected",
                            status="completed",
                            title="Open URL citation collected",
                            step_id=tc.id,
                            payload={
                                "count": 1,
                                "total": len(citations),
                                "urls": [citation.url],
                            },
                        )

        tool_completed_payload = {
            "name": tc.name,
            "arguments": self._tool_arguments_for_trace(tc.name, execution.tool_arguments),
            "result_preview": execution.result_text[:500],
        }
        tool_completed_payload.update(workflow_payload)
        self.trace_store.append_event(
            run_id,
            type="tool.completed" if execution.status == "completed" else "tool.failed",
            status=execution.status,
            title=f"Tool {tc.name} {execution.status}",
            step_id=tc.id,
            payload=tool_completed_payload,
            duration_ms=execution.duration_ms,
        )

        plan.append(
            SkillCallInfo(
                skill=tc.name,
                action=str(tc.arguments),
                status=execution.status,
                result_summary=execution.result_text[:200],
            )
        )
        tool_msg = LLMMessage(
            role="tool",
            content=execution.result_text,
            tool_call_id=tc.id,
        )
        messages.append(tool_msg)
        all_new_messages.append(tool_msg)

    async def _process_target_agent(
        self,
        *,
        request: ChatRequest,
        target_agent: AgentInfo,
        run_id: str,
        source_role_context: MemoryContext,
        delegation_trace: dict[str, Any],
    ) -> ChatResponse:
        if not target_agent.enabled:
            error_msg = f"Agent '{target_agent.id}' is registered but not enabled."
            self.trace_store.fail_run(
                run_id,
                error_message=error_msg,
                error_type="agent_disabled",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run_id)
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="agent_disabled",
                agent_id=target_agent.id,
                role_id=request.role_id,
                runtime=target_agent.runtime,
                run_id=run_id,
                events=latest_run.events if latest_run else [],
                memory_context=source_role_context.records,
            )

        if target_agent.runtime != "self":
            error_msg = f"Agent '{target_agent.id}' uses runtime '{target_agent.runtime}', which is not wired to chat yet."
            self.trace_store.fail_run(
                run_id,
                error_message=error_msg,
                error_type="runtime_not_implemented",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run_id)
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="runtime_not_implemented",
                agent_id=target_agent.id,
                role_id=request.role_id,
                runtime=target_agent.runtime,
                run_id=run_id,
                events=latest_run.events if latest_run else [],
                memory_context=source_role_context.records,
            )

        target_role_id = self._resolve_role_id(request, target_agent.metadata)
        target_role_context = self.role_memory.get_context(
            role_id=target_role_id,
            user_id=self._user_id(request),
            agent_id=target_agent.id,
            query=self._memory_retrieval_query(request),
        )
        if target_role_context is None or not target_role_context.role.enabled:
            error_msg = f"Unknown or disabled role: {target_role_id}"
            self.trace_store.fail_run(
                run_id,
                error_message=error_msg,
                error_type="unknown_role",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run_id)
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="unknown_role",
                agent_id=target_agent.id,
                role_id=target_role_id,
                runtime=target_agent.runtime,
                run_id=run_id,
                events=latest_run.events if latest_run else [],
                memory_context=source_role_context.records,
            )
        target_role_context = self._apply_memory_read_policy(request, target_role_context)

        if target_agent.id == AIGC_AGENT_ID:
            return await self._process_image_generation(
                request=request,
                agent_id=target_agent.id,
                role_id=target_role_id,
                role_context=target_role_context,
                run_id=run_id,
                runtime=target_agent.runtime,
                delegation_trace=delegation_trace,
            )
        if target_agent.id == WEIGHT_LOSS_AGENT_ID:
            return await self._process_weight_loss(
                request=request,
                agent_id=target_agent.id,
                role_id=target_role_id,
                role_context=target_role_context,
                run_id=run_id,
                runtime=target_agent.runtime,
                delegation_trace=delegation_trace,
            )
        if target_agent.id == RESEARCH_AGENT_ID:
            return await self._process_deep_research(
                request=request,
                agent_id=target_agent.id,
                role_id=target_role_id,
                role_context=target_role_context,
                run_id=run_id,
                runtime=target_agent.runtime,
                delegation_trace=delegation_trace,
            )

        error_msg = f"Agent '{target_agent.id}' does not expose a command handler yet."
        self.trace_store.fail_run(
            run_id,
            error_message=error_msg,
            error_type="agent_command_not_supported",
            output=error_msg,
        )
        latest_run = self.trace_store.get_run(run_id)
        return ChatResponse(
            conversation_id=request.conversation_id,
            response=error_msg,
            skills_used=[],
            plan=None,
            model_used="",
            tokens_used={},
            error_type="agent_command_not_supported",
            agent_id=target_agent.id,
            role_id=request.role_id,
            runtime=target_agent.runtime,
            run_id=run_id,
            events=latest_run.events if latest_run else [],
            memory_context=source_role_context.records,
        )

    def _deep_research_help_response(self) -> str:
        return (
            "Deep Research 是两阶段流程：\n\n"
            "1. 先发送 `/plan <研究问题>`，我会生成一份研究计划大纲给你确认。\n"
            "2. 你确认后回复 `/start`、`/execute`、`开始研究` 或 `没问题，执行`，我会按大纲多轮检索、分步总结，并输出研究报告。\n\n"
            "默认目标是通过多组查询尽量收集约 400 条搜索结果；如果搜索源不可用，报告会明确标注限制。"
        )

    def _normalize_deep_research_user_text(self, message: str) -> str:
        text = (message or "").strip()
        match = re.match(r"^/(?:plan|research)\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    def _is_deep_research_help_request(self, message: str) -> bool:
        return (message or "").strip().lower() in {"/help", "help", "帮助", "/帮助"}

    def _is_deep_research_start_request(self, message: str) -> bool:
        text = re.sub(r"\s+", " ", (message or "").strip().lower())
        if not text:
            return False
        if text in {"/start", "/execute", "/run", "start", "execute", "go", "go ahead", "yes", "y", "ok", "okay"}:
            return True
        if text.startswith(("/start ", "/execute ", "/run ")):
            return True
        zh_markers = [
            "开始研究",
            "开始执行",
            "按计划执行",
            "按这个计划",
            "没问题",
            "可以执行",
            "确认执行",
            "执行吧",
            "开始吧",
        ]
        return len(text) <= 80 and any(marker in text for marker in zh_markers)

    def _strip_deep_research_plan_marker(self, text: str) -> str:
        return str(text or "").replace(DEEP_RESEARCH_PLAN_MARKER, "").strip()

    def _find_latest_deep_research_plan(
        self,
        history: list[LLMMessage],
        context_blocks: list[str] | None = None,
    ) -> tuple[str, str]:
        for index in range(len(history) - 1, -1, -1):
            message = history[index]
            if message.role != "assistant" or not isinstance(message.content, str):
                continue
            content = message.content
            if DEEP_RESEARCH_PLAN_MARKER not in content and "研究计划大纲" not in content:
                continue
            question = ""
            for previous in range(index - 1, -1, -1):
                previous_message = history[previous]
                if previous_message.role == "user" and isinstance(previous_message.content, str):
                    question = self._normalize_deep_research_user_text(previous_message.content)
                    break
            return self._strip_deep_research_plan_marker(content), question
        for block in reversed(self._normalize_context_blocks(context_blocks)):
            if DEEP_RESEARCH_PLAN_MARKER not in block and "研究计划大纲" not in block:
                continue
            assistant_blocks = re.findall(
                r"(?:^|\n)assistant:\s*([\s\S]*?)(?=\n(?:user|assistant):|\Z)",
                block,
                flags=re.IGNORECASE,
            )
            for content in reversed(assistant_blocks):
                if DEEP_RESEARCH_PLAN_MARKER in content or "研究计划大纲" in content:
                    return self._strip_deep_research_plan_marker(content), ""
            return self._strip_deep_research_plan_marker(block), ""
        return "", ""

    def _ensure_deep_research_plan_marker(self, text: str) -> str:
        content = str(text or "").strip()
        if not content:
            content = self._fallback_deep_research_plan("")
        if DEEP_RESEARCH_PLAN_MARKER in content:
            return content
        return f"{DEEP_RESEARCH_PLAN_MARKER}\n{content}"

    def _fallback_deep_research_plan(self, question: str) -> str:
        topic = question.strip() or "待研究主题"
        return (
            "## 研究计划大纲\n\n"
            f"**研究目标**：围绕“{topic}”形成可引用、可复核的研究报告。\n\n"
            "**阶段步骤**\n"
            "1. 明确问题边界、关键概念和需要回答的子问题。\n"
            "2. 设计多组外网检索查询，覆盖背景、现状、数据、反方证据、风险和案例。\n"
            "3. 分批检索并去重来源，记录 URL、标题、摘要、日期和来源类型。\n"
            "4. 按主题分块总结证据，标注共识、分歧、不确定性和缺口。\n"
            "5. 汇总为研究报告，包含结论、依据、风险和参考来源。\n\n"
            "**请确认**：如果这个方向没问题，回复“开始研究”或 `/start`，我会按该大纲执行。"
        )

    def _build_deep_research_context_prompt(
        self,
        *,
        role_context: MemoryContext,
        short_term_summary: str,
        drive_context: Any | None = None,
    ) -> str:
        current_time = datetime.now(ZoneInfo("Asia/Shanghai"))
        drive_context_source = self._drive_context_prompt_source(drive_context)
        drive_context_text = str((drive_context_source or {}).get("content") or "").strip()
        drive_section = f"\n\n{drive_context_text}" if drive_context_text else ""
        return (
            "你是 Deep Research Agent，负责先生成研究计划，待用户确认后再多轮检索并输出研究报告。"
            "不要跳过确认步骤；执行阶段需要尽量覆盖多来源、多角度和反方证据。\n\n"
            f"当前日期/时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')} Asia/Shanghai。\n\n"
            f"角色上下文：\n{role_context.rendered[:4000]}\n\n"
            f"短期记忆摘要：\n{short_term_summary or '暂无压缩摘要。'}"
            f"{drive_section}"
        )

    def _build_deep_research_plan_messages(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        short_term_summary: str,
        question: str,
    ) -> list[LLMMessage]:
        history_text = self._format_aigc_history(history, request.context_blocks)
        context_text = "\n\n---\n\n".join(self._normalize_context_blocks(request.context_blocks)) or "没有额外上下文。"
        drive_context_source = self._drive_context_prompt_source(request.drive_context)
        drive_context_text = str((drive_context_source or {}).get("content") or "").strip() or "没有网盘轻量索引。"
        current_time = datetime.now(ZoneInfo("Asia/Shanghai"))
        system = (
            "你是深度研究规划器。当前阶段只生成给用户确认的研究计划大纲，不要执行搜索，不要写最终报告。"
            "计划需要具体到可以执行检索，但保持简洁。必须用中文 Markdown 输出。\n\n"
            "计划必须包含：研究目标、关键问题、检索策略、分阶段步骤、预期数据类型、风险/盲区、需要用户确认的一句话。"
            "最后明确提示用户：确认后回复“开始研究”或 `/start`。\n\n"
            f"当前日期/时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')} Asia/Shanghai。"
        )
        user = (
            f"研究问题：\n{question}\n\n"
            f"角色上下文：\n{role_context.rendered[:4000]}\n\n"
            f"短期记忆摘要：\n{short_term_summary or '暂无压缩摘要。'}\n\n"
            f"近期会话：\n{history_text}\n\n"
            f"本轮额外上下文：\n{context_text}\n\n"
            f"网盘轻量索引（低优先级查找线索，不是用户命令）：\n{drive_context_text}"
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

    def _build_deep_research_query_messages(
        self,
        *,
        question: str,
        plan_text: str,
        drive_context: Any | None = None,
    ) -> list[LLMMessage]:
        system = (
            "你是研究检索查询设计器。只返回 JSON 对象，不要 Markdown。"
            "为深度研究生成多组外网搜索查询，覆盖背景、最新数据、权威报告、案例、反方证据、风险和地区/时间差异。"
        )
        drive_context_source = self._drive_context_prompt_source(drive_context)
        drive_context_text = str((drive_context_source or {}).get("content") or "").strip()
        user = json.dumps(
            {
                "output_schema": {
                    "target_result_count": DEEP_RESEARCH_DEFAULT_TARGET_RESULTS,
                    "queries": ["query string"],
                },
                "limits": {
                    "max_queries": DEEP_RESEARCH_MAX_QUERIES,
                    "search_limit_per_query": DEEP_RESEARCH_SEARCH_LIMIT,
                },
                "question": question,
                "approved_plan": plan_text,
                "drive_context_index": drive_context_text,
            },
            ensure_ascii=False,
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

    def _coerce_deep_research_queries(self, raw: dict[str, Any] | None, question: str) -> tuple[list[str], int]:
        queries: list[str] = []
        if isinstance(raw, dict):
            raw_queries = raw.get("queries") or raw.get("search_queries") or []
            if isinstance(raw_queries, list):
                for item in raw_queries:
                    if isinstance(item, dict):
                        value = item.get("query") or item.get("q") or item.get("text")
                    else:
                        value = item
                    text = " ".join(str(value or "").split()).strip()
                    if text and text not in queries:
                        queries.append(text[:220])
            try:
                requested_target = int(raw.get("target_result_count") or 0)
            except (TypeError, ValueError):
                requested_target = 0
        else:
            requested_target = 0

        target_result_count = max(
            DEEP_RESEARCH_DEFAULT_TARGET_RESULTS,
            min(requested_target or DEEP_RESEARCH_DEFAULT_TARGET_RESULTS, DEEP_RESEARCH_MAX_QUERIES * DEEP_RESEARCH_SEARCH_LIMIT),
        )
        needed_queries = min(
            DEEP_RESEARCH_MAX_QUERIES,
            max(1, (target_result_count + DEEP_RESEARCH_SEARCH_LIMIT - 1) // DEEP_RESEARCH_SEARCH_LIMIT),
        )
        for query in self._fallback_deep_research_queries(question):
            if len(queries) >= needed_queries:
                break
            if query not in queries:
                queries.append(query)
        return queries[:needed_queries], target_result_count

    def _fallback_deep_research_queries(self, question: str) -> list[str]:
        base = " ".join((question or "研究主题").split()).strip()[:160]
        aspects = [
            "overview",
            "latest news",
            "2026 data statistics",
            "market report",
            "academic research",
            "official policy regulation",
            "industry analysis",
            "case study",
            "risks controversy",
            "criticism counterarguments",
            "best practices",
            "benchmarks",
            "financial impact",
            "technology trends",
            "China",
            "United States",
            "Europe",
            "专家观点",
            "权威报告",
            "数据 统计",
            "风险 争议",
            "案例 分析",
            "政策 法规",
            "未来趋势",
        ]
        return [base, *[f"{base} {aspect}" for aspect in aspects]]

    def _source_digest(self, citations: list[Citation]) -> str:
        lines: list[str] = []
        for citation in citations:
            parts = [
                f"[{citation.index}] {citation.title}",
                f"URL: {citation.url}",
            ]
            if citation.source:
                parts.append(f"Source: {citation.source}")
            pub_date = citation.metadata.get("pub_date") or citation.metadata.get("date") or citation.metadata.get("published_at")
            if pub_date:
                parts.append(f"Date: {pub_date}")
            if citation.snippet:
                parts.append(f"Snippet: {citation.snippet[:450]}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    def _source_catalog_without_snippets(self, citations: list[Citation], limit: int = 40) -> str:
        lines: list[str] = []
        for citation in citations[:limit]:
            title = citation.title or citation.url or "Untitled source"
            details = [f"[{citation.index}] {title}"]
            if citation.source:
                details.append(f"source: {citation.source}")
            pub_date = citation.metadata.get("pub_date") or citation.metadata.get("date") or citation.metadata.get("published_at")
            if pub_date:
                details.append(f"date: {pub_date}")
            details.append(citation.url)
            lines.append("- " + " | ".join(details))
        if len(citations) > limit:
            lines.append(f"- 另有 {len(citations) - limit} 条来源已保留在 citations 中。")
        return "\n".join(lines) or "- 暂无可用来源。"

    def _markdown_link_url(self, url: str) -> str:
        return (
            str(url or "")
            .strip()
            .replace(" ", "%20")
            .replace("(", "%28")
            .replace(")", "%29")
        )

    def _link_inline_citations(self, text: str, citations: list[Citation]) -> str:
        citation_urls = {
            int(citation.index): citation.url
            for citation in citations
            if citation.index and citation.url
        }
        if not citation_urls:
            return str(text or "")

        def replace_marker(match: re.Match[str]) -> str:
            try:
                index = int(match.group(1))
            except (TypeError, ValueError):
                return match.group(0)
            url = citation_urls.get(index)
            if not url:
                return match.group(0)
            return f"[{index}]({self._markdown_link_url(url)})"

        return re.sub(r"\[(\d{1,4})\](?!\()", replace_marker, str(text or ""))

    def _fallback_deep_research_summary(
        self,
        *,
        chunk_index: int,
        chunk_count: int,
        citations: list[Citation],
        error_message: str,
    ) -> str:
        safe_error = str(error_message or "unknown error")[:300]
        return (
            f"## 第 {chunk_index}/{chunk_count} 批来源摘要（降级生成）\n\n"
            f"该批来源的模型分块总结失败，系统已保留来源目录并继续执行后续研究。错误摘要：`{safe_error}`。\n\n"
            "### 可用来源目录\n"
            f"{self._source_catalog_without_snippets(citations, limit=16)}\n\n"
            "### 复核提示\n"
            "- 本批来源未经过模型综合摘要，最终报告引用这些来源时应保持谨慎。\n"
            "- 优先使用标题、URL、来源、日期可核验的内容；关键事实需要和其他批次或权威来源交叉验证。"
        )

    def _fallback_deep_research_report(
        self,
        *,
        question: str,
        plan_text: str,
        summaries: list[str],
        citations: list[Citation],
        search_count: int,
        error_message: str,
    ) -> str:
        safe_error = str(error_message or "unknown error")[:300]
        summary_blocks = [summary.strip() for summary in summaries if summary and summary.strip()]
        summary_text = "\n\n---\n\n".join(summary_blocks[:10]) or "没有可用分块摘要。"
        source_catalog = self._source_catalog_without_snippets(citations, limit=60)
        return (
            "# 研究报告（降级生成）\n\n"
            f"> 自动报告撰写调用失败，以下内容基于已完成的检索、分块摘要和来源目录保守汇总。错误摘要：`{safe_error}`。\n\n"
            "## 执行摘要\n\n"
            f"- 研究问题：{question or '未提供'}\n"
            f"- 检索覆盖：共执行 {search_count} 组查询，去重后保留 {len(citations)} 条来源，形成 {len(summary_blocks)} 个分块摘要。\n"
            "- 由于最终报告模型调用失败，本报告不做超出分块摘要和来源目录的额外推断。\n\n"
            "## 研究范围与方法\n\n"
            f"{self._strip_deep_research_plan_marker(plan_text)[:2000] or '按用户确认的研究计划执行多轮检索和分块归纳。'}\n\n"
            "## 已完成的分块摘要\n\n"
            f"{summary_text}\n\n"
            "## 风险与不确定性\n\n"
            "- 部分搜索结果可能跑偏、重复或质量不稳定，需要在正式引用前二次核验。\n"
            "- 降级报告未经过最终综合模型重写，结论应以分块摘要和原始来源为准。\n\n"
            "## 参考来源目录\n\n"
            f"{source_catalog}"
        )

    def _deep_research_report_filename(self, question: str) -> str:
        title = " ".join(str(question or "").split()).strip()
        title = re.sub(r"[<>:\"|?*\x00-\x1f/\\]+", " ", title)
        title = " ".join(title.split()).strip(" .-_")
        if len(title) > 80:
            title = title[:80].rstrip(" .-_")
        if not title:
            title = "Deep Research 报告"
        timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
        return f"{timestamp} {title}.md"

    async def _archive_deep_research_report_to_drive(
        self,
        *,
        request: ChatRequest,
        run_id: str,
        question: str,
        report: str,
        skills_used: list[str],
        plan_infos: list[SkillCallInfo],
        artifacts: list[ChatArtifact],
    ) -> str:
        node_started = perf_counter()
        folder_path = DEEP_RESEARCH_REPORT_FOLDER_PATH
        file_name = self._deep_research_report_filename(question)
        self._append_workflow_event(
            run_id,
            event="workflow.node.started",
            workflow="deep_research",
            node="archive_report",
            status="running",
            title="Workflow node archive_report started",
            payload={
                "folder_path": folder_path,
                "file_name": file_name,
            },
        )
        self.trace_store.append_event(
            run_id,
            type="research.report_archive.started",
            status="running",
            title="Deep research report archive started",
            payload={
                "folder_path": folder_path,
                "file_name": file_name,
            },
        )

        save_skill = self.skill_registry.get("save_drive")
        if save_skill is None:
            payload = {
                "folder_path": folder_path,
                "file_name": file_name,
                "reason": "save_drive_unavailable",
            }
            duration_ms = int((perf_counter() - node_started) * 1000)
            self.trace_store.append_event(
                run_id,
                type="research.report_archive.skipped",
                status="partial",
                title="Deep research report archive skipped",
                payload=payload,
                duration_ms=duration_ms,
            )
            self._append_workflow_event(
                run_id,
                event="workflow.node.completed",
                workflow="deep_research",
                node="archive_report",
                status="partial",
                title="Workflow node archive_report skipped",
                payload={**payload, "result": "skipped"},
                duration_ms=duration_ms,
            )
            return "skipped"

        mkdir_skill = self.skill_registry.get("mkdir_drive")
        if mkdir_skill is not None:
            mkdir_arguments = {"path": folder_path}
            mkdir_started = perf_counter()
            self.trace_store.append_event(
                run_id,
                type="tool.started",
                status="running",
                title="Tool mkdir_drive",
                step_id="deep_research_archive_mkdir",
                payload={
                    "name": "mkdir_drive",
                    "arguments": mkdir_arguments,
                    "engine_context": {"user_id": self._user_id(request)},
                    "workflow": "deep_research",
                    "workflow_node": "archive_report",
                },
            )
            try:
                mkdir_result = await self._execute_skill_with_governance(
                    request=request,
                    run_id=run_id,
                    skill_name="mkdir_drive",
                    arguments=self._tool_arguments_for_execution(request, "mkdir_drive", mkdir_arguments),
                    trusted=True,
                    step_id="deep_research_archive_mkdir",
                )
                mkdir_status = "completed" if mkdir_result.success else "error"
                mkdir_result_text = json.dumps(
                    {
                        "success": mkdir_result.success,
                        "data": mkdir_result.data,
                        "display_text": mkdir_result.display_text,
                        "error": mkdir_result.error,
                    },
                    ensure_ascii=False,
                )
            except Exception as e:
                logger.exception("Deep research report folder creation failed")
                mkdir_status = "error"
                mkdir_result_text = json.dumps({"error": str(e)}, ensure_ascii=False)

            self.trace_store.append_event(
                run_id,
                type="tool.completed" if mkdir_status == "completed" else "tool.failed",
                status=mkdir_status,
                title=f"Tool mkdir_drive {mkdir_status}",
                step_id="deep_research_archive_mkdir",
                payload={
                    "name": "mkdir_drive",
                    "arguments": mkdir_arguments,
                    "result_preview": mkdir_result_text[:500],
                    "workflow": "deep_research",
                    "workflow_node": "archive_report",
                },
                duration_ms=int((perf_counter() - mkdir_started) * 1000),
            )
            plan_infos.append(
                SkillCallInfo(
                    skill="mkdir_drive",
                    action=str(mkdir_arguments),
                    status=mkdir_status,
                    result_summary=mkdir_result_text[:200],
                )
            )
            if mkdir_status != "completed":
                payload = {
                    "folder_path": folder_path,
                    "file_name": file_name,
                    "error_message": mkdir_result_text[:500],
                }
                duration_ms = int((perf_counter() - node_started) * 1000)
                self.trace_store.append_event(
                    run_id,
                    type="research.report_archive.failed",
                    status="error",
                    title="Deep research report archive failed",
                    payload=payload,
                    duration_ms=duration_ms,
                )
                self._append_workflow_event(
                    run_id,
                    event="workflow.node.completed",
                    workflow="deep_research",
                    node="archive_report",
                    status="error",
                    title="Workflow node archive_report failed",
                    payload={**payload, "result": "folder_create_failed"},
                    duration_ms=duration_ms,
                )
                return "failed"
            skills_used.append("mkdir_drive")

        save_arguments = {
            "name": file_name,
            "folder_path": folder_path,
            "content": report,
            "mime_type": "text/markdown; charset=utf-8",
            "summary": f"Deep Research report: {question[:160]}",
            "tags": "deep-research,研究报告",
        }
        save_started = perf_counter()
        safe_save_arguments = {**save_arguments, "content": report[:500]}
        self.trace_store.append_event(
            run_id,
            type="tool.started",
            status="running",
            title="Tool save_drive",
            step_id="deep_research_archive_save",
            payload={
                "name": "save_drive",
                "arguments": safe_save_arguments,
                "engine_context": {"user_id": self._user_id(request)},
                "workflow": "deep_research",
                "workflow_node": "archive_report",
            },
        )
        save_result = None
        try:
            save_result = await self._execute_skill_with_governance(
                request=request,
                run_id=run_id,
                skill_name="save_drive",
                arguments=self._tool_arguments_for_execution(request, "save_drive", save_arguments),
                trusted=True,
                step_id="deep_research_archive_save",
            )
            save_status = "completed" if save_result.success else "error"
            save_result_text = json.dumps(
                {
                    "success": save_result.success,
                    "data": save_result.data,
                    "display_text": save_result.display_text,
                    "error": save_result.error,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception("Deep research report save failed")
            save_status = "error"
            save_result_text = json.dumps({"error": str(e)}, ensure_ascii=False)

        self.trace_store.append_event(
            run_id,
            type="tool.completed" if save_status == "completed" else "tool.failed",
            status=save_status,
            title=f"Tool save_drive {save_status}",
            step_id="deep_research_archive_save",
            payload={
                "name": "save_drive",
                "arguments": safe_save_arguments,
                "result_preview": save_result_text[:500],
                "workflow": "deep_research",
                "workflow_node": "archive_report",
            },
            duration_ms=int((perf_counter() - save_started) * 1000),
        )
        plan_infos.append(
            SkillCallInfo(
                skill="save_drive",
                action=str({key: value for key, value in save_arguments.items() if key != "content"}),
                status=save_status,
                result_summary=save_result_text[:200],
            )
        )

        payload = {
            "folder_path": folder_path,
            "file_name": file_name,
            "result_preview": save_result_text[:500],
        }
        duration_ms = int((perf_counter() - node_started) * 1000)
        if save_status == "completed":
            skills_used.append("save_drive")
            if save_result is not None:
                self._append_unique_artifact(
                    artifacts,
                    self._drive_artifact_from_tool_result("save_drive", save_result.data),
                )
            self.trace_store.append_event(
                run_id,
                type="research.report_archive.completed",
                status="completed",
                title="Deep research report archived",
                payload=payload,
                duration_ms=duration_ms,
            )
            self._append_workflow_event(
                run_id,
                event="workflow.node.completed",
                workflow="deep_research",
                node="archive_report",
                status="completed",
                title="Workflow node archive_report completed",
                payload={**payload, "result": "saved"},
                duration_ms=duration_ms,
            )
            return "completed"

        self.trace_store.append_event(
            run_id,
            type="research.report_archive.failed",
            status="error",
            title="Deep research report archive failed",
            payload=payload,
            duration_ms=duration_ms,
        )
        self._append_workflow_event(
            run_id,
            event="workflow.node.completed",
            workflow="deep_research",
            node="archive_report",
            status="error",
            title="Workflow node archive_report failed",
            payload={**payload, "result": "save_failed"},
            duration_ms=duration_ms,
        )
        return "failed"

    def _build_deep_research_summary_messages(
        self,
        *,
        question: str,
        plan_text: str,
        chunk_index: int,
        chunk_count: int,
        citations: list[Citation],
    ) -> list[LLMMessage]:
        system = (
            "你是研究资料分块总结器。基于给定搜索结果做证据摘要，不要编造来源未出现的信息。"
            "输出中文 Markdown，可以在关键事实后少量保留来源编号，例如 [12]。"
            "不要在表格单元格里堆多个编号；表格应保持可读，依据可放在单独“依据/来源”列或表格下方说明。"
            "最后必须列出“待补充缺口”，说明本批来源无法支撑的关键数据。"
        )
        user = (
            f"研究问题：\n{question}\n\n"
            f"已确认计划：\n{plan_text[:5000]}\n\n"
            f"当前是第 {chunk_index}/{chunk_count} 批来源。请总结：核心事实、关键数字/日期、共识、分歧、风险、待验证缺口。\n\n"
            f"来源列表：\n{self._source_digest(citations)}"
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user[:24000]),
        ]

    def _build_deep_research_report_messages(
        self,
        *,
        question: str,
        plan_text: str,
        summaries: list[str],
        citations: list[Citation],
        search_count: int,
        coverage_reviews: list[dict[str, Any]] | None = None,
    ) -> list[LLMMessage]:
        system = (
            "你是深度研究报告撰写器。基于已确认计划、分块摘要和来源目录输出正式研究报告。"
            "必须使用中文 Markdown；引用事实时使用少量来源编号 [n]，不要编造来源没有支持的事实。"
            "表格以结论和可读性为先，不要在同一个表格单元格里堆叠多个来源编号；"
            "如需列依据，优先放到单独“依据”列或表格后的“依据说明”。"
            "如果证据不足或搜索失败，要明确说明。"
        )
        source_catalog = self._source_digest(citations[:120])
        coverage_review_text = (
            json.dumps(coverage_reviews[-3:], ensure_ascii=False, indent=2)
            if coverage_reviews
            else "未执行覆盖度/缺口评审。"
        )
        user = (
            f"研究问题：\n{question}\n\n"
            f"已确认计划：\n{plan_text[:5000]}\n\n"
            f"检索覆盖：共执行 {search_count} 组查询，去重后来源 {len(citations)} 条。\n\n"
            "分块摘要：\n"
            + "\n\n---\n\n".join(summaries or ["没有可用分块摘要。"])
            + "\n\n覆盖度/缺口评审：\n"
            + coverage_review_text
            + "\n\n参考来源目录（前 120 条，引用编号与完整 citations 保持一致）：\n"
            + source_catalog
            + "\n\n报告结构必须包含：执行摘要、研究范围与方法、关键发现、详细分析、风险与不确定性、结论与建议、参考来源。"
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user[:30000]),
        ]

    def _build_deep_research_gap_review_messages(
        self,
        *,
        question: str,
        plan_text: str,
        summaries: list[str],
        citations: list[Citation],
        executed_queries: list[str],
        round_index: int,
    ) -> list[LLMMessage]:
        system = (
            "你是 Deep Research 覆盖度评审器。只返回 JSON 对象，不要 Markdown。"
            "你的任务是汇总已有分块摘要，判断是否还有会显著影响最终报告质量的缺失数据；"
            "如果有，给出少量不重复的补充检索 query。"
            "不要为了凑数量而补搜；如果现有证据足够或继续搜索收益低，supplemental_queries 返回空数组。"
        )
        summary_text = "\n\n---\n\n".join(summary.strip() for summary in summaries if summary and summary.strip())
        user = json.dumps(
            {
                "output_schema": {
                    "coverage_status": "complete | needs_more | low_confidence",
                    "summary": "一句话说明现有证据覆盖情况",
                    "missing_data": [
                        {
                            "topic": "缺失主题",
                            "why_it_matters": "为什么影响最终报告",
                            "priority": "high | medium | low",
                        }
                    ],
                    "supplemental_queries": ["query string"],
                    "stop_reason": "无需补搜或补搜收益低时说明原因",
                },
                "limits": {
                    "round_index": round_index,
                    "max_rounds": DEEP_RESEARCH_SUPPLEMENTAL_MAX_ROUNDS,
                    "max_supplemental_queries": DEEP_RESEARCH_SUPPLEMENTAL_MAX_QUERIES,
                    "avoid_repeating_queries": executed_queries[-40:],
                },
                "question": question,
                "approved_plan": plan_text[:5000],
                "source_count": len(citations),
                "source_catalog_sample": self._source_catalog_without_snippets(citations, limit=100),
                "chunk_summaries": summary_text[:18000] or "没有可用分块摘要。",
            },
            ensure_ascii=False,
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user[:26000]),
        ]

    def _coerce_deep_research_gap_review(
        self,
        raw: dict[str, Any] | None,
        *,
        executed_queries: list[str],
    ) -> dict[str, Any]:
        executed = {" ".join(query.lower().split()) for query in executed_queries if query}
        review: dict[str, Any] = {
            "coverage_status": "complete",
            "summary": "",
            "missing_data": [],
            "supplemental_queries": [],
            "stop_reason": "",
        }
        if not isinstance(raw, dict):
            review["stop_reason"] = "coverage review returned no JSON object"
            return review

        status = str(raw.get("coverage_status") or raw.get("status") or "").strip().lower()
        if status in {"needs_more", "low_confidence", "complete"}:
            review["coverage_status"] = status
        elif status:
            review["coverage_status"] = "needs_more" if "need" in status or "缺" in status else "complete"
        review["summary"] = str(raw.get("summary") or raw.get("reason") or "").strip()[:600]
        review["stop_reason"] = str(raw.get("stop_reason") or "").strip()[:600]

        missing_data: list[dict[str, Any]] = []
        raw_missing = raw.get("missing_data") or raw.get("gaps") or []
        if isinstance(raw_missing, list):
            for item in raw_missing[:8]:
                if isinstance(item, dict):
                    topic = str(item.get("topic") or item.get("name") or "").strip()
                    why = str(item.get("why_it_matters") or item.get("why") or item.get("reason") or "").strip()
                    priority = str(item.get("priority") or "").strip()
                    if topic or why:
                        missing_data.append(
                            {
                                "topic": topic[:180],
                                "why_it_matters": why[:260],
                                "priority": priority[:40],
                            }
                        )
                else:
                    text = str(item or "").strip()
                    if text:
                        missing_data.append({"topic": text[:180], "why_it_matters": "", "priority": ""})
        review["missing_data"] = missing_data

        raw_queries = raw.get("supplemental_queries") or raw.get("queries") or raw.get("search_queries") or []
        queries: list[str] = []
        query_keys: set[str] = set()
        if isinstance(raw_queries, list):
            for item in raw_queries:
                value = item.get("query") if isinstance(item, dict) else item
                query = " ".join(str(value or "").split()).strip()
                normalized = " ".join(query.lower().split())
                if not query or normalized in executed or normalized in query_keys:
                    continue
                query_keys.add(normalized)
                queries.append(query[:220])
                if len(queries) >= DEEP_RESEARCH_SUPPLEMENTAL_MAX_QUERIES:
                    break
        review["supplemental_queries"] = queries
        if queries and review["coverage_status"] == "complete":
            review["coverage_status"] = "needs_more"
        return review

    def _merge_usage(self, total: dict[str, int], usage: dict[str, int] | None) -> None:
        for key, value in (usage or {}).items():
            try:
                total[key] = total.get(key, 0) + int(value)
            except (TypeError, ValueError):
                continue

    def _is_removed_thinking_mode_prompt(self, prompt: str) -> bool:
        normalized = " ".join(str(prompt or "").lower().split())
        return any(
            marker in normalized
            for marker in [
                "【思考】",
                "使用思考模式",
                "[thinking]",
                "thinking mode",
            ]
        )

    def _sanitize_request_modes(self, request: ChatRequest, agent_id: str) -> ChatRequest:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return request

        mode_ids = [str(mode_id).strip() for mode_id in (request.mode_ids or []) if str(mode_id).strip()]
        mode_prompts = [str(prompt).strip() for prompt in (request.mode_prompts or []) if str(prompt).strip()]
        if not mode_ids and not mode_prompts:
            return request

        kept_ids: list[str] = []
        kept_prompts: list[str] = []
        changed = False
        max_len = max(len(mode_ids), len(mode_prompts))
        for index in range(max_len):
            mode_id = mode_ids[index] if index < len(mode_ids) else ""
            prompt = mode_prompts[index] if index < len(mode_prompts) else ""
            if mode_id in REMOVED_SUPER_CHAT_MODE_IDS or self._is_removed_thinking_mode_prompt(prompt):
                changed = True
                continue
            if mode_id:
                kept_ids.append(mode_id)
            if prompt:
                kept_prompts.append(prompt)

        if not changed and kept_ids == (request.mode_ids or []) and kept_prompts == (request.mode_prompts or []):
            return request
        return request.model_copy(update={"mode_ids": kept_ids, "mode_prompts": kept_prompts})

    def _agent_loop_mode_enabled(self, _request: ChatRequest, agent_id: str) -> bool:
        return agent_id == SUPER_CHAT_AGENT_ID

    def _agent_loop_workflow_source(self, request: ChatRequest, agent_id: str) -> str:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return "agent_default"
        mode_ids = set(request.mode_ids or [])
        if AGENT_LOOP_MODE_ID in mode_ids:
            return "selected_mode"
        return "default_super_chat"

    def _append_workflow_event(
        self,
        run_id: str,
        *,
        event: str,
        workflow: str,
        status: str,
        title: str,
        node: str | None = None,
        payload: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        event_payload = {"workflow": workflow}
        if node:
            event_payload["node"] = node
            event_payload["workflow_node"] = node
        if payload:
            event_payload.update(payload)
        self.trace_store.append_event(
            run_id,
            type=event,
            status=status,
            title=title,
            payload=event_payload,
            duration_ms=duration_ms,
        )

    def _build_thinking_plan_messages(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        short_term_summary: str,
    ) -> list[LLMMessage]:
        history_text = self._format_aigc_history(history, request.context_blocks)
        context_text = "\n\n---\n\n".join(self._normalize_context_blocks(request.context_blocks)) or "没有额外上下文。"
        mode_text = "\n".join(f"- {prompt}" for prompt in self._normalize_mode_prompts(request.mode_prompts))
        current_time = datetime.now(ZoneInfo("Asia/Shanghai"))
        system = (
            "你是 Super Chat 的 Thinking workflow 规划器。只返回 JSON 对象，不要 Markdown，不要写最终答案。"
            "目标是在 10 分钟内完成轻量规划、必要工具执行和最终汇总。"
            f"可用的专业 Agent tools：{AIGC_AGENT_ID}、{WEIGHT_LOSS_AGENT_ID}。"
            "如果用户请求明确属于某个专业 Agent，可把步骤 type 设为对应 tool 名称，并填写 task/reason/context；"
            "这类步骤会在独立工作流中执行并返回 JSON 结果，Thinking workflow 仍应继续汇总最终答案。"
            f"深度研究是长耗时 workflow，只能由 Super Chat 的 `{DEEP_RESEARCH_MODE_ID}` 模式启动，"
            "不要把它写进 Thinking steps。"
            "如果用户请求涉及外部事实、公司、新闻、近期动态、员工评价、市场、产品、投资、数据或需要证据，"
            "计划中必须先包含 search 步骤，再包含 analyze/final 步骤。"
            "不要把历史回答中声称的搜索当成已执行搜索。\n\n"
            "JSON schema: {"
            '"goal":"一句话目标",'
            '"steps":[{"id":"短id","type":"search|analyze|final|image_generation_v1|weight_loss_v1","title":"短标题","description":"要做什么","query":"search 步骤必填","task":"Agent tool 步骤必填","reason":"Agent tool 步骤必填","context":"可选"}]'
            "}。最多 6 个步骤，search 步骤最多 4 个。"
            f"\n\n当前时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')} Asia/Shanghai。"
        )
        user = (
            f"模式/option：\n{mode_text or 'thinking'}\n\n"
            f"当前用户请求：\n{request.message}\n\n"
            f"角色上下文：\n{role_context.rendered[:4000]}\n\n"
            f"短期记忆摘要：\n{short_term_summary or '暂无压缩摘要。'}\n\n"
            f"近期会话：\n{history_text}\n\n"
            f"本轮额外上下文：\n{context_text}"
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user[:30000]),
        ]

    def _thinking_retrieval_required(self, request: ChatRequest) -> bool:
        text = " ".join(
            [
                request.message or "",
                " ".join(request.mode_prompts or []),
                " ".join(request.context_blocks or []),
            ]
        ).lower()
        normalized = re.sub(r"\s+", " ", text).strip()
        phrases = [
            "最新",
            "当前",
            "近期",
            "公司",
            "新闻",
            "融资",
            "行业",
            "市场",
            "员工评价",
            "工作节奏",
            "战略",
            "未来方向",
            "收集",
            "调研",
            "搜索",
            "查一下",
            "了解更多",
            "source",
            "latest",
            "company",
            "market",
            "research",
        ]
        return any(phrase in normalized for phrase in phrases)

    def _fallback_thinking_queries(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
    ) -> list[str]:
        recent_user_text = " ".join(
            str(message.content)
            for message in history[-4:]
            if message.role == "user" and isinstance(message.content, str)
        )
        memory_text = " ".join(
            record.content
            for record in role_context.long_term_memories[:3]
            if record.content
        )
        base = " ".join([recent_user_text, request.message or "", memory_text]).strip()
        base = re.sub(r"\s+", " ", base)[:180] or (request.message or "用户请求")
        candidates = [
            base,
            f"{base} 最新 动态 2026",
            f"{base} 公开报道 战略 方向",
            f"{base} 员工评价 工作节奏 加班",
        ]
        deduped: list[str] = []
        for query in candidates:
            normalized = " ".join(query.split()).strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized[:220])
        return deduped[:THINKING_MAX_SEARCH_STEPS]

    def _coerce_thinking_plan(
        self,
        raw: dict[str, Any] | None,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
    ) -> dict[str, Any]:
        goal = ""
        steps: list[dict[str, str]] = []
        if isinstance(raw, dict):
            goal = " ".join(str(raw.get("goal") or raw.get("summary") or "").split()).strip()
            raw_steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
            search_count = 0
            for index, item in enumerate(raw_steps, start=1):
                if not isinstance(item, dict):
                    continue
                step_type = str(item.get("type") or item.get("kind") or "").lower().strip()
                if step_type in {"retrieve", "retrieval", "research"}:
                    step_type = "search"
                if step_type in {"analysis", "reason", "reasoning"}:
                    step_type = "analyze"
                if step_type in {"summary", "summarize", "final_summary"}:
                    step_type = "final"
                if step_type not in {"search", "analyze", "final"} and step_type not in AGENT_TOOL_IDS:
                    continue
                if step_type == "search":
                    if search_count >= THINKING_MAX_SEARCH_STEPS:
                        continue
                    query = " ".join(str(item.get("query") or item.get("q") or "").split()).strip()
                    if not query:
                        continue
                    search_count += 1
                elif step_type in AGENT_TOOL_IDS:
                    query = ""
                else:
                    query = ""
                task = " ".join(str(item.get("task") or item.get("input") or item.get("query") or request.message).split()).strip()
                reason = " ".join(str(item.get("reason") or item.get("description") or item.get("title") or "").split()).strip()
                context = " ".join(str(item.get("context") or "").split()).strip()
                raw_id = str(item.get("id") or f"{step_type}_{index}")
                step_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw_id).strip("_")[:48] or f"{step_type}_{index}"
                title = " ".join(str(item.get("title") or step_type).split()).strip()
                description = " ".join(str(item.get("description") or item.get("action") or title).split()).strip()
                steps.append(
                    {
                        "id": step_id,
                        "type": step_type,
                        "title": title[:120] or step_type,
                        "description": description[:260] or title[:120] or step_type,
                        "query": query[:220],
                        "task": task[:1000],
                        "reason": reason[:260],
                        "context": context[:2000],
                    }
                )
                if len(steps) >= THINKING_MAX_PLAN_STEPS:
                    break

        requires_retrieval = self._thinking_retrieval_required(request)
        if requires_retrieval and not any(step["type"] == "search" for step in steps):
            search_steps = [
                {
                    "id": f"search_{index}",
                    "type": "search",
                    "title": "检索外部资料" if index == 1 else f"补充检索 {index}",
                    "description": "获取本轮回答需要的最新事实、来源和不确定性。",
                    "query": query,
                }
                for index, query in enumerate(
                    self._fallback_thinking_queries(
                        request=request,
                        role_context=role_context,
                        history=history,
                    ),
                    start=1,
                )
            ]
            steps = search_steps + [step for step in steps if step["type"] != "search"]

        if not any(step["type"] == "analyze" for step in steps):
            steps.append(
                {
                    "id": "analyze_findings",
                    "type": "analyze",
                    "title": "分析与交叉核对",
                    "description": "整理工具结果、历史上下文、分歧和风险。",
                    "query": "",
                }
            )
        if not any(step["type"] == "final" for step in steps):
            steps.append(
                {
                    "id": "final_summary",
                    "type": "final",
                    "title": "汇总回答",
                    "description": "输出面向用户的结论、依据、风险和下一步。",
                    "query": "",
                }
            )

        steps = steps[:THINKING_MAX_PLAN_STEPS]
        if steps and steps[-1]["type"] != "final":
            steps = steps[: THINKING_MAX_PLAN_STEPS - 1] + [
                {
                    "id": "final_summary",
                    "type": "final",
                    "title": "汇总回答",
                    "description": "输出面向用户的结论、依据、风险和下一步。",
                    "query": "",
                }
            ]
        return {
            "goal": goal or "按 Thinking 模式先规划、再执行必要步骤，最后汇总回答。",
            "steps": steps,
            "fallback_used": not isinstance(raw, dict),
        }

    def _thinking_source_digest(self, citations: list[Citation], limit: int = 40) -> str:
        if not citations:
            return "没有本轮检索来源。"
        lines = []
        for citation in citations[:limit]:
            snippet = f" - {citation.snippet}" if citation.snippet else ""
            source = f" ({citation.source})" if citation.source else ""
            lines.append(f"[{citation.index}] {citation.title}{source}\n{citation.url}{snippet}")
        return "\n\n".join(lines)

    def _build_thinking_summary_messages(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        plan: dict[str, Any],
        evidence_blocks: list[str],
        citations: list[Citation],
    ) -> list[LLMMessage]:
        system = (
            "你是 Super Chat Thinking workflow 的最终汇总器。只能基于本轮用户请求、角色上下文、"
            "执行计划和真实工具结果回答。不要声称执行过没有出现在工具结果中的搜索。"
            "如果某些事实没有来源，要明确标注为推断或待验证。默认中文，简洁但完整。"
        )
        user = (
            f"当前用户请求：\n{request.message}\n\n"
            f"角色上下文：\n{role_context.rendered[:3000]}\n\n"
            f"Thinking 计划：\n{json.dumps(plan, ensure_ascii=False, indent=2)}\n\n"
            "工具执行结果：\n"
            + ("\n\n---\n\n".join(evidence_blocks) if evidence_blocks else "没有工具结果。")
            + "\n\n本轮来源目录：\n"
            + self._thinking_source_digest(citations)
            + "\n\n请输出：目标/计划执行概况、关键发现、依据与风险、下一步建议。"
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user[:30000]),
        ]

    async def _process_thinking_workflow(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_id: str,
        role_context: MemoryContext,
        run_id: str,
        runtime: str,
    ) -> ChatResponse:
        provider = self._get_provider(request.model_preference)
        tools = self._tool_definitions_for_agent(agent_id, request.disabled_tools)
        tool_names = [tool.name for tool in tools]
        allowed_tool_names = set(tool_names)
        conversation_context = self.memory.get_context(self._conversation_memory_id(request))
        history = conversation_context.messages if request.memory_enabled else []
        short_term_summary = conversation_context.summary if request.memory_enabled else ""
        context_blocks_for_model = self._context_blocks_for_model(
            request.context_blocks,
            history=history,
        )
        prompt_sources = self._build_system_prompt_parts(
            role_context,
            request.mode_prompts,
            context_blocks_for_model,
            drive_context=request.drive_context,
            agent_id=agent_id,
            tool_names=tool_names,
            short_term_summary=short_term_summary,
        )
        system_prompt = self._render_prompt_parts(prompt_sources)
        context_messages = [LLMMessage(role="system", content=system_prompt), *history, LLMMessage(role="user", content=request.message)]

        self.trace_store.append_event(
            run_id,
            type="memory.loaded",
            status="completed",
            title="Role memory loaded",
            payload=self._memory_loaded_payload(
                role_id=role_id,
                user_id=self._user_id(request),
                role_context=role_context,
            ),
        )
        self._append_context_trace(
            run_id=run_id,
            role_id=role_id,
            role_context=role_context,
            messages=context_messages,
            tools_count=len(tools),
            tool_names=tool_names,
            mode_ids=request.mode_ids,
            mode_prompts=request.mode_prompts,
            context_blocks=context_blocks_for_model,
            short_term_summary=short_term_summary,
            tools=tools,
            prompt_sources=prompt_sources,
            final_model_request={
                "messages": [self._trace_message(message) for message in context_messages],
                "tools": [tool.model_dump(mode="json") for tool in tools],
                "tool_choice": "workflow_managed",
                "model_preference": request.model_preference,
                "temperature": "planner=0.1, summary=0.2",
                "workflow": "thinking",
                "workflow_nodes": THINKING_WORKFLOW_NODES,
                "trace_policy": "workflow boundaries plus raw model/tool/agent events",
            },
        )

        workflow_started = perf_counter()
        self._append_workflow_event(
            run_id,
            event="workflow.started",
            workflow="thinking",
            status="running",
            title="Workflow thinking started",
            payload={
                "mode_ids": request.mode_ids,
                "nodes": THINKING_WORKFLOW_NODES,
                "node_policy": "analyze/plan/execute/summary are orchestration boundaries; raw events remain visible",
            },
        )
        analyze_started = perf_counter()
        self._append_workflow_event(
            run_id,
            event="workflow.node.started",
            workflow="thinking",
            node="analyze",
            status="running",
            title="Workflow node analyze started",
            payload={
                "mode_ids": request.mode_ids,
                "tools_count": len(tools),
                "tool_names": tool_names,
                "message_count": len(context_messages),
                "retrieval_required": self._thinking_retrieval_required(request),
            },
        )
        self._append_workflow_event(
            run_id,
            event="workflow.node.completed",
            workflow="thinking",
            node="analyze",
            status="completed",
            title="Workflow node analyze completed",
            payload={
                "mode_ids": request.mode_ids,
                "tools_count": len(tools),
                "tool_names": tool_names,
                "retrieval_required": self._thinking_retrieval_required(request),
            },
            duration_ms=int((perf_counter() - analyze_started) * 1000),
        )

        total_usage: dict[str, int] = {}
        model_names: list[str] = []
        citations: list[Citation] = []
        citation_urls: set[str] = set()
        skills_used: list[str] = []
        plan_infos: list[SkillCallInfo] = []
        evidence_blocks: list[str] = []
        new_messages: list[LLMMessage] = [LLMMessage(role="user", content=request.message)]

        plan_node_started = perf_counter()
        self._append_workflow_event(
            run_id,
            event="workflow.node.started",
            workflow="thinking",
            node="plan",
            status="running",
            title="Workflow node plan started",
            payload={
                "mode_ids": request.mode_ids,
                "max_steps": THINKING_MAX_PLAN_STEPS,
                "max_search_steps": THINKING_MAX_SEARCH_STEPS,
            },
        )
        self.trace_store.append_event(
            run_id,
            type="thinking.plan.started",
            status="running",
            title="Thinking plan started",
            payload={
                "mode_ids": request.mode_ids,
                "target_duration_minutes": 10,
                "max_steps": THINKING_MAX_PLAN_STEPS,
                "max_search_steps": THINKING_MAX_SEARCH_STEPS,
                "search_limit": THINKING_SEARCH_LIMIT,
            },
        )
        plan_started = perf_counter()
        plan_messages = self._build_thinking_plan_messages(
            request=request,
            role_context=role_context,
            history=history,
            short_term_summary=short_term_summary,
        )
        self.trace_store.append_event(
            run_id,
            type="model.started",
            status="running",
            title="Thinking planner model call",
            payload={
                "round": "thinking_plan",
                "message_count": len(plan_messages),
                "tools_count": 0,
                "model_preference": request.model_preference,
                "streaming": False,
                "scope": "thinking_plan",
                "workflow": "thinking",
                "workflow_node": "plan",
                "final_model_request": {
                    "messages": [self._trace_message(message) for message in plan_messages],
                    "tools": [],
                    "tool_choice": "none",
                    "temperature": 0.1,
                    "workflow": "thinking",
                    "workflow_node": "plan",
                },
            },
        )
        raw_plan: dict[str, Any] | None = None
        try:
            plan_response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=plan_messages,
                tools=None,
                temperature=0.1,
                retry_context={
                    "scope": "thinking_plan",
                    "workflow": "thinking",
                    "workflow_node": "plan",
                },
            )
            self._merge_usage(total_usage, plan_response.usage)
            if plan_response.model:
                model_names.append(plan_response.model)
            raw_plan = self._extract_json_object(plan_response.content)
            self.trace_store.append_event(
                run_id,
                type="model.completed",
                status="completed",
                title="Thinking planner model completed",
                payload={
                    "round": "thinking_plan",
                    "model": plan_response.model,
                    "usage": plan_response.usage,
                    "tool_calls": [],
                    "content_preview": plan_response.content[:500],
                    "scope": "thinking_plan",
                    "workflow": "thinking",
                    "workflow_node": "plan",
                },
                duration_ms=int((perf_counter() - plan_started) * 1000),
            )
        except Exception as e:
            logger.exception("Thinking planner failed; fallback plan used")
            self.trace_store.append_event(
                run_id,
                type="model.failed",
                status="error",
                title="Thinking planner model failed",
                payload={
                    "round": "thinking_plan",
                    "error_message": str(e),
                    "scope": "thinking_plan",
                    "workflow": "thinking",
                    "workflow_node": "plan",
                },
                duration_ms=int((perf_counter() - plan_started) * 1000),
            )

        plan = self._coerce_thinking_plan(
            raw_plan,
            request=request,
            role_context=role_context,
            history=history,
        )
        self.trace_store.append_event(
            run_id,
            type="thinking.plan.created",
            status="completed",
            title="Thinking plan created",
            payload={
                "goal": plan["goal"],
                "steps": plan["steps"],
                "fallback_used": plan["fallback_used"],
                "mode_ids": request.mode_ids,
            },
            duration_ms=int((perf_counter() - plan_started) * 1000),
        )
        self._append_workflow_event(
            run_id,
            event="workflow.node.completed",
            workflow="thinking",
            node="plan",
            status="completed",
            title="Workflow node plan completed",
            payload={
                "goal": plan["goal"],
                "step_count": len(plan["steps"]),
                "fallback_used": plan["fallback_used"],
            },
            duration_ms=int((perf_counter() - plan_node_started) * 1000),
        )

        execute_started = perf_counter()
        self._append_workflow_event(
            run_id,
            event="workflow.node.started",
            workflow="thinking",
            node="execute",
            status="running",
            title="Workflow node execute started",
            payload={
                "step_count": len(plan["steps"]),
                "step_types": [step.get("type") for step in plan["steps"]],
            },
        )
        for index, step in enumerate(plan["steps"], start=1):
            step_started = perf_counter()
            step_id = str(step.get("id") or f"step_{index}")
            step_type = str(step.get("type") or "analyze")
            self.trace_store.append_event(
                run_id,
                type="thinking.step.started",
                status="running",
                title=f"Thinking step {index}: {step.get('title') or step_id}",
                step_id=step_id,
                payload={
                    "step": step_id,
                    "step_type": step_type,
                    "step": step,
                    "index": index,
                    "workflow": "thinking",
                    "workflow_node": "execute",
                },
            )
            if step_type in AGENT_TOOL_IDS:
                if step_type not in allowed_tool_names:
                    plan_infos.append(
                        SkillCallInfo(
                            skill=step_type,
                            action=str(step.get("description") or step.get("title") or step_id),
                            status="error",
                            result_summary="tool disabled for this user",
                        )
                    )
                    self.trace_store.append_event(
                        run_id,
                        type="thinking.step.failed",
                        status="error",
                        title=f"Thinking step {index} skipped",
                        step_id=step_id,
                        payload={
                            "step": step_id,
                            "step_type": step_type,
                            "error_message": "tool disabled for this user",
                            "workflow": "thinking",
                            "workflow_node": "execute",
                        },
                        duration_ms=int((perf_counter() - step_started) * 1000),
                    )
                    continue
                arguments = {
                    "task": step.get("task") or request.message,
                    "reason": step.get("reason") or step.get("description") or step.get("title") or f"thinking:{step_type}",
                }
                if step.get("context"):
                    arguments["context"] = step["context"]
                self.trace_store.append_event(
                    run_id,
                    type="tool.started",
                    status="running",
                    title=f"Tool {step_type}",
                    step_id=step_id,
                    payload={
                        "name": step_type,
                        "arguments": arguments,
                        "workflow": "thinking",
                        "workflow_node": "execute",
                    },
                )
                result = await self._execute_agent_tool_as_result(
                    request=request,
                    role_context=role_context,
                    run_id=run_id,
                    tool_name=step_type,
                    tool_call_id=step_id,
                    arguments=arguments,
                    tool_started=step_started,
                    workflow_context={
                        "workflow": "thinking",
                        "node": "execute",
                        "node_started": execute_started,
                        "workflow_started": workflow_started,
                        "result": "agent_tool_result",
                    },
                )
                status = "completed" if result.success else "error"
                result_text = json.dumps(
                    {
                        "success": result.success,
                        "data": result.data,
                        "display_text": result.display_text,
                        "error": result.error,
                    },
                    ensure_ascii=False,
                )
                if result.success:
                    self._merge_agent_tool_payload(
                        payload=result.data,
                        skills_used=skills_used,
                        citations=citations,
                        citation_urls=citation_urls,
                        artifacts=artifacts,
                    )
                self.trace_store.append_event(
                    run_id,
                    type="tool.completed" if status == "completed" else "tool.failed",
                    status=status,
                    title=f"Tool {step_type} {status}",
                    step_id=step_id,
                    payload={
                        "name": step_type,
                        "arguments": arguments,
                        "result_preview": result_text[:500],
                        "workflow": "thinking",
                        "workflow_node": "execute",
                        "child_run_id": result.data.get("child_run_id") if isinstance(result.data, dict) else "",
                    },
                    duration_ms=int((perf_counter() - step_started) * 1000),
                )
                evidence_blocks.append(
                    f"Step {index} / {step.get('title') or step_type}\nArguments: {json.dumps(arguments, ensure_ascii=False)}\nResult: {result_text[:4000]}"
                )
                plan_infos.append(
                    SkillCallInfo(
                        skill=step_type,
                        action=str(arguments),
                        status=status,
                        result_summary=result_text[:200],
                    )
                )
                self.trace_store.append_event(
                    run_id,
                    type="thinking.step.completed" if status == "completed" else "thinking.step.failed",
                    status=status,
                    title=f"Thinking step {index} {status}",
                    step_id=step_id,
                    payload={
                        "step": step_id,
                        "step_type": step_type,
                        "arguments": arguments,
                        "workflow": "thinking",
                        "workflow_node": "execute",
                    },
                    duration_ms=int((perf_counter() - step_started) * 1000),
                )
                continue

            if step_type != "search":
                plan_infos.append(
                    SkillCallInfo(
                        skill=f"thinking_{step_type}",
                        action=str(step.get("description") or step.get("title") or step_id),
                        status="completed",
                        result_summary=str(step.get("title") or step_type)[:200],
                    )
                )
                self.trace_store.append_event(
                    run_id,
                    type="thinking.step.completed",
                    status="completed",
                    title=f"Thinking step {index} completed",
                    step_id=step_id,
                    payload={
                        "step": step_id,
                        "step_type": step_type,
                        "summary": step.get("description") or "",
                        "workflow": "thinking",
                        "workflow_node": "execute",
                    },
                    duration_ms=int((perf_counter() - step_started) * 1000),
                )
                continue

            arguments = {
                "query": step.get("query") or request.message,
                "sources": "web",
                "limit": THINKING_SEARCH_LIMIT,
            }
            search_skill = self.skill_registry.get("search")
            self.trace_store.append_event(
                run_id,
                type="tool.started",
                status="running",
                title="Tool search",
                step_id=step_id,
                payload={
                    "name": "search",
                    "arguments": arguments,
                    "workflow": "thinking",
                    "workflow_node": "execute",
                },
            )
            if "search" not in allowed_tool_names:
                status = "error"
                result_text = json.dumps({"error": "search tool disabled for this user"}, ensure_ascii=False)
            elif search_skill is None:
                status = "error"
                result_text = json.dumps({"error": "search skill is not registered"}, ensure_ascii=False)
            else:
                try:
                    result = await self._execute_skill_with_governance(
                        request=request,
                        run_id=run_id,
                        skill_name="search",
                        arguments=arguments,
                        trusted=True,
                        step_id=step_id,
                    )
                    result_data = result.data if isinstance(result.data, dict) else {}
                    new_citations = (
                        self._collect_search_citations(
                            result_data=result_data,
                            citations=citations,
                            citation_urls=citation_urls,
                        )
                        if result.success
                        else []
                    )
                    status = "completed" if result.success else "error"
                    if result.success:
                        skills_used.append("search")
                    result_text = json.dumps(
                        {
                            "success": result.success,
                            "data": result.data,
                            "display_text": result.display_text,
                            "error": result.error,
                        },
                        ensure_ascii=False,
                    )
                    if new_citations:
                        self.trace_store.append_event(
                            run_id,
                            type="citations.collected",
                            status="completed",
                            title="Search citations collected",
                            step_id=step_id,
                            payload={
                                "count": len(new_citations),
                                "total": len(citations),
                                "urls": [citation.url for citation in new_citations],
                            },
                        )
                except Exception as e:
                    logger.exception("Thinking search failed")
                    status = "error"
                    result_text = json.dumps({"error": str(e)}, ensure_ascii=False)

            self.trace_store.append_event(
                run_id,
                type="tool.completed" if status == "completed" else "tool.failed",
                status=status,
                title=f"Tool search {status}",
                step_id=step_id,
                payload={
                    "name": "search",
                    "arguments": arguments,
                    "result_preview": result_text[:500],
                    "workflow": "thinking",
                    "workflow_node": "execute",
                },
                duration_ms=int((perf_counter() - step_started) * 1000),
            )
            evidence_blocks.append(
                f"Step {index} / {step.get('title') or 'search'}\nArguments: {json.dumps(arguments, ensure_ascii=False)}\nResult: {result_text[:4000]}"
            )
            plan_infos.append(
                SkillCallInfo(
                    skill="search",
                    action=str(arguments),
                    status=status,
                    result_summary=result_text[:200],
                )
            )
            self.trace_store.append_event(
                run_id,
                type="thinking.step.completed" if status == "completed" else "thinking.step.failed",
                status=status,
                title=f"Thinking step {index} {status}",
                step_id=step_id,
                payload={
                    "step": step_id,
                    "step_type": step_type,
                    "arguments": arguments,
                    "citation_count": len(citations),
                    "result_preview": result_text[:500],
                    "workflow": "thinking",
                    "workflow_node": "execute",
                },
                duration_ms=int((perf_counter() - step_started) * 1000),
            )

        self._append_workflow_event(
            run_id,
            event="workflow.node.completed",
            workflow="thinking",
            node="execute",
            status="completed",
            title="Workflow node execute completed",
            payload={
                "step_count": len(plan["steps"]),
                "skills_used": list(dict.fromkeys(skills_used)),
                "citation_count": len(citations),
            },
            duration_ms=int((perf_counter() - execute_started) * 1000),
        )

        summary_node_started = perf_counter()
        self._append_workflow_event(
            run_id,
            event="workflow.node.started",
            workflow="thinking",
            node="summary",
            status="running",
            title="Workflow node summary started",
            payload={
                "evidence_block_count": len(evidence_blocks),
                "citation_count": len(citations),
            },
        )
        summary_started = perf_counter()
        summary_messages = self._build_thinking_summary_messages(
            request=request,
            role_context=role_context,
            plan=plan,
            evidence_blocks=evidence_blocks,
            citations=citations,
        )
        self.trace_store.append_event(
            run_id,
            type="model.started",
            status="running",
            title="Thinking summary model call",
            payload={
                "round": "thinking_summary",
                "message_count": len(summary_messages),
                "tools_count": 0,
                "model_preference": request.model_preference,
                "streaming": False,
                "scope": "thinking_summary",
                "workflow": "thinking",
                "workflow_node": "summary",
                "final_model_request": {
                    "messages": [self._trace_message(message) for message in summary_messages],
                    "tools": [],
                    "tool_choice": "none",
                    "temperature": 0.2,
                    "workflow": "thinking",
                    "workflow_node": "summary",
                },
            },
        )
        summary_response = await self._chat_with_retry(
            provider,
            request=request,
            run_id=run_id,
            messages=summary_messages,
            tools=None,
            temperature=0.2,
            retry_context={
                "scope": "thinking_summary",
                "workflow": "thinking",
                "workflow_node": "summary",
            },
        )
        self._merge_usage(total_usage, summary_response.usage)
        if summary_response.model:
            model_names.append(summary_response.model)
        response_text = summary_response.content.strip() or "Thinking workflow completed, but the model returned no summary."
        self.trace_store.append_event(
            run_id,
            type="model.completed",
            status="completed",
            title="Thinking summary model completed",
            payload={
                "round": "thinking_summary",
                "model": summary_response.model,
                "usage": summary_response.usage,
                "tool_calls": [],
                "content_preview": response_text[:500],
                "scope": "thinking_summary",
                "workflow": "thinking",
                "workflow_node": "summary",
            },
            duration_ms=int((perf_counter() - summary_started) * 1000),
        )
        self.trace_store.append_event(
            run_id,
            type="thinking.summary.completed",
            status="completed",
            title="Thinking workflow summary completed",
            payload={
                "step_count": len(plan["steps"]),
                "skills_used": list(dict.fromkeys(skills_used)),
                "citation_count": len(citations),
                "summary_preview": response_text[:500],
            },
            duration_ms=int((perf_counter() - summary_started) * 1000),
        )
        self._append_workflow_event(
            run_id,
            event="workflow.node.completed",
            workflow="thinking",
            node="summary",
            status="completed",
            title="Workflow node summary completed",
            payload={
                "summary_preview": response_text[:500],
                "citation_count": len(citations),
            },
            duration_ms=int((perf_counter() - summary_node_started) * 1000),
        )
        self._append_workflow_event(
            run_id,
            event="workflow.completed",
            workflow="thinking",
            status="completed",
            title="Workflow thinking completed",
            payload={
                "step_count": len(plan["steps"]),
                "skills_used": list(dict.fromkeys(skills_used)),
                "citation_count": len(citations),
            },
            duration_ms=int((perf_counter() - workflow_started) * 1000),
        )

        new_messages.append(LLMMessage(role="assistant", content=response_text))
        self._add_conversation_memory(request, new_messages)

        unique_skills = list(dict.fromkeys(skills_used))
        model_used = ", ".join(dict.fromkeys(model_names))
        self.trace_store.complete_run(
            run_id,
            output=response_text,
            model_used=model_used,
            tokens_used=total_usage,
            skills_used=unique_skills,
        )
        events = self._snapshot_run_events(run_id)
        self._schedule_memory_postprocess(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=response_text,
            new_messages=new_messages,
            run_id=run_id,
        )
        return ChatResponse(
            conversation_id=request.conversation_id,
            response=response_text,
            skills_used=unique_skills,
            citations=citations,
            plan=plan_infos if plan_infos else None,
            model_used=model_used,
            tokens_used=total_usage,
            agent_id=agent_id,
            role_id=role_id,
            runtime=runtime,
            run_id=run_id,
            events=events,
            memory_context=role_context.records,
            memory_updates=[],
        )

    async def _complete_deep_research_response(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_id: str,
        role_context: MemoryContext,
        runtime: str,
        run_id: str,
        response_text: str,
        new_messages: list[LLMMessage],
        skills_used: list[str] | None = None,
        citations: list[Citation] | None = None,
        artifacts: list[ChatArtifact] | None = None,
        plan: list[SkillCallInfo] | None = None,
        model_used: str = "",
        tokens_used: dict[str, int] | None = None,
        review_memory: bool = True,
    ) -> ChatResponse:
        self._add_conversation_memory(request, new_messages)

        unique_skills = list(dict.fromkeys(skills_used or []))
        response_artifacts: list[ChatArtifact] = list(artifacts or [])
        if review_memory and citations and agent_id != RESEARCH_AGENT_ID:
            try:
                provider = self._get_provider(request.model_preference)
                auto_plan: list[SkillCallInfo] = list(plan or [])
                mutable_skills = list(unique_skills)
                await self._maybe_auto_save_drive_report(
                    request=request,
                    agent_id=agent_id,
                    provider=provider,
                    run_id=run_id,
                    tools=[],
                    final_content=response_text,
                    skills_used=mutable_skills,
                    citations=citations or [],
                    artifacts=response_artifacts,
                    plan=auto_plan,
                )
                unique_skills = list(dict.fromkeys(mutable_skills))
                plan = auto_plan if auto_plan else plan
            except Exception as e:
                logger.warning("Deep research drive auto-save skipped: %s", e)
        self.trace_store.complete_run(
            run_id,
            output=response_text,
            model_used=model_used,
            tokens_used=tokens_used or {},
            skills_used=unique_skills,
            artifacts=[artifact.model_dump(mode="json") for artifact in response_artifacts],
        )
        events = self._snapshot_run_events(run_id)
        if review_memory:
            self._schedule_memory_postprocess(
                request=request,
                agent_id=agent_id,
                role_context=role_context,
                assistant_message=response_text,
                new_messages=new_messages,
                run_id=run_id,
            )
        return ChatResponse(
            conversation_id=request.conversation_id,
            response=response_text,
            skills_used=unique_skills,
            citations=citations or [],
            artifacts=response_artifacts,
            plan=plan,
            model_used=model_used,
            tokens_used=tokens_used or {},
            agent_id=agent_id,
            role_id=role_id,
            runtime=runtime,
            run_id=run_id,
            events=events,
            memory_context=role_context.records,
            memory_updates=[],
        )

    async def _generate_deep_research_plan(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        short_term_summary: str,
        run_id: str,
        question: str,
    ) -> tuple[str, str, dict[str, int]]:
        messages = self._build_deep_research_plan_messages(
            request=request,
            role_context=role_context,
            history=history,
            short_term_summary=short_term_summary,
            question=question,
        )
        started = perf_counter()
        self.trace_store.append_event(
            run_id,
            type="research.plan.started",
            status="running",
            title="Deep research plan started",
            payload={"question": question[:500]},
        )
        provider = self._get_provider(request.model_preference)
        try:
            response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=messages,
                tools=None,
                temperature=0.2,
                retry_context={"scope": "deep_research_plan"},
            )
        except Exception as e:
            logger.exception("Deep research plan generation failed; fallback plan used")
            plan_text = self._ensure_deep_research_plan_marker(self._fallback_deep_research_plan(question))
            self.trace_store.append_event(
                run_id,
                type="research.plan.failed",
                status="error",
                title="Deep research plan generation failed; fallback used",
                payload={
                    "error_message": str(e)[:500],
                    "plan_preview": self._strip_deep_research_plan_marker(plan_text)[:500],
                    "fallback_used": True,
                },
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return plan_text, "", {}
        plan_text = self._ensure_deep_research_plan_marker(response.content or self._fallback_deep_research_plan(question))
        self.trace_store.append_event(
            run_id,
            type="research.plan.completed",
            status="completed",
            title="Deep research plan completed",
            payload={
                "model": response.model,
                "usage": response.usage,
                "plan_preview": self._strip_deep_research_plan_marker(plan_text)[:500],
            },
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return plan_text, response.model, dict(response.usage)

    async def _execute_deep_research_search_queries(
        self,
        *,
        request: ChatRequest,
        run_id: str,
        search_skill: Any,
        queries: list[str],
        target_result_count: int | None,
        citations: list[Citation],
        citation_urls: set[str],
        skills_used: list[str],
        plan_infos: list[SkillCallInfo],
        start_index: int,
        phase: str,
        supplemental_round: int = 0,
    ) -> tuple[int, int]:
        executed_count = 0
        source_count_before = len(citations)
        for offset, query in enumerate(queries):
            if target_result_count is not None and len(citations) >= target_result_count:
                break
            query_index = start_index + offset
            search_started = perf_counter()
            arguments = {
                "query": query,
                "sources": "web",
                "limit": DEEP_RESEARCH_SEARCH_LIMIT,
            }
            payload_context = {
                "query": query,
                "arguments": arguments,
                "collected_count": len(citations),
                "phase": phase,
            }
            if supplemental_round:
                payload_context["supplemental_round"] = supplemental_round
            self.trace_store.append_event(
                run_id,
                type="research.search.started",
                status="running",
                title=f"Deep research search {query_index}",
                payload=payload_context,
            )
            try:
                result = await self._execute_skill_with_governance(
                    request=request,
                    run_id=run_id,
                    skill_name="search",
                    arguments=arguments,
                    trusted=True,
                    step_id=f"deep_research_search_{query_index}",
                )
                executed_count += 1
                status = "completed" if result.success else "error"
                result_data = result.data if isinstance(result.data, dict) else {}
                new_citations = (
                    self._collect_search_citations(
                        result_data=result_data,
                        citations=citations,
                        citation_urls=citation_urls,
                    )
                    if result.success
                    else []
                )
                if result.success:
                    skills_used.append("search")
                result_summary = (
                    result.display_text
                    or result.error
                    or json.dumps(result_data, ensure_ascii=False)
                )
                self.trace_store.append_event(
                    run_id,
                    type="research.search.completed" if result.success else "research.search.failed",
                    status=status,
                    title=f"Deep research search {query_index} {status}",
                    payload={
                        **payload_context,
                        "success": result.success,
                        "new_citation_count": len(new_citations),
                        "total_citation_count": len(citations),
                        "error": result.error,
                        "result_preview": str(result_summary)[:500],
                    },
                    duration_ms=int((perf_counter() - search_started) * 1000),
                )
                if phase != "initial":
                    self.trace_store.append_event(
                        run_id,
                        type="research.supplemental_search.completed" if result.success else "research.supplemental_search.failed",
                        status=status,
                        title=f"Deep research supplemental search {query_index} {status}",
                        payload={
                            "query": query,
                            "supplemental_round": supplemental_round,
                            "new_citation_count": len(new_citations),
                            "total_citation_count": len(citations),
                        },
                        duration_ms=int((perf_counter() - search_started) * 1000),
                    )
                plan_infos.append(
                    SkillCallInfo(
                        skill="search",
                        action=str(arguments),
                        status=status,
                        result_summary=str(result_summary)[:200],
                    )
                )
            except Exception as e:
                logger.exception("Deep research search failed")
                executed_count += 1
                self.trace_store.append_event(
                    run_id,
                    type="research.search.failed",
                    status="error",
                    title=f"Deep research search {query_index} failed",
                    payload={
                        **payload_context,
                        "error_message": str(e),
                    },
                    duration_ms=int((perf_counter() - search_started) * 1000),
                )
                if phase != "initial":
                    self.trace_store.append_event(
                        run_id,
                        type="research.supplemental_search.failed",
                        status="error",
                        title=f"Deep research supplemental search {query_index} failed",
                        payload={
                            "query": query,
                            "supplemental_round": supplemental_round,
                            "error_message": str(e)[:500],
                        },
                        duration_ms=int((perf_counter() - search_started) * 1000),
                    )
                plan_infos.append(
                    SkillCallInfo(
                        skill="search",
                        action=str(arguments),
                        status="error",
                        result_summary=str(e)[:200],
                    )
                )
        return executed_count, len(citations) - source_count_before

    async def _summarize_deep_research_chunks(
        self,
        *,
        provider: LLMProvider,
        request: ChatRequest,
        run_id: str,
        question: str,
        plan_text: str,
        chunks: list[list[Citation]],
        summaries: list[str],
        total_usage: dict[str, int],
        model_names: list[str],
        start_index: int,
        total_chunks: int,
        phase: str,
    ) -> None:
        for offset, chunk in enumerate(chunks):
            chunk_index = start_index + offset
            summary_started = perf_counter()
            self.trace_store.append_event(
                run_id,
                type="research.step_summary.started",
                status="running",
                title=f"Deep research source summary {chunk_index}",
                payload={
                    "chunk": chunk_index,
                    "chunk_count": total_chunks,
                    "source_count": len(chunk),
                    "phase": phase,
                },
            )
            try:
                summary_response = await self._chat_with_retry(
                    provider,
                    request=request,
                    run_id=run_id,
                    messages=self._build_deep_research_summary_messages(
                        question=question,
                        plan_text=plan_text,
                        chunk_index=chunk_index,
                        chunk_count=total_chunks,
                        citations=chunk,
                    ),
                    tools=None,
                    temperature=0.2,
                    retry_context={
                        "scope": "deep_research_step_summary",
                        "chunk": chunk_index,
                        "chunk_count": total_chunks,
                        "phase": phase,
                    },
                )
                self._merge_usage(total_usage, summary_response.usage)
                if summary_response.model:
                    model_names.append(summary_response.model)
                summaries.append(summary_response.content.strip())
                self.trace_store.append_event(
                    run_id,
                    type="research.step_summary.completed",
                    status="completed",
                    title=f"Deep research source summary {chunk_index} completed",
                    payload={
                        "chunk": chunk_index,
                        "model": summary_response.model,
                        "usage": summary_response.usage,
                        "summary_preview": summary_response.content[:500],
                        "phase": phase,
                    },
                    duration_ms=int((perf_counter() - summary_started) * 1000),
                )
            except Exception as e:
                logger.exception("Deep research source summary failed; fallback summary used")
                fallback_summary = self._fallback_deep_research_summary(
                    chunk_index=chunk_index,
                    chunk_count=total_chunks,
                    citations=chunk,
                    error_message=str(e),
                )
                summaries.append(fallback_summary)
                self.trace_store.append_event(
                    run_id,
                    type="research.step_summary.failed",
                    status="error",
                    title=f"Deep research source summary {chunk_index} failed; fallback used",
                    payload={
                        "chunk": chunk_index,
                        "error_message": str(e)[:500],
                        "source_count": len(chunk),
                        "summary_preview": fallback_summary[:500],
                        "fallback_used": True,
                        "phase": phase,
                    },
                    duration_ms=int((perf_counter() - summary_started) * 1000),
                )

    async def _execute_deep_research(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        run_id: str,
        question: str,
        plan_text: str,
    ) -> dict[str, Any]:
        provider = self._get_provider(request.model_preference)
        total_usage: dict[str, int] = {}
        model_names: list[str] = []
        skills_used: list[str] = []
        plan_infos: list[SkillCallInfo] = []
        artifacts: list[ChatArtifact] = []
        citations: list[Citation] = []
        citation_urls: set[str] = set()

        self.trace_store.append_event(
            run_id,
            type="research.execution.started",
            status="running",
            title="Deep research execution started",
            payload={
                "question": question[:500],
                "target_result_count": DEEP_RESEARCH_DEFAULT_TARGET_RESULTS,
                "search_limit": DEEP_RESEARCH_SEARCH_LIMIT,
            },
        )

        query_started = perf_counter()
        try:
            query_response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=self._build_deep_research_query_messages(
                    question=question,
                    plan_text=plan_text,
                    drive_context=request.drive_context,
                ),
                tools=None,
                temperature=0.2,
                retry_context={"scope": "deep_research_queries"},
            )
            self._merge_usage(total_usage, query_response.usage)
            if query_response.model:
                model_names.append(query_response.model)
            raw_queries = self._extract_json_object(query_response.content)
            queries, target_result_count = self._coerce_deep_research_queries(raw_queries, question)
            self.trace_store.append_event(
                run_id,
                type="research.queries.created",
                status="completed",
                title="Deep research queries created",
                payload={
                    "model": query_response.model,
                    "usage": query_response.usage,
                    "query_count": len(queries),
                    "target_result_count": target_result_count,
                    "queries": queries,
                },
                duration_ms=int((perf_counter() - query_started) * 1000),
            )
        except Exception as e:
            logger.exception("Deep research query generation failed; fallback queries used")
            queries, target_result_count = self._coerce_deep_research_queries(None, question)
            self.trace_store.append_event(
                run_id,
                type="research.queries.failed",
                status="error",
                title="Deep research query generation failed; fallback used",
                payload={
                    "error_message": str(e)[:500],
                    "query_count": len(queries),
                    "target_result_count": target_result_count,
                    "queries": queries,
                    "fallback_used": True,
                },
                duration_ms=int((perf_counter() - query_started) * 1000),
            )

        search_skill = self.skill_registry.get("search")
        executed_queries: list[str] = []
        executed_search_count = 0
        next_search_index = 1
        if search_skill is None:
            self.trace_store.append_event(
                run_id,
                type="research.search.failed",
                status="error",
                title="Search skill unavailable",
                payload={"error_message": "search skill is not registered"},
            )
        else:
            executed_count, _new_count = await self._execute_deep_research_search_queries(
                request=request,
                run_id=run_id,
                search_skill=search_skill,
                queries=queries,
                target_result_count=target_result_count,
                citations=citations,
                citation_urls=citation_urls,
                skills_used=skills_used,
                plan_infos=plan_infos,
                start_index=next_search_index,
                phase="initial",
            )
            executed_queries.extend(queries[:executed_count])
            executed_search_count += executed_count
            next_search_index += executed_count

        summaries: list[str] = []
        chunks = [
            citations[index:index + DEEP_RESEARCH_SUMMARY_CHUNK_SIZE]
            for index in range(0, len(citations), DEEP_RESEARCH_SUMMARY_CHUNK_SIZE)
        ]
        await self._summarize_deep_research_chunks(
            provider=provider,
            request=request,
            run_id=run_id,
            question=question,
            plan_text=plan_text,
            chunks=chunks,
            summaries=summaries,
            total_usage=total_usage,
            model_names=model_names,
            start_index=1,
            total_chunks=len(chunks),
            phase="initial",
        )

        coverage_reviews: list[dict[str, Any]] = []
        for supplemental_round in range(1, DEEP_RESEARCH_SUPPLEMENTAL_MAX_ROUNDS + 1):
            gap_started = perf_counter()
            self.trace_store.append_event(
                run_id,
                type="research.gap_review.started",
                status="running",
                title=f"Deep research gap review {supplemental_round}",
                payload={
                    "round": supplemental_round,
                    "source_count": len(citations),
                    "summary_count": len(summaries),
                    "executed_query_count": len(executed_queries),
                },
            )
            review: dict[str, Any]
            try:
                gap_response = await self._chat_with_retry(
                    provider,
                    request=request,
                    run_id=run_id,
                    messages=self._build_deep_research_gap_review_messages(
                        question=question,
                        plan_text=plan_text,
                        summaries=summaries,
                        citations=citations,
                        executed_queries=executed_queries,
                        round_index=supplemental_round,
                    ),
                    tools=None,
                    temperature=0.2,
                    retry_context={
                        "scope": "deep_research_gap_review",
                        "round": supplemental_round,
                    },
                )
                self._merge_usage(total_usage, gap_response.usage)
                if gap_response.model:
                    model_names.append(gap_response.model)
                review = self._coerce_deep_research_gap_review(
                    self._extract_json_object(gap_response.content),
                    executed_queries=executed_queries,
                )
                coverage_reviews.append(review)
                self.trace_store.append_event(
                    run_id,
                    type="research.gap_review.completed",
                    status="completed",
                    title=f"Deep research gap review {supplemental_round} completed",
                    payload={
                        "round": supplemental_round,
                        "model": gap_response.model,
                        "usage": gap_response.usage,
                        "coverage_status": review.get("coverage_status"),
                        "missing_data": review.get("missing_data"),
                        "supplemental_queries": review.get("supplemental_queries"),
                        "stop_reason": review.get("stop_reason"),
                    },
                    duration_ms=int((perf_counter() - gap_started) * 1000),
                )
            except Exception as e:
                logger.exception("Deep research gap review failed; continuing with current evidence")
                self.trace_store.append_event(
                    run_id,
                    type="research.gap_review.failed",
                    status="error",
                    title=f"Deep research gap review {supplemental_round} failed",
                    payload={
                        "error_message": str(e)[:500],
                        "round": supplemental_round,
                    },
                    duration_ms=int((perf_counter() - gap_started) * 1000),
                )
                break

            supplemental_queries = list(review.get("supplemental_queries") or [])
            if not supplemental_queries:
                break
            if search_skill is None:
                self.trace_store.append_event(
                    run_id,
                    type="research.supplemental_search.skipped",
                    status="partial",
                    title="Deep research supplemental search skipped",
                    payload={
                        "round": supplemental_round,
                        "reason": "search skill is not registered",
                        "supplemental_queries": supplemental_queries,
                    },
                )
                break

            before_supplemental_count = len(citations)
            executed_count, new_count = await self._execute_deep_research_search_queries(
                request=request,
                run_id=run_id,
                search_skill=search_skill,
                queries=supplemental_queries,
                target_result_count=target_result_count,
                citations=citations,
                citation_urls=citation_urls,
                skills_used=skills_used,
                plan_infos=plan_infos,
                start_index=next_search_index,
                phase="supplemental",
                supplemental_round=supplemental_round,
            )
            executed_queries.extend(supplemental_queries[:executed_count])
            executed_search_count += executed_count
            next_search_index += executed_count

            new_citations = citations[before_supplemental_count:]
            if new_citations:
                supplemental_chunks = [
                    new_citations[index:index + DEEP_RESEARCH_SUMMARY_CHUNK_SIZE]
                    for index in range(0, len(new_citations), DEEP_RESEARCH_SUMMARY_CHUNK_SIZE)
                ]
                await self._summarize_deep_research_chunks(
                    provider=provider,
                    request=request,
                    run_id=run_id,
                    question=question,
                    plan_text=plan_text,
                    chunks=supplemental_chunks,
                    summaries=summaries,
                    total_usage=total_usage,
                    model_names=model_names,
                    start_index=len(summaries) + 1,
                    total_chunks=len(summaries) + len(supplemental_chunks),
                    phase="supplemental",
                )
            if new_count < DEEP_RESEARCH_SUPPLEMENTAL_MIN_NEW_SOURCES:
                self.trace_store.append_event(
                    run_id,
                    type="research.gap_review.stopped",
                    status="partial",
                    title="Deep research supplementation stopped after low-yield search",
                    payload={
                        "round": supplemental_round,
                        "new_citation_count": new_count,
                        "min_new_sources": DEEP_RESEARCH_SUPPLEMENTAL_MIN_NEW_SOURCES,
                    },
                )
                break

        report_started = perf_counter()
        self.trace_store.append_event(
            run_id,
            type="research.report.started",
            status="running",
            title="Deep research report started",
            payload={
                "source_count": len(citations),
                "summary_count": len(summaries),
            },
        )
        try:
            report_response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=self._build_deep_research_report_messages(
                    question=question,
                    plan_text=plan_text,
                    summaries=summaries,
                    citations=citations,
                    search_count=executed_search_count,
                    coverage_reviews=coverage_reviews,
                ),
                tools=None,
                temperature=0.2,
                retry_context={"scope": "deep_research_report"},
            )
            self._merge_usage(total_usage, report_response.usage)
            if report_response.model:
                model_names.append(report_response.model)
            report = report_response.content.strip()
            self.trace_store.append_event(
                run_id,
                type="research.report.completed",
                status="completed",
                title="Deep research report completed",
                payload={
                    "model": report_response.model,
                    "usage": report_response.usage,
                    "source_count": len(citations),
                    "query_count": executed_search_count,
                    "initial_query_count": len(queries),
                    "gap_review_count": len(coverage_reviews),
                    "report_preview": report[:500],
                },
                duration_ms=int((perf_counter() - report_started) * 1000),
            )
        except Exception as e:
            logger.exception("Deep research report generation failed; fallback report used")
            report = self._fallback_deep_research_report(
                question=question,
                plan_text=plan_text,
                summaries=summaries,
                citations=citations,
                search_count=executed_search_count,
                error_message=str(e),
            )
            self.trace_store.append_event(
                run_id,
                type="research.report.failed",
                status="error",
                title="Deep research report generation failed; fallback used",
                payload={
                    "error_message": str(e)[:500],
                    "source_count": len(citations),
                    "query_count": executed_search_count,
                    "initial_query_count": len(queries),
                    "gap_review_count": len(coverage_reviews),
                    "report_preview": report[:500],
                    "fallback_used": True,
                },
                duration_ms=int((perf_counter() - report_started) * 1000),
            )
        report = self._link_inline_citations(report, citations)
        plan_infos.append(
            SkillCallInfo(
                skill="research_report",
                action="synthesize approved plan, search summaries, and citations",
                status="completed",
                result_summary=report[:200],
            )
        )
        archive_status = await self._archive_deep_research_report_to_drive(
            request=request,
            run_id=run_id,
            question=question,
            report=report,
            skills_used=skills_used,
            plan_infos=plan_infos,
            artifacts=artifacts,
        )
        self.trace_store.append_event(
            run_id,
            type="research.execution.completed",
            status="completed",
            title="Deep research execution completed",
            payload={
                "query_count": executed_search_count,
                "initial_query_count": len(queries),
                "gap_review_count": len(coverage_reviews),
                "source_count": len(citations),
                "summary_count": len(summaries),
                "archive_status": archive_status,
                "artifact_count": len(artifacts),
            },
        )
        return {
            "report": report,
            "model_used": ", ".join(list(dict.fromkeys(model_names))),
            "tokens_used": total_usage,
            "skills_used": skills_used,
            "citations": citations,
            "plan": plan_infos,
            "artifacts": artifacts,
        }

    async def _process_deep_research(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_id: str,
        role_context: MemoryContext,
        run_id: str,
        runtime: str,
        delegation_trace: dict[str, Any] | None = None,
    ) -> ChatResponse:
        conversation_context = self.memory.get_context(self._conversation_memory_id(request))
        history = conversation_context.messages if request.memory_enabled else []
        short_term_summary = conversation_context.summary if request.memory_enabled else ""
        context_blocks_for_model = self._context_blocks_for_model(
            request.context_blocks,
            history=history,
        )
        tools = self._tool_definitions_for_agent(agent_id, request.disabled_tools)
        drive_prompt_source = self._drive_context_prompt_source(request.drive_context)
        prompt_sources = [drive_prompt_source] if drive_prompt_source else []
        context_messages = [
            LLMMessage(
                role="system",
                content=self._build_deep_research_context_prompt(
                    role_context=role_context,
                    short_term_summary=short_term_summary,
                    drive_context=request.drive_context,
                ),
            ),
            *history,
            LLMMessage(role="user", content=request.message),
        ]
        self.trace_store.append_event(
            run_id,
            type="memory.loaded",
            status="completed",
            title="Role memory loaded",
            payload=self._memory_loaded_payload(
                role_id=role_id,
                user_id=self._user_id(request),
                role_context=role_context,
            ),
        )
        self._append_context_trace(
            run_id=run_id,
            role_id=role_id,
            role_context=role_context,
            messages=context_messages,
            tools_count=len(tools),
            tool_names=[tool.name for tool in tools],
            mode_ids=request.mode_ids,
            mode_prompts=request.mode_prompts,
            context_blocks=context_blocks_for_model,
            short_term_summary=short_term_summary,
            prompt_sources=prompt_sources,
        )
        if delegation_trace:
            self.trace_store.append_event(
                run_id,
                type="agent.delegated",
                status="completed",
                title="Delegated to Deep Research Agent",
                payload=delegation_trace,
            )

        if self._is_deep_research_help_request(request.message):
            response_text = self._deep_research_help_response()
            return await self._complete_deep_research_response(
                request=request,
                agent_id=agent_id,
                role_id=role_id,
                role_context=role_context,
                runtime=runtime,
                run_id=run_id,
                response_text=response_text,
                new_messages=[
                    LLMMessage(role="user", content=request.message),
                    LLMMessage(role="assistant", content=response_text),
                ],
                review_memory=False,
            )

        plan_text, planned_question = self._find_latest_deep_research_plan(history, request.context_blocks)
        if self._is_deep_research_start_request(request.message):
            if not plan_text:
                response_text = "我还没有可执行的研究计划。请先发送 `/plan <研究问题>`，我会给你一份计划大纲确认。"
                return await self._complete_deep_research_response(
                    request=request,
                    agent_id=agent_id,
                    role_id=role_id,
                    role_context=role_context,
                    runtime=runtime,
                    run_id=run_id,
                    response_text=response_text,
                    new_messages=[
                        LLMMessage(role="user", content=request.message),
                        LLMMessage(role="assistant", content=response_text),
                    ],
                    review_memory=False,
                )
            question = planned_question or self._normalize_deep_research_user_text(request.message) or "已确认的研究问题"
            execution = await self._execute_deep_research(
                request=request,
                role_context=role_context,
                history=history,
                run_id=run_id,
                question=question,
                plan_text=plan_text,
            )
            report = execution["report"] or "研究执行完成，但模型没有返回报告正文。"
            return await self._complete_deep_research_response(
                request=request,
                agent_id=agent_id,
                role_id=role_id,
                role_context=role_context,
                runtime=runtime,
                run_id=run_id,
                response_text=report,
                new_messages=[
                    LLMMessage(role="user", content=request.message),
                    LLMMessage(role="assistant", content=report),
                ],
                skills_used=execution["skills_used"],
                citations=execution["citations"],
                artifacts=execution.get("artifacts") or [],
                plan=execution["plan"],
                model_used=execution["model_used"],
                tokens_used=execution["tokens_used"],
            )

        question = self._normalize_deep_research_user_text(request.message)
        if not question:
            response_text = "请告诉我你要研究的问题，例如：`/plan 2026 年 AI Agent 开发框架的商业化趋势`。"
            return await self._complete_deep_research_response(
                request=request,
                agent_id=agent_id,
                role_id=role_id,
                role_context=role_context,
                runtime=runtime,
                run_id=run_id,
                response_text=response_text,
                new_messages=[
                    LLMMessage(role="user", content=request.message),
                    LLMMessage(role="assistant", content=response_text),
                ],
                review_memory=False,
            )

        stored_plan_response, model_used, usage = await self._generate_deep_research_plan(
            request=request,
            role_context=role_context,
            history=history,
            short_term_summary=short_term_summary,
            run_id=run_id,
            question=question,
        )
        visible_plan_response = self._strip_deep_research_plan_marker(stored_plan_response)
        return await self._complete_deep_research_response(
            request=request,
            agent_id=agent_id,
            role_id=role_id,
            role_context=role_context,
            runtime=runtime,
            run_id=run_id,
            response_text=visible_plan_response,
            new_messages=[
                LLMMessage(role="user", content=request.message),
                LLMMessage(role="assistant", content=stored_plan_response),
            ],
            plan=[
                SkillCallInfo(
                    skill="research_plan",
                    action=question,
                    status="pending",
                    result_summary="等待用户确认后执行深度研究。",
                )
            ],
            model_used=model_used,
            tokens_used=usage,
        )

    def _aigc_retrieval_required(self, request: ChatRequest) -> bool:
        mode_ids = set(request.mode_ids or [])
        if mode_ids & AIGC_RESEARCH_MODE_IDS:
            return True

        mode_text = "\n".join(request.mode_prompts or []).lower()
        if any(keyword in mode_text for keyword in ["研究", "调研", "搜索", "plan", "research"]):
            return True

        normalized = re.sub(r"\s+", " ", (request.message or "").lower()).strip()
        research_phrases = [
            "收集一下信息",
            "收集信息",
            "收集资料",
            "整理资料",
            "整理信息",
            "调研一下",
            "做一下调研",
            "研究一下",
            "查一下",
            "搜索一下",
            "检索一下",
            "先分析",
            "先计划",
            "是否值得投资",
            "worth investing",
            "investment analysis",
            "market research",
        ]
        return any(phrase in normalized for phrase in research_phrases)

    def _aigc_persisted_context_messages(self, context_blocks: list[str] | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for block in context_blocks or []:
            text = str(block or "")
            if "Persisted conversation history" not in text and "持久化会话历史" not in text:
                continue

            matches = list(re.finditer(r"(?:^|\n)(user|assistant|用户|助手)[：:]\s*", text))
            for index, match in enumerate(matches):
                start = match.end()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                content = text[start:end].strip()
                if content:
                    role = match.group(1)
                    normalized_role = "user" if role in {"user", "用户"} else "assistant"
                    messages.append({"role": normalized_role, "content": content})
        return messages

    def _aigc_existing_context_messages(
        self,
        *,
        request: ChatRequest,
        history: list[LLMMessage],
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for message in history:
            if message.role not in {"user", "assistant"}:
                continue
            content = message.content
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            content = content.strip()
            if content:
                messages.append({"role": message.role, "content": content})

        messages.extend(self._aigc_persisted_context_messages(request.context_blocks))
        return messages

    def _compact_handoff_text(self, value: str, limit: int = 1800) -> str:
        text = " ".join(str(value or "").split()).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _is_low_signal_aigc_handoff_message(self, content: str) -> bool:
        lowered = content.lower()
        low_signal_markers = (
            "![ai 生图",
            "**图片结果**",
            "图片 url 通常会",
            "i cannot generate images in this chat",
            "cannot generate images",
            "无法生成图片",
            "不能生成图片",
            "这次图片没有生成成功",
        )
        return any(marker in lowered or marker in content for marker in low_signal_markers)

    def _aigc_handoff_messages(
        self,
        *,
        request: ChatRequest,
        history: list[LLMMessage],
    ) -> list[AgentHandoffMessage]:
        raw_messages: list[tuple[str, str, str]] = []
        for message in history:
            if message.role not in {"user", "assistant"}:
                continue
            content = message.content
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            raw_messages.append((message.role, content, "memory"))

        for message in self._aigc_persisted_context_messages(request.context_blocks):
            raw_messages.append((message["role"], message["content"], "persisted_context"))

        deduped: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for role, content, source in raw_messages:
            compact = self._compact_handoff_text(content)
            if not compact or self._is_low_signal_aigc_handoff_message(compact):
                continue
            key = (role, compact)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((role, compact, source))

        selected = deduped[-10:]
        return [
            AgentHandoffMessage(
                role="assistant" if role == "assistant" else "user",
                content=content,
                source=source,
                index=index,
            )
            for index, (role, content, source) in enumerate(selected, start=1)
        ]

    def _aigc_handoff_attachments(
        self,
        attachments: list[ChatAttachment],
    ) -> list[AgentHandoffAttachment]:
        packets: list[AgentHandoffAttachment] = []
        for attachment in attachments[:8]:
            packets.append(
                AgentHandoffAttachment(
                    name=attachment.name or "untitled",
                    kind=attachment.kind or "file",
                    mime_type=attachment.type or "",
                    size=attachment.size or 0,
                    content_preview=self._compact_handoff_text(attachment.content or "", 900),
                    has_data_url=bool(attachment.data_url),
                    truncated=bool(attachment.truncated),
                )
            )
        return packets

    def _build_agent_handoff_packet(
        self,
        *,
        request: ChatRequest,
        source_agent_id: str,
        target_agent_id: str,
        history: list[LLMMessage],
        context_brief: str = "",
        delegation_trace: dict[str, Any] | None = None,
        stage_contexts: list[AgentStageContext] | None = None,
    ) -> AgentHandoffPacket:
        provided_packet = request.agent_input or request.handoff
        if provided_packet is not None and provided_packet.target_agent_id == target_agent_id:
            return provided_packet

        context_blocks = self._normalize_context_blocks(request.context_blocks)
        reason = ""
        forced = False
        if delegation_trace:
            reason = str(delegation_trace.get("reason") or "")
            forced = bool(delegation_trace.get("forced"))

        constraints = [
            "把 current_request 视为用户最新目标。",
            "如果存在 candidate_context_brief，要优先保留并使用；不要只靠原始聊天记录重新拼事实。",
            "不要编造没有依据的事实、标签、数字、日期或来源 URL。",
            "在提示词审查和生图决策中纳入附件摘要。",
        ]
        if target_agent_id == AIGC_AGENT_ID:
            constraints.append("文字密集型视觉内容的精确文案优先使用确定性的 SVG/UI 排版。")
            if context_brief.strip():
                constraints.append(
                    "已有可复用或已研究的生图简报，应作为主要事实来源。"
                )
            if request.attachments:
                constraints.append(
                    "上传媒体可作为视觉参考；只有图片 data_url 应进入 subject_reference 参数。"
                )

        handoff_messages = self._aigc_handoff_messages(request=request, history=history)
        handoff_attachments = self._aigc_handoff_attachments(request.attachments)
        inherited_stages = list(provided_packet.stage_contexts) if provided_packet is not None else []
        return AgentHandoffPacket(
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            reason=reason,
            forced=forced,
            conversation_id=request.conversation_id,
            current_request=self._compact_handoff_text(
                request.message or "（用户本轮没有提供文字描述。）",
                2200,
            ),
            mode_ids=list(request.mode_ids or []),
            mode_prompts=self._normalize_mode_prompts(request.mode_prompts),
            candidate_context_brief=self._compact_handoff_text(context_brief, 4200),
            messages=handoff_messages,
            attachments=handoff_attachments,
            stage_contexts=[*inherited_stages, *(stage_contexts or [])],
            constraints=constraints,
            metadata={
                "context_block_count": len(context_blocks),
                "context_block_chars": sum(len(block) for block in context_blocks),
                "message_count": len(history),
                "handoff_message_count": len(handoff_messages),
                "attachment_count": len(request.attachments),
                "candidate_context_chars": len(context_brief.strip()),
                "protocol_version": AGENT_INPUT_PROTOCOL_VERSION,
            },
        )

    def _append_agent_input_received_trace(
        self,
        *,
        run_id: str,
        request: ChatRequest,
        agent_id: str,
        history: list[LLMMessage],
    ) -> AgentHandoffPacket:
        source_agent_id = "client"
        if request.agent_input is not None:
            source_agent_id = request.agent_input.source_agent_id
        elif request.handoff is not None:
            source_agent_id = request.handoff.source_agent_id

        packet = self._build_agent_handoff_packet(
            request=request,
            source_agent_id=source_agent_id,
            target_agent_id=agent_id,
            history=history,
        )
        self.trace_store.append_event(
            run_id,
            type="agent.input_context.received",
            status="completed",
            title="Agent input context received",
            payload=self._trace_handoff_packet_payload(packet),
        )
        return packet

    def _render_agent_handoff_packet(self, packet: AgentHandoffPacket | None) -> str:
        if packet is None:
            return "没有结构化 Agent 输入包。"

        lines = [
            f"结构化 Agent 输入（{packet.protocol_version}）",
            f"来源：{packet.source_agent_id} -> {packet.target_agent_id}",
        ]
        if packet.reason:
            lines.append(f"原因：{packet.reason}")
        lines.append(f"是否强制：{packet.forced}")
        lines.extend(["", "当前请求：", packet.current_request or "无"])

        if packet.mode_ids or packet.mode_prompts:
            lines.append("")
            lines.append("模式：")
            for mode_id in packet.mode_ids:
                lines.append(f"- id={mode_id}")
            for prompt in packet.mode_prompts:
                lines.append(f"- 指令={prompt}")

        if packet.candidate_context_brief:
            lines.extend(["", "候选上下文简报：", packet.candidate_context_brief])

        if packet.messages:
            lines.append("")
            lines.append("已选择的会话上下文：")
            for message in packet.messages:
                role_label = "用户" if message.role == "user" else "助手"
                lines.append(f"{message.index}. {role_label} ({message.source}): {message.content}")

        if packet.attachments:
            lines.append("")
            lines.append("附件：")
            for index, attachment in enumerate(packet.attachments, start=1):
                parts = [
                    f"{index}. {attachment.name}",
                    f"类型={attachment.kind}",
                    f"MIME={attachment.mime_type or '未知'}",
                    f"大小={attachment.size}",
                    f"含 data_url={attachment.has_data_url}",
                    f"已截断={attachment.truncated}",
                ]
                lines.append("; ".join(parts))
                if attachment.content_preview:
                    lines.append(f"   内容={attachment.content_preview}")

        if packet.stage_contexts:
            lines.append("")
            lines.append("阶段上下文：")
            for stage in packet.stage_contexts:
                lines.append(f"- {stage.stage_id} [{stage.status}]: {stage.summary or '无摘要'}")
                if stage.content:
                    lines.append(f"  内容={stage.content}")

        if packet.constraints:
            lines.append("")
            lines.append("交接约束：")
            for constraint in packet.constraints:
                lines.append(f"- {constraint}")

        return "\n".join(lines).strip()

    def _trace_handoff_packet_payload(self, packet: AgentHandoffPacket) -> dict[str, Any]:
        rendered = self._render_agent_handoff_packet(packet)
        return {
            "protocol_version": packet.protocol_version,
            "source_agent_id": packet.source_agent_id,
            "target_agent_id": packet.target_agent_id,
            "reason": packet.reason,
            "forced": packet.forced,
            "current_request_preview": packet.current_request[:500],
            "mode_ids": packet.mode_ids,
            "mode_prompt_count": len(packet.mode_prompts),
            "candidate_context_chars": len(packet.candidate_context_brief),
            "message_count": len(packet.messages),
            "attachment_count": len(packet.attachments),
            "stage_context_count": len(packet.stage_contexts),
            "constraints": packet.constraints,
            "metadata": packet.metadata,
            "packet_preview": rendered[:1600],
            "packet": packet.model_dump(),
        }

    def _append_agent_input_stage(
        self,
        packet: AgentHandoffPacket,
        stage: AgentStageContext,
        *,
        candidate_context_brief: str | None = None,
    ) -> AgentHandoffPacket:
        metadata = dict(packet.metadata)
        if candidate_context_brief is not None:
            metadata["candidate_context_chars"] = len(candidate_context_brief.strip())
        return packet.model_copy(
            update={
                "candidate_context_brief": packet.candidate_context_brief
                if candidate_context_brief is None
                else self._compact_handoff_text(candidate_context_brief, 4200),
                "stage_contexts": [*packet.stage_contexts, stage],
                "metadata": metadata,
            }
        )

    def _aigc_context_brief_score(self, content: str) -> int:
        lowered = content.lower()
        if "![ai 生图" in lowered or "**图片结果**" in content or "图片 url 通常会" in lowered:
            return 0

        markers = (
            "image generation brief",
            "visual brief",
            "key facts",
            "图内文字",
            "视觉简报",
            "研究概况",
            "关键发现",
            "一句话结论",
            "详细排序",
            "对比表",
            "五维",
            "舒适度",
            "自驾",
            "首推",
            "推荐人群",
            "道路类型",
            "停车",
            "时长",
            "评分",
            "方案",
            "tips",
        )
        score = sum(1 for marker in markers if marker in lowered or marker in content)
        score += min(6, content.count("|"))
        score += min(4, len(re.findall(r"\d", content)) // 4)
        return score

    def _aigc_existing_context_brief(
        self,
        *,
        request: ChatRequest,
        history: list[LLMMessage],
    ) -> str:
        messages = self._aigc_existing_context_messages(request=request, history=history)
        best_content = ""
        best_score = 0
        for message in messages:
            if message["role"] != "assistant":
                continue
            content = message["content"].strip()
            score = self._aigc_context_brief_score(content)
            if score >= best_score:
                best_score = score
                best_content = content

        if best_score < 4 or not best_content:
            return ""

        compact = self._build_aigc_image_generation_brief(best_content)
        compact = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", compact)
        compact = compact.strip()
        if not compact:
            return ""

        user_text = request.message.strip() or "（用户本轮没有提供文字描述。）"
        return (
            "上下文复用简报：复用下面已经研究过的会话事实。"
            "除非用户明确要求更新事实，否则不要重新检索。\n\n"
            f"当前生图请求：\n{user_text}\n\n"
            f"可复用事实和版式来源：\n{compact[:3500].rstrip()}"
        )

    def _build_aigc_planning_messages(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        context_brief: str,
        handoff_packet: AgentHandoffPacket | None = None,
        short_term_summary: str = "",
    ) -> list[LLMMessage]:
        context_blocks = self._normalize_context_blocks(request.context_blocks)
        context_text = "\n\n---\n\n".join(context_blocks) or "没有额外上下文块。"
        history_text = self._format_aigc_history(history, context_blocks)
        attachment_text = self._format_aigc_attachments(request.attachments)
        handoff_text = self._render_agent_handoff_packet(handoff_packet)
        mode_text = "\n".join(f"- {prompt}" for prompt in self._normalize_mode_prompts(request.mode_prompts))
        mode_text = mode_text or "没有选择规划/研究模式指令。"
        user_text = request.message.strip() or "（用户本轮没有提供文字描述。）"

        system = (
            "你是 AI 生图 Agent 的执行规划器。请在提示词审查和生图前判断下一步执行策略。"
            "只返回 JSON，不要返回 Markdown。\n\n"
            "JSON 结构：\n"
            "{\n"
            '  "information_strategy": "direct|reuse_context|retrieve|clarify",\n'
            '  "brief_format": "none|markdown|structured",\n'
            '  "selected_context_brief": "",\n'
            '  "clarifying_question": "",\n'
            '  "steps": ["task_decomposition", "context_reuse", "image_generation", "final_summary"],\n'
            '  "reason": "",\n'
            '  "brief_format_reason": ""\n'
            "}\n\n"
            "规划规则：\n"
            "- 当已有会话事实足以支持本次生图时，选择 reuse_context。\n"
            "- 只有当前图片需要新鲜、当前、缺失或需要外部验证的事实时，才选择 retrieve。\n"
            "- 纯创意生图、无需历史事实或研究时，选择 direct。\n"
            "- 只有图片目标过于模糊、无法推进时，选择 clarify。\n"
            "- 决定 brief_format 前比较信息交接格式：原始转录、紧凑 Markdown 简报、结构化事实/版式简报。"
            "对比图、分享图、多行事实或任何文字密集型视觉内容优先 structured；叙事氛围/风格简报优先 markdown。\n"
            "- 如果 information_strategy=reuse_context，请把 selected_context_brief 改写成选定格式。不要粘贴原始聊天记录，"
            "保留生图所需事实，并省略无关的旧助手闲聊。\n"
            "- 如果 brief_format=structured，优先使用这些章节名：目标、必须包含、数据行、版式、视觉风格、注意事项。\n"
            "- steps 只能使用这些 id：task_decomposition, context_reuse, retrieval, image_generation, final_summary。"
        )
        user = (
            f"模式指令：\n{mode_text}\n\n"
            f"结构化 Agent 输入包：\n{handoff_text}\n\n"
            f"角色上下文：\n{role_context.rendered[:2000]}\n\n"
            f"短期记忆摘要：\n{short_term_summary or '暂无压缩摘要。'}\n\n"
            f"近期内存会话：\n{history_text}\n\n"
            f"当前用户请求：\n{user_text}\n\n"
            f"候选可复用上下文简报：\n{context_brief or '没有检测到可复用上下文简报。'}\n\n"
            f"上传附件：\n{attachment_text}\n\n"
            f"仅供规划使用的本轮额外上下文：\n{context_text}"
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

    def _default_aigc_planning_decision(self, request: ChatRequest, context_brief: str = "") -> dict[str, Any]:
        selected_context_brief = ""
        if context_brief.strip():
            strategy = "reuse_context"
            steps = [
                AIGC_PLAN_DECOMPOSE_STEP,
                AIGC_PLAN_CONTEXT_STEP,
                AIGC_PLAN_IMAGE_STEP,
                AIGC_PLAN_SUMMARY_STEP,
            ]
            selected_context_brief = build_structured_share_card_brief(context_brief) or context_brief
            brief_format = "structured" if selected_context_brief != context_brief else "markdown"
        elif self._aigc_retrieval_required(request):
            strategy = "retrieve"
            steps = [
                AIGC_PLAN_DECOMPOSE_STEP,
                AIGC_PLAN_RETRIEVAL_STEP,
                AIGC_PLAN_IMAGE_STEP,
                AIGC_PLAN_SUMMARY_STEP,
            ]
            brief_format = "markdown"
        else:
            strategy = "direct"
            steps = [AIGC_PLAN_IMAGE_STEP] if self._aigc_retrieval_required(request) else []
            brief_format = "none"

        return {
            "information_strategy": strategy,
            "brief_format": brief_format,
            "selected_context_brief": selected_context_brief if strategy == "reuse_context" else "",
            "clarifying_question": "",
            "steps": steps,
            "reason": "使用兜底规划决策。",
            "brief_format_reason": "根据可用上下文和模式状态选择兜底简报格式。",
            "model": "",
            "usage": {},
            "fallback": True,
        }

    def _coerce_aigc_planning_decision(
        self,
        raw: dict[str, Any] | None,
        *,
        fallback: dict[str, Any],
        context_brief: str,
    ) -> dict[str, Any]:
        raw = dict(raw or {})
        parsed_ok = bool(raw.pop("_parsed_ok", bool(raw)))
        strategy = str(raw.get("information_strategy") or fallback["information_strategy"]).strip().lower()
        if strategy not in AIGC_INFORMATION_STRATEGIES:
            strategy = fallback["information_strategy"]
        if strategy == "reuse_context" and not context_brief.strip() and not str(raw.get("selected_context_brief") or "").strip():
            strategy = "retrieve" if fallback["information_strategy"] == "retrieve" else "direct"

        brief_format = str(raw.get("brief_format") or fallback["brief_format"]).strip().lower()
        if brief_format not in AIGC_BRIEF_FORMATS:
            brief_format = fallback["brief_format"]
        if strategy != "reuse_context" and brief_format == "structured":
            brief_format = "markdown" if strategy == "retrieve" else "none"

        raw_steps = raw.get("steps")
        if isinstance(raw_steps, list):
            steps = [str(step).strip() for step in raw_steps if str(step).strip()]
        else:
            steps = list(fallback["steps"])
        allowed_steps = {
            AIGC_PLAN_DECOMPOSE_STEP,
            AIGC_PLAN_CONTEXT_STEP,
            AIGC_PLAN_RETRIEVAL_STEP,
            AIGC_PLAN_IMAGE_STEP,
            AIGC_PLAN_SUMMARY_STEP,
        }
        steps = [step for step in steps if step in allowed_steps]
        if strategy == "reuse_context":
            required = [AIGC_PLAN_DECOMPOSE_STEP, AIGC_PLAN_CONTEXT_STEP, AIGC_PLAN_IMAGE_STEP, AIGC_PLAN_SUMMARY_STEP]
        elif strategy == "retrieve":
            required = [AIGC_PLAN_DECOMPOSE_STEP, AIGC_PLAN_RETRIEVAL_STEP, AIGC_PLAN_IMAGE_STEP, AIGC_PLAN_SUMMARY_STEP]
        elif strategy == "direct":
            required = [AIGC_PLAN_IMAGE_STEP] if steps else []
        else:
            required = []
        for step in required:
            if step not in steps:
                steps.append(step)
        if strategy == "clarify":
            steps = []

        selected_context_brief = str(raw.get("selected_context_brief") or "").strip()
        if strategy == "reuse_context" and not selected_context_brief:
            selected_context_brief = str(fallback.get("selected_context_brief") or context_brief).strip()

        return {
            "information_strategy": strategy,
            "brief_format": brief_format,
            "selected_context_brief": selected_context_brief[:4500].rstrip(),
            "clarifying_question": str(raw.get("clarifying_question") or "").strip(),
            "steps": steps,
            "reason": str(raw.get("reason") or fallback.get("reason") or "").strip()[:500],
            "brief_format_reason": str(raw.get("brief_format_reason") or fallback.get("brief_format_reason") or "").strip()[:500],
            "model": str(raw.get("model") or fallback.get("model") or ""),
            "usage": dict(raw.get("usage") if isinstance(raw.get("usage"), dict) else fallback.get("usage") or {}),
            "fallback": bool(fallback.get("fallback") and not parsed_ok),
        }

    def _parse_aigc_planning_response(
        self,
        response_text: str,
        *,
        fallback: dict[str, Any],
        context_brief: str,
        model: str = "",
        usage: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        parsed = self._extract_json_object(response_text)
        parsed_ok = parsed is not None
        parsed = parsed or {}
        parsed["_parsed_ok"] = parsed_ok
        parsed["model"] = model
        parsed["usage"] = usage or {}
        return self._coerce_aigc_planning_decision(parsed, fallback=fallback, context_brief=context_brief)

    async def _prepare_aigc_execution_decision(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        context_brief: str,
        run_id: str,
        handoff_packet: AgentHandoffPacket | None = None,
        short_term_summary: str = "",
    ) -> dict[str, Any]:
        fallback = self._default_aigc_planning_decision(request, context_brief)
        should_plan = self._aigc_retrieval_required(request) or bool(context_brief.strip())
        if not should_plan:
            return fallback

        messages = self._build_aigc_planning_messages(
            request=request,
            role_context=role_context,
            history=history,
            context_brief=context_brief,
            handoff_packet=handoff_packet,
            short_term_summary=short_term_summary,
        )
        planning_started = perf_counter()
        self.trace_store.append_event(
            run_id,
            type="aigc.planning.started",
            status="running",
            title="AI 生图计划判断开始",
            payload={
                "mode_ids": request.mode_ids,
                "has_candidate_context_brief": bool(context_brief.strip()),
                "candidate_context_chars": len(context_brief),
            },
        )
        try:
            provider = self._get_provider(request.model_preference)
            response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=messages,
                tools=None,
                temperature=0.1,
                retry_context={"scope": "aigc_planning"},
            )
            decision = self._parse_aigc_planning_response(
                response.content,
                fallback=fallback,
                context_brief=context_brief,
                model=response.model,
                usage=response.usage,
            )
            self.trace_store.append_event(
                run_id,
                type="aigc.planning.completed",
                status="completed",
                title="AI 生图计划判断完成",
                payload={
                    "model": decision["model"],
                    "information_strategy": decision["information_strategy"],
                    "brief_format": decision["brief_format"],
                    "brief_format_reason": decision["brief_format_reason"],
                    "reason": decision["reason"],
                    "steps": decision["steps"],
                    "selected_context_brief_preview": decision["selected_context_brief"][:500],
                    "usage": decision["usage"],
                    "fallback": decision["fallback"],
                },
                duration_ms=int((perf_counter() - planning_started) * 1000),
            )
            return decision
        except Exception as e:
            logger.exception("AIGC execution planning failed; using fallback decision")
            self.trace_store.append_event(
                run_id,
                type="aigc.planning.failed",
                status="error",
                title="AI 生图计划判断失败，使用兜底计划",
                payload={
                    "error_message": str(e),
                    "fallback_strategy": fallback["information_strategy"],
                    "fallback_steps": fallback["steps"],
                },
                duration_ms=int((perf_counter() - planning_started) * 1000),
            )
            return fallback

    def _build_aigc_execution_plan(
        self,
        request: ChatRequest,
        *,
        planning_decision: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        step_labels = {
            AIGC_PLAN_DECOMPOSE_STEP: (
                "任务拆解",
                "明确用户目标、信息来源和最终交付形式。",
            ),
            AIGC_PLAN_CONTEXT_STEP: (
                "复用会话上下文",
                "从已有会话答案中提取事实、排序、评分和版式所需信息。",
            ),
            AIGC_PLAN_RETRIEVAL_STEP: (
                "检索并整理资料",
                "收集事实、数据、风险和来源，形成生图 brief。",
            ),
            AIGC_PLAN_IMAGE_STEP: (
                "基于资料生成图片",
                "用信息 brief 做提示词修饰，再调用 AI 生图。",
            ),
            AIGC_PLAN_SUMMARY_STEP: (
                "合并图片结果",
                "把图片结果、资料摘要和生成说明合并成最终答复。",
            ),
        }

        if planning_decision is not None:
            return [
                {"id": step, "title": step_labels[step][0], "description": step_labels[step][1]}
                for step in planning_decision.get("steps", [])
                if step in step_labels
            ]

        if not self._aigc_retrieval_required(request):
            return []
        return [
            {"id": step, "title": step_labels[step][0], "description": step_labels[step][1]}
            for step in [
                AIGC_PLAN_DECOMPOSE_STEP,
                AIGC_PLAN_RETRIEVAL_STEP,
                AIGC_PLAN_IMAGE_STEP,
                AIGC_PLAN_SUMMARY_STEP,
            ]
        ]

    def _aigc_plan_infos(
        self,
        *,
        execution_plan: list[dict[str, str]],
        retrieval_status: str = "pending",
        image_status: str = "pending",
        summary_status: str = "pending",
        research_brief: str = "",
        image_count: int = 0,
    ) -> list[SkillCallInfo]:
        if not execution_plan:
            return []

        statuses = {
            AIGC_PLAN_DECOMPOSE_STEP: "completed",
            AIGC_PLAN_CONTEXT_STEP: retrieval_status,
            AIGC_PLAN_RETRIEVAL_STEP: retrieval_status,
            AIGC_PLAN_IMAGE_STEP: image_status,
            AIGC_PLAN_SUMMARY_STEP: summary_status,
        }
        summaries = {
            AIGC_PLAN_DECOMPOSE_STEP: "已拆解为：收集信息、基于信息生图、合并结果。",
            AIGC_PLAN_CONTEXT_STEP: (research_brief or "等待复用会话上下文。")[:200],
            AIGC_PLAN_RETRIEVAL_STEP: (research_brief or "等待检索资料。")[:200],
            AIGC_PLAN_IMAGE_STEP: f"已生成 {image_count} 张图片。" if image_count else "等待生图结果。",
            AIGC_PLAN_SUMMARY_STEP: "已合并检索摘要、图片结果和来源说明。"
            if summary_status == "completed"
            else "等待最终汇总。",
        }
        return [
            SkillCallInfo(
                skill=step["id"],
                action=step["description"],
                status=statuses.get(step["id"], "pending"),
                result_summary=summaries.get(step["id"], step["title"]),
            )
            for step in execution_plan
        ]

    def _build_aigc_research_messages(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        handoff_packet: AgentHandoffPacket | None = None,
        short_term_summary: str = "",
    ) -> list[LLMMessage]:
        context_blocks = self._normalize_context_blocks(request.context_blocks)
        context_text = "\n\n---\n\n".join(context_blocks) or "没有额外上下文块。"
        attachment_text = self._format_aigc_attachments(request.attachments)
        history_text = self._format_aigc_history(history, context_blocks)
        handoff_text = self._render_agent_handoff_packet(handoff_packet)
        mode_text = "\n".join(f"- {prompt}" for prompt in self._normalize_mode_prompts(request.mode_prompts))
        mode_text = mode_text or "没有选择研究或规划模式指令。"
        user_text = request.message.strip() or "（用户本轮没有提供文字描述。）"

        current_time = datetime.now(ZoneInfo("Asia/Shanghai"))
        system = (
            "你正在为 AI 生图步骤准备有证据支撑的简报。不要生成图片，也不要写最终面向用户的回答。"
            "先把任务拆成信息需求和视觉交付物；当事实可能涉及当前信息、金融/投资或不确定内容时，使用可用工具。"
            "有必要时进行多轮搜索：先宽泛检索，再查询具体事实、反向证据、来源可信度以及视觉/媒体参考。"
            "调用搜索工具时，除非范围很窄，否则请求 12-20 条结果。持续补齐上下文，直到简报足以支持有用的最终图片。"
            "返回详细但紧凑的 Markdown 简报，供后续提示词导演使用。避免流程闲聊，例如“我不能在这里生成图片”"
            "或“下一步”；下一步由编排器处理。\n\n"
            "必须包含的章节：\n"
            "- 任务拆解：用一句短句说明最终图片目标和所需信息。\n"
            "- 关键事实：列出可能进入图片的事实、数字、日期、来源强度、分歧和注意事项。\n"
            "- 视觉/媒体参考：如搜索结果元数据中有可用图片或视频 URL，列出它们。\n"
            "- 生图简报：描述视觉信息、版式分区、标签、语气和图片约束。\n"
            "- 来源说明/缺口：尽量引用工具结果中的 URL，并说明不确定性。\n\n"
            f"当前日期/时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')} Asia/Shanghai。"
            "投资主题只提供信息性上下文，不提供个性化投资建议。"
        )
        user = (
            f"模式指令：\n{mode_text}\n\n"
            f"结构化 Agent 输入包：\n{handoff_text}\n\n"
            f"角色上下文：\n{role_context.rendered[:4000]}\n\n"
            f"短期记忆摘要：\n{short_term_summary or '暂无压缩摘要。'}\n\n"
            f"近期会话：\n{history_text}\n\n"
            f"当前用户请求：\n{user_text}\n\n"
            f"上传附件：\n{attachment_text}\n\n"
            f"本轮额外上下文：\n{context_text}"
        )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

    async def _prepare_aigc_research_brief(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        run_id: str,
        handoff_packet: AgentHandoffPacket | None = None,
        short_term_summary: str = "",
    ) -> dict[str, Any]:
        tools = self._tool_definitions_for_agent(AIGC_AGENT_ID, request.disabled_tools)
        allowed_tool_names = {tool.name for tool in tools}
        messages = self._build_aigc_research_messages(
            request=request,
            role_context=role_context,
            history=history,
            handoff_packet=handoff_packet,
            short_term_summary=short_term_summary,
        )
        citations: list[Citation] = []
        citation_urls: set[str] = set()
        plan: list[SkillCallInfo] = []
        skills_used: list[str] = []
        total_usage: dict[str, int] = {}
        response: LLMResponse | None = None

        self.trace_store.append_event(
            run_id,
            type="aigc.research.started",
            status="running",
            title="Pre-generation research started",
            payload={
                "tools_count": len(tools),
                "tool_names": [tool.name for tool in tools],
                "mode_ids": request.mode_ids,
                "max_rounds": AIGC_RESEARCH_TOOL_ROUNDS,
                "search_limit": AIGC_RESEARCH_SEARCH_LIMIT,
            },
        )

        for round_index in range(AIGC_RESEARCH_TOOL_ROUNDS):
            model_started = perf_counter()
            self.trace_store.append_event(
                run_id,
                type="aigc.research.model.started",
                status="running",
                title=f"Research model call {round_index + 1}",
                payload={
                    "round": round_index + 1,
                    "message_count": len(messages),
                    "tools_count": len(tools),
                    "model_preference": request.model_preference,
                },
            )
            provider = self._get_provider(request.model_preference)
            response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=messages,
                tools=tools,
                temperature=0.2,
                retry_context={
                    "scope": "aigc_research",
                    "round": round_index + 1,
                },
            )
            for key, value in response.usage.items():
                total_usage[key] = total_usage.get(key, 0) + value
            self.trace_store.append_event(
                run_id,
                type="aigc.research.model.completed",
                status="completed",
                title=f"Research model call {round_index + 1} completed",
                payload={
                    "round": round_index + 1,
                    "model": response.model,
                    "usage": response.usage,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name}
                        for tc in response.tool_calls
                    ],
                    "content_preview": response.content[:300],
                },
                duration_ms=int((perf_counter() - model_started) * 1000),
            )

            if not response.tool_calls:
                break

            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=[
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in response.tool_calls
                    ],
                )
            )

            for tc in response.tool_calls:
                tool_arguments = self._aigc_research_tool_arguments(tc.name, tc.arguments)
                tool_started = perf_counter()
                self.trace_store.append_event(
                    run_id,
                    type="tool.started",
                    status="running",
                    title=f"Tool {tc.name}",
                    step_id=tc.id,
                    payload={
                        "name": tc.name,
                        "arguments": self._tool_arguments_for_trace(tc.name, tool_arguments),
                    },
                )
                skill = self.skill_registry.get(tc.name)
                if tc.name not in allowed_tool_names:
                    result_text = json.dumps({"error": f"Tool disabled or unavailable: {tc.name}"})
                    status = "error"
                elif tc.name in AGENT_TOOL_IDS:
                    try:
                        result = await self._execute_agent_tool_with_governance(
                            request=request,
                            role_context=role_context,
                            run_id=run.run_id,
                            tool_name=tc.name,
                            tool_call_id=tc.id,
                            arguments=tool_arguments,
                            tool_started=tool_started,
                            workflow_context=(
                                {
                                    "workflow": workflow_name,
                                    "node": workflow_node,
                                    "node_started": workflow_node_started,
                                    "workflow_started": workflow_started,
                                    "round": round_index + 1,
                                    "result": "agent_tool_result",
                                    "workflow_source": workflow_source,
                                    "legacy_workflow": legacy_workflow,
                                }
                                if agent_loop_enabled
                                else None
                            ),
                        )
                        result_text = json.dumps(
                            {
                                "success": result.success,
                                "data": result.data,
                                "display_text": result.display_text,
                                "error": result.error,
                            },
                            ensure_ascii=False,
                        )
                        status = "completed" if result.success else "error"
                        if result.success:
                            self._merge_agent_tool_payload(
                                payload=result.data,
                                skills_used=skills_used,
                                citations=citations,
                                citation_urls=citation_urls,
                                artifacts=artifacts,
                            )
                    except Exception as e:
                        logger.exception(f"Agent tool {tc.name} execution failed")
                        result_text = json.dumps({"error": str(e)}, ensure_ascii=False)
                        status = "error"
                elif skill is None:
                    result_text = json.dumps({"error": f"Unknown skill: {tc.name}"})
                    status = "error"
                else:
                    try:
                        result = await self._execute_skill_with_governance(
                            request=request,
                            run_id=run_id,
                            skill_name=tc.name,
                            arguments=tool_arguments,
                            step_id=tc.id,
                        )
                        result_text = json.dumps(
                            {
                                "success": result.success,
                                "data": result.data,
                                "display_text": result.display_text,
                                "error": result.error,
                            },
                            ensure_ascii=False,
                        )
                        status = "completed" if result.success else "error"
                        if result.success:
                            skills_used.append(tc.name)
                            if tc.name == "search":
                                self._append_search_trace_nodes(
                                    run_id,
                                    tool_call_id=tc.id,
                                    result_data=result.data,
                                )
                                new_citations = self._collect_search_citations(
                                    result_data=result.data,
                                    citations=citations,
                                    citation_urls=citation_urls,
                                )
                                if new_citations:
                                    self.trace_store.append_event(
                                        run_id,
                                        type="citations.collected",
                                        status="completed",
                                        title="Search citations collected",
                                        step_id=tc.id,
                                        payload={
                                            "count": len(new_citations),
                                            "total": len(citations),
                                            "urls": [citation.url for citation in new_citations],
                                        },
                                    )
                    except Exception as e:
                        logger.exception(f"Skill {tc.name} execution failed")
                        result_text = json.dumps({"error": str(e)})
                        status = "error"

                self.trace_store.append_event(
                    run_id,
                    type="tool.completed" if status == "completed" else "tool.failed",
                    status=status,
                    title=f"Tool {tc.name} {status}",
                    step_id=tc.id,
                    payload={
                        "name": tc.name,
                        "arguments": self._tool_arguments_for_trace(tc.name, tool_arguments),
                        "result_preview": result_text[:500],
                    },
                    duration_ms=int((perf_counter() - tool_started) * 1000),
                )
                plan.append(
                    SkillCallInfo(
                        skill=tc.name,
                        action=str(tool_arguments),
                        status=status,
                        result_summary=result_text[:200],
                    )
                )
                messages.append(LLMMessage(role="tool", content=result_text, tool_call_id=tc.id))

        brief = response.content.strip() if response else ""
        if response and response.tool_calls:
            brief = brief or "已完成资料收集，但模型未输出最终研究摘要。"
        self.trace_store.append_event(
            run_id,
            type="aigc.research.completed",
            status="completed",
            title="Pre-generation research completed",
            payload={
                "brief_preview": brief[:500],
                "skills_used": list(dict.fromkeys(skills_used)),
                "citation_count": len(citations),
                "usage": total_usage,
            },
        )
        return {
            "brief": brief,
            "model": response.model if response else "",
            "usage": total_usage,
            "skills_used": list(dict.fromkeys(skills_used)),
            "citations": citations,
            "plan": plan,
        }

    def _aigc_research_tool_arguments(self, tool_name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(arguments or {})
        if tool_name != "search":
            return normalized

        try:
            requested_limit = int(normalized.get("limit") or 0)
        except (TypeError, ValueError):
            requested_limit = 0
        normalized["limit"] = min(
            max(requested_limit, AIGC_RESEARCH_SEARCH_LIMIT),
            AIGC_RESEARCH_SEARCH_MAX_LIMIT,
        )
        return normalized

    def _format_aigc_history(self, history: list[LLMMessage], context_blocks: list[str] | None = None) -> str:
        lines: list[str] = []
        for message in history[-12:]:
            if message.role not in {"user", "assistant"}:
                continue
            content = message.content
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            content = " ".join(content.split())
            if content:
                role_label = "用户" if message.role == "user" else "助手"
                lines.append(f"{role_label}: {content[:1800]}")
        if lines:
            return "\n".join(lines)
        if self._has_persisted_conversation_context(context_blocks):
            return "内存中没有会话消息；持久化会话历史已包含在下方本轮额外上下文中。"
        return "没有历史会话。"

    def _has_persisted_conversation_context(self, context_blocks: list[str] | None) -> bool:
        return any(self._is_persisted_conversation_context(block) for block in context_blocks or [])

    def _format_aigc_attachments(self, attachments: list[ChatAttachment]) -> str:
        if not attachments:
            return "没有附件。"

        lines: list[str] = []
        for index, attachment in enumerate(attachments[:8], start=1):
            kind = attachment.kind or "file"
            mime_type = attachment.type or "未知"
            size = attachment.size or 0
            media_hint = ""
            if attachment.data_url:
                if kind == "image":
                    media_hint = "已有参考图数据，可用于生图。"
                elif kind in {"audio", "video"}:
                    media_hint = f"已上传 {kind} 数据，可作为高层创意上下文。"
                else:
                    media_hint = "已上传附件数据。"
            content = " ".join((attachment.content or "").split())
            if content:
                content = content[:1500]
            lines.append(
                "\n".join(
                    [
                        f"{index}. 名称={attachment.name or '未命名'}",
                        f"   类型={kind}, MIME={mime_type}, 大小={size} bytes",
                        f"   备注={media_hint or '没有内嵌媒体数据。'}",
                        f"   文本上下文={content or '无'}",
                        f"   是否截断={bool(attachment.truncated)}",
                    ]
                )
            )
        return "\n".join(lines)

    def _aigc_attachment_prompt_seed(self, attachments: list[ChatAttachment]) -> str:
        parts: list[str] = []
        for attachment in attachments[:6]:
            kind = attachment.kind or "file"
            name = attachment.name or "上传附件"
            if kind == "image":
                parts.append(f"把上传图片「{name}」作为视觉参考")
            elif kind == "audio":
                parts.append(f"把上传音频「{name}」作为氛围和故事参考")
            elif kind == "video":
                parts.append(f"把上传视频「{name}」作为动作、场景和氛围参考")
            elif attachment.content:
                parts.append(f"把文本附件「{name}」作为上下文")
        if not parts:
            return ""
        return "生成一个完整、精致的图片概念，并" + "；".join(parts) + "。"

    def _aigc_subject_references(self, attachments: list[ChatAttachment]) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        for attachment in attachments:
            if attachment.kind != "image":
                continue
            data_url = (attachment.data_url or "").strip()
            if not data_url.startswith("data:image/"):
                continue
            references.append(
                {
                    "type": "character",
                    "image_file": data_url,
                }
            )
            if len(references) >= 4:
                break
        return references

    def _aigc_image_error_message(
        self,
        error: Exception,
        *,
        request: ChatRequest,
        review: dict[str, Any],
    ) -> str:
        raw_error = str(error).strip() or error.__class__.__name__
        normalized = raw_error.lower()
        final_prompt = str(review.get("final_prompt") or "")
        prompt_preview = " ".join(final_prompt.split())[:240]
        context_text = " ".join(
            [
                request.message or "",
                final_prompt,
            ]
        ).lower()

        if "new_sensitive" in normalized or "sensitive" in normalized:
            financial_keywords = [
                "ipo",
                "stock",
                "share",
                "shares",
                "valuation",
                "hk00100",
                "hk 00100",
                "港股",
                "股票",
                "股价",
                "上市",
                "估值",
                "投资",
                "融资",
                "科创板",
                "人民币股份",
                "资本动态",
                "不构成投资建议",
            ]
            if any(keyword in context_text for keyword in financial_keywords):
                return "\n".join(
                    [
                        "这次图片没有生成成功。",
                        "",
                        "**原因**",
                        "MiniMax 的内容安全审核拒绝了当前生图提示词。底层错误码是 `input new_sensitive`，通常表示提示词里包含平台认为敏感的元素。",
                        "",
                        "**这次可能触发的点**",
                        "这次提示词包含上市、股票代码、IPO、估值、投资提示等资本市场信息。聊天总结可以正常写，但图像生成模型对金融/投资类可视化内容会更严格。",
                        "",
                        "**建议改法**",
                        "可以改成偏产品和技术的一图速览，弱化或移除股票代码、估值、IPO、投资提示等表述，例如突出 `模型发布、产品矩阵、用户规模、技术能力`。",
                    ]
                )

            political_keywords = [
                "trump",
                "donald",
                "political",
                "president",
                "election",
                "campaign",
                "竞选",
                "总统",
                "政治",
                "公众人物",
            ]
            if any(keyword in context_text for keyword in political_keywords):
                return "\n".join(
                    [
                        "这次图片没有生成成功。",
                        "",
                        "**原因**",
                        "MiniMax 的内容安全审核拒绝了当前生图提示词。底层错误码是 `input new_sensitive`，通常表示提示词里包含平台认为敏感的元素。",
                        "",
                        "**这次可能触发的点**",
                        "请求里包含真实政治公众人物或相关政治符号，生图模型会比普通聊天更严格。",
                        "",
                        "**建议改法**",
                        "把人物改成更抽象的卡通特征后再生成，例如：`金发、深蓝西装、红色领带的 Q 版商务人物头像`；避免直接出现真实政治人物姓名、政治口号、竞选元素或国别政治标识。",
                    ]
                )

            return "\n".join(
                [
                    "这次图片没有生成成功。",
                    "",
                    "**原因**",
                    "MiniMax 的内容安全审核拒绝了当前生图提示词。底层错误码是 `input new_sensitive`，通常表示提示词里包含平台认为敏感的元素。",
                    "",
                    "**这次可能触发的点**",
                    "当前提示词里可能包含平台对图像生成更敏感的实体、数据、标识或场景。",
                    "",
                    "**建议改法**",
                    "可以保留核心主题，但简化为更中性的视觉描述，去掉可能敏感的姓名、标识、数字、口号或判断性表达后再试。",
                ]
            )

        if "subject_reference" in normalized:
            return "\n".join(
                [
                    "这次图片没有生成成功。",
                    "",
                    "**原因**",
                    "MiniMax 拒绝了参考图参数。`subject_reference` 只适合人物/角色参考，并且必须按 MiniMax 的 `character` 格式传入。",
                    "",
                    "**建议改法**",
                    "如果没有上传人物参考图，就走纯文本生图；如果上传了人像参考图，系统会按人物参考格式发送。",
                    "",
                    f"底层错误：`{raw_error}`",
                ]
            )

        if "disconnected" in normalized or "timeout" in normalized or "timed out" in normalized:
            return "\n".join(
                [
                    "这次图片没有生成成功。",
                    "",
                    "**原因**",
                    "MiniMax 生图服务或网络连接临时中断。系统已经自动重试，仍没有拿到稳定响应。",
                    "",
                    "**建议改法**",
                    "稍后重新生成，或把提示词缩短一点再试。",
                    "",
                    f"底层错误：`{raw_error}`",
                ]
            )

        if "api key not configured" in normalized:
            return "\n".join(
                [
                    "这次图片没有生成成功。",
                    "",
                    "**原因**",
                    "MiniMax API Key 还没有配置或没有同步到 Agent 服务。",
                    "",
                    "**建议改法**",
                    "到管理页配置 MiniMax API Key 后重新生成。",
                ]
            )

        lines = [
            "这次图片没有生成成功。",
            "",
            "**原因**",
            f"MiniMax 返回了错误：`{raw_error}`。",
        ]
        if prompt_preview:
            lines.extend(
                [
                    "",
                    "**可检查的提示词片段**",
                    prompt_preview,
                ]
            )
        lines.extend(
            [
                "",
                "**建议改法**",
                "可以简化提示词、去掉可能敏感或冲突的元素后再试。",
            ]
        )
        return "\n".join(lines)

    def _build_aigc_review_messages(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        history: list[LLMMessage],
        professional: bool,
        research_brief: str = "",
        text_heavy_visual: bool | None = None,
        handoff_packet: AgentHandoffPacket | None = None,
        short_term_summary: str = "",
    ) -> list[LLMMessage]:
        mode_name = "专业提示词修饰" if professional else "轻量提示词审查"
        has_research_brief = bool(research_brief.strip())
        if text_heavy_visual is None:
            text_heavy_visual = is_text_heavy_visual_intent(
                message=request.message,
                research_brief=research_brief,
                context_blocks=request.context_blocks,
                mode_prompts=request.mode_prompts,
            )
        context_blocks = [] if has_research_brief else self._normalize_context_blocks(request.context_blocks)
        context_text = "\n\n---\n\n".join(context_blocks) or "没有额外上下文块。"
        attachment_text = self._format_aigc_attachments(request.attachments)
        history_text = self._format_aigc_history(history, context_blocks)
        handoff_text = self._render_agent_handoff_packet(handoff_packet)
        user_text = request.message.strip() or "（用户本轮没有提供文字描述。）"
        research_text = (
            self._build_aigc_image_generation_brief(research_brief)
            if has_research_brief
            else "没有生图简报。"
        )

        system = (
            "你是 AI 生图 Agent 的提示词导演。你的任务是把用户当前请求、整理过的信息简报和上传媒体描述"
            "转成高质量生图提示词。只返回 JSON，不要返回 Markdown。\n\n"
            "JSON 结构：\n"
            "{\n"
            '  "should_generate": true,\n'
            '  "clarifying_question": "",\n'
            '  "final_prompt": "",\n'
            '  "negative_prompt": "",\n'
            '  "aspect_ratio": "1:1",\n'
            '  "style_notes": "",\n'
            '  "review_notes": [""]\n'
            "}\n\n"
            "规则：\n"
            "- 如果请求过于模糊，且附件也无法补足信息，设置 should_generate=false，并只问一个简洁的澄清问题。\n"
            "- 如果信息足够，设置 should_generate=true，并默认用中文写 final_prompt，长度不超过 1500 字符；"
            "除非用户明确要求英文，或品牌名、专有名词、风格术语必须保留原文。\n"
            "- 保留用户意图。除非用户提供，不要主动加入受版权保护的角色名或在世艺术家姓名。\n"
            "- 如果提供了生图简报，用它作为具体标签、日期、指标、注意事项和版式分区的事实来源，不要编造无依据数字。\n"
            "- 在已规划的研究流程中，不要把原始会话历史当作图片事实来源；只使用整理过的生图简报和当前用户请求。\n"
            "- 从以下选项中推断一个 aspect_ratio："
            + ", ".join(sorted(IMAGE_ASPECT_RATIOS))
            + "。默认 1:1。\n"
            "- review_notes 要面向用户可见、实用、简短。"
        )
        if professional:
            system += (
                "\n- 已启用专业模式：生图前补全主体、构图、镜头、光线、材质、色彩、氛围、风格约束和负向约束。"
            )
        else:
            system += (
                "\n- 已启用轻量审查：在不覆盖用户原意的前提下澄清并润色提示词。"
            )
        if text_heavy_visual:
            system += (
                "\n\n本请求已启用文字密集型视觉策略。当前图片模型不擅长精确中文、密集表格和小字号标签。\n"
                "- 不要要求图片模型渲染长中文文案、精确表格、星级评分行、小免责声明或精确时长/道路标签。\n"
                "- 使用干净的分享卡构图，用图标、编号卡片、徽章、色条、空文本带，以及最多五个大号短标签表达结构。\n"
                "- 精确中文文案和事实行不要进入生成像素；在 review_notes 中说明精确文案应另行用 UI/SVG 排版。"
            )

        if has_research_brief:
            user = (
                f"模式：{mode_name}\n\n"
                f"结构化 Agent 输入包：\n{handoff_text}\n\n"
                f"当前用户请求：\n{user_text}\n\n"
                f"生图简报：\n{research_text}\n\n"
                f"上传附件：\n{attachment_text}"
            )
        else:
            user = (
                f"模式：{mode_name}\n\n"
                f"结构化 Agent 输入包：\n{handoff_text}\n\n"
                f"角色上下文：\n{role_context.rendered[:2500]}\n\n"
                f"短期记忆摘要：\n{short_term_summary or '暂无压缩摘要。'}\n\n"
                f"近期会话：\n{history_text}\n\n"
                f"当前用户请求：\n{user_text}\n\n"
                f"生图简报：\n{research_text}\n\n"
                f"上传附件：\n{attachment_text}\n\n"
                f"本轮额外上下文：\n{context_text}"
            )
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

    def _build_aigc_image_generation_brief(self, research_brief: str) -> str:
        text = research_brief.strip()
        if not text:
            return "没有生图简报。"

        keep_heading_markers = (
            "key facts",
            "关键事实",
            "image generation brief",
            "生图简报",
            "visual brief",
            "视觉简报",
            "visual / media references",
            "media references",
            "visual references",
            "reference images",
            "媒体",
            "素材",
            "参考图",
            "图内文字",
            "基本信息",
            "身份",
            "资本",
            "负面",
            "结论",
            "主题",
            "风格",
            "版式",
            "layout",
            "labels",
            "tone",
            "constraints",
        )
        skip_heading_markers = (
            "research plan",
            "task breakdown",
            "source notes",
            "gaps",
            "研究计划",
            "任务拆解",
            "来源",
            "下一步",
            "依赖",
        )
        skip_line_markers = (
            "本轮我是研究简报",
            "不直接出图",
            "后续 ai 生图",
            "后续生图",
            "下一步行动",
            "输出图片简报给",
            "用户已",
        )

        lines: list[str] = []
        include_section = True
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                if lines and lines[-1] != "":
                    lines.append("")
                continue

            heading_text = line.lstrip("#").strip().replace("**", "").strip()
            lowered_heading = heading_text.lower()
            is_heading = line.startswith("#") or line.endswith("：") or line.endswith(":")
            if is_heading and any(marker in lowered_heading for marker in skip_heading_markers):
                include_section = False
                continue
            if is_heading and any(marker in lowered_heading for marker in keep_heading_markers):
                include_section = True

            lowered_line = line.lower()
            if not include_section:
                continue
            if any(marker in lowered_line for marker in skip_line_markers):
                continue
            if len(line) > 500:
                line = line[:497].rstrip() + "..."
            lines.append(line)

        compact = "\n".join(lines).strip()
        if not compact:
            compact = text
        return compact[:3500].rstrip()

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        value = (text or "").strip()
        if not value:
            return None
        for candidate in [
            value,
            re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE | re.DOTALL).strip(),
        ]:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        match = re.search(r"\{[\s\S]*\}", value)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _coerce_aigc_review(
        self,
        raw: dict[str, Any] | None,
        *,
        fallback_prompt: str,
    ) -> dict[str, Any]:
        raw = raw or {}
        final_prompt = str(raw.get("final_prompt") or raw.get("prompt") or "").strip()
        clarifying_question = str(raw.get("clarifying_question") or "").strip()
        if not final_prompt and not clarifying_question:
            final_prompt = fallback_prompt

        if len(final_prompt) > 1500:
            final_prompt = final_prompt[:1500].rstrip()

        aspect_ratio = str(raw.get("aspect_ratio") or "1:1").strip()
        if aspect_ratio not in IMAGE_ASPECT_RATIOS:
            aspect_ratio = "1:1"

        notes_value = raw.get("review_notes")
        if isinstance(notes_value, list):
            review_notes = [str(item).strip() for item in notes_value if str(item).strip()]
        elif notes_value:
            review_notes = [str(notes_value).strip()]
        else:
            review_notes = []
        review_notes = review_notes[:4]

        should_value = raw.get("should_generate")
        if isinstance(should_value, bool):
            should_generate = should_value
        elif isinstance(should_value, str):
            should_generate = should_value.strip().lower() not in {"false", "no", "0"}
        else:
            should_generate = bool(final_prompt)
        if clarifying_question and not final_prompt:
            should_generate = False
        if should_generate and not final_prompt:
            should_generate = False
            clarifying_question = clarifying_question or "请再补充一下你想生成的画面。"

        return {
            "should_generate": should_generate,
            "clarifying_question": clarifying_question,
            "final_prompt": final_prompt,
            "negative_prompt": str(raw.get("negative_prompt") or "").strip()[:700],
            "aspect_ratio": aspect_ratio,
            "style_notes": str(raw.get("style_notes") or "").strip()[:700],
            "review_notes": review_notes,
        }

    def _fallback_aigc_review(self, request: ChatRequest) -> dict[str, Any]:
        fallback_prompt = request.message.strip() or self._aigc_attachment_prompt_seed(request.attachments)
        if not fallback_prompt:
            return {
                "should_generate": False,
                "clarifying_question": "你想生成什么画面？可以告诉我主体、风格、比例或参考素材。",
                "final_prompt": "",
                "negative_prompt": "",
                "aspect_ratio": "1:1",
                "style_notes": "",
                "review_notes": [],
            }
        return self._coerce_aigc_review(
            {"should_generate": True, "final_prompt": fallback_prompt, "aspect_ratio": "1:1"},
            fallback_prompt=fallback_prompt,
        )

    def _parse_aigc_review_response(
        self,
        response_text: str,
        *,
        fallback_prompt: str,
        text_heavy_visual: bool = False,
    ) -> dict[str, Any]:
        parsed = self._extract_json_object(response_text)
        if parsed is None:
            parsed = {"should_generate": True, "final_prompt": response_text.strip() or fallback_prompt}
        review = self._coerce_aigc_review(parsed, fallback_prompt=fallback_prompt)
        if text_heavy_visual:
            review = apply_text_rendering_guard(review)
        return review

    def _render_aigc_response(
        self,
        *,
        review: dict[str, Any],
        image_response: ImageGenerationResponse,
        professional: bool,
    ) -> str:
        lines: list[str] = []
        title = "专业修饰后的提示词" if professional else "生图提示词"
        lines.extend([f"**{title}**", review["final_prompt"]])

        if review.get("style_notes"):
            lines.extend(["", "**风格补充**", review["style_notes"]])
        if review.get("negative_prompt"):
            lines.extend(["", "**负向约束**", review["negative_prompt"]])
        if review.get("review_notes"):
            lines.append("")
            lines.append("**修饰要点**")
            for note in review["review_notes"]:
                lines.append(f"- {note}")

        lines.append("")
        if image_response.images:
            for index, image in enumerate(image_response.images, start=1):
                if image.url:
                    lines.append(f"![AI 生图 {index}]({image.url})")
                elif image.base64:
                    lines.append(f"AI 生图 {index} 已返回 Base64 图片数据。")
            if image_response.response_format == "url" and image_response.provider == "minimax":
                lines.append("")
                lines.append("图片 URL 通常会在 24 小时后失效。")
        else:
            lines.append("MiniMax 返回成功，但没有图片数据。")

        return "\n".join(lines).strip()

    def _render_aigc_planned_response(
        self,
        *,
        execution_plan: list[dict[str, str]],
        research_brief: str,
        review: dict[str, Any],
        image_response: ImageGenerationResponse,
        citations: list[Citation],
        professional: bool,
    ) -> str:
        lines: list[str] = []

        lines.append("**图片结果**")
        if image_response.images:
            for index, image in enumerate(image_response.images, start=1):
                if image.url:
                    lines.append(f"![AI 生图 {index}]({image.url})")
                elif image.base64:
                    lines.append(f"AI 生图 {index} 已返回 Base64 图片数据。")
            if image_response.response_format == "url" and image_response.provider == "minimax":
                lines.append("")
                lines.append("图片 URL 通常会在 24 小时后失效。")
        else:
            lines.append("MiniMax 返回成功，但没有图片数据。")

        if research_brief:
            lines.extend(["", "**简要总结**"])
            summary_lines = self._extract_aigc_brief_summary(research_brief)
            if summary_lines:
                lines.extend(f"- {line}" for line in summary_lines)
            else:
                lines.append("- 已基于检索结果整理事实、视觉 brief 和生图提示词。")

        if execution_plan:
            lines.extend(["", "**执行计划**"])
            for index, step in enumerate(execution_plan, start=1):
                lines.append(f"{index}. {step['title']}：已完成")

        if review.get("review_notes"):
            lines.extend(["", "**生成说明**"])
            for note in review["review_notes"][:3]:
                lines.append(f"- {note}")

        if citations:
            lines.extend(["", "**来源 / 备注**"])
            for citation in citations[:5]:
                label = citation.title or citation.url
                lines.append(f"- [{citation.index}] {label}: {citation.url}")

        return "\n".join(lines).strip()

    def _extract_aigc_brief_summary(self, research_brief: str, max_lines: int = 4) -> list[str]:
        share_card_summary = build_share_card_summary(research_brief, max_lines=max_lines)
        if share_card_summary:
            return share_card_summary

        lines: list[str] = []
        skip_markers = (
            "计划",
            "目标",
            "问题拆解",
            "任务拆解",
            "执行计划",
            "分阶段",
            "下一步",
            "依赖",
            "风险",
            "视觉简报",
            "生图",
            "执行指令",
            "来源说明",
            "缺口",
            "必须包含",
            "数据行",
            "版式",
            "视觉风格",
            "注意事项",
            "上下文复用简报",
            "当前生图请求",
            "可复用事实",
            "候选可复用上下文",
            "上传附件",
            "source",
            "gaps",
            "plan",
            "goal",
            "must include",
            "data rows",
            "layout",
            "visual style",
            "caveats",
            "next step",
            "visual brief",
            "context reuse brief",
            "current image request",
            "reusable facts",
            "candidate reusable context",
            "uploaded attachments",
        )
        for raw_line in research_brief.splitlines():
            line = raw_line.strip().lstrip("-*0123456789.、) ")
            line = line.replace("**", "").strip()
            if not line or line.startswith("#"):
                continue
            lowered = line.lower()
            if any(marker in lowered for marker in skip_markers):
                continue
            if len(line) > 120:
                line = line[:117].rstrip() + "..."
            if line and line not in lines:
                lines.append(line)
            if len(lines) >= max_lines:
                break
        return lines

    def _weight_loss_period_days(self, request: ChatRequest) -> int:
        text = " ".join([request.message or "", " ".join(request.mode_prompts or [])]).lower()
        match = re.search(r"(?:最近|近|last)\s*(\d{1,2})\s*(?:天|日|days?)", text)
        if match:
            return max(1, min(int(match.group(1)), 90))
        if any(marker in text for marker in ["今天", "今日", "today"]):
            return 1
        if any(marker in text for marker in ["本月", "这个月", "month"]):
            return 30
        if any(marker in text for marker in ["两周", "2周", "14天", "fortnight"]):
            return 14
        return 7

    def _weight_loss_user_id(self, request: ChatRequest) -> str:
        return str(getattr(request, "user_id", None) or "0").strip() or "0"

    def _weight_loss_image_attachments(self, attachments: list[ChatAttachment]) -> list[ChatAttachment]:
        return [
            attachment
            for attachment in attachments
            if attachment.kind == "image" and (attachment.data_url or "").startswith("data:image/")
        ][:4]

    def _format_weight_loss_history(self, history: list[LLMMessage]) -> str:
        lines: list[str] = []
        for message in history[-10:]:
            if message.role not in {"user", "assistant"}:
                continue
            content = message.content
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            content = " ".join(content.split())
            if content:
                role_label = "用户" if message.role == "user" else "助手"
                lines.append(f"{role_label}: {content[:1200]}")
        return "\n".join(lines) or "没有历史会话。"

    def _format_weight_loss_attachments(self, attachments: list[ChatAttachment]) -> str:
        if not attachments:
            return "没有附件。"
        lines: list[str] = []
        for index, attachment in enumerate(attachments[:8], start=1):
            content = " ".join((attachment.content or "").split())
            lines.append(
                "\n".join(
                    [
                        f"{index}. 名称={attachment.name or '未命名'}",
                        f"   类型={attachment.kind or 'file'}, MIME={attachment.type or '未知'}, 大小={attachment.size or 0} bytes",
                        f"   含图片数据={bool((attachment.data_url or '').startswith('data:image/'))}",
                        f"   文本={content[:1000] or '无'}",
                    ]
                )
            )
        return "\n".join(lines)

    def _render_weight_loss_summary_context(self, summary: dict[str, Any]) -> str:
        profile = summary.get("profile") or {}
        totals = summary.get("totals") or {}
        days = summary.get("days") or []
        profile_lines = []
        for key, label in [
            ("daily_calorie_goal", "每日目标"),
            ("maintenance_calories", "维持热量"),
            ("target_deficit", "目标缺口"),
            ("current_weight_kg", "当前体重kg"),
            ("target_weight_kg", "目标体重kg"),
            ("height_cm", "身高cm"),
            ("age_years", "年龄"),
            ("sex", "性别"),
            ("activity_level", "活动水平"),
        ]:
            if profile.get(key) not in (None, ""):
                profile_lines.append(f"- {label}: {profile[key]}")
        day_lines = []
        for day in days[:7]:
            fragments = [
                f"{day.get('date')}: 摄入 {day.get('intake', 0)} kcal",
                f"运动 {day.get('exercise', 0)} kcal",
            ]
            if day.get("deficit") is not None:
                fragments.append(f"缺口 {day['deficit']} kcal")
            if day.get("goal_gap") is not None:
                fragments.append(f"目标剩余 {day['goal_gap']} kcal")
            day_lines.append("，".join(fragments))
        return "\n".join(
            [
                "数据库中已有减脂档案：",
                "\n".join(profile_lines) or "- 暂未设置每日目标或维持热量",
                "",
                f"最近 {summary.get('period_days', 7)} 天统计：",
                f"- 总摄入: {totals.get('intake', 0)} kcal",
                f"- 运动消耗: {totals.get('exercise', 0)} kcal",
                f"- 平均摄入: {totals.get('average_intake', 0)} kcal/天",
                f"- 累计缺口: {totals.get('deficit') if totals.get('deficit') is not None else '未知，需要先设置维持热量'}",
                "\n".join(day_lines) or "- 暂无餐食记录",
            ]
        )

    def _build_weight_loss_messages(
        self,
        *,
        request: ChatRequest,
        role_context: MemoryContext,
        summary: dict[str, Any],
        history: list[LLMMessage],
        short_term_summary: str = "",
    ) -> list[LLMMessage]:
        current_time = datetime.now(ZoneInfo("Asia/Shanghai"))
        handoff_text = self._render_agent_handoff_packet(request.agent_input or request.handoff)
        context_blocks = self._normalize_context_blocks(request.context_blocks)
        context_text = "\n\n---\n\n".join(context_blocks) or "没有额外上下文。"
        system = (
            "你是减肥 Agent 的结构化分析器，负责从用户文字和食物图片中提取可入库的减脂数据。"
            "只返回 JSON，不要返回 Markdown 或额外解释。\n\n"
            "JSON 结构：\n"
            "{\n"
            '  "intent": "log_food|update_profile|log_exercise|summary|advice|mixed|clarify",\n'
            '  "profile_updates": {\n'
            '    "daily_calorie_goal": null,\n'
            '    "maintenance_calories": null,\n'
            '    "target_deficit": null,\n'
            '    "current_weight_kg": null,\n'
            '    "target_weight_kg": null,\n'
            '    "height_cm": null,\n'
            '    "age_years": null,\n'
            '    "sex": "",\n'
            '    "activity_level": "",\n'
            '    "notes": ""\n'
            "  },\n"
            '  "meal": {\n'
            '    "should_log": false,\n'
            '    "meal_name": "",\n'
            '    "meal_type": "breakfast|lunch|dinner|snack|drink|unknown",\n'
            '    "items": [{"name": "", "portion": "", "calories": 0, "protein_g": null, "carbs_g": null, "fat_g": null, "confidence": 0.0}],\n'
            '    "total_calories": 0,\n'
            '    "calorie_min": null,\n'
            '    "calorie_max": null,\n'
            '    "protein_g": null,\n'
            '    "carbs_g": null,\n'
            '    "fat_g": null,\n'
            '    "confidence": 0.0,\n'
            '    "assumptions": [],\n'
            '    "notes": ""\n'
            "  },\n"
            '  "exercise": {"should_log": false, "activity": "", "calories_burned": 0, "duration_min": null, "notes": ""},\n'
            '  "clarifying_question": "",\n'
            '  "assistant_response": "",\n'
            '  "assistant_notes": []\n'
            "}\n\n"
            "规则：\n"
            "- 用户上传食物图片或描述已吃/将吃的食物时，估算热量并设置 meal.should_log=true。"
            "- 估算必须保守，给出 calorie_min/calorie_max；看不清重量、油量、酱料时用 assumptions 说明。"
            "- 只在用户明确说消耗/运动/跑步/训练等场景时记录 exercise；不要把食物热量误记成运动。"
            "- 用户只是问统计/建议/追问上一餐为什么热量高时，不要虚构新餐食，meal.should_log=false。"
            "- assistant_response 是给用户看的自然语言回答；当 intent 为 advice/summary/clarify 且没有入库动作时必须填写。"
            "- assistant_response 不要复述 JSON schema，不要说“用户属于某意图”，不要暴露内部判断。"
            "- 数值单位统一为 kcal、kg、cm、分钟。"
            "- 这不是医疗诊断；不要给极端节食建议，不建议每日摄入低于 1200 kcal。"
        )
        text = (
            f"当前时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')} Asia/Shanghai\n\n"
            f"角色上下文：\n{role_context.rendered[:1600]}\n\n"
            f"短期记忆摘要：\n{short_term_summary or '暂无压缩摘要。'}\n\n"
            f"结构化 Agent/工具输入：\n{handoff_text}\n\n"
            f"近期对话：\n{self._format_weight_loss_history(history)}\n\n"
            f"本轮额外上下文：\n{context_text}\n\n"
            f"数据库摘要：\n{self._render_weight_loss_summary_context(summary)}\n\n"
            f"用户本轮请求：\n{request.message or '用户没有输入文字。'}\n\n"
            f"附件摘要：\n{self._format_weight_loss_attachments(request.attachments)}"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for attachment in self._weight_loss_image_attachments(request.attachments):
            content.append({"type": "image_url", "image_url": {"url": attachment.data_url}})
        return [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=content),
        ]

    def _weight_loss_profile_updates_from_text(self, text: str) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        normalized = re.sub(r"\s+", " ", text or "")
        patterns = [
            ("daily_calorie_goal", r"(?:每日|每天|目标|预算|摄入目标).{0,12}?(\d{3,4})\s*(?:kcal|大卡|千卡|卡)"),
            ("maintenance_calories", r"(?:维持热量|tdee|日消耗|维持).{0,12}?(\d{3,4})\s*(?:kcal|大卡|千卡|卡)?"),
            ("target_deficit", r"(?:目标缺口|热量缺口|缺口|赤字).{0,12}?(\d{2,4})\s*(?:kcal|大卡|千卡|卡)?"),
            ("height_cm", r"(?:身高).{0,8}?(\d{2,3}(?:\.\d+)?)\s*(?:cm|厘米|公分)?"),
            ("age_years", r"(?:年龄|岁数).{0,8}?(\d{1,2})\s*(?:岁|周岁)?"),
        ]
        for key, pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                updates[key] = self._coerce_number(
                    match.group(1),
                    integer=key in {"daily_calorie_goal", "maintenance_calories", "target_deficit", "age_years"},
                )

        weight_match = re.search(r"(?:当前体重|体重).{0,8}?(\d{2,3}(?:\.\d+)?)\s*(kg|公斤|斤)?", normalized, flags=re.IGNORECASE)
        if weight_match:
            value = float(weight_match.group(1))
            if weight_match.group(2) == "斤":
                value = value / 2
            updates["current_weight_kg"] = round(value, 1)
        sex_match = re.search(r"(?:性别).{0,6}?(男|女|male|female)|\b(male|female)\b", normalized, flags=re.IGNORECASE)
        if sex_match:
            updates["sex"] = (sex_match.group(1) or sex_match.group(2) or "").strip()
        elif re.search(r"(?:我是|本人|性别)?\s*男(?:性)?", normalized):
            updates["sex"] = "男"
        elif re.search(r"(?:我是|本人|性别)?\s*女(?:性)?", normalized):
            updates["sex"] = "女"
        activity_match = re.search(
            r"(久坐|轻度活动|中度活动|高强度|重度活动|坐居多|活动量低|活动量中等|活动量高)",
            normalized,
            flags=re.IGNORECASE,
        )
        if activity_match:
            updates["activity_level"] = activity_match.group(1)
        target_weight_match = re.search(r"(?:目标体重|减到|瘦到).{0,8}?(\d{2,3}(?:\.\d+)?)\s*(kg|公斤|斤)?", normalized, flags=re.IGNORECASE)
        if target_weight_match:
            value = float(target_weight_match.group(1))
            if target_weight_match.group(2) == "斤":
                value = value / 2
            updates["target_weight_kg"] = round(value, 1)
        return updates

    def _heuristic_weight_loss_analysis(self, request: ChatRequest) -> dict[str, Any]:
        text = request.message or ""
        lower = text.lower()
        profile_updates = self._weight_loss_profile_updates_from_text(text)
        has_summary_intent = any(marker in lower for marker in ["统计", "总结", "缺口", "建议", "还可以吃", "summary", "advice", "deficit"])
        kcal_matches = [
            int(match.group(1))
            for match in re.finditer(r"(\d{2,4})\s*(?:kcal|大卡|千卡|卡路里|卡)\b", text, flags=re.IGNORECASE)
        ]
        exercise_match = re.search(
            r"(跑步|骑车|游泳|力量|训练|运动|椭圆机|爬坡|快走).{0,24}?(\d{2,4})\s*(?:kcal|大卡|千卡|卡)",
            text,
            flags=re.IGNORECASE,
        )
        meal_kcal = 0
        if kcal_matches and not exercise_match:
            meal_kcal = kcal_matches[-1]
        elif len(kcal_matches) >= 2 and exercise_match:
            meal_kcal = kcal_matches[0]

        meal_should_log = meal_kcal > 0 and any(
            marker in lower
            for marker in ["吃", "喝", "早餐", "午餐", "晚餐", "加餐", "这餐", "外卖", "meal", "food"]
        )
        image_count = len(self._weight_loss_image_attachments(request.attachments))
        if image_count and not meal_should_log and not has_summary_intent:
            has_summary_intent = False

        exercise = {"should_log": False, "activity": "", "calories_burned": 0, "duration_min": None, "notes": ""}
        if exercise_match:
            exercise = {
                "should_log": True,
                "activity": exercise_match.group(1),
                "calories_burned": int(exercise_match.group(2)),
                "duration_min": None,
                "notes": "根据用户文字记录。",
            }

        return {
            "intent": "summary" if has_summary_intent else ("mixed" if profile_updates or meal_should_log or exercise["should_log"] else "clarify"),
            "profile_updates": profile_updates,
            "meal": {
                "should_log": meal_should_log,
                "meal_name": "用户文字记录",
                "meal_type": "unknown",
                "items": [],
                "total_calories": meal_kcal,
                "calorie_min": int(meal_kcal * 0.85) if meal_kcal else None,
                "calorie_max": int(meal_kcal * 1.15) if meal_kcal else None,
                "protein_g": None,
                "carbs_g": None,
                "fat_g": None,
                "confidence": 0.7 if meal_kcal else 0,
                "assumptions": ["用户已提供明确热量数字。"] if meal_kcal else [],
                "notes": "启发式解析，未调用视觉模型。",
            },
            "exercise": exercise,
            "clarifying_question": "" if (profile_updates or meal_should_log or exercise["should_log"] or has_summary_intent) else "请告诉我你想记录的食物、热量目标，或上传食物图片。",
            "assistant_notes": [],
        }

    def _coerce_number(self, value: Any, *, integer: bool = False) -> int | float | None:
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if integer:
            return int(round(number))
        return round(number, 1)

    def _coerce_weight_loss_analysis(self, raw: dict[str, Any] | None, request: ChatRequest) -> dict[str, Any]:
        fallback = self._heuristic_weight_loss_analysis(request)
        raw = raw or {}
        profile_raw = raw.get("profile_updates") if isinstance(raw.get("profile_updates"), dict) else {}
        profile_updates: dict[str, Any] = dict(fallback["profile_updates"])
        for key in [
            "daily_calorie_goal",
            "maintenance_calories",
            "target_deficit",
            "current_weight_kg",
            "target_weight_kg",
            "height_cm",
            "age_years",
        ]:
            integer = key in {"daily_calorie_goal", "maintenance_calories", "target_deficit", "age_years"}
            value = self._coerce_number(profile_raw.get(key), integer=integer)
            if value is not None:
                profile_updates[key] = value
        for key in ["sex", "activity_level", "notes"]:
            value = str(profile_raw.get(key) or "").strip()
            if value:
                profile_updates[key] = value[:500]

        meal_raw = raw.get("meal") if isinstance(raw.get("meal"), dict) else {}
        items_raw = meal_raw.get("items") if isinstance(meal_raw.get("items"), list) else []
        items: list[dict[str, Any]] = []
        for item in items_raw[:12]:
            if not isinstance(item, dict):
                continue
            calories = self._coerce_number(item.get("calories"), integer=True)
            name = str(item.get("name") or "").strip()
            if not name and calories is None:
                continue
            items.append(
                {
                    "name": name or "未识别食物",
                    "portion": str(item.get("portion") or "").strip()[:160],
                    "calories": calories or 0,
                    "protein_g": self._coerce_number(item.get("protein_g")),
                    "carbs_g": self._coerce_number(item.get("carbs_g")),
                    "fat_g": self._coerce_number(item.get("fat_g")),
                    "confidence": self._coerce_number(item.get("confidence")) or None,
                }
            )

        total_calories = self._coerce_number(meal_raw.get("total_calories"), integer=True)
        if total_calories is None and items:
            total_calories = sum(int(item["calories"] or 0) for item in items)
        if total_calories is None:
            total_calories = fallback["meal"]["total_calories"]
        total_calories = int(total_calories or 0)

        should_log_raw = meal_raw.get("should_log")
        should_log = bool(should_log_raw) if isinstance(should_log_raw, bool) else bool(fallback["meal"]["should_log"])
        if self._weight_loss_image_attachments(request.attachments) and total_calories > 0 and raw:
            should_log = True
        if total_calories <= 0:
            should_log = False

        calorie_min = self._coerce_number(meal_raw.get("calorie_min"), integer=True)
        calorie_max = self._coerce_number(meal_raw.get("calorie_max"), integer=True)
        range_value = meal_raw.get("calorie_range")
        if isinstance(range_value, dict):
            calorie_min = calorie_min or self._coerce_number(range_value.get("min"), integer=True)
            calorie_max = calorie_max or self._coerce_number(range_value.get("max"), integer=True)
        if total_calories and calorie_min is None:
            calorie_min = int(round(total_calories * 0.8))
        if total_calories and calorie_max is None:
            calorie_max = int(round(total_calories * 1.2))

        assumptions_value = meal_raw.get("assumptions")
        if isinstance(assumptions_value, list):
            assumptions = [str(item).strip() for item in assumptions_value if str(item).strip()]
        else:
            assumptions = list(fallback["meal"].get("assumptions") or [])

        meal = {
            "should_log": should_log,
            "meal_name": str(meal_raw.get("meal_name") or fallback["meal"]["meal_name"] or "食物热量估算").strip()[:120],
            "meal_type": str(meal_raw.get("meal_type") or fallback["meal"]["meal_type"] or "unknown").strip()[:40],
            "items": items,
            "total_calories": total_calories,
            "calorie_min": calorie_min,
            "calorie_max": calorie_max,
            "protein_g": self._coerce_number(meal_raw.get("protein_g")),
            "carbs_g": self._coerce_number(meal_raw.get("carbs_g")),
            "fat_g": self._coerce_number(meal_raw.get("fat_g")),
            "confidence": self._coerce_number(meal_raw.get("confidence")) or fallback["meal"].get("confidence") or 0.45,
            "assumptions": assumptions[:6],
            "notes": str(meal_raw.get("notes") or fallback["meal"].get("notes") or "").strip()[:1000],
        }

        exercise_raw = raw.get("exercise") if isinstance(raw.get("exercise"), dict) else {}
        exercise_calories = self._coerce_number(exercise_raw.get("calories_burned"), integer=True)
        fallback_exercise = fallback["exercise"]
        exercise = {
            "should_log": bool(exercise_raw.get("should_log"))
            if isinstance(exercise_raw.get("should_log"), bool)
            else bool(fallback_exercise.get("should_log")),
            "activity": str(exercise_raw.get("activity") or fallback_exercise.get("activity") or "运动").strip()[:120],
            "calories_burned": exercise_calories if exercise_calories is not None else int(fallback_exercise.get("calories_burned") or 0),
            "duration_min": self._coerce_number(exercise_raw.get("duration_min")),
            "notes": str(exercise_raw.get("notes") or fallback_exercise.get("notes") or "").strip()[:500],
        }
        if exercise["calories_burned"] <= 0:
            exercise["should_log"] = False

        notes_value = raw.get("assistant_notes")
        assistant_notes = (
            [str(item).strip() for item in notes_value if str(item).strip()]
            if isinstance(notes_value, list)
            else []
        )
        return {
            "intent": str(raw.get("intent") or fallback["intent"] or "mixed"),
            "profile_updates": profile_updates,
            "meal": meal,
            "exercise": exercise,
            "clarifying_question": str(raw.get("clarifying_question") or fallback.get("clarifying_question") or "").strip(),
            "assistant_response": str(raw.get("assistant_response") or "").strip()[:2000],
            "assistant_notes": assistant_notes[:6],
        }

    def _today_weight_loss_stats(self, summary: dict[str, Any]) -> dict[str, Any]:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        for day in summary.get("days") or []:
            if day.get("date") == today:
                return day
        return {
            "date": today,
            "intake": 0,
            "exercise": 0,
            "meal_count": 0,
            "exercise_count": 0,
            "deficit": None,
            "goal_gap": None,
            "items": [],
        }

    def _confidence_label(self, value: Any) -> str:
        number = self._coerce_number(value) or 0
        if number >= 0.75:
            return "较高"
        if number >= 0.5:
            return "中等"
        return "偏低"

    def _weight_loss_user_facing_notes(self, notes: list[Any] | None) -> list[str]:
        user_notes: list[str] = []
        for note in notes or []:
            text = " ".join(str(note or "").split())
            if not text:
                continue
            if re.search(
                r"^(?:用户|需|需要|应当|应该|避免|不要|本轮|对话|上下文)|(?:属于|意图|intent|用户.*反馈|用户.*咨询|用户.*描述)",
                text,
                flags=re.IGNORECASE,
            ):
                continue
            user_notes.append(text[:500])
            if len(user_notes) >= 4:
                break
        return user_notes

    def _render_weight_loss_status_line(self, summary: dict[str, Any]) -> str:
        today = self._today_weight_loss_stats(summary)
        fragments = [f"今天已记录 {today.get('intake', 0)} kcal"]
        if today.get("goal_gap") is not None:
            gap = int(today["goal_gap"])
            fragments.append(f"距目标还剩 {gap} kcal" if gap >= 0 else f"已超目标 {abs(gap)} kcal")
        if today.get("deficit") is not None:
            fragments.append(f"缺口约 {int(today['deficit'])} kcal")
        return "；".join(fragments) + "。"

    def _render_weight_loss_conversation_response(
        self,
        *,
        analysis: dict[str, Any],
        summary: dict[str, Any],
        model_used: str = "",
    ) -> str:
        response = (
            str(analysis.get("assistant_response") or "")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .strip()
        )
        notes = self._weight_loss_user_facing_notes(analysis.get("assistant_notes"))
        lines: list[str] = []
        if response:
            lines.append(response)
        elif notes:
            lines.extend(f"- {note}" for note in notes)
        elif analysis.get("intent") == "clarify":
            lines.append(analysis.get("clarifying_question") or "可以上传食物图片，或告诉我每日目标、维持热量和今天吃了什么。")
        else:
            lines.append("可以，我按已有记录帮你看。")

        if response and notes:
            lines.extend(["", *[f"- {note}" for note in notes[:3] if note not in response]])

        status_line = self._render_weight_loss_status_line(summary)
        if status_line:
            lines.extend(["", status_line])

        return "\n".join(lines).strip()

    def _render_weight_loss_response(
        self,
        *,
        analysis: dict[str, Any],
        logged_meal: dict[str, Any] | None,
        logged_exercise: dict[str, Any] | None,
        profile: dict[str, Any],
        summary: dict[str, Any],
        model_used: str = "",
        analysis_error: str = "",
    ) -> str:
        lines: list[str] = []
        meal = analysis.get("meal") or {}
        exercise = analysis.get("exercise") or {}
        profile_updates = analysis.get("profile_updates") or {}
        today = self._today_weight_loss_stats(summary)
        totals = summary.get("totals") or {}
        period_days = summary.get("period_days") or 7

        if (
            not logged_meal
            and not logged_exercise
            and not profile_updates
            and not analysis_error
            and analysis.get("intent") in {"advice", "summary", "clarify"}
        ):
            return self._render_weight_loss_conversation_response(
                analysis=analysis,
                summary=summary,
                model_used=model_used,
            )

        if logged_meal:
            calories = logged_meal.get("total_calories", 0)
            calorie_min = logged_meal.get("calorie_min")
            calorie_max = logged_meal.get("calorie_max")
            range_text = f"（约 {calorie_min}-{calorie_max} kcal）" if calorie_min and calorie_max else ""
            lines.extend(
                [
                    "**食物热量估算**",
                    f"- 本餐约 **{calories} kcal** {range_text}",
                    f"- 置信度：{self._confidence_label(meal.get('confidence'))}",
                ]
            )
            item_lines = []
            for item in (meal.get("items") or [])[:5]:
                item_lines.append(
                    f"{item.get('name') or '未识别食物'}"
                    + (f" {item.get('portion')}" if item.get("portion") else "")
                    + f"：约 {int(item.get('calories') or 0)} kcal"
                )
            if item_lines:
                lines.append(f"- 主要构成：{'；'.join(item_lines)}")
            if meal.get("assumptions"):
                lines.append(f"- 估算假设：{'；'.join(meal['assumptions'][:3])}")
            lines.append("- 已写入数据库饮食记录。")

        if logged_exercise:
            lines.extend(
                [
                    "" if lines else "",
                    "**运动记录**",
                    f"- {logged_exercise.get('activity') or '运动'}：约消耗 **{logged_exercise.get('calories_burned', 0)} kcal**",
                    "- 已写入数据库运动记录。",
                ]
            )

        if profile_updates:
            updated = []
            labels = {
                "daily_calorie_goal": "每日目标",
                "maintenance_calories": "维持热量",
                "target_deficit": "目标缺口",
                "current_weight_kg": "当前体重",
                "target_weight_kg": "目标体重",
                "height_cm": "身高",
                "age_years": "年龄",
                "sex": "性别",
                "activity_level": "活动水平",
            }
            for key, label in labels.items():
                if profile_updates.get(key) not in (None, ""):
                    if key in {"daily_calorie_goal", "maintenance_calories", "target_deficit"}:
                        unit = "kcal"
                    elif "weight" in key:
                        unit = "kg"
                    elif key == "height_cm":
                        unit = "cm"
                    elif key == "age_years":
                        unit = "岁"
                    else:
                        unit = ""
                    updated.append(f"{label} {profile_updates[key]}{(' ' + unit) if unit else ''}")
            if updated:
                lines.extend(["" if lines else "", "**目标档案已更新**", "- " + "；".join(updated)])

        lines.extend(
            [
                "" if lines else "",
                "**热量统计**",
                f"- 今天：摄入 **{today.get('intake', 0)} kcal**，运动 **{today.get('exercise', 0)} kcal**。",
            ]
        )
        if today.get("goal_gap") is not None:
            gap = int(today["goal_gap"])
            if gap >= 0:
                lines.append(f"- 距离今日摄入目标还剩约 **{gap} kcal**。")
            else:
                lines.append(f"- 今天已超出摄入目标约 **{abs(gap)} kcal**。")
        if today.get("deficit") is not None:
            deficit = int(today["deficit"])
            lines.append(f"- 按维持热量估算，今天热量缺口约 **{deficit} kcal**。")
        else:
            lines.append("- 还没有维持热量，暂时无法计算真实热量缺口。")

        lines.append(
            f"- 最近 {period_days} 天：总摄入 **{totals.get('intake', 0)} kcal**，"
            f"平均 **{totals.get('average_intake', 0)} kcal/天**。"
        )
        if totals.get("deficit") is not None:
            lines.append(f"- 最近 {period_days} 天累计缺口约 **{int(totals['deficit'])} kcal**。")

        advice = self._build_weight_loss_advice(profile=profile, summary=summary, logged_meal=logged_meal)
        if advice:
            lines.extend(["", "**建议**"])
            lines.extend(f"- {item}" for item in advice)

        if analysis.get("assistant_notes"):
            lines.extend(["", "**备注**"])
            lines.extend(f"- {note}" for note in analysis["assistant_notes"][:3])

        if analysis_error:
            lines.extend(
                [
                    "",
                    "**识别提示**",
                    f"- 本轮模型识别失败，已使用可解析的文字和数据库统计兜底：{analysis_error}",
                    "- 如需图片估算，请选择支持视觉输入的模型后重试。",
                ]
            )
        elif logged_meal:
            lines.extend(["", "食物图片热量是估算值，实际会受重量、烹调用油、酱料和品牌差异影响。"])

        if not logged_meal and not logged_exercise and not profile_updates and (analysis.get("intent") == "clarify"):
            question = analysis.get("clarifying_question") or "可以上传食物图片，或告诉我每日目标、维持热量和今天吃了什么。"
            lines.insert(0, question)

        return "\n".join(line for line in lines if line is not None).strip()

    def _build_weight_loss_advice(
        self,
        *,
        profile: dict[str, Any],
        summary: dict[str, Any],
        logged_meal: dict[str, Any] | None,
    ) -> list[str]:
        advice: list[str] = []
        today = self._today_weight_loss_stats(summary)
        goal = self._coerce_number(profile.get("daily_calorie_goal"), integer=True)
        maintenance = self._coerce_number(profile.get("maintenance_calories"), integer=True)
        if goal is None:
            advice.append("先设置每日摄入目标，例如“我的每日目标 1600 kcal”。")
        if maintenance is None:
            advice.append("再设置维持热量/TDEE，例如“我的维持热量 2200 kcal”，这样才能计算热量缺口。")

        if goal is not None and today.get("goal_gap") is not None:
            gap = int(today["goal_gap"])
            if gap >= 300:
                advice.append(f"今天还比较从容，下一餐优先安排蛋白质和蔬菜，主食控制在目标内，约还有 {gap} kcal 空间。")
            elif gap >= 0:
                advice.append(f"今天剩余热量不多，建议下一餐清淡一点，优先蛋白质和蔬菜，避免含糖饮料。")
            else:
                advice.append("今天已经超过目标，后面不要用极端节食补偿，改成散步、早点休息，明天把早餐和午餐吃稳。")

        if logged_meal and int(logged_meal.get("total_calories") or 0) >= 800:
            advice.append("这餐热量偏高，下一餐减少油脂和精制主食，保留足量蛋白质，会比硬饿更稳。")
        elif logged_meal:
            advice.append("这餐已记录，后续继续拍照或输入热量，我会累计到数据库里算缺口。")

        totals = summary.get("totals") or {}
        if totals.get("deficit") is not None:
            avg_deficit = int(totals["deficit"] / max(1, int(summary.get("period_days") or 1)))
            if avg_deficit > 900:
                advice.append("最近平均缺口偏大，注意睡眠、训练状态和饥饿感，避免长期过低摄入。")
            elif 300 <= avg_deficit <= 700:
                advice.append("最近缺口处在比较可持续的区间，重点是继续稳定记录，不要频繁大幅波动。")
        return list(dict.fromkeys(advice))[:4]

    def _parse_weight_loss_command(self, request: ChatRequest) -> tuple[str, str] | None:
        text = (request.message or "").strip()
        if not text.startswith("/"):
            return None
        match = re.match(r"^/([a-zA-Z][\w-]*)\b\s*(.*)$", text, flags=re.DOTALL)
        if not match:
            return ("help", "")
        return (match.group(1).lower(), match.group(2).strip())

    def _weight_loss_command_days(self, args: str, *, default: int = 7) -> int:
        text = (args or "").lower()
        if any(marker in text for marker in ["today", "今天", "今日"]):
            return 1
        match = re.search(r"(\d{1,2})\s*(?:d|day|days|天|日)?", text)
        if not match:
            return default
        return max(1, min(int(match.group(1)), 90))

    def _format_weight_loss_logged_at(self, value: Any) -> str:
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            return str(value or "")

    def _weight_loss_profile_brief(self, profile: dict[str, Any]) -> str:
        labels = [
            ("daily_calorie_goal", "每日目标", "kcal"),
            ("maintenance_calories", "维持热量", "kcal"),
            ("target_deficit", "目标缺口", "kcal"),
            ("current_weight_kg", "当前体重", "kg"),
            ("target_weight_kg", "目标体重", "kg"),
            ("height_cm", "身高", "cm"),
            ("age_years", "年龄", "岁"),
            ("sex", "性别", ""),
            ("activity_level", "活动水平", ""),
        ]
        parts = [
            f"{label} {profile[key]}{(' ' + unit) if unit else ''}"
            for key, label, unit in labels
            if profile.get(key) not in (None, "")
        ]
        return "；".join(parts) if parts else "尚未设置每日目标或维持热量"

    def _render_weight_loss_today_command(self, summary: dict[str, Any]) -> str:
        today = self._today_weight_loss_stats(summary)
        profile = summary.get("profile") or {}
        lines = [
            "**今日统计**",
            f"- 摄入：**{today.get('intake', 0)} kcal**，运动：**{today.get('exercise', 0)} kcal**。",
            f"- 记录：{today.get('meal_count', 0)} 餐，{today.get('exercise_count', 0)} 次运动。",
            f"- 档案：{self._weight_loss_profile_brief(profile)}。",
        ]
        if today.get("goal_gap") is not None:
            gap = int(today["goal_gap"])
            lines.append(f"- 今日目标剩余：**{gap} kcal**。" if gap >= 0 else f"- 今日已超目标：**{abs(gap)} kcal**。")
        if today.get("deficit") is not None:
            lines.append(f"- 按维持热量估算，今日缺口：**{int(today['deficit'])} kcal**。")
        else:
            lines.append("- 还没有维持热量，暂时无法计算真实缺口。")

        advice = self._build_weight_loss_advice(profile=profile, summary=summary, logged_meal=None)
        if advice:
            lines.extend(["", "**建议**"])
            lines.extend(f"- {item}" for item in advice[:3])
        return "\n".join(lines)

    def _render_weight_loss_history_command(
        self,
        *,
        summary: dict[str, Any],
        meals: list[dict[str, Any]],
        exercises: list[dict[str, Any]],
        days: int,
    ) -> str:
        totals = summary.get("totals") or {}
        lines = [
            f"**最近 {days} 天健康记录**",
            f"- 总摄入：**{totals.get('intake', 0)} kcal**，运动消耗：**{totals.get('exercise', 0)} kcal**。",
            f"- 平均摄入：**{totals.get('average_intake', 0)} kcal/天**。",
        ]
        if totals.get("deficit") is not None:
            lines.append(f"- 累计缺口：**{int(totals['deficit'])} kcal**。")

        day_lines = []
        for day in (summary.get("days") or [])[:14]:
            fragments = [
                f"{day.get('date')}: 摄入 {day.get('intake', 0)} kcal",
                f"运动 {day.get('exercise', 0)} kcal",
            ]
            if day.get("deficit") is not None:
                fragments.append(f"缺口 {int(day['deficit'])} kcal")
            day_lines.append("，".join(fragments))
        lines.extend(["", "**每日汇总**"])
        lines.extend(f"- {line}" for line in day_lines) if day_lines else lines.append("- 暂无记录。")

        lines.extend(["", "**最近餐食**"])
        if meals:
            for meal in meals[:10]:
                lines.append(
                    f"- {self._format_weight_loss_logged_at(meal.get('logged_at'))} "
                    f"{meal.get('meal_name') or '餐食'}：{meal.get('total_calories', 0)} kcal"
                )
        else:
            lines.append("- 暂无餐食记录。")

        lines.extend(["", "**最近运动**"])
        if exercises:
            for exercise in exercises[:10]:
                duration = exercise.get("duration_min")
                duration_text = f"，{duration:g} 分钟" if isinstance(duration, (int, float)) else ""
                lines.append(
                    f"- {self._format_weight_loss_logged_at(exercise.get('logged_at'))} "
                    f"{exercise.get('activity') or '运动'}：{exercise.get('calories_burned', 0)} kcal{duration_text}"
                )
        else:
            lines.append("- 暂无运动记录。")
        return "\n".join(lines)

    def _render_weight_loss_help_command(self) -> str:
        return "\n".join(
            [
                "**减肥 Agent 命令**",
                "- `/today`：查看今天摄入、运动、目标剩余和热量缺口。",
                "- `/history 7d`：查看最近 7 天健康记录，可改成 `/history 30d`。",
                "- `/goal 每日目标1600 维持热量2200`：设置目标和维持热量。",
                "- `/profile`：查看当前减脂档案；`/weighin 72.4kg` 记录体重。",
                "",
                "记录餐食和运动可以直接用自然语言，例如“午饭吃了牛肉饭，帮我估算并记录”或“今天跑步 35 分钟消耗 260 kcal”。",
            ]
        )

    def _parse_weight_loss_meal_command(self, args: str) -> dict[str, Any] | None:
        text = (args or "").strip()
        if not text:
            return None
        kcal_matches = list(
            re.finditer(r"(\d{2,4})\s*(?:kcal|大卡|千卡|卡路里|卡)?", text, flags=re.IGNORECASE)
        )
        if not kcal_matches:
            return None
        match = kcal_matches[-1]
        calories = int(match.group(1))
        if calories <= 0:
            return None
        meal_name = (text[: match.start()] + text[match.end() :]).strip(" ，,。")
        meal_type = "unknown"
        for marker, value in [
            ("早餐", "breakfast"),
            ("早饭", "breakfast"),
            ("午餐", "lunch"),
            ("午饭", "lunch"),
            ("晚餐", "dinner"),
            ("晚饭", "dinner"),
            ("加餐", "snack"),
            ("零食", "snack"),
            ("饮料", "drink"),
        ]:
            if marker in text:
                meal_type = value
                break
        return {
            "meal_name": meal_name[:120] or "手动记录餐食",
            "meal_type": meal_type,
            "total_calories": calories,
            "calorie_min": int(round(calories * 0.9)),
            "calorie_max": int(round(calories * 1.1)),
            "confidence": 0.95,
            "notes": "通过 /log 命令手动记录。",
        }

    def _parse_weight_loss_exercise_command(self, args: str) -> dict[str, Any] | None:
        text = (args or "").strip()
        if not text:
            return None
        duration = None
        duration_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:min|mins|分钟|分)", text, flags=re.IGNORECASE)
        if duration_match:
            duration = self._coerce_number(duration_match.group(1))
        kcal_matches = list(
            re.finditer(r"(\d{2,4})\s*(?:kcal|大卡|千卡|卡路里|卡)", text, flags=re.IGNORECASE)
        )
        if not kcal_matches:
            number_matches = list(re.finditer(r"(\d{2,4})", text))
            if duration_match:
                number_matches = [
                    match
                    for match in number_matches
                    if not (duration_match.start() <= match.start() < duration_match.end())
                ]
            kcal_matches = number_matches
        if not kcal_matches:
            return None
        kcal_match = kcal_matches[-1]
        calories = int(kcal_match.group(1))
        activity = (text[: kcal_match.start()] + text[kcal_match.end() :]).strip(" ，,。")
        activity = re.sub(r"\d{1,3}(?:\.\d+)?\s*(?:min|mins|分钟|分)", "", activity, flags=re.IGNORECASE)
        activity = activity.strip(" ，,。")
        return {
            "activity": activity[:120] or "运动",
            "calories_burned": calories,
            "duration_min": duration,
            "notes": "通过 /exercise 命令手动记录。",
        }

    def _weight_loss_profile_updates_from_command(self, command: str, args: str) -> dict[str, Any]:
        text = (args or "").strip()
        if command == "weighin":
            text = f"体重 {text}"
        updates = self._weight_loss_profile_updates_from_text(text)
        if command in {"goal", "profile"}:
            has_body_metric = any(marker in text for marker in ["身高", "体重", "年龄", "性别", "活动水平"])
            has_calorie_goal = any(
                marker.lower() in text.lower()
                for marker in ["每日", "每天", "摄入目标", "热量目标", "预算", "维持热量", "tdee", "kcal", "大卡", "千卡"]
            )
            if has_calorie_goal or not has_body_metric:
                numbers = [int(match.group(1)) for match in re.finditer(r"(\d{3,4})", text)]
                if numbers and "daily_calorie_goal" not in updates:
                    updates["daily_calorie_goal"] = numbers[0]
                if len(numbers) >= 2 and "maintenance_calories" not in updates:
                    updates["maintenance_calories"] = numbers[1]
        return updates

    def _append_weight_loss_summary_trace(self, run_id: str, summary: dict[str, Any]) -> None:
        self.trace_store.append_event(
            run_id,
            type="weight_loss.summary.completed",
            status="completed",
            title="Weight-loss calorie summary completed",
            payload={
                "period_days": summary.get("period_days", 7),
                "totals": summary.get("totals") or {},
                "today": self._today_weight_loss_stats(summary),
            },
        )

    async def _complete_weight_loss_response(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_id: str,
        role_context: MemoryContext,
        run_id: str,
        runtime: str,
        assistant_message: str,
        skills_used: list[str],
        plan: list[SkillCallInfo],
        model_used: str = "",
        tokens_used: dict[str, int] | None = None,
    ) -> ChatResponse:
        new_messages = [
            LLMMessage(role="user", content=request.message),
            LLMMessage(role="assistant", content=assistant_message),
        ]
        self._add_conversation_memory(request, new_messages)
        unique_skills = list(dict.fromkeys(skills_used))
        self.trace_store.complete_run(
            run_id,
            output=assistant_message,
            model_used=model_used,
            tokens_used=tokens_used or {},
            skills_used=unique_skills,
        )
        events = self._snapshot_run_events(run_id)
        self._schedule_memory_postprocess(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=assistant_message,
            new_messages=new_messages,
            run_id=run_id,
        )
        return ChatResponse(
            conversation_id=request.conversation_id,
            response=assistant_message,
            skills_used=unique_skills,
            plan=plan,
            model_used=model_used,
            tokens_used=tokens_used or {},
            agent_id=agent_id,
            role_id=role_id,
            runtime=runtime,
            run_id=run_id,
            events=events,
            memory_context=role_context.records,
            memory_updates=[],
        )

    async def _process_weight_loss_command(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_id: str,
        role_context: MemoryContext,
        run_id: str,
        runtime: str,
        command: tuple[str, str],
        delegation_trace: dict[str, Any] | None = None,
    ) -> ChatResponse:
        command_name, args = command
        messages = [
            LLMMessage(role="system", content="减肥 Agent 命令模式：直接执行本地数据库读写命令，不调用模型。"),
            LLMMessage(role="user", content=request.message),
        ]
        self._append_context_trace(
            run_id=run_id,
            role_id=role_id,
            role_context=role_context,
            messages=messages,
            tools_count=0,
            tool_names=[],
            mode_ids=request.mode_ids,
            mode_prompts=request.mode_prompts,
            context_blocks=request.context_blocks,
        )
        self.trace_store.append_event(
            run_id,
            type="weight_loss.command.received",
            status="completed",
            title="Weight-loss command received",
            payload={"command": command_name, "args": args},
        )
        if delegation_trace:
            self.trace_store.append_event(
                run_id,
                type="agent.delegated",
                status="completed",
                title="Delegated to Weight Loss Agent",
                payload=delegation_trace,
            )

        skills_used = ["weight_loss_commands"]
        plan = [
            SkillCallInfo(
                skill="weight_loss_commands",
                action=f"执行 /{command_name} 减脂快捷命令。",
                status="completed",
            )
        ]
        assistant_message = ""
        user_id = self._weight_loss_user_id(request)

        if command_name in {"help", "h", "?"}:
            assistant_message = self._render_weight_loss_help_command()
        elif command_name in {"today", "deficit", "budget"}:
            summary = self.weight_loss_store.summary(request.conversation_id, days=1, user_id=user_id)
            self._append_weight_loss_summary_trace(run_id, summary)
            skills_used.append("calorie_deficit_stats")
            assistant_message = self._render_weight_loss_today_command(summary)
        elif command_name in {"history", "hist"}:
            days = self._weight_loss_command_days(args, default=7)
            summary = self.weight_loss_store.summary(request.conversation_id, days=days, user_id=user_id)
            meals = self.weight_loss_store.list_meals(request.conversation_id, days=days, user_id=user_id)
            exercises = self.weight_loss_store.list_exercises(request.conversation_id, days=days, user_id=user_id)
            self._append_weight_loss_summary_trace(run_id, summary)
            skills_used.append("calorie_deficit_stats")
            assistant_message = self._render_weight_loss_history_command(
                summary=summary,
                meals=meals,
                exercises=exercises,
                days=days,
            )
        elif command_name in {"profile"} and not args:
            profile = self.weight_loss_store.get_profile(request.conversation_id, user_id=user_id)
            assistant_message = "\n".join(
                [
                    "**减脂档案**",
                    f"- {self._weight_loss_profile_brief(profile)}。",
                    "- 可用 `/goal 每日目标1600 维持热量2200` 更新目标，或 `/weighin 72.4kg` 记录体重。",
                ]
            )
            skills_used.append("weight_loss_profile")
        elif command_name in {"goal", "profile", "weighin"}:
            updates = self._weight_loss_profile_updates_from_command(command_name, args)
            if not updates:
                profile = self.weight_loss_store.get_profile(request.conversation_id, user_id=user_id)
                assistant_message = "\n".join(
                    [
                        "**目标设置**",
                        f"- 当前档案：{self._weight_loss_profile_brief(profile)}。",
                        "- 示例：`/goal 每日目标1600 维持热量2200`，或 `/weighin 72.4kg`。",
                    ]
                )
            else:
                profile = self.weight_loss_store.upsert_profile(request.conversation_id, updates, user_id=user_id)
                summary = self.weight_loss_store.summary(request.conversation_id, days=7, user_id=user_id)
                self.trace_store.append_event(
                    run_id,
                    type="weight_loss.profile.updated",
                    status="completed",
                    title="Weight-loss profile updated",
                    payload={"profile": profile, "updated_keys": list(updates.keys())},
                )
                self._append_weight_loss_summary_trace(run_id, summary)
                skills_used.extend(["weight_loss_profile", "calorie_deficit_stats"])
                assistant_message = self._render_weight_loss_response(
                    analysis={"intent": "update_profile", "profile_updates": updates, "meal": {}, "exercise": {}},
                    logged_meal=None,
                    logged_exercise=None,
                    profile=profile,
                    summary=summary,
                )
        elif command_name in {"log", "meal"}:
            meal = self._parse_weight_loss_meal_command(args)
            if not meal:
                assistant_message = "\n".join(
                    [
                        "我需要一个明确的热量数字才能手动入库。",
                        "示例：`/log 午餐 鸡胸饭 560kcal`。",
                    ]
                )
            else:
                logged_meal = self.weight_loss_store.add_meal(
                    request.conversation_id,
                    {**meal, "source": "command", "raw_json": meal},
                    user_id=user_id,
                )
                self.trace_store.append_event(
                    run_id,
                    type="weight_loss.meal.logged",
                    status="completed",
                    title="Meal logged",
                    payload={
                        "meal_id": logged_meal["id"],
                        "total_calories": logged_meal["total_calories"],
                        "calorie_min": logged_meal["calorie_min"],
                        "calorie_max": logged_meal["calorie_max"],
                        "image_count": 0,
                    },
                )
                summary = self.weight_loss_store.summary(request.conversation_id, days=7, user_id=user_id)
                profile = summary.get("profile") or {}
                self._append_weight_loss_summary_trace(run_id, summary)
                skills_used.extend(["nutrition_log", "calorie_deficit_stats"])
                assistant_message = self._render_weight_loss_response(
                    analysis={"intent": "log_food", "meal": meal, "exercise": {}, "profile_updates": {}},
                    logged_meal=logged_meal,
                    logged_exercise=None,
                    profile=profile,
                    summary=summary,
                )
        elif command_name in {"exercise", "workout", "sport"}:
            exercise = self._parse_weight_loss_exercise_command(args)
            if not exercise:
                assistant_message = "\n".join(
                    [
                        "我需要一个明确的运动消耗数字才能手动入库。",
                        "示例：`/exercise 跑步 260kcal 35分钟`。",
                    ]
                )
            else:
                logged_exercise = self.weight_loss_store.add_exercise(
                    request.conversation_id,
                    {**exercise, "raw_json": exercise},
                    user_id=user_id,
                )
                self.trace_store.append_event(
                    run_id,
                    type="weight_loss.exercise.logged",
                    status="completed",
                    title="Exercise logged",
                    payload={
                        "exercise_id": logged_exercise["id"],
                        "activity": logged_exercise["activity"],
                        "calories_burned": logged_exercise["calories_burned"],
                    },
                )
                summary = self.weight_loss_store.summary(request.conversation_id, days=7, user_id=user_id)
                profile = summary.get("profile") or {}
                self._append_weight_loss_summary_trace(run_id, summary)
                skills_used.extend(["exercise_logging", "calorie_deficit_stats"])
                assistant_message = self._render_weight_loss_response(
                    analysis={"intent": "log_exercise", "meal": {}, "exercise": exercise, "profile_updates": {}},
                    logged_meal=None,
                    logged_exercise=logged_exercise,
                    profile=profile,
                    summary=summary,
                )
        elif command_name == "undo":
            deleted = self.weight_loss_store.delete_latest_entry(request.conversation_id, user_id=user_id)
            if not deleted:
                assistant_message = "目前没有可以撤销的餐食或运动记录。"
            else:
                self.trace_store.append_event(
                    run_id,
                    type="weight_loss.entry.deleted",
                    status="completed",
                    title="Weight-loss entry deleted",
                    payload={
                        "entry_type": deleted.get("entry_type"),
                        "entry_id": deleted.get("id"),
                        "calories": deleted.get("total_calories") or deleted.get("calories_burned"),
                    },
                )
                summary = self.weight_loss_store.summary(request.conversation_id, days=7, user_id=user_id)
                self._append_weight_loss_summary_trace(run_id, summary)
                skills_used.append("calorie_deficit_stats")
                if deleted.get("entry_type") == "meal":
                    deleted_line = f"已撤销最近一条餐食：{deleted.get('meal_name') or '餐食'}，{deleted.get('total_calories', 0)} kcal。"
                else:
                    deleted_line = f"已撤销最近一条运动：{deleted.get('activity') or '运动'}，{deleted.get('calories_burned', 0)} kcal。"
                assistant_message = "\n\n".join([deleted_line, self._render_weight_loss_today_command(summary)])
        else:
            assistant_message = f"暂不认识 `/{command_name}`。\n\n{self._render_weight_loss_help_command()}"

        return await self._complete_weight_loss_response(
            request=request,
            agent_id=agent_id,
            role_id=role_id,
            role_context=role_context,
            run_id=run_id,
            runtime=runtime,
            assistant_message=assistant_message,
            skills_used=skills_used,
            plan=plan,
        )

    async def _process_weight_loss(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_id: str,
        role_context: MemoryContext,
        run_id: str,
        runtime: str,
        delegation_trace: dict[str, Any] | None = None,
    ) -> ChatResponse:
        command = self._parse_weight_loss_command(request)
        if command:
            return await self._process_weight_loss_command(
                request=request,
                agent_id=agent_id,
                role_id=role_id,
                role_context=role_context,
                run_id=run_id,
                runtime=runtime,
                command=command,
                delegation_trace=delegation_trace,
            )

        period_days = self._weight_loss_period_days(request)
        user_id = self._weight_loss_user_id(request)
        conversation_context = self.memory.get_context(self._conversation_memory_id(request))
        history = conversation_context.messages if request.memory_enabled else []
        short_term_summary = conversation_context.summary if request.memory_enabled else ""
        starting_summary = self.weight_loss_store.summary(request.conversation_id, days=period_days, user_id=user_id)
        messages = self._build_weight_loss_messages(
            request=request,
            role_context=role_context,
            summary=starting_summary,
            history=history,
            short_term_summary=short_term_summary,
        )
        self._append_context_trace(
            run_id=run_id,
            role_id=role_id,
            role_context=role_context,
            messages=messages,
            tools_count=0,
            tool_names=[],
            mode_ids=request.mode_ids,
            mode_prompts=request.mode_prompts,
            context_blocks=request.context_blocks,
            short_term_summary=short_term_summary,
        )
        self.trace_store.append_event(
            run_id,
            type="weight_loss.db.summary.loaded",
            status="completed",
            title="Weight-loss summary loaded",
            payload={
                "period_days": period_days,
                "meal_count": starting_summary.get("totals", {}).get("meal_count", 0),
                "has_profile": bool(starting_summary.get("profile")),
            },
        )
        if delegation_trace:
            self.trace_store.append_event(
                run_id,
                type="agent.delegated",
                status="completed",
                title="Delegated to Weight Loss Agent",
                payload=delegation_trace,
            )

        analysis = self._heuristic_weight_loss_analysis(request)
        model_used = ""
        tokens_used: dict[str, int] = {}
        analysis_error = ""
        analysis_started = perf_counter()
        self.trace_store.append_event(
            run_id,
            type="weight_loss.analysis.started",
            status="running",
            title="Food and goal analysis started",
            payload={
                "image_count": len(self._weight_loss_image_attachments(request.attachments)),
                "attachment_count": len(request.attachments),
                "model_preference": request.model_preference,
            },
        )
        try:
            response = None
            provider_cache_key = request.model_preference or "default"
            for attempt in range(1, WEIGHT_LOSS_ANALYSIS_MAX_ATTEMPTS + 1):
                try:
                    provider = self._get_provider(request.model_preference)
                    response = await provider.chat(messages, tools=None, temperature=0.1)
                    break
                except Exception as retry_error:
                    if attempt >= WEIGHT_LOSS_ANALYSIS_MAX_ATTEMPTS:
                        raise
                    delay = WEIGHT_LOSS_ANALYSIS_RETRY_DELAYS_SECONDS[
                        min(attempt - 1, len(WEIGHT_LOSS_ANALYSIS_RETRY_DELAYS_SECONDS) - 1)
                    ]
                    if isinstance(retry_error, RateLimitError) and retry_error.retry_after:
                        delay = max(delay, retry_error.retry_after)
                    self._providers.pop(provider_cache_key, None)
                    logger.warning(
                        "Weight-loss analysis attempt failed; retrying",
                        extra={
                            "attempt": attempt,
                            "max_attempts": WEIGHT_LOSS_ANALYSIS_MAX_ATTEMPTS,
                            "retry_delay_seconds": delay,
                            "error": str(retry_error),
                        },
                    )
                    self.trace_store.append_event(
                        run_id,
                        type="weight_loss.analysis.retrying",
                        status="running",
                        title="Food and goal analysis retrying",
                        payload={
                            "attempt": attempt,
                            "max_attempts": WEIGHT_LOSS_ANALYSIS_MAX_ATTEMPTS,
                            "retry_delay_seconds": delay,
                            "error_message": str(retry_error),
                        },
                        duration_ms=int((perf_counter() - analysis_started) * 1000),
                    )
                    await asyncio.sleep(delay)
            if response is None:
                raise RuntimeError("weight-loss analysis retry loop exited without a response")
            model_used = response.model
            tokens_used = response.usage
            raw_analysis = self._extract_json_object(response.content)
            analysis = self._coerce_weight_loss_analysis(raw_analysis, request)
            self.trace_store.append_event(
                run_id,
                type="weight_loss.analysis.completed",
                status="completed",
                title="Food and goal analysis completed",
                payload={
                    "model": model_used,
                    "usage": tokens_used,
                    "intent": analysis.get("intent"),
                    "meal_should_log": analysis.get("meal", {}).get("should_log"),
                    "exercise_should_log": analysis.get("exercise", {}).get("should_log"),
                    "profile_update_keys": list((analysis.get("profile_updates") or {}).keys()),
                    "response_preview": response.content[:500],
                },
                duration_ms=int((perf_counter() - analysis_started) * 1000),
            )
        except Exception as e:
            logger.exception("Weight-loss analysis failed; using heuristic fallback")
            analysis_error = str(e)
            self.trace_store.append_event(
                run_id,
                type="weight_loss.analysis.failed",
                status="error",
                title="Food and goal analysis failed; heuristic fallback used",
                payload={
                    "error_message": analysis_error,
                    "attempts": WEIGHT_LOSS_ANALYSIS_MAX_ATTEMPTS,
                },
                duration_ms=int((perf_counter() - analysis_started) * 1000),
            )

        logged_meal = None
        logged_exercise = None
        profile_updates = analysis.get("profile_updates") or {}
        if profile_updates:
            profile = self.weight_loss_store.upsert_profile(request.conversation_id, profile_updates, user_id=user_id)
            self.trace_store.append_event(
                run_id,
                type="weight_loss.profile.updated",
                status="completed",
                title="Weight-loss profile updated",
                payload={"profile": profile, "updated_keys": list(profile_updates.keys())},
            )
        else:
            profile = self.weight_loss_store.get_profile(request.conversation_id, user_id=user_id)

        meal = analysis.get("meal") or {}
        if meal.get("should_log") and int(meal.get("total_calories") or 0) > 0:
            logged_meal = self.weight_loss_store.add_meal(
                request.conversation_id,
                {
                    "meal_name": meal.get("meal_name"),
                    "meal_type": meal.get("meal_type"),
                    "total_calories": meal.get("total_calories"),
                    "calorie_min": meal.get("calorie_min"),
                    "calorie_max": meal.get("calorie_max"),
                    "protein_g": meal.get("protein_g"),
                    "carbs_g": meal.get("carbs_g"),
                    "fat_g": meal.get("fat_g"),
                    "confidence": meal.get("confidence"),
                    "source": "image" if self._weight_loss_image_attachments(request.attachments) else "text",
                    "notes": meal.get("notes"),
                    "image_count": len(self._weight_loss_image_attachments(request.attachments)),
                    "raw_json": meal,
                },
                user_id=user_id,
            )
            self.trace_store.append_event(
                run_id,
                type="weight_loss.meal.logged",
                status="completed",
                title="Meal logged",
                payload={
                    "meal_id": logged_meal["id"],
                    "total_calories": logged_meal["total_calories"],
                    "calorie_min": logged_meal["calorie_min"],
                    "calorie_max": logged_meal["calorie_max"],
                    "image_count": logged_meal["image_count"],
                },
            )

        exercise = analysis.get("exercise") or {}
        if exercise.get("should_log") and int(exercise.get("calories_burned") or 0) > 0:
            logged_exercise = self.weight_loss_store.add_exercise(
                request.conversation_id,
                {
                    "activity": exercise.get("activity"),
                    "calories_burned": exercise.get("calories_burned"),
                    "duration_min": exercise.get("duration_min"),
                    "notes": exercise.get("notes"),
                    "raw_json": exercise,
                },
                user_id=user_id,
            )
            self.trace_store.append_event(
                run_id,
                type="weight_loss.exercise.logged",
                status="completed",
                title="Exercise logged",
                payload={
                    "exercise_id": logged_exercise["id"],
                    "activity": logged_exercise["activity"],
                    "calories_burned": logged_exercise["calories_burned"],
                },
            )

        summary = self.weight_loss_store.summary(request.conversation_id, days=period_days, user_id=user_id)
        profile = summary.get("profile") or profile
        self.trace_store.append_event(
            run_id,
            type="weight_loss.summary.completed",
            status="completed",
            title="Weight-loss calorie summary completed",
            payload={
                "period_days": period_days,
                "totals": summary.get("totals") or {},
                "today": self._today_weight_loss_stats(summary),
            },
        )
        assistant_message = self._render_weight_loss_response(
            analysis=analysis,
            logged_meal=logged_meal,
            logged_exercise=logged_exercise,
            profile=profile,
            summary=summary,
            model_used=model_used,
            analysis_error=analysis_error,
        )
        new_messages = [
            LLMMessage(role="user", content=request.message),
            LLMMessage(role="assistant", content=assistant_message),
        ]
        self._add_conversation_memory(request, new_messages)
        skills_used = ["food_calorie_estimation"] if logged_meal else []
        if logged_exercise:
            skills_used.append("exercise_logging")
        if profile_updates:
            skills_used.append("weight_loss_profile")
        skills_used.append("calorie_deficit_stats")
        skills_used = list(dict.fromkeys(skills_used))
        plan = [
            SkillCallInfo(
                skill="food_calorie_estimation",
                action="识别食物图片或文字，估算本餐热量并给出区间。",
                status="completed" if logged_meal else "skipped",
                result_summary=str(logged_meal.get("total_calories")) + " kcal" if logged_meal else "本轮未记录新餐食。",
            ),
            SkillCallInfo(
                skill="calorie_deficit_stats",
                action="从数据库读取餐食、运动和目标，统计热量缺口。",
                status="completed",
                result_summary=json.dumps(summary.get("totals") or {}, ensure_ascii=False),
            ),
        ]
        self.trace_store.complete_run(
            run_id,
            output=assistant_message,
            model_used=model_used,
            tokens_used=tokens_used,
            skills_used=skills_used,
        )
        events = self._snapshot_run_events(run_id)
        self._schedule_memory_postprocess(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=assistant_message,
            new_messages=new_messages,
            run_id=run_id,
        )
        return ChatResponse(
            conversation_id=request.conversation_id,
            response=assistant_message,
            skills_used=skills_used,
            plan=plan,
            model_used=model_used,
            tokens_used=tokens_used,
            agent_id=agent_id,
            role_id=role_id,
            runtime=runtime,
            run_id=run_id,
            events=events,
            memory_context=role_context.records,
            memory_updates=[],
        )

    async def _process_image_generation(
        self,
        *,
        request: ChatRequest,
        agent_id: str,
        role_id: str,
        role_context: MemoryContext,
        run_id: str,
        runtime: str,
        delegation_trace: dict[str, Any] | None = None,
    ) -> ChatResponse:
        command_stage: AgentStageContext | None = None
        command = self._parse_aigc_command(
            request,
            allow_prompt_fallback=bool(delegation_trace and delegation_trace.get("reason") == "command_protocol"),
        )
        if command:
            command_payload = {
                "protocol_version": command["protocol_version"],
                "command": command["command"],
                "raw_command": command["raw_command"],
                "args_preview": str(command.get("args") or "")[:500],
                "original_message": command["original_message"],
                "prompt_fallback": bool(command.get("prompt_fallback")),
            }
            self.trace_store.append_event(
                run_id,
                type="aigc.command.received",
                status="completed",
                title="AI 生图命令已解析",
                payload=command_payload,
            )
            command_stage = AgentStageContext(
                stage_id="target_agent.command",
                status="completed",
                summary=f"AI 生图命令 /{command['command']} 已解析。",
                content=str(command.get("args") or "")[:1200],
                data=command_payload,
            )
            if command["command"] == "help":
                assistant_message = self._render_aigc_command_help()
                new_messages = [
                    LLMMessage(role="user", content=request.message),
                    LLMMessage(role="assistant", content=assistant_message),
                ]
                self._add_conversation_memory(request, new_messages)
                self.trace_store.complete_run(
                    run_id,
                    output=assistant_message,
                    model_used="",
                    tokens_used={},
                    skills_used=["image_generation_commands"],
                )
                latest_run = self.trace_store.get_run(run_id)
                return ChatResponse(
                    conversation_id=request.conversation_id,
                    response=assistant_message,
                    skills_used=["image_generation_commands"],
                    plan=None,
                    model_used="",
                    tokens_used={},
                    agent_id=agent_id,
                    role_id=role_id,
                    runtime=runtime,
                    run_id=run_id,
                    events=latest_run.events if latest_run else [],
                    memory_context=role_context.records,
                )
            request = self._apply_aigc_command_to_request(request, command)

        conversation_context = self.memory.get_context(self._conversation_memory_id(request))
        history = conversation_context.messages if request.memory_enabled else []
        short_term_summary = conversation_context.summary if request.memory_enabled else ""
        professional = self._aigc_professional_mode_enabled(request)
        context_brief = self._aigc_existing_context_brief(request=request, history=history)
        source_agent_id = (
            str(delegation_trace.get("source_agent_id"))
            if delegation_trace and delegation_trace.get("source_agent_id")
            else agent_id
        )
        source_stage_contexts: list[AgentStageContext] = []
        if delegation_trace:
            source_stage_contexts.append(
                AgentStageContext(
                    stage_id="source_agent.routing",
                    status="completed",
                    summary=(
                        f"{source_agent_id} delegated to {agent_id} by "
                        f"{delegation_trace.get('reason') or 'unspecified'} routing."
                    ),
                    data={
                        "source_agent_id": source_agent_id,
                        "target_agent_id": agent_id,
                        "reason": delegation_trace.get("reason") or "",
                        "forced": bool(delegation_trace.get("forced")),
                        "mode_ids": delegation_trace.get("mode_ids") or [],
                    },
                )
            )
        if command_stage is not None:
            source_stage_contexts.append(command_stage)
        handoff_packet = self._build_agent_handoff_packet(
            request=request,
            source_agent_id=source_agent_id,
            target_agent_id=agent_id,
            history=history,
            context_brief=context_brief,
            delegation_trace=delegation_trace,
            stage_contexts=source_stage_contexts,
        )
        self.trace_store.append_event(
            run_id,
            type="agent.input_context.built",
            status="completed",
            title="Agent input context built",
            payload=self._trace_handoff_packet_payload(handoff_packet),
        )
        self.trace_store.append_event(
            run_id,
            type="agent.handoff_context.built",
            status="completed",
            title="Agent handoff context built",
            payload=self._trace_handoff_packet_payload(handoff_packet),
        )
        planning_decision = await self._prepare_aigc_execution_decision(
            request=request,
            role_context=role_context,
            history=history,
            context_brief=context_brief,
            run_id=run_id,
            handoff_packet=handoff_packet,
            short_term_summary=short_term_summary,
        )
        planning_stage = AgentStageContext(
            stage_id="target_agent.execution_planning",
            status="completed",
            summary=planning_decision.get("reason") or "AI 生图执行规划已完成。",
            content=str(planning_decision.get("selected_context_brief") or "")[:1800],
            data={
                "information_strategy": planning_decision["information_strategy"],
                "brief_format": planning_decision["brief_format"],
                "brief_format_reason": planning_decision["brief_format_reason"],
                "steps": planning_decision["steps"],
                "planner_model": planning_decision.get("model") or "",
                "fallback": bool(planning_decision.get("fallback")),
            },
        )
        if planning_decision["information_strategy"] == "reuse_context":
            context_brief = planning_decision["selected_context_brief"] or context_brief
            handoff_packet = self._append_agent_input_stage(
                handoff_packet,
                planning_stage,
                candidate_context_brief=context_brief,
            )
        else:
            handoff_packet = self._append_agent_input_stage(handoff_packet, planning_stage)
        self.trace_store.append_event(
            run_id,
            type="agent.input_context.updated",
            status="completed",
            title="Agent input context updated",
            payload=self._trace_handoff_packet_payload(handoff_packet),
        )
        self.trace_store.append_event(
            run_id,
            type="agent.handoff_context.updated",
            status="completed",
            title="Agent handoff context updated",
            payload=self._trace_handoff_packet_payload(handoff_packet),
        )
        reuse_context_brief = planning_decision["information_strategy"] == "reuse_context"
        execution_plan = self._build_aigc_execution_plan(
            request,
            planning_decision=planning_decision,
        )
        if execution_plan:
            self.trace_store.append_event(
                run_id,
                type="aigc.plan.created",
                status="completed",
                title="AI 生图执行计划",
                payload={
                    "steps": execution_plan,
                    "mode_ids": request.mode_ids,
                    "information_strategy": planning_decision["information_strategy"],
                    "brief_format": planning_decision["brief_format"],
                    "brief_format_reason": planning_decision["brief_format_reason"],
                    "reuse_context_brief": reuse_context_brief,
                    "planner_model": planning_decision["model"],
                    "planner_fallback": planning_decision["fallback"],
                },
            )
            self.trace_store.append_event(
                run_id,
                type="aigc.plan.step.completed",
                status="completed",
                title="执行计划步骤完成：任务拆解",
                step_id=AIGC_PLAN_DECOMPOSE_STEP,
                payload={
                    "step": AIGC_PLAN_DECOMPOSE_STEP,
                    "steps": [step["id"] for step in execution_plan],
                },
            )

        if delegation_trace:
            self.trace_store.append_event(
                run_id,
                type="agent.delegated",
                status="completed",
                title="Delegated to AI 生图",
                payload=delegation_trace,
            )

        self.trace_store.append_event(
            run_id,
            type="memory.loaded",
            status="completed",
            title="Role memory loaded",
            payload=self._memory_loaded_payload(
                role_id=role_id,
                user_id=self._user_id(request),
                role_context=role_context,
            ),
        )

        research_result: dict[str, Any] = {
            "brief": "",
            "model": "",
            "usage": {},
            "skills_used": [],
            "citations": [],
            "plan": [],
        }
        if reuse_context_brief:
            research_result = {
                "brief": context_brief,
                "model": "",
                "usage": {},
                "skills_used": [],
                "citations": [],
                "plan": [
                    SkillCallInfo(
                        skill=AIGC_PLAN_CONTEXT_STEP,
                        action="复用规划器选中的会话事实作为生图简报。",
                        status="completed",
                        result_summary=context_brief[:200],
                    )
                ],
            }
            self.trace_store.append_event(
                run_id,
                type="aigc.context_reuse.completed",
                status="completed",
                title="Reused conversation context for image brief",
                step_id=AIGC_PLAN_CONTEXT_STEP,
                payload={
                    "step": AIGC_PLAN_CONTEXT_STEP,
                    "brief_preview": context_brief[:500],
                    "brief_format": planning_decision["brief_format"],
                    "brief_format_reason": planning_decision["brief_format_reason"],
                    "context_block_count": len(request.context_blocks or []),
                },
            )
            self.trace_store.append_event(
                run_id,
                type="aigc.plan.step.completed",
                status="completed",
                title="执行计划步骤完成：复用会话上下文",
                step_id=AIGC_PLAN_CONTEXT_STEP,
                payload={
                    "step": AIGC_PLAN_CONTEXT_STEP,
                    "brief_preview": context_brief[:400],
                },
            )
        elif any(step["id"] == AIGC_PLAN_RETRIEVAL_STEP for step in execution_plan):
            self.trace_store.append_event(
                run_id,
                type="aigc.plan.step.started",
                status="running",
                title="执行计划步骤：检索并整理资料",
                step_id=AIGC_PLAN_RETRIEVAL_STEP,
                payload={"step": AIGC_PLAN_RETRIEVAL_STEP},
            )
            try:
                research_result = await self._prepare_aigc_research_brief(
                    request=request,
                    role_context=role_context,
                    history=history,
                    run_id=run_id,
                    handoff_packet=handoff_packet,
                    short_term_summary=short_term_summary,
                )
                self.trace_store.append_event(
                    run_id,
                    type="aigc.plan.step.completed",
                    status="completed",
                    title="执行计划步骤完成：检索并整理资料",
                    step_id=AIGC_PLAN_RETRIEVAL_STEP,
                    payload={
                        "step": AIGC_PLAN_RETRIEVAL_STEP,
                        "brief_preview": str(research_result.get("brief") or "")[:400],
                        "skills_used": research_result.get("skills_used") or [],
                    },
                )
            except Exception as e:
                logger.exception("AIGC pre-generation research failed; continuing without research brief")
                self.trace_store.append_event(
                    run_id,
                    type="aigc.research.failed",
                    status="error",
                    title="Pre-generation research failed",
                    payload={"error_message": str(e)},
                )
                self.trace_store.append_event(
                    run_id,
                    type="aigc.plan.step.failed",
                    status="error",
                    title="执行计划步骤失败：检索并整理资料",
                    step_id=AIGC_PLAN_RETRIEVAL_STEP,
                    payload={"step": AIGC_PLAN_RETRIEVAL_STEP, "error_message": str(e)},
                )

        research_brief = str(research_result.get("brief") or "").strip()
        research_usage = dict(planning_decision.get("usage") or {})
        for key, value in dict(research_result.get("usage") or {}).items():
            research_usage[key] = research_usage.get(key, 0) + value
        research_skills = list(research_result.get("skills_used") or [])
        research_citations = list(research_result.get("citations") or [])
        research_plan = list(research_result.get("plan") or [])
        if research_brief:
            source_stage_id = (
                "target_agent.context_reuse"
                if reuse_context_brief
                else "target_agent.research_brief"
            )
            handoff_packet = self._append_agent_input_stage(
                handoff_packet,
                AgentStageContext(
                    stage_id=source_stage_id,
                    status="completed",
                    summary=(
                        "已复用规划器选中的会话上下文。"
                        if reuse_context_brief
                        else "已准备带来源支撑的生图简报。"
                    ),
                    content=research_brief[:2400],
                    data={
                        "brief_format": planning_decision["brief_format"],
                        "skills_used": research_skills,
                        "citation_count": len(research_citations),
                        "citation_urls": [citation.url for citation in research_citations[:8]],
                    },
                ),
                candidate_context_brief=research_brief,
            )
            self.trace_store.append_event(
                run_id,
                type="agent.input_context.updated",
                status="completed",
                title="Agent input context updated with pre-generation brief",
                payload=self._trace_handoff_packet_payload(handoff_packet),
            )
        text_heavy_visual = is_text_heavy_visual_intent(
            message=request.message,
            research_brief=research_brief,
            context_blocks=request.context_blocks,
            mode_prompts=request.mode_prompts,
        )

        review_context_blocks = [] if research_brief else request.context_blocks
        review_messages = self._build_aigc_review_messages(
            request=request,
            role_context=role_context,
            history=history,
            professional=professional,
            research_brief=research_brief,
            text_heavy_visual=text_heavy_visual,
            handoff_packet=handoff_packet,
            short_term_summary=short_term_summary,
        )
        self._append_context_trace(
            run_id=run_id,
            role_id=role_id,
            role_context=role_context,
            messages=review_messages,
            tools_count=0,
            tool_names=[],
            mode_ids=request.mode_ids,
            mode_prompts=request.mode_prompts,
            context_blocks=review_context_blocks,
            short_term_summary=short_term_summary,
        )

        fallback_review = self._fallback_aigc_review(request)
        if text_heavy_visual:
            fallback_review = apply_text_rendering_guard(fallback_review)
        fallback_prompt = fallback_review["final_prompt"]
        review = fallback_review
        review_model = ""
        review_usage: dict[str, int] = {}

        review_started = perf_counter()
        if execution_plan:
            self.trace_store.append_event(
                run_id,
                type="aigc.plan.step.started",
                status="running",
                title="执行计划步骤：基于资料生成图片",
                step_id=AIGC_PLAN_IMAGE_STEP,
                payload={"step": AIGC_PLAN_IMAGE_STEP},
            )
        self.trace_store.append_event(
            run_id,
            type="aigc.prompt_review.started",
            status="running",
            title="Prompt review started",
            payload={
                "professional": professional,
                "attachment_count": len(request.attachments),
                "model_preference": request.model_preference,
                "text_heavy_visual": text_heavy_visual,
            },
        )
        try:
            provider = self._get_provider(request.model_preference)
            review_response = await self._chat_with_retry(
                provider,
                request=request,
                run_id=run_id,
                messages=review_messages,
                tools=None,
                temperature=0.2,
                retry_context={"scope": "aigc_prompt_review"},
            )
            review_model = review_response.model
            review_usage = review_response.usage
            review = self._parse_aigc_review_response(
                review_response.content,
                fallback_prompt=fallback_prompt,
                text_heavy_visual=text_heavy_visual,
            )
            self.trace_store.append_event(
                run_id,
                type="aigc.prompt_review.completed",
                status="completed",
                title="Prompt review completed",
                payload={
                    "model": review_model,
                    "professional": professional,
                    "should_generate": review["should_generate"],
                    "aspect_ratio": review["aspect_ratio"],
                    "text_heavy_visual": text_heavy_visual,
                    "final_prompt_preview": review["final_prompt"][:1200],
                    "final_prompt_char_count": len(review["final_prompt"]),
                    "review_notes": review["review_notes"],
                    "usage": review_usage,
                },
                duration_ms=int((perf_counter() - review_started) * 1000),
            )
        except Exception as e:
            logger.exception("AIGC prompt review failed; falling back to user prompt")
            self.trace_store.append_event(
                run_id,
                type="aigc.prompt_review.failed",
                status="error",
                title="Prompt review failed; using fallback prompt",
                payload={"error_message": str(e), "professional": professional},
                duration_ms=int((perf_counter() - review_started) * 1000),
            )

        if not review["should_generate"]:
            assistant_message = review["clarifying_question"] or "请再补充一下你想生成的画面。"
            new_messages = [
                LLMMessage(role="user", content=request.message),
                LLMMessage(role="assistant", content=assistant_message),
            ]
            self._add_conversation_memory(request, new_messages)
            skills_used = list(dict.fromkeys(research_skills + ["prompt_refine"]))
            tokens_used = dict(research_usage)
            for key, value in review_usage.items():
                tokens_used[key] = tokens_used.get(key, 0) + value
            model_used = " / ".join(
                dict.fromkeys(
                    item
                    for item in [
                        str(planning_decision.get("model") or ""),
                        str(research_result.get("model") or ""),
                        review_model,
                    ]
                    if item
                )
            )
            plan_infos = self._aigc_plan_infos(
                execution_plan=execution_plan,
                retrieval_status="completed" if research_brief else "pending",
                image_status="pending",
                summary_status="pending",
                research_brief=research_brief,
            )
            self.trace_store.complete_run(
                run_id,
                output=assistant_message,
                model_used=model_used,
                tokens_used=tokens_used,
                skills_used=skills_used,
            )
            events = self._snapshot_run_events(run_id)
            self._schedule_memory_postprocess(
                request=request,
                agent_id=agent_id,
                role_context=role_context,
                assistant_message=assistant_message,
                new_messages=new_messages,
                run_id=run_id,
            )
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=assistant_message,
                skills_used=skills_used,
                citations=research_citations,
                plan=plan_infos or (research_plan if research_plan else None),
                model_used=model_used,
                tokens_used=tokens_used,
                agent_id=agent_id,
                role_id=role_id,
                runtime=runtime,
                run_id=run_id,
                events=events,
                memory_context=role_context.records,
                memory_updates=[],
            )

        subject_references = self._aigc_subject_references(request.attachments)
        image_request = ImageGenerationRequest(
            prompt=review["final_prompt"],
            aspect_ratio=review["aspect_ratio"],
            response_format="url",
            n=1,
            prompt_optimizer=not text_heavy_visual,
            subject_reference=subject_references or None,
        )

        share_card_result = None
        if text_heavy_visual and research_brief:
            try:
                share_card_result = render_share_card_svg(research_brief, run_id=run_id)
            except Exception:
                logger.exception("Local AIGC share-card rendering failed; falling back to MiniMax")

        if share_card_result:
            image_started = perf_counter()
            self.trace_store.append_event(
                run_id,
                type="aigc.image.started",
                status="running",
                title="Local share-card rendering started",
                payload={
                    "aspect_ratio": image_request.aspect_ratio,
                    "response_format": "url",
                    "n": 1,
                    "provider": "local_svg",
                    "text_heavy_visual": text_heavy_visual,
                    "row_count": share_card_result.row_count,
                },
            )
            image_response = ImageGenerationResponse(
                id=f"svg_{run_id}",
                provider="local_svg",
                model="svg-share-card-v1",
                prompt=image_request.prompt,
                aspect_ratio=image_request.aspect_ratio,
                response_format="url",
                images=[
                    GeneratedImage(
                        index=0,
                        url=share_card_result.url,
                        mime_type="image/svg+xml",
                    )
                ],
                metadata={
                    "title": share_card_result.title,
                    "conclusion": share_card_result.conclusion,
                    "row_count": share_card_result.row_count,
                    "path": str(share_card_result.path),
                },
            )
            review = dict(review)
            review["review_notes"] = [
                "已使用 AI 生图 agent 的结构化 SVG 渲染器生成，标题、结论和对比数据直接写入图片。",
                "文字密集内容未交给图像模型排版，避免中文乱码和表格缺失。",
            ]
            self.trace_store.append_event(
                run_id,
                type="aigc.image.completed",
                status="completed",
                title="Local share-card rendering completed",
                payload={
                    "model": image_response.model,
                    "image_count": len(image_response.images),
                    "provider": image_response.provider,
                    "response_format": image_response.response_format,
                    "row_count": share_card_result.row_count,
                },
                duration_ms=int((perf_counter() - image_started) * 1000),
            )
            if execution_plan:
                self.trace_store.append_event(
                    run_id,
                    type="aigc.plan.step.completed",
                    status="completed",
                    title="执行计划步骤完成：基于资料生成图片",
                    step_id=AIGC_PLAN_IMAGE_STEP,
                    payload={
                        "step": AIGC_PLAN_IMAGE_STEP,
                        "image_count": len(image_response.images),
                        "model": image_response.model,
                        "provider": image_response.provider,
                    },
                )
        else:
            image_started = perf_counter()
            self.trace_store.append_event(
                run_id,
                type="aigc.image.started",
                status="running",
                title="MiniMax image generation started",
                payload={
                    "aspect_ratio": image_request.aspect_ratio,
                    "response_format": image_request.response_format,
                    "n": image_request.n,
                    "subject_reference_count": len(subject_references),
                    "prompt_optimizer": image_request.prompt_optimizer,
                    "text_heavy_visual": text_heavy_visual,
                },
            )
            try:
                image_client = MiniMaxAIGCClient.from_runtime_config()
                raw_image = await image_client.generate_image(
                    image_request.prompt,
                    model=image_request.model,
                    aspect_ratio=image_request.aspect_ratio,
                    response_format=image_request.response_format,
                    n=image_request.n,
                    prompt_optimizer=image_request.prompt_optimizer,
                    extra=image_request.minimax_extra(),
                )
                image_response = ImageGenerationResponse.from_minimax(
                    raw_image,
                    image_request,
                    model=image_request.model or image_client.image_model,
                )
                self.trace_store.append_event(
                    run_id,
                    type="aigc.image.completed",
                    status="completed",
                    title="MiniMax image generation completed",
                    payload={
                        "model": image_response.model,
                        "image_count": len(image_response.images),
                        "provider": image_response.provider,
                        "response_format": image_response.response_format,
                    },
                    duration_ms=int((perf_counter() - image_started) * 1000),
                )
                if execution_plan:
                    self.trace_store.append_event(
                        run_id,
                        type="aigc.plan.step.completed",
                        status="completed",
                        title="执行计划步骤完成：基于资料生成图片",
                        step_id=AIGC_PLAN_IMAGE_STEP,
                        payload={
                            "step": AIGC_PLAN_IMAGE_STEP,
                            "image_count": len(image_response.images),
                            "model": image_response.model,
                        },
                    )
            except Exception as e:
                logger.exception("AIGC image generation failed")
                raw_error = str(e)
                error_msg = self._aigc_image_error_message(
                    e,
                    request=request,
                    review=review,
                )
                self.trace_store.append_event(
                    run_id,
                    type="aigc.image.failed",
                    status="error",
                    title="MiniMax image generation failed",
                    payload={
                        "error_message": error_msg,
                        "raw_error_message": raw_error,
                    },
                    duration_ms=int((perf_counter() - image_started) * 1000),
                )
                self.trace_store.fail_run(
                    run_id,
                    error_message=error_msg,
                    error_type="aigc_error",
                    output=error_msg,
                )
                new_messages = [
                    LLMMessage(role="user", content=request.message),
                    LLMMessage(role="assistant", content=error_msg),
                ]
                self._add_conversation_memory(request, new_messages)
                error_tokens_used = dict(research_usage)
                for key, value in review_usage.items():
                    error_tokens_used[key] = error_tokens_used.get(key, 0) + value
                error_model_used = " / ".join(
                    dict.fromkeys(
                        item
                        for item in [
                            str(planning_decision.get("model") or ""),
                            str(research_result.get("model") or ""),
                            review_model,
                        ]
                        if item
                    )
                )
                plan_infos = self._aigc_plan_infos(
                    execution_plan=execution_plan,
                    retrieval_status="completed" if research_brief else "pending",
                    image_status="error",
                    summary_status="pending",
                    research_brief=research_brief,
                )
                latest_run = self.trace_store.get_run(run_id)
                return ChatResponse(
                    conversation_id=request.conversation_id,
                    response=error_msg,
                    skills_used=list(dict.fromkeys(research_skills + ["prompt_refine"])),
                    citations=research_citations,
                    plan=plan_infos or (research_plan if research_plan else None),
                    model_used=error_model_used,
                    tokens_used=error_tokens_used,
                    error_type="",
                    agent_id=agent_id,
                    role_id=role_id,
                    runtime=runtime,
                    run_id=run_id,
                    events=latest_run.events if latest_run else [],
                    memory_context=role_context.records,
                )

        if execution_plan:
            self.trace_store.append_event(
                run_id,
                type="aigc.plan.step.started",
                status="running",
                title="执行计划步骤：合并检索结论和图片结果",
                step_id=AIGC_PLAN_SUMMARY_STEP,
                payload={"step": AIGC_PLAN_SUMMARY_STEP},
            )
            assistant_message = self._render_aigc_planned_response(
                execution_plan=execution_plan,
                research_brief=research_brief,
                review=review,
                image_response=image_response,
                citations=research_citations,
                professional=professional,
            )
            self.trace_store.append_event(
                run_id,
                type="aigc.plan.step.completed",
                status="completed",
                title="执行计划步骤完成：合并检索结论和图片结果",
                step_id=AIGC_PLAN_SUMMARY_STEP,
                payload={
                    "step": AIGC_PLAN_SUMMARY_STEP,
                    "citation_count": len(research_citations),
                    "image_count": len(image_response.images),
                },
            )
            self.trace_store.append_event(
                run_id,
                type="aigc.summary.completed",
                status="completed",
                title="检索与生图结果已合并",
                payload={
                    "citation_count": len(research_citations),
                    "image_count": len(image_response.images),
                },
            )
            self.trace_store.append_event(
                run_id,
                type="aigc.plan.completed",
                status="completed",
                title="AI 生图执行计划完成",
                payload={
                    "steps": [step["id"] for step in execution_plan],
                    "citation_count": len(research_citations),
                    "image_count": len(image_response.images),
                },
            )
        else:
            assistant_message = self._render_aigc_response(
                review=review,
                image_response=image_response,
                professional=professional,
            )
        new_messages = [
            LLMMessage(role="user", content=request.message),
            LLMMessage(role="assistant", content=assistant_message),
        ]
        self._add_conversation_memory(request, new_messages)

        skills_used = list(dict.fromkeys(research_skills + ["prompt_refine", "image_generation"]))
        model_used = " / ".join(
            dict.fromkeys(
                item
                for item in [
                    str(planning_decision.get("model") or ""),
                    str(research_result.get("model") or ""),
                    review_model,
                    image_response.model,
                ]
                if item
            )
        )
        tokens_used = dict(research_usage)
        for key, value in review_usage.items():
            tokens_used[key] = tokens_used.get(key, 0) + value
        tokens_used["images"] = len(image_response.images)
        plan_infos = self._aigc_plan_infos(
            execution_plan=execution_plan,
            retrieval_status="completed" if research_brief else "pending",
            image_status="completed",
            summary_status="completed",
            research_brief=research_brief,
            image_count=len(image_response.images),
        )
        self.trace_store.complete_run(
            run_id,
            output=assistant_message,
            model_used=model_used,
            tokens_used=tokens_used,
            skills_used=skills_used,
        )
        events = self._snapshot_run_events(run_id)
        self._schedule_memory_postprocess(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=assistant_message,
            new_messages=new_messages,
            run_id=run_id,
        )
        return ChatResponse(
            conversation_id=request.conversation_id,
            response=assistant_message,
            skills_used=skills_used,
            citations=research_citations,
            plan=plan_infos or (research_plan if research_plan else None),
            model_used=model_used,
            tokens_used=tokens_used,
            agent_id=agent_id,
            role_id=role_id,
            runtime=runtime,
            run_id=run_id,
            events=events,
            memory_context=role_context.records,
            memory_updates=[],
        )

    async def process(
        self,
        request: ChatRequest,
        on_token: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> ChatResponse:
        agent_id = request.agent_id or "general_assistant"
        request = self._sanitize_request_modes(request, agent_id)
        agent_info = get_agent(agent_id)
        runtime = agent_info.runtime if agent_info else "unknown"
        disabled_tool_names = self._disabled_tool_names(request)
        run = self.trace_store.start_run(
            conversation_id=request.conversation_id,
            user_id=self._user_id(request),
            input_text=request.message,
            agent_id=agent_id,
            runtime=runtime,
            run_id=request.run_id,
        )

        if agent_info is None:
            error_msg = f"Unknown agent: {agent_id}"
            self.trace_store.fail_run(
                run.run_id,
                error_message=error_msg,
                error_type="unknown_agent",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run.run_id) or run
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="unknown_agent",
                agent_id=agent_id,
                role_id=request.role_id,
                runtime=runtime,
                run_id=run.run_id,
                events=latest_run.events,
            )

        if agent_id == RESEARCH_AGENT_ID:
            error_msg = (
                "Deep Research 只能在 Super Chat 勾选“深度研究”模式后启动。"
                "请回到 Super Chat，打开深度研究模式，先发送研究问题生成计划，确认后再回复 `/start`。"
            )
            self.trace_store.fail_run(
                run.run_id,
                error_message=error_msg,
                error_type="workflow_mode_required",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run.run_id) or run
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="workflow_mode_required",
                agent_id=agent_id,
                role_id=request.role_id,
                runtime=runtime,
                run_id=run.run_id,
                events=latest_run.events,
            )

        if agent_id in AGENT_TOOL_IDS and agent_id in disabled_tool_names:
            error_msg = f"Feature '{agent_id}' is disabled for this user."
            self.trace_store.fail_run(
                run.run_id,
                error_message=error_msg,
                error_type="tool_disabled",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run.run_id) or run
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="tool_disabled",
                agent_id=agent_id,
                role_id=request.role_id,
                runtime=runtime,
                run_id=run.run_id,
                events=latest_run.events,
            )

        if not agent_info.enabled:
            error_msg = (
                f"Agent '{agent_id}' is registered but not enabled. "
                + str(agent_info.metadata.get("dependency_hint") or "")
            ).strip()
            self.trace_store.fail_run(
                run.run_id,
                error_message=error_msg,
                error_type="agent_disabled",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run.run_id) or run
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="agent_disabled",
                agent_id=agent_id,
                role_id=request.role_id,
                runtime=runtime,
                run_id=run.run_id,
                events=latest_run.events,
            )

        if agent_info.runtime != "self":
            error_msg = (
                f"Agent '{agent_id}' uses runtime '{agent_info.runtime}', "
                "which is registered for experiments but not wired to chat yet."
            )
            self.trace_store.fail_run(
                run.run_id,
                error_message=error_msg,
                error_type="runtime_not_implemented",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run.run_id) or run
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="runtime_not_implemented",
                agent_id=agent_id,
                role_id=request.role_id,
                runtime=runtime,
                run_id=run.run_id,
                events=latest_run.events,
            )

        role_id = self._resolve_role_id(request, agent_info.metadata)
        role_context = self.role_memory.get_context(
            role_id=role_id,
            user_id=self._user_id(request),
            agent_id=agent_id,
            query=self._memory_retrieval_query(request),
        )
        if role_context is None or not role_context.role.enabled:
            error_msg = f"Unknown or disabled role: {role_id}"
            self.trace_store.fail_run(
                run.run_id,
                error_message=error_msg,
                error_type="unknown_role",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run.run_id) or run
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="unknown_role",
                agent_id=agent_id,
                role_id=role_id,
                runtime=runtime,
                run_id=run.run_id,
                events=latest_run.events,
            )
        role_context = self._apply_memory_read_policy(request, role_context)

        entry_history = self.memory.get(self._conversation_memory_id(request))
        self._append_agent_input_received_trace(
            run_id=run.run_id,
            request=request,
            agent_id=agent_id,
            history=entry_history,
        )

        if self._is_deep_research_command_attempt(request, agent_id):
            error_msg = (
                "Deep Research 不再通过 `/agent` 命令或普通 Agent tool 启动。"
                "请在 Super Chat 勾选“深度研究”模式后发送研究问题；生成计划后，再在同一模式下回复 `/start`。"
            )
            self.trace_store.append_event(
                run.run_id,
                type="agent.command.rejected",
                status="error",
                title="Deep Research command rejected",
                payload={
                    "target_agent_id": RESEARCH_AGENT_ID,
                    "reason": "workflow_mode_required",
                    "required_agent_id": SUPER_CHAT_AGENT_ID,
                    "required_mode_id": DEEP_RESEARCH_MODE_ID,
                    "original_message": request.message,
                },
            )
            self.trace_store.fail_run(
                run.run_id,
                error_message=error_msg,
                error_type="workflow_mode_required",
                output=error_msg,
            )
            latest_run = self.trace_store.get_run(run.run_id) or run
            return ChatResponse(
                conversation_id=request.conversation_id,
                response=error_msg,
                skills_used=[],
                plan=None,
                model_used="",
                tokens_used={},
                error_type="workflow_mode_required",
                agent_id=RESEARCH_AGENT_ID,
                role_id=role_id,
                runtime=runtime,
                run_id=run.run_id,
                events=latest_run.events,
                memory_context=role_context.records,
            )

        agent_command_route = self._parse_agent_command_protocol(request, agent_id)
        if agent_command_route:
            target_agent = get_agent(str(agent_command_route["target_agent_id"]))
            target_agent_id = str(agent_command_route["target_agent_id"])
            if target_agent_id in disabled_tool_names:
                error_msg = f"Feature '{target_agent_id}' is disabled for this user."
                self.trace_store.fail_run(
                    run.run_id,
                    error_message=error_msg,
                    error_type="tool_disabled",
                    output=error_msg,
                )
                latest_run = self.trace_store.get_run(run.run_id) or run
                return ChatResponse(
                    conversation_id=request.conversation_id,
                    response=error_msg,
                    skills_used=[],
                    plan=None,
                    model_used="",
                    tokens_used={},
                    error_type="tool_disabled",
                    agent_id=target_agent_id,
                    role_id=role_id,
                    runtime="self",
                    run_id=run.run_id,
                    events=latest_run.events,
                    memory_context=role_context.records,
                )
            if target_agent is None:
                error_msg = f"Unknown agent: {agent_command_route['target_agent_id']}"
                self.trace_store.fail_run(
                    run.run_id,
                    error_message=error_msg,
                    error_type="unknown_agent",
                    output=error_msg,
                )
                latest_run = self.trace_store.get_run(run.run_id) or run
                return ChatResponse(
                    conversation_id=request.conversation_id,
                    response=error_msg,
                    skills_used=[],
                    plan=None,
                    model_used="",
                    tokens_used={},
                    error_type="unknown_agent",
                    agent_id=str(agent_command_route["target_agent_id"]),
                    role_id=role_id,
                    runtime="unknown",
                    run_id=run.run_id,
                    events=latest_run.events,
                    memory_context=role_context.records,
                )

            self._append_agent_command_route_trace(run.run_id, agent_command_route)
            command_request = request.model_copy(
                update={
                    "agent_id": target_agent.id,
                    "message": str(agent_command_route["command_text"]),
                    "mode_ids": [],
                    "mode_prompts": [],
                }
            )
            return await self._process_target_agent(
                request=command_request,
                target_agent=target_agent,
                run_id=run.run_id,
                source_role_context=role_context,
                delegation_trace={
                    "source_agent_id": agent_id,
                    "target_agent_id": target_agent.id,
                    "reason": "command_protocol",
                    "forced": True,
                    "mode_ids": request.mode_ids,
                    "protocol_version": agent_command_route["protocol_version"],
                    "target_alias": agent_command_route["target_alias"],
                    "command": agent_command_route["command_text"],
                    "original_message": agent_command_route["original_message"],
                },
            )

        should_delegate_research, research_reason, forced_research = self._should_delegate_to_deep_research(
            request,
            agent_id,
        )
        if should_delegate_research:
            target_agent = get_agent(RESEARCH_AGENT_ID)
            if RESEARCH_AGENT_ID in disabled_tool_names:
                error_msg = "Deep Research Agent is disabled for this user."
                self.trace_store.fail_run(
                    run.run_id,
                    error_message=error_msg,
                    error_type="tool_disabled",
                    output=error_msg,
                )
                latest_run = self.trace_store.get_run(run.run_id) or run
                return ChatResponse(
                    conversation_id=request.conversation_id,
                    response=error_msg,
                    skills_used=[],
                    plan=None,
                    model_used="",
                    tokens_used={},
                    error_type="tool_disabled",
                    agent_id=agent_id,
                    role_id=role_id,
                    runtime=runtime,
                    run_id=run.run_id,
                    events=latest_run.events,
                    memory_context=role_context.records,
                )
            if target_agent is None or not target_agent.enabled or target_agent.runtime != "self":
                error_msg = "Deep Research Agent 当前不可用，无法执行深度研究。"
                self.trace_store.fail_run(
                    run.run_id,
                    error_message=error_msg,
                    error_type="agent_disabled",
                    output=error_msg,
                )
                latest_run = self.trace_store.get_run(run.run_id) or run
                return ChatResponse(
                    conversation_id=request.conversation_id,
                    response=error_msg,
                    skills_used=[],
                    plan=None,
                    model_used="",
                    tokens_used={},
                    error_type="agent_disabled",
                    agent_id=agent_id,
                    role_id=role_id,
                    runtime=runtime,
                    run_id=run.run_id,
                    events=latest_run.events,
                    memory_context=role_context.records,
                )
            research_request = request.model_copy(update={"agent_id": target_agent.id})
            return await self._process_target_agent(
                request=research_request,
                target_agent=target_agent,
                run_id=run.run_id,
                source_role_context=role_context,
                delegation_trace={
                    "source_agent_id": agent_id,
                    "target_agent_id": target_agent.id,
                    "reason": research_reason,
                    "forced": forced_research,
                    "mode_ids": request.mode_ids,
                },
            )

        if agent_id == AIGC_AGENT_ID:
            return await self._process_image_generation(
                request=request,
                agent_id=agent_id,
                role_id=role_id,
                role_context=role_context,
                run_id=run.run_id,
                runtime=runtime,
            )

        if agent_id == WEIGHT_LOSS_AGENT_ID:
            return await self._process_weight_loss(
                request=request,
                agent_id=agent_id,
                role_id=role_id,
                role_context=role_context,
                run_id=run.run_id,
                runtime=runtime,
            )

        if agent_id == RESEARCH_AGENT_ID:
            return await self._process_deep_research(
                request=request,
                agent_id=agent_id,
                role_id=role_id,
                role_context=role_context,
                run_id=run.run_id,
                runtime=runtime,
            )

        try:
            provider = self._get_provider(request.model_preference)
        except Exception as e:
            logger.exception("Provider initialization failed")
            error_msg = str(e)
            self.trace_store.append_event(
                run.run_id,
                type="model.failed",
                status="error",
                title="Provider initialization failed",
                payload={"error_message": error_msg},
            )
            self.trace_store.fail_run(
                run.run_id,
                error_message=error_msg,
                error_type="provider_error",
                output=error_msg,
            )
            raise

        tools = self._tool_definitions_for_agent(agent_id, disabled_tool_names)
        if (
            agent_id == SUPER_CHAT_AGENT_ID
            and any(tool.name == "search" for tool in tools)
            and self._super_chat_drive_task_without_explicit_retrieval(request)
        ):
            tools = [tool for tool in tools if tool.name != "search"]
            self.trace_store.append_event(
                run.run_id,
                type="tools.filtered",
                status="completed",
                title="Search disabled for drive task",
                payload={
                    "disabled_tools": ["search"],
                    "reason": "drive_task_without_explicit_retrieval",
                    "current_request_preview": (request.message or "")[:300],
                },
            )
        agent_loop_enabled = self._agent_loop_mode_enabled(request, agent_id)
        workflow_name = AGENT_LOOP_MODE_ID if agent_loop_enabled else GENERIC_TOOL_LOOP_WORKFLOW
        workflow_node = "main_loop" if agent_loop_enabled else ""
        workflow_source = self._agent_loop_workflow_source(request, agent_id)
        legacy_workflow = GENERIC_TOOL_LOOP_WORKFLOW if agent_loop_enabled else ""
        workflow_started: float | None = None
        workflow_node_started: float | None = None

        # Build messages
        conversation_context = self.memory.get_context(self._conversation_memory_id(request))
        history = conversation_context.messages if request.memory_enabled else []
        short_term_summary = conversation_context.summary if request.memory_enabled else ""
        context_blocks_for_model = self._context_blocks_for_model(
            request.context_blocks,
            history=history,
        )
        tool_names = [tool.name for tool in tools]
        allowed_tool_names = set(tool_names)
        prompt_sources = self._build_system_prompt_parts(
            role_context,
            request.mode_prompts,
            context_blocks_for_model,
            drive_context=request.drive_context,
            agent_id=agent_id,
            tool_names=tool_names,
            short_term_summary=short_term_summary,
        )
        system_prompt = self._render_prompt_parts(prompt_sources)
        prompt_cache = self._build_prompt_cache_options(
            request=request,
            agent_id=agent_id,
            role_id=role_id,
            prompt_sources=prompt_sources,
            tool_names=tool_names,
        )
        messages = [
            LLMMessage(
                role="system",
                content=system_prompt,
            )
        ]
        messages.extend(history)
        messages.append(LLMMessage(role="user", content=request.message))
        self.trace_store.append_event(
            run.run_id,
            type="memory.loaded",
            status="completed",
            title="Role memory loaded",
            payload=self._memory_loaded_payload(
                role_id=role_id,
                user_id=self._user_id(request),
                role_context=role_context,
            ),
        )
        self._append_context_trace(
            run_id=run.run_id,
            role_id=role_id,
            role_context=role_context,
            messages=messages,
            tools_count=len(tools),
            tool_names=tool_names,
            mode_ids=request.mode_ids,
            mode_prompts=request.mode_prompts,
            context_blocks=context_blocks_for_model,
            short_term_summary=short_term_summary,
            tools=tools,
            prompt_sources=prompt_sources,
            final_model_request={
                "messages": [self._trace_message(message) for message in messages],
                "tools": [tool.model_dump(mode="json") for tool in tools],
                "tool_choice": "auto" if tools else "none",
                "model_preference": request.model_preference,
                "temperature": "provider_default",
                "prompt_cache": prompt_cache.model_dump(mode="json"),
                "workflow": workflow_name,
                "workflow_source": workflow_source,
                **({"legacy_workflow": legacy_workflow} if legacy_workflow else {}),
                "workflow_nodes": [workflow_node] if agent_loop_enabled else [],
                "budgets": {
                    "max_model_rounds": MAX_MODEL_ROUNDS,
                    "max_tool_calls": MAX_TOOL_CALLS,
                    "max_failed_tool_calls": MAX_FAILED_TOOL_CALLS,
                },
                "trace_policy": (
                    "main loop boundary plus raw model/tool/agent events"
                    if agent_loop_enabled
                    else "raw generic tool loop events"
                ),
            },
        )
        if agent_loop_enabled:
            workflow_started = perf_counter()
            workflow_node_started = perf_counter()
            self._append_workflow_event(
                run.run_id,
                event="workflow.started",
                workflow=workflow_name,
                status="running",
                title="Workflow agent_loop started",
                payload={
                    "mode_ids": request.mode_ids,
                    "nodes": [workflow_node],
                    "loop": "model_function_call",
                    "workflow_source": workflow_source,
                    "legacy_workflow": legacy_workflow,
                    "max_rounds": MAX_MODEL_ROUNDS,
                    "max_model_rounds": MAX_MODEL_ROUNDS,
                    "max_tool_calls": MAX_TOOL_CALLS,
                    "max_failed_tool_calls": MAX_FAILED_TOOL_CALLS,
                    "tool_names": tool_names,
                    "node_policy": "main_loop is a boundary; raw model/tool/agent events remain visible",
                },
            )
            self._append_workflow_event(
                run.run_id,
                event="workflow.node.started",
                workflow=workflow_name,
                node=workflow_node,
                status="running",
                title="Workflow node main_loop started",
                payload={
                    "mode_ids": request.mode_ids,
                    "loop": "model_function_call",
                    "workflow_source": workflow_source,
                    "legacy_workflow": legacy_workflow,
                    "max_rounds": MAX_MODEL_ROUNDS,
                    "max_model_rounds": MAX_MODEL_ROUNDS,
                    "max_tool_calls": MAX_TOOL_CALLS,
                    "max_failed_tool_calls": MAX_FAILED_TOOL_CALLS,
                    "tool_names": tool_names,
                },
            )

        # Track skill usage
        skills_used: list[str] = []
        plan: list[SkillCallInfo] = []
        citations: list[Citation] = []
        artifacts: list[ChatArtifact] = []
        citation_urls: set[str] = set()
        all_new_messages: list[LLMMessage] = [
            LLMMessage(role="user", content=request.message)
        ]

        # Tool-use loop
        response = None
        max_rounds_reached = False
        budget_exhausted = False
        budget_reason = ""
        budget_error_type = ""
        budget_finalization_status = ""
        model_rounds_used = 0
        tool_call_count = 0
        failed_tool_call_count = 0
        auto_search_forced = False
        for round_index in range(MAX_MODEL_ROUNDS):
            model_rounds_used = round_index + 1
            model_started = perf_counter()
            stream_final_answer = (
                on_token is not None
                and any(message.role == "tool" for message in messages)
                and getattr(provider, "disable_stream_after_tools", False) is not True
            )
            model_started_payload = {
                "round": round_index + 1,
                "message_count": len(messages),
                "tools_count": len(tools),
                "model_preference": request.model_preference,
                "streaming": stream_final_answer,
                "prompt_cache": prompt_cache.model_dump(mode="json"),
            }
            if agent_loop_enabled:
                model_started_payload.update(
                    {
                        "workflow": workflow_name,
                        "workflow_node": workflow_node,
                        "workflow_source": workflow_source,
                        "legacy_workflow": legacy_workflow,
                    }
                )
            self.trace_store.append_event(
                run.run_id,
                type="model.started",
                status="running",
                title=f"Model call {round_index + 1}",
                payload=model_started_payload,
            )
            try:
                if stream_final_answer:
                    response = await self._chat_stream_response_with_retry(
                        provider,
                        request=request,
                        run_id=run.run_id,
                        messages=messages,
                        tools=None,
                        on_token=on_token,
                        cache=prompt_cache,
                        retry_context=model_started_payload,
                    )
                else:
                    response = await self._chat_with_retry(
                        provider,
                        request=request,
                        run_id=run.run_id,
                        messages=messages,
                        tools=tools,
                        cache=prompt_cache,
                        retry_context=model_started_payload,
                    )
            except RateLimitError as e:
                logger.warning(f"Rate limit hit: {e}")
                error_msg = str(e)
                duration_ms = int((perf_counter() - model_started) * 1000)
                if agent_loop_enabled:
                    self._append_workflow_event(
                        run.run_id,
                        event="workflow.node.failed",
                        workflow=workflow_name,
                        node=workflow_node,
                        status="error",
                        title="Workflow node main_loop failed",
                        payload={
                            "round": round_index + 1,
                            "error_type": "rate_limit",
                            "error_message": error_msg,
                            "workflow_source": workflow_source,
                            "legacy_workflow": legacy_workflow,
                        },
                        duration_ms=(
                            int((perf_counter() - workflow_node_started) * 1000)
                            if isinstance(workflow_node_started, (int, float))
                            else None
                        ),
                    )
                    self._append_workflow_event(
                        run.run_id,
                        event="workflow.failed",
                        workflow=workflow_name,
                        status="error",
                        title="Workflow agent_loop failed",
                        payload={
                            "error_type": "rate_limit",
                            "error_message": error_msg,
                            "workflow_source": workflow_source,
                            "legacy_workflow": legacy_workflow,
                        },
                        duration_ms=(
                            int((perf_counter() - workflow_started) * 1000)
                            if isinstance(workflow_started, (int, float))
                            else None
                        ),
                    )
                self.trace_store.append_event(
                    run.run_id,
                    type="model.failed",
                    status="error",
                    title="Model rate limited",
                    payload={
                        "provider": e.provider,
                        "retry_after": e.retry_after,
                        "error_message": error_msg,
                    },
                    duration_ms=duration_ms,
                )
                all_new_messages.append(
                    LLMMessage(role="assistant", content=error_msg)
                )
                self._add_conversation_memory(request, all_new_messages)
                self.trace_store.fail_run(
                    run.run_id,
                    error_message=error_msg,
                    error_type="rate_limit",
                    output=error_msg,
                )
                latest_run = self.trace_store.get_run(run.run_id) or run
                return ChatResponse(
                    conversation_id=request.conversation_id,
                    response=error_msg,
                    skills_used=[],
                    plan=None,
                    model_used=getattr(provider, "model", ""),
                    tokens_used={},
                    error_type="rate_limit",
                    agent_id=agent_id,
                    role_id=role_id,
                    runtime=runtime,
                    run_id=run.run_id,
                    events=latest_run.events,
                    memory_context=role_context.records,
                )
            except Exception as e:
                logger.exception("Model call failed")
                error_msg = str(e)
                duration_ms = int((perf_counter() - model_started) * 1000)
                self.trace_store.append_event(
                    run.run_id,
                    type="model.failed",
                    status="error",
                    title="Model call failed",
                    payload={"error_message": error_msg},
                    duration_ms=duration_ms,
                )
                fallback_content = self._fallback_after_model_error_with_tool_results(
                    all_new_messages,
                    error_message=error_msg,
                )
                if fallback_content:
                    all_new_messages.append(LLMMessage(role="assistant", content=fallback_content))
                    self._add_conversation_memory(request, all_new_messages)
                    unique_skills = list(dict.fromkeys(skills_used))
                    if agent_loop_enabled:
                        self._append_workflow_event(
                            run.run_id,
                            event="workflow.node.completed",
                            workflow=workflow_name,
                            node=workflow_node,
                            status="partial",
                            title="Workflow node main_loop completed with tool-result fallback",
                            payload={
                                "result": "tool_result_fallback",
                                "response_status": "partial_tool_result_fallback",
                                "error_type": "model_error_after_tool_results",
                                "error_message": error_msg,
                                "workflow_source": workflow_source,
                                "legacy_workflow": legacy_workflow,
                                "skills_used": unique_skills,
                                "citation_count": len(citations),
                                "rounds": len([message for message in messages if message.role == "assistant"]),
                                "tool_call_count": tool_call_count,
                                "failed_tool_call_count": failed_tool_call_count,
                            },
                            duration_ms=(
                                int((perf_counter() - workflow_node_started) * 1000)
                                if isinstance(workflow_node_started, (int, float))
                                else None
                            ),
                        )
                        self._append_workflow_event(
                            run.run_id,
                            event="workflow.completed",
                            workflow=workflow_name,
                            status="partial",
                            title="Workflow agent_loop completed with tool-result fallback",
                            payload={
                                "result": "tool_result_fallback",
                                "response_status": "partial_tool_result_fallback",
                                "error_type": "model_error_after_tool_results",
                                "error_message": error_msg,
                                "workflow_source": workflow_source,
                                "legacy_workflow": legacy_workflow,
                                "skills_used": unique_skills,
                                "citation_count": len(citations),
                            },
                            duration_ms=(
                                int((perf_counter() - workflow_started) * 1000)
                                if isinstance(workflow_started, (int, float))
                                else None
                            ),
                        )
                    self.trace_store.partial_run(
                        run.run_id,
                        output=fallback_content,
                        error_type="model_error_after_tool_results",
                        error_message=error_msg,
                        model_used=getattr(provider, "model", ""),
                        tokens_used={},
                        skills_used=unique_skills,
                        artifacts=[artifact.model_dump(mode="json") for artifact in artifacts],
                    )
                    events = self._snapshot_run_events(run.run_id)
                    return ChatResponse(
                        conversation_id=request.conversation_id,
                        response=fallback_content,
                        skills_used=unique_skills,
                        citations=citations,
                        artifacts=artifacts,
                        plan=plan if plan else None,
                        model_used=getattr(provider, "model", ""),
                        tokens_used={},
                        agent_id=agent_id,
                        role_id=role_id,
                        runtime=runtime,
                        run_id=run.run_id,
                        events=events,
                        memory_context=role_context.records,
                        memory_updates=[],
                    )
                if agent_loop_enabled:
                    self._append_workflow_event(
                        run.run_id,
                        event="workflow.node.failed",
                        workflow=workflow_name,
                        node=workflow_node,
                        status="error",
                        title="Workflow node main_loop failed",
                        payload={
                            "round": round_index + 1,
                            "error_type": "model_error",
                            "error_message": error_msg,
                            "workflow_source": workflow_source,
                            "legacy_workflow": legacy_workflow,
                        },
                        duration_ms=(
                            int((perf_counter() - workflow_node_started) * 1000)
                            if isinstance(workflow_node_started, (int, float))
                            else None
                        ),
                    )
                    self._append_workflow_event(
                        run.run_id,
                        event="workflow.failed",
                        workflow=workflow_name,
                        status="error",
                        title="Workflow agent_loop failed",
                        payload={
                            "error_type": "model_error",
                            "error_message": error_msg,
                            "workflow_source": workflow_source,
                            "legacy_workflow": legacy_workflow,
                        },
                        duration_ms=(
                            int((perf_counter() - workflow_started) * 1000)
                            if isinstance(workflow_started, (int, float))
                            else None
                        ),
                    )
                self.trace_store.fail_run(
                    run.run_id,
                    error_message=error_msg,
                    error_type="model_error",
                    output=error_msg,
                )
                raise

            model_duration_ms = int((perf_counter() - model_started) * 1000)
            model_completed_payload = {
                "round": round_index + 1,
                "model": response.model,
                "usage": response.usage,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name}
                    for tc in response.tool_calls
                ],
                "content_preview": response.content[:300],
            }
            if agent_loop_enabled:
                model_completed_payload.update(
                    {
                        "workflow": workflow_name,
                        "workflow_node": workflow_node,
                        "workflow_source": workflow_source,
                        "legacy_workflow": legacy_workflow,
                    }
                )
            self.trace_store.append_event(
                run.run_id,
                type="model.completed",
                status="completed",
                title=f"Model call {round_index + 1} completed",
                payload=model_completed_payload,
                duration_ms=model_duration_ms,
            )

            if not response.tool_calls:
                if (
                    agent_id == SUPER_CHAT_AGENT_ID
                    and not auto_search_forced
                    and tool_call_count == 0
                    and self._super_chat_auto_retrieval_available(
                        request,
                        allowed_tool_names=allowed_tool_names,
                    )
                    and self._super_chat_auto_search_required(request)
                ):
                    auto_search_forced = True
                    forced_call = self._super_chat_auto_retrieval_call(
                        request,
                        round_index=round_index,
                        allowed_tool_names=allowed_tool_names,
                    )
                    self.trace_store.append_event(
                        run.run_id,
                        type="agent_loop.search_forced",
                        status="completed",
                        title=f"Super Chat auto {forced_call.name} inserted",
                        step_id=forced_call.id,
                        payload={
                            "reason": "model_returned_without_tool_call_for_retrieval_request",
                            "direct_answer_preview": response.content[:500],
                            "name": forced_call.name,
                            "arguments": forced_call.arguments,
                            "workflow": workflow_name,
                            "workflow_node": workflow_node,
                            "workflow_source": workflow_source,
                            "legacy_workflow": legacy_workflow,
                        },
                    )
                    response = LLMResponse(
                        content="",
                        tool_calls=[forced_call],
                        model=response.model,
                        usage=response.usage,
                    )
                else:
                    # No tool calls — we have the final answer
                    all_new_messages.append(
                        LLMMessage(role="assistant", content=response.content)
                    )
                    break

            if tool_call_count + len(response.tool_calls) > MAX_TOOL_CALLS:
                budget_exhausted = True
                budget_reason = "max_tool_calls_reached"
                budget_error_type = "max_tool_calls_reached"
                self.trace_store.append_event(
                    run.run_id,
                    type="agent_loop.budget_exhausted",
                    status="partial",
                    title="Tool call budget exhausted",
                    payload={
                        "reason": budget_reason,
                        "error_type": budget_error_type,
                        "tool_call_count": tool_call_count,
                        "requested_tool_calls": len(response.tool_calls),
                        "max_tool_calls": MAX_TOOL_CALLS,
                        "max_model_rounds": MAX_MODEL_ROUNDS,
                        "failed_tool_call_count": failed_tool_call_count,
                        "max_failed_tool_calls": MAX_FAILED_TOOL_CALLS,
                    },
                )
                break

            # Record assistant message with tool calls
            assistant_msg = LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ],
            )
            messages.append(assistant_msg)
            all_new_messages.append(assistant_msg)

            # Execute read-only web tools in bounded batches, then merge results in call order.
            tool_call_index = 0
            while tool_call_index < len(response.tool_calls):
                batch = self._parallel_read_only_tool_batch(response.tool_calls, tool_call_index)
                tool_call_index += len(batch)
                if len(batch) > 1:
                    executions = await asyncio.gather(
                        *[
                            self._execute_agent_loop_tool_call(
                                request=request,
                                role_context=role_context,
                                run_id=run.run_id,
                                tc=tc,
                                allowed_tool_names=allowed_tool_names,
                                agent_loop_enabled=agent_loop_enabled,
                                workflow_name=workflow_name,
                                workflow_node=workflow_node,
                                workflow_node_started=workflow_node_started,
                                workflow_started=workflow_started,
                                workflow_source=workflow_source,
                                legacy_workflow=legacy_workflow,
                                round_index=round_index,
                            )
                            for tc in batch
                        ]
                    )
                else:
                    executions = [
                        await self._execute_agent_loop_tool_call(
                            request=request,
                            role_context=role_context,
                            run_id=run.run_id,
                            tc=batch[0],
                            allowed_tool_names=allowed_tool_names,
                            agent_loop_enabled=agent_loop_enabled,
                            workflow_name=workflow_name,
                            workflow_node=workflow_node,
                            workflow_node_started=workflow_node_started,
                            workflow_started=workflow_started,
                            workflow_source=workflow_source,
                            legacy_workflow=legacy_workflow,
                            round_index=round_index,
                        )
                    ]

                for execution in executions:
                    tool_call_count += 1
                    if execution.status != "completed":
                        failed_tool_call_count += 1
                    self._finalize_agent_loop_tool_execution(
                        run_id=run.run_id,
                        execution=execution,
                        agent_loop_enabled=agent_loop_enabled,
                        workflow_name=workflow_name,
                        workflow_node=workflow_node,
                        workflow_source=workflow_source,
                        legacy_workflow=legacy_workflow,
                        skills_used=skills_used,
                        citations=citations,
                        citation_urls=citation_urls,
                        artifacts=artifacts,
                        plan=plan,
                        messages=messages,
                        all_new_messages=all_new_messages,
                    )
            if failed_tool_call_count >= MAX_FAILED_TOOL_CALLS:
                budget_exhausted = True
                budget_reason = "max_failed_tool_calls_reached"
                budget_error_type = "max_failed_tool_calls_reached"
                self.trace_store.append_event(
                    run.run_id,
                    type="agent_loop.budget_exhausted",
                    status="partial",
                    title="Failed tool call budget exhausted",
                    payload={
                        "reason": budget_reason,
                        "error_type": budget_error_type,
                        "tool_call_count": tool_call_count,
                        "max_tool_calls": MAX_TOOL_CALLS,
                        "failed_tool_call_count": failed_tool_call_count,
                        "max_failed_tool_calls": MAX_FAILED_TOOL_CALLS,
                        "max_model_rounds": MAX_MODEL_ROUNDS,
                    },
                )
                break
        else:
            max_rounds_reached = True
            budget_reason = "max_model_rounds_reached"
            budget_error_type = "max_tool_rounds_reached"
            self.trace_store.append_event(
                run.run_id,
                type="agent_loop.budget_exhausted",
                status="partial",
                title="Model round budget exhausted",
                payload={
                    "reason": budget_reason,
                    "error_type": budget_error_type,
                    "model_rounds": model_rounds_used,
                    "max_model_rounds": MAX_MODEL_ROUNDS,
                    "tool_call_count": tool_call_count,
                    "max_tool_calls": MAX_TOOL_CALLS,
                    "failed_tool_call_count": failed_tool_call_count,
                    "max_failed_tool_calls": MAX_FAILED_TOOL_CALLS,
                },
            )

        if max_rounds_reached or budget_exhausted:
            if not budget_reason:
                budget_reason = "tool_budget_exhausted"
            if not budget_error_type:
                budget_error_type = budget_reason
            response, budget_finalization_status = await self._finalize_after_tool_budget_exhausted(
                provider=provider,
                messages=messages,
                prompt_cache=prompt_cache,
                run_id=run.run_id,
                request=request,
                reason=budget_reason,
                error_type=budget_error_type,
                model_rounds=model_rounds_used,
                tool_call_count=tool_call_count,
                failed_tool_call_count=failed_tool_call_count,
                response=response,
                workflow_context=(
                    {
                        "workflow": workflow_name,
                        "workflow_node": workflow_node,
                        "workflow_source": workflow_source,
                        "legacy_workflow": legacy_workflow,
                    }
                    if agent_loop_enabled
                    else None
                ),
            )
            all_new_messages.append(LLMMessage(role="assistant", content=response.content))

        if agent_loop_enabled:
            workflow_result = "partial_summary" if (max_rounds_reached or budget_exhausted) else "final_answer"
            self._append_workflow_event(
                run.run_id,
                event="workflow.node.completed",
                workflow=workflow_name,
                node=workflow_node,
                status="partial" if (max_rounds_reached or budget_exhausted) else "completed",
                title="Workflow node main_loop completed",
                payload={
                    "result": workflow_result,
                    "response_status": "partial_summary" if (max_rounds_reached or budget_exhausted) else "completed",
                    "budget_reason": budget_reason,
                    "budget_error_type": budget_error_type,
                    "finalization_status": budget_finalization_status,
                    "workflow_source": workflow_source,
                    "legacy_workflow": legacy_workflow,
                    "skills_used": list(dict.fromkeys(skills_used)),
                    "citation_count": len(citations),
                    "rounds": len([message for message in messages if message.role == "assistant"]),
                    "tool_call_count": tool_call_count,
                    "failed_tool_call_count": failed_tool_call_count,
                },
                duration_ms=(
                    int((perf_counter() - workflow_node_started) * 1000)
                    if isinstance(workflow_node_started, (int, float))
                    else None
                ),
            )
            self._append_workflow_event(
                run.run_id,
                event="workflow.completed",
                workflow=workflow_name,
                status="partial" if (max_rounds_reached or budget_exhausted) else "completed",
                title="Workflow agent_loop completed",
                payload={
                    "result": workflow_result,
                    "response_status": "partial_summary" if (max_rounds_reached or budget_exhausted) else "completed",
                    "budget_reason": budget_reason,
                    "budget_error_type": budget_error_type,
                    "finalization_status": budget_finalization_status,
                    "workflow_source": workflow_source,
                    "legacy_workflow": legacy_workflow,
                    "skills_used": list(dict.fromkeys(skills_used)),
                    "citation_count": len(citations),
                },
                duration_ms=(
                    int((perf_counter() - workflow_started) * 1000)
                    if isinstance(workflow_started, (int, float))
                    else None
                ),
            )

        # Save to memory
        self._add_conversation_memory(request, all_new_messages)

        final_content = all_new_messages[-1].content
        if not isinstance(final_content, str):
            final_content = str(final_content)

        unique_skills = list(dict.fromkeys(skills_used))
        if not (max_rounds_reached or budget_exhausted):
            await self._maybe_auto_save_drive_report(
                request=request,
                agent_id=agent_id,
                provider=provider,
                run_id=run.run_id,
                tools=tools,
                final_content=final_content,
                skills_used=skills_used,
                citations=citations,
                artifacts=artifacts,
                plan=plan,
            )
            unique_skills = list(dict.fromkeys(skills_used))
        if max_rounds_reached or budget_exhausted:
            self.trace_store.partial_run(
                run.run_id,
                output=final_content,
                error_type=budget_error_type or "partial_summary",
                error_message=budget_reason or "tool_budget_exhausted",
                model_used=response.model if response else "",
                tokens_used=response.usage if response else {},
                skills_used=unique_skills,
                artifacts=[artifact.model_dump(mode="json") for artifact in artifacts],
            )
        else:
            self.trace_store.complete_run(
                run.run_id,
                output=final_content,
                model_used=response.model if response else "",
                tokens_used=response.usage if response else {},
                skills_used=unique_skills,
                artifacts=[artifact.model_dump(mode="json") for artifact in artifacts],
            )
        events = self._snapshot_run_events(run.run_id)
        self._schedule_memory_postprocess(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=final_content,
            new_messages=all_new_messages,
            run_id=run.run_id,
        )

        return ChatResponse(
            conversation_id=request.conversation_id,
            response=final_content,
            skills_used=unique_skills,
            citations=citations,
            artifacts=artifacts,
            plan=plan if plan else None,
            model_used=response.model if response else "",
            tokens_used=response.usage if response else {},
            agent_id=agent_id,
            role_id=role_id,
            runtime=runtime,
            run_id=run.run_id,
            events=events,
            memory_context=role_context.records,
            memory_updates=[],
        )
