"""Provider-enforced JSON contracts for Creation; semantic validation remains local."""
from __future__ import annotations

import copy

import openai
from agent.llm.openai_provider import OpenAIProvider


def strict_schema(schema):
    """Close every object; optional properties use null to mean omitted on the wire."""
    schema = copy.deepcopy(schema)
    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        value = {key: ({name: visit(child) for name, child in item.items()} if key in ('properties', '$defs', 'definitions') else visit(item))
                 for key, item in value.items() if key not in ('default', 'title')}
        if value.get('type') == 'object' or 'properties' in value:
            properties = value.get('properties', {})
            required = value.get('required', [])
            for name, item in properties.items():
                if name not in required:
                    properties[name] = {'anyOf': [item, {'type': 'null'}]}
            value.update(properties=properties, required=list(properties), additionalProperties=False)
        return value
    return visit(schema)


def structured_options(provider, schema, name, *, json_only=False):
    if not isinstance(provider, OpenAIProvider):
        return {}
    response_format = {'type': 'json_object'} if json_only else {
        'type': 'json_schema', 'json_schema': {'name': name, 'strict': True, 'schema': strict_schema(schema)}}
    return {'response_format': response_format}


def unsupported_schema(exc):
    if not isinstance(exc, openai.BadRequestError):
        return False
    text = str(getattr(exc, 'body', '')).lower()
    return any(word in text for word in ('json_schema', 'response_format', 'structured output')) and any(
        word in text for word in ('not support', 'unsupported', 'not available'))


def omit_null_fields(value):
    """Null optional keys represent no change, never a request to erase approved data."""
    if isinstance(value, dict):
        return {key: omit_null_fields(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [omit_null_fields(item) for item in value]
    return value


def validation_details(exc):
    if hasattr(exc, 'errors'):
        return [{'type': e['type'], 'loc': e['loc'], 'msg': e['msg']}
                for e in exc.errors(include_input=False, include_context=False)]
    return [{'type': type(exc).__name__, 'msg': str(exc)[:500]}]
