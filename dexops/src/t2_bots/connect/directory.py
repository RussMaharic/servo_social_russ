"""Single-instance persistent follower directory. Robot traffic never passes here."""
import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field



def endpoint_url(value):
    value = value.strip()
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        raise ValueError("Invalid connection port.")
    if parts.scheme not in ("ws", "wss") or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("Use a ws:// or wss:// follower address without embedded credentials.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid connection port.")
    return value


class Identity(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    device_id: str = Field(min_length=20, max_length=80)
    credential: str = Field(min_length=32, max_length=100)


class Publication(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    endpoint: str = Field(max_length=300)
    calibrated: bool = False
    busy: bool = False


class Directory:
    integrity_error = sqlite3.IntegrityError
    reservation_query = "SELECT * FROM followers WHERE id=?"

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, token TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS followers (
                    id TEXT PRIMARY KEY REFERENCES devices(id), label TEXT NOT NULL,
                    endpoint TEXT NOT NULL, certificate TEXT NOT NULL, seen REAL NOT NULL,
                    busy INTEGER NOT NULL DEFAULT 0, holder TEXT, held_until REAL NOT NULL DEFAULT 0);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def claim(self, req):
        name = req.username.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{2,23}", name):
            raise HTTPException(422, "Use 3–24 letters, numbers, underscores or hyphens, starting with a letter.")
        token = hashlib.sha256(req.credential.encode()).hexdigest()
        with self.lock, self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM devices WHERE id=?", (req.device_id,)).fetchone()
            if existing:
                if not hmac.compare_digest(existing["token"], token):
                    raise HTTPException(403, "This device is already registered with another credential.")
                if name != existing["username"]:
                    raise HTTPException(409, "This device already owns @" + existing["username"])
                return {"username": name}
            try:
                db.execute("INSERT INTO devices VALUES (?,?,?)", (req.device_id, name, token))
            except self.integrity_error:
                raise HTTPException(409, "That username is taken. Choose another.")
        return {"username": name}

    def authorize(self, request):
        device = request.headers.get("X-Device-ID", "")
        credential = request.headers.get("Authorization", "").removeprefix("Bearer ")
        with self.db() as db:
            row = db.execute("SELECT * FROM devices WHERE id=?", (device,)).fetchone()
        if not row or not hmac.compare_digest(row["token"], hashlib.sha256(credential.encode()).hexdigest()):
            raise HTTPException(403, "Device credential required.")
        return device

    def list(self):
        now = time.time()
        with self.db() as db:
            rows = db.execute("SELECT followers.*, devices.username FROM followers JOIN devices ON devices.id=followers.id WHERE seen>? ORDER BY label", (now - 25,)).fetchall()
        return [{"id": r["id"], "label": r["label"], "owner": r["username"],
                 "endpoint": r["endpoint"], "calibrated": json.loads(r["certificate"]).get("calibrated") is True,
                 "last_seen": r["seen"], "available": not r["busy"] and r["held_until"] < now}
                for r in rows]

    def publish(self, device, req):
        address = endpoint_url(req.endpoint)
        if req.calibrated is not True:
            raise HTTPException(422, "Complete follower calibration before sharing.")
        # Preserve the deployed storage schema; this column now stores readiness.
        readiness = {"calibrated": True}
        with self.lock, self.db() as db:
            db.execute("""INSERT INTO followers(id,label,endpoint,certificate,seen,busy)
                VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                label=excluded.label, endpoint=excluded.endpoint, certificate=excluded.certificate,
                seen=excluded.seen,busy=excluded.busy""",
                       (device, req.label, address, json.dumps(readiness), time.time(), int(req.busy)))
        return {"published": True}

    def reserve(self, device, follower):
        now = time.time()
        with self.lock, self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(self.reservation_query, (follower,)).fetchone()
            if not row or row["seen"] < now - 25:
                raise HTTPException(409, "This follower is offline. Refresh the directory.")
            if (row["busy"] or row["held_until"] > now) and row["holder"] != device:
                raise HTTPException(409, "This follower is already in use.")
            db.execute("UPDATE followers SET holder=?,held_until=? WHERE id=?", (device, now + 45, follower))
        return {"endpoint": row["endpoint"], "reserved_until": now + 45}

    def check(self):
        with self.db() as db:
            db.execute("SELECT id FROM devices LIMIT 1").fetchone()


def sqlite_directory_path():
    """Use an optional persistent path or the current SQLite pilot database."""
    configured = os.environ.get("T2_DIRECTORY_DB")
    if configured:
        return configured
    return "directory.sqlite3"


def create_app(db_path=None):
    directory = Directory(db_path or sqlite_directory_path())
    app = FastAPI(title="Dexops directory", docs_url=None, redoc_url=None)
    app.state.directory = directory
    attempts = defaultdict(deque)
    rate_lock = threading.Lock()

    @app.middleware("http")
    async def guards(request, call_next):
        from fastapi.responses import JSONResponse
        if request.method not in ("GET", "HEAD") and len(await request.body()) > 16384:
            return JSONResponse({"detail": "Request too large."}, 413)
        if request.method == "POST" and request.url.path == "/v1/identity":
            # Render terminates the public proxy; configure uvicorn proxy trust there.
            key = request.client.host if request.client else "unknown"
            with rate_lock:
                now = time.monotonic()
                if len(attempts) > 10000:
                    attempts.clear()
                bucket = attempts[key]
                while bucket and bucket[0] < now - 600:
                    bucket.popleft()
                if len(bucket) >= 20:
                    return JSONResponse({"detail": "Too many username claims. Try again later."}, 429)
                bucket.append(now)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/healthz")
    def health():
        try:
            directory.check()
        except Exception:
            from fastapi.responses import JSONResponse
            return JSONResponse({"status": "unavailable", "service": "t2-directory"}, status_code=503)
        return {"status": "ok", "service": "t2-directory"}

    @app.post("/v1/identity")
    def claim(req: Identity):
        return directory.claim(req)

    @app.get("/v1/followers")
    def followers():
        return {"followers": directory.list()}

    @app.put("/v1/follower")
    def publish(req: Publication, request: Request):
        try:
            return directory.publish(directory.authorize(request), req)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.delete("/v1/follower")
    def unpublish(request: Request):
        device = directory.authorize(request)
        with directory.lock, directory.db() as db:
            db.execute("DELETE FROM followers WHERE id=?", (device,))
        return {"published": False}

    @app.post("/v1/followers/{follower}/reserve")
    def reserve(follower: str, request: Request):
        return directory.reserve(directory.authorize(request), follower)

    @app.delete("/v1/followers/{follower}/reserve")
    def release(follower: str, request: Request):
        device = directory.authorize(request)
        with directory.lock, directory.db() as db:
            db.execute("UPDATE followers SET holder=NULL,held_until=0 WHERE id=? AND holder=?", (follower, device))
        return {"released": True}

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="Shared Dexops follower directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8090")))
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
