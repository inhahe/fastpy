# Linux Port & Bridge Bugs

Bugs found while porting fastpy to Linux (WSL Ubuntu 24.04, Python 3.12 + 3.14)
and exercising the CPython bridge across ~60 stdlib `.so`/C-builtin modules.
Most of these are not Linux-specific — they're latent codegen / runtime bugs
that happen to surface because the bridge is used more heavily here than on
Windows with MSVC.

**Legend:** ✅ = fixed • ⚠️ = still open

---

## Category 1: Linux build failures (FIXED)

These prevented the runtime from compiling at all on Linux with gcc.
Fixes are currently sitting in the working tree (uncommitted) from this
porting session.

### 1.1  ✅ `runtime/runtime.c` — missing POSIX includes

`fastpy_os_listdir` uses `opendir` / `readdir` / `closedir` / `struct dirent`
in the `#else` (POSIX) branch, but `<dirent.h>` and `<unistd.h>` were never
included. MSVC doesn't see this branch so it never surfaced on Windows.

**Fix:** Added at the top of `runtime.c`:
```c
#ifndef _WIN32
#include <dirent.h>
#include <unistd.h>
#endif
```

### 1.2  ✅ `runtime/objects.h` — missing `<stddef.h>`

`fpy_str_header` uses `offsetof()` but `<stddef.h>` was never included.
MSVC pulls this in transitively via other headers; gcc does not.

**Fix:** Added `#include <stddef.h>` after `<stdint.h>`.

### 1.3  ✅ `runtime/objects.c` — signature mismatch on `fastpy_closure_call_list`

The header declared `(void *, void *)` while the definition used
`(FpyClosure *, FpyList *)`. MSVC accepts pointer-type mismatches between
declaration and definition; gcc errors out (`conflicting types`).

**Fix:** Definition now uses `(void *closure, void *args_list)` and casts
internally, matching the header.

### 1.4  ✅ `compiler/toolchain.py` — baked-in `LIBDIR` from relocatable Pythons

`_probe_python_install` trusted `sysconfig.get_config_var('LIBDIR')`. For
Python distributions built on one machine and used on another (e.g.
python-build-standalone), this value is the **original build-time path**,
like `/install/lib`, which does not exist on the target system. Linking
then failed with `cannot find -lpython3.14`.

**Fix:** `_probe_python_install` now verifies the reported LIBDIR actually
contains `libpythonX.Y.{so,dylib,a}`. If not, it falls back through
`{prefix}/lib` → `/usr/lib/x86_64-linux-gnu` → `/usr/lib64` → `/usr/lib`
→ `/usr/local/lib`.

---

## Category 2: Codegen — bridge-argument type corruption

These cause `TypeError` from CPython ("not 'int'", "not 'str'",
"bytes-like object required"), then usually segfault when the `NULL`
error-return is used.

### 2.1  ✅ `b"..."` bytes literals always arrive as `str` at the bridge

A literal like `b"hi"` passed as an argument to a bridge call is tagged
and marshalled as `str`, not `bytes`. Every CPython function that wants a
buffer (`hashlib`, `zlib`, `binascii`, `_struct`, etc.) rejects it.

**Repro:**
```python
import binascii
print(binascii.hexlify(b"hi"))   # TypeError: a bytes-like object is required, not 'str'
```

**Workaround:** Build bytes via `bytes([...])` **into a variable first**,
then pass the variable.

### 2.2  ✅ Inline `bytes([...])` passed to a bridge call is corrupted

Even using `bytes([...])` — which *does* produce a real `bytes` — fails
if the expression is passed inline. The argument arrives tagged as `int`
(apparently the last list element).

**Repro:**
```python
import binascii
print(binascii.hexlify(bytes([104, 105])))
# TypeError: a bytes-like object is required, not 'int'
```

**Workaround:** Assign to a variable first.
```python
hi = bytes([104, 105])
print(binascii.hexlify(hi))   # b'6869' — works
```

### 2.3  ✅ User function returning bytes loses the `bytes` tag

```python
def s_to_b(s):
    return bytes([ord(c) for c in s])

import zlib
data = s_to_b("hello")
print(len(data))           # prints 0 (not 5)
zlib.compress(data)        # TypeError: not 'int'
```

The result of the call is retagged (likely as `int`) as it crosses the
user-function return boundary. Direct `bytes([...])` at the call site
(assigned to a variable) is fine; a wrapper function is not.

### 2.4  ✅ `_struct.pack("<d", 3.14)` inside a tuple -> float bit-pattern

When `_struct.unpack("<d", ...)` returns `(3.14,)`, indexing with `[0]`
yields `4614253070214989087` — the IEEE-754 int bit pattern of 3.14.
The float tag is lost as the element crosses out of the bridge-returned
tuple.

### 2.5  ✅ Bridge calls with > 3 positional args are unsupported

The `_emit_cpython_method_call` fast path only dispatched `call0`/`call1`/
`call2`/`call3`. Anything with 4+ positional args crashed.

**Fix:** Added `fpy_cpython_call_kw` which handles arbitrary positional args
via a packed argument array. 4+ arg bridge calls now work correctly.

---

## Category 3: Codegen — variable lifetime & reassignment

### 3.1  ✅ Reassigning a variable across different bridge return types segfaults

```python
r = _struct.unpack(">I", pack)   # r is a tuple (OBJ)
r = _struct.pack(">q", -1).hex() # r is now a str — SEGFAULT during this assignment
```

Appears to be a double-decref or refcount-mismatch during the
assignment's "drop old value" step when the tags differ.

**Fix:** `fpy_rc_incref` / `fpy_rc_decref` in objects.c now safely distinguish
FpyClosure, FpyObj, and CPython PyObject* by checking the first word (magic for
closures, plausible refcount range + magic offset for FpyObj). Unrecognized
OBJ-tagged pointers delegate to `fpy_bridge_pyobj_incref` / `fpy_bridge_pyobj_decref`
(in cpython_bridge.c) which call `Py_INCREF` / `Py_DECREF`.

### 3.2  ✅ `time.time()` stored in a variable, then read, segfaults

Specific to Linux — works fine on Windows.

```python
import time
t = time.time()   # ok
print(t)          # SEGFAULT
```

But the inline form is fine:
```python
print(time.time())   # works
```

Was a float-return-boxing bug that manifested under the System V
ABI (Linux). Fixed by SafeIRBuilder type coercion and improved float
variable storage.

---

## Category 4: Codegen — "partial-native" modules are broken

### 4.1  ✅ Named-native modules store `NULL` for the module object

`_NATIVE_MODULES` in `compiler/codegen.py` (line ~11380) lists `os`,
`hashlib`, `json`, `math`, `time`, `struct`, `base64`, `random`,
`string`, `pathlib`, `collections`, etc. For these, `import X` emits:

```llvm
store {i32 6 (OBJ), i64 0 (NULL)}, {i32,i64}* %"X"
```

i.e. the variable is stored as `{tag=OBJ, data=NULL}`. Some attributes
on these modules have native dispatch (`os.getcwd`, `hashlib.md5`) and
work; others fall through to the bridge path:

```llvm
%attr = call i8* @"fpy_cpython_getattr"(i8* NULL, i8* "attr_name")
```

`PyObject_GetAttrString(NULL, ...)` segfaults inside CPython.

**Repro (any of these):**
```python
import os
s = os.name          # NULL.name — SEGFAULT

import hashlib
h = hashlib.md5(b"x")
s = h.hexdigest()    # h was stored as {INT,0}; .hexdigest() dereferences NULL — SEGFAULT
```

**Workaround:** Use the underscore-prefixed C module directly:
```python
import _hashlib
h = _hashlib.openssl_md5(bytes([120]))
print(h.hexdigest())   # works — pure bridge path
```

Pure-bridge modules (not in `_NATIVE_MODULES`) call `fpy_jit_import`
correctly and their attribute access works.

### 4.2  ✅ `hashlib.md5(...)` doesn't actually call the bridge

The IR for `h = hashlib.md5(b"hello")` shows no `fpy_cpython_*` call at
all — `h` is stored as `{tag=INT, data=0}`. The codegen recognizes
`hashlib.md5` as a partial-native name but the native stub either
doesn't exist or stores a placeholder. Any subsequent method call on
`h` then operates on a NULL pointer.

---

## Category 5: Runtime — return-value conversion

### 5.1  ✅ Bridge-returned `bool` comes back as `int`

`pyobject_to_fpy` in `runtime/cpython_bridge.c` falls through
`PyBool_Check` but the consumer displays it as 1/0 instead of True/False.

**Repro:**
```python
import select
print(hasattr(select, "poll"))       # prints 1 (expected True)

import unicodedata
print(unicodedata.mirrored("("))     # prints 1 (expected True)
```

### 5.2  ✅ `bytes1 + bytes2` from bridge returns → wrong tag

After `chunk1 = co.compress(data); tail = co.flush()`, the expression
`chunk1 + tail` is retagged incorrectly; `zlib.decompress(chunk1 + tail)`
then raises `TypeError: bytes-like object required, not 'int'`.

**Fix:** `fastpy_fv_binop` now handles BYTES+BYTES concatenation and BYTES*INT
repetition. OBJ-tagged operands (bridge-returned PyObject*) now delegate to
`fpy_cpython_binop` / `fpy_cpython_rbinop` via the PyNumber protocol.

### 5.3  ✅ `bytes1 == bytes2` equality after round-trip returns False

```python
c = zlib.compress(data)
d = zlib.decompress(c)
print(d == data)      # False — byte contents match, but equality fails
```

Equality isn't dispatched to PyObject's `__eq__`; fastpy compares
bytes-tagged values by pointer identity or by a path that doesn't work
for bridge-returned buffers.

**Fix:** Added `fpy_cpython_compare` (in cpython_bridge.c) which calls
`PyObject_RichCompare`. Codegen now dispatches PYOBJ comparisons (Eq, NotEq,
Lt, LtE, Gt, GtE) through this function. Bridge-returned bytes stored as
raw PyObject* are correctly compared by value.

### 5.4  ✅ Binary operators on bridge-returned objects don't dispatch

```python
import _decimal
a = _decimal.Decimal("1.23")
b = _decimal.Decimal("4.56")
print(a + b)          # prints a random int like 127795266677056 (a pointer)
```

`__add__` / `__sub__` / `__mul__` / `__eq__` etc. aren't routed through
`PyNumber_Add(a, b)` when both operands are OBJ-tagged PyObjects.

---

## Category 6: Runtime — mutation through bridge is silently dropped

### 6.1  ⚠️ `_heapq.heapify(list)` doesn't mutate the list (known limitation)

```python
import _heapq
h = [5, 3, 8, 1, 9, 2]
_heapq.heapify(h)
print(h)   # [5, 3, 8, 1, 9, 2] — unchanged
```

An FpyList is marshalled to a *new* PyList when crossing the bridge; any
in-place mutation happens on that temporary copy and is discarded. Same
issue for `_heapq.heappush`, `list.sort` called via bridge, etc.

### 6.2  ⚠️ `_struct.pack_into(fmt, buf, offset, ...)` doesn't mutate `buf` (known limitation)

```python
import _struct
buf = bytearray(8)
_struct.pack_into(">I", buf, 0, 0xdeadbeef)
print(buf.hex())   # "0000000000000000" — unchanged
```

Same root cause as 6.1: `bytearray` gets copied across the bridge, and
CPython mutates the copy.

---

## Category 7: CPython ↔ fastpy object-model gap

### 7.1  ⚠️ fastpy objects are not PyObjects (known limitation)

CPython can't treat a fastpy-compiled function/class/instance as a
`PyObject *`. Anywhere CPython needs a callable, hashable, or
weak-referenceable Python value from the fastpy side, it fails.
This is a fundamental architectural gap that would require wrapping
every fastpy object in a PyObject* shim. Deferred to a future
architecture rework.

**Examples:**
```python
import _collections
dd = _collections.defaultdict(int)
# TypeError: first argument must be callable or None (fastpy's int isn't PyCallable)

import _functools
print(_functools.reduce(lambda a, b: a + b, [1, 2, 3], 0))
# returns None — the lambda isn't callable from CPython

import _weakref
class Foo: pass
r = _weakref.ref(Foo())
# TypeError: cannot create weak reference to '' object
```

### 7.2  ⚠️ `import sys.version` misparse

A top-level expression like `sys.version.split()[0]` can trigger a
spurious "`No module named 'sys.version'`" in the import pass.
Happens at compile/bridge-init time, not AST parse time.

---

## Category 8: Misc

### 8.1  ⚠️ `binascii.hexlify` errors then produces `None`, next call segfaults

Typical pattern across the above bugs: a bridge call returns NULL after
a TypeError, that NULL is then tagged as a real FpyValue (`{tag=2 str,
data=0}`), and the next use segfaults when dereferenced.

### 8.2  ✅ `"hello".encode()` segfaults

```python
z = "hello".encode()
print(z)   # SEGFAULT
```

`str.encode()` goes through a code path that produces a bytes-like that
later dereferences bad memory. `bytes([...])` works as a substitute.

### 8.3  ⚠️ Generator-returning bridge results can't be iterated

```python
import _string
for item in _string.formatter_parser("hello {name}!"):
    print(item)
# prints small integers (memory addresses or tags) — not the tuples
# CPython's parser yields
```

The returned generator is tagged as an iterator but fastpy's `for`-loop
protocol doesn't call `tp_iternext` on an OBJ-tagged PyObject.

---

## Workarounds summary

Most bridge bugs from the initial Linux port have been fixed. Remaining
workarounds:

1. **Don't expect in-place mutation of lists/bytearrays through the
   bridge.** Capture the return value of any method you'd expect to
   mutate, or work with CPython-side objects (PyListObject returned by
   another bridge call, mutated via bridge).
2. **Don't use fastpy classes/lambdas as CPython callables.** If you
   need a callable into CPython, write it as a pure-Python (bridge-run)
   helper.

Previously required workarounds that are NO LONGER NEEDED:
- ~~Always use underscore-prefixed C modules~~ -- native modules now work
- ~~Always pre-bind bytes~~ -- bytes literals and inline bytes() work
- ~~Keep bridge calls to 3 or fewer positional args~~ -- 4+ args now supported
- ~~Don't reassign a variable across bridge return types~~ -- safe refcounting fixed

---

## Fix priority (remaining items)

| Priority | Bug | Rationale |
|----------|-----|-----------|
| **P2** | 6.1/6.2 bridge mutation | Blocks `_heapq` in-place usage, `pack_into` |
| **P3** | 7.1 object model gap | Deep architectural item — fastpy objects are not PyObjects |
| **P3** | 7.2 `sys.version` misparse | Edge case in import pass |
| **P3** | 8.1 NULL after TypeError | Error propagation across bridge |
| **P3** | 8.3 Generator bridge results | Iterator protocol for bridge generators |

All P0 and P1 bugs from the initial Linux port have been fixed.

---

## Appendix: What works well

For balance — most of the bridge **does** work. Verified on Python 3.14
across ~60 stdlib modules:

- Constants (Int, Float, Str, bytes): `_signal.SIGTERM`, `_ssl.OPENSSL_VERSION`,
  `_locale.LC_ALL`, all work.
- Scalar-returning functions: `_socket.htons`, `_operator.add`,
  `_stat.filemode`, `_statistics._normal_dist_inv_cdf`, all work.
- Object constructors + attribute access: `_datetime.date(2026,4,21).year`,
  `grp.getgrnam('root').gr_gid`, `pwd.getpwuid(0).pw_name` — all work.
- Method calls returning scalars or objects (when receiver is a real
  PyObject): `_hashlib.openssl_md5(hi).hexdigest()`,
  `_io.BytesIO().write(x).getvalue()` — work.
- Tuple returns: `_struct.unpack(">IH", packed) == (1000, 7)` — works.
- Python 3.14 specific modules: `_interpreters`, `_interpqueues`,
  `_interpchannels`, `_remote_debugging` — all load and their
  attributes/functions work.

The partial-native NULL-module path (Category 4) has been fixed. `import os;
os.getpid()`, `import hashlib; hashlib.sha256(b"x")` etc. now work correctly.
