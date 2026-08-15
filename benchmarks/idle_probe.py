"""
Idle-CPU probe: wait for a *sustained* quiet machine, then benchmark.

Micro-benchmarks here run in 10-70ms and are dominated by scheduler noise,
so a run started during a momentary lull is worthless. This probe refuses to
start until the CPU has been continuously below a threshold for a long
window, and it *aborts and re-waits* if load reappears mid-run.

A full benchmark pass takes ~10s, so the default 300s quiet window is ~30x
the work it protects -- deliberately far more headroom than needed.

Usage:
    python benchmarks/idle_probe.py [--quiet-secs 300] [--threshold 25]
                                    [--runs 7] [--attempts 20] [--no-tests]

Writes:
    benchmarks/_probe.log          human-readable progress log
    benchmarks/_probe_status.json  machine-readable current state
    benchmarks/_bench_after.json   benchmark results (on success)
    benchmarks/_probe_report.md    final report w/ regressions (on success)
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOG = HERE / "_probe.log"
STATUS = HERE / "_probe_status.json"
BASELINE = HERE / "_bench_baseline.json"
AFTER = HERE / "_bench_after.json"
REPORT = HERE / "_probe_report.md"

# A benchmark pass pins ~1 core; on an N-core box that is 100/N percent of
# total. Allow that much headroom above the idle threshold while we run.
RUN_HEADROOM = max(15.0, 100.0 / max(psutil.cpu_count() or 1, 1) * 1.6)


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_status(**kw):
    kw["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    kw["pid"] = os.getpid()
    STATUS.write_text(json.dumps(kw, indent=2), encoding="utf-8")


def wait_for_quiet(threshold, quiet_secs, poll=5.0):
    """Block until CPU stays under `threshold` for `quiet_secs` straight."""
    psutil.cpu_percent(interval=None)  # prime
    time.sleep(1.0)
    quiet_since = None
    last_report = 0.0
    last_busy_report = time.monotonic()
    busy_min = 100.0
    busy_samples = 0
    busy_sum = 0.0
    while True:
        cpu = psutil.cpu_percent(interval=None)
        now = time.monotonic()
        # Heartbeat while busy. Without it the log goes silent for hours and
        # there is no way to tell a waiting probe from a dead one, nor whether
        # the threshold is merely strict or hopelessly so.
        if cpu >= threshold:
            busy_min = min(busy_min, cpu)
            busy_sum += cpu
            busy_samples += 1
            if now - last_busy_report >= 600:
                avg = busy_sum / max(busy_samples, 1)
                log(f"  still busy: cpu now {cpu:.1f}%, "
                    f"10-min avg {avg:.1f}%, min seen {busy_min:.1f}% "
                    f"(need < {threshold}%)")
                write_status(state="waiting_busy", cpu=cpu,
                             busy_min=round(busy_min, 1),
                             busy_avg=round(avg, 1), threshold=threshold)
                last_busy_report = now
                busy_min, busy_sum, busy_samples = 100.0, 0.0, 0
        if cpu < threshold:
            if quiet_since is None:
                quiet_since = now
                log(f"CPU {cpu:.1f}% < {threshold}% - starting quiet timer")
            held = now - quiet_since
            if now - last_report >= 60:
                log(f"  quiet {held:.0f}/{quiet_secs}s (cpu {cpu:.1f}%)")
                write_status(state="waiting", cpu=cpu,
                             quiet_held=round(held), quiet_needed=quiet_secs)
                last_report = now
            if held >= quiet_secs:
                log(f"Quiet window satisfied ({held:.0f}s under {threshold}%)")
                return
        else:
            if quiet_since is not None:
                held = now - quiet_since
                log(f"CPU spiked to {cpu:.1f}% after {held:.0f}s quiet "
                    f"- timer reset")
                write_status(state="reset", cpu=cpu, quiet_held=round(held),
                             quiet_needed=quiet_secs)
                last_report = now
            quiet_since = None
        time.sleep(poll)


class LoadWatcher:
    """Samples CPU during the run; records the worst reading seen."""

    def __init__(self, ceiling):
        self.ceiling = ceiling
        self.peak = 0.0
        self.tainted = False
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        psutil.cpu_percent(interval=None)
        while not self._stop.wait(0.5):
            cpu = psutil.cpu_percent(interval=None)
            self.peak = max(self.peak, cpu)
            if cpu > self.ceiling:
                self.tainted = True

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=3)


def run_benchmark(runs):
    """Run one benchmark pass, watching for contention. Returns (ok, peak)."""
    ceiling = ARGS.threshold + RUN_HEADROOM
    log(f"Running benchmark pass (runs={runs}, contention ceiling "
        f"{ceiling:.0f}%)")
    with LoadWatcher(ceiling) as w:
        t0 = time.perf_counter()
        p = subprocess.run(
            [sys.executable, str(HERE / "bench_fastpy_only.py"), "after",
             str(runs)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=1800)
        dur = time.perf_counter() - t0
    log(f"  pass finished in {dur:.1f}s, peak cpu {w.peak:.1f}%, "
        f"tainted={w.tainted}, rc={p.returncode}")
    if p.returncode != 0:
        log(f"  benchmark FAILED rc={p.returncode}\n{p.stderr[-1500:]}")
        return False, w.peak
    return (not w.tainted), w.peak


def compare():
    """Diff _bench_after.json against the baseline snapshot."""
    if not (BASELINE.exists() and AFTER.exists()):
        return None, []
    base = json.loads(BASELINE.read_text())
    cur = json.loads(AFTER.read_text())
    rows, regressions = [], []
    for name, c in cur.items():
        b = base.get(name, {})
        bm, cm = b.get("ms"), c.get("ms")
        if not bm or not cm:
            rows.append((name, bm, cm, None))
            continue
        pct = (bm - cm) / bm * 100.0
        rows.append((name, bm, cm, pct))
        if pct <= -15.0:  # >15% slower than baseline
            regressions.append((name, bm, cm, pct))
    regressions.sort(key=lambda r: r[3])
    return rows, regressions


def run_tests():
    """Correctness suite. Load-insensitive, so run it after the timing work."""
    log("Running differential test suite (correctness; load-insensitive)")
    t0 = time.perf_counter()
    p = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_differential.py", "tests/test_comprehensive.py",
         "tests/test_full_suite.py", "tests/test_cpython_adapted.py",
         "-q", "--timeout=300"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=5400)
    dur = time.perf_counter() - t0
    tail = [l for l in p.stdout.strip().splitlines() if l.strip()][-1:]
    summary = tail[0] if tail else f"rc={p.returncode}"
    log(f"  tests finished in {dur:.0f}s: {summary}")
    return summary, p.stdout[-4000:]


def write_report(rows, regressions, peak, test_summary, test_tail):
    L = ["# Idle-probe benchmark report", "",
         f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
         f"Quiet window: >={ARGS.quiet_secs}s continuously under "
         f"{ARGS.threshold}% CPU", f"Peak CPU during run: {peak:.1f}%", ""]
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              cwd=str(ROOT)).stdout.strip()
        L += [f"Commit: `{head}`", ""]
    except Exception:
        pass

    L += ["## Regressions (>15% slower than baseline)", ""]
    if regressions:
        L += ["| Benchmark | baseline | now | delta |",
              "|---|---|---|---|"]
        L += [f"| {n} | {b:.1f}ms | {c:.1f}ms | **{p:+.1f}%** |"
              for n, b, c, p in regressions]
    else:
        L += ["None. No benchmark is more than 15% slower than baseline."]

    L += ["", "## Full results", "",
          "| Benchmark | baseline | now | delta |", "|---|---|---|---|"]
    for n, b, c, p in rows:
        if p is None:
            L.append(f"| {n} | {b or '-'} | {c or '-'} | n/a |")
        else:
            L.append(f"| {n} | {b:.1f}ms | {c:.1f}ms | {p:+.1f}% |")

    L += ["", "## Correctness suite", "", f"`{test_summary}`", "",
          "<details><summary>tail</summary>", "", "```", test_tail.strip(),
          "```", "", "</details>", ""]
    REPORT.write_text("\n".join(L), encoding="utf-8")
    log(f"Wrote {REPORT}")


def main():
    log("=" * 68)
    log(f"Idle probe started (pid {os.getpid()}) - "
        f"need {ARGS.quiet_secs}s continuously under {ARGS.threshold}% CPU")
    log(f"Benchmark pass is ~10s, so the quiet window is ~"
        f"{ARGS.quiet_secs / 10:.0f}x the protected work")

    for attempt in range(1, ARGS.attempts + 1):
        log(f"--- attempt {attempt}/{ARGS.attempts} ---")
        write_status(state="waiting", attempt=attempt)
        wait_for_quiet(ARGS.threshold, ARGS.quiet_secs)
        write_status(state="benchmarking", attempt=attempt)
        ok, peak = run_benchmark(ARGS.runs)
        if not ok:
            log("Run was contended or failed - discarding and re-waiting")
            write_status(state="discarded", attempt=attempt, peak=peak)
            continue

        log("Clean run captured.")
        rows, regressions = compare()
        write_status(state="testing", attempt=attempt, peak=peak,
                     regressions=len(regressions))
        if ARGS.no_tests:
            test_summary, test_tail = "(skipped: --no-tests)", ""
        else:
            test_summary, test_tail = run_tests()
        write_report(rows, regressions, peak, test_summary, test_tail)
        write_status(state="done", attempt=attempt, peak=peak,
                     regressions=[r[0] for r in regressions],
                     report=str(REPORT))
        log(f"DONE. {len(regressions)} regression(s) >15%. Report: {REPORT}")
        return 0

    log("Gave up: never found a clean window.")
    write_status(state="gave_up")
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet-secs", type=float, default=300.0)
    ap.add_argument("--threshold", type=float, default=25.0)
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--attempts", type=int, default=20)
    ap.add_argument("--no-tests", action="store_true")
    ARGS = ap.parse_args()
    sys.exit(main())
