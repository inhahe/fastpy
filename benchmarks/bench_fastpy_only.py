"""
fastpy-only benchmark runner for optimization work.

Reuses the BENCHMARKS defined in run_comparison.py, compiles each with
fastpy, times the resulting executable (best-of-N), and writes a JSON
snapshot so before/after runs can be diffed.

Usage:
    python benchmarks/bench_fastpy_only.py [label] [runs]

Writes benchmarks/_bench_<label>.json
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure python3XX.dll on PATH for compiled exes
_python_dir = os.path.dirname(sys.executable)
if _python_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _python_dir + os.pathsep + os.environ.get("PATH", "")

from compiler.pipeline import compile_source
from benchmarks.run_comparison import BENCHMARKS


def time_exe(exe_path, runs, timeout=120):
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        out = subprocess.run([str(exe_path)], capture_output=True,
                             text=True, timeout=timeout)
        t1 = time.perf_counter()
        if out.returncode != 0:
            return None, out.stderr[:200]
        times.append((t1 - t0) * 1000)
    return min(times), None


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "run"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    results = {}
    for name, category, py_src, cpp_src in BENCHMARKS:
        print(f"  {name}...", end=" ", flush=True)
        t_c0 = time.perf_counter()
        r = compile_source(py_src)
        compile_ms = (time.perf_counter() - t_c0) * 1000
        if not r.success:
            print("SKIP (compile fail)")
            results[name] = {"category": category, "ms": None,
                             "compile_ms": compile_ms}
            continue
        ms, err = time_exe(r.executable, runs)
        results[name] = {"category": category, "ms": ms,
                         "compile_ms": compile_ms, "err": err}
        if ms is not None:
            print(f"{ms:.1f}ms  (compile {compile_ms:.0f}ms)")
        else:
            print(f"RUN FAIL: {err}")

    out_path = Path(__file__).parent / f"_bench_{label}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_path}")

    # If a baseline exists and this isn't it, print a comparison
    base_path = Path(__file__).parent / "_bench_baseline.json"
    if base_path.exists() and label != "baseline":
        base = json.loads(base_path.read_text())
        print(f"\n{'Benchmark':<30s} {'base':>9s} {label:>9s} {'delta':>9s}")
        print("-" * 60)
        for name, cur in results.items():
            b = base.get(name, {})
            bm, cm = b.get("ms"), cur.get("ms")
            if bm and cm:
                pct = (bm - cm) / bm * 100.0
                print(f"{name:<30s} {bm:8.1f}m {cm:8.1f}m {pct:+7.1f}%")


if __name__ == "__main__":
    main()
