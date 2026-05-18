"""
Generate adapted CPython test files for fastpy differential testing.

Downloads raw CPython test files from GitHub (cached locally in tests/cpython_raw/)
and produces adapted self-contained programs in tests/cpython_adapted/.

Usage:
    python -m tests.cpython_adapter.generate          # generate all
    python -m tests.cpython_adapter.generate bisect   # generate specific module
    python -m tests.cpython_adapter.generate --list   # list available modules

For stdlib tests: inlines the pure-Python module source so both CPython and
fastpy run the SAME pure-Python implementation. This tests fastpy's ability
to compile and run stdlib modules correctly.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from tests.cpython_adapter.adapter import adapt_stdlib_test, adapt_language_test

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Pin to a specific CPython tag for reproducibility
_CPYTHON_TAG = "v3.13.0"
_RAW_URL = f"https://raw.githubusercontent.com/python/cpython/{_CPYTHON_TAG}/Lib/test"

_RAW_DIR = _PROJECT_ROOT / "tests" / "cpython_raw"
_OUT_DIR = _PROJECT_ROOT / "tests" / "cpython_adapted"

# Manifest: which CPython tests to adapt and how
# mode: "stdlib" = inline the module source; "language" = just strip boilerplate
MANIFEST: dict[str, dict] = {
    # ── Stdlib module tests (inline pure-Python source) ─────────────────
    "test_bisect": {
        "mode": "stdlib",
        "module": "bisect",
        "skip_methods": {
            "test_keyword_args",          # uses keyword-only syntax
            "test_precomputed",           # uses large data from test.support
            "test_lt_returns_non_bool",   # uses local class not extractable
            "test_lt_returns_notimplemented",  # uses local class
            "test_listDerived",           # uses self.data from setUp
        },
        "skip_classes": {"TestBisectC", "TestInsortC"},  # C-extension variants
    },
    "test_heapq": {
        "mode": "stdlib",
        "module": "heapq",
        "skip_methods": {
            "test_nbest",             # uses random
            "test_nsmallest",         # uses random
            "test_nlargest",          # uses random
            "test_nbest_lazy",        # uses random + itertools
            "test_merge",             # uses itertools
            "test_merge_stability",   # uses itertools
            "test_merge_does_not_suppress_index_error",  # complex
            "test_py_functions",      # uses class-level func_names attribute
        },
        "skip_classes": {"TestHeapC", "TestErrorHandling", "TestMerge", "TestModules"},
    },
    "test_colorsys": {
        "mode": "stdlib",
        "module": "colorsys",
        "skip_methods": set(),
        "skip_classes": set(),
    },
    "test_graphlib": {
        "mode": "stdlib",
        "module": "graphlib",
        "skip_methods": {
            "test_calls_before_prepare",  # uses assertRaises context mgr
        },
        "skip_classes": set(),
    },
    "test_statistics": {
        "mode": "stdlib",
        "module": "statistics",
        "skip_methods": {
            "test_binomialtest",   # complex scipy-like
            "test_correlation",    # uses NormalDist
            "test_covariance",     # uses NormalDist
            "test_linear_regression",  # uses NormalDist
            "test_normal_dist",    # NormalDist class
        },
        "skip_classes": {
            "TestNormalDist", "TestBinomialDist",
            "TestKDE", "TestLinearRegression",
        },
    },
    "test_textwrap": {
        "mode": "stdlib",
        "module": "textwrap",
        "skip_methods": set(),
        "skip_classes": set(),
    },
    # ── Language feature tests (no stdlib inlining) ────────────────────
    # These test Python semantics that fastpy should handle natively.
    # (We already have hand-adapted versions; these are for when we want
    # to pull directly from CPython's test suite.)
}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_test(test_name: str) -> Path:
    """Download a CPython test file if not already cached."""
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = _RAW_DIR / f"{test_name}.py"
    if dest.exists():
        return dest

    url = f"{_RAW_URL}/{test_name}.py"
    print(f"  Downloading {url} ...", end=" ", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        print("OK")
    except Exception as e:
        print(f"FAILED: {e}")
        return dest  # return path even if download failed
    return dest


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

def generate_one(test_name: str, config: dict) -> bool:
    """Generate one adapted test. Returns True on success."""
    mode = config["mode"]
    module_name = config.get("module", test_name.replace("test_", ""))
    skip_methods = config.get("skip_methods", set())
    skip_classes = config.get("skip_classes", set())

    # Download raw test
    raw_path = download_test(test_name)
    if not raw_path.exists():
        print(f"  ERROR: Could not find {raw_path}")
        return False

    raw_source = raw_path.read_text(encoding="utf-8", errors="replace")

    # Adapt
    if mode == "stdlib":
        adapted = adapt_stdlib_test(
            raw_source, module_name,
            skip_methods=skip_methods,
            skip_classes=skip_classes,
        )
    elif mode == "language":
        adapted = adapt_language_test(
            raw_source, test_name,
            skip_methods=skip_methods,
            skip_classes=skip_classes,
        )
    else:
        print(f"  ERROR: Unknown mode '{mode}'")
        return False

    if adapted is None:
        print(f"  ERROR: Adaptation failed for {test_name}")
        return False

    # Write output
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Use _stdlib suffix to distinguish from hand-crafted versions
    out_name = f"{test_name}_stdlib.py" if mode == "stdlib" else f"{test_name}_auto.py"
    out_path = _OUT_DIR / out_name
    out_path.write_text(adapted, encoding="utf-8")
    print(f"  Generated: {out_path.name} ({len(adapted)} bytes)")
    return True


def generate_all(filter_name: str = None):
    """Generate all (or filtered) adapted tests."""
    print(f"CPython test adapter — tag: {_CPYTHON_TAG}")
    print(f"Output directory: {_OUT_DIR}")
    print()

    success = 0
    failed = 0

    for test_name, config in sorted(MANIFEST.items()):
        if filter_name and filter_name not in test_name:
            continue
        print(f"[{config['mode']}] {test_name}:")
        if generate_one(test_name, config):
            success += 1
        else:
            failed += 1

    print()
    print(f"Done: {success} generated, {failed} failed")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--list" in args:
        for name, cfg in sorted(MANIFEST.items()):
            print(f"  {name} [{cfg['mode']}] -> {cfg.get('module', name)}")
    elif args:
        generate_all(filter_name=args[0])
    else:
        generate_all()
