from agent.llm.base import ToolDefinition
from agent.skills.router import CORE_ALWAYS_ON_TOOL_NAMES, ToolRouter


def _tool(name: str, **metadata) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} drive capability",
        parameters={"type": "object", "properties": {}},
        metadata=metadata,
    )


def test_router_keeps_core_tools_and_caps_dynamic_exposure():
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

    route = ToolRouter(max_dynamic_tools=8).route(catalog, query="整理我的网盘文件")
    names = {tool.name for tool in route.tools}

    assert CORE_ALWAYS_ON_TOOL_NAMES.issubset(names)
    assert len(route.tools) == len(CORE_ALWAYS_ON_TOOL_NAMES) + 8
    assert route.activated_domains == ["drive"]


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
