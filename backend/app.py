from models import Task  # noqa
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, g
import psycopg2
import psycopg2.extras
import redis

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://taskuser:taskpass@db:5432/taskdb")
REDIS_URL = os.environ["REDIS_URL"]

search_history = []

def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL)
        g.db.autocommit = True
    return g.db

def get_redis():
    if "redis" not in g:
        g.redis = redis.from_url(REDIS_URL)
    return g.redis

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.before_request
def log_request():
    try:
        g.start_time = datetime.now()
        app.logger.info(f"{request.method} {request.path}")
    except:
        pass

@app.after_request
def after_request(response):
    try:
        duration = datetime.now() - g.start_time
        app.logger.info(f"{request.method} {request.path} -> {response.status_code} ({duration.total_seconds():.3f}s)")
    except:
        pass
    return response

@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    status = request.args.get("status")
    today_only = request.args.get("today")
    query = "SELECT * FROM tasks"
    conditions = []
    params = []
    if status:
        conditions.append("active = true" if status == "active" else "active = false")
    if today_only:
        conditions.append("DATE(created_at) = DATE(%s)")
        params.append(datetime.now())
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC"
    cur.execute(query, params)
    tasks = cur.fetchall()
    result = []
    for t in tasks:
        result.append({
            "id": t["id"], "title": t["title"], "description": t["description"],
            "is_active": t["is_active"],
            "created_at": t["created_at"].isoformat() if t["created_at"] else None,
            "updated_at": t["updated_at"].isoformat() if t["updated_at"] else None,
        })
    return jsonify(result)

@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.get_json()
    if not data or not data.get("title"):
        return jsonify({"error": "Title is required"}), 400
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "INSERT INTO tasks (title, description, is_active, created_at, updated_at) VALUES (%s, %s, %s, %s, %s) RETURNING *",
        (data["title"], data.get("description", ""), True, datetime.now(timezone.utc), datetime.now(timezone.utc))
    )
    task = cur.fetchone()
    r = get_redis()
    r.delete("stats")
    return jsonify({
        "id": task["id"], "title": task["title"], "description": task["description"],
        "is_active": task["is_active"], "created_at": task["created_at"].isoformat(),
        "updated_at": task["updated_at"].isoformat(),
    }), 201

@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    data = request.get_json()
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
    task = cur.fetchone()
    if not task:
        return jsonify({"error": "Not found"}), 404
    title = data.get("title", task["title"])
    description = data.get("description", task["description"])
    is_active = data.get("is_active", task["is_active"])
    cur.execute(
        "UPDATE tasks SET title = %s, description = %s, is_active = %s, updated_at = %s WHERE id = %s RETURNING *",
        (title, description, is_active, datetime.now(timezone.utc), task_id)
    )
    updated = cur.fetchone()
    r = get_redis()
    r.delete("stats")
    return jsonify({
        "id": updated["id"], "title": updated["title"], "description": updated["description"],
        "is_active": updated["is_active"], "created_at": updated["created_at"].isoformat(),
        "updated_at": updated["updated_at"].isoformat(),
    })

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    r = get_redis()
    r.delete("stats")
    return "", 204

@app.route("/api/search", methods=["GET"])
def search_tasks():
    q = request.args.get("q", "")
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM tasks WHERE title ILIKE %s OR description ILIKE %s", (f"%{q}%", f"%{q}%"))
    results = cur.fetchall()
    search_history.append({"query": q, "results_count": len(results), "timestamp": datetime.now().isoformat()})
    serialized = []
    for t in results:
        serialized.append({
            "id": t["id"], "title": t["title"], "description": t["description"],
            "is_active": t["is_active"],
            "created_at": t["created_at"].isoformat() if t["created_at"] else None,
        })
    return jsonify(serialized)

@app.route("/api/stats", methods=["GET"])
def get_stats():
    r = get_redis()
    cached = r.get("stats")
    if cached:
        import json
        return jsonify(json.loads(cached))
    db = get_db()
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE is_active = true) as active, COUNT(*) FILTER (WHERE is_active = false) as done FROM tasks")
    stats = cur.fetchone()
    import json
    r.setex("stats", 1, json.dumps(dict(stats)))
    return jsonify(dict(stats))

def warmup_cache():
    try:
        r = redis.from_url(REDIS_URL)
        r.ping()
        import urllib.request
        urllib.request.urlopen("http://localhost:8000/api/stats")
    except Exception as e:
        print(f"Cache warmup failed (non-critical): {e}")

warmup_cache()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
