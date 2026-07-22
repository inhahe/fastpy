# fastpy — Known Issues

Running list of unsolved bugs and technical debt. Each entry should have
enough context to act on later: what the bug is, where in the code it lives,
how to reproduce it, and what the proper fix looks like.

---

## Active Bugs

### BUG-BIGINT-MUL-INT-NULL. A bigint × small-int multiply passes a NULL operand into `fpy_bigint_mul` and segfaults — 2026-07-21

**What:** when the running value of an expression has been promoted to a
bigint and is then multiplied by an `int` literal that fits in i64, codegen
calls `fpy_bigint_mul(a, b)` with one operand NULL (the small int is not
converted to an `FpyBigInt*`). `fpy_bigint_mul` immediately dereferences
`b->length` (offset 8) and faults on the null pointer.

**Reproduce (SlateOS/pure mode — this is how it was found):** a 64-bit FNV-1a
hash. The mask `18446744073709551615` (= 2^64-1) exceeds i64 range, so fastpy
represents it as a bigint; `h = (h ^ c) & mask` then makes `h` a bigint, and
the next line multiplies a bigint by a small int literal:
```python
h = 1469598103934665603
mask = 18446744073709551615        # > i64 max → bigint
h = (h ^ c) & mask                 # h becomes bigint
h = (h * 1099511628211) & mask     # bigint * int-literal → fpy_bigint_mul(a, NULL) → #PF
```
On-target this faulted at `rip` inside `fpy_bigint_mul` with `addr=0x8`
(null + offsetof(FpyBigInt, length)). Confirmed by mapping the crash PC to the
symbol table of the linked ELF (`nm`). NOTE: SlateOS pure-mode ELFs cannot be
tested under WSL/Linux — even a trivial `print(...)` pure-mode binary segfaults
at startup on Linux (the runtime targets SlateOS), so the only valid execution
environment is the SlateOS QEMU boot. Host-bridge mode (CPython) shares
`runtime/bigint.c`, so the bug is likely reproducible there too once host
stdout is available (needs the Python DLL on PATH).

**Likely root cause:** the binary-op codegen path for `*` (and probably the
other bigint arith ops) has a case for bigint×bigint and a case for int×int,
but the **mixed** bigint×int case doesn't wrap the int operand with
`fpy_bigint_from_i64(...)` before calling `fpy_bigint_mul`; it passes the raw
i64 (or a null) as the second `FpyBigInt*`. Compare with how `+`/`&` handle
the mixed case (those evidently promote, since `(h ^ c) & mask` worked).

**Proper fix:** in the bigint arithmetic emission, when exactly one operand is
a bigint and the other is an int, materialize the int operand as a bigint
(`fpy_bigint_from_i64`) — or route the whole mixed op through a runtime helper
that accepts (tag,data) pairs and promotes internally — before calling
`fpy_bigint_mul`/`_add`/`_sub`/etc. Add a codegen/runtime regression test for
`big * small`, `small * big`, and the same for `-`, `//`, `%`.

**Workaround in the meantime:** avoid bigint in hot arithmetic when a native
i64 range suffices. The `services/fastpy-store` SlateOS utility uses a **32-bit**
FNV-1a (`mask = 0xFFFFFFFF`, prime = 16777619) so the running hash stays < 2^32
and `h * prime < 2^57` — entirely inside signed i64, no bigint, no multiply
through `fpy_bigint_mul`.

### BUG-SUBSCRIPT-UNTYPED-PARAM-BRIDGE. Subscripting an untyped function parameter that holds a `str` falls back to the CPython bridge and returns NULL in pure mode — 2026-07-21

**What:** when a user function has an **unannotated** parameter (e.g.
`def fnv1a(s):`) and the body subscripts it (`s[i]`), codegen doesn't know the
receiver is a `str`, so instead of lowering the subscript to the native
`fastpy_str_index` helper it emits the generic CPython object-subscript path:
`fpy_cpython_getattr(s, "__getitem__")` followed by `fpy_cpython_call1(...)`.
In **pure mode** (SlateOS / `-DFPY_PURE_MODE`, `bridge_stub.c`) those bridge
stubs return NULL, so the subscript result is NULL and the next use (here
`ord(s[i])` → `fastpy_ord(NULL)`) dereferences a null pointer and faults.

**Reproduce (SlateOS pure mode — how it was found):** a helper that hashes a
string parameter, called with a `str` argument:
```python
def fnv1a(s):            # untyped param → s[i] uses CPython bridge
    h = 2166136261
    i = 0
    n = len(s)
    while i < n:
        c = ord(s[i])    # s[i] → fpy_cpython_getattr/call1 → NULL → ord(NULL) → #PF
        h = (h ^ c) & 4294967295
        i = i + 1
    return h
```
On-target this faulted at `rip` inside `fastpy_ord` with `addr=0x0` (null `s[0]`
read). Confirmed by mapping the crash PC to the ELF symbol table (`nm`) and by
inspecting the emitted IR: `s[i]` lowered to `@fpy_cpython_getattr(s,
"__getitem__")` + `@fpy_cpython_call1`, whose pure-mode result (`sub.data`) is
NULL. The same `s[i]` at **module scope** (where the variable is statically
known to be a `str`) lowers to `fastpy_str_index` and works — so the defect is
specific to *subscripting a parameter/local of unknown static type*, not the
subscript itself. NOTE: pure-mode ELFs can't be run under WSL/Linux (the runtime
targets SlateOS); the only valid execution env is the SlateOS QEMU boot.

**Likely root cause:** subscript codegen chooses `fastpy_str_index` only when it
statically infers the receiver's type is `str`. For a bare parameter it has no
type, so it defaults to the object path. Adding a `str` annotation
(`def fnv1a(s: str):`) makes the inference succeed and the subscript lowers to
`fastpy_str_index` (verified in IR). The bridge path is simply wrong for pure
mode — there is no CPython to call — so falling back to it produces a guaranteed
crash rather than a graceful error.

**Proper fix:** (1) infer parameter types from call sites / annotations so a
`str`-typed parameter subscripts natively; and/or (2) make the *runtime-tagged*
subscript path (for genuinely unknown types) dispatch on the value tag
(`FPY_TAG_STR` → `fastpy_str_index`, list → element load, etc.) instead of
assuming a CPython object — and in pure mode, raise `TypeError` rather than
dereferencing a NULL bridge result. Add codegen regression tests for
`def f(s): return s[0]` and `def f(s): return ord(s[i])` under pure mode.

**Workaround in the meantime:** annotate the parameter's type
(`def fnv1a(s: str)`, `def to_hex8(v: int)`). The `services/fastpy-store`
SlateOS utility does exactly this so `s[i]` stays on the native
`fastpy_str_index` fast path.

### BUG-FILEREAD-FN-RETTAG. A user function that returns a file-read result is typed `int`, losing the `str` tag — 2026-07-21

**What:** codegen's return-type inference for a user-defined function does not
recognize that the function returns a `str` when the returned value came from a
built-in file object's `read()`/`readline()` (or a local variable bound to
one). The function's inferred return type defaults to `int`, so at the call
site the result is treated as a bare `int` and re-tagged `FPY_TAG_INT`, even
though the underlying value is a valid `FPY_TAG_STR` pointer.

**Reproduce (host):**
```python
import sys
def cat(path):
    f = open(path, "r")
    data = f.read()
    f.close()
    return data
print("version: " + cat(sys.argv[1]), end="")   # TypeError: str + int
```
Runtime raises `TypeError: unsupported operand type(s) for +: 'str' and 'int'`
because `cat(...)` is tagged INT. The **inline** form works fine:
```python
f = open(p, "r"); data = f.read(); f.close()
out = "version: " + data     # OK — `data` is correctly typed str
```
So the defect is specific to the *function-return* path, not the file read or
str-concat themselves.

**Likely root cause:** user-function return types are inferred in a pre-pass
(before function bodies are emitted), but the "this local is a built-in file
object" fact lives in `CodeGen._file_vars`, which is only populated *during*
`_emit_assign` while emitting the body. At pre-inference time `_file_vars` is
empty, so `_infer_type_tag(f.read())` doesn't see `f` as a file var and the
read's return type isn't recognized as `str` → the function return type
defaults to `int`.

**Proper fix:** teach the return-type inference to recognize file-object method
calls independently of emit-time `_file_vars` state. Options:
  1. In the function-signature pre-pass, do a lightweight scan of the body to
     mark locals assigned from `open(...)` as file vars *before* inferring the
     return type (mirror the `_is_open_call` detection used in `_emit_assign`).
  2. Or make `_infer_call_type_tag` map a file-object method call
     (`<filevar>.read`/`readline` → STR, `readlines` → LIST, `write` → INT,
     `close` → NONE) using an AST-level "is this an open()-derived receiver"
     check that doesn't depend on emit ordering.
Then `data = f.read()` types `data` STR, `return data` types the function STR,
and the call site keeps the STR tag.

**Workaround in the meantime:** read files inline (don't return a file-read
result through a user function). The `services/fastpy-cat` and
`services/fastpy-sysinfo` SlateOS utilities use the inline pattern for this
reason.
