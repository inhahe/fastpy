"""
Entry point for: python -m compiler <source.py> [-o output]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compiler.pipeline import compile_file


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fastpy",
        description="Compile Python source to a native executable.",
    )
    parser.add_argument("source", type=Path, nargs="?", default=None,
                        help="Python source file to compile")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output executable path")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show detailed compilation info")
    parser.add_argument("-t", "--free-threaded", action="store_true",
                        help="Enable free-threaded mode (no GIL, per-object locks)")
    parser.add_argument("--threading", choices=["none", "gil", "free"],
                        default=None,
                        help="Threading mode: none (default), gil, or free")
    parser.add_argument("--int64", action="store_true",
                        help="Use i64 integers with overflow detection (no BigInt fallback, raises OverflowError)")
    parser.add_argument("--python-version", type=str, default=None,
                        metavar="VER",
                        help='Target Python version (e.g. "3.12", "3.14"). '
                             'Default: current Python.')
    parser.add_argument("--list-pythons", action="store_true",
                        help="List discovered Python installations and exit")
    parser.add_argument("-T", "--typed", action="store_true",
                        help="Use type annotations for fast-path code generation "
                             "(native LLVM ops for annotated int/float/bool vars)")
    parser.add_argument("--no-stdlib-merge", action="store_true",
                        help="Disable stdlib source merging (use CPython bridge "
                             "for all stdlib modules)")
    parser.add_argument("--warm-stdlib-cache", action="store_true",
                        help="Pre-test all stdlib modules for compilability, "
                             "populate the cache, and exit")
    parser.add_argument("--repl", action="store_true",
                        help="Start interactive REPL (compile-and-run each input)")
    parser.add_argument("--analyze", action="store_true",
                        help="Produce optimization analysis report showing "
                             "which code patterns prevent fast-path optimizations")
    parser.add_argument("--analyze-json", action="store_true",
                        help="Output analysis report as JSON (implies --analyze)")

    args = parser.parse_args()
    if args.analyze_json:
        args.analyze = True

    if args.repl:
        from compiler.repl import start_repl
        start_repl()
        return 0

    if args.list_pythons:
        from compiler.toolchain import discover_pythons
        pythons = discover_pythons()
        if not pythons:
            print("No Python installations found.", file=sys.stderr)
            return 1
        for p in pythons:
            current = " (current)" if p.executable == Path(sys.executable) else ""
            print(f"Python {p.version_str:5s}  {p.executable}{current}")
        return 0

    if args.warm_stdlib_cache:
        from compiler.stdlib_cache import warm_cache
        warm_cache()
        return 0

    if args.source is None:
        parser.error("the following arguments are required: source"
                     " (or use --repl for interactive mode)")

    if not args.source.exists():
        print(f"Error: {args.source} not found", file=sys.stderr)
        return 1

    # Determine threading mode
    threading_mode = 0  # default: single-threaded
    if args.free_threaded:
        threading_mode = 2
    elif args.threading:
        threading_mode = {"none": 0, "gil": 1, "free": 2}[args.threading]

    result = compile_file(args.source, args.output,
                          threading_mode=threading_mode,
                          int64_mode=args.int64,
                          typed_mode=args.typed,
                          python_version=args.python_version,
                          merge_stdlib=not args.no_stdlib_merge,
                          analyze=args.analyze)

    if result.success:
        print(f"Compiled: {result.executable}")
    else:
        for err in result.errors:
            msg = str(err)
            # SyntaxError messages from traceback.format_exception_only()
            # are already nicely formatted with source line + caret.
            # Print them directly instead of prefixing with "Error:".
            if msg.startswith(("SyntaxError:", "  File ")):
                print(msg, file=sys.stderr)
            else:
                print(f"Error: {msg}", file=sys.stderr)

    # Print analysis report (even on failure — codegen findings
    # are available if the failure was in linking, not codegen)
    if args.analyze and result.analysis_report:
        if args.analyze_json:
            print(result.analysis_report.to_json_str())
        else:
            print(result.analysis_report.to_text(), file=sys.stderr)

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
