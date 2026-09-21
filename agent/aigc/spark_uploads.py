"""Private upload receipts; retries keep the same provider asset and task payload."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

UPLOAD_CACHE_DIR = Path(__file__).resolve().parents[2] / 'data/spark-input-uploads'


class UploadConflict(ValueError):
    pass


class UploadCache:
    def __init__(self, directory, origin, credential):
        self.directory = Path(directory)
        self.scope = origin.rstrip('/') + '\n' + hashlib.sha256(credential.encode()).hexdigest()

    def path(self, key):
        return self.directory / (hashlib.sha256((self.scope+'\n'+key).encode()).hexdigest()+'.json')

    @staticmethod
    def fingerprint(content, media_type):
        return hashlib.sha256(media_type.encode()+b'\n'+content).hexdigest()

    def load(self, key, content, media_type):
        try:
            saved = json.loads(self.path(key).read_text())
        except (FileNotFoundError, ValueError):
            return None  # Replay the original immutable upload key after an incomplete receipt.
        if not isinstance(saved, dict) or not saved.get('fingerprint') or not saved.get('asset_id'):
            return None
        try:
            if str(uuid.UUID(saved['asset_id'])) != saved['asset_id']:return None
        except (ValueError, TypeError, AttributeError):
            return None
        if saved['fingerprint'] != self.fingerprint(content, media_type):
            raise UploadConflict('The upload input changed under the same idempotency key')
        return saved['asset_id']

    def save(self, key, content, media_type, asset_id):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=self.directory, suffix='.pending')
        try:
            with os.fdopen(fd,'w') as target:
                json.dump(dict(fingerprint=self.fingerprint(content,media_type),asset_id=asset_id),target)
            os.replace(name,self.path(key))
        finally:
            if os.path.exists(name):os.unlink(name)
