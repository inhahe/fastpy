"""Pure-mode pathlib.Path regression program (mirrors the SlateOS on-target self-test).

Compiled + run by `tools/pure_harness.py` under native Linux with ASan/UBSan.
Exits with a BITMASK: check N sets bit (N-1). A full pass is 2**10 - 1 == 1023,
the same value `self_test_fastpy_slateos_pathlib` (kernel/src/proc/spawn.rs in
the SlateOS repo) asserts on target. Any cleared bit names exactly which
Path operation regressed.

Kept as a flat sequence of `if cond: ok = ok + N` (no boolean fold) to stay in
pure-mode-safe codegen territory.
"""
import sys
from pathlib import Path

p = Path('/tmp/fpy-pathlib-harness.txt')
p.write_text('hello pathlib\n')
ok = 0
if p.read_text() == 'hello pathlib\n':
    ok = ok + 1
if p.exists():
    ok = ok + 2
if p.is_file():
    ok = ok + 4
if not p.is_dir():
    ok = ok + 8
if p.name == 'fpy-pathlib-harness.txt':
    ok = ok + 16
if p.suffix == '.txt':
    ok = ok + 32
if p.stem == 'fpy-pathlib-harness':
    ok = ok + 64
d = p.parent
if str(d) == '/tmp':
    ok = ok + 128
j = d.joinpath('fpy-pathlib-harness.txt')
if str(j) == '/tmp/fpy-pathlib-harness.txt':
    ok = ok + 256
if d.is_dir():
    ok = ok + 512
print('bitmask', ok)
sys.exit(ok)
