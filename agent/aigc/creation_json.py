"""Recover unambiguous JSON punctuation without rewriting a model's decision."""
import json


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('JSON包含重复字段，不能推测采用哪个值')
        result[key] = value
    return result


def _finite_json(_):
    raise ValueError('JSON不能包含非有限数值')


def parse_complete_object(content):
    """Only insert a missing colon after a fully parsed property name.

    The JSON decoder supplies that exact position. Never guess quotation marks,
    commas, missing values or closing delimiters, nor accept multiple objects.
    All original text is retained; schema and domain validation still follow.
    """
    if not isinstance(content, str) or len(content) > 50000:
        raise ValueError('JSON回复大小无效')
    text = content.strip()
    repairs = 0
    while True:
        try:
            result = json.loads(text, object_pairs_hook=_unique_fields, parse_constant=_finite_json)
        except json.JSONDecodeError as exc:
            if exc.msg != "Expecting ':' delimiter" or repairs >= 32:
                # Do not expose model content in errors or trace metadata.
                raise ValueError('JSON结构不完整或存在歧义，需要重新返回完整对象') from None
            text = text[:exc.pos] + ':' + text[exc.pos:]
            repairs += 1
            continue
        if not isinstance(result, dict):
            raise ValueError('JSON必须是单个对象')
        return result, repairs
