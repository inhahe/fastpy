"""
Helper script called from WSL to compile and run fastpy source.

Usage:
    python compile_helper.py <exe_path>
    (source code read from stdin, output written to stdout)

Exit codes:
    0  = compiled and ran successfully, stdout on stdout, stderr on stderr
    2  = compilation failed, error message on stderr
"""

import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compiler.pipeline import compile_source


def main():
    exe_path = Path(sys.argv[1])
    source = sys.stdin.read()

    result = compile_source(source, exe_path, source_filename="<repl>")
    if not result.success:
        errors = "; ".join(str(e) for e in result.errors)
        print(errors, file=sys.stderr)
        sys.exit(2)

    proc = subprocess.run(
        [str(result.executable)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(exe_path.parent),
    )
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
