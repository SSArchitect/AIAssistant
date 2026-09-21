"""Persist accepted Creation image/video identities without storing prompts or credentials."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from agent.config import runtime_config

STATE_DIR = Path(__file__).resolve().parents[2] / 'data/creation-media-tasks'


class CreationMediaState:
    def __init__(self, request):
        excluded = {'resume_task_id'}
        # Preserve pre-edit fingerprints so accepted jobs still resume after upgrade.
        if not getattr(request, 'image_operation', ''):
            excluded.add('image_operation')
        if not getattr(request, 'image_layout', []):
            excluded.add('image_layout')
        fingerprint = hashlib.sha256((request.model_dump_json(exclude=excluded) + '\n' + runtime_config.get('aigc.spark.base_url')).encode()).hexdigest()
        self.path = STATE_DIR / (hashlib.sha256(request.idempotency_key.encode()).hexdigest() + '.json')
        self.record = dict(fingerprint=fingerprint, task_id='', stage='submitting')
        STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._save(first=True)
        self.record = json.loads(self.path.read_text())
        if self.record.get('fingerprint') != fingerprint:
            raise ValueError('生成请求的上下文已变化，请使用新的生成请求')
        if request.resume_task_id:
            if self.task_id and self.task_id != request.resume_task_id:
                raise ValueError('原任务标识与已保存记录不一致')
            self.record['task_id'] = request.resume_task_id
            self._save()

    @property
    def task_id(self):
        return self.record.get('task_id') or None

    def _save(self, *, first=False):
        fd, temporary = tempfile.mkstemp(dir=STATE_DIR, suffix='.pending')
        try:
            with os.fdopen(fd, 'w') as target:
                json.dump(self.record, target)
            if first:
                try:
                    os.link(temporary, self.path)
                except FileExistsError:
                    pass
            else:
                os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def progress(self, payload):
        task_id = payload.get('task_id')
        if task_id:
            if self.task_id and self.task_id != task_id:
                raise ValueError('生成服务返回了不同的任务标识')
            self.record['task_id'] = task_id
        self.record['stage'] = payload.get('stage', '')
        self.record['code'] = payload.get('code', '')
        self._save()
