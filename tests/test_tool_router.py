from agent.llm.base import ToolDefinition
from agent.skills.router import CORE_ALWAYS_ON_TOOL_NAMES, ToolRouter


def _tool(name: str, **metadata) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} drive capability",
        parameters={"type": "object", "properties": {}},
        metadata=metadata,
    )


def test_router_keeps_core_tools_and_caps_high_priority_dynamic_exposure():
    catalog = [
        _tool(name, always_on=True)
        for name in sorted(CORE_ALWAYS_ON_TOOL_NAMES)
    ] + [
        _tool(
            f"drive_action_{index}",
            domains=["drive"],
            routing_keywords=["网盘"],
        )
        for index in range(12)
    ]

    route = ToolRouter().route(catalog, query="整理我的网盘文件")
    names = {tool.name for tool in route.tools}

    assert CORE_ALWAYS_ON_TOOL_NAMES.issubset(names)
    assert len(route.tools) == len(CORE_ALWAYS_ON_TOOL_NAMES) + 3
    assert len(route.deferred_tools) == 9
    assert route.activated_domains == ["drive"]


def test_calculator_and_datetime_are_not_default_core_tools():
    catalog = [
        _tool("open_url", always_on=True),
        _tool("search", always_on=True),
        _tool("tool_search", always_on=True, discoverable=False),
        _tool("calculator", routing_keywords=["计算", "calculate"]),
        _tool("datetime", routing_keywords=["几点", "current time"]),
    ]
    router = ToolRouter()

    default_route = router.route(catalog, query="你好")
    calculation_route = router.route(catalog, query="calculate 42 * 17")
    time_route = router.route(catalog, query="上海现在几点")

    assert [tool.name for tool in default_route.tools] == [
        "open_url", "search", "tool_search",
    ]
    assert "calculator" in {tool.name for tool in calculation_route.tools}
    assert "datetime" in {tool.name for tool in time_route.tools}


def test_router_defers_weak_domain_matches_to_tool_search():
    catalog = [
        _tool("tool_search", always_on=True, discoverable=False),
        ToolDefinition(
            name="format_notes",
            description="Organize content into readable notes.",
            parameters={"type": "object", "properties": {}},
            metadata={"domains": ["notes"]},
        ),
        ToolDefinition(
            name="summarize_notes",
            description="Summarize content into concise notes.",
            parameters={"type": "object", "properties": {}},
            metadata={"domains": ["notes"]},
        ),
    ]
    router = ToolRouter()

    route = router.route(catalog, query="organize and summarize content")
    matches = router.search(
        catalog,
        query="organize and summarize content",
        exclude_names={tool.name for tool in route.tools},
    )

    assert [tool.name for tool in route.tools] == ["tool_search"]
    assert {item["name"] for item in route.deferred_tools} == {
        "format_notes",
        "summarize_notes",
    }
    assert {item["name"] for item in matches} == {
        "format_notes",
        "summarize_notes",
    }
    assert all("parameters" not in item for item in matches)


def test_router_exposes_explicit_keyword_match_on_first_round():
    catalog = [
        _tool("tool_search", always_on=True, discoverable=False),
        _tool(
            "save_drive",
            domains=["drive"],
            routing_keywords=["保存到网盘"],
        ),
        _tool(
            "delete_drive",
            domains=["drive"],
            routing_keywords=["删除网盘文件"],
        ),
    ]

    route = ToolRouter().route(catalog, query="把回答保存到网盘")

    assert [tool.name for tool in route.tools] == ["tool_search", "save_drive"]
    assert [item["name"] for item in route.deferred_tools] == ["delete_drive"]


def test_tool_search_only_returns_unexposed_matches():
    catalog = [
        _tool("tool_search", always_on=True, discoverable=False),
        _tool("share_drive", domains=["drive"], routing_keywords=["分享文件"]),
        _tool("delete_drive", domains=["drive"], routing_keywords=["删除文件"]),
    ]

    matches = ToolRouter().search(
        catalog,
        query="分享网盘文件",
        exclude_names={"share_drive"},
    )

    assert all(item["name"] != "share_drive" for item in matches)
    assert all(item["name"] != "tool_search" for item in matches)


def test_activated_domain_suppresses_cross_domain_description_noise():
    catalog = [
        ToolDefinition(
            name="get_pulse",
            description="Get today's noteworthy topics.",
            parameters={"type": "object", "properties": {}},
            metadata={"domains": ["pulse"], "routing_keywords": ["值得关注"]},
        ),
        ToolDefinition(
            name="list_todos",
            description="List today's tasks and pending work.",
            parameters={"type": "object", "properties": {}},
            metadata={"domains": ["todo"], "routing_keywords": ["今日待办"]},
        ),
    ]

    route = ToolRouter().route(catalog, query="今天有什么值得关注")

    assert [tool.name for tool in route.tools] == ["get_pulse"]


def test_focus_today_routes_both_todo_and_pulse_reads():
    catalog = [
        ToolDefinition(
            name="list_todos",
            description="List today's tasks and pending work.",
            parameters={"type": "object", "properties": {}},
            metadata={"domains": ["todo"], "routing_keywords": ["今日待办"]},
        ),
        ToolDefinition(
            name="get_pulse",
            description="Get today's noteworthy topics.",
            parameters={"type": "object", "properties": {}},
            metadata={"domains": ["pulse"], "routing_keywords": ["值得关注"]},
        ),
    ]

    route = ToolRouter().route(
        catalog,
        query=(
            "请先调用 list_todos 读取今天和已逾期的未完成 Todo，"
            "然后调用 get_pulse 读取今日 Pulse，并生成今日聚焦。"
        ),
    )

    assert route.activated_domains == ["todo", "pulse"]
    assert [tool.name for tool in route.tools] == ["list_todos", "get_pulse"]


def test_pulse_information_cluster_optimization_routes_to_analysis_tool():
    catalog = [
        _tool(
            "optimize_pulse_topics",
            domains=["pulse"],
            routing_keywords=["优化信息簇", "优化订阅"],
        ),
        _tool(
            "list_todos",
            domains=["todo"],
            routing_keywords=["今日待办"],
        ),
    ]

    route = ToolRouter().route(catalog, query="帮我优化 Pulse 信息簇和订阅关键词")

    assert route.activated_domains == ["pulse"]
    assert [tool.name for tool in route.tools] == ["optimize_pulse_topics"]


def test_pulse_topic_deletion_routes_to_delete_tool():
    catalog = [
        _tool(
            "delete_pulse_topic",
            domains=["pulse"],
            routing_keywords=["删除 topic", "删掉订阅"],
        ),
        _tool(
            "upsert_pulse_topic",
            domains=["pulse"],
            routing_keywords=["新增 topic", "修改订阅"],
        ),
    ]

    route = ToolRouter().route(catalog, query="把停用的 Pulse Topic 删除")

    assert route.activated_domains == ["pulse"]
    assert route.scored_tools[0]["name"] == "delete_pulse_topic"


def test_cat_image_request_has_one_public_image_tool(engine):
    from agent.schemas.chat import ChatRequest
    catalog, tools, route = engine._routed_tool_definitions_for_request(
        ChatRequest(conversation_id='cat-route', message='给我画一幅小猫图片', agent_id='super_chat'), agent_id='super_chat')
    assert 'image_generation_v1' in {tool.name for tool in tools}
    assert 'generate_image' not in {tool.name for tool in catalog}
    assert route.activated_domains == ['image']


def test_explicit_ascii_request_does_not_activate_image_domain():
    router = ToolRouter()
    assert 'image' not in router._activated_domains('给我画一幅 ASCII 小猫字符画')


def test_disabling_unified_image_tool_leaves_no_direct_bypass(engine):
    from agent.schemas.chat import ChatRequest
    _, tools, _ = engine._routed_tool_definitions_for_request(
        ChatRequest(conversation_id='cat-disabled',message='给我画一幅小猫图片',agent_id='super_chat'),
        agent_id='super_chat',disabled_tools={'image_generation_v1'})
    assert not {'image_generation_v1','generate_image'} & {tool.name for tool in tools}


def test_drawing_phrases_activate_images_but_general_chat_does_not():
    router = ToolRouter()
    for query in ['帮我画一只猫','画个机器人','Draw me a cat','paint a landscape']:
        assert 'image' in router._activated_domains(query)
    for query in ['小猫为什么睡觉','这张画的作者是谁','ASCII cat','给我画一幅字符画']:
        assert 'image' not in router._activated_domains(query)


def test_image_tool_is_available_even_when_query_does_not_match_keywords(engine):
    from agent.schemas.chat import ChatRequest
    for query in ['帮我生成一只小猫', '来只橘猫，水彩风格', '你好']:
        _, tools, _ = engine._routed_tool_definitions_for_request(
            ChatRequest(conversation_id='image-always',message=query,agent_id='super_chat'),agent_id='super_chat')
        assert 'image_generation_v1' in {tool.name for tool in tools}


def test_image_execution_guard_excludes_questions_negation_and_text_art():
    from agent.skills.router import explicit_image_generation_request
    assert explicit_image_generation_request('帮我生成一只小猫')
    assert explicit_image_generation_request('给我画一幅小猫图片')
    for query in ['不要给我画一只猫', '为什么刚才生成一只猫失败了', '帮我生成一首诗',
                  '帮我生成一个接口', '给我画一幅 ASCII 小猫', '小猫吃什么',
                  '帮我生成一只小猫的提示词', '给我画一只猫，不要实际生成，只要提示词']:
        assert not explicit_image_generation_request(query)
