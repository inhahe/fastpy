"""Pure-mode checks for *displaying* a pathlib.Path.

Run under the ASan/UBSan harness:

    python tools/pure_harness.py tests/pure/path_display_checks.py

Exits with a BITMASK: check N (1-based) sets bit (N-1). A full pass is
2**8 - 1 == 255.

Why this file exists
--------------------
Codegen tags a Path OBJ, so every *generic* OBJ consumer in the runtime
(`print` / `write` / `str` / `repr`) receives a pointer it cannot type, and its
fallback is the CPython bridge — a stub that RAISES in a pure build. So
`print(Path(...))` used to fail with "operation requires the CPython bridge"
even though the value is trivially printable, and `repr()` likewise. The Path
header's magic word now lets those generic paths identify a Path and dispatch it
natively (`_fpy_obj_as_path_text` in runtime/objects.c).

Note that merely *reaching* the end of this program is a large part of the test:
a raise from any of the print calls below does not unwind, it sets a pending
exception that aborts at the next statement boundary, so the bitmask would never
be reached at all. The explicit checks then pin down the exact text.

Checks (bit value in parentheses):
   1. str(p) is the path text                                       (1)
   2. an f-string interpolates the path text                        (2)
   3. repr(p) is CPython's PosixPath('...') form                    (4)
   4. repr of a Path built by .parent is likewise correct           (8)
   5. str() of a joinpath result is the joined text                 (16)
   6. an empty Path displays as '.' like CPython                    (32)
   7. repr text survives a filename that collides with FPY_OBJ_MAGIC(64)
   8. the program reached the end (all the bare print()s below ran) (128)
"""

import sys
from pathlib import Path

ok = 0
p = Path('/tmp/fpy-display.txt')

# Bare prints: none of these may raise. They are not individually asserted
# (stdout is not readable from inside the program) — their check is check 8,
# reaching the end at all.
print(p)
print('prefix', p)
print(f'interp={p}')
print(repr(p))

if str(p) == '/tmp/fpy-display.txt':
    ok = ok + 1

f = f'{p}'
if f == '/tmp/fpy-display.txt':
    ok = ok + 2

if repr(p) == "PosixPath('/tmp/fpy-display.txt')":
    ok = ok + 4

d = p.parent
print(d)
if repr(d) == "PosixPath('/tmp')":
    ok = ok + 8

j = d.joinpath('sub', 'leaf.txt')
print(j)
if str(j) == '/tmp/sub/leaf.txt':
    ok = ok + 16

# CPython: str(Path('')) == '.' and repr(Path('')) == "PosixPath('.')"
empty = Path('')
print(empty)
if str(empty) == '.':
    ok = ok + 32

# The same offset-32 FPY_OBJ_MAGIC collision the Path header defends against,
# now exercised through the *display* paths rather than the accessors: "/tmp/"
# (5) + 27 filler puts "SJBO" at bytes 32..35.
c = Path('/tmp/aaaaaaaaaaaaaaaaaaaaaaaaaaaSJBO-collide.txt')
print(c)
if repr(c) == "PosixPath('/tmp/aaaaaaaaaaaaaaaaaaaaaaaaaaaSJBO-collide.txt')":
    ok = ok + 64

ok = ok + 128

print('path_display_checks bitmask')
print(str(ok))
sys.exit(ok)
