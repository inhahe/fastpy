# fastpy — Known Issues

Running list of unsolved bugs and technical debt. Each entry should have
enough context to act on later: what the bug is, where in the code it lives,
how to reproduce it, and what the proper fix looks like.

---

## Active Bugs

### BUG-CODEGEN-OWNED-TEMP-OVER-INCREF. Owned expression temps leak a refcount; being migrated to Model 2 (borrowed-at-boundary). Stage 1 done: str-concat temps released at statement boundary — 2026-07-24 (partially fixed)

**What:** `_store_variable` (codegen.py:~21434) increfs the stored value unless
its caller passes `steal=True`, treating the RHS as **borrowed**. But many
expressions produce an **owned** value (rc 1). Under the old mixed model an owned
value stored bumped rc 1→2 and never returned to 0 → leak; owned temps that never
landed in a variable (nested/discarded) leaked unconditionally.

**Chosen fix: Model 2 (borrowed-at-boundary, CPython-like).** Owned producers
register their (+1) result on `_rc_temps`; *all* consumers uniformly incref to
retain; a **watermark flush** at each statement/condition boundary releases every
temp registered since the mark. Being rolled out in stages.

**Stage 1 — string concatenation — DONE (2026-07-24):** infrastructure +
str-concat producers converted.
- Infra (codegen.py): `_register_owned_temp` appends `(tag,data)` to `_rc_temps`;
  `_flush_rc_temps_to(mark)` pops back to `mark`, emitting `rc_decref` **only when
  the block is not terminated** (terminated ⇒ truncate silently, so return/break/
  continue are auto-safe — the returned temp's +1 transfers to the caller or leaks
  exactly as before, never a UAF); `_flush_rc_temps` = flush-to-0.
- Watermark call sites: `_emit_stmts` (mark before each stmt, flush after),
  `_emit_if` (flush condition temps before cbranch), `_emit_while` (flush condition
  temps each iteration inside cond_block). `_emit_for` deliberately does **not**
  flush — the iterable temp is registered during the `for` statement and released
  by the enclosing `_emit_stmts` after the whole loop, so it survives all
  iterations.
- Producers: `_owned_str_concat(args)` calls `fastpy_str_concat` (always a fresh
  `fpy_str_alloc`, rc 1) and registers the result. Wired into the statically-typed
  `str + str` binop path and the closure-result str-concat paths in `_emit_binop`,
  and the local-var `str +=` augmented-assign path. The old concat `_steal` case in
  `_emit_assign` was **removed** (register + steal would double-release → UAF).
- Verified (native ASan, pure mode): stored `c=a+b`, nested `out=a+b+"cc"` (inner
  temp freed), discarded `len(a+b)`, augmented `s+=b`, in-loop `acc=acc+"x"`, and
  concat in if/while conditions + break + nested loops are all **leak-free with no
  UAF/double-free** (values correct); differential suite **314 passed**.

**Still leaking (later Model-2 stages):**
- **str()-family owned producers** (Stage 2): `str()`, `repr`, `hex/oct/bin`,
  `.upper()/.lower()/.strip()/.replace()/.split()/.join()/.format()`, `json.dumps`,
  format-spec, f-strings (`ast.JoinedStr`), bytes concat. Not yet registered.
  (`str(k)` still leaks ~4 KB per call — `fastpy_fv_str` over-allocs a large buf.)
- **Function-call results dropped at the call site** (Stage 3): `foo()` /
  `print(ret(a+b))` — a user-function that returns an owned value has its result
  neither registered nor released at the *caller*. Note this means returning a
  concat and dropping it in the caller still leaks — the leak is at the **call
  site**, not the callee return (even a perfect callee would leak there). Also
  covers the dynamic MIXED `a+b` binop path (33078), which is runtime-conditional
  so can't be registered unconditionally.
- **Containers/objects** (Stage 3): still use store-site `_steal` (Model 1). They
  don't leak *observably* because lists/dicts/objects are `fpy_gc_track`'d
  (objects.c:320/1870/6957) so a leaked refcount is GC-swept; strings are pure-
  refcounted (no `gc_node`) so their leaks are genuine/LSan-visible. When converting
  containers to Model 2, the container `_steal` cases must be removed in lockstep
  (register + steal = double-release → UAF).

**Why the staging is safe:** registration is purely additive (more boundary
decrefs). A value is only ever registered by ONE producer, and no registered value
is also stolen (the remaining `_steal` set is container/class literals only, never
str-concat). Mis-tagging owned→borrowed only leaks; only borrowed→owned = UAF, so
each stage stays conservative. Validate every stage with the broad native-ASan
sweep (concat/str()/upper/lower/replace/strip/format/split/join/dict-build/
comprehension/f-string/user-fn-return, nested & discarded temps, in & out of loops,
if/while conditions, break/continue/return, borrowed re-assignment `a=b`, subscript
`a=lst[0]`, attr `a=o.x`) **plus** the full differential suite.

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

---

## Recently Fixed

### BUG-VERSIONINFO-TUPLE-STR-INCREF (fixed 2026-07-24)

Assigning `sys.version_info` to a variable (`a = sys.version_info`) emitted the
store-incref via the **STR** refcount path on the tuple pointer, so codegen ran
`fpy_rc_incref(FPY_TAG_STR, <FpyList*>)` and `fpy_str_header((char*)list - 8)`
read 8 bytes before the `fpy_list_new` struct — a `heap-buffer-overflow READ of
size 4 in fpy_str_header` (confirmed under native ASan: 8 bytes before the
104-byte `sizeof(FpyList)` region allocated by `fastpy_sys_version_info`,
runtime.c:1377). Benign in production (the stray bytes rarely equal the `"STRC"`
magic, so the incref was silently skipped — the differential suite passed) but a
genuine UB read and a refcount-model violation.

**Root cause:** `_infer_type_tag`'s `ast.Attribute` branch (codegen.py:19668)
never consulted `_native_module_attr_vtype`, so the `i8*`-returning
`sys_version_info` call defaulted to the STR tag for the store-incref decision,
even though `sys.version_info` is statically typed `TUPLE(elem=INT)` (which maps
to `FPY_TAG_LIST` in `_wrap_bare_to_fv`, correctly increfing the `FpyList`).

**Fix:** consult `_native_module_attr_vtype` first in `_infer_type_tag`'s
`ast.Attribute` branch. It returns non-None only for `sys.argv`/`sys.path`
(→ `list[str]`) and `sys.version_info` (→ `tuple`), so the store-incref now uses
the list refcount path; inert for every other attribute access. Validated:
native-ASan reproducer (`import sys; a = sys.version_info; print(a[0])`) goes
`heap-buffer-overflow` → EXIT=0 / leak-free (prints `3`, `14`); full differential
suite 314 passes. (Confirmed the OOB by stashing the fix and re-running the same
harness — reproduced the exact `fpy_str_header` overflow, then restored.)

**Remaining (separate, lower priority):** `version_info` is a *heterogeneous*
tuple but is typed `elem=INT`, which is a lie at index 3 (STR `"final"`), so
`b = a[3]` is typed INT while holding a STR value. A complete fix would model
per-index element types or fall back to a dynamic element kind. (The STR element
itself is now header-backed — see the STR-PRODUCERS fix below.) Not tracked as an
active bug yet; log one if it bites.

### BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC (fixed 2026-07-24)

Most runtime string-*producing* functions returned bare `malloc`'d/`fpy_strdup`'d
`char*` with no `FpyString` `{magic, refcount}` header, so `fpy_str_header(s)`
(which reads `s-8`) did an out-of-bounds read on every incref/decref of such a
string, and `fpy_str_decref` no-oped → the block leaked. Benign on real
hardware/SlateOS (the stray bytes rarely match the `"STRC"` magic, so it's
treated as non-owned), but a genuine UB read that ASan flags and a real leak.

**Fix (this session, coordinated pass):**
1. Added central header-backed helpers in `objects.h`: `fpy_str_copy(src, len)`
   (headered alloc + memcpy → `->data`, refcount 1), `fpy_str_from_cstr(src)`,
   and `fpy_str_buf(len)` (uninitialised headered writable buffer → `->data`).
2. Converted **all** runtime STR-value producers to header-backed allocation:
   the `str.split`/`rsplit`/`splitlines`/`partition`/`replace`/`strip`/`join`/
   `translate`/`repr`/`format` family + `os.path`/`os`/`getenv`/Counter key path
   (objects.c); the scalar producers `fv_repr`/`fv_str`, `list/tuple/dict_to_str`,
   `chr`/`hex`/`oct`/`bin`, `format_spec_{float,int,str}`, `obj_type_repr`,
   `obj_to_str`/`obj_to_repr`, `complex_to_str`, `os_getcwd` (objects.c); the
   `json.loads` parser (`json_parse_string`) and `json.dumps` (`fastpy_json_dumps_fv`),
   which build in a realloc-grown scratch buffer then copy into a headered string;
   `str_repeat`/`lower`/`path_with_suffix`/`textwrap`/`tempfile`/`uuid`, `glob.glob`
   results, and the `sys.version_info` `"final"` literal (runtime.c).
3. Audited direct `free()`/`realloc()` of STR data pointers — the remaining bare
   producers are correctly bare (internal helpers freed via `free(buf)` after a
   `snprintf`/copy, e.g. `fpy_decimal_to_str`; borrowed dict f-string fast-paths;
   error-message temps handed to `fastpy_raise`; the cpython-bridge `fpy_strdup`
   sites, whose results are tagged PYOBJ not STR). BYTES producers
   (`bytes_split`, base64, `int_to_bytes`) are a *separate* value kind and left
   as-is.

**Validated:** full differential suite (314 passed) after each increment; native
ASan (`clang -DFPY_PURE_MODE -fsanitize=address`, WSL) confirmed a real
heap-buffer-overflow in `fpy_str_header` for JSON parse and a global-buffer-overflow
for the `sys.version_info` "final" literal *before* the fix, and EXIT=0 /
LeakSanitizer-clean *after* for json/glob/version_info paths. Commits: `902912e`,
`bf01314`, `190114e`, `99f6f8d`, `56831be`, `004bcbd`.

Two orthogonal bugs surfaced during this work and were logged separately:
BUG-CODEGEN-OWNED-TEMP-OVER-INCREF (codegen leak, Model-2 Stage 1 done) and
BUG-VERSIONINFO-TUPLE-STR-INCREF (assignment type-inference — now fixed, see its
Recently Fixed entry above).

### STR-CONSTANT-BARE-HEADER (fixed 2026-07-24)

String constants emitted from `.rodata` were bare NUL-terminated `i8` arrays
with no `FpyString` header. The runtime's ownership check `fpy_str_header(s)`
reads the magic in the 8 bytes *before* `s`, so for a constant it read off the
front of the `.rodata` array — a benign-on-hardware but genuine out-of-bounds
read that ASan flags (global-buffer-overflow), and which could spuriously match
`"STRC"` in adjacent bytes and mis-treat a constant as owned.

**Fix:** `CodeGen._make_string_constant` (compiler/codegen.py ~2870) now emits
each constant as an `FpyString`-compatible struct global —
`{i32 magic=0x53545243, i32 refcount=0x7FFFFFFF (FPY_RC_IMMORTAL), [N x i8] data}`
— and returns a GEP to `data` (struct field 2). So `fpy_str_header(ptr-8)` lands
on a real, immortal header: incref/decref are no-ops (never writes to the
read-only global, never freed). Validated under the native-ASan harness with a
constant-heavy + file-I/O program (all checks pass, no ASan report).

**Scope note:** this fixed *only* the constant class. Runtime heap string
producers (`split`, concat, `upper`, etc.) were tracked separately as
`BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC` and have since been fixed too — see that
entry under Recently Fixed.

### BUG-STR-OF-PATH-RAISES-IN-PURE-MODE (fixed 2026-07-24)

`str(path)` (and any generic `fastpy_fv_str` conversion of a `pathlib.Path`)
raised `RuntimeError: operation requires the CPython bridge` in pure mode, so
a pure-mode program aborted the moment it stringified a Path.

**Root cause:** codegen tags a `Path` as `FPY_TAG_OBJ` (tag 6) but its data is
a **raw `char*`** (the path text), NOT an `FpyObj`. `_emit_builtin_str` fell
through to the generic `fastpy_fv_str(tag, data)` runtime dispatch, which for
an OBJ reads a would-be `FpyObj` magic and, finding none, routes to
`fpy_bridge_pyobj_str` — a no-op/`RuntimeError` stub in pure-mode builds
(`bridge_stub.c`). Compounding it, a variable bound to a *Path-returning
method call* (`j = d.joinpath(...)`) lost its PATH tag entirely because
`_infer_type_tag` had no case for `<path>.<method>()` calls, so even the
str() PATH-specialization wouldn't fire for it.

**Fix (compiler/codegen.py):** (1) `_emit_builtin_str` now specializes
`str(x)` for a PATH-typed `x` to call `fastpy_path_str(ptr)` — the native
handler that exists in *both* runtimes (pure: `_str_dup(_p(self))`; bridge:
`_path_as_cstr(self)`), mirroring how `.as_posix()`/`__str__` already
dispatch. (2) `_infer_type_tag` now returns `VKind.PATH` for
`<path-expr>.<method>()` calls via `_is_path_expr(node)` (which already
encodes the `resolve/parent/with_suffix/joinpath/absolute` set), so
Path-returning method results keep their PATH tag. Verified with a native
Linux AddressSanitizer build of the real codegen IR + pure runtime (all 10
checks → `ok == 1023`, no RuntimeError) and on-target: the SlateOS
`self_test_fastpy_slateos_pathlib` reports bitmask 1023 (all checks pass).

**Residual tech-debt (not yet fixed):**
- *Path-header collision (low risk):* pure-mode Path buffers are zero-padded to
  ≥40 bytes so the OBJ incref/decref dispatcher's offset-32 magic read is
  in-bounds and reads 0 (`runtime/pathlib_pure.c` `_path_alloc_n`). A path
  whose bytes 32–35 happen to equal `FPY_OBJ_MAGIC` ("SJBO") could still
  misfire. Proper fix: give pure-mode Path a real header struct (magic at a
  controlled offset) instead of a bare `char*`, so the path text never sits at
  offset 0/32.
- *`Path.iterdir()` deferred in pure mode:* needs a runtime list-builder API to
  materialize the directory entries as an FpyValue list.

### BUG-SCALARKIND-LOST-ON-NATIVE-MODULE-CALL-ASSIGN (fixed 2026-07-22)

A variable bound to a *chained* native `os.path.*` scalar result
(`b = os.path.getmtime(p)` → float, `b = os.path.getsize(p)` → int) was
tagged `PYOBJ` instead of its true scalar kind, so a later `int(b)` /
`float(b)` / arithmetic over it bridged to CPython
(`fpy_cpython_call1`/`getattr`/`import`, stubbed/undefined in pure mode).
The inline form (`int(os.path.getmtime(p))`) was unaffected because it never
created an intermediate var.

**Root cause:** `_infer_call_type_tag` only recognized native-module method
calls when `node.func.value` was a bare `Name` (the two-level `os.getsize(f)`
form). For the chained three-level form `os.path.getsize(f)`,
`node.func.value` is an `Attribute` (`os.path`), so that block was skipped and
the generic pyobj-receiver fallback tagged the result `PYOBJ`.

**Fix:** added a chained-form handler in `_infer_call_type_tag`
(compiler/codegen.py, just before the from-import collections block) that
recognizes `<pkg>.<sub>.<fn>` where `<pkg>`/`<pkg>.<sub>` is a native module
and maps the natively-lowered `os.path` functions to their kinds
(join/basename/dirname→STR, getsize→INT, getmtime→FLOAT,
exists/isfile/isdir→BOOL), mirroring the `_os_path_fns` emit map. Verified
bridge-free via `llvm-nm` on the intermediate-var form, and exercised on
SlateOS: `services/fastpy-getmtime` now uses `back = os.path.getmtime(path);
got = int(back)` as an on-target regression test.
