from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
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
from agent.llm.base import LLMMessage, LLMProvider, LLMResponse, RateLimitError
from agent.llm.factory import create_provider
from agent.memory.conversation import ConversationMemory
from agent.memory.hooks import HeuristicMemoryHook, MemoryHook
from agent.memory.role_store import RoleMemoryStore
from agent.runtime.registry import get_agent, list_agents
from agent.schemas.agent import AgentInfo
from agent.schemas.aigc import IMAGE_ASPECT_RATIOS, GeneratedImage, ImageGenerationRequest, ImageGenerationResponse
from agent.schemas.chat import ChatAttachment, ChatRequest, ChatResponse, Citation, SkillCallInfo
from agent.schemas.handoff import (
    AGENT_INPUT_PROTOCOL_VERSION,
    AgentHandoffAttachment,
    AgentHandoffMessage,
    AgentHandoffPacket,
    AgentStageContext,
)
from agent.schemas.memory import MemoryContext, MemoryRecord
from agent.skills.registry import SkillRegistry
from agent.trace import TraceStore
from agent.weight_loss import WeightLossStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个可靠、友好的个人助手，可以使用已接入的工具/技能帮助用户完成任务。

当用户提出请求时，先判断是否有工具能提供更准确或更及时的帮助；需要时主动使用工具，不需要时直接基于已有上下文回答。

默认使用中文回答，除非用户明确要求英文或其他语言。回答要简洁、清楚、有帮助。使用工具后，简要说明你做了什么，并清晰呈现结果。"""

MAX_TOOL_ROUNDS = 12
SUPER_CHAT_AGENT_ID = "super_chat"
AIGC_AGENT_ID = "image_generation_v1"
WEIGHT_LOSS_AGENT_ID = "weight_loss_v1"
AIGC_FORCE_MODE_ID = "image_generation"
AIGC_REFINE_MODE_ID = "image_prompt_refine"
AIGC_RESEARCH_MODE_IDS = {"research", "plan"}
AIGC_RESEARCH_TOOL_ROUNDS = 8
AIGC_RESEARCH_SEARCH_LIMIT = 12
AIGC_RESEARCH_SEARCH_MAX_LIMIT = 20
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
WEIGHT_LOSS_ANALYSIS_MAX_ATTEMPTS = 5
WEIGHT_LOSS_ANALYSIS_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0, 20.0)


class AgentEngine:
    def __init__(
        self,
        skill_registry: SkillRegistry,
        trace_store: TraceStore | None = None,
        role_memory: RoleMemoryStore | None = None,
        memory_hook: MemoryHook | None = None,
        weight_loss_store: WeightLossStore | None = None,
    ):
        self.skill_registry = skill_registry
        self.memory = ConversationMemory()
        self.role_memory = role_memory or RoleMemoryStore()
        self.memory_hook = memory_hook or HeuristicMemoryHook()
        self.trace_store = trace_store or TraceStore()
        self.weight_loss_store = weight_loss_store or WeightLossStore()
        self._providers: dict[str, LLMProvider] = {}

    def clear_providers(self) -> None:
        """Clear cached providers so they get recreated with new config."""
        self._providers.clear()
        logger.info("Provider cache cleared")

    def _get_provider(self, name: str | None = None) -> LLMProvider:
        key = name or "default"
        if key not in self._providers:
            self._providers[key] = create_provider(name)
        return self._providers[key]

    def _user_id(self, request: ChatRequest) -> str:
        value = str(getattr(request, "user_id", None) or "0").strip()
        return value or "0"

    def _conversation_memory_id(self, request: ChatRequest) -> str:
        return f"user:{self._user_id(request)}:conversation:{request.conversation_id}"

    def _resolve_role_id(self, request: ChatRequest, agent_metadata: dict) -> str:
        if request.role_id:
            return request.role_id
        default_role_id = agent_metadata.get("default_role_id") or "default"
        return str(default_role_id)

    def _normalize_mode_prompts(self, prompts: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for prompt in prompts or []:
            text = " ".join(str(prompt).split())
            if not text or text in normalized:
                continue
            normalized.append(text[:1200])
            if len(normalized) >= 8:
                break
        return normalized

    def _normalize_context_blocks(self, blocks: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for block in blocks or []:
            text = str(block).replace("\r\n", "\n").replace("\r", "\n").strip()
            if not text:
                continue
            normalized.append(text[:24000])
            if len(normalized) >= 4:
                break
        return normalized

    def _agent_system_context(self, agent_id: str) -> str:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return ""
        return (
            "\n\n可用的专业 Agent：\n"
            f"- AI 生图 ({AIGC_AGENT_ID})：当用户要生成、绘制、设计或产出图片、照片、插画、海报、"
            "封面、头像、视觉概念或生图提示词时，使用这个 Agent。Super Chat 可以在识别到生图意图时"
            f"自动委派，也可以在用户启用 {AIGC_FORCE_MODE_ID} 模式时强制委派。"
            f"\n- 减肥 Agent ({WEIGHT_LOSS_AGENT_ID})：当用户上传食物图片、记录餐食热量、设置减脂目标、"
            "统计摄入/运动/热量缺口或请求减脂建议时，使用这个 Agent。"
            "\n\nAgent 命令协议：当用户在 Super Chat 中输入 `/agent <agent_id或别名> <命令>`、"
            "`/<agent别名> <命令>` 或 `/<agent别名>/<命令>` 时，必须按 agent_command.v1 "
            "转交给目标 Agent 执行，不要把它当作普通聊天。示例：`/agent weight_loss_v1 /today`、"
            "`/减肥 /history 7d`、`/weight_loss/history 7d`、`/生图 /generate 复古台灯海报`。"
        )

    def _build_system_prompt(
        self,
        role_context: MemoryContext,
        mode_prompts: list[str] | None = None,
        context_blocks: list[str] | None = None,
        agent_id: str = "general_assistant",
    ) -> str:
        current_time = datetime.now(ZoneInfo("Asia/Shanghai"))
        temporal_context = (
            "时间上下文：\n"
            f"- 当前日期/时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')} "
            "Asia/Shanghai (UTC+08:00).\n"
            f"- 当前年份：{current_time.year}。\n"
            "- 将以上日期视为今天。用户询问最新、当前、近期、投资、公司、新闻、价格、法律、日程等"
            "时效性信息时，如有搜索工具，应优先使用。\n"
            "- 如果搜索不可用或失败，要明确说明，不要把过期资料包装成最新信息。\n"
            "- 金融或投资问题只提供信息分析，不提供个性化投资建议。引用搜索结果中的来源 URL，区分"
            "搜索片段和已验证事实，并把薄弱或不熟悉的来源标为未验证。"
        )
        normalized_mode_prompts = self._normalize_mode_prompts(mode_prompts)
        mode_context = ""
        if normalized_mode_prompts:
            mode_context = (
                "\n\nSuper Chat 模式指令：\n"
                + "\n".join(f"- {prompt}" for prompt in normalized_mode_prompts)
            )
        normalized_context_blocks = self._normalize_context_blocks(context_blocks)
        turn_context = ""
        if normalized_context_blocks:
            turn_context = (
                "\n\n用户本轮提供的上下文：\n"
                + "\n\n---\n\n".join(normalized_context_blocks)
            )
        return (
            SYSTEM_PROMPT
            + "\n\n"
            + temporal_context
            + "\n\n"
            + role_context.rendered
            + self._agent_system_context(agent_id)
            + mode_context
            + turn_context
            + "\n\n记忆使用规则：\n"
            "- 把记忆视为可能出错的上下文，而不是绝对事实。\n"
            "- 除非用户询问，否则不要暴露隐藏的记忆实现细节。"
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

    def _trace_message(self, message: LLMMessage) -> dict:
        content = message.content
        return {
            "role": message.role,
            "content": content if isinstance(content, str) else content,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }

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
    ) -> None:
        normalized_context_blocks = self._normalize_context_blocks(context_blocks)
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
                "system_prompt": messages[0].content if messages else "",
                "role_context": role_context.rendered,
                "memory_records": [
                    {
                        "id": record.id,
                        "kind": record.kind,
                        "content": record.content,
                        "source": record.source,
                        "confidence": record.confidence,
                        "tags": record.tags,
                    }
                    for record in role_context.records
                ],
                "messages": [self._trace_message(message) for message in messages],
            },
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
            candidates = await self.memory_hook.review_turn(
                role=role_context.role,
                agent_id=agent_id,
                conversation_id=request.conversation_id,
                user_message=request.message,
                assistant_message=assistant_message,
                new_messages=new_messages,
            )
        except Exception as e:
            logger.exception("Memory hook failed")
            self.trace_store.append_event(
                run_id,
                type="memory.failed",
                status="error",
                title="Memory hook failed",
                payload={"error_message": str(e), "role_id": role_context.role.id},
            )
            return []

        updates: list[MemoryRecord] = []
        for candidate in candidates:
            try:
                updates.append(
                    self.role_memory.add_memory(
                        role_id=role_context.role.id,
                        user_id=self._user_id(request),
                        kind=candidate.kind,
                        content=candidate.content,
                        source="hook",
                        agent_id=candidate.agent_id,
                        confidence=candidate.confidence,
                        tags=candidate.tags,
                        metadata={
                            **candidate.metadata,
                            "reason": candidate.reason,
                            "conversation_id": request.conversation_id,
                            "agent_id": agent_id,
                        },
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
            },
        )
        return updates

    def _aigc_professional_mode_enabled(self, request: ChatRequest) -> bool:
        mode_ids = set(request.mode_ids or [])
        if AIGC_REFINE_MODE_ID in mode_ids:
            return True
        mode_text = "\n".join(request.mode_prompts or []).lower()
        return "专业修饰" in mode_text or "prompt refine" in mode_text

    def _aigc_force_mode_enabled(self, request: ChatRequest) -> bool:
        mode_ids = set(request.mode_ids or [])
        if AIGC_FORCE_MODE_ID in mode_ids or AIGC_AGENT_ID in mode_ids:
            return True
        mode_text = "\n".join(request.mode_prompts or []).lower()
        return "ai 生图" in mode_text or "image generation" in mode_text

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

    def _looks_like_image_generation_intent(self, request: ChatRequest) -> bool:
        text = " ".join(
            [
                request.message or "",
                " ".join(
                    attachment.content
                    for attachment in request.attachments
                    if attachment.kind in {"image", "audio", "video"} and attachment.content
                ),
            ]
        ).lower()
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return False

        direct_phrases = [
            "生图",
            "文生图",
            "图像生成",
            "生成图片",
            "生成一张图",
            "生成一张图片",
            "对比图",
            "关系图",
            "流程图",
            "架构图",
            "总结图",
            "信息图",
            "可视化图",
            "思维导图",
            "知识图谱",
            "学习路线图",
            "一图看懂",
            "出图",
            "ai作图",
            "ai 作图",
            "ai绘图",
            "ai 绘图",
            "generate an image",
            "generate image",
            "create an image",
            "text to image",
            "text-to-image",
        ]
        if any(phrase in normalized for phrase in direct_phrases):
            return True

        zh_pattern = (
            r"(生成|画|绘制|设计|做|制作|创建|出|产出|给我来|帮我来)"
            r".{0,16}"
            r"(图|图片|图像|画面|海报|封面|头像|插画|壁纸|视觉|logo|照片|产品图|宣传图|对比图|关系图|流程图|架构图|信息图|路线图|图谱)"
        )
        if re.search(zh_pattern, normalized):
            return True

        en_pattern = (
            r"\b(generate|create|make|draw|design|produce|render)\b"
            r".{0,40}"
            r"\b(image|picture|photo|poster|cover|avatar|illustration|wallpaper|visual|logo|banner)\b"
        )
        if re.search(en_pattern, normalized):
            return True

        return False

    def _should_delegate_to_aigc(self, request: ChatRequest, agent_id: str) -> tuple[bool, str, bool]:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return False, "", False
        forced = self._aigc_force_mode_enabled(request)
        if forced:
            return True, "mode", True
        if self._looks_like_image_generation_intent(request):
            return True, "intent", False
        return False, "", False

    def _looks_like_weight_loss_intent(self, request: ChatRequest) -> bool:
        text = " ".join(
            [
                request.message or "",
                " ".join(
                    attachment.content
                    for attachment in request.attachments
                    if attachment.content
                ),
            ]
        ).lower()
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return False

        direct_phrases = [
            "减肥",
            "减脂",
            "掉秤",
            "热量",
            "卡路里",
            "大卡",
            "千卡",
            "kcal",
            "calorie",
            "calories",
            "caloric deficit",
            "热量缺口",
            "摄入",
            "饮食记录",
            "食物图片",
            "这餐",
            "这一餐",
            "吃了",
            "早餐",
            "午餐",
            "晚餐",
            "加餐",
            "外卖",
            "维持热量",
            "tdee",
            "基础代谢",
            "bmr",
        ]
        profile_markers = [
            "身高",
            "体重",
            "目标体重",
            "年龄",
            "性别",
            "活动水平",
            "久坐",
            "轻度活动",
            "中度活动",
            "高强度",
        ]
        profile_action_markers = [
            "设置",
            "记录",
            "登记",
            "更新",
            "写入",
            "保存",
            "档案",
            "资料",
            "我的",
            "帮我",
        ]
        profile_update_intent = any(marker in normalized for marker in profile_markers) and (
            any(marker in normalized for marker in profile_action_markers)
            or any(marker in normalized for marker in ["减肥", "减脂", "tdee", "维持热量", "基础代谢"])
        )
        food_image = any(
            attachment.kind == "image"
            and (
                any(marker in normalized for marker in ["吃", "餐", "食物", "热量", "卡路里", "kcal", "减脂", "减肥"])
                or "food" in normalized
                or "meal" in normalized
                or "calorie" in normalized
            )
            for attachment in request.attachments
        )
        return food_image or profile_update_intent or any(phrase in normalized for phrase in direct_phrases)

    def _should_delegate_to_weight_loss(self, request: ChatRequest, agent_id: str) -> tuple[bool, str, bool]:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return False, "", False
        if self._looks_like_weight_loss_intent(request):
            return True, "intent", False
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
            and agent.runtime == "self"
            and bool((agent.metadata or {}).get("command_protocol"))
        ]

    def _parse_agent_command_protocol(self, request: ChatRequest, agent_id: str) -> dict[str, Any] | None:
        if agent_id != SUPER_CHAT_AGENT_ID:
            return None
        text = (request.message or "").strip()
        if not text.startswith("/"):
            return None

        explicit = re.match(r"^/(?:agent|agent:|a)\s+([^\s]+)\s+(.+)$", text, flags=re.IGNORECASE | re.DOTALL)
        if explicit:
            target_token = explicit.group(1).strip()
            command_text = explicit.group(2).strip()
        else:
            nested = re.match(r"^/([^\s/]+)/(.+)$", text, flags=re.DOTALL)
            if nested:
                target_token = nested.group(1).strip()
                command_text = nested.group(2).strip()
            else:
                implicit = re.match(r"^/([^\s/]+)\s+(.+)$", text, flags=re.DOTALL)
                if not implicit:
                    return None
                target_token = implicit.group(1).strip()
                command_text = implicit.group(2).strip()

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
            response = await provider.chat(messages, tools=None, temperature=0.1)
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
    ) -> dict[str, Any]:
        tools = self.skill_registry.get_tool_definitions()
        messages = self._build_aigc_research_messages(
            request=request,
            role_context=role_context,
            history=history,
            handoff_packet=handoff_packet,
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
            response = await provider.chat(messages, tools=tools, temperature=0.2)
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
                    payload={"name": tc.name, "arguments": tool_arguments},
                )
                skill = self.skill_registry.get(tc.name)
                if skill is None:
                    result_text = json.dumps({"error": f"Unknown skill: {tc.name}"})
                    status = "error"
                else:
                    try:
                        result = await skill.execute(**tool_arguments)
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
                        "arguments": tool_arguments,
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
        return any(
            block.lstrip().startswith(("Persisted conversation history", "持久化会话历史"))
            for block in context_blocks or []
        )

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
    ) -> list[LLMMessage]:
        current_time = datetime.now(ZoneInfo("Asia/Shanghai"))
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
            f"近期对话：\n{self._format_weight_loss_history(history)}\n\n"
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
            if re.search(r"(?:属于|意图|intent|用户.*反馈|用户.*咨询|用户.*描述)", text, flags=re.IGNORECASE):
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
        response = " ".join(str(analysis.get("assistant_response") or "").split())
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
        self.memory.add_many(self._conversation_memory_id(request), new_messages)
        memory_updates = await self._review_and_store_memories(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=assistant_message,
            new_messages=new_messages,
            run_id=run_id,
        )
        unique_skills = list(dict.fromkeys(skills_used))
        self.trace_store.complete_run(
            run_id,
            output=assistant_message,
            model_used=model_used,
            tokens_used=tokens_used or {},
            skills_used=unique_skills,
        )
        latest_run = self.trace_store.get_run(run_id)
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
            events=latest_run.events if latest_run else [],
            memory_context=role_context.records,
            memory_updates=memory_updates,
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
        history = self.memory.get(self._conversation_memory_id(request))
        starting_summary = self.weight_loss_store.summary(request.conversation_id, days=period_days, user_id=user_id)
        messages = self._build_weight_loss_messages(
            request=request,
            role_context=role_context,
            summary=starting_summary,
            history=history,
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
        self.memory.add_many(self._conversation_memory_id(request), new_messages)
        memory_updates = await self._review_and_store_memories(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=assistant_message,
            new_messages=new_messages,
            run_id=run_id,
        )
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
        latest_run = self.trace_store.get_run(run_id)
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
            events=latest_run.events if latest_run else [],
            memory_context=role_context.records,
            memory_updates=memory_updates,
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
                self.memory.add_many(self._conversation_memory_id(request), new_messages)
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

        history = self.memory.get(self._conversation_memory_id(request))
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
            payload={
                "role_id": role_id,
                "persona_count": len(role_context.persona_memories),
                "long_term_count": len(role_context.long_term_memories),
                "context_record_ids": [record.id for record in role_context.records],
            },
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
            review_response = await provider.chat(review_messages, tools=None, temperature=0.2)
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
            self.memory.add_many(self._conversation_memory_id(request), new_messages)
            memory_updates = await self._review_and_store_memories(
                request=request,
                agent_id=agent_id,
                role_context=role_context,
                assistant_message=assistant_message,
                new_messages=new_messages,
                run_id=run_id,
            )
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
            latest_run = self.trace_store.get_run(run_id)
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
                events=latest_run.events if latest_run else [],
                memory_context=role_context.records,
                memory_updates=memory_updates,
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
                self.memory.add_many(self._conversation_memory_id(request), new_messages)
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
        self.memory.add_many(self._conversation_memory_id(request), new_messages)
        memory_updates = await self._review_and_store_memories(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=assistant_message,
            new_messages=new_messages,
            run_id=run_id,
        )

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
        latest_run = self.trace_store.get_run(run_id)
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
            events=latest_run.events if latest_run else [],
            memory_context=role_context.records,
            memory_updates=memory_updates,
        )

    async def process(
        self,
        request: ChatRequest,
        on_token: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> ChatResponse:
        agent_id = request.agent_id or "general_assistant"
        agent_info = get_agent(agent_id)
        runtime = agent_info.runtime if agent_info else "unknown"
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

        entry_history = self.memory.get(self._conversation_memory_id(request))
        self._append_agent_input_received_trace(
            run_id=run.run_id,
            request=request,
            agent_id=agent_id,
            history=entry_history,
        )

        agent_command_route = self._parse_agent_command_protocol(request, agent_id)
        if agent_command_route:
            target_agent = get_agent(str(agent_command_route["target_agent_id"]))
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

        should_delegate, delegate_reason, forced_delegate = self._should_delegate_to_aigc(
            request,
            agent_id,
        )
        if should_delegate:
            target_agent = get_agent(AIGC_AGENT_ID)
            if target_agent is None or not target_agent.enabled or target_agent.runtime != "self":
                error_msg = "AI 生图 Agent 当前不可用，无法完成生图任务。"
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

            target_role_id = self._resolve_role_id(request, target_agent.metadata)
            target_role_context = self.role_memory.get_context(
                role_id=target_role_id,
                user_id=self._user_id(request),
                agent_id=AIGC_AGENT_ID,
            )
            if target_role_context is None or not target_role_context.role.enabled:
                error_msg = f"Unknown or disabled role: {target_role_id}"
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
                    agent_id=AIGC_AGENT_ID,
                    role_id=target_role_id,
                    runtime=target_agent.runtime,
                    run_id=run.run_id,
                    events=latest_run.events,
                    memory_context=role_context.records,
                )

            return await self._process_image_generation(
                request=request,
                agent_id=AIGC_AGENT_ID,
                role_id=target_role_id,
                role_context=target_role_context,
                run_id=run.run_id,
                runtime=target_agent.runtime,
                delegation_trace={
                    "source_agent_id": agent_id,
                    "target_agent_id": AIGC_AGENT_ID,
                    "reason": delegate_reason,
                    "forced": forced_delegate,
                    "mode_ids": request.mode_ids,
                },
            )

        should_delegate_weight_loss, weight_loss_reason, forced_weight_loss = self._should_delegate_to_weight_loss(
            request,
            agent_id,
        )
        if should_delegate_weight_loss:
            target_agent = get_agent(WEIGHT_LOSS_AGENT_ID)
            if target_agent is None or not target_agent.enabled or target_agent.runtime != "self":
                error_msg = "减肥 Agent 当前不可用，无法完成热量记录或缺口统计。"
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

            target_role_id = self._resolve_role_id(request, target_agent.metadata)
            target_role_context = self.role_memory.get_context(
                role_id=target_role_id,
                user_id=self._user_id(request),
                agent_id=WEIGHT_LOSS_AGENT_ID,
            )
            if target_role_context is None or not target_role_context.role.enabled:
                error_msg = f"Unknown or disabled role: {target_role_id}"
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
                    agent_id=WEIGHT_LOSS_AGENT_ID,
                    role_id=target_role_id,
                    runtime=target_agent.runtime,
                    run_id=run.run_id,
                    events=latest_run.events,
                    memory_context=role_context.records,
                )

            return await self._process_weight_loss(
                request=request,
                agent_id=WEIGHT_LOSS_AGENT_ID,
                role_id=target_role_id,
                role_context=target_role_context,
                run_id=run.run_id,
                runtime=target_agent.runtime,
                delegation_trace={
                    "source_agent_id": agent_id,
                    "target_agent_id": WEIGHT_LOSS_AGENT_ID,
                    "reason": weight_loss_reason,
                    "forced": forced_weight_loss,
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

        tools = self.skill_registry.get_tool_definitions()

        # Build messages
        history = self.memory.get(self._conversation_memory_id(request))
        messages = [
            LLMMessage(
                role="system",
                content=self._build_system_prompt(
                    role_context,
                    request.mode_prompts,
                    request.context_blocks,
                    agent_id=agent_id,
                ),
            )
        ]
        messages.extend(history)
        messages.append(LLMMessage(role="user", content=request.message))
        self.trace_store.append_event(
            run.run_id,
            type="memory.loaded",
            status="completed",
            title="Role memory loaded",
            payload={
                "role_id": role_id,
                "persona_count": len(role_context.persona_memories),
                "long_term_count": len(role_context.long_term_memories),
                "context_record_ids": [record.id for record in role_context.records],
            },
        )
        self._append_context_trace(
            run_id=run.run_id,
            role_id=role_id,
            role_context=role_context,
            messages=messages,
            tools_count=len(tools),
            tool_names=[tool.name for tool in tools],
            mode_ids=request.mode_ids,
            mode_prompts=request.mode_prompts,
            context_blocks=request.context_blocks,
        )

        # Track skill usage
        skills_used: list[str] = []
        plan: list[SkillCallInfo] = []
        citations: list[Citation] = []
        citation_urls: set[str] = set()
        all_new_messages: list[LLMMessage] = [
            LLMMessage(role="user", content=request.message)
        ]

        # Tool-use loop
        response = None
        for round_index in range(MAX_TOOL_ROUNDS):
            model_started = perf_counter()
            stream_final_answer = (
                on_token is not None
                and any(message.role == "tool" for message in messages)
                and getattr(provider, "disable_stream_after_tools", False) is not True
            )
            self.trace_store.append_event(
                run.run_id,
                type="model.started",
                status="running",
                title=f"Model call {round_index + 1}",
                payload={
                    "round": round_index + 1,
                    "message_count": len(messages),
                    "tools_count": len(tools),
                    "model_preference": request.model_preference,
                    "streaming": stream_final_answer,
                },
            )
            try:
                if stream_final_answer:
                    chunks: list[str] = []
                    async for token in provider.chat_stream(messages, tools=None):
                        chunks.append(token)
                        await self._emit_token(on_token, token)
                    response = LLMResponse(
                        content="".join(chunks),
                        tool_calls=[],
                        model=getattr(provider, "model", ""),
                        usage={},
                    )
                else:
                    response = await provider.chat(messages, tools=tools)
            except RateLimitError as e:
                logger.warning(f"Rate limit hit: {e}")
                error_msg = str(e)
                duration_ms = int((perf_counter() - model_started) * 1000)
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
                self.memory.add_many(self._conversation_memory_id(request), all_new_messages)
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
                self.trace_store.fail_run(
                    run.run_id,
                    error_message=error_msg,
                    error_type="model_error",
                    output=error_msg,
                )
                raise

            model_duration_ms = int((perf_counter() - model_started) * 1000)
            self.trace_store.append_event(
                run.run_id,
                type="model.completed",
                status="completed",
                title=f"Model call {round_index + 1} completed",
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
                duration_ms=model_duration_ms,
            )

            if not response.tool_calls:
                # No tool calls — we have the final answer
                all_new_messages.append(
                    LLMMessage(role="assistant", content=response.content)
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

            # Execute each tool call
            for tc in response.tool_calls:
                tool_started = perf_counter()
                self.trace_store.append_event(
                    run.run_id,
                    type="tool.started",
                    status="running",
                    title=f"Tool {tc.name}",
                    step_id=tc.id,
                    payload={"name": tc.name, "arguments": tc.arguments},
                )
                skill = self.skill_registry.get(tc.name)
                if skill is None:
                    result_text = json.dumps({"error": f"Unknown skill: {tc.name}"})
                    status = "error"
                else:
                    try:
                        result = await skill.execute(**tc.arguments)
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
                                new_citations = self._collect_search_citations(
                                    result_data=result.data,
                                    citations=citations,
                                    citation_urls=citation_urls,
                                )
                                if new_citations:
                                    self.trace_store.append_event(
                                        run.run_id,
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

                tool_duration_ms = int((perf_counter() - tool_started) * 1000)
                self.trace_store.append_event(
                    run.run_id,
                    type="tool.completed" if status == "completed" else "tool.failed",
                    status=status,
                    title=f"Tool {tc.name} {status}",
                    step_id=tc.id,
                    payload={
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "result_preview": result_text[:500],
                    },
                    duration_ms=tool_duration_ms,
                )

                plan.append(SkillCallInfo(
                    skill=tc.name,
                    action=str(tc.arguments),
                    status=status,
                    result_summary=result_text[:200],
                ))

                tool_msg = LLMMessage(
                    role="tool", content=result_text, tool_call_id=tc.id
                )
                messages.append(tool_msg)
                all_new_messages.append(tool_msg)
        else:
            # Exceeded max rounds — response is guaranteed non-None here
            # because the loop body always assigns it before checking tool_calls
            fallback_content = response.content if response else ""
            all_new_messages.append(
                LLMMessage(
                    role="assistant",
                    content="I've reached the maximum number of tool calls. Here's what I found so far: "
                    + fallback_content,
                )
            )

        # Save to memory
        self.memory.add_many(self._conversation_memory_id(request), all_new_messages)

        final_content = all_new_messages[-1].content
        if not isinstance(final_content, str):
            final_content = str(final_content)

        memory_updates = await self._review_and_store_memories(
            request=request,
            agent_id=agent_id,
            role_context=role_context,
            assistant_message=final_content,
            new_messages=all_new_messages,
            run_id=run.run_id,
        )

        unique_skills = list(dict.fromkeys(skills_used))
        self.trace_store.complete_run(
            run.run_id,
            output=final_content,
            model_used=response.model if response else "",
            tokens_used=response.usage if response else {},
            skills_used=unique_skills,
        )
        latest_run = self.trace_store.get_run(run.run_id) or run

        return ChatResponse(
            conversation_id=request.conversation_id,
            response=final_content,
            skills_used=unique_skills,
            citations=citations,
            plan=plan if plan else None,
            model_used=response.model if response else "",
            tokens_used=response.usage if response else {},
            agent_id=agent_id,
            role_id=role_id,
            runtime=runtime,
            run_id=run.run_id,
            events=latest_run.events,
            memory_context=role_context.records,
            memory_updates=memory_updates,
        )
