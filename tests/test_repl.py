"""
ReplSession keeps the executables it compiles in a temp dir of its own.

The web playground drops a session by deleting its last reference (on
expiry, on eviction and on reset) and keeps serving, so a dir that outlives
its session is never removed: every input a visitor ever typed stays on disk
as an executable.
"""

from __future__ import annotations

import gc

from compiler.repl import ReplSession


def test_temp_dir_goes_with_the_session():
    session = ReplSession()
    tmp_dir = session._tmp_dir
    assert session.eval_line("print(6 * 7)") == "42"
    assert any(tmp_dir.iterdir()), "the compiled executable should be in it"

    del session
    gc.collect()
    assert not tmp_dir.exists()
