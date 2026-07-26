"""Pure-mode Path.iterdir() regression program.

iterdir() is the one Path method that returns a *container* of Paths, so it is
the only place the pure runtime hands the codegen an FpyList whose elements are
OBJ-tagged Path headers. That makes it the interesting case for:

  * the static type — codegen types p.iterdir() as list[Path], so the loop
    variable must keep its PATH tag (a PYOBJ tag would route the for-loop
    through the CPython iterator protocol, which does not exist in pure mode).
  * the element representation — each entry is an FpyPurePath header, so
    fpy_list_append's OBJ incref probes it; the header's magic/guard words are
    what stop that probe from mangling the path text.
  * long entry names — a name pushing the joined path past 36 bytes puts real
    text under the offset-32 probe.

Run under tools/pure_harness.py so ASan/UBSan see any out-of-bounds or
misaligned access. Exits 0; the printed bitmask must be 63.
"""
import os
import sys
from pathlib import Path

DIR = '/tmp/fpy-iterdir-probe'
A = '/tmp/fpy-iterdir-probe/alpha.txt'
B = '/tmp/fpy-iterdir-probe/beta-with-a-deliberately-long-entry-name.txt'

# Start from a known-empty directory so the entry count is exact even when a
# previous run left files behind. (Path.mkdir() is not part of the surface the
# codegen emits natively; os.mkdir on a plain str is. Each of these returns -1
# instead of raising when the target is missing//present, so no guards needed.)
os.remove(A)
os.remove(B)
os.rmdir(DIR)
os.mkdir(DIR)

d = Path(DIR)

a = d.joinpath('alpha.txt')
a.write_text('a\n')
b = d.joinpath('beta-with-a-deliberately-long-entry-name.txt')
b.write_text('b\n')

ok = 0

n = 0
for e in d.iterdir():
    n = n + 1
if n == 2:
    ok = ok + 1

# The loop variable must still be a Path: .name / str() / read_text() on it
# all go through the native Path entry points, not the bridge.
seen_alpha = 0
seen_beta = 0
total = 0
for e in d.iterdir():
    if e.name == 'alpha.txt':
        seen_alpha = 1
    if e.name == 'beta-with-a-deliberately-long-entry-name.txt':
        seen_beta = 1
    if e.is_file():
        total = total + 1
if seen_alpha == 1:
    ok = ok + 2
if seen_beta == 1:
    ok = ok + 4
if total == 2:
    ok = ok + 8

# Entries must be joined against the parent, not bare basenames — otherwise
# read_text() would resolve relative to the cwd.
contents = ''
for e in d.iterdir():
    contents = contents + e.read_text()
if contents == 'a\nb\n' or contents == 'b\na\n':
    ok = ok + 16

# str(entry) must carry the full path.
prefixed = 1
for e in d.iterdir():
    if not str(e).startswith('/tmp/fpy-iterdir-probe/'):
        prefixed = 0
if prefixed == 1:
    ok = ok + 32

print('bitmask', ok, 'of', 63)
sys.exit(0)
