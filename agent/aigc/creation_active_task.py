"""Separate the current operation from the project's historical conversation."""
import json
from agent.aigc.creation_draft_edit import draft_edit_task
from agent.aigc.creation_edit_attempts import exhausted_edit_task
from agent.aigc.creation_region_repair import region_repair_task


def active_planning_task(request):
    if request.repair:
        task=dict(mode='automatic_repair',repair=request.repair.model_dump(),
            instruction='仅处理本次repair，遵循冻结验收和锁定范围；历史对话中的已处理修改命令不是本轮任务。')
        operation = region_repair_task(request) or exhausted_edit_task(request) or draft_edit_task(request)
        if operation:
            task['current_operation'] = operation
            task['instruction'] += 'repair记录全部未通过项；这一次操作只执行current_operation，未处理项留到下一轮。'
    elif request.automatic_mode:
        task=dict(mode='automatic_continue',
            instruction='接管当前未确认的后续创作，基于现有方案及用户已确定的要求推进，保留锁定内容；不要重新执行历史维护命令。')
    else:
        current=next((message for message in reversed(request.messages) if message.get('role')=='user'),None)
        task=dict(mode='user_request',current_request=current or {},
            instruction='执行current_request这一次最新请求；此前messages仅为已发生的历史。最新明确修改覆盖历史冲突指令，既有未冲突的创作要求继续保留。')
    return {'type':'text','text':'本轮待执行任务（历史记录和图片均已在前面提供）：\n'+json.dumps(task,ensure_ascii=False)}
