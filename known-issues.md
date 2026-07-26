# fastpy — Known Issues

Running list of unsolved bugs and technical debt. Each entry should have
enough context to act on later: what the bug is, where in the code it lives,
how to reproduce it, and what the proper fix looks like.

---

## Active Bugs

### BUG-LIST-ELEM-STR-TAG-LOST. A list whose string element type isn't statically visible as a `str` Constant is typed `list[int]`, so reading the element back mis-tags it (e.g. `len()` → 0) — 2026-07-24

**What:** list element-type inference only recognises **constant** string
elements. When a string element is a non-constant expression (str concat
`a+b`, a `str` Name variable, `str()`/`.upper()`/f-string, etc.), or when the
list is built with `[]` + `.append(...)`, the list is typed `list[int]`.
Subsequent reads (`lst[0]`, `for x in lst`) then reinterpret the stored string
pointer as an `int`, so `len(lst[0])` returns 0 and the value is silently wrong.

**Reproduce (real compile path, differs from CPython):**
```python
a='ab'; b='cd'
l1=[]; l1.append(a+b);  print(len(l1[0]))   # fastpy 0, CPython 4
c=a+b; l2=[]; l2.append(c); print(len(l2[0]))  # fastpy 0, CPython 4
l3=[a+b];               print(len(l3[0]))   # fastpy 0, CPython 4
lit=['abcd','efgh'];    print(len(lit[0]))  # fastpy 4, CPython 4 (constants OK)
```
CPython: `4 4 4 4`; fastpy: `0 0 0 4`. Not covered by the differential suite
(the failing patterns aren't exercised there). Verified pre-existing (reproduces
on parent commit `ac1fb3b`, before the Model-2 work) — this is a type-inference
bug, **not** a refcount/UAF bug (the string isn't freed, just mis-tagged; no ASan
report).

**Where:** `_infer_list_elem_type` (codegen.py ~20296) — the `ast.List`/`ast.Tuple`
first-element fast paths only return `STR` for `ast.Constant` str (20370) and a
few attribute patterns; a `BinOp`/`Name`/`Call` string element falls through to
`return ValueType(VKind.INT)` (20428). Two facets:
  - **(a) literal `[a+b]` / `[c]`** — fixable in `_infer_list_elem_type` by adding
    static string-expression detection (BinOp(Add) typed STR, Name of a str var,
    str()/str-method/JoinedStr calls) to the first-element fast paths (mirror the
    numeric-BinOp handling already present at ~20334).
  - **(b) `l=[]; l.append(<str>)`** — harder/flow-sensitive: an empty-list literal
    is typed `list[int]` and `.append()` does not upgrade the list's element type.
    Proper fix tracks/updates the variable's element ValueType when a homogeneous
    non-int value is appended (or infers list element type from all append sites in
    the function, like the global-scope pass at ~3364 does for module lists).

**Impact:** silent wrong output (worse than a leak) for the common
build-a-list-of-strings-by-append pattern and list literals with computed string
elements. Same root family as the (fixed) BUG-VERSIONINFO-TUPLE-STR-INCREF
(bare-pointer element tag inference).

**Store-side UAF now guarded (2026-07-25, Model-2 Stage 3.1):** the write side of
this mis-inference (`lst[0] = <str>` on a list typed `list[int]`) used the
no-refcount `_inline_list_set` fast path, storing the str pointer with no incref.
Once str-builtin results became Model-2 owned temps, the boundary flush freed the
value while the list still held it → **UAF** at list destroy. `_emit_subscript_store`
now gates `_inline_list_set` on a scalar value tag (`_SCALAR_TAGS_CLS`); heap-tagged
values route through the refcounting `list_set_fv`. This removes the UAF but the
**read-side** facet (inline *get* returning a str element as a raw int → wrong
output / here `len()`→0) is unchanged and remains this bug's open problem.

**Refcount entanglement (do with the container Model-2 stage):** fixing facet
(a) so `[a+b]` is typed `list[str]` is NOT purely additive — it interacts with
BUG-CODEGEN-OWNED-TEMP-OVER-INCREF. Today `[a+b]` is "safe" only because the
mis-typing means the concat is stored/read as an int and never dereferenced as a
string; the Model-2 boundary flush frees the concat (registered by
`_owned_str_concat`) but nothing derefs the freed memory. Once correctly typed
`list[str]`, the freed pointer WOULD be read as a string → UAF **iff** list-literal
element insertion *steals* the concat's +1 instead of increfing. So before
applying facet (a), verify list-literal/append element insertion increfs the
element (Model 2: all consumers incref); do facet (a) in lockstep with converting
containers to Model 2, with a native-ASan check on `[a+b]`, `[str(i) for ...]`,
and `lst.append(a+b)` read-back.

### BUG-CODEGEN-OWNED-TEMP-OVER-INCREF. Owned expression temps leak a refcount; being migrated to Model 2 (borrowed-at-boundary). Stage 1 (str-concat) + Stage 3.1 (str/repr/hex/oct/bin/chr builtins + scalar f-string interpolants) done — 2026-07-24/25 (partially fixed)

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

**Stage 3.1 — str/repr/hex/oct/bin/chr builtins + scalar f-string interpolants — DONE (2026-07-25):**
- **str-producing builtins registered** (codegen.py): `repr`/`hex`/`oct`/`bin`/`chr`
  are unconditionally-owned (`fpy_str_buf`/`fastpy_fv_repr` etc. always return a
  fresh +1 buffer), so their call results are wrapped in `_register_owned_str_ptr`
  in `_emit_builtin_repr/hex/oct/bin/chr`. `str()` is runtime-conditional
  (`fastpy_fv_str`: STR tag → borrowed passthrough, OBJ → conditional user
  `__str__`, else → fresh owned buf), so it is registered **only** when the arg is
  statically a scalar (int/float/bool) via `_call_arg0_is_static_scalar` →
  `_expr_is_static_scalar`. Conservative: a non-scalar arg is never registered
  (→ at worst a leak, never a UAF, per the owned→borrowed-only-leaks asymmetry).
- **f-string scalar interpolants registered**: the `_emit_fstring` generic `else`
  branch calls `_fv_call_str` (runtime tag dispatch); for a statically-scalar
  interpolant that routes through `fastpy_fv_str`'s fresh-buffer (+1) branch, so it
  is now registered under the same `_expr_is_static_scalar` gate. (`{int}`/`{float}`
  interpolation previously leaked ~4 KB/occurrence.) STR/OBJ interpolants take the
  borrowed/conditional paths and are correctly NOT registered.
- **Steal-collision exclusions (avoid register+steal → UAF):**
  - *Attribute store*: str-builtin `Call` nodes (in `_STR_PRODUCING_BUILTINS`, and
    not user fns/aliases) are excluded from the attr-store `_steal` (codegen.py
    ~19063) → the slot *retains* (increfs) instead. Superset-safe.
  - *Inline list set*: `_emit_subscript_store` now only uses the no-refcount
    `_inline_list_set` fast path when the stored value's tag is scalar
    (`_SCALAR_TAGS_CLS`). A list mis-inferred as scalar-element that actually holds
    strings (**BUG-LIST-ELEM-STR-TAG-LOST**) previously stole a registered str temp
    with no incref; the boundary flush then freed it while the list still held it →
    UAF at list destroy. Heap-tagged values now route through the refcounting
    `list_set_fv` setter. (The read-side facet — inline *get* mis-reading a str
    element as int → wrong output — is unchanged and still tracked under
    BUG-LIST-ELEM-STR-TAG-LOST.)
- **Verified (native ASan, pure mode)**: dropped/var/attr/dict/typed-list stores of
  `str/repr/hex/oct/bin/chr`, `str(float)`, scalar+str f-string interpolation, and
  str-var reuse after interpolation (no UAF) are all **leak-free with no
  UAF/double-free**, outputs match CPython; differential suite **314 passed**.

**Stage 3.3 — format-spec + json.dumps + bytes concat/repeat — DONE (2026-07-26):**
- **str.format()/f-string `{:spec}` format-spec results registered** (codegen.py):
  the 13 `format_spec_{str,int,float}` call sites in `_apply_format_spec` /
  `_apply_format_spec_dynamic` now go through the new `_fmt_spec_call` helper,
  which wraps the result in `_register_owned_str_ptr` (each `fastpy_format_spec_*`
  is unconditionally-owned — `fpy_str_buf`). The obj `__format__` path and the
  empty-constant returns are excluded (may be borrowed / not heap). Was ~4 KB/leak.
- **json.dumps registered**: `_emit_json_call` "dumps" branch wraps the
  `fastpy_json_dumps_fv` result (unconditionally-owned, `fpy_str_copy`) in
  `_register_owned_str_ptr`. Was ~5 KB/leak.
- **bytes concat/repeat** now use dedicated `fastpy_bytes_concat`/`fastpy_bytes_repeat`
  runtime funcs (header-backed `fpy_bytes_alloc`, length-preserving `fpy_bytes_len`)
  registered as owned FPY_TAG_BYTES temps via `_owned_bytes_result`. See
  **BUG-BYTES-REPR-AS-STRING** below for the underlying representation fix that made
  this correct (bytes were formerly FpyString-headered → OOB header reads + strlen
  length bug + a genuine leak since bytes are pure-refcount, not GC-tracked).
- **Verified (native ASan, pure mode)**: `str.format`/f-string specs, `json.dumps`,
  and `b1+b2` / `b*n` / embedded-null concat in a 1000-iter drop loop are all
  **leak-free**, outputs match CPython; differential suite **314 passed**.

**Still leaking (later Model-2 stages):**
- **str()-family owned producers** (Stage 2 remainder): `str()`/f-string interpolation
  of **non-static-scalar** values (e.g. `str(<obj with owned __str__>)`, a
  call-returned int). Not yet registered. (str-methods `.upper()/.lower()/.strip()/
  .replace()/.split()/.join()` etc. and `.format()` are already registered — Stage
  3.2/3.3.) **Note:** *bytes* methods now have their own leak-free bytes-native
  runtime and register as `FPY_TAG_BYTES` owned temps — see
  BUG-BYTES-METHODS-STR-RUNTIME below (FIXED).
- **Function-call results dropped at the call site** (Stage 3): `foo()` /
  `print(ret(a+b))` — a user-function that returns an owned value has its result
  neither registered nor released at the *caller*. Note this means returning a
  concat and dropping it in the caller still leaks — the leak is at the **call
  site**, not the callee return (even a perfect callee would leak there). Also
  covers the dynamic MIXED `a+b` binop path (33078), which is runtime-conditional
  so can't be registered unconditionally.
- **Containers/objects** (Stage 3): codegen still uses store-site `_steal` (Model 1)
  for container/class *literals*, but the runtime container setters have been made
  **retain-consistent** (see BUG-CONTAINER-STORE-STR-TEMP-UAF below) so a registered
  str temp stored via `dict[k]=<str-expr>` is no longer a UAF. Containers don't leak
  *observably* because lists/dicts/objects are `fpy_gc_track`'d
  (objects.c:320/1870/6957) so a leaked refcount is GC-swept; strings are pure-
  refcounted (no `gc_node`) so their leaks are genuine/LSan-visible. When fully
  converting containers to Model 2, the codegen container `_steal` cases must be
  removed in lockstep (register + steal into a now-retaining setter = double-release
  → UAF).

**Why the staging is safe:** registration is purely additive (more boundary
decrefs). A value is only ever registered by ONE producer, and no registered value
is also stolen (the remaining `_steal` set is container/class literals only, never
str-concat). Mis-tagging owned→borrowed only leaks; only borrowed→owned = UAF, so
each stage stays conservative. Validate every stage with the broad native-ASan
sweep (concat/str()/upper/lower/replace/strip/format/split/join/dict-build/
comprehension/f-string/user-fn-return, nested & discarded temps, in & out of loops,
if/while conditions, break/continue/return, borrowed re-assignment `a=b`, subscript
`a=lst[0]`, attr `a=o.x`) **plus** the full differential suite.

### BUG-BYTES-REPR-AS-STRING. Bytes literals were emitted as FpyString constants (wrong header) — FIXED 2026-07-26

**What (was):** `_emit_constant_value` emitted a `bytes` literal via
`_make_string_constant(value.decode('latin-1'))`, producing an **FpyString**
constant — header `{i32 magic=STRC, i32 refcount}` 8 bytes before the data —
but the value was tagged `FPY_TAG_BYTES`. Every `fpy_bytes_*` accessor reads an
**FpyBytes** header `{i32 magic=BYTE, i32 refcount, i64 length}` **16** bytes
before the data. So on any bytes literal:
- `fpy_bytes_header` (ptr-16) read 8 bytes off the front of the global → an
  **out-of-bounds read** (ASan `global-buffer-overflow`; on the concat result it
  was a heap-buffer-overflow via `len(b1+b2)`);
- `fpy_bytes_len` found no BYTE magic → fell back to `strlen`, so **embedded null
  bytes truncated the length** (`len(b"a\x00b")` gave 1, not 3);
- registering a bytes value as a refcount temp crashed in `fpy_bytes_incref`.

**Fix:** new `_make_bytes_constant(value: bytes)` emits a real FpyBytes-layout
global — `{i32 magic=BYTE, i32 refcount=IMMORTAL, i64 length, i8 data[]}` (data
NUL-terminated for C-compat) — and returns a GEP to `data` (field 3). `refcount
= FPY_RC_IMMORTAL` so incref/decref are no-ops and the read-only global is never
written/freed. `_emit_constant_value`'s bytes branch now calls it. Also added
`FPY_TAG_BYTES` cases to `fpy_rc_incref`/`fpy_rc_decref` (via new inline
`fpy_bytes_incref`/`fpy_bytes_decref` on the FpyBytes header) so bytes temps are
refcounted, and rewrote the dynamic `fastpy_fv_binop` bytes concat/repeat blocks
(objects.c) to use `fpy_bytes_alloc`+`fpy_bytes_len` instead of bare
`malloc`+`strlen` (were leaking + null-truncating). Verified: `b1+b2`, `b*n`,
embedded-null concat, `len`, index, `==` all leak-free under ASan and match
CPython; differential suite 314 passed.

### BUG-BYTES-METHODS-STR-RUNTIME. bytes methods route through str runtime helpers → leak + wrong element type + embedded-null truncation — FIXED 2026-07-26

**What (was):** methods on a `bytes` value (e.g. `b"Hello".lower()`,
`b"a,b,c".split(b",")`) were lowered to the **str** runtime helpers
(`fastpy_str_lower`, str split, …), which:
1. **Leaked** — `fastpy_str_lower` returns a fresh owned `fpy_str_buf` FpyString
   that was *not* registered as a Model-2 owned temp (LSan: 14-byte direct leak
   from `fastpy_str_lower` on `b"Hello".lower()`).
2. **Produced the wrong element type** — `b"a,b,c".split(b",")` yielded a list of
   **str** elements; fastpy printed `['a','b','c']` where CPython prints
   `[b'a',b'b',b'c']`.
3. **Truncated on embedded nulls** (str helpers are `strlen`-based), and the
   FpyString result carried a STRC header while tagged BYTES.

**Fix:** added bytes-native runtime helpers in `runtime/runtime.c`
(`fastpy_bytes_upper/lower/strip/lstrip/rstrip`, `fastpy_bytes_replace`,
`fastpy_bytes_split_sep`, `fastpy_bytes_join`, plus helpers
`fpy_bytes_is_ws`/`fpy_bytes_find`/`fpy_bytes_strip_impl`/
`fpy_bytes_list_append_slice`). All are `fpy_bytes_len`-based (embedded-null
safe), allocate results via `fpy_bytes_alloc` (real FpyBytes header), and
`split`/`join` build/read lists of `fpy_bytes_val` elements. `_emit_method_call_bytes`
(codegen.py) now routes `upper/lower/strip/lstrip/rstrip/replace/split/join`
to these and wraps the single-bytes results in `_owned_bytes_result` so they
register as `FPY_TAG_BYTES` Model-2 owned temps. Also fixed the bytes **repr**
in `objects.c` (both `fpy_value_repr` and `fpy_value_write` paths) to use
`fpy_bytes_len` instead of `strlen`, so `b"a\x00b".upper()` reprs as `b'A\x00B'`.
Verified leak-free under ASan/LSan and byte-exact vs CPython for upper/lower/
strip/lstrip/rstrip/replace/split(sep)/split()/join incl. embedded-null cases;
314 differential tests pass.

**Known remaining gaps (minor):** `bytes.replace(old, new, count)` ignores the
`count` argument (always full replace); `bytes.split(sep, maxsplit)` ignores
`maxsplit` (always full split). Both were also imperfect under the old str
routing; tracked as small follow-ups.

### BUG-BIGINT-BITWISE-MIXED. [FIXED for static path] A bigint bitwise op (`&`/`|`/`^`/`<<`/`>>`) against an int crashed — the crash blamed on `*` was actually `&` — 2026-07-21 (fixed 2026-07-26)

**Title note:** this was originally filed as `BUG-BIGINT-MUL-INT-NULL` ("a
bigint × small-int multiply segfaults"). That diagnosis was **wrong**. The
faulting op in the FNV-1a repro is the bitwise `&` on line
`h = (h ^ c) & mask`, not the `*`. `fpy_bigint_mul` and the other bigint
*arithmetic* ops already promote a mixed int operand correctly. The bug was
that the bigint binop dispatch dict (`_bigint_ops` in codegen) had **no
bitwise/shift entries at all**, so `&`/`|`/`^`/`<<`/`>>` with a bigint operand
fell through to the CPython bridge slow path, which dereferenced an integer as
a pointer → access violation.

**Reproduce (host-bridge mode, reproduced on Windows):** a 64-bit FNV-1a hash.
The mask `18446744073709551615` (= 2^64-1) exceeds i64 range → bigint:
```python
h = 1469598103934665603
mask = 18446744073709551615        # > i64 max → bigint
c = 65
h = (h ^ c) & mask                 # `&` with a bigint operand → crash (was 0xC0000005)
```

**Fix (static path, committed 7e126c8):** implemented
`fpy_bigint_and/or/xor/lshift/rshift` in `runtime/bigint.c` (two's-complement
widening to honor Python's infinite-width negative semantics; floor/arithmetic
right shift), declared them in `runtime/bigint.h` and codegen, and added
`BitAnd/BitOr/BitXor/LShift/RShift → bigint_and/...` to `_bigint_ops`. The
positive-operand cases now compute correctly and no longer crash. Validated:
314 differential tests pass.

**Still broken — DYNAMIC path (see BUG-BIGINT-BITWISE-DYNAMIC below):** when an
operand's *inferred* vtype is FVALUE/UNKNOWN (e.g. a negated bigint variable
`-B`, which returns an FpyValue tagged BIGINT), the op routes to
`_emit_binop_unknown` instead of the static `_bigint_ops` path. That dynamic
path still has no bigint-bitwise handling, so inline `(-B) & 255` etc. produce
wrong output. Tracked separately.

### BUG-BIGINT-BITWISE-DYNAMIC. [FIXED] Bitwise ops on a runtime-tagged (FVALUE/UNKNOWN) bigint go through `_emit_binop_unknown` / `fastpy_fv_binop`, which lacked bigint-bitwise handling — 2026-07-26

**Fix (committed):** (1) `fastpy_fv_binop` (objects.c) now handles bitwise/shift
opcodes 6=and,7=or,8=xor,9=lshift,10=rshift for integer-like operands by
promoting to BigInt, calling `fpy_bigint_and/or/xor/lshift/rshift`, and
demoting the result to a native INT when it fits (the promoted int operands
are freed; a caller BigInt is not). (2) codegen routes bitwise ops through
fv_binop with those opcodes in every dynamic sub-path of `_emit_binop`/
`_emit_binop_unknown`: the FpyValue-operand branch (was `_emit_int_binop`,
which corrupted a BigInt pointer), the UNKNOWN+INT BigInt branch (`_fv_ops`
lacked bitwise → defaulted to opcode 0=Add), and the general
"UNKNOWN-with-extractable-tags" dispatch (`_fv_op_map` lacked bitwise). The
both-UNKNOWN int/float fast path now *excludes* bitwise so a runtime-BigInt
operand doesn't get routed through `_emit_float_binop`. Validated: `(-B)&k`,
`mask & x` (int var), the 64-bit FNV-1a hash loop, and 314 differential tests
all pass.

**Known remaining (separate bug):** see BUG-INT-LSHIFT-OVERFLOW below —
`7 << 70` (pure int<<int that overflows i64) still gives garbage because the
static `_emit_int_binop` LShift is a bare `shl`. That is orthogonal to the
dynamic-dispatch bug fixed here.

### BUG-INT-LSHIFT-OVERFLOW. Static `int << int` that overflows i64 is not promoted to BigInt — `7 << 70` gives garbage — 2026-07-26

**What:** `_emit_int_binop` (codegen ~34482) lowers `ast.LShift` to a bare
`self.builder.shl(left, right)`. When the shift amount is >= 64 (or the result
exceeds i64), LLVM `shl` is poison/UB and the result is garbage (e.g. `7 << 70`
→ `20` instead of `8264141345021879123968`). Unlike `+`/`-`/`*` (which route
through `fpy_checked_*` and promote to BigInt), shift has no overflow-checked
path.

**Reproduce:**
```python
print(7 << 70)     # CPython: 8264141345021879123968 ; fastpy: 20
```

**Proper fix:** add `fpy_checked_lshift(int64_t a, int64_t b, FpyBigInt **big)`
(bigint.c/.h) mirroring `fpy_checked_mul`: if `a << b` fits i64 return it, else
set `*big` to the BigInt result. Route `ast.LShift` in `_emit_int_binop`
through it (localized to shift only, so non-shift arithmetic keeps its
`_program_uses_bigint` gating), and ensure the AST bigint detector flags
programs using `<<` with a large/limit-exceeding shift so `_program_uses_bigint`
is set. RShift, And, Or, Xor cannot grow past i64, so they stay bare ops.

**What:** the static fix above (`_bigint_ops`) only fires when codegen has
*statically* inferred a BIGINT vtype for an operand. When an operand's inferred
kind is FVALUE/UNKNOWN — the clearest trigger is a unary-negated bigint var
`-B`, whose inline lowering returns an `FpyValue` struct tagged BIGINT at
runtime but typed FVALUE/UNKNOWN at compile time — the binop is dispatched
through `_emit_binop_unknown` (codegen ~33210). For bitwise ops that path falls
back to `_emit_int_binop` (the i64 path, ~34071-34076), which treats the
bigint's tagged pointer as a raw i64 and corrupts it → wrong result or crash.

**Reproduce:**
```python
mask = 18446744073709551615
B = mask          # bigint
n = -B            # `-B` → FpyValue tagged BIGINT, inferred kind FVALUE/UNKNOWN
print(n & 255)    # routes to _emit_binop_unknown → i64 path → wrong (should be 1)
```
(Contrast: `n = -B` bound to a var *then* `n & 255` with `n` statically bigint
works; the failure is specifically the runtime-tagged dispatch.)

**Proper fix:** (1) extend the runtime dynamic-binop helper `fastpy_fv_binop`
(`runtime/objects.c` ~1007) to handle the bitwise opcodes when either operand
carries a BIGINT tag — promote int operands via `fpy_bigint_from_i64` and call
`fpy_bigint_and/or/xor/lshift/rshift`; (2) in codegen `_emit_binop_unknown`,
route bitwise ops through `fastpy_fv_binop` when a BIGINT tag is possible,
instead of the unconditional i64 `_emit_int_binop`. Add regression tests for
`(-big) & k`, `(-big) | k`, `(-big) ^ k`, `(-big) << k`, `(-big) >> k`.

### BUG-BYTES-ITER-CRASH. [FIXED] `for c in some_bytes:` crashes — `_emit_for` has no BYTES branch — 2026-07-26

**Fix (committed):** added `_emit_for_bytes` (mirrors `_emit_for_string` but
uses `fastpy_bytes_len`/`fastpy_bytes_get` and binds the loop var as INT), and
wired `_emit_for` dispatch for VKind.BYTES named vars, `b"..."` literals, and
any expression inferred BYTES. Validated: `for c in b"ABC"` yields 65/66/67,
embedded-null bytes iterate correctly, 314 differential tests pass.

**What:** iterating a `bytes` object in a `for` loop crashes. `_emit_for`
(codegen ~22736) dispatches on the iterable's VKind and has branches for
str/list/range/etc. but **no VKind.BYTES branch**, so a bytes iterable falls
through to a path that doesn't understand the FpyBytes layout.

**Reproduce:**
```python
data = b"ABC"
for c in data:
    print(c)      # should print 65, 66, 67
```

**Proper fix:** add a VKind.BYTES (and bytes-Constant) branch to the `_emit_for`
dispatch that iterates `i in range(fpy_bytes_len(data))` yielding
`fastpy_bytes_get(data, i)` as an int byte value, mirroring `_emit_for_string`.

**Workaround:** index manually — `i = 0; n = len(data); while i < n: c = data[i]; ...`.

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

### BUG-CONTAINER-STORE-STR-TEMP-UAF (fixed 2026-07-24)

Storing a Model-2-registered owned **string temp** into a dict/set via the
`_fv` (flat-value) setters caused a **heap-use-after-free**: the setter *stole*
the pointer (no incref), but the statement-boundary watermark flush released the
temp's +1 (Stage 1/2 of BUG-CODEGEN-OWNED-TEMP-OVER-INCREF) **and**
`fpy_dict_destroy` also decrefs stored values at teardown — so the concat's one
refcount was conceptually freed twice while the container held a now-dangling
borrowed pointer. Reproduced under native ASan with `d["k"] = a + b` inside a
loop (heap-use-after-free on the freed `FpyString`).

**Root cause:** the `_fv` dict setters were the sole **steal-model outliers** in
an otherwise retain-consistent runtime. `fastpy_dict_set_fv` /
`fastpy_dict_set_int_fv` / `fastpy_dict_set_kv_fv` (objects.c ~1959/2103/2185)
stored the caller's value *without* increfing, whereas the internal
`fpy_dict_set_unlocked` (1880), list append, `set_add_fv`, and both obj setters
(`fastpy_obj_set_slot`/`fastpy_obj_set_fv`, 6970/7006) already **retained**
(increfed on store, decrefed the old value on overwrite). Because
`fpy_dict_destroy` decrefs, the steal path left the container's held ref
unbalanced against both the destroy-time decref and the Model-2 boundary flush.

**Fix (objects.c):** make the three `_fv` dict setters retain, matching the
internal setter / list / obj / set paths — the *safe* direction (a missed
release only ever leaks a GC-backstopped container ref; it can never UAF):
- `fastpy_dict_set_fv`: `FPY_VAL_INCREF(k); FPY_VAL_INCREF(v);` after building the
  value; the string-key overwrite branch now `FPY_VAL_DECREF`s the old value and
  `FPY_VAL_DECREF`s the (already-held) new key before returning.
- `fastpy_dict_set_int_fv`: `FPY_VAL_INCREF(v);` (int key isn't refcounted);
  overwrite branch decrefs the old value.
- `fastpy_dict_set_kv_fv`: `FPY_VAL_INCREF(k); FPY_VAL_INCREF(v);`; `fpy_key_equal`
  overwrite branch decrefs the old value and the new key.
- `fastpy_dict_clear`: now decrefs every key+value before zeroing `length` (was
  leaking all entries). `fastpy_dict_set_int_int` left unchanged (pure int
  key+value, no heap refs).

**Why this is correct / why no codegen leak-recovery was needed:** container
*values* are GC-tracked (FpyList/FpyDict/FpyObj mark-swept in gc.c), so any
residual creation-ref on a stored list/dict/obj value is swept at exit — no
permanent leak, so codegen doesn't need to release unregistered container-value
producers. **Strings** are the only refcount-only heap type (no `gc_node`), and
the retain fix makes their store balance exactly against the Model-2 boundary
flush. Misclassifying owned→borrowed only leaks (safe); the dangerous
borrowed→owned direction is avoided because the setter now always takes its own
ref.

**Validated:** native-ASan probes — dict value, dict key, overwrite, str-method
value, set literal, `dict.clear`, obj attr, nested dict, and a 200-iteration
reassign-each-loop stress (`P` attr + nested dict) — all leak-free, no UAF,
correct output (EXIT=0); full differential suite **314 passed**.

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
