# Linux Port & Bridge — Remaining Items

All P0, P1, and P2 bugs from the initial Linux port (WSL Ubuntu 24.04,
Python 3.12 + 3.14) have been fixed. The categories below are the only
remaining low-priority items.

## Remaining (P3)

### Error propagation (residual from bridge NULL guard)
NULL guard added to `pyobject_to_fpy()`, but error recovery is still
`exit()`/`return-None` rather than raising fastpy exceptions. Bridge
call failures produce `{tag=NONE, data=0}` instead of propagating the
Python exception into fastpy's exception system.

### Weak references to fastpy objects
`_weakref.ref(Foo())` requires the target to have a `tp_weaklistoffset`,
which `FpyObjProxy` does not provide. Fastpy class instances wrapped as
CPython proxies can't be weak-referenced.

### bytearray mutation through bridge (edge case)
`bytearray` mutation through the bridge may not work if the bytearray
is somehow represented as `FPY_TAG_BYTES` (unlikely in practice —
`bytearray()` returns OBJ-tagged `PyObject*`).

## What works well

Verified on Python 3.14 across ~60 stdlib modules:

- Constants, scalar-returning functions, object constructors + attribute access
- Method calls returning scalars or objects on real PyObject receivers
- Tuple returns (`_struct.unpack(">IH", packed) == (1000, 7)`)
- Python 3.14 specific modules (`_interpreters`, `_interpqueues`, etc.)
- Partial-native modules (`import os; os.getpid()`, `import hashlib; hashlib.sha256(b"x")`)
- Closures/lambdas passed to CPython (via FpyClosureProxy)
- Class instances passed to CPython (via FpyObjProxy with full protocol support)
- List mutation through bridge (sync-back after `heapify`, `sort`, etc.)
- 4+ positional args, PYOBJ binops/comparisons, safe cross-type refcounting
