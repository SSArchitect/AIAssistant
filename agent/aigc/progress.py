"""Task-local media progress, shared by nested workflows without leaking across users."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

BACKGROUND_TIMEOUT = 6 * 60 * 60
_progress = ContextVar('media_progress', default=None)
_background = ContextVar('media_background', default=False)


@contextmanager
def progress_scope(sink, *, background=False):
    sink_token = _progress.set(sink)
    background_token = _background.set(background)
    try:
        yield
    finally:
        _background.reset(background_token)
        _progress.reset(sink_token)


def emit_progress(**payload):
    sink = _progress.get()
    if sink is not None:
        sink(payload)


def background_enabled():
    return _background.get()


def tool_timeout(name, default):
    if background_enabled() and name in {'generate_video', 'generate_image', 'image_generation_v1', 'deep_research_v1'}:
        return max(default, BACKGROUND_TIMEOUT + 120)
    return default


def track_media_progress(process):
    @wraps(process)
    async def tracked(self, request, *args, **kwargs):
        if not request.run_id:
            request = request.model_copy(update={'run_id': f'run_{uuid4().hex}'})
        def sink(payload):
            self.trace_store.append_event(request.run_id, type='media.task.progress',
                status='running', title='Media task progress', payload=payload)
        with progress_scope(sink, background=request.stream or background_enabled()):
            return await process(self, request, *args, **kwargs)
    return tracked
