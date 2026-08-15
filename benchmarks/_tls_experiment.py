"""Does reading the exception flag inline actually beat calling for it?

PERF-EXC-CHECK-IN-HOT-LOOP says a `fastpy_exc_pending()` call after every
possibly-raising operation costs ~2.5x on `dict lookup 1K keys x 1K`.  Adding
`readonly nounwind` to the declaration changed nothing, so the hypothesis that
the cost was LLVM re-loading around an opaque call is dead.  The remaining
hypothesis is that the cost is the cross-module call itself.

That is testable without touching the compiler: take the IR the compiler
already emits, textually swap each call for a load of the thread-local it
would have read, build both, and time them interleaved.  If the load is not
faster there is no point building TLS support into codegen.

**Answer: it is not.**  The inline load came out 0.971x — 3% — while deleting
the check outright (replace the call with `add i32 0, 0` so the branch folds)
recovered all of it.  So the cost is the branch and the block split, not the
call, and TLS support in codegen would buy nothing.  Kept because the same
question will be asked again about some other runtime predicate, and this is
how to answer it in a few minutes instead of arguing from the IR.

Usage:  python benchmarks/_tls_experiment.py [--runs 15]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from compiler.pipeline import compile_source        # noqa: E402
from compiler.toolchain import compile_and_link     # noqa: E402

SRC = (HERE / "_dict_src.py").read_text(encoding="utf-8")

DECL = 'declare i32 @"fastpy_exc_pending"()'
# `localexec` is the right model: the executable is statically linked, so the
# flag lives in the main module's own TLS block and needs no dynamic lookup.
TLS_GLOBAL = '@"fpy_exc_type" = external thread_local(localexec) global i32'
CALL_RE = re.compile(r'call i32 @"fastpy_exc_pending"\(\)')

HIGH = getattr(subprocess, "HIGH_PRIORITY_CLASS", 0)


def make_inline_variant(ir: str) -> str:
    """Swap every exc_pending call for a direct load of the flag."""
    if DECL not in ir:
        raise SystemExit("declaration not found; IR shape changed")
    n = len(CALL_RE.findall(ir))
    if not n:
        raise SystemExit("no exc_pending calls to replace")
    ir = ir.replace(DECL, DECL + "\n" + TLS_GLOBAL)
    ir = CALL_RE.sub('load i32, i32* @"fpy_exc_type"', ir)
    print(f"  replaced {n} calls")
    return ir


def run_once(exe: Path) -> tuple[float, str]:
    t0 = time.perf_counter()
    p = subprocess.run([str(exe)], capture_output=True, text=True,
                       timeout=300, creationflags=HIGH)
    dt = (time.perf_counter() - t0) * 1000.0
    if p.returncode != 0:
        raise RuntimeError(f"{exe} rc={p.returncode}\n{p.stderr[-2000:]}")
    return dt, p.stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=15)
    args = ap.parse_args()

    out = HERE / "_tls_exes"
    out.mkdir(parents=True, exist_ok=True)

    print("building call variant ...")
    r = compile_source(SRC, output=out / "call.exe")
    if not r.success:
        raise SystemExit(f"compile failed: {r.error}")
    exe_call = Path(r.executable)

    print("building inline-TLS variant ...")
    exe_tls = compile_and_link(make_inline_variant(r.ir), out / "tls.exe")

    # Same answer or the comparison is meaningless.
    _, o_call = run_once(exe_call)
    _, o_tls = run_once(exe_tls)
    print(f"  call -> {o_call}\n  tls  -> {o_tls}")
    if o_call != o_tls:
        raise SystemExit("outputs differ; the inline variant is not equivalent")

    ta, tb = [], []
    for i in range(args.runs):
        if i % 2 == 0:
            ta.append(run_once(exe_call)[0])
            tb.append(run_once(exe_tls)[0])
        else:
            tb.append(run_once(exe_tls)[0])
            ta.append(run_once(exe_call)[0])

    a, b = min(ta), min(tb)
    print(f"\ncall   min {a:7.1f}ms")
    print(f"inline min {b:7.1f}ms")
    print(f"ratio      {b / a:6.3f}x  (<1 means the inline load is faster)")


if __name__ == "__main__":
    main()
