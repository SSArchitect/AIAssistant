"""Model capability routing and safe diagnostics for creative planning."""
from __future__ import annotations

import asyncio
import re

import httpx
import openai

from agent.llm.doubao_provider import is_agent_plan_url

VISION_PLAN_MODEL = 'doubao-seed-2.1-turbo'
CREATION_OUTPUT_TOKENS = 16384


class PlanningOutputTruncated(RuntimeError):
    pass


def configure_planning_output(provider):
    """Size this director instance for a graph, without changing chat settings."""
    if (getattr(provider, 'provider_name', '') == 'doubao'
            and is_agent_plan_url(str(getattr(getattr(provider, 'client', None), 'base_url', '')))
            and getattr(provider, 'max_tokens', None) is None):
        provider.max_tokens = CREATION_OUTPUT_TOKENS


def can_use_plan_vision(provider) -> bool:
    return (getattr(provider, 'provider_name', '') == 'doubao'
            and is_agent_plan_url(str(getattr(getattr(provider, 'client', None), 'base_url', '')))
            and getattr(provider, 'model', '') != VISION_PLAN_MODEL)


async def use_plan_vision(provider, factory):
    # Retain the configured provider, credentials and endpoint; do not alter the default model.
    replacement = factory('doubao:' + VISION_PLAN_MODEL)
    client = getattr(provider, 'client', None)
    if client is not None:
        await client.close()
    return replacement


def unsupported_image_input(exc) -> bool:
    if not isinstance(exc, openai.BadRequestError):
        return False
    body = getattr(exc, 'body', None)
    error = body.get('error', body) if isinstance(body, dict) else {}
    message = str(error.get('message', '')).lower() if isinstance(error, dict) else ''
    return ('only support text' in message or 'only supports text' in message
            or bool(re.search(r'(?:image|vision|multimodal).{0,70}(?:not supported|unsupported|not support)', message))
            or bool(re.search(r'(?:not support|unsupported).{0,70}(?:image|vision|multimodal)', message)))


def planning_error(exc):
    if isinstance(exc, PlanningOutputTruncated):
        return 'planning_output_truncated', '模型未完整返回创作方案，原有内容已保留；请分段规划后继续'
    if unsupported_image_input(exc):
        return 'model_image_unsupported', '当前规划模型不支持图片输入，请配置支持图片理解的模型后重试；素材已保留'
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException, openai.APITimeoutError)):
        return 'planning_timeout', '创作规划等待超时，原有内容已保留，请重试'
    status = getattr(exc, 'status_code', None)
    if status in (401, 403):
        return 'provider_auth_failed', '规划模型鉴权或访问权限异常，请检查模型服务配置；原有内容已保留'
    if status == 429:
        return 'provider_rate_limited', '规划模型调用额度不足或请求过于频繁，请检查额度或稍后重试；原有内容已保留'
    if status == 400:
        return 'provider_request_rejected', '规划模型拒绝了本次请求，请检查所选模型的输入能力与配置；原有内容已保留'
    if isinstance(exc, openai.APIConnectionError) or isinstance(status, int) and status >= 500:
        return 'provider_unavailable', '暂时无法连接规划模型服务，请稍后重试；原有内容已保留'
    if isinstance(exc, ValueError):
        return 'invalid_plan', '创作方案格式校验失败，原有内容已保留，请补充要求或重试'
    return 'planning_failed', '创作助手暂时无法完成规划，原有内容已保留，请重试'
