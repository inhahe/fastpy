"""
Load-tolerant benchmark runner: measure on a busy machine, honestly.

`idle_probe.py` tried to make the *machine* quiet enough to trust a naive
measurement. On this box that never happened -- 18h44m of waiting produced a
longest quiet streak of 45s against a 300s requirement, because two disk
scanners pulse across the threshold every ~10s. Waiting is the wrong lever.

What this does instead, in order of how much each one actually mattered:

1.  **Subtract the process-spawn floor.**  `bench_fastpy_only.py` times
    `subprocess.run(exe)`, so every number includes Windows process creation.
    That floor is ~12ms here, while eight of the sixteen benchmarks *total*
    under 16ms -- the fastest two measure less than the floor itself. Timing
    was therefore reporting mostly startup. A trivial program is compiled and
    timed the same way in the same session, and its min is subtracted.

2.  **Report dispersion, not just the winner.**  `min` is the right estimator
    -- contention only ever makes a run slower, so the fastest run is the
    least-disturbed one -- but a lone lucky sample and a tight cluster are
    very different evidence and the old runner returned a bare float for
    both.  Every measurement now carries its spread, and a measurement whose
    spread is wide is reported as untrustworthy rather than quietly used.

3.  **Flag degenerate workloads.**  Once the floor is subtracted, several
    benchmarks have essentially nothing left, because LLVM closes their loops
    into a constant-time form: raising `function calls 10M` to 1000M
    iterations costs 1.3ms, i.e. 100x the work for free. Such a benchmark
    cannot measure the throughput it is named for. It is not useless -- it
    still detects the catastrophic case where the loop stops being closable
    -- but a percentage delta on it means something quite different, so it is
    labelled instead of being silently mixed in with the real ones.

4.  **Pin and prioritise.**  One core is chosen (the quietest at startup),
    the runner pins itself so children inherit the affinity, and children run
    at HIGH_PRIORITY_CLASS. This is listed last on purpose: it is the part
    everyone reaches for first and it was worth far less here than (1).

`--synthetic-load N` exists to *test* the above rather than to use it: it
loads N other cores on purpose, so the same binaries can be measured under
contention and the numbers compared. A method that claims to tolerate load
should be made to prove it.

Usage:
    python benchmarks/stable_bench.py [label] [--runs 15] [--synthetic-load 8]

Writes benchmarks/_stable_<label>.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Compiled exes need python3XX.dll on PATH.
_PYDIR = os.path.dirname(sys.executable)
if _PYDIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _PYDIR + os.pathsep + os.environ.get("PATH", "")

from compiler.pipeline import compile_source          # noqa: E402
from benchmarks.run_comparison import BENCHMARKS      # noqa: E402

HERE = Path(__file__).resolve().parent

# A null program: same compile pipeline, same exe format, no work. Its runtime
# is the process-creation floor that every other measurement sits on top of.
NULL_SRC = "x = 1\n"

# Below this many ms of work-after-floor, a benchmark is not measuring its
# workload -- it is measuring Windows. Chosen as ~3x the run-to-run spread of
# the floor itself, so it is a statement about resolution, not a preference.
DEGENERATE_MS = 3.0

# A spread wider than this (as a fraction of the min) means the machine moved
# under us enough that even the minimum is suspect.
SPREAD_WARN = 0.25


def pick_quiet_core() -> int:
    """Index of the least-busy core, sampled over a short window."""
    psutil.cpu_percent(percpu=True)
    time.sleep(1.0)
    per = psutil.cpu_percent(percpu=True)
    # Core 0 handles a disproportionate share of interrupts on Windows, so it
    # is excluded when there is any alternative.
    order = sorted(range(len(per)), key=lambda i: (i == 0, per[i]))
    return order[0]


def time_exe(exe, runs, timeout=300):
    """Run `exe` `runs` times, returning every timing in ms."""
    times = []
    flags = getattr(subprocess, "HIGH_PRIORITY_CLASS", 0)
    for _ in range(runs):
        t0 = time.perf_counter()
        p = subprocess.run([str(exe)], capture_output=True, timeout=timeout,
                           creationflags=flags)
        t1 = time.perf_counter()
        if p.returncode != 0:
            return None, f"rc={p.returncode} {p.stderr[:200]!r}"
        times.append((t1 - t0) * 1000.0)
    return times, None


def summarise(times):
    """Reduce raw timings to min + the evidence for trusting it."""
    ts = sorted(times)
    lo = ts[0]
    return {
        "min": lo,
        "p25": ts[len(ts) // 4],
        "median": statistics.median(ts),
        "max": ts[-1],
        "n": len(ts),
        # How far the typical run sits above the best one. Small means the
        # min is a plateau (trustworthy); large means it is a lucky outlier.
        "spread": (statistics.median(ts) - lo) / lo if lo else None,
    }


class SyntheticLoad:
    """Busy-spins N processes on cores other than `avoid`, for validation."""

    def __init__(self, n, avoid):
        self.n, self.avoid, self.procs = n, avoid, []

    def __enter__(self):
        if self.n <= 0:
            return self
        cores = [c for c in range(psutil.cpu_count()) if c != self.avoid]
        for i in range(self.n):
            p = subprocess.Popen(
                [sys.executable, "-c",
                 "\nwhile True:\n    pass\n"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                psutil.Process(p.pid).cpu_affinity([cores[i % len(cores)]])
            except Exception:
                pass
            self.procs.append(p)
        time.sleep(2.0)  # let the load actually ramp
        return self

    def __exit__(self, *exc):
        # Only ever the PIDs this class created, never by process name.
        for p in self.procs:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label", nargs="?", default="run")
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--synthetic-load", type=int, default=0)
    args = ap.parse_args()

    core = pick_quiet_core()
    try:
        psutil.Process().cpu_affinity([core])   # children inherit this
        pinned = True
    except Exception as e:
        print(f"  (could not pin: {e})")
        pinned = False

    cpu_now = psutil.cpu_percent(interval=1.0)
    print(f"core={core} pinned={pinned} runs={args.runs} "
          f"machine_cpu={cpu_now:.0f}% synthetic_load={args.synthetic_load}")

    with SyntheticLoad(args.synthetic_load, core):
        if args.synthetic_load:
            print(f"  synthetic load: {psutil.cpu_percent(interval=1.0):.0f}% "
                  f"machine cpu")

        rn = compile_source(NULL_SRC)
        assert rn.success, rn.errors
        null_times, err = time_exe(rn.executable, args.runs)
        assert null_times, err
        null = summarise(null_times)
        print(f"  spawn floor: {null['min']:.1f}ms "
              f"(median {null['median']:.1f}, spread {null['spread']:.0%})\n")

        results = {"_meta": {
            "label": args.label, "core": core, "pinned": pinned,
            "runs": args.runs, "synthetic_load": args.synthetic_load,
            "machine_cpu": cpu_now, "floor": null,
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        }}

        print(f"{'benchmark':<30s} {'total':>8s} {'net':>8s} "
              f"{'spread':>7s}  note")
        print("-" * 68)
        for name, category, py_src, _cpp in BENCHMARKS:
            r = compile_source(py_src)
            if not r.success:
                results[name] = {"category": category, "error": "compile"}
                print(f"{name:<30s} {'COMPILE FAIL':>25s}")
                continue
            times, err = time_exe(r.executable, args.runs)
            if not times:
                results[name] = {"category": category, "error": err}
                print(f"{name:<30s} {'RUN FAIL':>25s}")
                continue
            s = summarise(times)
            net = s["min"] - null["min"]
            notes = []
            if net < DEGENERATE_MS:
                notes.append("SPAWN-DOMINATED")
            if s["spread"] > SPREAD_WARN:
                notes.append("NOISY")
            results[name] = {
                "category": category, **s, "net": net,
                "degenerate": net < DEGENERATE_MS,
                "noisy": s["spread"] > SPREAD_WARN,
            }
            print(f"{name:<30s} {s['min']:7.1f}m {net:7.1f}m "
                  f"{s['spread']:6.0%}  {' '.join(notes)}")

    out = HERE / f"_stable_{args.label}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
