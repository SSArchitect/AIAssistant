"""The creative director's bounded, read-only research toolbox."""
from __future__ import annotations

import asyncio
import json

from agent.llm.base import ToolDefinition
from agent.skills.builtin.drive import DriveListSkill, DriveReadSkill, DriveSearchSkill


def director_tools():
    skills = [DriveSearchSkill(), DriveReadSkill(), DriveListSkill()]
    return {skill.metadata().name: skill for skill in skills}


def tool_definitions(skills):
    return [ToolDefinition(**skill.to_tool_definition()) for skill in skills.values()]


async def execute_director_tool(skills, call, user_id, report, trace_store=None, run_id=''):
    skill = skills.get(call.name)
    if not skill or skill.metadata().access != 'read' or 'creation_director' not in skill.metadata().allowed_agents:
        return {'success': False, 'error': '创作助手只能检索和读取当前账号的素材，生成需在画布确认后执行'}
    names = {'search_drive': '检索网盘中的创作资料', 'read_drive': '读取脚本或参考文档', 'ls_drive': '查看创作素材目录'}
    label = names[call.name]
    if call.name == 'search_drive':
        label += '：' + str(call.arguments.get('query', ''))[:100]
    await report('tool_start', label)
    if trace_store:
        trace_store.append_event(run_id, type='tool.started', status='running', title=label, step_id=call.id, payload={'tool_name': call.name})
    allowed = {p.name for p in skill.metadata().parameters}
    arguments = {key: value for key, value in call.arguments.items() if key in allowed}
    if call.name == 'search_drive': arguments['limit'] = 8
    if call.name == 'read_drive': arguments['max_chars'] = 12000
    try:
        result = await asyncio.wait_for(skill.execute(**arguments, _user_id=user_id), timeout=25)
        payload = {'success': result.success, 'data': result.data} if result.success else {'success': False, 'error': '未能读取这份资料，请检查文件是否存在或改用其他资料'}
        serialized = json.dumps(payload, ensure_ascii=False)
        if len(serialized) > 18000:
            payload = {'success': result.success, 'excerpt': serialized[:18000], 'truncated': True}
    except Exception:
        payload = {'success': False, 'error': '资料读取失败或超时，可以重试或向用户说明缺少哪些资料'}
    await report('tool_end', f'{label}：' + ('已完成，继续整理创作方案' if payload['success'] else '未完成，正在调整下一步'))
    if trace_store:
        trace_store.append_event(run_id, type='tool.completed' if payload['success'] else 'tool.failed', status='completed' if payload['success'] else 'failed', title=label, step_id=call.id, payload={'tool_name': call.name, 'success': payload['success']})
    return payload
