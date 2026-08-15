"""Time codegen alone (no MSVC), so a compile-time A/B isn't drowned in linking."""
import ast, io, contextlib, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compiler.codegen import CodeGen
from benchmarks.run_comparison import BENCHMARKS

srcs = [p for _n, _c, p, _x in BENCHMARKS]
trees = [ast.parse(s) for s in srcs]
ts = []
for _ in range(7):
    t0 = time.perf_counter()
    for s in srcs:
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            CodeGen().generate(ast.parse(s))
    ts.append(time.perf_counter() - t0)
print(f"{min(ts):.4f} {statistics.median(ts):.4f}")
