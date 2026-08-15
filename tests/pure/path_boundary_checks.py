"""Pure-mode pathlib.Path *boundary* regression program.

Complements pathlib_checks.py by covering the cases where a Path pointer meets
code outside runtime/pathlib_pure.c, plus the buffer-size edge the OBJ refcount
dispatcher probes:

  * with_suffix()  — the only Path consumer implemented in runtime.c, not in
    pathlib_pure.c, so it exercises the cross-TU Path representation contract.
  * paths longer than 36 bytes — the OBJ incref/decref dispatcher reads a
    would-be FpyObj magic at byte offset 32, so a long path puts real path text
    under that probe rather than zero padding.
  * Path.cwd() — a CLASSmethod. Before the fix this reached
    fastpy_obj_call_method0 with a non-object receiver (UBSan: misaligned
    FpyObj access at 0x1).
  * resolve(), parent, joinpath — Path-returning methods whose results must
    keep their PATH tag.

Run under tools/pure_harness.py so ASan/UBSan can see the out-of-bounds and
misaligned accesses that a plain build silently tolerates. Exits 0; the printed
bitmask must be 255.
"""
import sys
from pathlib import Path

ok = 0
p = Path('/tmp/probe-a.txt')
p.write_text('x\n')
if str(p.with_suffix('.log')) == '/tmp/probe-a.log':
    ok = ok + 1

# >36 bytes, so path text — not zero padding — sits under the offset-32 probe.
q = Path('/tmp/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-long.txt')
q.write_text('y\n')
if q.read_text() == 'y\n':
    ok = ok + 2
if q.name == 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-long.txt':
    ok = ok + 4
if q.exists():
    ok = ok + 8
if str(q.parent) == '/tmp':
    ok = ok + 16

r = Path('/tmp')
if str(r.joinpath('probe-a.txt')) == '/tmp/probe-a.txt':
    ok = ok + 32
if str(Path.cwd()) != '':
    ok = ok + 64
if str(p.resolve()) == '/tmp/probe-a.txt':
    ok = ok + 128

print('bitmask', ok, 'of', 255)
sys.exit(0)
