import os
import sys
import pathlib
import importlib
from datetime import datetime, timezone
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

if "flask_cors" not in sys.modules:
    stub = types.ModuleType("flask_cors")
    stub.CORS = lambda *args, **kwargs: None
    sys.modules["flask_cors"] = stub

if "psycopg2" not in sys.modules:
    pg = types.ModuleType("psycopg2")
    pg.extras = types.ModuleType("psycopg2.extras")
    pg.extras.RealDictCursor = object
    sys.modules["psycopg2"] = pg
    sys.modules["psycopg2.extras"] = pg.extras

if "redis" not in sys.modules:
    rmod = types.ModuleType("redis")
    rmod.from_url = lambda *args, **kwargs: None
    sys.modules["redis"] = rmod

app = importlib.import_module("app")


class DummyRedis:
    def ping(self):
        return True

    def delete(self, _key):
        return None


class MemoryDB:
    def __init__(self):
        self.tasks = []
        self._next_id = 1
        self.autocommit = True

    def cursor(self, *args, **kwargs):
        return MemoryCursor(self)

    def commit(self):
        return None

    def rollback(self):
        return None


class MemoryCursor:
    def __init__(self, db):
        self.db = db
        self._last = None

    def execute(self, query, params=None):
        q = query.strip().lower()
        params = params or []
        if q.startswith("select pg_advisory_xact_lock"):
            return None
        if q.startswith("select * from tasks where title"):
            title = params[0]
            self._last = next((t for t in self.db.tasks if t["title"] == title), None)
            return None
        if q.startswith("insert into tasks"):
            title, description, is_active, created_at, updated_at = params
            task = {
                "id": self.db._next_id,
                "title": title,
                "description": description,
                "is_active": is_active,
                "created_at": created_at or datetime.now(timezone.utc),
                "updated_at": updated_at or datetime.now(timezone.utc),
            }
            self.db._next_id += 1
            self.db.tasks.append(task)
            self._last = task
            return None
        if q.startswith("select * from tasks"):
            self._last = list(self.db.tasks)
            return None
        raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self):
        return self._last

    def fetchall(self):
        return self._last or []


def test_task_is_added(monkeypatch):
    mem = MemoryDB()
    monkeypatch.setattr(app, "get_db", lambda: mem)
    monkeypatch.setattr(app, "get_redis", lambda: DummyRedis())
    client = app.app.test_client()
    resp = client.post("/api/tasks", json={"title": "test task"})
    assert resp.status_code in (200, 201)
    resp = client.get("/api/tasks")
    data = resp.get_json()
    assert any(t.get("title") == "test task" for t in data)
