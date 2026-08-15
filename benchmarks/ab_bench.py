"""
Paired A/B benchmarking: compare two checkouts on a machine you don't control.

`stable_bench.py` established that absolute timings here are not trustworthy
under load -- pinned to a dedicated core, at high priority, taking the minimum
of 15 runs and subtracting the process-spawn floor, the same binaries still
came out 1.20x to 2.01x slower with eight cores busy. The inflation is also
non-uniform across workloads, so it cannot be divided out by a single factor.
Absolute numbers therefore need a quiet machine, and this box has not offered
one for 18h.

The comparison, however, does not need absolute numbers. Both builds are
compiled up front and their runs are *interleaved* -- A, B, A, B, ... -- so
any drift in clock, cache pressure or scheduler behaviour lands on both sides
in the same proportion and cancels in the ratio. What survives is exactly the
question being asked: did this change make it slower?

Two guards on top of that:

- Interleaving is per-repetition, not per-benchmark, so a load spike partway
  through cannot land entirely on one side.
- The A/B order alternates between repetitions, so a systematic
  first-of-the-pair effect (cache warmed by the other build, say) does not
  accumulate in one direction.

`--synthetic-load N` is here to validate the claim: run it loaded and idle
and check that the *ratios* agree even though the absolute times do not.

Usage:
    python benchmarks/ab_bench.py <repo_a> <repo_b> [--runs 15]
                                  [--label x] [--synthetic-load 8]
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from benchmarks.stable_bench import (                 # noqa: E402
    SyntheticLoad, pick_quiet_core,
)

HIGH = getattr(subprocess, "HIGH_PRIORITY_CLASS", 0)


def build(repo: Path, out: Path) -> dict:
    """Compile every benchmark in `repo`, in `repo`'s own interpreter."""
    print(f"  building {repo.name} ...", end=" ", flush=True)
    p = subprocess.run(
        [sys.executable, str(repo / "benchmarks" / "_compile_all.py"),
         str(out)],
        capture_output=True, text=True, cwd=str(repo), timeout=3600)
    if p.returncode != 0:
        raise SystemExit(f"build failed in {repo}:\n{p.stderr[-3000:]}")
    exes = json.loads(p.stdout.strip().splitlines()[-1])
    print(f"{len(exes)} exes")
    return exes


def run_once(exe) -> float:
    t0 = time.perf_counter()
    p = subprocess.run([str(exe)], capture_output=True, timeout=300,
                       creationflags=HIGH)
    dt = (time.perf_counter() - t0) * 1000.0
    if p.returncode != 0:
        raise RuntimeError(f"{exe} rc={p.returncode}")
    return dt


def ab_times(exe_a, exe_b, runs):
    """Interleave A and B, alternating which goes first each repetition."""
    ta, tb = [], []
    for i in range(runs):
        if i % 2 == 0:
            ta.append(run_once(exe_a))
            tb.append(run_once(exe_b))
        else:
            tb.append(run_once(exe_b))
            ta.append(run_once(exe_a))
    return ta, tb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_a")
    ap.add_argument("repo_b")
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--label", default="ab")
    ap.add_argument("--synthetic-load", type=int, default=0)
    args = ap.parse_args()

    ra, rb = Path(args.repo_a).resolve(), Path(args.repo_b).resolve()
    tmp = HERE / "_ab_exes"
    exes_a = build(ra, tmp / "a")
    exes_b = build(rb, tmp / "b")

    core = pick_quiet_core()
    try:
        psutil.Process().cpu_affinity([core])
        pinned = True
    except Exception:
        pinned = False
    cpu0 = psutil.cpu_percent(interval=1.0)
    print(f"\ncore={core} pinned={pinned} runs={args.runs} "
          f"cpu={cpu0:.0f}% synthetic_load={args.synthetic_load}")

    with SyntheticLoad(args.synthetic_load, core):
        if args.synthetic_load:
            print(f"  loaded to {psutil.cpu_percent(interval=1.0):.0f}%")

        # The spawn floor is measured the same interleaved way, so it can be
        # removed from both sides using each side's own value.
        fa, fb = ab_times(exes_a["__null__"], exes_b["__null__"], args.runs)
        floor_a, floor_b = min(fa), min(fb)
        print(f"  spawn floor  A {floor_a:.1f}ms   B {floor_b:.1f}ms\n")

        results = {"_meta": {
            "repo_a": str(ra), "repo_b": str(rb), "runs": args.runs,
            "core": core, "pinned": pinned, "cpu": cpu0,
            "synthetic_load": args.synthetic_load,
            "floor_a": floor_a, "floor_b": floor_b,
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        }}

        print(f"{'benchmark':<30s} {'A net':>8s} {'B net':>8s} "
              f"{'B/A':>7s}  verdict")
        print("-" * 70)
        names = [n for n in exes_a if n != "__null__" and n in exes_b]
        for name in names:
            ta, tb = ab_times(exes_a[name], exes_b[name], args.runs)
            na = min(ta) - floor_a
            nb = min(tb) - floor_b
            # Below the resolution floor the ratio is meaningless: dividing
            # two sub-millisecond residuals amplifies noise without limit.
            if na < 3.0 or nb < 3.0:
                verdict, ratio = "spawn-dominated", None
            else:
                ratio = nb / na
                verdict = ("SLOWER" if ratio > 1.10 else
                           "faster" if ratio < 0.90 else "same")
            results[name] = {
                "a_min": min(ta), "b_min": min(tb), "a_net": na, "b_net": nb,
                "ratio": ratio, "verdict": verdict,
                "a_median": statistics.median(ta),
                "b_median": statistics.median(tb),
            }
            rs = f"{ratio:6.2f}x" if ratio else "     -"
            print(f"{name:<30s} {na:7.1f}m {nb:7.1f}m {rs}  {verdict}")

    out = HERE / f"_ab_{args.label}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
