"""
Stdlib module compilation cache for fastpy.

Manages per-module discovery and compilability testing of Python stdlib .py
files, caching results so that compilable modules can be source-merged into
user programs instead of routing through the CPython bridge.

Cache layout:
    ~/.fastpy/cache/stdlib/py314/
        <module_name>.json     # compilability verdict + metadata

Layer 2 (future — separate .obj caching):
    ~/.fastpy/cache/stdlib/py314/
        manifest.json          # master index (fastpy_version, llvm triple)
        <module_name>.obj      # compiled object file
        <module_name>.sigs     # exported function signatures

Cache invalidation uses content hashing (sha256) with mtime+size as a
fast-path skip, matching CPython's --check-hash-based-pycs strategy.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

# Version tag embedded in cache entries — bump when codegen changes make
# old compilability verdicts unreliable.
_CACHE_VERSION = "1"


@dataclass
class CacheEntry:
    """Cached compilability verdict for a single stdlib module."""
    compilable: bool
    source_hash: str
    mtime: float
    size: int
    prefixed_source: str | None  # only set when compilable=True
    cache_version: str = _CACHE_VERSION
    error: str | None = None     # error message when compilable=False


class StdlibResolver:
    """Locates pure-Python stdlib modules and classifies them."""

    def __init__(self, python_version: tuple[int, int] | None = None,
                 stdlib_dir: Path | None = None):
        if stdlib_dir is not None:
            self._stdlib_dir = stdlib_dir
        else:
            self._stdlib_dir = Path(sysconfig.get_path("stdlib"))
        self._pyver = python_version or (
            sys.version_info.major, sys.version_info.minor)
        # Modules with native LLVM IR implementations in codegen.py.
        # Never merge their source — codegen handles them directly.
        self._native_blocklist = _get_native_modules()
        # Modules known to fail compilation or that are too complex
        # for source merge (e.g., they use exec/eval extensively or
        # have metaprogramming that the AOT compiler can't handle).
        self._hard_blocklist: set[str] = set()
        # Cache find results
        self._find_cache: dict[str, Path | None] = {}

    @property
    def stdlib_dir(self) -> Path:
        return self._stdlib_dir

    def find_stdlib_module(self, module_name: str) -> Path | None:
        """Find a pure-Python stdlib module's .py source file.

        Returns None if:
        - module is in the native blocklist (handled by codegen)
        - module is a C extension with no .py source
        - module is a package we can't merge (complex __init__.py)
        - module not found in stdlib
        """
        if module_name in self._find_cache:
            return self._find_cache[module_name]

        result = self._find_impl(module_name)
        self._find_cache[module_name] = result
        return result

    def _find_impl(self, module_name: str) -> Path | None:
        # Never merge modules that codegen handles natively
        if module_name in self._native_blocklist:
            return None
        if module_name in self._hard_blocklist:
            return None

        # Skip dotted names for now (packages like xml.etree.ElementTree)
        if "." in module_name:
            return None

        # Skip private/internal modules
        if module_name.startswith("_"):
            return None

        # Look for module_name.py in stdlib
        candidate = self._stdlib_dir / (module_name + ".py")
        if candidate.is_file():
            return candidate

        # Look for package: module_name/__init__.py
        candidate = self._stdlib_dir / module_name / "__init__.py"
        if candidate.is_file():
            # Only merge simple packages (single __init__.py without
            # complex submodule imports). For now, skip packages entirely
            # and only merge single-file modules.
            return None

        return None

    def list_compilable_candidates(self) -> list[tuple[str, Path]]:
        """List all single-file pure-Python stdlib modules that could
        potentially be compiled. Does NOT test compilability — just
        returns modules that pass the basic filter."""
        results = []
        if not self._stdlib_dir.is_dir():
            return results

        for entry in sorted(self._stdlib_dir.iterdir()):
            if not entry.is_file() or entry.suffix != ".py":
                continue
            name = entry.stem
            # Apply same filters as find_stdlib_module
            if name.startswith("_"):
                continue
            if name in self._native_blocklist:
                continue
            if name in self._hard_blocklist:
                continue
            results.append((name, entry))
        return results


class StdlibCache:
    """Disk cache for stdlib module compilability verdicts."""

    def __init__(self, python_version: tuple[int, int] | None = None):
        pyver = python_version or (
            sys.version_info.major, sys.version_info.minor)
        self._cache_dir = (
            Path.home() / ".fastpy" / "cache" / "stdlib"
            / f"py{pyver[0]}{pyver[1]}")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem_cache: dict[str, CacheEntry] = {}

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def get(self, module_name: str, source_path: Path) -> CacheEntry | None:
        """Look up a cached compilability verdict.

        Returns None on cache miss (no entry, or entry is stale).
        Uses mtime+size as fast-path; falls back to content hash.
        """
        # Check in-memory cache first
        if module_name in self._mem_cache:
            entry = self._mem_cache[module_name]
            stat = source_path.stat()
            if entry.mtime == stat.st_mtime and entry.size == stat.st_size:
                return entry
            # mtime/size changed — check hash
            current_hash = _source_hash(source_path)
            if entry.source_hash == current_hash:
                # Content unchanged despite mtime change — update mtime
                entry.mtime = stat.st_mtime
                entry.size = stat.st_size
                return entry
            # Content changed — cache miss
            del self._mem_cache[module_name]
            return None

        # Check disk cache
        cache_file = self._cache_dir / f"{module_name}.json"
        if not cache_file.is_file():
            return None

        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        # Version check — invalidate if cache format changed
        if data.get("cache_version") != _CACHE_VERSION:
            cache_file.unlink(missing_ok=True)
            return None

        stat = source_path.stat()
        entry = CacheEntry(
            compilable=data["compilable"],
            source_hash=data["source_hash"],
            mtime=data["mtime"],
            size=data["size"],
            prefixed_source=data.get("prefixed_source"),
            cache_version=data.get("cache_version", "0"),
            error=data.get("error"),
        )

        # Fast path: mtime + size match
        if entry.mtime == stat.st_mtime and entry.size == stat.st_size:
            self._mem_cache[module_name] = entry
            return entry

        # Slow path: content hash
        current_hash = _source_hash(source_path)
        if entry.source_hash == current_hash:
            entry.mtime = stat.st_mtime
            entry.size = stat.st_size
            self._mem_cache[module_name] = entry
            # Update disk cache with new mtime
            self._write_entry(module_name, entry)
            return entry

        # Content changed — invalidate
        cache_file.unlink(missing_ok=True)
        return None

    def put(self, module_name: str, source_path: Path,
            compilable: bool, prefixed_source: str | None = None,
            error: str | None = None) -> CacheEntry:
        """Store a compilability verdict in the cache."""
        stat = source_path.stat()
        entry = CacheEntry(
            compilable=compilable,
            source_hash=_source_hash(source_path),
            mtime=stat.st_mtime,
            size=stat.st_size,
            prefixed_source=prefixed_source,
            error=error,
        )
        self._mem_cache[module_name] = entry
        self._write_entry(module_name, entry)
        return entry

    def is_compilable(self, module_name: str,
                      source_path: Path) -> bool | None:
        """Check if a module is compilable.

        Returns True/False from cache, or None on cache miss.
        """
        entry = self.get(module_name, source_path)
        if entry is None:
            return None
        return entry.compilable

    def _write_entry(self, module_name: str, entry: CacheEntry) -> None:
        """Write a cache entry to disk."""
        cache_file = self._cache_dir / f"{module_name}.json"
        data = {
            "compilable": entry.compilable,
            "source_hash": entry.source_hash,
            "mtime": entry.mtime,
            "size": entry.size,
            "cache_version": entry.cache_version,
        }
        if entry.prefixed_source is not None:
            data["prefixed_source"] = entry.prefixed_source
        if entry.error is not None:
            data["error"] = entry.error
        try:
            cache_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass  # cache write failure is non-fatal


def _source_hash(source_path: Path) -> str:
    """Compute a content hash for a source file."""
    content = source_path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:16]


def _get_native_modules() -> set[str]:
    """Return the set of module names handled natively by codegen.

    Imports from codegen.py at call time to avoid circular imports
    during module load.
    """
    try:
        from compiler.codegen import CodeGen
        return set(CodeGen._NATIVE_MODULES)
    except (ImportError, AttributeError):
        # Fallback if codegen can't be imported (e.g., during testing)
        return {
            "math", "json", "os", "os.path", "asyncio", "collections",
            "_collections", "typing", "abc", "functools", "_functools",
            "logging", "contextlib", "sys", "time", "itertools", "enum",
            "dataclasses", "random", "hashlib", "string", "pathlib",
            "copy", "operator", "io", "warnings", "base64", "uuid",
            "textwrap", "shutil", "glob", "tempfile", "heapq", "bisect",
            "traceback", "pprint", "unittest", "argparse", "decimal",
            "platform", "secrets",
        }


def test_compilability(module_name: str, source_path: Path) -> tuple[bool, str | None, str | None]:
    """Test whether a stdlib module can be compiled by fastpy.

    Returns (compilable, prefixed_source_or_none, error_or_none).
    """
    from compiler.pipeline import _strip_main_block, _prefix_module_defs

    source = source_path.read_text(encoding="utf-8")
    source = _strip_main_block(source)
    prefix = module_name.replace(".", "_")
    prefixed = _prefix_module_defs(source, prefix)

    # Wrap in a minimal program that the compiler can handle
    # (the prefixed source is just function/class defs + assignments —
    # it needs a top-level statement to be valid for compile_source)
    test_source = prefixed + "\npass\n"

    try:
        from compiler.pipeline import compile_source
        result = compile_source(test_source)
        if result.success:
            return True, prefixed, None
        else:
            err = "; ".join(str(e) for e in result.errors[:3])
            return False, None, err
    except Exception as e:
        return False, None, str(e)[:200]


def warm_cache(python_version: tuple[int, int] | None = None,
               verbose: bool = True) -> dict[str, bool]:
    """Pre-test all pure-Python stdlib modules and populate the cache.

    Returns a dict mapping module_name → compilable.
    """
    pyver = python_version or (
        sys.version_info.major, sys.version_info.minor)
    resolver = StdlibResolver(python_version=pyver)
    cache = StdlibCache(python_version=pyver)

    candidates = resolver.list_compilable_candidates()
    results: dict[str, bool] = {}
    total = len(candidates)

    if verbose:
        print(f"Testing {total} stdlib modules for compilability "
              f"(Python {pyver[0]}.{pyver[1]})...\n")

    compiled = 0
    failed = 0
    cached = 0

    for i, (name, path) in enumerate(candidates, 1):
        # Check cache first
        existing = cache.is_compilable(name, path)
        if existing is not None:
            results[name] = existing
            if existing:
                compiled += 1
            else:
                failed += 1
            cached += 1
            if verbose:
                status = "PASS" if existing else "FAIL"
                print(f"  [{i:3d}/{total}] {status} {name:30s} (cached)")
            continue

        # Test compilation
        import time
        t0 = time.time()
        compilable, prefixed, error = test_compilability(name, path)
        elapsed = time.time() - t0

        cache.put(name, path, compilable,
                  prefixed_source=prefixed, error=error)
        results[name] = compilable

        if compilable:
            compiled += 1
        else:
            failed += 1

        if verbose:
            status = "PASS" if compilable else "FAIL"
            detail = f" ({error[:50]})" if error else ""
            print(f"  [{i:3d}/{total}] {status} {name:30s} "
                  f"({elapsed:.1f}s){detail}")

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"RESULTS: {compiled} compilable, {failed} not compilable"
              f" ({cached} from cache)")
        print(f"Cache directory: {cache.cache_dir}")
        print(f"{'=' * 60}")

    return results
