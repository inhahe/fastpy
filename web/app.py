"""
fastpy playground — web interface for the fastpy compiler REPL.

It compiles in this process, so it needs llvmlite (web/requirements.txt).

Windows (direct):
    python web/app.py

WSL (via gunicorn, run from the checkout):
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

# The REPL imports the compiler, and with it llvmlite, only when it first
# compiles: importing llvmlite here makes a server without it fail as it
# starts, naming the package, rather than on its first request.
import llvmlite  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# `compiler` is a top-level package of the checkout, which is not installed.
# gunicorn, run from the checkout, has it on sys.path already; running this
# file directly puts web/ there instead.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from compiler.repl import ReplSession  # noqa: E402

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
        repl = ReplSession()
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
