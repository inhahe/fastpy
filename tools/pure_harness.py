#!/usr/bin/env python3
"""Fast native-Linux + AddressSanitizer harness for fastpy **pure-mode** runtime work.

Why this exists
---------------
Pure mode (no embedded CPython) is normally only exercised by cross-compiling to
`x86_64-slateos` and booting SlateOS under QEMU — a ~6 minute round trip per
change. That is far too slow to iterate on a runtime bug, and it gives no
memory-safety signal at all: a wild pointer just silently corrupts the heap and
shows up as "some later check returned the wrong answer".

This harness compiles **the exact same artifacts** — the real `CodeGen` IR for a
given Python source, plus the real pure-mode runtime TUs
(`toolchain._SLATEOS_RUNTIME_NAMES`, built with `-DFPY_PURE_MODE`) — as a native
x86_64-linux binary under WSL clang, with AddressSanitizer + UndefinedBehaviorSanitizer
enabled, and runs it. Turnaround is seconds, and out-of-bounds reads/writes that
QEMU would hide become loud, located diagnostics.

It is a *development* tool: on-target QEMU boot remains the authority for
SlateOS-specific behavior (syscall ABI, loader, VFS). Use this to get the
runtime logic and memory safety right, then confirm with one boot.

Usage
-----
    python tools/pure_harness.py <source.py>      # run a Python file
    python tools/pure_harness.py -c "print(1)"    # run an inline snippet
    python tools/pure_harness.py --keep ...       # keep the build dir for gdb

Exit status mirrors the compiled program's own exit status, so a bitmask-style
self-test can be asserted directly from a shell.
"""

from __future__ import annotations

import argparse
import ast
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNTIME_DIR = REPO / "runtime"

# Sanitizers worth having on by default: ASan catches the out-of-bounds reads
# that the OBJ refcount dispatcher can make against undersized buffers; UBSan
# catches the misaligned/invalid-value cases that ASan misses.
SAN_FLAGS = [
    "-fsanitize=address,undefined",
    "-fno-omit-frame-pointer",
    "-fno-sanitize-recover=all",
    "-g",
]


def _to_wsl(p: Path) -> str:
    """Translate a Windows path to its WSL /mnt/<drive> equivalent."""
    s = p.resolve().as_posix()
    if len(s) > 1 and s[1] == ":":
        return f"/mnt/{s[0].lower()}{s[2:]}"
    return s


def _wsl(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    # Everything is routed through `bash -c`, so each argument must be shell
    # quoted — the repo lives under "visual studio projects", i.e. paths contain
    # spaces. `VAR=value` prefixes survive quoting unchanged (no metacharacters).
    cmd = ["wsl", "-d", "Ubuntu", "--", "bash", "-c"]
    line = " ".join(shlex.quote(a) if " " in a else a for a in args)
    if cwd is not None:
        line = f"cd {shlex.quote(_to_wsl(cwd))} && {line}"
    cmd.append(line)
    return subprocess.run(cmd, capture_output=True, text=True)


def _neutralize_target(ll: str) -> str:
    """Drop the cross-target triple/datalayout so the IR builds for the host.

    The codegen stamps the IR for `x86_64-slateos` with a static-reloc/large
    code model. For the harness we want a plain host build, and clang supplies
    the right defaults when both directives are absent.
    """
    ll = re.sub(r'^target triple\s*=.*$', "", ll, flags=re.MULTILINE)
    ll = re.sub(r'^target datalayout\s*=.*$', "", ll, flags=re.MULTILINE)
    return ll


def build_and_run(src: str, keep: bool = False, verbose: bool = False) -> int:
    from compiler.codegen import CodeGen
    from compiler import toolchain

    work = Path(tempfile.mkdtemp(prefix="fpy-pure-", dir=str(REPO / "build"))) \
        if (REPO / "build").is_dir() else Path(tempfile.mkdtemp(prefix="fpy-pure-"))

    try:
        ll_text = _neutralize_target(CodeGen().generate(ast.parse(src)))
        ll_path = work / "prog.ll"
        ll_path.write_text(ll_text, encoding="utf-8")

        objs: list[str] = []

        # 1. The program IR. -Wno-override-module silences the stripped triple.
        r = _wsl(
            ["clang", "-c", "prog.ll", "-o", "prog.o", "-O1",
             "-Wno-override-module", *SAN_FLAGS],
            cwd=work,
        )
        if r.returncode != 0:
            print("=== IR compile failed ===\n" + r.stderr, file=sys.stderr)
            return 90
        objs.append("prog.o")

        # 2. The pure-mode runtime TUs — exactly the set a SlateOS pure build links.
        for name in toolchain._SLATEOS_RUNTIME_NAMES:
            csrc = RUNTIME_DIR / f"{name}.c"
            if not csrc.is_file():
                print(f"=== missing runtime TU: {csrc} ===", file=sys.stderr)
                return 91
            r = _wsl(
                ["clang", "-c", _to_wsl(csrc), "-o", f"{name}.o", "-O1",
                 "-DFPY_PURE_MODE", "-I", _to_wsl(RUNTIME_DIR),
                 "-Wno-everything", *SAN_FLAGS],
                cwd=work,
            )
            if r.returncode != 0:
                print(f"=== runtime compile failed: {name}.c ===\n" + r.stderr,
                      file=sys.stderr)
                return 92
            objs.append(f"{name}.o")

        # 3. Link.
        r = _wsl(["clang", *objs, "-o", "prog", "-lm", "-lpthread", *SAN_FLAGS],
                 cwd=work)
        if r.returncode != 0:
            print("=== link failed ===\n" + r.stderr, file=sys.stderr)
            return 93

        # 4. Run. detect_leaks=0: the pure runtime intentionally leaks Path/str
        #    buffers that the program never drops; we care about OOB, not leaks.
        r = _wsl(["ASAN_OPTIONS=detect_leaks=0", "./prog"], cwd=work)
        if r.stdout:
            sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
        if verbose:
            print(f"[harness] build dir: {work}", file=sys.stderr)
        return r.returncode
    finally:
        if keep:
            print(f"[harness] kept build dir: {work}", file=sys.stderr)
        else:
            shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", nargs="?", help="Python source file to compile+run")
    ap.add_argument("-c", "--code", help="inline Python source instead of a file")
    ap.add_argument("--keep", action="store_true", help="keep the build directory")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    if a.code:
        src = a.code
    elif a.source:
        src = Path(a.source).read_text(encoding="utf-8")
    else:
        ap.error("give a source file or -c/--code")
    return build_and_run(src, keep=a.keep, verbose=a.verbose)


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
