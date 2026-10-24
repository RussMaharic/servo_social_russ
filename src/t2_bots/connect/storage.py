"""Atomic local state; device credentials never leave the companion for the browser."""
import hashlib
import json
import os
import secrets
import time
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp-" + secrets.token_hex(4))
    try:
        descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class LocalStore:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("T2_CONNECT_HOME") or
                         Path.home() / ".config" / "t2_bots" / "connect")
        self.path = self.root / "station.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "device_id": secrets.token_urlsafe(24), "credential": secrets.token_urlsafe(32),
            "username": "", "directory_url": "", "arms": {}, "active_role": "leader",
        }
        self.save()

    def save(self):
        atomic_json(self.path, self.data)

    def save_profile(self, role, profile):
        target = self.root / "calibration" / ("so101_" + role + ".json")
        if target.exists():
            backup = target.with_name(target.name + "." + str(time.time_ns()) + ".bak")
            backup.write_bytes(target.read_bytes())
        atomic_json(target, profile)
        return target

    def profile_path(self, role):
        return self.root / "calibration" / ("so101_" + role + ".json")
