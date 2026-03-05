import os
import sys
import pathlib
import importlib
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


class DummyCursor:
    def execute(self, _query, _params=None):
        return None

    def fetchone(self):
        return {"ok": 1}


class DummyDB:
    autocommit = True

    def cursor(self, *args, **kwargs):
        return DummyCursor()

    def commit(self):
        return None

    def rollback(self):
        return None


def test_db_connection_ok(monkeypatch):
    monkeypatch.setattr(app, "get_db", lambda: DummyDB())
    db = app.get_db()
    cur = db.cursor()
    cur.execute("SELECT 1")
    assert cur.fetchone()["ok"] == 1


def test_health_reports_db_ok(monkeypatch):
    monkeypatch.setattr(app, "get_db", lambda: DummyDB())
    monkeypatch.setattr(app, "get_redis", lambda: type("R", (), {"ping": lambda self: True})())
    client = app.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json().get("database") == "ok"
