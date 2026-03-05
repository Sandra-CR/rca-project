#!/usr/bin/env python3
"""
RCA Health Check Runner
Runs 18 checks against the local docker-compose stack and generates report.json
"""

import json
import subprocess
import time
import concurrent.futures
from datetime import datetime, timezone

BACKEND = "http://localhost:8000"
FRONTEND = "http://localhost:3000"

REPORT = {"generated_at": None, "checks": {}}


def check(name):
    """Decorator to register a check function."""
    def decorator(fn):
        def wrapper():
            try:
                result = fn()
                passed = result if isinstance(result, bool) else result.get("pass", False)
                REPORT["checks"][name] = passed
                icon = "✅" if passed else "❌"
                print(f"  {icon} {name}")
            except Exception:
                REPORT["checks"][name] = False
                print(f"  ❌ {name}")
        wrapper._check_name = name
        return wrapper
    return decorator


# =============================================================================
# 🟢 SURFACE CHECKS (10 pts each)
# =============================================================================

@check("backend_builds")
def check_backend_builds():
    result = subprocess.run(
        ["docker", "compose", "build", "backend"],
        capture_output=True, text=True, timeout=120
    )
    return result.returncode == 0


@check("frontend_builds")
def check_frontend_builds():
    result = subprocess.run(
        ["docker", "compose", "build", "frontend"],
        capture_output=True, text=True, timeout=120
    )
    return result.returncode == 0


@check("frontend_port")
def check_frontend_port():
    try:
        import requests
        r = requests.get(FRONTEND, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


@check("redis_connected")
def check_redis_connected():
    try:
        import requests
        logs = subprocess.run(
            ["docker", "compose", "logs", "backend"],
            capture_output=True, text=True, timeout=10
        )
        has_redis_error = any(
            kw in logs.stdout.lower() + logs.stderr.lower()
            for kw in ["redis.exceptions", "connectionerror", "connection refused"]
        )
        try:
            r = requests.get(f"{BACKEND}/health", timeout=5)
            backend_up = r.status_code == 200
        except Exception:
            backend_up = False
        return not has_redis_error and backend_up
    except Exception:
        return False


@check("db_schema_valid")
def check_db_schema_valid():
    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "db",
             "psql", "-U", "taskuser", "-d", "taskdb", "-c",
             "SELECT column_name FROM information_schema.columns WHERE table_name='tasks' ORDER BY ordinal_position;"],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout.lower()
        return all(col in output for col in ["id", "title"])
    except Exception:
        return False


@check("backend_imports")
def check_backend_imports():
    try:
        logs = subprocess.run(
            ["docker", "compose", "logs", "backend"],
            capture_output=True, text=True, timeout=10
        )
        combined = logs.stdout + logs.stderr
        return "ImportError" not in combined and "ModuleNotFoundError" not in combined
    except Exception:
        return False


# =============================================================================
# 🔵 INTERMEDIATE CHECKS (15 pts each)
# =============================================================================

@check("db_connection")
def check_db_connection():
    try:
        import requests
        r = requests.get(f"{BACKEND}/health", timeout=10)
        return r.json().get("database") == "ok"
    except Exception:
        return False


@check("api_query_works")
def check_api_query_works():
    try:
        import requests
        r = requests.get(f"{BACKEND}/api/tasks", timeout=10)
        return isinstance(r.json(), list)
    except Exception:
        return False


@check("frontend_api_call")
def check_frontend_api_call():
    try:
        import requests, re
        r = requests.get(FRONTEND, timeout=10)
        html = r.text
        if any(kw in html for kw in ["/api/tasks", "api"]):
            return True
        for script in re.findall(r'src=["\']([^"\']+\.js)', html):
            url = f"{FRONTEND}/{script.lstrip('/')}" if not script.startswith("http") else script
            try:
                jr = requests.get(url, timeout=10)
                if "/api/tasks" in jr.text:
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


@check("cors_works")
def check_cors_works():
    try:
        import requests
        r = requests.options(
            f"{BACKEND}/api/tasks",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
            timeout=10
        )
        cors_header = r.headers.get("Access-Control-Allow-Origin", "")
        return cors_header in ["*", "http://localhost:3000"]
    except Exception:
        return False


@check("frontend_deps")
def check_frontend_deps():
    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "frontend",
             "test", "-f", "node_modules/.package-lock.json"],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


@check("cache_consistent")
def check_cache_consistent():
    try:
        import requests
        r1 = requests.get(f"{BACKEND}/api/stats", timeout=10)
        time.sleep(1)
        r2 = requests.get(f"{BACKEND}/api/stats", timeout=10)
        return r1.json() == r2.json()
    except Exception:
        return False


# =============================================================================
# 🟡 ADVANCED CHECKS (25 pts each)
# =============================================================================

@check("no_duplicates")
def check_no_duplicates():
    try:
        import requests
        title = f"dup_test_{int(time.time())}"
        payload = {"title": title}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(requests.post, f"{BACKEND}/api/tasks", json=payload, timeout=10),
                pool.submit(requests.post, f"{BACKEND}/api/tasks", json=payload, timeout=10),
            ]
            concurrent.futures.wait(futures)
        time.sleep(1)
        r = requests.get(f"{BACKEND}/api/tasks", timeout=10)
        matches = [t for t in r.json() if t.get("title") == title]
        return len(matches) == 1
    except Exception:
        return False


@check("no_memory_leak")
def check_no_memory_leak():
    try:
        import requests
        mem_before = _get_container_mem("backend")
        if not mem_before:
            return False
        for i in range(100):
            try:
                requests.get(f"{BACKEND}/api/search?q=test{i}", timeout=5)
            except Exception:
                pass
        time.sleep(2)
        mem_after = _get_container_mem("backend")
        if not mem_after:
            return False
        growth = (mem_after - mem_before) / mem_before if mem_before > 0 else 0
        return growth < 0.5
    except Exception:
        return False


def _get_container_mem(service):
    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", service, "cat", "/sys/fs/cgroup/memory.current"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return int(result.stdout.strip()) / (1024 * 1024)
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            if "MiB" in line:
                return float(line.split("MiB")[0].strip())
            if "GiB" in line:
                return float(line.split("GiB")[0].strip()) * 1024
    except Exception:
        pass
    return None


@check("db_ready_check")
def check_db_ready_check():
    try:
        import requests
        subprocess.run(["docker", "compose", "restart"], capture_output=True, timeout=60)
        time.sleep(5)
        for _ in range(10):
            try:
                r = requests.get(f"{BACKEND}/api/tasks", timeout=5)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(2)
        return False
    except Exception:
        return False


@check("errors_logged")
def check_errors_logged():
    try:
        import requests
        try:
            requests.post(f"{BACKEND}/api/tasks", json={"invalid_field": None}, timeout=5)
        except Exception:
            pass
        try:
            requests.get(f"{BACKEND}/api/tasks/99999999", timeout=5)
        except Exception:
            pass
        time.sleep(2)
        logs = subprocess.run(
            ["docker", "compose", "logs", "--since", "10s", "backend"],
            capture_output=True, text=True, timeout=10
        )
        combined = logs.stdout + logs.stderr
        return any(kw in combined.lower() for kw in ["error", "exception", "traceback", "warning", "404", "500"])
    except Exception:
        return False


@check("timezone_filter")
def check_timezone_filter():
    try:
        import requests
        title = f"tz_test_{int(time.time())}"
        requests.post(f"{BACKEND}/api/tasks", json={"title": title}, timeout=10)
        time.sleep(1)
        for tz in ["UTC", "America/New_York", "Asia/Tokyo"]:
            try:
                r = requests.get(f"{BACKEND}/api/tasks?filter=today&tz={tz}", timeout=10)
                if not any(t.get("title") == title for t in r.json()):
                    return False
            except Exception:
                r = requests.get(f"{BACKEND}/api/tasks?filter=today", timeout=10)
                return any(t.get("title") == title for t in r.json())
        return True
    except Exception:
        return False


@check("no_circular_dep")
def check_no_circular_dep():
    try:
        subprocess.run(["docker", "compose", "down"], capture_output=True, timeout=30)
        time.sleep(2)
        start = time.time()
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            capture_output=True, text=True, timeout=60
        )
        elapsed = time.time() - start
        if result.returncode != 0:
            return False
        ps_text = subprocess.run(
            ["docker", "compose", "ps"],
            capture_output=True, text=True, timeout=10
        ).stdout
        services_up = ps_text.count("Up") + ps_text.count("running")
        return elapsed < 60 and services_up >= 3
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


# =============================================================================
# Runner
# =============================================================================

def main():
    print("🩺 Running RCA Health Checks...\n")

    all_checks = [v for v in globals().values() if callable(v) and hasattr(v, "_check_name")]

    surface = ["backend_builds", "frontend_builds", "frontend_port", "redis_connected", "db_schema_valid", "backend_imports"]
    intermediate = ["db_connection", "api_query_works", "frontend_api_call", "cors_works", "frontend_deps", "cache_consistent"]
    advanced = ["no_duplicates", "no_memory_leak", "db_ready_check", "errors_logged", "timezone_filter", "no_circular_dep"]

    print("🟢 Surface checks:")
    for fn in all_checks:
        if fn._check_name in surface:
            fn()

    print("\n🔵 Intermediate checks:")
    for fn in all_checks:
        if fn._check_name in intermediate:
            fn()

    print("\n🟡 Advanced checks:")
    for fn in all_checks:
        if fn._check_name in advanced:
            fn()

    REPORT["generated_at"] = datetime.now(timezone.utc).isoformat()

    total = sum(1 for v in REPORT["checks"].values() if v)
    print(f"\n📊 Results: {total}/{len(REPORT['checks'])} checks passed")

    with open("report.json", "w") as f:
        json.dump(REPORT, f, indent=2)
    print("📄 report.json generated")


if __name__ == "__main__":
    main()
