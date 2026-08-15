"""Pure-mode regression: path text must never be mistaken for an object header.

An OBJ-tagged FpyValue carries no type information, so fpy_rc_incref /
fpy_rc_decref (runtime/objects.c) *probe* the pointee: they read a would-be
FpyObj magic at byte offset 32 and a would-be FpyClosure magic at offset 0.
Before the FpyPurePath header change, a pure-mode Path pointed straight at raw
path text, so any path whose bytes 32..35 happened to spell "SJBO"
(FPY_OBJ_MAGIC 0x4F424A53, little-endian) was treated as an FpyObj and had
arbitrary bytes of its own name decremented as a refcount.

This is not a 1-in-4-billion curiosity: it is fully attacker/user-controllable
by filename, and it corrupts *everything*. Under the old layout the path below
scores 4 of 31 (only .name survives); with the header it scores 31 of 31.

Run under tools/pure_harness.py so ASan sees the out-of-bounds write. Exits 0;
the printed bitmask must be 31.
"""
import sys
from pathlib import Path

# "/tmp/" (5 bytes) + 27 filler = offset 32, then the magic, then a suffix.
p = Path('/tmp/aaaaaaaaaaaaaaaaaaaaaaaaaaaSJBO-collide.txt')
p.write_text('collide\n')

ok = 0
if p.read_text() == 'collide\n':
    ok = ok + 1
if p.exists():
    ok = ok + 2
if p.name == 'aaaaaaaaaaaaaaaaaaaaaaaaaaaSJBO-collide.txt':
    ok = ok + 4
if str(p.parent) == '/tmp':
    ok = ok + 8
if p.is_file():
    ok = ok + 16

# Same idea at offset 0: "CLOS" == FPY_CLOSURE_MAGIC (0x434C4F53).
q = Path('CLOS-closure-magic-collide.txt')
q.write_text('clos\n')
if q.read_text() == 'clos\n':
    ok = ok + 32
if q.name == 'CLOS-closure-magic-collide.txt':
    ok = ok + 64

print('collide_bitmask', ok, 'of', 127)
sys.exit(0)
