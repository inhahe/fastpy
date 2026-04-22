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

### 6.1  ✅ `_heapq.heapify(list)` doesn't mutate the list

```python
import _heapq
h = [5, 3, 8, 1, 9, 2]
_heapq.heapify(h)
print(h)   # [1, 3, 2, 5, 9, 8] — now correctly mutated
```

**Fix:** All bridge call functions (`fpy_cpython_call`, `call1`–`call3`,
`call_kw`, and their `_raw` variants) now sync LIST-tagged arguments back
after the call. A new `fpy_sync_pylist_to_fpylist()` helper copies the
mutated PyList contents (which may have been reordered, grown, or shrunk)
back into the original FpyList, using `fpy_list_set` for existing slots
(handles decref/incref) and `fpy_list_append` for growth. Also works for
`heappush`, `heappop`, `list.sort` through the bridge.

### 6.2  ⚠️ `_struct.pack_into(fmt, buf, offset, ...)` doesn't mutate `buf` (known limitation)

```python
import _struct
buf = bytearray(8)
_struct.pack_into(">I", buf, 0, 0xdeadbeef)
print(buf.hex())   # "0000000000000000" — unchanged
```

Note: if `buf` was created via the bridge (e.g. `bytearray(8)` returns a
real CPython PyObject* tagged as FPY_TAG_OBJ), it IS passed through
by-reference and mutation works. The issue only manifests if `buf` were
somehow represented as FPY_TAG_BYTES (fastpy's immutable bytes), which
would be copied. In practice, `bytearray()` returns an OBJ-tagged
PyObject*, so this case may already work.

---

## Category 7: CPython ↔ fastpy object-model gap

### 7.1  ✅ fastpy closures and class instances are not PyObjects

**Fixed for closures/lambdas:** `fpy_to_pyobject()` now detects
FpyClosure (via `FPY_CLOSURE_MAGIC` at offset 0) and wraps it in an
`FpyClosureProxy` — a real CPython type with `tp_call` that converts
Python args → FpyList, calls `fastpy_closure_call_list()`, and converts
the result back. The proxy increfs the closure on creation and decrefs
on dealloc, so lifetime is correct.

`pyobject_to_fpy()` unwraps the proxy back to the original FpyClosure
pointer when a proxy returns from CPython.

```python
import _functools
print(_functools.reduce(lambda a, b: a + b, [1, 2, 3], 0))
# now works — lambda is wrapped as a callable CPython proxy
```

**Fixed for class instances:** `fpy_to_pyobject()` now detects FpyObj
(via `FPY_OBJ_MAGIC`) and wraps it in an `FpyObjProxy` — a real CPython
type with full protocol support:
- `tp_getattro` → checks methods first (returns `FpyBoundMethodProxy`),
  then data attrs (static slots + dynamic attrs)
- `tp_setattro` → delegates to `fastpy_obj_set_fv()`
- `tp_str` / `tp_repr` → calls `fastpy_obj_to_str()` or `__repr__` method
- `tp_hash` → calls `__hash__` if defined, falls back to pointer identity
- `tp_richcompare` → dispatches `__eq__`/`__ne__`/`__lt__`/`__le__`/
  `__gt__`/`__ge__` methods
- `tp_call` → dispatches `__call__` if the class defines it

`FpyBoundMethodProxy` wraps a specific method bound to an instance,
dispatching to the fastpy method func pointer with up to 4 args.

`pyobject_to_fpy()` unwraps FpyObjProxy back to the original FpyObj
pointer when a proxy returns from CPython (e.g. after `sorted()`
reorders a list of class instances).

```python
class Item:
    def __init__(self, name, value):
        self.name = name
        self.value = value
    def __str__(self):
        return self.name + "=" + str(self.value)

items = [Item("c", 3), Item("a", 1), Item("b", 2)]
result = sorted(items, key=lambda x: x.value)
for item in result:
    print(item)
# now works — class instances are wrapped as proxy objects with attribute access
```

**Still limited for weak references:** `_weakref.ref(Foo())` requires
the target to have a `tp_weaklistoffset`, which the proxy does not
provide.

### 7.2  ✅ `import sys.version` misparse

Fixed in earlier work. The codegen correctly treats `sys.version` as
attribute access on the `sys` module, not as a dotted import. The
`_load_variable` / `_emit_attr_load` path handles this properly.

---

## Category 8: Misc

### 8.1  ✅ `binascii.hexlify` errors then produces `None`, next call segfaults

**Fix:** `pyobject_to_fpy()` now has a NULL guard at the top — if `obj`
is NULL (from a failed bridge call), it returns `{tag=NONE, data=0}`
instead of falling through to `Py_INCREF(NULL)` → segfault. This
prevents the cascading crash where a bridge error produces a tagged NULL
that segfaults on next use.

### 8.2  ✅ `"hello".encode()` segfaults

```python
z = "hello".encode()
print(z)   # SEGFAULT
```

`str.encode()` goes through a code path that produces a bytes-like that
later dereferences bad memory. `bytes([...])` works as a substitute.

### 8.3  ✅ Generator-returning bridge results can't be iterated

```python
import _string
for item in _string.formatter_parser("hello {name}!"):
    print(item)
# now correctly prints tuples like ('hello ', 'name', '', None)
```

**Fix:** `_emit_for_pyobj()` in codegen.py now loads both the tag and
data slots from `fpy_cpython_iter_next()` and stores the loop variable
as a full FpyValue with `"pyobj"` type (preserving the runtime tag).
Previously it only loaded the data slot and hardcoded `"int"`, so
yielded tuples/strings/objects were misinterpreted as raw integers.

---

## Workarounds summary

Nearly all bridge bugs from the initial Linux port have been fixed.
Remaining workarounds:

1. **`bytearray` mutation through the bridge** may still not work if the
   bytearray is somehow represented as FPY_TAG_BYTES (unlikely in
   practice — `bytearray()` returns OBJ-tagged PyObject*).
2. **Weak references to fastpy objects** (`_weakref.ref(Foo())`) require
   `tp_weaklistoffset` which the proxy does not provide.

Previously required workarounds that are NO LONGER NEEDED:
- ~~Always use underscore-prefixed C modules~~ -- native modules now work
- ~~Always pre-bind bytes~~ -- bytes literals and inline bytes() work
- ~~Keep bridge calls to 3 or fewer positional args~~ -- 4+ args now supported
- ~~Don't reassign a variable across bridge return types~~ -- safe refcounting fixed
- ~~Don't expect in-place mutation of lists through the bridge~~ -- list sync-back now works
- ~~Don't use fastpy lambdas as CPython callables~~ -- closure proxy now wraps them
- ~~Don't pass fastpy class instances to CPython functions~~ -- object proxy now wraps them

---

## Fix priority (remaining items)

| Priority | Bug | Rationale |
|----------|-----|-----------|
| **P3** | 8.1 (residual) error propagation | NULL guard added, but error recovery is still exit()/return-None rather than raising fastpy exceptions |
| **P3** | 7.1 (residual) weak references | FpyObjProxy lacks `tp_weaklistoffset`, so `_weakref.ref()` doesn't work on fastpy objects |

All P0, P1, and P2 bugs from the initial Linux port have been fixed.

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
