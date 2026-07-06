from __future__ import annotations

from agent.runtime.langgraph_runtime import is_available, missing_dependency_message
from agent.schemas.agent import AgentInfo


def list_agents() -> list[AgentInfo]:
    langgraph_available = is_available()
    return [
        AgentInfo(
            id="super_chat",
            name="Super Chat",
            description="具备意图识别的聊天入口。当前使用自研 self loop，可按任务委派给专业 Agent 并汇总结果。",
            runtime="self",
            framework="native",
            enabled=True,
            experimental=False,
            capabilities=[
                "chat",
                "tool_use",
                "role_memory",
                "intent_routing_planned",
                "summary_planned",
                "tracing",
            ],
            metadata={
                "entry_mode": "super_chat",
                "default_role_id": "default",
                "starter_prompt": "帮我判断这个任务应该由哪个 Agent 处理，并给出一个简洁结论：",
            },
        ),
        AgentInfo(
            id="general_assistant",
            name="General Assistant",
            description="基于本地 self runtime 和内置技能的默认助手。",
            runtime="self",
            framework="native",
            enabled=True,
            experimental=False,
            capabilities=[
                "chat",
                "tool_use",
                "conversation_memory",
                "role_memory",
                "memory_hook",
                "tracing",
            ],
            metadata={"default_role_id": "default"},
        ),
        AgentInfo(
            id="deep_research_v1",
            name="Deep Research",
            description="先产出研究计划大纲，用户确认后进行多轮检索、分步归纳并汇总研究报告。",
            runtime="self",
            framework="native",
            enabled=True,
            experimental=True,
            capabilities=[
                "deep_research",
                "research_planning",
                "multi_round_search",
                "source_synthesis",
                "report_generation",
                "tracing",
            ],
            metadata={
                "agent_type": "research",
                "implementation": "deep_research_v1",
                "default_role_id": "default",
                "starter_prompt": "请先给我一份研究计划大纲，主题是：",
                "input_protocol": "agent_input.v1",
                "execution_mode": "workflow_job",
                "entrypoint": "super_chat_mode_only",
                "super_chat_mode_id": "deep_research",
                "research_policy": {
                    "requires_plan_confirmation": True,
                    "target_result_count": 400,
                    "search_limit_per_query": 20,
                    "max_queries": 24,
                },
            },
        ),
        AgentInfo(
            id="langgraph_research",
            name="LangGraph Research",
            description="用于有状态研究工作流的实验性 LangGraph Agent 槽位。",
            runtime="langgraph",
            framework="langgraph",
            enabled=langgraph_available,
            experimental=True,
            capabilities=["state_graph", "checkpoint_ready", "tracing"],
            metadata={
                "available": langgraph_available,
                "dependency_hint": None
                if langgraph_available
                else missing_dependency_message(),
            },
        ),
        AgentInfo(
            id="image_generation_v1",
            name="AI 生图",
            description="对话优先的 AI 生图 Agent，支持 MiniMax 图片输出和提示词修饰。",
            runtime="self",
            framework="native",
            enabled=True,
            experimental=True,
            capabilities=[
                "aigc",
                "image_generation",
                "prompt_refine",
                "conversation_image_generation",
                "multimodal_input",
                "tracing",
            ],
            metadata={
                "agent_type": "aigc",
                "implementation": "image_generation_v1",
                "default_role_id": "default",
                "starter_prompt": "请直接帮我生成一张图片：",
                "supports_attachments": ["image", "audio", "video", "text"],
                "professional_mode_id": "image_prompt_refine",
                "input_protocol": "agent_input.v1",
                "legacy_input_field": "handoff",
                "command_protocol": {
                    "version": "agent_command.v1",
                    "aliases": [
                        "image",
                        "image-generation",
                        "image_generation",
                        "img",
                        "aigc",
                        "ai-image",
                        "生图",
                        "画图",
                        "AI生图",
                        "ai生图",
                    ],
                    "usage": "/agent image_generation_v1 /generate <提示词> 或 /生图 /refine <提示词>",
                    "commands": [
                        "/generate <提示词>",
                        "/refine <提示词>",
                        "/reference <提示词>",
                        "/help",
                    ],
                },
                "quick_actions": [
                    {
                        "id": "generate",
                        "label": {"zh": "直接生图", "en": "Generate"},
                        "description": {"zh": "输入提示词后直接生成图片", "en": "Generate from the prompt you enter"},
                        "query": "/generate ",
                    },
                    {
                        "id": "refine",
                        "label": {"zh": "专业修饰", "en": "Polish"},
                        "description": {"zh": "先补全画面提示词，再生成图片", "en": "Polish the prompt before generation"},
                        "query": "/refine ",
                    },
                    {
                        "id": "reference",
                        "label": {"zh": "参考素材", "en": "Reference"},
                        "description": {"zh": "结合上传素材生成新图片", "en": "Generate using uploaded references"},
                        "query": "/reference ",
                    },
                    {
                        "id": "help",
                        "label": {"zh": "命令帮助", "en": "Commands"},
                        "description": {"zh": "查看生图可用命令", "en": "Show image commands"},
                        "query": "/help",
                        "auto_send": True,
                    },
                ],
            },
        ),
        AgentInfo(
            id="weight_loss_v1",
            name="减肥 Agent",
            description="通过食物图片估算热量，记录饮食/运动和目标，并从数据库统计摄入、消耗与热量缺口。",
            runtime="self",
            framework="native",
            enabled=True,
            experimental=True,
            capabilities=[
                "chat",
                "multimodal_input",
                "food_image_calorie_estimation",
                "nutrition_log",
                "calorie_deficit_tracking",
                "database_persistence",
                "tracing",
            ],
            metadata={
                "agent_type": "wellness",
                "implementation": "weight_loss_v1",
                "default_role_id": "default",
                "starter_prompt": "请帮我估算这餐热量并记录到减脂数据库：",
                "supports_attachments": ["image", "text"],
                "input_protocol": "agent_input.v1",
                "command_protocol": {
                    "version": "agent_command.v1",
                    "aliases": ["weight_loss", "weight-loss", "wl", "减肥", "减脂"],
                    "usage": "/agent weight_loss_v1 /today 或 /减肥 /history 7d",
                    "commands": [
                        "/today",
                        "/history [7d|30d]",
                        "/goal <每日目标> <维持热量>",
                        "/profile",
                        "/help",
                    ],
                },
                "quick_actions": [
                    {
                        "id": "today",
                        "label": {"zh": "今日统计", "en": "Today"},
                        "description": {"zh": "查看今天摄入、运动和缺口", "en": "View today's intake, exercise, and deficit"},
                        "query": "/today",
                        "auto_send": True,
                    },
                    {
                        "id": "history",
                        "label": {"zh": "历史记录", "en": "History"},
                        "description": {"zh": "查看最近 7 天健康记录", "en": "View the last 7 days of health logs"},
                        "query": "/history 7d",
                        "auto_send": True,
                    },
                    {
                        "id": "goal",
                        "label": {"zh": "设置目标", "en": "Set goal"},
                        "description": {"zh": "设置每日目标、维持热量或体重", "en": "Set calorie goal, maintenance, or weight"},
                        "query": "/goal ",
                    },
                    {
                        "id": "profile",
                        "label": {"zh": "减脂档案", "en": "Profile"},
                        "description": {"zh": "查看当前身高、体重和目标", "en": "View current body metrics and goals"},
                        "query": "/profile",
                        "auto_send": True,
                    },
                    {
                        "id": "help",
                        "label": {"zh": "命令帮助", "en": "Commands"},
                        "description": {"zh": "查看可用命令", "en": "Show available commands"},
                        "query": "/help",
                        "auto_send": True,
                    },
                ],
            },
        ),
    ]


def get_agent(agent_id: str) -> AgentInfo | None:
    for agent in list_agents():
        if agent.id == agent_id:
            return agent
    return None
