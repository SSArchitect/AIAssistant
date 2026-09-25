"""Regression: a promise to fetch a script must not finish a planning turn."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.aigc import creation_planning as planning
from agent.llm.base import LLMResponse, ToolCall
from agent.skills.base import SkillResult
from tests.test_creation_planning import request, plan


@pytest.mark.asyncio
async def test_deferred_drive_read_continues_in_same_turn(monkeypatch):
    req = request()
    req.messages = [{'role': 'user', 'content': '好，继续去读网盘28秒脚本，按已选两段方案规划'}]
    req.current_plan = plan()
    skills = planning.director_tools()
    read = AsyncMock(return_value=SkillResult(success=True, data={'content': '脚本正文'}))
    monkeypatch.setattr(skills['read_drive'], 'execute', read)
    monkeypatch.setattr(planning, 'director_tools', lambda: skills)
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content=json.dumps({'reply': '我先去网盘读取更新的脚本，拿到后重排节点。', 'patch': {}})),
        LLMResponse(tool_calls=[ToolCall(id='read', name='read_drive', arguments={'item_id': 'script'})]),
        LLMResponse(content=json.dumps({'reply': '已读取并更新脚本', 'patch': {'nodes': [{'id': 'script', 'content': '更新后的完整脚本'}]}})),
    ]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    result = await planning.propose_creation(req)
    assert read.await_count == 1
    assert provider.chat.await_count == 3
    assert result.plan.nodes[0].content == '更新后的完整脚本'


@pytest.mark.asyncio
async def test_repeated_deferred_work_is_bounded_and_not_reported_as_success(monkeypatch):
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps({
        'reply': '我先去网盘检索脚本，拿到后继续规划。', 'patch': {}}))))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    req = request(); req.current_plan = plan()
    with pytest.raises(planning.PlanningConstraintError, match='资料'):
        await planning.propose_creation(req)
    assert provider.chat.await_count == 3


@pytest.mark.asyncio
async def test_clarification_without_node_changes_does_not_force_tool_call(monkeypatch):
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps({
        'reply': '当前方案有一条视频，请确认是否需要拆分。', 'patch': {}}))))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    req = request(); req.current_plan = plan()
    result = await planning.propose_creation(req)
    assert result.reply.startswith('当前方案') and provider.chat.await_count == 1
