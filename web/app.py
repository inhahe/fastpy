"""
fastpy playground — web interface for the fastpy compiler REPL.

Windows (direct):
    python web/app.py

WSL (via gunicorn, compiles through Windows Python):
    gunicorn -w 1 --bind 127.0.0.1:5001 --timeout 60 web.app:app
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import threading
from pathlib import Path

from flask import Flask, request, jsonify, render_template

from compiler.repl import ReplSession

# ---------------------------------------------------------------------------
# Detect environment: Windows (local compile) vs WSL (remote compile)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# When running from WSL, the compiler isn't importable directly — we
# shell out to Windows Python via the compile_helper script.
try:
    import llvmlite  # noqa: F401 — just checking availability
    # Compiler available locally (Windows, or WSL with llvmlite installed).
    _PYTHON_EXE = None
    _HELPER_SCRIPT = None
except ImportError:
    if sys.platform == "win32":
        raise  # llvmlite should always be present on Windows
    # WSL without llvmlite: fall back to Windows Python.
    _PYTHON_EXE = "/mnt/d/python314/python.exe"
    _HELPER_SCRIPT = r"D:\visual studio projects\fastpy\web\compile_helper.py"

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__,
            template_folder=str(PROJECT_ROOT / "web" / "templates"),
            static_folder=str(PROJECT_ROOT / "web" / "static"))
app.secret_key = os.urandom(32)

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()

SESSION_TIMEOUT = 1800      # 30 min idle expiry
MAX_SESSIONS = 50
MAX_SOURCE_LEN = 10_000     # 10 KB per input
MAX_OUTPUT_LEN = 100_000    # 100 KB output cap
MAX_LOG_STATEMENTS = 200


def _make_repl() -> ReplSession:
    return ReplSession(python_exe=_PYTHON_EXE,
                       helper_script=_HELPER_SCRIPT)


def _get_or_create_session(sid: str | None, ip: str) -> tuple[str, ReplSession]:
    now = time.time()
    with _sessions_lock:
        stale = [k for k, v in _sessions.items()
                 if now - v["last_access"] > SESSION_TIMEOUT]
        for k in stale:
            del _sessions[k]

        if sid and sid in _sessions:
            entry = _sessions[sid]
            entry["last_access"] = now
            return sid, entry["repl"]

        if len(_sessions) >= MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: _sessions[k]["last_access"])
            del _sessions[oldest]

        new_id = uuid.uuid4().hex[:16]
        repl = _make_repl()
        _sessions[new_id] = {"repl": repl, "last_access": now, "ip": ip}
        return new_id, repl


def _destroy_session(sid: str):
    with _sessions_lock:
        _sessions.pop(sid, None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("playground.html")


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(silent=True) or {}
    source = data.get("source", "").strip()
    sid = data.get("session_id")

    if not source:
        return jsonify({"error": "empty input", "session_id": sid})

    if len(source) > MAX_SOURCE_LEN:
        return jsonify({"error": f"input too long ({len(source)} chars, "
                                 f"max {MAX_SOURCE_LEN})",
                        "session_id": sid})

    ip = request.remote_addr or "unknown"
    sid, repl = _get_or_create_session(sid, ip)

    if len(repl._statement_log) > MAX_LOG_STATEMENTS:
        return jsonify({
            "error": f"Session too large ({len(repl._statement_log)} "
                     "statements). Use Reset to start fresh.",
            "session_id": sid,
        })

    t0 = time.perf_counter()
    try:
        result = repl.eval_line(source)
    except Exception as e:
        result = f"Internal error: {e}"
    elapsed = time.perf_counter() - t0

    output = result or ""
    if len(output) > MAX_OUTPUT_LEN:
        output = output[:MAX_OUTPUT_LEN] + "\n... (output truncated)"

    return jsonify({
        "output": output,
        "session_id": sid,
        "elapsed": round(elapsed, 2),
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    data = request.get_json(silent=True) or {}
    sid = data.get("session_id")
    if sid:
        _destroy_session(sid)
    return jsonify({"ok": True, "session_id": None})


# ---------------------------------------------------------------------------
# Main (Windows development server)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("fastpy playground starting on http://localhost:5001")
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
