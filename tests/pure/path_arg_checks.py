"""Pure-mode checks for passing a pathlib.Path *as an argument*.

Run under the ASan/UBSan harness:

    python tools/pure_harness.py tests/pure/path_arg_checks.py

Exits with a BITMASK: check N (1-based) sets bit (N-1). A full pass is
2**17 - 1 == 131071.

Why this file exists
--------------------
CPython accepts a `Path` anywhere a path string is accepted, and fastpy's
runtime entry points for `os.*` / `os.path.*` take the path as a plain C
string. In pure mode a Path is NOT a plain C string: it is a headed object
(`FpyPurePath` in runtime/pathlib_pure.c) whose text starts at offset 40, so
handing the callee the Path pointer makes it read the header instead. It saw
the magic word "PATH" and cheerfully answered about a file of that name —
`os.path.exists(Path('/tmp/x'))` returned False. That is the worst of the
possible failure modes: not a link error, not a raise, just a wrong answer.

Codegen now routes every runtime parameter that is *path text* through
`fastpy_path_str()` (`_emit_path_text_arg`). This file pins that down for the
whole surface, because the conversion is per-argument: a single missed call
site regresses silently and only for Path arguments, which is exactly the
shape of bug that survives a test suite written with string paths.

Note the last check is the completion sentinel. An uncaught exception exits 1,
which would otherwise be indistinguishable from the legitimate bitmask "only
check 1 passed".

Checks (bit value in parentheses):
   1. os.path.exists(Path) finds the file                            (1)
   2. os.path.isfile(Path)                                           (2)
   3. os.path.isdir(Path) on the directory                           (4)
   4. os.path.getsize(Path) is the byte count                        (8)
   5. os.path.basename(Path)                                        (16)
   6. os.path.dirname(Path)                                         (32)
   7. os.listdir(Path) sees the one entry                           (64)
   8. os.path.join(Path, str)                                      (128)
   9. os.access(Path, 0)                                           (256)
  10. os.rename(Path, Path) succeeds                                (512)
  11. the renamed file exists at the new Path                      (1024)
  12. os.remove(Path) succeeds                                     (2048)
  13. the builtin open(Path, 'r') reads the file                   (4096)
  14. the builtin open(Path, 'w') writes it                        (8192)
  15. `with open(Path) as h` reads it                             (16384)
  16. plain *string* arguments still work (no regression)         (32768)
  17. the program reached the end                                 (65536)
"""

import os
import sys
from pathlib import Path

base = '/tmp/fpy-path-arg-checks'

# Start from a known-empty directory. rmdir on a missing directory just reports
# failure through its return value (see known-issues.md), so this is safe to run
# on a fresh filesystem.
os.rmdir(base)
os.mkdir(base)

d = Path(base)
f = d.joinpath('a.txt')
f.write_text('abc\n')

ok = 0

if os.path.exists(f):
    ok = ok + 1

if os.path.isfile(f):
    ok = ok + 2

if os.path.isdir(d):
    ok = ok + 4

if os.path.getsize(f) == 4:
    ok = ok + 8

if os.path.basename(f) == 'a.txt':
    ok = ok + 16

if os.path.dirname(f) == base:
    ok = ok + 32

names = os.listdir(d)
if len(names) == 1:
    ok = ok + 64

if os.path.join(d, 'x.txt') == base + '/x.txt':
    ok = ok + 128

if os.access(f, 0) == 1:
    ok = ok + 256

g = d.joinpath('b.txt')
if os.rename(f, g) == 0:
    ok = ok + 512

if os.path.exists(g):
    ok = ok + 1024

if os.remove(g) == 0:
    ok = ok + 2048

# The builtin open() is a separate code path from os.open() — it goes to
# fastpy_io_open, not to the os module table — and it failed loudly rather than
# quietly: fopen() was handed the header and reported
# "FileNotFoundError: [Errno 2] No such file or directory: 'PATH'".
o = d.joinpath('c.txt')
o.write_text('hello\n')
h = open(o, 'r')
if h.read() == 'hello\n':
    ok = ok + 4096
h.close()

h2 = open(o, 'w')
h2.write('bye\n')
h2.close()
if o.read_text() == 'bye\n':
    ok = ok + 8192

# The `with` form takes the same argument path but through a different
# statement shape, and it is how open() is normally written.
with open(o) as h3:
    if h3.read() == 'bye\n':
        ok = ok + 16384

os.remove(o)

# The Path conversion must not have cost the string spelling: a `str` argument
# is passed through untouched, and both the positive and the negative answer
# have to be right (a callee reading the wrong bytes tends to answer "no" to
# everything, which the first half of this check would not catch on its own).
if os.path.exists(base) and os.path.exists(base + '/b.txt') == 0:
    ok = ok + 32768

os.rmdir(base)

ok = ok + 65536

print('path_arg_checks bitmask')
print(str(ok))
sys.exit(ok)
