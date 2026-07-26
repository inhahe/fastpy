# Open Questions — decisions that need the operator

This is the operator's decision queue. It is distinct from:

- `design.md` — what the system *is* (features + architecture),
- `known-issues.md` — bugs and technical debt already understood,
- and any record of decisions already *made*.

When a question here is answered, record the decision (attributed to the
operator) and delete the entry from this file.

---

## Q1. Should the `os.*` filesystem mutators raise `OSError`, or keep returning int status?

**Status:** open (raised 2026-07-26)

### The question

`os.remove` / `os.unlink` / `os.mkdir` / `os.rmdir` / `os.rename` currently
return `0` on success and `-1` on failure, and raise nothing. CPython returns
`None` and raises `OSError`. Should fastpy match CPython?

### Why it is being asked now

The int-status behaviour is **deliberate and documented** — `runtime/objects.c`
(~line 9010) says:

> Python's `os.remove` returns None and raises OSError on failure; in pure/AOT
> mode (no exception unwinding wired for this path) we surface success/failure
> as an int status instead, so a caller can branch on it.

That rationale is **no longer true.** `tests/pure/exception_checks.py`
(added 2026-07-26, bitmask 1023 green under ASan/UBSan) proves pure mode
catches exceptions correctly, *including* a raise originating inside a runtime
function — `Path.iterdir()` on a missing directory raises via `fastpy_raise`
and a `try` / `except RuntimeError` catches it, with `finally` running on both
paths. So the technical blocker the deviation was built around is gone, and the
deviation now stands on its own merits rather than on necessity.

It also has a demonstrated cost. A capability-denied `os.mkdir()` on SlateOS
returned `-1` with no error of any kind; the failure only surfaced two
statements later as `Path.iterdir()` raising "cannot open directory", which
sent the investigation after `opendir` instead of `mkdir` and cost a full
~10-minute QEMU boot cycle to localize.

### Options

**A. Raise `OSError` (match CPython).**
- *For:* fastpy's premise is compiling real Python; a program that ignores a
  failed `mkdir` and continues is a bug in every other Python implementation.
  Failures become loud at the point they happen.
- *Against:* breaking change. 27 call sites across `os/services/*/build.py`
  currently branch on the int status, and their kernel self-tests assert exact
  exit codes; each would need updating in the same change. The common
  "delete if it exists" idiom (used by the pathlib self-test itself) would need
  an explicit `try`/`except` or an `os.path.exists()` guard.
- *Cost:* also needs a new `FPY_EXC_OSERROR` kind — `FPY_EXC_*` in `runtime.c`
  (~line 606) has no OS-error member today, only `GENERIC`/`RUNTIMEERROR`.

**B. Keep int status (status quo).**
- *For:* no breakage; lets pure-mode code branch on failure without exception
  machinery; consistent with `os.path.exists` returning a bool.
- *Against:* silently diverges from CPython in a way that turns a hard failure
  into a wrong answer later. The same class of bug will recur.

**C. Raise only when the result is discarded.** Codegen can see whether the
call is a bare expression-statement (`os.mkdir(p)`) or has its value consumed
(`r = os.mkdir(p)` / `if os.mkdir(p) == 0:`), and raise only in the former.
- *For:* CPython-correct for the idiomatic case, fully source-compatible with
  all 27 existing call sites, no migration needed.
- *Against:* the same call has two behaviours depending on syntactic context,
  which is not a rule Python has anywhere. Surprising to read, and awkward once
  the value flows through a variable the compiler can't track.

### Recommendation

**A**, done as one change that also updates the affected `build.py` call sites —
fastpy's value proposition is that a Python program means what Python says it
means, and a silent-failure filesystem API undercuts that specifically in the
place where silence is most expensive. C is tempting for its zero migration
cost, but inventing a context-dependent calling convention to avoid a one-time
migration is the kind of cleverness that gets rediscovered as a bug later.

### Where it bites

- `runtime/objects.c` ~9010-9045 (`fastpy_os_remove` / `mkdir` / `rmdir` /
  `rename`).
- `runtime/runtime.c` ~606-618 (`FPY_EXC_*` — would need an `OSERROR` kind).
- `os/services/*/build.py` — 27 call sites, plus the kernel self-tests in
  `kernel/src/proc/spawn.rs` that assert their exit codes.
