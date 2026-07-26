"""Pure-mode (CPython-free) exception-handling checks.

Run under the ASan/UBSan harness:

    python tools/pure_harness.py tests/pure/exception_checks.py

Exits with a BITMASK: check N (1-based) sets bit (N-1). A full pass is
2**10 - 1 == 1023; any other value's clear bits name exactly which checks
failed.

Why this file exists
--------------------
`tests/pure/` covered the Path runtime but had *no* exception coverage at all,
even though pure mode's whole error-reporting story rests on `fastpy_raise`.
That matters because `fastpy_raise` does not unwind: it only sets a pending
exception and snapshots the shadow stack, and codegen tests that flag at
statement boundaries. Whether a `try`/`except` actually *catches* such a raise
in a no-CPython build was therefore unverified — and the answer gates whether
runtime functions may report failure by raising (the CPython-correct behaviour)
or must keep returning int status codes.

Checks (bit value in parentheses):
   1. a bare `except:` catches a raise from a runtime function       (1)
   2. control resumes after the try block (the handler ran once)     (2)
   3. a typed `except RuntimeError:` catches the runtime's raise     (4)
   4. `else` runs when the body does NOT raise                       (8)
   5. `finally` runs on the non-raising path                         (16)
   6. `finally` runs on the raising path too                         (32)
   7. an explicit `raise ValueError(...)` is catchable by type       (64)
   8. a non-matching typed handler does not swallow a later match    (128)
   9. state mutated before the raise survives into the handler       (256)
  10. a raise inside a loop body is catchable per-iteration          (512)
"""

import sys
from pathlib import Path

ok = 0

# Check 1-2: a runtime function that raises. Path.iterdir() on a directory that
# does not exist is the cheapest genuine runtime raise available in pure mode
# (it calls fastpy_raise(RUNTIMEERROR) when opendir fails), so this exercises
# the real pending-exception path rather than only the `raise` statement.
caught = 0
after = 0
try:
    missing = Path('/tmp/fpy-no-such-dir-exception-checks')
    for _entry in missing.iterdir():
        caught = caught + 100
except:
    caught = caught + 1
after = after + 1
if caught == 1:
    ok = ok + 1
if after == 1:
    ok = ok + 2

# Check 3: the same raise, caught by its declared type.
typed = 0
try:
    missing2 = Path('/tmp/fpy-no-such-dir-exception-checks-2')
    for _e2 in missing2.iterdir():
        typed = typed + 100
except RuntimeError:
    typed = typed + 1
if typed == 1:
    ok = ok + 4

# Checks 4-5: else/finally on the non-raising path.
ran_else = 0
ran_finally = 0
try:
    quiet = 1
except RuntimeError:
    quiet = 2
else:
    ran_else = ran_else + 1
finally:
    ran_finally = ran_finally + 1
if ran_else == 1 and quiet == 1:
    ok = ok + 8
if ran_finally == 1:
    ok = ok + 16

# Check 6: finally must also run when the body raises and the handler catches.
ran_finally2 = 0
try:
    raise ValueError('boom')
except ValueError:
    ran_finally2 = ran_finally2 + 1
finally:
    ran_finally2 = ran_finally2 + 10
if ran_finally2 == 11:
    ok = ok + 32

# Check 7: an explicit raise of a different builtin type.
val = 0
try:
    raise ValueError('explicit')
except ValueError:
    val = val + 1
if val == 1:
    ok = ok + 64

# Check 8: a handler for the wrong type must not swallow the exception; the
# nested outer handler is the one that must run.
inner = 0
outer = 0
try:
    try:
        raise ValueError('for the outer handler')
    except IndexError:
        inner = inner + 1
except ValueError:
    outer = outer + 1
if inner == 0 and outer == 1:
    ok = ok + 128

# Check 9: writes performed before the raise must be visible in the handler —
# i.e. catching does not roll back or lose local state.
before = 0
seen = 0
try:
    before = 7
    raise ValueError('after the write')
except ValueError:
    seen = before
if seen == 7:
    ok = ok + 256

# Check 10: raising inside a loop body, caught per-iteration, so the loop still
# completes all its iterations.
iters = 0
handled = 0
i = 0
while i < 3:
    try:
        raise ValueError('per-iteration')
    except ValueError:
        handled = handled + 1
    iters = iters + 1
    i = i + 1
if iters == 3 and handled == 3:
    ok = ok + 512

print('exception_checks bitmask')
print(str(ok))
sys.exit(ok)
