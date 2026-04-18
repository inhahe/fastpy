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
    parser.add_argument("source", type=Path, help="Python source file to compile")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output executable path")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show detailed compilation info")

    args = parser.parse_args()

    if not args.source.exists():
        print(f"Error: {args.source} not found", file=sys.stderr)
        return 1

    result = compile_file(args.source, args.output)

    if result.success:
        print(f"Compiled: {result.executable}")
        return 0
    else:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
