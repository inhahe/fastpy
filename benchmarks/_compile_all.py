"""Compile every benchmark in this checkout, copy the exes somewhere stable.

Run from the root of whichever fastpy checkout you want to measure; prints a
JSON map of {benchmark name: exe path}. Exists so `ab_bench.py` can build the
same workloads with two different compilers without importing both into one
interpreter, which is impossible -- `compiler` is a top-level package name and
only one copy can own it per process.

Usage:  python benchmarks/_compile_all.py <out_dir>
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_PYDIR = os.path.dirname(sys.executable)
if _PYDIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _PYDIR + os.pathsep + os.environ.get("PATH", "")

from compiler.pipeline import compile_source          # noqa: E402
from benchmarks.run_comparison import BENCHMARKS      # noqa: E402

NULL_SRC = "x = 1\n"


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    built = {}
    for name, _cat, src in [(n, c, p) for n, c, p, _ in BENCHMARKS] + \
                           [("__null__", "meta", NULL_SRC)]:
        r = compile_source(src)
        if not r.success:
            print(f"COMPILE FAIL: {name}", file=sys.stderr)
            continue
        dst = out / (name.replace(" ", "_").replace("+", "p")
                     .replace("(", "").replace(")", "") + ".exe")
        shutil.copy2(str(r.executable), str(dst))
        built[name] = str(dst)
    print(json.dumps(built))


if __name__ == "__main__":
    main()
