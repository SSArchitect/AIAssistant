"""Bounded, process-local recovery of unfinished read-only planning segments.

No partial plan is committed to a project. Keys bind the complete immutable
request (including user, choices, locks and asset content), excluding retry hints.
"""
from collections import OrderedDict
import copy
import hashlib
import json
import time

TTL_SECONDS = 1800
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
_CACHE = OrderedDict()


def key(request):
    body = request.model_dump(exclude={'recovery'})
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def discard(request):
    _CACHE.pop(key(request), None)


def load(request):
    now = time.monotonic()
    for ident, (stamp, _, _) in list(_CACHE.items()):
        if now - stamp >= TTL_SECONDS:
            _CACHE.pop(ident, None)
    if not request.recovery:
        discard(request)
        return {}
    saved = _CACHE.get(key(request))
    return copy.deepcopy(saved[2]) if saved else {}


def save(request, checkpoint):
    ident = key(request)
    size = len(json.dumps(checkpoint, ensure_ascii=False).encode())
    _CACHE.pop(ident, None)
    if size > MAX_ENTRY_BYTES or not checkpoint:
        return
    while _CACHE and sum(item[1] for item in _CACHE.values()) + size > MAX_TOTAL_BYTES:
        _CACHE.popitem(last=False)
    _CACHE[ident] = (time.monotonic(), size, copy.deepcopy(checkpoint))
