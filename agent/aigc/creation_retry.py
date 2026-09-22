"""Classify recoverable model failures without matching private error prose."""
import asyncio

import httpx
import openai


def transient_model_error(exc):
    if isinstance(exc, (httpx.TransportError, openai.APIConnectionError, asyncio.TimeoutError)):
        return True
    status = getattr(exc, 'status_code', None)
    if status is not None:
        return status in (500, 502, 503, 504)
    # An SSE error can arrive after HTTP 200; the SDK raises plain APIError
    # without status_code. Only recognize explicit temporary provider codes.
    if isinstance(exc, openai.APIError):
        body = getattr(exc, 'body', None)
        error = body.get('error', body) if isinstance(body, dict) else {}
        code = error.get('code', error.get('type', '')) if isinstance(error, dict) else ''
        return str(code).lower().replace('_', '').replace('-', '') in {
            'internalservererror', 'internalerror', 'servererror',
            'serviceunavailable', 'temporarilyunavailable', 'requesttimeout',
        }
    return False
