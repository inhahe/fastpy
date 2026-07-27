# fastpy — Known Issues

Running list of unsolved bugs and technical debt. Each entry should have
enough context to act on later: what the bug is, where in the code it lives,
how to reproduce it, and what the proper fix looks like.

---

## Active Bugs

### BUG-FLOAT-KEY-DICT-LITERAL-SEGFAULTS. A dict literal with a float key produces something `len()` crashes on — 2026-07-27

**What:** `_emit_dict_literal` dispatches on the key's LLVM type and has no arm
for `DoubleType`, so it returns `_bridge_fallback_expr` for the whole literal.
Whatever that hands back is then consumed as a native `FpyDict*` — `len(d)`
faults before any lookup happens.

**Reproduce** — the crash is at `len`, not at the subscript:
```python
d = {2.5: "a", 7: "b"}
print("built")     # prints
print(len(d))      # segfault
```

**Where:** `_emit_dict_store_by_key` in `compiler/codegen.py` (the shared setter
dispatch) returns False for a `double` key, and every caller's fallback assumes
the bridge result is interchangeable with a native dict. Both halves are wrong:
the missing arm and the unchecked fallback.

**Proper fix:** add a float arm that bitcasts the double to i64 and stores via
`dict_set_kv_fv` with `FPY_TAG_FLOAT` — the table is uniform and hashes floats
already (`fpy_hash_value`), so this is a missing case rather than missing
machinery. The read side needs the matching arm in the dict-subscript getter,
which today falls to `_bridge_fallback_expr(node, "dict access with non-string
key")` for the same reason; `d[2.5]` on a *mixed* dict built the working way
returns `0` rather than crashing, which is the same gap seen without the
fallback. Audit the bridge-fallback-returns-a-PyObject assumption while there.

**Severity:** segfault on valid Python.

### BUG-DICTCOMP-FV-KEY-EMITS-BROKEN-IR. A dict comprehension whose key becomes FV-typed leaves a block unterminated and the build fails — 2026-07-27 — **FIXED**

**Fixed:** the four comprehension setters and the dict literal now share
`_emit_dict_store_by_key`, which has the `fpy_val` arm they were each missing
and — the structural half — returns False *without emitting anything* so a
caller can fall back before it has built a partial store. The new arm hashes
the key tag-and-all through `dict_set_kv_fv` rather than using the data word as
an int key, which the dict literal had been doing: the word alone cannot tell a
str's address from an int, so `{s: 1}` for a tagged `s = "a"` filed the entry
under the address and `d["a"]` raised KeyError. Passing the key's AST node in
closed the matching hole for comprehension *keys* — an FV-backed variable
arrives as a bare i64 payload, so `{k: 1 for k in ["a", 7, 2.5]}` filed all
three under raw payloads. Covered by
`tests/regressions/dict_key_shapes_that_are_not_strings.py`.

**What:** `_emit_dict_comprehension`'s range path dispatches on the key's LLVM
type — `IntType` → `dict_set_int_fv`, `PointerType` → `dict_set_fv`, and
anything else `return self._bridge_fallback_expr(...)`. That `return` happens
with the builder positioned *inside the loop body*, after `dc.incr` and `dc.end`
have already been created, so those blocks are never terminated and the module
fails to parse. The fallback is reached whenever the loop variable gets promoted
to an `fpy_val` struct, which a BigInt anywhere in the function is enough to do.

**Reproduce** — a compile failure, not a wrong answer:
```python
m = [2 ** 80]
c = {i: m[i] for i in range(1)}
print(c)
```
```
Error: Build failed: LLVM IR parsing error
<string>:1364:1: error: expected instruction opcode
dc.end.8:
```
Drop the `2 ** 80` (`m = [7]`) and it compiles and runs correctly, which is what
identifies the promotion as the trigger rather than the comprehension shape.

**Where:** `compiler/codegen.py`, the key-type dispatch near the end of
`_emit_dict_comprehension`'s range path (and the same `else: return
self._bridge_fallback_expr(...)` shape in its list-iteration path).

**Proper fix:** two parts, and both are wanted. (1) Add the missing
`elif key.type == fpy_val:` arm that extracts the tag/data pair and calls
`dict_set_kv_fv` — the dict *literal* emitter already has exactly this arm, so
the comprehension is just missing a case that exists elsewhere. (2) Decide to
fall back to the bridge *before* emitting any of the loop, so an unsupported key
type can never strand half-built blocks; a mid-loop `return` out of an emitter
is structurally unsafe regardless of which types reach it.

**Severity:** was loud (the build failed), but it failed on valid Python.

### BUG-DICT-IN-COERCES-NON-STR-KEY-TO-CHAR-PTR. `2.5 in {"a": 1}` segfaults — 2026-07-27 — **FIXED**

**Fixed:** the non-str, non-native-int arm of the dict branch of
`_emit_in_compare` now converts the probe with `_to_tag_data_ir` and calls
`fastpy_dict_has_kv_key`, the same uniform tagged lookup the tuple-key arm
already used. Every setter — `dict_set_fv` included — stores keys as tagged
`FpyValue`s in one table, so this finds a str key too and simply misses on a
tag that was never stored. Covered by
`tests/regressions/dict_key_shapes_that_are_not_strings.py`.

**What:** the arm coerced the value to a pointer (`_ensure_ptr`) and handed it
to `fastpy_dict_has_key`, which `strcmp`s it. A `double` operand had its bit
pattern reinterpreted as a `char*`.

**Reproduce** — the answer is just False in CPython:
```python
d = {"a": 1, "b": 2}
print(2.5 in d)    # segfault
```

**Severity:** was a segfault on valid Python.

### BUG-SORTED-KEY-DROPS-TAG. `sorted(xs, key=f)` over a heterogeneous list calls `f` on the raw payload — 2026-07-27

**What:** the key function is applied to the element's i64 payload with the tag
discarded, so it sees a float's bit pattern or a string's address as an int.
Homogeneous lists are fine; it is specifically FV-tagged elements.

**Reproduce** — should print `[10, 2.5, 9, 'a']`:
```python
xs = [10, 9, "a", 2.5]
print(sorted(xs, key=str))   # prints [10, 'a', 2.5, 9]
```
The wrong order is exactly what you get by sorting `str(payload)`
lexicographically: `"10" < "140702223754920" < "4612811918334230528" < "9"`,
i.e. `10, 'a', 2.5, 9`. That arithmetic is the proof of the diagnosis — the key
function really is receiving the untagged word.

Same list with the key removed, or the same key over a homogeneous list
(`sorted([10, 9, 2, 100], key=str)`, `sorted(["bb","a","ccc"], key=len)`,
`sorted([10,9,2,100], key=lambda v: -v)`), is all correct.

**Where:** the `sorted`/`list.sort` `key=` emitter in `compiler/codegen.py`,
which builds the call argument from the bare element instead of the `(tag, data)`
pair `fastpy_list_get_fv` returned. Same family as
BUG-DICT-VALUE-STATIC-KIND and BUG-MINMAX-OF-TAGGED-VALUE: a consumer that
assumes naked scalars.

**Severity:** silently wrong order.

### BUG-IS-NONE-ON-TAGGED-VALUE. `is None` and `== None` against a runtime-tagged expression are always False — 2026-07-27

**What:** `_emit_is_compare` decides `is None` from *AST-level* inference — a
`None` literal, or a `Name` whose `VKind` is `NONE`. A subscript or any other
expression whose noneness is only known from its runtime tag can never satisfy
that test, so it folds to a constant `False`. `== None` is wrong in more cases
than `is None`: even the `Name` form fails.

**Reproduce** — should print `True True True` then `None True True`:
```python
m = [1, None]
no = m[1]
print(no is None, m[1] is None, no == None)   # prints True False False
d = {"o": no}
print(d["o"], d["o"] is None, d["o"] == None) # prints None False False
```

**Where:** `_emit_is_compare` in `compiler/codegen.py`. It bails to AST
inference precisely because the unwrapped value has lost the tag.

**Proper fix:** when either side is the `None` literal and the other emits to an
`fpy_val` (or to a variable whose alloca is `fpy_val`-backed), compare the
extracted tag against `FPY_TAG_NONE` at runtime rather than folding. The
equality path needs the same treatment, since `x == None` must agree with
`x is None` for the built-in `None`.

**Severity:** silently wrong branch — a `None` guard on a value read out of a
container simply never fires.

### ~~BUG-BIGINT-TRUEDIV-UNIMPLEMENTED. `/` on a big int reaches the CPython bridge with a raw `FpyBigInt*` and segfaults~~ — FIXED 2026-07-27

**Fixed:** `fpy_bigint_truediv` in `runtime/bigint.c` implements it the way
CPython's `long_true_divide` does — shift so the integer quotient carries 55
bits (53 of mantissa, one to round on, one for stickiness), fold any remainder
into the low bit, convert once and `ldexp` back — so `(10 ** 400) / (10 ** 399)`
is exactly `10.0` even though neither operand is representable. A zero divisor
returns 1 and an out-of-range quotient returns 2, which the caller turns into
`ZeroDivisionError("division by zero")` and `OverflowError("integer division
result too large for a float")`. `fpy_bigint_bit_length` and
`fpy_bigint_to_double` (written as division by one, so the rounding is not
implemented twice) came with it. The BigInt arm of `fastpy_fv_binop` no longer
falls through for any op, and the codegen guard that keeps native pointers out
of `cpython_binop` now lists BIGINT — see
BUG-BINOP-GUARDS-ENUMERATE-THE-FORBIDDEN, which is the general form of this
bug and was found while fixing it. Covered by
`tests/regressions/bigint_truediv.py`.

**What:** `fastpy_fv_binop`'s BigInt arm implements `+ - * // %` and leaves
`case 3: /* truediv — fall through to float */` empty, with a comment saying
"BigInt / BigInt → float not implemented yet". The fall-through does not stop
there: the value continues to the bridge fallback, which hands the
`FpyBigInt*` to `PyNumber_TrueDivide` as if it were a `PyObject*`.

**Reproduce** — access violation, not a wrong answer:

```python
big = 2 ** 80
print(big / 2)      # CPython: 6.044629098073146e+23;  fastpy: segfault
```

Confirmed under cdb: `python314!PyNumber_TrueDivide+0x23` reading
`[r8+60h]` where `r8` is the `FpyBigInt*`. The zero divisor is not required —
any big-int true division crashes.

**Where:** `runtime/objects.c`, the `lt == FPY_TAG_BIGINT || rt ==
FPY_TAG_BIGINT` arm of `fastpy_fv_binop` (`case 3` and the
`/* truediv falls through */` comment below the switch). `runtime/bigint.h`
has no `to_double` and no `bit_length` to build one from.

**Proper fix:** implement it as CPython does, from the magnitudes rather than
by converting each side to a double first — `(10 ** 400) / (10 ** 399)` is
`10.0` even though neither operand fits in a double. Take ~64 significant bits
off the top of each magnitude, divide those, and scale by the difference in
bit lengths with `ldexp`; raise `ZeroDivisionError("division by zero")` for a
zero divisor and `OverflowError("integer division result too large for a
float")` when the scaled exponent leaves double range. Whatever the result,
the arm must not fall through to the bridge — an unhandled tag combination
reaching `fpy_cpython_binop` with a native pointer is a crash by
construction, so the BigInt arm should end in an explicit TypeError rather
than silently continuing.

**Severity:** high — a hard crash on a basic arithmetic operator.

### ~~BUG-BINOP-GUARDS-ENUMERATE-THE-FORBIDDEN. Three arithmetic guards deny-list the kinds that must stop, so every kind missing from a list is silently mishandled~~ — FIXED 2026-07-27

**What:** the general form of BUG-BIGINT-TRUEDIV-UNIMPLEMENTED, found while
fixing it. Three independent guards in the arithmetic path were written as
"these kinds must not continue", and each was missing entries:

1. `compiler/codegen.py`, the float fast path in `_emit_binop`
   (`_float_incompatible = (STR, LIST, DICT, SET, TUPLE, BYTES, OBJ)`). Every
   pointer kind absent from that tuple — BIGINT, DECIMAL, COMPLEX — reached
   `sitofp(as_i64())`, which converts the *pointer* to a double.
   `print((2 ** 80) + 0.5)` printed `3032756220832.5`: the heap address of the
   FpyBigInt, plus a half.
2. `compiler/codegen.py`, the BigInt fast path just above it, which promoted
   the other operand with `bigint_from_i64(other.as_i64())`. For a float that
   is the double's bit pattern read as an integer, so `(2 ** 80) + 0.5` gave
   `2**80 + 4602678819172646912`.
3. `runtime/objects.c`, the TypeError guard near the end of `fastpy_fv_binop`,
   which listed the container tags plus DECIMAL and COMPLEX. BIGINT was never
   on it, so an op with no BigInt arm fell into the plain i64 arithmetic at
   the bottom and did the sum on the pointer. `None + None` likewise answered
   `0` instead of raising.

**Fixed:** all three are positive checks now — `_float_ok = (FLOAT, INT,
BOOL)`, `_bigint_ok = (BIGINT, INT, BOOL)`, and `(lt is INT or BOOL) and (rt
is INT or BOOL)` — so anything unhandled falls to `fv_binop` or to the
TypeError instead of into an emitter that assumes a machine integer.
`_container_kinds` (the codegen guard against handing a native pointer to
`cpython_binop`) gained BIGINT, DECIMAL and COMPLEX for the same reason, and
`fastpy_fv_binop` grew a BigInt-times-float arm that converts properly.
Covered by `tests/regressions/numeric_guard_falls_through.py`.

**Severity:** was high — silently wrong arithmetic, and a crash in the BigInt
true-division case.

### DEBT-FV-BINOP-HAS-NO-POW-OPCODE. `**` cannot be routed through the dynamic binop, so the `_container_kinds` guard has no fallback for it — 2026-07-27

**What:** noticed while making the three arithmetic guards positive (above).
The guards work by *falling through* to `fastpy_fv_binop` whenever the static
emitter can't prove both operands are machine integers. That fallback exists
for every operator except `**`: the op codes are a dense `0..10` —
`+ - * / // % & | ^ << >>`, see `_FV_BINOP_OPCODES` in `compiler/codegen.py`
and the matching switch in `fastpy_fv_binop` — and `ast.Pow` was never
assigned one. So the `_container_kinds` guard in `compiler/codegen.py`,
which is supposed to stop a native pointer from reaching `cpython_binop`,
cannot redirect a `**` anywhere — there is no op code to redirect it *to*.

Today nothing is visibly broken: `(2 ** 80) ** 2` works because codegen has a
*static* BigInt fast path that maps `ast.Pow: "bigint_pow"` and never consults
`fv_binop`. The hole is only reachable when both operands are runtime-tagged
(FVALUE/UNKNOWN) and at least one is a non-int pointer kind — e.g. a BigInt
that arrived through an untyped parameter, or a dict value read back with a
dynamic tag, raised to a power.

**Reproduce:** not yet reproduced end-to-end; the shapes that would reach it
(untyped-parameter BigInt with `**`) currently take other paths. Treat this as
debt found by reading, not an observed failure.

**Where:** `compiler/codegen.py`, `_FV_BINOP_OPCODES` (~line 36002) and
`_container_kinds`; `runtime/objects.c`, the op-code switch in
`fastpy_fv_binop`; the `ast.Pow: "bigint_pow"` entry in codegen's static
BigInt fast-path table is what covers the reachable cases today.

**Proper fix:** give `**` an op code (11) in `fastpy_fv_binop` with arms for
int/float/BigInt — including the CPython rules the static path already knows
(negative integer exponent promotes to float; `0 ** -1` raises
ZeroDivisionError) — then let `_container_kinds` route `ast.Pow` through it
like every other operator.

**Severity:** low today (unreachable in practice), but it is exactly the shape
of the guard bugs above: a kind the emitter doesn't handle continuing into an
emitter that assumes a machine integer, instead of falling through to a path
that handles it.

### ~~BUG-ARITH-SILENT-ZERO-AND-C-SIGN-RULES. Zero divisors answer 0 or nan instead of raising, and `//`/`%` follow C's sign rules rather than Python's~~ — FIXED 2026-07-27

**What:** found alongside the guard bugs above, same theme — an error or a
wrong answer that looks like a plausible number:

- `fastpy_fv_binop` (the dynamic path) had `ri != 0 ? li / ri : 0` for int
  `/`, `//` and `%` and the same three ternaries in the float arm, so a zero
  divisor produced `0` rather than `ZeroDivisionError`.
- The same two arms used C's `/` and `fmod`, which truncate toward zero and
  take the *dividend's* sign. Python floors and takes the divisor's:
  `-7 // 2` is `-4` not `-3`, and `-7 % 2` is `1` not `-1`.
- `INT64_MIN // -1` is UB in C; in Python it is `2 ** 63`, so it has to
  promote to BigInt.
- codegen inlined float `%` as a bare `frem` plus a sign fixup with no zero
  check, so `1.0 % 0.0` answered `nan`.
- codegen's `_emit_float_binop` sent any bitwise operator to
  `_bridge_fallback_expr`, whose no-match answer is `0` — so `1 & 1.5`
  printed `0` where CPython raises TypeError.

**Fixed:** the runtime arms raise `ZeroDivisionError("division by zero")` and
implement Python's floor/sign rules (including the `INT64_MIN // -1`
promotion); new `fastpy_safe_fmod` gives codegen a float `%` that raises and
signs correctly; the float fast path raises TypeError for bit operators, with
the real operand type names, via the new `_emit_runtime_type_error` helper.
Covered by `tests/regressions/numeric_guard_falls_through.py`.

**Severity:** was high — wrong arithmetic with no diagnostic.

### ~~BUG-UNTYPED-PARAM-BARE-ABI. A parameter with no known type is given the bare ABI, so its runtime tag is dropped and `len()` answers 0~~ — FIXED 2026-07-26

**What:** `_duf_select_abi` granted the bare-type ABI whenever every
parameter's LLVM type was scalar. `param_types` falls back to `i64` when
nothing is known about a parameter, so "no evidence at all" and "known to be an
int" were indistinguishable by the time the ABI was chosen, and an untyped
parameter counted as a scalar one.

**Reproduce** — should print `4`, printed `0`:
```python
"""Doc."""

def sink(v):
    return len(v)

def opaque():
    return "abcd"

print(sink(opaque()))
```
`sink` was emitted as `define internal i64 @fastpy.user.sink(i64 %v)`.

**Root cause:** bare ABI has nowhere to put a runtime tag. The caller unwrapped
the callee's tagged `FpyValue` down to a naked `i64`, and the body then read a
string pointer as an integer.

**Fix:** bare ABI now also requires `_all_params_typed` — every parameter must
carry an annotation or have been classified at some call site. Inferring
"scalar" from silence is what produced the wrong answer. `sink` is now
`define internal {i32, i64} @fastpy.user.sink({i32, i64} %v)`.

**Blast radius, measured:** across the 312-file regression corpus, 11 of 641
functions changed ABI (169 were bare before), all of them nested or closure
functions. Full suite green at 994.

**This is the shared root cause** behind BUG-PARAM-TYPE-FROM-USER-CALL-ARG's
residual, BUG-SPLAT-DEFAULTED-SLOT-TYPE (whose `"mixed"` tag still landed on a
bare `i64` rather than dispatching), and BUG-SUBSCRIPT-UNTYPED-PARAM-BRIDGE.
The last is **not** fixed by this — `s[0]` on an FV-ABI parameter still faults,
because the subscript path has no runtime-tag dispatch arm — but the tag now
survives the call, which is the prerequisite.

**Test:** `tests/regressions/untyped_param_fv_abi.py`. Verified badly wrong at
`b1a665d` (pointers printed as integers, lengths 0). Clean under
ASan/UBSan/LSan.

### ~~BUG-RETURNS-UNTYPED-PARAM-RET-TAG~~ **FIXED**. A function that returns its own untyped parameter was typed `int`, so `len(f(x))` answered 0 — 2026-07-26

**What:** `_duf_determine_ret_tag` had no arm for "returns a parameter whose
type is unknown", so it fell through to the `int` default. The call site then
unwrapped the callee's tagged `FpyValue` to that guess and the tag was gone.

**Reproduce** — should print `abcd 4` / `4`, prints `abcd 4` / `0`:
```python
"""Doc."""

def opaque():
    return "abcd"

def echo(v):
    return v

r = echo(opaque())
print(r, len(r))          # correct — the name-binding path keeps the tag
print(len(echo(opaque())))  # 0
```

**Why the two forms disagree:** exactly the split that was
BUG-DIRECT-CALL-LEN-STATIC-TAG. `_assign_fv_fast_path` keeps the whole
`FpyValue` when storing to a name, while `_emit_user_call` calls
`_unwrap_return_value` unless `_callee_returns_mixed` says otherwise — and that
helper reads `_func_ret_types`, which has no entry here. Meanwhile
`info.ret_tag` is a confident, wrong `"int"`.

**Fix:** `_duf_determine_ret_tag` now reports `"mixed"` when a `return` yields
a parameter with no known type — the honest answer, since the kind is whatever
the caller passed — and `_callee_returns_mixed` falls back to `info.ret_tag`
when `_func_ret_types` has no entry. The declaration pass is the authority for
this one shape because it is the only pass that can see "returns a parameter";
the CSA chain has no arm for it, so the two answers are combined rather than
one deferring to the other.

An *annotated* parameter is excluded even with no call site: the annotation is
evidence, `_duf_select_abi` accepts it as such and may hand the function the
bare ABI, and a bare `i64` return has nowhere to carry a `mixed` tag.

A second gap fell out while testing and is fixed with it: a plain forwarding
wrapper, `def wrap(v): return inner(v)`, has no "returns a user call" arm
either and fell through to the same `int` default. `_csa_propagate_ret_types`
already does this propagation for tags it knows, but it runs *before* the
declaration pass and so cannot see this one. `_duf_propagate_mixed_ret_tags`
is a fixed-point step after Pass 1.1 that spreads `mixed` through such
wrappers, in either definition order. It only touches functions still carrying
the bare `"int"` default, skips bare-ABI ones, and is confined to a direct
`return <user call>`.

**Test:** `tests/regressions/returns_untyped_param_ret_tag.py`. Verified wrong
at `24bfaa4`. Clean under ASan/UBSan/LSan.

### ~~BUG-BYTES-RETURN-TAG-LOST. A `bytes`-returning function loses its tag, so `len()` answers 0 and `print()` shows a pointer~~ — FIXED 2026-07-26

**What:** `_csa_propagate_ret_types` records list/dict/tuple/float/mixed but has
no arm for `return b"abc"` (nor for a plain `return "abcd"` — the str half of
the same gap). A `bytes` value crossing a function return therefore arrives
untagged.

**Reproduce** — should print `3` / `4` / `3` / `b'abc'`:
```python
"""Doc."""

def opaque_bytes():
    return b"abc"

def blen(v):
    return len(v)

def bshow(v):
    print(v)

x = opaque_bytes()
print(len(x))                 # 0
print(blen(b"abcd"))          # 4  — a literal call site types the param
print(blen(opaque_bytes()))   # 3  — correct once the param is typed
bshow(opaque_bytes())         # prints a pointer, not b'abc'
```

Note the third line is *right*: one classifiable call site (`blen(b"abcd")`)
types the parameter and every other site starts working. Remove it and the
answer goes to 0. That is the same "one good call site hides it" property as
BUG-PARAM-TYPE-FROM-USER-CALL-ARG.

**Where:** the return-type propagation chain in `_analyze_call_sites`
(`_csa_propagate_ret_types`) and the declaration pass
(`_duf_detect_ret_type`, `_duf_determine_ret_tag`).

**Fix:** three places in that chain had to learn `bytes`, and each was hiding
the next behind it.

* `_csa_propagate_ret_types` now records `bytes` (and `set`) for a literal,
  a `.encode()`, and a `bytes`/`bytearray`/`set`/`frozenset` call, and
  propagates them through `var_types` like the kinds it already knew. Without
  this nothing downstream could classify a call site that passed one.
* `_duf_detect_ret_type` now returns `i8_ptr` for those same shapes. It used
  to leave the function declared returning `i64`, and every pointer-gated
  path then declined to fire — the BYTES arm of the subscript emitter is
  behind `isinstance(obj.type, ir.PointerType)`, so `ob()[0]` fell through to
  the generic CPython `__getitem__` bridge and faulted.
* `_duf_determine_ret_tag`'s `i8_ptr` arm had no `bytes`/`set` case, so once
  the type *was* a pointer it fell through to the `"ptr"` default — which
  means list. `ob() + b"d"` concatenated as a list and printed `()`. Its
  `return <param>` arm had the same gap, so `len(echo(ob()))` measured a
  bytes object as a list.

Two consumers of the kind were separately blind to it. `_is_bytes_expr` knew
a *variable* could hold bytes but not that a *call* could, so
`b = ob(); b + b"d"` worked while `ob() + b"d"` produced a str; it now reads
the callee's declared return tag, and `_infer_type_tag`'s private duplicate of
the same predicate was deleted in favour of it. The bytes-subscript arm of
`_infer_type_tag` gained the same call case, so `ob()[1:]` is a bytes slice
rather than a str one.

The `str` half of the original gap turned out not to bite: `_duf_detect_ret_type`
and `_duf_determine_ret_tag` both have direct arms for a str literal, and the
forward-referenced case resolves through `_func_ret_types` for the tags it does
record. `tests/regressions/bytes_return_tag.py` pins the str behaviour anyway.

**Test:** `tests/regressions/bytes_return_tag.py`. Verified wrong at `e781cfb`.
Clean under ASan/UBSan/LSan.

### ~~BUG-BYTES-CONTAINS-NO-ARM. `x in b"..."` has no arm in the emitter and faults through the CPython bridge~~ — FIXED 2026-07-26

**What:** found while writing the test above. `_emit_in_compare` dispatches on
the container's kind and had arms for set, list/tuple, ChainMap, dict,
mixed/FVALUE, str, pyobj and obj — but none for `bytes`. A bytes container is a
pointer, so it slid past all of them into the legacy fallback and then the
CPython `__contains__` bridge: an access violation on Windows, NULL in pure
mode. `97 in b"abc"` was enough to crash; it did not need a function return
anywhere.

**Fix:** a `VKind.BYTES` arm placed before the STR one (both are pointers, and
the str path would stop at the first NUL) calling a new
`fastpy_bytes_contains(hay, tag, data)`. The left operand arrives tagged
because Python gives the two forms different meanings — an int asks whether
that byte value occurs, a bytes/str asks whether it occurs as a contiguous
subsequence, and the empty one always does. Everything is length-aware, so an
embedded null byte is matched rather than ending the search, and an int outside
`range(0, 256)` raises `ValueError` as CPython does instead of answering False.

**Test:** covered by `tests/regressions/bytes_return_tag.py`.

### ~~BUG-BYTES-CTOR-BRIDGE-ONLY. `bytes(x)` has no native lowering and returns NULL in pure mode~~ — FIXED 2026-07-26

**What:** also found while writing the test above. The `bytes` builtin was not
in the emitter's dispatch table at all, so every `bytes([65, 66, 67])` went to
the CPython bridge. In pure mode (`-DFPY_PURE_MODE`, i.e. the SlateOS target)
the bridge is compiled out and answers NULL, and the next `fpy_bytes_len` then
subtracted the header offset from a null pointer — UBSan reported *applying
non-zero offset -16 to null pointer* and the read that followed was into
unmapped memory.

**Fix:** `_emit_builtin_bytes` plus a runtime `fastpy_fv_to_bytes(tag, data)`.
The argument is handed over *tagged* so one helper covers all four CPython
behaviours: an int is a zero-fill count, a bytes is a copy, a str without an
encoding is a `TypeError`, and anything else is routed through
`fastpy_fv_to_list` so sets, dicts, ranges and generators need no separate arm.
`fpy_bytes_header`/`fpy_bytes_len` also grew NULL guards, since callers do
legitimately reach them with NULL from other bridge-only operations.

**Deliberately not fixed here:** `bytearray` stays on the bridge. fastpy has no
mutable bytes type, so answering with an `FpyBytes` would make it print
`b'AB'` rather than `bytearray(b'AB')`. See BUG-NO-BYTEARRAY-TYPE below.

**Second half of the fix, found by the full suite:** `_emit_assign` keeps a
`native_builtins` set and tags `x = f(...)` `pyobj` for every builtin *not* in
it, on the reasoning that anything else came back from the bridge as a
`PyObject*`. Adding the lowering without adding `"bytes"` to that set left
`x = bytes(3)` declared `pyobj` while the emitter produced a native `FpyBytes`,
so `print(x)` handed the buffer to `PyObject_Str` — an access violation, caught
by the `binascii`, `gzip` and `zlib` stdlib-import tests. Note for next time:
a new native builtin lowering is two edits, the dispatch table *and* that set.

**Test:** covered by `tests/regressions/bytes_return_tag.py`; the pyobj-tag half
is covered by the `binascii`/`gzip`/`zlib` cases in `tests/test_full_suite.py`.

### ~~BUG-BYTES-SLICE-VIA-STR. Slicing a bytes produced an `FpyString` that was then tagged BYTES — heap-buffer-overflow on every later length probe~~ — FIXED 2026-07-26

**What:** `bytes` and `str` are both `i8*` to the compiler, and that similarity
was taken one step too far: *every* slice was lowered to `fastpy_str_slice` /
`fastpy_str_slice_step`, and a bytes slice was simply re-tagged BYTES
afterwards. Two things are wrong with that. The str helpers walk the buffer by
*code point*, so `"é".encode()[0:1]` gave two bytes where CPython gives one.
And they allocate an `FpyString`, whose header is smaller than an `FpyBytes`
header — so tagging that allocation BYTES made every later `fpy_bytes_len` read
the magic field 16 bytes before the buffer. ASan caught it as a
heap-buffer-overflow read on `b = b"abcd"; print(b[1:3])`; without a sanitizer
it silently read whatever the allocator left there, so the length was garbage
or, more often, accidentally plausible. Verified wrong at `e781cfb`.

**Fix:** real byte-indexed `fastpy_bytes_slice` / `fastpy_bytes_slice_step`
backed by `fpy_bytes_alloc`, selected at all three lowering sites — the static
path when the receiver is known to be bytes, the pointer fallback, and
`fastpy_fv_slice`'s runtime dispatch for a receiver whose kind is only known
then.

Fixing the slice exposed the consumers downstream of it, which had the same
shape of gap: each asked "is this bytes?" with its own partial predicate that
only recognised a *variable*. `_is_bytes_expr` is now the single definition —
taught about slices, and given an optional name-table argument so the static
pre-passes can use it instead of re-implementing it — and the receiver check in
`_infer_type_tag`, the `list()` builtin and the pointer slice fallback all call
it.

**Test:** `tests/regressions/bytes_slice.py`. Clean under ASan/UBSan/LSan.

### ~~BUG-BYTES-IN-LIST-TAG-LOST. A `bytes` stored in a list came back out as a `str` (or as a raw pointer)~~ — FIXED 2026-07-26

**What:** found while writing the test above, and independent of it —
`z = b"abcd"; print([z])` printed `['abcd']` at `e781cfb`. Three separate gaps,
all the same shape:

- `_emit_list_append_expr` has arms that tag the element LIST, DICT, OBJ,
  CLOSURE, PYOBJ, BIGINT and COMPLEX, then falls through to
  `_emit_list_append_value`, which tags *every* unrecognised pointer STR. There
  was no bytes arm, so the element went in mislabelled.
- `_infer_list_elem_type` had no bytes arm either, so `[b"ab", b"cd"]` was typed
  `list:int` and `for p in parts` handed the loop body the raw pointer as an
  integer — `140696617395776 0`.
- the `.append()` pre-pass that types a list built from `[]` had no bytes arm,
  and its own name table never recorded a bytes assignment, so
  `parts.append(b[i:i+2])` left the list typed `list:int` as well.

**Fix:** a bytes arm in each of the three, all calling `_is_bytes_expr`. The
pre-pass passes its `local_var_types`/`loop_var_types` in through the new `env`
argument rather than re-deriving the answer, and `b = b"..."` is now recorded in
`local_var_types` so it can be found there.

**Not fixed, deliberately:** the new append arm does not `rc_decref` the
temporary, mirroring the str pointer path beside it, which also hands its
creation reference to the list. Adding a decref on only one of the two would be
an asymmetry, and the general question of owned temporaries is tracked as
BUG-CODEGEN-OWNED-TEMP-OVER-INCREF.

**Test:** covered by `tests/regressions/bytes_slice.py`.

### BUG-NO-BYTEARRAY-TYPE. `bytearray` has no native type — it prints as a list of ints — 2026-07-26

**What:** fastpy has no mutable bytes type. `bytearray([65, 66])` prints
`[65, 66]` where CPython prints `bytearray(b'AB')`. Verified the same at
`e781cfb`, so this is long-standing rather than a regression; it is recorded
here because the neighbouring `bytes()` work (BUG-BYTES-CTOR-BRIDGE-ONLY above)
deliberately left `bytearray` alone and it would otherwise look like an
oversight.

**Reproduce** — should print `bytearray(b'AB')`, prints `[65, 66]`:
```python
"""Doc."""

print(bytearray([65, 66]))
```

**Where:** no `bytearray` entry in the builtin dispatch table in
`compiler/codegen.py`; it reaches the CPython bridge, which is also why it
cannot work in pure mode.

**Proper fix:** a real `FpyByteArray` object — a header, a length, a capacity
and a `data[]` — with its own tag, its own `repr`, in-place `__setitem__`,
`append`/`extend`, and the mutating slice assignment. That is a genuinely new
runtime type rather than a patch, which is why it was not folded into the
`bytes()` change. Until then `bytearray` should arguably raise rather than
silently answer with a list, but changing that is a user-visible behaviour
decision.

### ~~BUG-SPLAT-DEFAULTED-SLOT-TYPE. A defaulted parameter reached by `f(*seq)` is typed from the default even when the sequence supplies it~~ — FIXED 2026-07-26

**What:** when a splat could reach a slot that *also* had a default, the slot's
static type was taken from the default, so an element of a different kind
landing there was converted to the wrong type.

**Reproduce** — should print `4.0`, printed `3.5`:
```python
"""Doc."""

def g(a, b=0):
    return a + b

xs = [1.5, 2.5]
print(g(*xs))
```
`a` was correctly `float` (a required slot, see BUG-STARARG-SPLAT-DEFAULT-PARAM),
but `b` was typed `int` from `b=0`, so the 2.5 the sequence actually supplies
was truncated to 2.

**Why "let the element win" was not the answer:** whether the slot receives the
element or the default depends on the sequence's *runtime* length, so neither
static answer is safe. Element-wins breaks the mirror case — `d_list(v, n=1)`
splatted from a one-element list of lists would declare `n` a pointer and then
read the integer default `1` as one. Both directions were tried and measured;
each fixes one case and breaks the other.

**Fix — three parts, because the ambiguity had to survive three hand-offs.**

1. **Record it.** The splat block in `_analyze_call_sites` now runs for every
   splat call, not only ones whose element tag it could read, and writes
   `"mixed"` into each splat-reachable defaulted slot unless the element tag
   and the default's type are positively known to agree. An *unreadable*
   sequence is not evidence that the default wins: `mix(*[1, 2.5])` has no
   common element tag at all and still supplies 2.5 to a slot defaulted to `0`.

2. **Let it reach the callee.** `"mixed"` is cleared to `None` in
   `_call_site_param_types` (the merge cannot refine it further), but
   `_function_signatures` keeps it — and the FV-ABI prologue in
   `_efd_store_parameters` read a lone `"mixed"` signature entry as
   `len(_sig_types) == 1`, i.e. as one *known* type, and tagged the parameter
   `"int"` anyway. Both halves of that branch (the pointer one and the scalar
   one) now test for a MIXED entry first. This is why the earlier attempt at
   this fix printed a float's bit pattern rather than dispatching, and it is
   what the old entry meant by "a `None` slot still lands on a bare `i64`".

3. **Narrow it correctly at the call.** `_splat_elem_or_default`'s unwrap tail
   became `_splat_fv_to_param`, shared with the required-slot path (see
   BUG-SPLAT-HETEROGENEOUS-ELEM below).

**Blast radius:** a function with a splat-reachable defaulted slot now loses
the bare ABI unless the element and default types are known to agree. That is
the intended trade — the slot genuinely has no single static type — and the
required-slot fast path is untouched, so `f(*seq)` into an all-required
signature is as cheap as before.

**Test:** `tests/regressions/splat_defaulted_slot_type.py`. Verified wrong at
`157c863`.

### ~~BUG-SPLAT-HETEROGENEOUS-ELEM. A required slot filled by `f(*seq)` is unwrapped by the sequence's static element type, which a heterogeneous sequence does not have~~ — FIXED 2026-07-26

**What:** `_splat_positional_args` filled required slots with
`_list_get_as_bare(list_val, i, elem_type)`, which unwraps the element by the
*static* element type `_get_list_elem_type` reports. That function answers with
a single type even for a sequence that has no single type, so the bits were
reinterpreted.

**Reproduce** — should print `2.5`, printed `4612811918334230528` (the IEEE-754
bits of 2.5 read as an i64):
```python
"""Doc."""

def two(a, b):
    return b

print(two(*[1, 2.5]))
```

**Root cause:** the same one as BUG-SPLAT-DEFAULTED-SLOT-TYPE — a static answer
given where there is no single static answer — reached from the *element* side
rather than the parameter side. The defaulted-slot path had already been made
tag-aware (`_splat_fv_as_double` / `_splat_fv_as_i64`); the required-slot path
had not, because it looked like the case where the type was known.

**Fix:** every splatted element is now read as a tagged `FpyValue` and narrowed
through the shared `_splat_fv_to_param`, which passes it straight through for
an FV-ABI callee and converts it via the runtime tag for a bare-ABI one. The
`list_get_fv` call is the same one `_list_get_as_bare` was already making, so
the FV path costs nothing extra; the bare path adds one tag compare.

**Test:** `tests/regressions/splat_defaulted_slot_type.py`. Verified wrong at
`157c863`.

### ~~BUG-SPLAT-CALL-PICKS-FIRST-SPECIALIZATION. `f(*seq)` against a monomorphized function always calls the first specialization~~ — FIXED 2026-07-26

**What:** `_resolve_specialization` rebuilds a call's signature from its
argument nodes via `_infer_call_arg_type`. A `Starred` node classifies as
`None` and stands for an unknown number of parameter slots, so the rebuilt
signature was `(None,)` — too short, and uninformative. The exact-match loop
missed, the scoring loop gave every specialization zero, and the fallback took
`specs[0]`.

**Reproduce** — should print `3.0` then `4`, printed `3.0` then `1.0`:
```python
"""Doc."""

def h(a, n=1):
    return a + n

print(h(*[1.0, 2.0]))
print(h(*[3]))
```
Two signatures — `('float', 'mixed')` and `('int', 'int')` — so `h` is
monomorphized, and both calls went to the float variant. The integer 3 arrived
in a parameter tagged `float` and was unwrapped by bitcast into a denormal, so
`a + n` came out as `0.0 + 1`.

**Hidden before, because it was only half-wrong:** with the pre-`"mixed"`
signatures the first variant was `('float', 'int')`, whose bare-ABI `double`
parameter made the caller `sitofp` the integer, so the value survived and only
the *type* was wrong (`4.0` instead of `4`). Giving the slot its honest
`"mixed"` tag turned that silent type error into a visible value error.

**Fix:** `_analyze_call_sites` records the signature it computes for a splat
call against `id()` of the call's `Starred` node
(`self._csa_splat_call_sigs`), and `_resolve_specialization` uses that instead
of re-deriving a worse one. One computation, two consumers — the resolver was
never in a position to reproduce it, since it has neither the callee's
parameter list nor the sequence-binding map.

**Test:** `tests/regressions/splat_defaulted_slot_type.py`. Verified wrong at
`157c863`.

### ~~BUG-STARARG-SPLAT-DEFAULT-PARAM. `f(*xs)` raises IndexError when `f` has a default parameter~~ — FIXED 2026-07-26

**What:** splatting into a function that has *any* default parameter failed at
runtime. Nothing to do with the element type — a list of plain ints failed the
same way.

**Reproduce** — should print `6`, raised:
```python
"""Doc."""

def d_int(a, n=1):
    return a + n

ints = [5]
print(d_int(*ints))
```
```
Traceback (most recent call last):
  File "<module>", line 7, in <module>
IndexError: list index out of range
```

**Root cause:** the splat expansion extracted exactly `info.param_count`
elements — `remaining = info.param_count - len(args)` — so a sequence shorter
than the callee's arity was read off the end. `two_pos(*[3, 4])` into
`def two_pos(a, b)` worked and `d_int(5)` worked, so neither splatting nor
defaults was broken alone; it was the combination.

**Fix:** `_splat_positional_args` extracts required parameters unconditionally
(a too-short sequence is a TypeError in Python, and the existing `min_args`
check reports it) and resolves each *defaulted* slot at runtime via
`_splat_elem_or_default`, which emits `seq[i] if i < len(seq) else <default>`
as an `FpyValue` — the two arms need a common LLVM type and an element need not
agree with the default. Mutable defaults still go through
`_load_cached_default`, so `def f(x=[])` is not re-evaluated per call.

**The expansion existed twice.** `_emit_user_call` and `_emit_user_call_fv`
each carried their own copy of the loop, so the first fix left the FV path
still crashing. They now share `_splat_positional_args`; the FV caller only has
to pad its parallel `arg_source_nodes` list.

**A second bug fell out of it:** a parameter fed *only* by a splat had no type
at all, because the per-argument classification in `_analyze_call_sites` had no
arm for `ast.Starred`. `no_default(*lists)` left `v` untyped and `len(v)`
answered 0 instead of 3 — the same silent-zero as
BUG-PARAM-TYPE-FROM-USER-CALL-ARG, reached from the argument side.
`_csa_splat_elem_tag` / `_csa_build_seq_binds` now trace a splatted *name* back
to the sequence literal it was bound to (`_csa_var_types` records only the
coarse kind `"list"`, never the element type) and hand that element tag to
every *required* slot from the splat's position on. A name rebound anywhere is
poisoned rather than guessed at. The defaulted slots are left alone — see
BUG-SPLAT-DEFAULTED-SLOT-TYPE above.

**Test:** `tests/regressions/stararg_splat_default_param.py`. Verified to
IndexError at `2482ae6`. Clean under ASan/UBSan/LSan.

**Follow-up done:** `tests/regressions/param_type_from_call_arg.py` says a
star-args call site cannot be exercised because of this bug; that note is now
stale and the file can use a defaulted callee.

### ~~BUG-PARAM-TYPE-FROM-USER-CALL-ARG. A parameter whose only call-site evidence is a user call is left untyped, and `len()` on it returns 0~~ — FIXED 2026-07-26

**What:** when every call site passes a *call result* for a given parameter, the
parameter gets no inferred type and operations on it silently produce wrong
answers. `len()` returns 0 rather than crashing, so this fails quietly.

**Reproduce** — should print `3 6 4`, prints `0 0 0`:
```python
"""Doc."""

def always_list(n):
    return [n, n, n]

def always_str(n):
    return "ab" * n

def pick(flag):
    if flag:
        return "abcd"
    return [1, 2, 3]

def sink_l(v): return len(v)
def sink_s(v): return len(v)
def sink_m(v): return len(v)

print(sink_l(always_list(5)), sink_s(always_str(3)), sink_m(pick(True)))
```

**Not mixed-specific.** This is the important part: `sink_l(always_list(5))` is
just as broken as the mixed case, and `always_list` has one unambiguous return.
It is also enough for the *slot* to be sole-evidence — adding one call with a
literal (`sink_l([1, 2])` anywhere) types the parameter and everything starts
working, which is why this has stayed hidden: almost all real code eventually
passes a literal somewhere.

**Where:** `_call_site_param_types` (declared ~3693, populated during
`_analyze_call_sites`). Probing the minimal repro shows `{'sink': [None],
'pick': ['bool'], ...}` — the argument slot is `None`. Argument types are
recorded *before* `_csa_propagate_ret_types` runs at 8766, so at the moment an
argument is classified, no callee's return type is known yet.

**Proper fix:** the ordering is the bug. Either run return-type propagation
before argument classification, or iterate the two to a fixed point — an
argument slot left `None` on the first pass should be revisited once
`_func_ret_types` is populated. A fixed point is the honest answer, since
`_func_ret_types` itself propagates through `return f()` chains and so has the
same dependency in the other direction. Do *not* paper over it by
special-casing `len()` on an untyped param.

**Not a regression:** identical `0 0 0` at the parent commit — verified by
stashing.

**Worse than "returns 0":** the regression test showed the untyped parameter
also *crashes* once it is genuinely used. At baseline the test prints `0 0 0`
and then dies with `0xC0000005` (access violation) in `uses_fully`, which
iterates and subscripts the parameter. `len()` answering 0 is just the quietest
symptom.

**Fixed** by `_csa_refine_params_from_call_returns`, a fixed-point step run
after `_csa_post_scan_propagation` (so `_func_ret_types` exists). It fills only
slots that are still `None` and never overrides the main merge. Two rules, in
opposite directions:

* An **unresolvable** caller at a position poisons that position — the slot
  stays untyped, preserving the "unknown doesn't override known" rule.
  Call sites with keywords or `*args` disable refinement for the whole callee,
  since positional slots cannot be aligned through them.
* Callers that all resolve but **disagree** get `mixed`, not `None`. This is
  not a guess: every caller is known, they simply are not the same kind, and
  the merge at the top of the pass already accepts `mixed` as a parameter tag
  (it has an "already mixed, can't refine further" arm). The first draft left
  these `None` and consequently still printed 0 — caught by the `two_kinds`
  case in the test.

**Residual, deliberately not fixed here:** coverage is bounded by what
`_func_ret_types` records, which is list/dict/tuple/float/mixed but **not**
str/bytes/set. There is no arm in `_csa_propagate_ret_types` for a plain
`return "abcd"` — the only place it records `"str"` is for a parameter
forwarded straight through (`return v` where a call site passed a str literal).
So a parameter fed only by a str-returning function is still untyped. That is
the same callee-side absence that caused BUG-MODULE-DOCSTRING-UNBOXES-GLOBAL,
and it should be fixed there rather than papered over on the argument side.

### ~~BUG-DIRECT-CALL-LEN-STATIC-TAG. `len(f(x))` ignores the callee's `mixed` return tag; only `v = f(x); len(v)` is correct~~ — FIXED 2026-07-26

**What:** with BUG-MODULE-DOCSTRING-UNBOXES-GLOBAL fixed, a mixed-kind return
bound to a variable is tagged `mixed` and `len()` dispatches on the runtime tag.
Calling it *inline* still takes a static path and prints garbage.

**Reproduce** — should print `2 2`:
```python
"""Doc."""

def str_or_dict(f):
    if f:
        return "xy"
    return {"a": 1, "b": 2}

print(len(str_or_dict(True)), len(str_or_dict(False)))   # 9223372033957843523 2
v = str_or_dict(True)
print(len(v))                                            # 2 — correct
```

**Where:** the fix for the variable case lands in
`_assign_fv_fast_path` (~17170), which reads `_func_ret_types` when *storing*
to a name. The call-expression path used by `len(<call>)` never consults it, so
it still uses the coarse `info.ret_tag` from the declaration pass. Both `len()`
arms of a mixed function are affected, not just the "wrong" one — the first
call above is wrong for `True` and right for `False` purely by which kind the
guess happened to land on.

**Proper fix:** route the call-expression result through the same
`_func_ret_types` consultation that `_assign_fv_fast_path` does, so a `mixed`
callee yields an FVALUE-typed expression rather than a bare pointer. Ideally
factor the tag choice out of `_assign_fv_fast_path` into one helper both call
sites use, since having two places decide a callee's result type is what let
them drift apart.

**Not a regression:** identical garbage at the parent commit — verified by
stashing the fix and re-running. The `mixed` work neither caused nor fixed it.

**Fixed** at the `_emit_user_call` seam: when `_callee_returns_mixed(name)` —
i.e. `_func_ret_types[name]` is `mixed` — the unwrap is skipped and the whole
tagged FpyValue is handed back. `_emit_expr` already types any `fpy_val`-shaped
result as `VKind.FVALUE`, so no consumer needed changing; `len`, subscript,
slicing, `in`, iteration, `bool()` and `str()` all went correct at once. The
helper deliberately reads `_func_ret_types` rather than `info.ret_tag`, because
agreeing with `_assign_fv_fast_path` is the entire point — the two call sites
drifting apart is what made `v = f(x); len(v)` and `len(f(x))` disagree.

The suggestion above to factor the tag choice into one shared helper was *not*
taken, and deliberately so: the two sites need different things from the answer
(one picks an alloca representation, the other picks whether to unwrap), so the
shared part is only the `_func_ret_types` lookup, which is now one line each.
Merging them would have meant a larger refactor of `_assign_fv_fast_path` for
no behavioural gain. Revisit if a third consumer appears.

**Damage was wider than `len()`:** subscripting a returned str gave an empty
result, `in` answered False, and iterating yielded a single empty item — all
from the same stripped tag. `tests/regressions/direct_call_mixed_tag.py` covers
each, plus the invariant that the direct and via-variable forms agree.

### ~~BUG-MIXED-SCALAR-RETURN-TAG. A function returning an int on one branch and a float on another prints the float's bit pattern~~ — FIXED 2026-07-27

**What:** mixed *scalar* returns were not reconciled at all; the float came back
reinterpreted as an i64.

**Reproduce** — should print `1 2.5`:
```python
"""Doc."""

def int_or_float(f):
    if f:
        return 1
    return 2.5

print(int_or_float(True), int_or_float(False))   # 1 4612811918334230528
```
`4612811918334230528` is the IEEE-754 bit pattern of `2.5`. Binding to a
variable did not help; inside a function it degraded differently
(`5e-324 2.5` — the int reinterpreted as a double), which is the same confusion
in the other direction.

**Where:** the LLVM return type is one of i64 / double, chosen once per
function, and there was no branch-sensitive reconciliation. `_csa_returns_disagree`
(added for BUG-MODULE-DOCSTRING-UNBOXES-GLOBAL) deliberately did **not** cover
this: it is scoped to pointer kinds, on the stated grounds that scalar returns
are "settled by a separate mechanism (the i64 vs double LLVM return type)".
They are not settled by it — that mechanism is exactly the one that picks one
of the two and discards the other.

**Fix.** `_returns_mix_int_and_float` is the scalar counterpart of
`_csa_returns_disagree`, backed by `_literal_scalar_kind` (the counterpart of
`_csa_literal_ptr_kind`) and just as deliberately narrow: constants, unary
`+`/`-`, comparisons, `not`, uniform `and`/`or`, arithmetic binops, `float()`
/`int()`/`len()`/`ord()` calls, and `/` (always float in Python, whatever the
operands). Anything else reads as "no constraint", never as disagreement, so a
lone `return helper()` cannot push a whole function off the bare ABI. Returns
inside nested `def`s and lambdas are excluded; `return 1 if c else 2.5` is
looked through.

Three consumers had to agree, the same shape as the splat fix one commit
earlier:

1. `_duf_select_abi` — `_mixed_scalar_ret` joins the `uses_bare` conjunction
   (and the `_analyze_mode` blocker list), so the value can carry a tag at all.
2. `_duf_determine_ret_tag` — records `"mixed"`, so callers do not unwrap the
   returned FpyValue by a static guess.
3. `_csa_propagate_ret_types` — records `"mixed"` too, so a module-level
   `a = f(...)` is not typed from the guess either. This is the one that fixed
   the `5e-324 2.5` variant.

**Two things the first attempt got wrong:**

* **A bool return is not an int return.** `return True` beside `return -1.5`
  reached `_emit_return`'s `static_ret_type is double` promote path, whose
  IntType arm tagged every integer INT — so the program printed `1` where
  CPython prints `True`. The new bool arm has to run *before* the
  `_is_float_expr` one, because that answers yes for `x > 5` when `x` is
  float-typed, and a comparison is a bool whatever it compares.
* **A `-> float` annotation is not a promise.** Python does not enforce it, so
  `def a(x) -> float: return 1` really does return the integer 1. Exempting
  annotated functions left them printing `1 4612811918334230528` — the tag said
  float, the value was an i64. The `"mixed"` override therefore runs *after*
  the annotation override in `_duf_determine_ret_tag`, not before it. Note this
  is a deliberate ruling that a return annotation is **not** coercive for this
  purpose; CPython's own behaviour is the tie-breaker.

Regression test: `tests/regressions/mixed_scalar_return_tag.py`. Verified wrong
at `cfc34df`.

**Two adjacent bugs surfaced while testing this** — both verified pre-existing
at `cfc34df`, both since fixed together (they had to be: the first is
unobservable without the second):
~~BUG-IFEXP-INT-FLOAT-PROMOTE~~ and ~~BUG-VAR-RETYPED-MIDSCOPE-STALE-SLOT~~,
below.

### ~~BUG-IFEXP-INT-FLOAT-PROMOTE. `1 if c else 2.5` evaluates to `1.0`, not `1`~~ — FIXED 2026-07-27

**What:** a conditional expression whose arms were an int and a float unified to
`double` and the int arm was `sitofp`'d, so the int-ness was lost. CPython
evaluates each arm independently and returns whichever one ran, unconverted.

**Reproduce** — should print `1` twice:
```python
c = True
print(1 if c else 2.5)     # printed 1.0
x = 1 if c else 2.5
print(x)                   # printed 1.0
```
No function is involved, so this was independent of
BUG-MIXED-SCALAR-RETURN-TAG — but it is why
`tests/regressions/mixed_scalar_return_tag.py` writes its mixed returns as
`if`/`return` statements rather than one-liners.

**Where:** `_emit_ifexp`, which builds a phi and must give both incoming values
one LLVM type. It carried an explicit exemption:

```python
# int/float can be promoted to double without fpy_val
if not ({_body_k, _else_k} <= {VKind.INT, VKind.FLOAT}):
    needs_fv_output = True
```

The premise is true and the conclusion does not follow. A `double` really does
hold both, which is why this never produced a bit-reinterpretation — but the
value is *whichever arm ran*, and promoting erases that.

**Fix:** three parts.

* The exemption is gone: arms of disagreeing kinds get an `fpy_val` phi like
  every other disagreeing pair.
* `_returns_mix_int_and_float` no longer reads return kinds one expression at a
  time. `return 1 if c else 2.5` is one return with two kinds, and
  `v = 1 if c else 2.5; return v` moves the disagreement into a local, so the
  old `_literal_scalar_kind` was replaced by `_scalar_kinds_of` /
  `_scalar_kinds_binop` over expressions plus `_local_scalar_kinds`, a small
  monotone fixpoint over the function's plain assignments. A fixpoint rather
  than one pass because an accumulator needs its own kinds on the right-hand
  side: `t = 0` then `t = t + (1 if c else 0.5)` grows `t` from `{"int"}` to
  `{"int", "float"}` on the second round. Anything unclassifiable stays `None`,
  "no constraint" — never a conflict.
* `_ifexp_branch_kind` gained a third answer. It used to fold "this arm is a
  runtime-tagged value" into `None`, "unknown" — and `None` on *both* sides
  reads as "they might yet agree", so the tagged phi was skipped and two
  `FpyValue`s were merged as naked i64:

  ```python
  (1 if x else 2.5) if y else (3 if x else 4.5)   # printed 1 4612811918334230528
  ```

  It now returns `VKind.MIXED` for a nested ternary that will itself be wrapped,
  and for a name of MIXED/FVALUE kind, mirroring exactly what `_emit_ifexp`
  decides for the same sub-branches. `VKind.UNKNOWN` still maps to `None` —
  that one really is an absence of information.

Regression test: `tests/regressions/ifexp_int_float_promote.py`.

### ~~BUG-VAR-RETYPED-MIDSCOPE-STALE-SLOT. Re-typing a module-level variable allocates a second slot; reads keep using the first~~ — FIXED 2026-07-27

**What:** when a variable's static type changed across assignments in the same
scope, codegen allocated a *new* alloca and rebound `self.variables[name]` to
it. Statements already emitted still read the old slot — and so did the same
statement on the next iteration of a loop, because the loop's back-edge re-runs
code emitted before the rebind.

**Reproduce** — should print `2.0 / 2.25 / 4.25 / 4.5`:
```python
def m(i):
    if i % 2 == 0:
        return 2
    return 0.25

t = 0.0
i = 0
while i < 4:
    t = t + m(i)
    print(t)
    i = i + 1
```
printed `2.0 / 0.25 / 2.0 / 0.25` — i.e. `t` read as 0 every iteration. The IR
showed it plainly:

```llvm
  %"t.2" = alloca {i32, i64}        ; the FpyValue slot the loop body stores to
  %"t"   = alloca double            ; the slot `t = 0.0` wrote and the loop reads
  ...
  %"t.1" = load double, double* %"t"      ; always 0.0
  ...
  store {i32, i64} %".18", {i32, i64}* %"t.2"
```

Unrolling the loop worked (each read follows its own store in emission order);
so did moving the whole thing inside a `def`. Pre-existing at `cfc34df`, where
the same program printed a different wrong answer (`2.0 / 4.598e+18 / …`) for
the same reason.

**Fix:** the machinery to prevent this already existed and was simply not
reaching module scope. `_scan_fv_forced_locals` decides up front which names
must get an `fpy_val` slot from their *first* store — its own docstring
describes this exact failure — but it was run only over function bodies. Pass 3
now runs it over the module's top-level statements too, excluding names backed
by a real LLVM global (their storage is not an alloca and cannot be widened).
Its inner `yields_mixed` also did not know that a ternary with disagreeing arms
yields a mixed value, so the function-scope case was broken too once
BUG-IFEXP-INT-FLOAT-PROMOTE was fixed; it does now.

There is still no assertion that a name never gets a second alloca. Adding one
would be the durable guard — see BUG-SECOND-ALLOCA-NOT-DIAGNOSED below.

**Blast radius (before the fix):** any module-level accumulator fed by a value
whose static kind differs from its initialiser. Made easier to hit by the
BUG-MIXED-SCALAR-RETURN-TAG fix, which gives more functions a `"mixed"` return,
but not caused by it.

### ~~BUG-ABS-OF-TAGGED-VALUE. `abs()` of a runtime-tagged value returns 0~~ — FIXED 2026-07-27

**What:** `_emit_builtin_abs` handled exactly two LLVM types — `ir.IntType` and
`ir.DoubleType`. Anything else matched neither, fell off the end of the `if`,
and returned `self._bridge_fallback_expr(node, "abs() with wrong args")`, which
in native/pure mode yields 0. Three separate kinds of argument did:

* an `fpy_val` `{i32, i64}` — a heterogeneous list element, or a call to a
  function whose returns disagree;
* a **BigInt**, which is a pointer;
* a **Decimal**, likewise — and `decimal_abs` had been declared in codegen's
  runtime table all along without a single caller, which is a fair summary of
  the bug.

**Reproduced** — should print `1 2.5`:
```python
v = [1, -2.5]
print(abs(v[0]), abs(v[1]))        # printed 0 0
b = 2 ** 80
print(abs(b))                       # printed 0
from decimal import Decimal
print(abs(Decimal("-2.5")))         # printed 0
```
Nothing here was new: a heterogeneous list element has been a tagged value all
along. The silent `_bridge_fallback_expr` is why it survived — a `CodeGenError`
would have surfaced it immediately.

**Fix,** in three parts:

1. **`fastpy_abs_fv(int32_t tag, int64_t data, int32_t *out_tag,
   int64_t *out_data)`** in `runtime/objects.c` (declared `extern` and
   `SYM()`-registered in `runtime/runtime.c`), switching on the tag. It lives in
   the runtime rather than being open-coded as IR because *six* tags are numeric
   rather than two — INT, BOOL, FLOAT, BIGINT, DECIMAL and COMPLEX. An
   i64/double select in codegen would have left the other three silently wrong
   instead of visibly wrong. Two details it has to get right: `abs(-2**63)` does
   not fit an i64, so the INT case widens to a BigInt rather than wrapping (and
   negating in place to detect it would itself be UB); and `abs(a+bj)` is a real
   magnitude, so COMPLEX returns FLOAT. A non-numeric tag raises `TypeError`
   with CPython's own wording rather than returning a quiet zero.
2. **`_emit_builtin_abs`** gained an `fpy_val` branch calling it, plus a
   bigint/Decimal dispatch loop (`fpy_bigint_abs` / `fpy_decimal_abs`) ahead of
   the scalar branches. The pointer results are returned *tagged*, following
   `bigint_neg`'s convention.
3. **`_scan_fv_forced_locals`** learned `_KIND_FORWARDING_BUILTINS =
   {abs, min, max, sum, round}`: a builtin whose result kind is its argument's
   kind is mixed exactly when the argument is. Without this,
   `t = t + abs(f(i % 2))` in a loop gave the accumulator a narrow slot on its
   first store and then a second, stale one — the same shape as
   BUG-VAR-RETYPED-MIDSCOPE-STALE-SLOT.

**Test:** `tests/regressions/abs_of_tagged_value.py`, also clean under
ASan/UBSan/LSan.

**Not fixed, and split out:** the dict shape below is a *different* failure —
the value is loaded with a static kind guessed from the first store, and is
wrong with no `abs()` in sight. See BUG-DICT-VALUE-STATIC-KIND.

**Still worth auditing:** `_emit_builtin_abs` is unlikely to be the only builtin
whose type dispatch predates `FpyValue`; `divmod`, `pow` and `round` are in the
same block and take the same naked-scalar shape.

### ~~BUG-MODULE-DOCSTRING-UNBOXES-GLOBAL. `_load_variable` unboxes an FpyValue local using its (wrong) static tag, so a mixed-kind module-level value loses its runtime tag~~ — FIXED 2026-07-26

**What:** a module-level variable holding a value whose kind is only known at
runtime is loaded as a bare `i8*` typed LIST, so `len()` takes the static
`fastpy_list_length` path on what is actually a string.

**Reproduce** — prints `abcd 0` instead of `abcd 4`:
```python
"""Hello."""

def pick(flag):
    if flag:
        return "abcd"
    return [1, 2, 3]

r = pick(True)
print(r, len(r))
```
Delete the docstring line and it prints `abcd 4`. Any docstring triggers it,
including a one-word one; inserting blank lines, comments or `x = 1` in its
place does not, so it is not a line-number effect.

**Why the docstring matters — it is only the trigger, not the cause.**
`_gen_detect_bare_abi` (~4015) disables bare-ABI for module-level code when any
module-level statement contains a string constant:

```python
or (isinstance(n, ast.Constant) and isinstance(n.value, str))   # ~4032
```

A module docstring *is* a module-level `ast.Expr(Constant(str))`, so its
presence alone flips `_current_fn_bare_abi` from True to False. The two paths
then diverge in `_load_variable`:

- **bare-ABI (no docstring)** — `return self.builder.load(alloca)` (~22472).
  The bare-ABI store path stored the callee's whole `{i32, i64}` struct, so the
  alloca *is* `fpy_val` and the raw load hands back a fully tagged FpyValue.
  `len()` then dispatches on the tag. **Correct, but by accident.**
- **FV locals (docstring)** — `return self._unwrap_fv_for_tag(fv, type_tag)`
  (~22494). `type_tag` is `ValueType(list:int)`, `kind.is_ptr` is true, so it
  returns `self._fv_as_ptr(fv)` (~22598) and **throws the runtime tag away**.
  Everything downstream sees a LIST.

`self.variables['r']` is `ValueType(list:int)` in *both* builds — the recorded
type is identical, so the divergence is purely in the load.

**Where the `list:int` comes from — measured, not guessed.** Monkey-patching
`_store_variable`/`_load_variable` in a throwaway process gives:

```
[DOC]   STORE r tag=ValueType(list:int) llvm={i32, i64} bare_abi=False
[DOC]   LOAD  r -> llvm=i8*        vars=ValueType(list:int) bare_abi=False
[NODOC] STORE r tag=ValueType(list:int) llvm={i32, i64} bare_abi=True
[NODOC] LOAD  r -> llvm={i32, i64} vars=ValueType(list:int) bare_abi=True
```

Identical stores, divergent loads — so the store tag is wrong in *both* builds
and only the bare-ABI load accidentally survives it. The tag is chosen in
`_assign_fv_fast_path` (~17170–17176), which prefers the CSA pass's
`_func_ret_types` over `info.ret_tag`. For `pick` the two disagree and *both*
are wrong:

```
_func_ret_types: {'pick': 'list'}      # CSA — wins
user_fn ret_tag: 'str'                 # _duf_determine_ret_tag — ignored
```

The CSA loop (~6800–6966) walks every `ast.Return` in the function and
**overwrites** `_func_ret_types[fname]` each time, so it is last-classifiable-
return-wins. `return "abcd"` matches no branch in the chain (there is no
str-Constant arm), so `return [1, 2, 3]` writes `"list"` unopposed.

**Proper fix — producer only; the consumer is already correct.**
`_unwrap_fv_for_tag` *already* returns the FpyValue unchanged for `VKind.MIXED`
(:22620, `if kind in (VKind.FVALUE, VKind.MIXED): return fv`), and
`VKind.MIXED.is_ptr` is False so it never reaches the `_fv_as_ptr` branch. So
nothing downstream needs touching: it is enough to make the CSA pass *say*
`"mixed"`.

Add a post-pass after the per-return loop that classifies each return
independently and records `"mixed"` when they disagree:

```python
_kinds = {coarse_ptr_kind(n.value) for n in ast.walk(fnode)
          if isinstance(n, ast.Return) and n.value is not None}
_kinds.discard(None)
if len(_kinds) > 1:
    _func_ret_types[fname] = "mixed"
```

Deliberately scope `coarse_ptr_kind` to **pointer** kinds only (STR, BYTES,
LIST, TUPLE, DICT, SET) and return None for everything else, including `None`
returns, scalars, and any expression it cannot classify. Rationale: `return
None` alongside `return [...]` is extremely common and already tolerated
everywhere, and INT/FLOAT returns are decided by a separate scalar mechanism
(i64 vs double LLVM return types) that `"mixed"` would disrupt. Restricting to
disagreeing pointer kinds fixes the actual breakage with minimal blast radius.
An unclassifiable return must count as *no* constraint, never as disagreement —
otherwise every `return helper()` would go MIXED.

**Fixed as described**, via `_csa_literal_ptr_kind` / `_csa_returns_disagree`
and a post-pass at the end of `_csa_propagate_ret_types`'s per-function loop.
No consumer change was needed. Regression test:
`tests/regressions/mixed_return_tag.py`, which covers every pointer-kind
pairing at both module and function scope, both exclusions, uniform-kind
functions, rebinding one slot across kinds, and a 30-iteration loop.

Two adjacent bugs surfaced while testing this and are **not** covered by the
fix — both verified pre-existing at the parent commit: `len(f(x))` without an
intermediate variable (BUG-DIRECT-CALL-LEN-STATIC-TAG) and mixed int/float
returns (BUG-MIXED-SCALAR-RETURN-TAG, since fixed by the scalar counterpart
`_returns_mix_int_and_float`).

Note the `"ptr"` tag is separately overloaded — it means both "definitely
list/tuple" (annotations at ~10408/~10414) and "a pointer, kind unknown"
(the `_duf_determine_ret_tag` fallback at ~10337), and `ValueType.from_old_tag`
maps both to `VKind.LIST` (:346, :364). That overload wants splitting for the
same reason, but it is not what mis-types `r` here.

**Severity:** wrong answers, not memory-unsafe — `fastpy_list_length` reads the
`FpyList` length field of a string, which is in-bounds for the allocation. Every
regression test has a docstring, so in the test suite the broken path is the
*normal* one; user code without a docstring silently gets the working one.

**Not a regression:** reproduces identically at the parent commit.

**Where it bites:** `tests/regressions/native_slot_const_rc_tag.py` had to move
its `len()` coverage inside functions for this reason; the module-level cases
there only `print()` the value.

### ~~BUG-NATIVE-SLOT-CONST-RC-TAG. A slot holding an FpyValue is refcounted with a compile-time constant tag, so a mixed-kind assignment segfaults~~ — FIXED 2026-07-26

**What:** `_retain_native_store` makes a bare (non-FpyValue) alloca own what it
holds, and it retained/released with a tag derived from the variable's **static**
kind:

```python
self.builder.call(self.runtime["rc_incref"],
                  [ir.Constant(i32, fpy_tag), self._ptr_as_i64(value)])
```

That is right for a genuine native slot — one native pointer whose kind the
compiler knows. But the bare-ABI store path also takes whole `{i32, i64}`
FpyValues, and there the static kind is a guess. A function returning a str on
one branch and a list on another is typed `list`, so:

```python
def pick(flag):
    if flag:
        return "abcd"
    return [1, 2, 3]

r = pick(True)          # fpy_rc_incref(FPY_TAG_LIST, <str pointer>)
```

retained a string through the `FpyList` header offset and wrote past the end of
the allocation — an outright segfault at module scope, before anything printed:

```
AddressSanitizer: SEGV ... caused by a WRITE memory access
    #0 fpy_rc_incref runtime/objects.c
```

**The store itself was never wrong.** The emitted IR stored the correct struct,
and `print(r)` rendered `abcd` through `fastpy_fv_write` on the same variable in
the same statement; only the *refcount* ops flanking the store used a constant:

```llvm
%".4" = call {i32, i64} @"fastpy.user.pick"(...)   ; correct runtime tag
call void @"fpy_rc_incref"(i32 5, i64 %".5")       ; 5 == FPY_TAG_LIST
store {i32, i64} %".4", {i32, i64}* %"r"           ; correct tag stored
```

**Fix:** not a better static guess — no static tag can be right here, since the
kind depends on the branch taken. The slot is tagged at runtime already, so
retain and release now read that tag. A `_RC_TAG_DYNAMIC = -2` sentinel in the
native-slot registry marks "this slot holds a whole FpyValue"; the retain in
`_retain_native_store` and the release in `_release_native_slot` then
`extract_value` the tag and data out of the struct instead of emitting an
`ir.Constant`. The `_is_fv` test has to run *before* the `fpy_tag is None`
early-out, because a static scalar kind says nothing about what the struct
actually holds. The FpyValue-locals store path had always done this; the
bare-ABI path was the hole.

**Not the `len()` dispatch.** `_emit_builtin_len` already falls back to
`fastpy_fv_len`, which switches on the tag; the first diagnosis blamed the
`"ptr"` → `VKind.LIST` mapping in `ValueType.from_old_tag` and was wrong.
Re-probing showed both `len()` calls already used `fv_len`, and ASan pinned the
fault in the *assignment*. (`"ptr"` is still overloaded — it means both
"definitely list/tuple", from `list[int]`/`tuple[...]` annotations at ~10408 and
~10414, and "pointer of unknown kind", from the `_infer_ret_tag` fallback at
~10337 — but that overload was not what crashed this program.)

**Regression test:** `tests/regressions/native_slot_const_rc_tag.py` — mixed
str/list/dict/int returns through one slot at module scope, in a function,
rebound across kinds, aliased, and in loops of 30–40 iterations where a wrong
tag corrupts or leaks every iteration. Fails at the parent commit.

### ~~BUG-BARE-ABI-STORE-NO-RETAIN. Assigning an owned str temp to a local inside a bare-ABI function is a use-after-free~~ — FIXED 2026-07-26

**What:** inside a function compiled with the bare-type ABI, storing a
Model-2 **owned** temp into a local emits no incref, but the statement-boundary
flush still emits the release — so the variable is left pointing at freed
memory. Every later read is garbage.

**Reproduce** (prints a garbage line instead of `7`):
```python
def f():
    s = str(7)
    print(s)

f()
```
The emitted IR shows the problem directly:
```llvm
%".6" = call i8* @"fastpy_fv_str"(i32 %".4", i64 %".5")  ; owned +1 temp
%".7" = ptrtoint i8* %".6" to i64
store i8* %".6", i8** %"s"                               ; stored, NO incref
call void @"fpy_rc_decref"(i32 2, i64 %".7")             ; boundary flush frees it
%"s.1" = load i8*, i8** %"s"                             ; dangling
```
Any producer registered as an owned temp triggers it — `str()`/`repr()`/`hex()`/
`oct()`/`bin()`/`chr()` on a static scalar, and scalar f-string interpolants
(the Stage 3.1 producers). `s = "a" + str(n)` does **not**, because the concat
path already retains. Module scope is unaffected: module-level names take the
early-return global path in `_store_variable`, which emits neither incref nor
decref.

**Where:** `compiler/codegen.py`, `_store_variable`. Two of its branches do a
plain `builder.store` and return with no refcount traffic at all:
- the bare-ABI/legacy branch,
  `if not self._USE_FV_LOCALS or self._current_fn_bare_abi:` (~21444);
- the `_native_vars` annotated/typed fast path (~21393), checked *before* it.

Contrast the FV path (~21603), which does the right thing: decref the slot's old
value, then incref the new one unless `steal=True`.

**What the symptom tracks:** the failure follows `_current_fn_bare_abi`, not the
annotation. Measured:

| case | result |
|---|---|
| `def f(): s = str(7); print(s)` (bare-ABI) | **fail** |
| `def f(): s: str = str(7); print(s)` (bare-ABI, `_native_vars`) | **fail** |
| same, plus a `try/except` so the function is no longer bare-ABI | pass |
| `s = str(7); print(s)` at module scope | pass |

so both no-retain branches are reachable only from bare-ABI functions in
practice; a non-bare-ABI function routes to the FV path, which retains.

**Proper fix** — three parts, all gated on the slot's static VKind being a heap
kind so the typed fast path stays refcount-traffic-free for scalars:

1. **Null-initialize heap-kind native allocas** in the entry block, mirroring
   `_entry_store_fv_none` (~21289), which exists for exactly this reason on the
   FV side. Without it the *first* store's decref reads an uninitialized slot.
   `_create_entry_alloca` (~21275) deliberately does not initialize, so this
   needs a sibling `_entry_store_null` plus a set tracking which slots got it.
2. **Retain/release on store** in both no-retain branches: decref the slot's old
   contents (tag = the slot's static `fpy_tag`, data = `ptrtoint(load(alloca))`),
   then incref the incoming value unless `steal=True` — i.e. the same discipline
   the FV path already applies at ~21603.
3. **Release at function exit.** `_emit_scope_decref` (~25951) explicitly
   `continue`s on anything whose alloca isn't `fpy_val` (~25970), so native slots
   are never released. It must also walk heap-kind native slots, keeping the
   existing exclusions (parameters are borrowed; the returned variable transfers
   ownership).

Doing (2) without (3) converts the UAF into a leak on every reassignment — still
an improvement, per the documented asymmetry (owned-treated-as-borrowed leaks,
borrowed-treated-as-owned is a UAF), so the retain is the safe half to land
first if they must be split. Verify with `tools/pure_harness.py` (ASan + LSan
catches both halves) before and after.

**Note:** the existing "Verified (native ASan, pure mode): dropped/var/attr/
dict/typed-list stores of `str/repr/hex/oct/bin/chr` … no UAF/double-free" claim
under BUG-CODEGEN-OWNED-TEMP-OVER-INCREF Stage 3.1 is **too strong** — those
checks were written at module scope, which takes the global path and so never
exercised this branch.

**Fixed 2026-07-26** exactly as the three-part plan above describes, with
ownership tracked compiler-side because a bare alloca carries no runtime tag:

- `self._rc_native_slots: dict[ir.Function, dict[str, tuple[alloca, fpy_tag]]]`
  records, per function, the tag each native slot was last *retained* with — a
  slot can be rebound across static kinds (`x = str(5)` then `x = 12`), so the
  release must use the tag from the retain, not the tag being stored now. Keyed
  by `ir.Function` so the several places that swap `self.variables` in and out
  don't have to know about it.
- `_retain_native_store` increfs the incoming value **before** decref'ing the
  old contents, so `s = s` (and `s = f(s)`, `s = s[1:]`) can't drop the last
  reference before taking the new one. *(The FV path had the reverse order and
  was a latent self-assignment UAF; it was brought into line the same day — see
  BUG-FV-STORE-DECREF-BEFORE-INCREF.)*
- `_entry_store_null` zeroes a native alloca in the entry block (after all
  allocas, `ir.Constant` only so dominance holds), so a slot assigned on only
  one branch releases NULL rather than stack garbage — `fpy_rc_decref`'s
  `if (data == 0) return;` makes that a no-op.
- Rebinding a name to a *different* alloca (the bare-ABI path re-allocas on an
  LLVM type change) releases the old alloca, which is otherwise unreachable.
- `_emit_scope_decref` gained a second walk over the registry, keeping the
  existing exclusions (params borrowed, returned var transfers ownership,
  globals outlive the frame) and skipping stale entries whose name has since
  been rebound.

`_NATIVE_HEAP_TAGS` gates all of this on the slot's static VKind being a
refcounted heap kind (STR/BYTES/LIST/TUPLE/DICT/SET/OBJ), so scalar slots stay
refcount-traffic-free. PYOBJ is deliberately excluded — those are CPython-bridge
pointers the bridge owns, not `fpy_rc_*`.

Regression test: `tests/regressions/rc_native_slot_retain.py` (ASan/UBSan/LSan
clean under `tools/pure_harness.py`; the same file aborts ASan at the parent
commit).

### BUG-DECORATOR-WRAPPER-STATIC-RET-TAG. A decorator `wrapper` reused for several callees publishes one statically-inferred return tag for all of them — 2026-07-26

**What:** a decorator's inner `wrapper(*args)` is a single `fastpy.closure.*`
body, emitted once and shared by every function that decorator is applied to.
Its `return result` goes through `_emit_return`'s `_needs_ret_tag` path, which
falls back to `_infer_ret_tag_for_value` when `result` is not an FpyValue local.
That inference sees one merged set of call-site types, so the wrapper publishes
a *single* tag — wrong for whichever decorated callee returns a different kind:

```python
def deco(fn):
    def wrapper(*args):
        return fn(*args)          # one body, one static ret tag
    return wrapper

@deco
def as_int(n):  return n * 2
@deco
def as_str(n):  return "v" + str(n)
```

**Currently latent, not observable.** Call sites for decorated names do not read
`get_ret_tag()` — they use the *static* `ret_tag` of the undecorated function,
which happens to be right. It becomes live the moment any call site trusts the
side channel for a decorated name; that is exactly what happened when the
BUG-INDIRECT-CALL-RET-TAG-INT recovery was first written without the decorated-
name exclusion, and it broke `tests/regressions/decorator_star_args.py` (case 5,
chained decorators over a str-returning `get_greeting`, printed a pointer).

**Where:** `_emit_return` in `compiler/codegen.py`, the `_needs_ret_tag` blocks
(~25790 and ~25890); the exclusion that keeps it latent is in
`_recover_closure_ret_tag`.

**Proper fix:** make the forwarded value dynamic rather than statically tagged —
`return fn(*args)` inside a closure should forward the inner callee's
`get_ret_tag()` (the machinery exists: `_emit_return` already does exactly this
for `return <closure_var>(...)`, but only when the callee name is a
`VKind.CLOSURE` *variable*, which a `*args`-forwarding parameter is not). Once
the wrapper forwards the runtime tag, the decorated-name exclusion in
`_recover_closure_ret_tag` can be dropped and decorated calls get the same
runtime-tag treatment as everything else.

**Regression coverage:** `shared_decorator_wrapper()` in
`tests/regressions/indirect_call_ret_tag.py` pins the boundary — it passes today
via the static path and would fail if the exclusion were removed before the
wrapper is taught to forward.

### ~~BUG-NESTED-DEF-NAME-COLLISION. Two sibling nested `def`s that share a name silently resolve to one another~~ — FIXED 2026-07-26

**What:** a nested `def` with no free variables is *hoisted* to module scope and
registered in `self._user_functions` under its **bare** name. Two different
enclosing functions each containing a `def build(...)` therefore collide: the
second registration hits the `if key_name in self._user_functions: return`
early-out in `_declare_user_function`, and the second `build` is silently typed
from the first one's `FuncInfo`.

**Reproduce** (should print `[10, 11, 12] 3 10 12` / `xv 1`):
```python
def list_return():
    def build(n):
        return [n, n + 1, n + 2]
    a = build(10)
    print(a, len(a), a[0], a[2])

def dict_return():
    def build(k):
        return {k: str(k) + "v"}
    d = build("x")
    print(d["x"], len(d))

list_return()
dict_return()
```
prints
```
[10, 11, 12] 3 10 12
0 2064512507584
IndexError: list index out of range
```
`d` is typed LIST from `list_return`'s `build`, so `d["x"]` compiles to a list
index. Renaming either helper makes it pass.

**Not a total absence of handling.** `_scan_for_closures` (~4614) *does* check
for the collision — `_name_collides` forces the second def down the
zero-capture-closure path so it gets a qualified name — and that half works: a
probe shows `dict_return.build` registered as a closure alongside the hoisted
bare `build`. So the call *dispatches* correctly; what came from the sibling was
the result *type*.

**Root cause — deeper than `_user_functions`.** The first attempt was a
scope-first `_lookup_user_function(name)` helper (try `f"{_current_func_name}.{name}"`,
fall back to the bare name) wired into `_recover_closure_ret_tag` and the
call-site type inferrer. It made the closure and the caller individually
correct, and the repro *still* failed: `d["x"]` compiled to `fastpy_list_get_fv`.
Tracing bare-name lookups with a logging `dict` subclass found the real source —
`_csa_func_asts` is built with a flat

```python
func_asts.setdefault(node.name, node)     # over ast.walk(tree)
```

so the **first** `def build` in the module wins for every consumer of that map
(`_func_ret_types`, `_call_site_param_types`, `_monomorphized`, string-param
detection, …). Every one of those maps is keyed by a function's bare name.

**Fix:** `_uniquify_nested_def_names(tree)` (compiler/codegen.py ~4076), an
alpha-renaming pass run as the very first statement of `generate()`, before
`_gen_prescan` and therefore before any analysis map is built. A nested `def`
whose bare name is used by another `def` anywhere in the module is renamed to
`name__nK`, and references are rewritten throughout the owner scope. Re-keying
every map by scope was rejected: it would have meant auditing dozens of lookup
sites and would have left the flat ones as latent traps for the next bug.

The pass is deliberately conservative and bails out — leaving the name alone —
when renaming would be unsafe: a `global`/`nonlocal` names it, the owner scope
rebinds it (another def, an assignment, a parameter, an import), or the def is
module-level or a class method. `_rewrite` also stops descending into a nested
scope that shadows the name with a parameter of its own. The scope-first
`_lookup_user_function` was kept as well — it is the right thing independently,
and it covers the cases the renaming pass declines.

**Not a regression:** reproduced identically at the parent commit.

**Regression coverage:** `tests/regressions/nested_def_name_collision.py` — the
original list/dict repro plus str/int siblings, a nested def shadowing a
module-level one, recursion inside a renamed def, capturing closures, collisions
two levels deep, the name as a parameter elsewhere, a class method of the same
name, an owner-scope rebinding (the bail-out), and a loop body. Fails at the
parent commit; ASan/UBSan/LSan clean.

### BUG-SAME-SCOPE-DEF-REBIND. Two `def`s with the same name in one scope both resolve to the first — 2026-07-26

**What:** Python rebinds a name on each `def`, so a later `def f` shadows an
earlier one for uses that follow it. The compiler keeps only the first.

**Reproduce** (should print `8 12`, prints `8 8`):
```python
def collide_in_branch(flag):
    if flag:
        def step(n):
            return n * 2
        return step(4)
    def step(n):
        return n * 3
    return step(4)

print(collide_in_branch(True), collide_in_branch(False))
```

**Why the alpha-renaming pass does not cover it.** `_uniquify_nested_def_names`
renames a def and then rewrites *every* reference in the owner scope, which is
only sound when exactly one def binds the name in that scope. Here both do, so
`_rebound_elsewhere` returns true and the pass declines. Resolving a use to the
right def needs flow analysis, not a scope-wide rewrite.

**Proper fix:** replace the scope-wide `_rewrite` with a structured
environment walk over the owner scope's statements — carry a
`name -> current binding` map, rename each `def` to a fresh name as it is
encountered, rewrite `Name` loads to whatever the map holds, and recurse into
compound statements with a copy of the map (marking a name ambiguous when
`if`/`else` arms disagree, when a loop body rebinds it, or when a non-`def`
binding intervenes). Ambiguous names fall back to today's behaviour. This
subsumes the current conservative bail-outs.

**Not a regression:** reproduces identically at the parent commit, and before
the alpha-renaming pass existed. Called out in the docstring of
`tests/regressions/nested_def_name_collision.py`, whose `collide_in_branch`
case is written to stay inside the cross-scope collision this pass does fix.

### ~~BUG-EXC-MSG-NOT-OWNED. A raised exception borrows its message string, so every dynamic message must leak~~ — FIXED 2026-07-27

**What:** `fastpy_raise` (runtime/runtime.c:818) stores the message pointer
rather than copying it:

```c
void fastpy_raise(int exc_type, const char *msg) {
    fpy_exc_type = exc_type;
    fpy_exc_msg  = msg;          /* borrowed — no copy, no incref */
```

The handler reads it back much later via `fastpy_exc_get_msg()`. So a
*heap-allocated* message — an f-string, a concatenation, `str(x)` — must stay
alive across the entire raise/unwind/handle path, but nothing owns it. Codegen's
only safe option is to **drop the owned temp without releasing it**, i.e. leak
it. `_emit_assert` does exactly that (see the note under
BUG-DECREF-DOES-NOT-DOMINATE), and `_emit_raise` is in the same position.

**Impact:** a bounded leak per raised exception with a computed message. Not a
correctness bug and not observable in output, but it does mean a program that
raises in a hot loop with an f-string message grows without bound:

```python
for i in range(1_000_000):
    try:
        raise ValueError(f"bad {i}")   # each message string is leaked
    except ValueError:
        pass
```

**Proper fix:** make the exception state *own* its message, released in
`fastpy_exc_clear()` and whenever a new raise overwrites the slot. The obvious
one-liner — `fpy_str_incref(msg)` inside `fastpy_raise` — is **wrong**, and the
reason is worth writing down because it is easy to miss:

`fpy_str_incref` finds the refcount by reading the 8 bytes *before* the char
pointer (`fpy_str_header`). That is safe for anything the project treats as a
STR value, because those are all header-backed: heap strings come from
`fpy_str_copy`/`fpy_str_buf` (BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC is the rule
that enforces this), and codegen emits string *constants* as
`{i32 FPY_STR_MAGIC, i32 FPY_RC_IMMORTAL, [N x i8]}` globals so incref/decref
no-op on them. But `fastpy_raise` is also called from the runtime's own C code
with **plain C literals** (`fpy_pure_unsupported()`, the arithmetic/index/key
errors, …), which have no such header — so a blanket incref would read out of
bounds on a `.rodata` literal and ASan would flag a global-buffer-overflow.

Three shapes that do work, in rough order of preference:

1. **Split the entry point.** Keep `fastpy_raise` borrowing (for the runtime's
   own literal messages) and add `fastpy_raise_owned(exc_type, msg)` that takes
   ownership of a header-backed string, with a companion `fpy_exc_msg_owned`
   flag so `fastpy_exc_clear` frees only what it owns. Codegen emits
   `raise_owned` for computed messages, increfing first so a *borrowed* message
   (`assert False, msg` where `msg` is a live variable) is retained rather than
   stolen. No cost on the internal raise path.
2. **Copy unconditionally** — `fpy_exc_msg = fpy_str_from_cstr(msg)`. Simplest
   and uniformly correct (no header read on the incoming pointer at all), but
   adds a malloc+copy to *every* raise, including the `StopIteration` that ends
   every iterator loop.
3. Codegen-side ownership, keeping the message alive across the unwind. Most
   fragile; mentioned only for completeness.

Whichever is chosen, it also removes the special-case temp-dropping in
`_emit_assert`.

**Discovered** while fixing BUG-DECREF-DOES-NOT-DOMINATE facet (c) — the
try-body flush made the previously invisible leak visible as an invalid-IR
failure in `assert_fstring_msg.py`.

**Fixed:** option 2, in two steps. The runtime side landed first —
`fastpy_raise` copies through `fpy_exc_msg_store` into storage the exception
slot owns (originally for the header probe, then made refcounted by
BUG-EXC-MSG-BUFFER-ALIASES-ACROSS-RAISES) — which is what makes releasing the
caller's temp legal at all. The codegen side is the release itself, and the
reason it was not simply "delete the special case" is that both raise sites
evaluate their message in a block that *always* terminates:

- `_emit_raise` (BUG-RAISE-MESSAGE-TEMP-LEAKS): the statement-boundary flush
  is emitted in the no-exception continuation block, which a raise never
  reaches. It now takes an `_rc_mark` before the message and flushes right
  after the raise call, while the block is still open.
- `_emit_assert`: same shape, and the one the original note called out. The
  arm's flush ran *after* the `ret`/branch to the handler, where
  `_flush_rc_temps_to` can only pop temps without emitting decrefs. Moved
  above the terminator; a second flush stays below it as a guard for anything
  a future edit adds there (it pops nothing today).

Measured on 500k iterations: `raise ValueError("m" * 350)` went 189 → 12.95 MB,
`assert i < 0, "m" * 350` went 186 → 14.25 MB. Covered by
`tests/regressions/assert_msg_survives_later_asserts.py`, whose cases hold a
message across later failing asserts and across a handler's clear — the
property that proves the copy is independent of the released temp.

**Severity:** was medium — unbounded growth in any loop that raises or asserts
with a computed message, invisible to output-diffing tests.

### ~~BUG-INDIRECT-CALL-RET-TAG-INT. A nested `def`'s return value is tagged INT at the call site, so a returned str prints as a pointer~~ — FIXED 2026-07-26

**What it was:** a nested function is lowered to a closure object and invoked
indirectly through `fastpy_call_ptrN`, which returns a bare `i64`. The call site
then wraps that `i64` into an `FpyValue` with a **hardcoded** tag of `0` (INT)
instead of consulting the callee's return tag. Any non-int return — `str`,
`list`, `dict` — comes back as an integer, so the value prints as a decimal
pointer.

**Reproduce** (prints e.g. `88098369175608` instead of `3?`):
```python
def outer():
    def make(n):
        s = str(n) + "?"
        return s
    r = make(3)
    print(r)

outer()
```
The emitted IR for `outer` shows the hardcoded tag:
```llvm
%".19" = call i64 @"fastpy_call_ptr1"(i8* %".17", i64 3)
%".20" = insertvalue {i32, i64} undef, i32 0, 0   ; <-- tag 0 = INT, always
%".21" = insertvalue {i32, i64} %".20", i64 %".19", 1
store {i32, i64} %".21", {i32, i64}* %"r"
```
Note `fastpy.user.make` itself correctly returns `{i32, i64}` — the real tag
exists, it is thrown away by the `__i64_wrap` thunk and never recovered.

**Scope of the symptom.** It needs *both* a nested def *and* binding the result
to a name; a direct `print(make(3))` passes because print's argument path
recovers the tag another way. A module-level `def` is unaffected (it is called
directly, not through a closure object). Measured:

| case | result |
|---|---|
| `def make(...)` top level; `r = make(3); print(r)` | pass |
| nested `def make(...)`; `print(make(3))` | pass |
| nested `def make(...)`; `r = make(3); print(r)` | **fail** |

**Where:** `compiler/codegen.py`, the indirect-call emitter that builds
`fastpy_call_ptrN` calls and wraps the `i64` result. The nested-def registration
sites also hardcode the return type: `_scan_for_closures` sets
`ret_type = i64 if has_return else void` and `ret_tag = "int"` at ~4654/4729,
with an ad-hoc `bool` special case at ~4739–4764 but nothing for `str`/`list`/
`dict`.

**Why a static tag could not fix it.** `FuncInfo.ret_tag` stays `"int"` for
FpyValue-ABI functions *by design* — their real tag travels inside the returned
`{i32, i64}` struct — and this is true of module-level defs too (verified: both
the nested and the module-level `make` carry `ret_tag == "int"`,
`uses_fv_abi == True`; the module-level case only works because a *direct* call
reads the tag out of the struct). On top of that a function may return different
kinds on different branches. The tag has to come from the runtime.

**Fixed** by `_recover_closure_ret_tag` (`compiler/codegen.py`, just above
`_emit_closure_call`), called from the `VKind.CLOSURE` arm of `_emit_call_expr`.
It reads `get_ret_tag()` back and rebuilds an `FpyValue`. Three parts:

1. **Recovery is gated on the callee actually publishing a tag.** Two lowerings
   qualify: `uses_fv_abi` functions, which go through the `__i64_wrap` thunk
   (that thunk already called `set_ret_tag` before discarding the struct — the
   tag existed, nobody read it); and `fastpy.closure.*` bodies, which return
   `i64` directly but whose `return` emitter already calls `set_ret_tag` on
   every path. The first covers zero-capture nested defs (hoisted to module
   scope), the second covers capturing closures. Decorator-returned closures and
   function-pointer parameters resolve to no `FuncInfo` and keep the plain `i64`
   path.
2. **Lambdas now publish a tag too** (`_emit_lambda_body`). They previously
   returned `i64` in silence — and silence is *not* "assume int", because call
   sites that already used `get_ret_tag()` then read whatever `fpy_ret_tag` held
   from an earlier, unrelated call. A str-returning nested def anywhere before
   the lambda call was enough to make `print(f(1))` interpret an int as a
   `char*` and **segfault**. That crash reproduced at the parent commit; it is a
   second facet of the same bug, not a regression.
3. **Callee lookup is scope-first** (`outer.inner` before `inner`), since
   zero-capture nested defs are registered under their bare name, and
   **decorated names are excluded**: for `@deco def f(...)`,
   `_user_functions["f"]` describes the *undecorated* function while the
   variable `f` holds the decorator's wrapper — a different callee. Missing
   this exclusion regressed `tests/regressions/decorator_star_args.py` (see
   BUG-DECORATOR-WRAPPER-STATIC-RET-TAG).

**Verified:** `tests/regressions/indirect_call_ret_tag.py` (17 cases: str/list/
dict/float/bool/None returns, per-branch mixed kinds, a rebound slot, a
100-iteration loop, capturing and two-deep nesting, plus lambda/decorator/
`sorted(key=)` cases proving the plain-`i64` path did not regress) fails at the
parent commit and passes now; ASan/UBSan/LSan clean; full suite green.

**Follow-up:** the docstring note in `tests/regressions/rc_native_slot_retain.py`
that explains why it uses module-level helpers is now stale.

### ~~BUG-FV-STORE-DECREF-BEFORE-INCREF. The FpyValue store path releases the old value before retaining the new one~~ — FIXED 2026-07-26

**What it was:** in `_store_variable`'s FV path, `compiler/codegen.py` decrefed
the slot's previous contents and only *then* increfed the value being stored.
When both are the same object and the slot holds the last reference, the decref
frees it and the incref resurrects freed memory:

```python
s = str(7)
s = s          # decref(old s) -> refcount 0 -> freed; then incref(freed)
```

It was latent rather than firing in the suite: the producers whose results reach
the FV path with a refcount of exactly 1 were still the minority while the
Model-2 migration was in progress. It would have become live as more producers
converted — the reason to fix it now rather than wait for it to bite.

**Fixed** by hoisting the incref block above the `if name in self.variables:`
decref blocks, so the incoming value is retained before anything is released —
matching the native-slot path (`_retain_native_store`, added for
BUG-BARE-ABI-STORE-NO-RETAIN), so the two paths now agree on ordering. The
inline OBJ fast path (`_emit_inline_obj_incref`) moved with it.

**Verified** on a methods-based test (`s = s`, `t = s`, `s = t` round-trips,
container slots, a 200-iteration rebind loop) — methods are never bare-ABI, so
they exercise the FV path. IR valid, output matches CPython, ASan/UBSan/LSan
clean. Note this could *not* be verified via a try-block test at the time: try
bodies were independently emitting invalid IR (BUG-DECREF-DOES-NOT-DOMINATE
facet (c), fixed in the same commit).

### ~~BUG-RETTAG-STR-VIA-LOCAL. `s = str(n); return s` infers an `int` return, so the caller prints the string pointer as a number~~ — FIXED 2026-07-26

**What:** `_analyze_function_signature`'s return-type inference recognised a
*direct* `return str(n)` / `return x.upper()` as producing `i8_ptr`, but the
local-variable classifier that feeds `return <name>` only ever added a name to
`str_vars` for `s = "literal"`, `s = f"..."` and `s = <str_var> + x`. So routing
the exact same expression through a local lost the tag:

```python
def make(n):
    s = str(n)
    return s

print(make(3))      # prints e.g. 2639512264584 instead of 3
```
`return str(n)` directly worked; `s = str(n) + "?"` worked (the concat rule);
only the plain builtin-through-a-local form failed.

**Root cause:** two hand-maintained lists of "expressions that produce a str",
one in the return path and one absent from the assignment path, which drifted.

**Fixed** by extracting the knowledge into a single predicate `_expr_is_str`
(literals, f-strings, the `str`/`repr`/`hex`/`bin`/`oct`/`chr` builtins, the str
methods, `+`/`*` with a str operand, and `IfExp` when *both* arms are str),
using it in the local classifier, and repointing the return path at the same
`_STR_BUILTINS` / `_STR_METHODS` frozensets so the two cannot drift apart again.

**Related but still open:** BUG-FILEREAD-FN-RETTAG below is the same family —
`data = f.read(); return data` — but needs open()-derived-receiver tracking that
`_expr_is_str` deliberately does not attempt, since it can't see which locals
are file objects.

### ~~BUG-DECREF-DOES-NOT-DOMINATE. Compiling `compiler/pipeline.py` emits invalid IR — a `fpy_rc_decref` whose operand doesn't dominate it~~ — FIXED 2026-07-26

**What it was:** the self-hosting progress test
`tests/test_comprehensive.py::test_self_compile_real_module[pipeline]` skipped
with a **verifier** failure, not a "feature not supported" message:

```
Can't compile yet: Build failed: Instruction does not dominate all uses!
  %.895 = ptrtoint ptr %.894 to i64
  call void @fpy_rc_decref(i32 2, i64 %.895)
```

**Root cause:** an owned (+1) temporary created *inside a conditional expression
arm* lives in that arm's own basic block, but the enclosing statement's Model-2
flush runs in the **merge** block — which the arm does not dominate. The
offending construct in `pipeline.py` was line 134,
`msg = str(e)[:200] if str(e) else f"{type(e).__name__} in codegen"`: the
f-string in the `else` arm allocates, and its release was emitted at the join.

Minimal repro (7 lines):
```python
def f(e):
    n = str(e)
    msg = n if n else f"{n} fallback"
    return msg
```
The same defect affected the `and`/`or` short-circuit operands, where *every*
operand block is a predecessor of the merge — so `a or f"{a}"` produced the same
invalid IR. It went unnoticed for so long because it only fires when an arm
**allocates**; the many `x if c else y` tests over ints and literals register no
temp and so stayed valid.

**Fix:** two helpers in `compiler/codegen.py` next to `_flush_rc_temps`:
- `_capture_arm_rc_temps(mark)` — pops the temps registered since `mark` while
  the builder is still positioned in the arm, so the enclosing statement's flush
  can no longer see them.
- `_rejoin_arm_rc_temps(arms)` — called at the *top* of the merge block, before
  any non-phi instruction. It rebuilds each captured temp as a pair of phis
  (tag, data) whose incoming value from every *other* predecessor is `0`;
  `fpy_rc_decref` already no-ops on `data == 0`, so exactly the arm that ran is
  released. The +1 is untouched — only the release *site* moves — so Model-2
  semantics are unchanged.

Wired into `_emit_ifexp` (both the FpyValue-output path and the same-type path)
and into `_emit_short_circuit_and` / `_emit_short_circuit_or` (one arm entry per
operand). Dominance holds because a pending temp's defining block always
dominates `self.builder.block` at capture time, and that block is the
predecessor registered in the phi.

**Regression test:** `tests/regressions/rc_temp_in_conditional_arm.py` — both
arms taken, the result consumed after the merge, 200- and 100-iteration loops
(a double-free would crash, a leak would grow), 3-operand `or`, nested
conditionals, arms as call arguments, and the mixed-type FpyValue path.
`test_self_compile_real_module[pipeline]` now **passes** rather than skipping.

**Second facet — comprehension bodies — also fixed 2026-07-26.** Reclassifying
verifier errors as failures (BUG-SKIP-MASKS-VERIFIER-ERRORS) immediately exposed
the same defect in a different shape:
`test_self_compile_ir_builder_pattern` failed on
`ops = ", ".join(str(o) for o in self.operands)`. A comprehension is lowered to a
cond/body/incr/end loop; a temp allocated in the **body** was left pending for
the statement flush that runs in the **end** block, which the body does not
dominate.

This needed a *different* fix from the conditional-arm case. The phi trick is
wrong here: the body runs N times, so there is no single merged value — releasing
at the merge would free only the last iteration's temp and leak the other N-1.
The correct fix is a **per-iteration flush** at the end of the body, before the
back-edge. It is safe because every container store retains: `fpy_list_append`
and `fastpy_dict_set_fv` both incref what they store, so the body's +1 really is
surplus once the element is in.

A filter (`if` clause) forks the body into keep/skip paths that both reach the
incr block, so a third helper `_release_rc_temps_since(mark)` emits the release
on the skip arm *without* popping the pending list — the arms are mutually
exclusive and the fork block dominates both, so each path releases exactly once.

Applied to `_emit_lc_body` (shared by the single-generator and tuple-unpack list
comprehensions), `_emit_list_comprehension_multi`,
`_emit_list_comprehension_nested` (per *outer* iteration, for the inner
iterable), both single-generator dict-comprehension loops (`dc.*` and `dcl.*`)
and `_emit_dict_comprehension_multi`.

**Regression test:** `tests/regressions/rc_temp_in_comprehension.py` — allocating
element, allocating filter, both, a generator expression fed to `str.join` (the
self-hosting shape), allocating dict comprehensions with and without a filter, a
two-generator comprehension, and a 200-iteration loop building both a list and a
dict. ASan/UBSan/LSan-clean under `tools/pure_harness.py`.

**Third facet — try/except*/with bodies — also fixed 2026-07-26.** The same
shape once more, in the one place where statements are emitted *without* going
through `_emit_stmts`. Three loops iterated `node.body` calling `_emit_stmt`
directly and never flushed:

- `_emit_try` (~25107, `try.cont`)
- `_emit_try_star` (~24364, `trystar.cont`)
- the with-statement body loop (~23349, `with.cont`)

Each statement in such a body is followed by a pending-exception check that
opens a **new** block, so a value defined in `try.cont.4` was released by the
enclosing statement flush in `try.end.2` — which does not dominate it. Two
heap-producing statements in one try body were enough:

```python
def f():
    try:
        s = str(7)
        s = str(8)
        print(s)
    except ValueError:
        print("no")
```
```
Instruction does not dominate all uses!
  %.36 = ptrtoint ptr %.35 to i64
  call void @fpy_rc_decref(i32 2, i64 %.36)
```

**Fix:** mirror `_emit_stmts` — take `_rc_mark = len(self._rc_temps)` before
`_emit_stmt` and flush after it — with one deliberate difference: the flush is
emitted **in `cont_block`**, after `position_at_end`, rather than immediately
after the statement. On the raising path a partially executed statement may
have registered a temp whose value is undefined (a runtime call that sets an
exception still *returns* something), and decref'ing that is a UAF; leaking it
is the safe direction under the owned/borrowed asymmetry. Definitions dominate
`cont_block` either way, so the IR is valid regardless of which site is used.
The `is_terminated` early-outs call the flush too, so the temps are popped from
the compiler-side list — `_flush_rc_temps_to` emits no decrefs into a
terminated block.

**Follow-on — `assert` with a dynamic message.** Adding the flush above
immediately exposed a *latent* instance of the same defect one level down, in
`tests/regressions/assert_fstring_msg.py`. `_emit_assert` splits into
`assert.pass` / `assert.fail` and builds the message expression inside the
**fail** arm, which always terminates (a `ret`, or a branch straight to the
except target). It then repositions to `assert.pass` leaving the message's
owned temps still pending — and `assert.fail` does not dominate `assert.pass`.
Before the try-body flush existed those temps quietly rode up to a flush that
never fired, so they only *leaked*; with a flush in `try.cont` they became a
hard verifier error.

`_emit_assert` now takes its own watermark before the message expression and
calls `_flush_rc_temps_to` after the arm's terminator. Because the block is
terminated by then, this **pops the temps without emitting decrefs** — which is
required, not merely convenient: `fastpy_raise` does `fpy_exc_msg = msg`, i.e.
it stores the pointer rather than copying it, and the handler reads it back
later via `fastpy_exc_get_msg()`. Releasing at the raise site would be a
use-after-free. So the message deliberately leaks, exactly as it did before.
*(Making the exception machinery own its message string is the real cure and is
tracked separately as BUG-EXC-MSG-NOT-OWNED below.)*

**Regression test:** `tests/regressions/rc_try_body_stmt_flush.py` — the
two-producer repro, six producers in one body, handler-taken, `finally`, `else`,
`return` inside try, nested try, a 50-iteration try-in-loop, with-statement
bodies both standalone and in a 20-iteration loop, and `assert` with an f-string
and a concatenated message inside a try. Fails (invalid IR) at the parent
commit, passes with the fix, ASan/UBSan/LSan-clean under
`tools/pure_harness.py`.

**Process note:** this hid behind a SKIP for as long as it did because
`test_self_compile_real_module` treats *every* compile failure as "self-hosting
isn't there yet". A verifier error is categorically different from an
unsupported-feature error and should be a hard failure — see
BUG-SKIP-MASKS-VERIFIER-ERRORS below.

### BUG-SKIP-MASKS-VERIFIER-ERRORS. Invalid-IR failures are reported as skips, not failures — 2026-07-26

**What:** the diff-test harness and `test_self_compile_real_module` both map any
build failure to "compiler can't compile this yet" (a SKIP). That is right for
an unsupported Python feature, but wrong for an **LLVM verifier** error, which
always means codegen emitted invalid IR — a real defect that will never be fixed
by adding a feature. BUG-DECREF-DOES-NOT-DOMINATE sat green in the suite this
way; the new `rc_temp_in_conditional_arm.py` regression test likewise reports
`skip`, not `fail`, when the fix is reverted.

**Proper fix:** in `tests/harness.py`, classify a build failure whose message
contains an LLVM verifier signature (`Instruction does not dominate all uses`,
`Invalid operand types`, `Broken module`, …) as a hard FAIL rather than a SKIP,
so this class of bug can never hide again.

### ~~BUG-IS-COMPARE-DOUBLE-EVAL. `a is b` evaluated its left operand twice~~ — FIXED 2026-07-26

**What it was:** `_emit_compare` emitted the left operand eagerly
(`tv_left = self._emit_expr(node.left)`) before dispatching per operator, but
`_emit_is_compare` needs the AST *node* rather than the value — the unwrapped
value has lost the FpyValue tag it must inspect — so it emitted the left operand
a second time. Any call on the left of an `is` therefore ran twice.

**Reproduced:**
```python
n = 0
def val():
    global n
    n = n + 1
    return 5
print(val() is val())
print(n)              # was 4, CPython 3
```

Found while fixing BUG-VOID-RETURNS-ZERO-NOT-NONE (the new `_call_is_void` fold
in `_emit_is_compare` doubled a `c.bump()` side effect, which turned out to be
the pre-existing hazard rather than a new one).

**Fixed** in `_emit_compare` by skipping the eager emission when *every*
operator in the comparison is `is`/`is not` — `in` and the ordering/equality
operators still consume the value, and a chain that mixes them still gets it.

### ~~BUG-VOID-RETURNS-ZERO-NOT-NONE. A function or method with no `return <expr>` yields `0`, not `None`~~ — FIXED 2026-07-26

**What it was:** fastpy compiles a Python function whose body never executes
`return <expr>` to an LLVM function with a `void` return type, and every call
site substitutes the placeholder `ir.Constant(i64, 0)` for its value. Nothing
recorded that the placeholder means None, so every consumer fell back to its
LLVM type — INT — and the value read back as the integer `0`. It affected plain
functions and methods equally.

**Reproduced (all three differed from CPython):**
```python
def f():
    x = 1
print(f())            # was 0, CPython None

class C:
    def m(self):
        x = 1
print(C().m())        # was 0, CPython None

def g():
    pass
r = g()
print(r, r is None)   # was "0 False", CPython "None True"
```

**Fixed by the narrower of the two options** that were on the table: keep the
`i64 0` placeholder (so the calling convention is untouched) and correct only
the *tag*. `CodeGen._call_is_void(node)` answers "this call's Python value is
None" for both a `Name` call (`_user_functions[...].ret_tag == "void"`) and an
`Attribute` call (`_find_method_return_type(...)` is `ir.VoidType`), and the
four places that produce a tag rather than an LLVM type consult it:

| site | what it used to do |
|---|---|
| `_wrap_for_print` | fell through to the placeholder's INT type → printed `0` |
| `_bare_to_tag_data` | boxed the placeholder as `FPY_TAG_INT` |
| `_emit_is_compare` | compared the placeholder to null → `f() is None` was False |
| `_infer_type_tag` | typed `r = f()` as INT, so `print(r)` said `0` |

Plus one guard in `_load_or_wrap_fv`: the obj-method-call branch recovers a
method's runtime type with `get_ret_tag()`, but a void method never calls
`set_ret_tag`, so that read back a stale tag — void method calls now fall
through to `_wrap_for_print` instead. `"void"` was also added to
`ValueType.from_old_tag` (→ `VKind.NONE`, whose `llvm_type` is still `i64`, so
nothing about the emitted value changes).

Regression test: `tests/regressions/void_return_is_none.py`.

**Still open, but a different bug:** a void call *as a list element* —
`[f(), g()]` prints `[0, 0]`. That is not about void returns; list element
tagging loses NONE generally (`x = None; print([x, x])` prints `[0, 0]` too).
See BUG-LIST-ELEM-STR-TAG-LOST below, which is the same inference gap for `str`.

**The wider fix is still available if it's ever needed:** return a NONE-tagged
`fpy_val` from the ~20 `isinstance(ret_type, ir.VoidType)` branches in
`compiler/codegen.py` instead of a bare `i64 0`, so the value carries its type
the way every other dynamically-typed result does. That was not done because the
placeholder is consumed as a plain `i64` by a lot of surrounding code
(statement-expression discard, argument coercion, `set_arg_tag` inference), so
it has to be changed at every site at once.

**Related, and already fixed:** the *runtime* side of this had a much worse
symptom. `fastpy_obj_call_methodN` called every registered method through an
`int64_t`-returning pointer type, including void ones, so the "return value" was
whatever the callee left in the return register. `with` reads that value as
"should I suppress the exception?", so a `__exit__` returning None **swallowed
exceptions** — `tests/regressions/with_statement.py` failed with `caught: oops`
missing. It reproduced only when `__exit__` did enough work to leave a non-zero
value behind (touching `self` sufficed), which disguised it as a self-reference
bug. Fixed 2026-07-26 by dispatching on the `returns_value` flag that
`fastpy_register_method` already records (`FpyMethod*VoidFunc` in
`runtime/objects.h`); regression test
`tests/regressions/void_method_return_value.py`.

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

**Facet (c) — list *comprehensions* — newly visible 2026-07-26.** The same
mis-inference applies to `[str(n) for n in nums]`: the result list is typed
`list[int]`, so `g[0]` is emitted as a raw `i64` load of the element's data field
with a hardcoded `i32 0` (INT) tag, and `len(g[0])` returns 0.
```python
def go():
    nums = [1, 2, 3]
    g = [str(n) for n in nums]
    print(len(g) + len(g[0]))   # CPython 4, fastpy 3
go()
```
It also reproduces at module scope, and with `[x + "y" for x in ...]`. A
comprehension whose element is a **constant** str (`["vv" for n in nums]`) or a
plain `Name` of a str element (`[x for x in words]`) is fine, matching facets
(a)/(b): only computed string elements are lost. This facet was invisible until
2026-07-26 because every allocating comprehension crashed the LLVM verifier first
(BUG-DECREF-DOES-NOT-DOMINATE, comprehension facet) — the module never got as far
as producing wrong output. Fix belongs with facets (a)/(b): teach
`_infer_list_elem_type` (and the comprehension result-type inference that feeds
the assignment's `var_types`, codegen.py ~8369) to recognise a statically-str
element expression.

### BUG-NESTED-LISTCOMP-OUTER-ELEM-TAG. A two-generator list comprehension over a flat list mis-tags the outer variable as a list, giving wrong output or an access violation — 2026-07-26

**What:** `_emit_list_comprehension_nested` (codegen.py ~45880) hardcodes the
outer element type to `list:int`:
```python
_nlc_outer_elem = (ValueType(VKind.FVALUE) if _outer_is_obj
                   else ValueType.from_old_tag("list:int"))
```
That is only right for the nested-list shape `[y for row in rows for y in row]`.
For a flat outer iterable — `[f(x, y) for x in nums for y in nums]`, the usual
Cartesian-product idiom — the outer variable `x` is bound as a **list pointer**
built from an `int`, so any use of `x` reinterprets an integer as a pointer.

**Reproduce:**
```python
nums = [1, 2, 3]
f = [x * 10 + y for x in nums for y in nums if x != y]
print(len(f), f[0], f[-1])   # CPython: 6 12 32
```
fastpy: exits `3221225477` (0xC0000005, access violation) with no output. With a
string element expression it instead raises
`TypeError: '<' not supported between instances of 'list' and 'int'`, or silently
drops the filter (`[str(x) + "-" + str(y) for x in nums for y in nums if x != y]`
yields 9 elements instead of 6, first element `1-1`).

**Verified pre-existing:** reproduces unchanged on the parent commit, before the
BUG-DECREF-DOES-NOT-DOMINATE work. It stayed hidden because the differential
suite's nested comprehensions all iterate a list of lists.

**Proper fix:** infer the outer element type from `gen0.iter` the way the
single-generator path does (`_infer_list_elem_type` / `_infer_for_elem_type`)
instead of assuming `list:int`; fall back to `FVALUE` when the element type isn't
statically known, so the runtime tag is preserved. Audit the same hardcoded
assumption in `_emit_list_comprehension_multi` (`_mlc_elem`, ~45830) and
`_emit_dict_comprehension_multi` (`_elem_tag`, ~46412), which use `int` rather
than `list:int` but are equally unconditional.

**Regression coverage:** `tests/regressions/rc_temp_in_comprehension.py`
deliberately iterates a list of lists and carries a comment pointing here, so the
refcount regression test isn't blocked on this bug.

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
  **Correction (2026-07-26): this verification was written entirely at module
  scope**, which takes the early-return global path in `_store_variable` and
  therefore emits neither incref nor decref. The same stores *inside a function*
  hit the bare-ABI/native store paths, which retain nothing while the boundary
  flush still releases → use-after-free. See **BUG-BARE-ABI-STORE-NO-RETAIN**.

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

### BUG-INT-LSHIFT-OVERFLOW. [FIXED] Static `int << int` that overflows i64 is not promoted to BigInt — `7 << 70` gives garbage — 2026-07-26

**Fix (committed):** added `fpy_checked_lshift(int64_t a, int64_t b, FpyBigInt **big)`
(bigint.c/.h) mirroring `fpy_checked_mul` — probes `a >> (63 - b)` for lost bits
and promotes to BigInt via `fpy_bigint_lshift` on overflow. Declared it in
codegen (`self.runtime["checked_lshift"]`), routed `ast.LShift` in
`_emit_int_binop` through `_emit_checked_int_op` (added `ast.LShift` to both
`plain` dicts → bare `shl` when `_program_uses_bigint` is False, and to the
`op_map` → `checked_lshift`), and extended the AST bigint detector to flag
programs using `<<` with a constant shift >= 40. Validated: `7 << 70` →
`8264141345021879123968`, `1 << 63` → `9223372036854775808`, small shifts
(`1 << 3`, `x << 2`) unchanged, 314 differential tests pass.

**What:** `_emit_int_binop` (codegen ~34482) lowered `ast.LShift` to a bare
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

### ~~BUG-SUBSCRIPT-UNTYPED-PARAM-BRIDGE~~ **FIXED**. Subscripting an untyped function parameter that holds a `str` falls back to the CPython bridge and returns NULL in pure mode — 2026-07-21

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

**Fix:** the value never reached the dispatch helper, which already knew how to
index a str, list, dict, tuple or bytes from the tag. Four parts:

1. *The parameter was tagged `int`.* `_efd_store_parameters` resolves each
   parameter's tag from `_function_signatures`. Its **pointer** branch already
   had an "every caller unresolvable → `mixed`" arm; the **non-pointer** branch
   did not, and fell through to `"int"` — the same "silence means scalar" guess
   as BUG-UNTYPED-PARAM-BARE-ABI. So `s` loaded as a naked pointer-as-integer
   and `s[i]` sailed past the `fastpy_fv_subscript` arm into the CPython
   `__getitem__` bridge. The non-pointer branch now answers `mixed` too, unless
   the parameter carries an annotation (which is evidence in its own right).
2. *`return v[i]` was typed `int`.* An element of an untyped container is
   itself of unknown kind, so `_duf_determine_ret_tag` now reports `mixed` for
   it rather than throwing the runtime tag away one frame up.
3. *Slices had no runtime-dispatch arm at all.* `v[1:3]` took whichever static
   path the compiler guessed, so a list arriving on `str_slice` sliced to `""`
   instead of faulting. New runtime helper `fastpy_fv_slice` (`runtime/objects.c`)
   picks str/bytes or list/tuple from the tag and echoes that tag back, since a
   slice has the same kind as what it came from; `_emit_fv_slice` calls it.
4. *One slot per local.* A local's storage class was decided by its first
   store, and a later store needing an `FpyValue` allocated a **second**, wider
   slot — stranding every load already emitted against the first. Straight-line
   code survives that; `t = 0` followed by `t = t + at(lst, i)` in a `while`
   loop does not, because the load in the loop body is bound to the dead slot
   forever (`sum` came out 60 instead of 420). New pre-scan
   `_scan_fv_forced_locals` decides up front which locals can hold a
   runtime-tagged value and gives them an `FpyValue` slot from their first
   store, so a slot is never widened.

**Test:** tests/regressions/subscript_untyped_param.py. Verified wrong at
1f23c9f. Clean under ASan/UBSan/LSan.

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

**Residual tech-debt:**
- *Path-header collision — **FIXED** 2026-07-26, and it was NOT low risk.* The
  original note called this a 1-in-4-billion curiosity; it is actually
  deterministic and user-controllable by filename. `Path('/tmp/' + 'a'*27 +
  'SJBO-collide.txt')` puts `FPY_OBJ_MAGIC` ("SJBO") at bytes 32–35, so
  `fpy_rc_incref`/`fpy_rc_decref` treat the path text as an `FpyObj` and
  decrement bytes of the filename as a refcount. Measured: 4 of 31 checks pass
  under the old layout (read_text/exists/parent/is_file all corrupt) vs 31 of
  31 with the fix.
  **Fix:** pure-mode Path is now a real header struct (`FpyPurePath` in
  `runtime/pathlib_pure.c`): `magic` at offset 0 (`0x48544150` "PATH", chosen
  to differ from `FPY_CLOSURE_MAGIC`), a zero `guard` word at offset 32 (where
  the OBJ probe reads), and the NUL-terminated text at offset 40. `_p()`
  validates the magic before returning text; `fastpy_path_as_cstr()` is
  exported for cross-TU consumers. Because the text no longer starts at the
  pointer, two call sites had to convert: `fastpy_path_with_suffix` now has a
  pure-mode implementation in `pathlib_pure.c` (the `runtime.c` one is
  `#ifndef FPY_PURE_MODE`), and codegen routes a Path right-hand operand of
  `joinpath()` / `p / other` through `path_str` first
  (`_emit_path_join_operand`). Regression test:
  `tests/pure/path_magic_collision_checks.py` (bitmask 127).
- *`Path.iterdir()` in pure mode — **FIXED** 2026-07-26.* Implemented with
  opendir/readdir into `fpy_list_new`/`fpy_list_append`, yielding an FpyList of
  OBJ-tagged `FpyPurePath` entries joined against the parent (readdir order,
  `.`/`..` skipped, like CPython). Codegen now types `p.iterdir()` as
  `list[Path]` (`_is_path_iterdir_call` feeds `_infer_type_tag`,
  `_is_list_expr` and `_get_list_elem_type`), so `for e in p.iterdir()` uses
  `_emit_for_list` and the loop variable keeps its PATH tag. Because codegen is
  mode-agnostic, `cpython_bridge.c`'s `fastpy_path_iterdir` was changed to
  return an FpyList too instead of the raw PyObject* list. Regression test:
  `tests/pure/path_iterdir_checks.py` (bitmask 63). Unlike `read_text`, a
  failed `opendir` raises RuntimeError rather than degrading — an empty list
  would be indistinguishable from an empty directory.

**Other pure-mode gaps found while testing this (pre-existing, not
regressions):**
- ~~`print(Path(...))` raises `RuntimeError: operation requires the CPython
  bridge`~~ — **FIXED 2026-07-26.** `print`/`repr` of an OBJ-tagged value fell
  through to the bridge because nothing could tell a Path pointer from a
  `PyObject*`. The Path header's magic now answers that: `pathlib_pure.c`
  exports `fpy_pure_path_text()` and `objects.c` consults it before each bridge
  fallback (`fastpy_obj_write`, `fastpy_fv_str`, `fpy_value_repr`). `repr`
  matches CPython's `PosixPath('...')`. Regression test:
  `tests/pure/path_display_checks.py` (bitmask 255).
- ~~`os.path.exists(p)` / `os.path.getsize(p)` / `open(p)` with a Path argument
  fail to **link** in pure mode~~ — **FIXED 2026-07-26**, and the original
  description was wrong in a way worth recording: this was never a link error.
  The runtime entry points take the path as a `const char *`, and after the
  `FpyPurePath` header landed a Path pointer no longer points at its text, so
  the callee read the header. `os.path.exists(Path('/tmp/x'))` returned **False**
  — a silently wrong answer, which is worse than a link error, not better. The
  builtin `open()` was the loud member of the family: `fopen` was handed the
  header and reported `FileNotFoundError: [Errno 2] No such file or directory:
  'PATH'` — the magic word, read as a filename. Fixed by generalising
  `_emit_path_join_operand` into `_emit_path_text_arg` in codegen and routing
  every *path text* parameter through `fastpy_path_str()`: the `os.path.*`
  table, 20 `os.*` argument sites, and `_emit_builtin_open`. Method receivers
  are deliberately untouched — those take a Path proper. Regression test:
  `tests/pure/path_arg_checks.py` (bitmask 131071). **When adding a runtime
  entry point that takes a path string, emit its argument with
  `_emit_path_text_arg`** — the failure mode is per-call-site, silent, and only
  reproduces with a Path argument, so a suite written with string paths will not
  catch it.
- `os.mkdir(p)` / `os.remove(p)` / `os.rmdir(p)` **fail silently**, returning
  `-1` instead of raising `OSError`. CPython raises; pure mode swallows. This is
  not merely cosmetic — it cost a full SlateOS boot cycle to diagnose: a
  capability-denied `os.mkdir` produced no error at all, and the failure only
  surfaced two statements later as `Path.iterdir()` raising "cannot open
  directory", which pointed the investigation at `opendir` rather than at
  `mkdir`. The proper fix is an `OSError`/`FileNotFoundError` exception kind in
  the pure runtime (`FPY_EXC_*` in runtime.c has no OS-error member today —
  only GENERIC/RUNTIMEERROR are available) and raising it from the `os.*`
  mutators on a negative return. Until then, pure-mode programs that mutate the
  filesystem should check the result explicitly rather than assume success.

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

### BUG-SECOND-ALLOCA-NOT-DIAGNOSED. A name can silently acquire a second stack slot — 2026-07-27

**What (tech debt):** when a store's value type does not match the alloca
already bound to a name, the store path allocates a *fresh* alloca and rebinds
`self.variables[name]` to it. Every load already emitted — including the ones a
loop's back-edge will re-run — stays bound to the abandoned slot. This is the
mechanism behind BUG-VAR-RETYPED-MIDSCOPE-STALE-SLOT, and the fix for that bug
addressed the *cause* (pre-scan the scope, widen the slot up front) without
closing off the *mechanism*.

`_scan_fv_forced_locals` is a conservative approximation. Anything it fails to
foresee still falls through to the silent second alloca, and the resulting
wrong answer looks like a miscompile with no diagnostic anywhere.

**Proper fix:** make the second alloca an assertion failure — a `CodeGenError`
naming the variable, the two types and the statement. Every case it catches is
a bug in the pre-scan; none should reach a user. Landing this needs the whole
suite run once to enumerate what currently trips it, which is why it is filed
rather than done.

**Where:** the assignment/store path in `CodeGen`, and
`_scan_fv_forced_locals` (`compiler/codegen.py:~23157`).

### BUG-BIGINT-PROGRAM-HANGS-WHILE-COUNTER. Any big-integer constant makes every `while` loop counter spin forever — 2026-07-27

**What:** the compiled binary produces *no output at all* and never exits.

**Reproduce** — should print `1`, instead hangs forever with empty stdout:
```python
def f():
    x = 4611686018427387904      # any constant >= 1 << 62
    i = 0
    while i < 1:
        i = i + 1
    print(i)

f()
```

**Root cause — this is BUG-SECOND-ALLOCA-NOT-DIAGNOSED firing.** Pass 0.9
(`compiler/codegen.py:~3830`) sets a **whole-program** flag
`_program_uses_bigint` when the AST contains an integer literal `>= 1 << 62`,
a `**` with a constant exponent `> 30`, or a `<<` with a constant shift `>= 40`.
With that flag set, `_emit_int_binop` (`~36683`) stops emitting a plain
`builder.add` and routes *every* integer `+`/`-`/`*`/`**`/`<<` through
`fpy_checked_add` and friends, whose result is a **tagged** `{i32, i64}` that
carries `FPY_TAG_BIGINT` on overflow.

`_scan_fv_forced_locals.yields_mixed` does not know this. Its `ast.BinOp` case
is `yields_mixed(e.left) or yields_mixed(e.right)`, and for `i + 1` neither
operand is mixed — so `i` is not forced wide, gets an `i64` alloca from `i = 0`,
and the widening then happens *mid-loop* via the silent second alloca. The
emitted IR says it plainly:

```llvm
  %"i.3" = alloca {i32, i64}          ; the wide slot the body writes
  %"i"   = alloca i64                 ; the abandoned slot the condition reads
while.cond.1:
  %"i.1" = load i64, i64* %"i"        ; always 0  ->  i < 1 forever
while.body.2:
  ... call i64 @"fpy_checked_add"(i64 %"i.2", i64 1, i8** %"big_out") ...
  store {i32, i64} %".14", {i32, i64}* %"i.3"   ; writes the *other* slot
  br label %"while.cond.1"
```

The condition reads a slot nobody ever stores to again, so the counter is
permanently 0 and the loop never terminates. There is no output because stdout
is still buffered.

**Why it looked narrower than it is.** Originally filed as
"module-level int > INT32_MAX + a `while` inside a function". All three
qualifiers are wrong: the constant may live anywhere including inside the same
function; the threshold is not `INT32_MAX` but Pass 0.9's rules (which is why
`2 ** 31` tripped it and `2 ** 30` did not — exponent `> 30` — while the bare
literal `2147483648` does *not*, being below `1 << 62`); and the *constant's*
scope is irrelevant.

What does matter is the scope of the **loop**. A `while` at module scope is
unaffected, because a module-level name is backed by a real LLVM global whose
storage is one fixed location — there is no second alloca to strand the loads
on. A `for` loop is unaffected in either scope, because its induction
variable's slot is created by the loop emitter rather than by a first plain
store. So the bug needs a `while` *inside a function*, with a counter
introduced by an ordinary assignment.

**Not a regression.** Verified failing identically at HEAD, `622b214` and
`cfc34df`. It predates the whole IfExp/tagged-value line of work.

**Severity: high — an infinite hang with no output, on entirely ordinary code.**
Worse than a wrong answer: no assertion, no message, no exit. The harness does
report it, as a `fail` with `Timed out` in stderr.

**Fix,** in five parts:

1. `yields_mixed`'s `BinOp` case now returns `True` for an overflow-capable
   operator (`+ - * ** <<`) whenever `self._program_uses_bigint` is set,
   without asking whether either operand is *already* mixed — because that is
   precisely what the emitter will do. Pass 0.9 runs long before the scan, so
   the flag is available.
2. **All-constant arithmetic is exempt, and that exemption is load-bearing.**
   `x = 2 ** 63` is *unconditionally* a BigInt, not a value that might promote,
   and codegen gives it a static BIGINT slot holding a pointer. Widening it to
   a tagged slot instead broke every consumer expecting that pointer —
   `print(add_big(x, y))` printed an address — because a BIGINT-tagged
   `FpyValue` is never narrowed back at a call boundary. **This is the
   correction to the assumption that over-approximating is free:** a wide slot
   is only harmless for values the tagged paths actually handle, and BigInt is
   not one of them until BUG-BIGINT-FV-RESULT-NOT-CONSUMED is fixed. New
   helper `_is_constant_arith`. Float arithmetic *is* still over-approximated,
   which is fine because a float round-trips through a wide slot correctly.
3. **Variables with an explicit overflow policy are exempt.** `unchecked_int`
   wraps and `checked_int` raises; neither ever produces a tagged value, and
   widening one broke the policy badly enough to crash
   `annotated_overflow_behavior` with an access violation. The scan now reads
   the `unchecked_int`/`checked_int` constructors and the
   `Unchecked`/`Checked` `Annotated` markers *syntactically*, because
   `_int_mode_vars` is not populated until emission — long after this scan.
   The constructor table moved to a shared `_INT_CONSTRUCTORS` class constant
   rather than being duplicated.
4. **Parameters needed the same guarantee.** Excluding them from the scan is
   right — their slots are made by `_efd_store_parameters`, not by a first
   store — but a parameter is the most natural loop counter there is, and
   `def f(i): while i < n: i = i + 1` hung for exactly the same reason. The
   scan is now re-run with parameters visible, and any parameter it forces has
   its slot rebuilt as an `fpy_val` immediately after `_efd_store_parameters`.
   That point is the only safe one: just the parameter stores have been
   emitted, so rebuilding a slot strands no loads. Non-parameter names already
   in `self.variables` stay skipped — a closure cell or a global is not ours to
   widen.
5. **The operator decides, but only for operands that could be integers.**
   Part 1 keyed off `+` alone, and `+` is also object concatenation: it widened
   `v3` in `v3 = v1 + v2` for a user class with `__add__`, so `f"{v3}"` printed
   the empty string — the object sat in a tagged slot where its `__str__` was
   never found. `tests/programs/advanced.py` caught this and nothing else did.
   The scan now carries a `maybe_int` predicate: container/comprehension/
   f-string/comparison nodes, non-int constants, and calls to a class defined
   in this program are never ints, and names assigned from any of those are
   propagated to a `_never_int` set by a small fixpoint. Anything it cannot see
   through — a plain call, an attribute, a subscript — answers "maybe", since
   under-approximating brings the hang back. Class names come from a new
   `_program_class_names` property reading `self._module_tree` (saved in
   Pass 0), because no codegen-side class registry exists this early.

   This also removes the float over-approximation part 2 had accepted:
   `t + 1.5` has a float constant operand, so it is no longer widened.

**Test:** `tests/regressions/bigint_program_while_counter.py`, also clean under
ASan/UBSan/LSan.

**Was worked around** in `tests/regressions/abs_of_tagged_value.py`, whose
`while` accumulator was moved to module scope (the file binds `2 ** 80`). The
workaround is now unnecessary but harmless, and the comment there points here.

### BUG-INT-OVERFLOW-WRAPS-WITHOUT-BIG-LITERAL. Integer arithmetic silently wraps unless the program *mentions* a big constant — 2026-07-27

**What:** Pass 0.9 decides whether a program needs BigInt by looking for a big
integer *constant* in the AST (`>= 1 << 62`, `**` with exponent `> 30`, `<<`
with shift `>= 40`). If it finds none, `_emit_int_binop` emits a plain
`builder.add`/`mul` with no overflow check at all. But a program can overflow at
runtime without containing any big constant — that is what repeated
multiplication *is*. Python integers are arbitrary precision; fastpy silently
produces a wrapped i64.

**Reproduce** — every one of these is ordinary, big-literal-free code:
```python
def fact(n):
    r = 1
    i = 2
    while i <= n:
        r = r * i
        i = i + 1
    return r
print(fact(25))     # 7034535277573963776, not 15511210043330985984000000

a = 0
b = 1
i = 0
while i < 100:
    a, b = b, a + b
    i = i + 1
print(a)            # 3736710778780434371, not 354224848179261915075

def f():
    t = 1
    for i in range(70):
        t = t * 2
    return t
print(f())          # 0, not 1180591620717411303424
```
Adding any big constant anywhere in the file — even an unused `z = 2 ** 80` —
makes the first and third correct, which is a good way to confirm the trigger.

**Where:** Pass 0.9 (`compiler/codegen.py:~3830`) and the
`if not self._program_uses_bigint` early-out in `_emit_int_binop` (`~36683`).

**Why it is the way it is:** the flag exists purely for speed — it lets the
majority of programs use plain LLVM arithmetic instead of paying an
`fpy_checked_add` call per operation. The heuristic is sound for *constants* and
unsound for *computed* values, which is most of them.

**Proper fix:** the fast path has to be justified by something other than "no
big literals appear". The right shape is the one already used for
`--typed --int64`: `llvm.sadd.with.overflow.i64` and friends, which cost
essentially nothing (no call, still vectorisable) and branch to a promotion slow
path only on actual overflow. That gets correctness *and* keeps the speed, and
would let Pass 0.9's whole-program flag be deleted rather than patched.

**Blocked on the BigInt consumers.** Deleting the flag means every program's
integer arithmetic can promote, so BIGINT-tagged `FpyValue`s stop being confined
to programs that mention a big literal and start flowing through ordinary code —
and every consumer that fails to narrow one back to a pointer becomes wrong on
textbook arithmetic. The same flag also drives the slot scan's widening, so
turning it on everywhere widens every integer local. Both effects are safe only
once a BIGINT-tagged value is narrowed correctly wherever it is consumed.

Two of these are now fixed: BUG-BIGINT-FV-RESULT-NOT-CONSUMED (comparison and
arithmetic) and BUG-BIGINT-RETURNED-FROM-FUNCTION-LOSES-TAG (the return
boundary, which this bug's own repros all walk into — `fact` and `f` above both
`return` the accumulator).

Still open and worth clearing first, because deleting the flag turns each from a
corner case into something reachable from ordinary code:
BUG-LIST-LITERAL-BIGINT-DECIMAL-ELEM (a promoted value stored into a list
literal loses its tag) and BUG-INT-FLOAT-OF-TAGGED-VALUE (`int()`/`float()` of
one are no-ops). Neither is large.

Note also that `_returns_may_be_bigint` and the slot scan's widening clause are
both gated on `_program_uses_bigint`. Deleting the flag makes both
unconditional, which is the intended end state but means the widening they do
must be measured for cost, not just correctness.

**Severity: high — silently wrong arithmetic on ordinary code,** and it violates
a core language guarantee rather than an edge case. `fact(25)` and `fib(100)`
are not exotic inputs.

### BUG-BIGINT-MUL-BY-VAR-MISTAGS-FLOAT. A promoted BigInt times a *variable* comes back tagged FLOAT — 2026-07-27

**What:** in a program where `_program_uses_bigint` is set, an accumulator that
promotes to BigInt and is then multiplied by a **variable** produces a value
tagged `FPY_TAG_FLOAT`, so it prints as a float. Multiplying by a **constant**
is correct.

**Reproduce** — the only difference between these is `2` vs `i`:
```python
z = 2 ** 80                      # switches on checked arithmetic

def ok():
    t = 1
    i = 0
    while i < 70:
        t = t * 2                # correct: 1180591620717411303424
        i = i + 1
    print(t)

def bad():
    t = 1
    i = 2
    while i <= 25:
        t = t * i                # 6.746447057102016e+17
        i = i + 1
    print(t)
```

**Where:** the tagged-operand path of `_emit_int_binop` / `fpy_checked_mul`'s
result handling. The FLOAT tag suggests a branch that treats "tag is not INT" as
"tag is FLOAT" and reinterprets the BigInt pointer's bits as a double.

**Independent of the slot scan.** It fails identically at module scope and in a
`for` loop, neither of which goes through `_scan_fv_forced_locals`, and it
failed at HEAD before BUG-BIGINT-PROGRAM-HANGS-WHILE-COUNTER was fixed.

**Severity:** silently wrong values, with a visibly wrong *type* as the tell.
Excluded with a comment in
`tests/regressions/bigint_program_while_counter.py`.

### BUG-DICT-VALUE-STATIC-KIND. A dict value is loaded with the static kind of the first store — 2026-07-27 — **store half FIXED, load half OPEN**

**Store half fixed 2026-07-27.** Every container store now carries the value's
*runtime* tag. The stores reached for `_bare_to_tag_data`, whose contract is
"bare value in, **static** tag out", and wrapped its answer in
`ir.Constant(i32, tag)` — so an FV-backed local went in as `FPY_TAG_INT` and
the container kept the payload word under the wrong type. They now go through
`_to_tag_data_ir`, which was extended to recognise the shape that actually
matters: an FV-backed **variable**. `_emit_expr_value` hands a `Name` back as
the bare i64 payload, so that helper's `isinstance(value.type,
ir.LiteralStructType)` test used to miss it and fall through to the same static
guess; it now reloads the variable's `fpy_val` alloca for *both* halves, so tag
and payload always describe the same value. Converted sites: `_emit_dict_literal`,
`_emit_set_literal`, the `_emit_subscript_store` dict/ChainMap/pyobj arms, all
three `_emit_dict_comprehension` shapes plus `_emit_dict_comprehension_multi`,
`set.add`/`.discard`/`.remove`, and the `in` probe against a set (which has to
match what `add` stored — a static INT guess there made `4.5 in s` compare a bit
pattern against a FLOAT-tagged entry and answer False). The list store keeps the
*static* tag deliberately: it is what decides whether the inline fast path is
safe, since a heap tag must go through the refcounting setter.

Two adjacent defects fell out of the same fix. The **comprehension** tuple-unpack
paths (`_emit_list_comp_tuple_unpack` and the `ast.Tuple`-target arm of
`_emit_dict_comprehension`) hand-rolled the element fetch — `list_get_fv` into
scratch slots, then `_store_variable(load(d2), pos_tag)` — and threw the runtime
tag away, after a `pos_tags = [t if t != "unknown" else "int" ...]` line rewrote
every honest "unknown" into a wrong "int". The statement `for` loop had been
right all along because it uses `_fv_store_from_list`; both comprehensions now
call the same helper and keep "unknown" unknown. That is why
`{k: v for k, v in [("a", fl)]}` stored `4616752568008179712` while the
equivalent `for` loop printed `4.5`.

Covered by `tests/regressions/dict_and_set_keep_the_runtime_tag.py`.

**Still open: the load half**, which is the original repro below. A dict whose
values have differing *static* kinds still loads through the kind of the first
store. `print` is right (it has a tagged path) and any arithmetic consumer is
wrong.

**What:** subscripting a dict whose values have differing kinds yields a *bare*
scalar typed from whatever was stored first, rather than a tagged `FpyValue`.
The bit pattern is then reinterpreted as that kind.

**Reproduce** — should print `1 -2.5` then `-2.5`:
```python
d = {}
d[0] = 1
d[1] = -2.5
print(d[0], d[1])     # prints 1 -2.5   (print has a tagged path)
x = d[1] + 0.0
print(x)              # prints -4.6105601185205453e+18
```
`print` happens to be right, which makes this easy to miss; any *arithmetic*
consumer is wrong. `abs(d[1])` is wrong for the same reason and was originally
filed under BUG-ABS-OF-TAGGED-VALUE, but it is abs-independent — the repro above
has no `abs()` in it.

**~~Sharper repro (2026-07-27) — `print` is wrong too.~~ — this half is FIXED.**
When the values being stored were themselves *runtime-tagged* (an `FpyValue`
variable rather than a literal), the tag was dropped on the way in and the load
handed back a bare i64 tagged INT, so even `print` showed the raw payload:
```python
m = [3, True, 4.5, "s", None]
n, t, fl, st, no = m[0], m[1], m[2], m[3], m[4]
d = {"n": n, "t": t, "f": fl, "s": st, "o": no}
print(d["n"], d["t"], d["f"], d["s"], d["o"])
# was:  3 1 4616752568008179712 140701479720616 0
# now:  3 True 4.5 s None
```
`4616752568008179712` is the bit pattern of `4.5` and `140701479720616` is the
string's address. Note the diagnosis this misled me toward was wrong: the load
was *not* missing `fastpy_dict_get_fv` — an IR dump showed the load already
calling it with tag out-params, and every store passing a literal `i32 0`
alongside. Sets had it too (`s.add(fl)` then `fl in s` was False), which is what
established this was a store-side rule and not a dict-specific one.

**Where (load half, still open):** the dict-subscript load path in `CodeGen`
picks a bare kind from the dict's inferred value type instead of consuming the
`fastpy_dict_get_fv` tag. The likely fix is a `_scan_fv_forced_locals` that
knows a heterogeneous dict's value is mixed, so the destination is an FV local
and the tagged load is kept rather than unwrapped.

**Severity:** silently wrong arithmetic.

### BUG-MINMAX-OF-TAGGED-VALUE. `max`/`min` of two tagged values emits an `icmp` on a struct and fails the IR verifier — 2026-07-27

**What:** `max(a, b)` where both operands are `fpy_val` `{i32, i64}` emits an
`icmp` directly on the struct. LLVM rejects it with *"icmp requires integer
operands"*, so the build fails outright.

**Reproduce:**
```python
v = [1, -2.5]
print(max(v[0], v[1]))
```

**Where:** the `max`/`min` emitter in `CodeGen`, which — exactly like
`_emit_builtin_abs` before its fix — assumes naked scalars. The fix has the same
shape: a runtime `fastpy_max_fv`/`fastpy_min_fv` dispatching on the tag pair,
because comparing INT against FLOAT against BIGINT against DECIMAL is not an
`icmp`.

**Note this is reported by the harness as `skip`, not `fail`** — see
BUG-SKIP-MASKS-VERIFIER-ERRORS. Excluded with a comment in
`tests/regressions/abs_of_tagged_value.py`.

**Severity:** compile failure (loud), but invisible in the suite.

### ~~BUG-BIGINT-FV-RESULT-NOT-CONSUMED. A BIGINT-tagged FpyValue is not narrowed back to a pointer by comparison or arithmetic~~ — FIXED 2026-07-27

**What:** runtime helpers that return a BigInt do so as a *tagged* `FpyValue`
carrying the pointer in `data`. Consumers that expect a bare BigInt pointer —
`==`, `-`, and friends — never narrow it, so they operate on the two pointers
instead of the two numbers.

**Reproduce** — `-b == -c` is False and the subtraction is garbage:
```python
b = 2 ** 80
c = 2 ** 80
print(-b == -c)      # False; should be True
print(-b - -c)       # nonzero garbage
```
`abs()` inherits this exactly, because its BigInt path follows the same
`bigint_neg` convention: `abs(b) == abs(-b)` is False.

**Where — two separate holes, both downstream of correct codegen.** Reading the
IR for the repro settles it: codegen builds *exactly the right thing*. `-b`
emits `fpy_bigint_neg` and wraps the result in an `{i32 10, i64 ptr}`, so both
operands reach the consumer properly tagged BIGINT. Neither consumer knows the
tag.

1. **`fastpy_fv_compare` (`runtime/objects.c:689`) has no BIGINT case.** It
   handles STR, then "at least one is FLOAT", then falls through to a default
   integer compare — which compares the two *pointers*. So `-b == -c` is
   pointer equality. The FLOAT branch is wrong for BigInt too: it does
   `(double)data` on a pointer. Note `fpy_value_compare` (the qsort helper at
   `:1596`) already gets this right with `fpy_bigint_cmp`, so the knowledge
   exists in the file — just not on this path. Needs a BIGINT case that
   promotes an INT/BOOL operand with `fpy_bigint_from_i64`, calls
   `fpy_bigint_cmp`, and frees the temporary; plus a real conversion for
   FLOAT ⊕ BIGINT.
2. **`_emit_binop_unknown` inlines a two-way INT-vs-FLOAT tag test.** The IR is
   `and(tag_l == 0, tag_r == 0)` branching to `unkn_uu.iarith` or
   `unkn_uu.farith` — so BIGINT (tag 10) takes the *float* branch and the
   pointer is bitcast to a double. That is where `-b - -c` gets `1024.0`.
   **This is BUG-ABS-OF-TAGGED-VALUE's shape exactly**: an inlined binary
   dispatch where six tags are numeric. And as with `abs`, the runtime already
   has the correct answer — `fastpy_fv_binop` (`runtime/objects.c:1119`)
   handles BIGINT and Decimal properly and simply is not called. The fix is to
   keep the inlined int/float fast path for speed but give it a third edge to
   `fastpy_fv_binop` for anything else, rather than assuming float.

**Not caused by the abs fix** — the `bigint_neg` repro above has no `abs()` in
it. Excluded with a comment in `tests/regressions/abs_of_tagged_value.py`.

**Severity:** silently wrong comparisons and arithmetic on big integers.

**This blocked BUG-INT-OVERFLOW-WRAPS-WITHOUT-BIG-LITERAL, and was fixed
first.** Fixing the wrap means checking every integer operation, which means
`_program_uses_bigint` is effectively on for every program, which means
BIGINT-tagged `FpyValue`s flow through *ordinary* code rather than only through
programs that mention a big literal. Every consumer that fails to narrow one
would then be wrong on textbook arithmetic instead of on a corner. It is also
the same limit that forced `_is_constant_arith` in
BUG-BIGINT-PROGRAM-HANGS-WHILE-COUNTER — a wide slot is only safe for kinds the
tagged paths handle, so making BigInt one of them unblocks both.

**FIXED 2026-07-27**, in four parts. Regression test:
`tests/regressions/bigint_fv_result_consumed.py`, also clean under
ASan/UBSan/LSan.

1. **`fastpy_fv_compare` got a BIGINT branch**, placed *before* the FLOAT and
   default-integer branches so neither can claim a BigInt operand first. Two
   BIGINTs go to `fpy_bigint_cmp`; an INT/BOOL operand is promoted with
   `fpy_bigint_from_i64` into a temporary that is freed; a FLOAT operand goes to
   a new `_fpy_bigint_cmp_double`.
2. **That float comparison is exact, in both directions.** Converting the BigInt
   to a double would round every value past 2^53 together, making
   `2**80 + 1 == 2.0**80` true — so the *double* is converted to an integer
   instead, which is always lossless. Below 2^63 it goes through an `int64_t`
   with the fraction breaking the tie; at or above 2^63 a finite double is
   necessarily an exact `mantissa * 2^k`, and the new
   `_fpy_bigint_from_large_double` recovers both halves with `frexp`/`ldexp`
   (53-bit mantissa into an i64, leftover exponent as a `fpy_bigint_lshift`).
   NaN answers "unordered", so only `!=` is true.
   Also **FLOAT was missing from the BIGINT row of
   `_fpy_tags_order_compatible`**, so `2 ** 80 < 1.5` used to raise TypeError.
   Adding it is what exposed the exactness question: at HEAD `==` between a
   BigInt and a float answered False *by accident*, because the pair was
   "incompatible".
3. **The three inlined two-way dispatches in codegen got a third edge.** There
   were three, not one: `_emit_binop_unknown`'s Add-specific `unkn.num_*` split,
   its general `_uu` split, and the unary-minus FpyValue path. Each tested
   "both tags == INT" and sent *everything else* to float arithmetic, bitcasting
   a pointer to a double. The int and float fast paths stay inline; the float
   edge is now guarded by a real `_fv_tag_is_plain_scalar` check on both
   operands (INT/FLOAT/BOOL — the tags whose `data` really is a number), and
   anything else takes a new third edge to `fastpy_fv_binop`, which already
   handled BigInt, Decimal, string concatenation and the TypeErrors correctly
   and simply was not being called. A shared `_FV_BINOP_OPCODES` table replaced
   two copies of the operator→opcode map that had to agree.
4. **Unary minus needed a runtime entry point that did not exist.** It had been
   an inlined `select(tag == FLOAT, fneg, 0 - data)`, which negated a BigInt's
   *pointer* while keeping tag 10 — `-(-b)` handed garbage to the printer and
   took an access violation. New `fastpy_neg_fv` in `runtime/objects.c`, modelled
   on `fastpy_abs_fv`: BOOL→INT, INT with the `INT64_MIN` widening to BIGINT,
   FLOAT, BIGINT, DECIMAL, COMPLEX, and a TypeError for the rest.

**Two pre-existing bugs were found and excluded from the test** rather than
fixed here, each verified by A/B against HEAD: BUG-BOOL-PLUS-INT-YIELDS-FLOAT
and BUG-BIGINT-RETURNED-FROM-FUNCTION-LOSES-TAG.

### ~~BUG-INT-FLOAT-OF-TAGGED-VALUE. `int()` and `float()` of a tagged value are no-ops~~ — FIXED 2026-07-27

**What:** `int(x)` and `float(x)` where `x` is an `fpy_val` pass the value
straight through, tag and all, instead of converting it.

**Reproduce** — should print `-2` then `1.0`:
```python
v = [1, -2.5]
print(int(v[1]))      # prints -2.5
print(float(v[0]))    # prints 1
```

**Where:** `_emit_builtin_int` / `_emit_builtin_float` in `CodeGen` — the same
"knows only naked scalars" shape as BUG-ABS-OF-TAGGED-VALUE, but failing open
(pass-through) rather than closed (fallback zero). The fix is the same: a
tag-dispatching runtime entry point, which additionally has to get
truncation-toward-zero right for FLOAT→INT and raise for the non-numeric tags.

**Severity:** silently wrong values, and wrong *types* downstream.

**FIXED 2026-07-27** with `fastpy_int_fv` / `fastpy_float_fv`, the entry
points that note asks for. Writing them turned up that the pass-through was
only half the bug — the *other* half was the path that looked correct:

- The inlined FV-**variable** branch (a three-way float/str/else in `int()`, a
  three-way str/float/else in `float()`) fell into its else arm for every
  remaining tag. `int()` returned that arm's raw payload, which for a BigInt
  or Decimal is the **pointer**; `float()` ran `sitofp` on it, converting the
  pointer to a double. `int(None)` was special-cased to raise, but
  `int([1])`, `int({})` and every `float()` of a non-number answered a number.
  Both branches are gone; both shapes now call the runtime.
- `int()` of a *naked double* lowered to a bare `fptosi`, which is undefined
  outside the target range. `int(1e30)` gave **20**; `int(float("nan"))` and
  `int(float("inf"))` both gave INT64_MIN where CPython raises ValueError and
  OverflowError. `_emit_int_of_double` keeps the `fptosi` for the in-range
  case — guarded by an *ordered* compare, so NaN takes the other edge — and
  calls the runtime otherwise.

Because a float past 2^63 and a BigInt argument both convert to a BigInt,
`int()` now yields a *tagged* result rather than a bare i64, the way `abs()`
already did. `float()` keeps returning a bare double, since it has only one
result kind. The runtime handles seven convertible tags (int, bool, float,
str, bytes, bigint, Decimal) and raises CPython's message for the rest;
Decimal→int truncates on the coefficient rather than through a double, so
`int(Decimal("0.9999999999999999999"))` is 0 and not 1.

One leak fixed alongside, since `fastpy_int_fv` calls into it: six sites in
`runtime/objects.c` built their error message with a fresh `malloc` and handed
it to `fastpy_raise` — correct when the message was borrowed, a straight leak
per failed conversion now that the raise copies. All six use `_err_buf` with a
`%.160s` bound, which no parseable number reaches.

Pinned by `tests/regressions/int_float_of_tagged_value.py`.

### ~~BUG-LIST-LITERAL-BIGINT-DECIMAL-ELEM. A BigInt or Decimal stored into a list literal loses its tag~~ — FIXED 2026-07-27

**What:** a list literal containing a BigInt element stores the raw pointer with
an INT tag, so reading it back prints the address. A Decimal element is worse —
it prints nothing at all.

**Reproduce:**
```python
v = [2 ** 80, 1]
print(v[0])                    # prints 1715270543088 (a pointer)

from decimal import Decimal
w = [Decimal("1.5"), 1]
print(w[0])                    # prints an empty line
```

**Where:** the list-literal element store path. It classifies each element by
static kind and evidently has no BIGINT/DECIMAL case, so the pointer is stored
with the default INT tag (and the Decimal one presumably reaches a printer that
formats a mis-tagged value as empty). This is the sibling of
BUG-LIST-ELEM-STR-TAG-LOST and probably wants fixing alongside it.

**Note the asymmetry:** a *dict* holds these correctly, so the two container
element-store paths disagree — which is itself worth collapsing.

**Severity:** silently wrong output; the Decimal case loses the value entirely.

**FIXED 2026-07-27.** Collapsing the two container element-store paths is
exactly the fix. `_emit_list_append_expr` now asks `_infer_type_tag` for the
element's kind — the same analysis `_bare_to_tag_data` consults, which is
precisely *why* a dict was right all along — instead of the narrow `_is_*_expr`
predicates. (`_is_bigint_expr` knows only an integer literal too wide for an
i64 and a BIGINT-kinded name, so it answered False for `2 ** 80`, a BinOp of
two small constants; `_is_decimal_expr` was right about `Decimal("1.5")` and
simply had no branch calling it.) The old predicates are kept as extra
evidence, OR-ed in, since they were already trusted and can only widen what is
tagged correctly.

Storing the tag correctly then made the *read* side reachable, and it turned
out to be broken in seven further ways — each found and fixed in the same
change, each listed below: BUG-LIST-ELEM-TYPE-MISSES-HEAP-NUMERICS,
BUG-COMPLEX-SUBSCRIPT-NOT-COMPLEX-EXPR, BUG-DECIMAL-SUBSCRIPT-NOT-DECIMAL-EXPR,
BUG-UNKNOWN-INT-BINOP-FLOAT-EDGE, BUG-FV-BINOP-NO-DECIMAL-COMPLEX,
BUG-SUM-BARE-I64-OVER-HEAP-ELEMENTS and the comparison pair
BUG-DECIMAL-COMPLEX-COMPARE-BY-POINTER / BUG-FV-COMPARE-NO-DECIMAL-COMPLEX.
Plus one memory-safety bug, BUG-COMPLEX-REPR-FREES-HEADERED-STRING, which
`print([1 + 2j])` hit as soon as the element carried its real tag.

Pinned by `tests/regressions/list_literal_heap_numeric_elems.py`.

### ~~BUG-LIST-ELEM-TYPE-MISSES-HEAP-NUMERICS. A complex/Decimal/BigInt list element is read as a bare i64~~ — FIXED 2026-07-27

**What:** with the store side fixed, `c = [1 + 2j, 1j]; print(c[0])` still read
the element's *pointer* as an integer.

**Where:** `_infer_list_elem_type` (`compiler/codegen.py`) had arms for str,
float, bytes and so on but none for COMPLEX/DECIMAL/BIGINT, so all three fell
through to the INT default at the bottom. `_can_inline_list_access` then
answered "int" and the subscript became an inline i64 load, bypassing
`list_get_fv` and the tag it carries.

**FIXED 2026-07-27.** An arm consulting `_infer_type_tag(first)` for the three
kinds. None of them is inlineable, so merely *naming* the kind is what routes
the access through `list_get_fv` and preserves the tag — the same collapse onto
one inference that fixed the store side.

### ~~BUG-COMPLEX-SUBSCRIPT-NOT-COMPLEX-EXPR. `c[0] + c[1]` on a complex list prints a pointer~~ — FIXED 2026-07-27

**What:** `c = [1 + 2j, complex(0, 1)]; print(c[0] + c[1])` printed
`2716821164608`. Each element read on its own was correct; only the sum was
wrong.

**Where:** `_infer_type_tag` typed the Subscript COMPLEX and the binop
correctly dispatched to `_emit_complex_binop` — but the *BinOp* arm of
`_infer_type_tag` asks `_is_complex_expr`, not itself, and `_is_complex_expr`
had no `ast.Subscript` case. So the BinOp was typed INT and `print` rendered
the resulting `FpyComplex*` as an integer.

**FIXED 2026-07-27.** A non-Slice Subscript arm deferring to
`_infer_type_tag(node).kind == VKind.COMPLEX`, so there is one definition of
"what kind does this subscript yield". The recursion terminates because
`_infer_type_tag`'s Subscript arm only descends into `node.value`.

### ~~BUG-DECIMAL-SUBSCRIPT-NOT-DECIMAL-EXPR. `d < z[1]` compares a Decimal against a pointer~~ — FIXED 2026-07-27

**What:** the same hole one predicate over. `d = Decimal("1.5"); z =
[Decimal("1.5"), Decimal("2.5")]; print(d < z[1])` printed `False`.

**Where:** `_is_decimal_expr` recognised only a DECIMAL-kinded name and a
`Decimal(...)` call, so a container read was not a Decimal and the comparison
saw a Decimal on one side only.

**FIXED 2026-07-27.** The same non-Slice Subscript arm as `_is_complex_expr`.

### ~~BUG-UNKNOWN-INT-BINOP-FLOAT-EDGE. The third copy of the two-way binop split misreads a pointer as a double~~ — FIXED 2026-07-27

**What:** `[Decimal("1.5"), 1][0] + 1` printed `1.0`, and `* 2` printed
`2.1355557234974e-311`.

**Where:** the UNKNOWN⊗INT block of `_emit_binop_unknown` split on "both tags
== INT → integer, else → float via `bitcast(i64, double)`". That is correct
only for plain scalars: BIGINT, DECIMAL, COMPLEX, STR and LIST all keep a
*pointer* in the data slot, so the float edge read an address as a denormal
double. This is the third instance of the anti-pattern — see
BUG-BIGINT-FV-RESULT-NOT-CONSUMED for the other two.

The block did carry a BIGINT-only special case, but it was both narrower (one
tag out of the five that break the float edge) and gated on
`_program_uses_bigint` — a condition the *runtime* tag does not respect, since
a value can arrive BIGINT-tagged through a list or a call without the program
mentioning a big literal at all.

**FIXED 2026-07-27.** Same answer as the other two copies: guard the float edge
with `_fv_tag_is_plain_scalar` and give everything else a third edge to
`fastpy_fv_binop`, which subsumes the `_program_uses_bigint` special case.

### ~~BUG-FV-BINOP-NO-DECIMAL-COMPLEX. `fastpy_fv_binop` did arithmetic on Decimal and complex *pointers*~~ — FIXED 2026-07-27

**What:** exposed immediately by the fix above — the new generic edge landed in
`fastpy_fv_binop`, which had no Decimal or complex case at all and fell through
to the integer arithmetic at the bottom, returning the sum of two addresses.

**Where:** `fastpy_fv_binop` in `runtime/objects.c`.

**FIXED 2026-07-27.** Decimal and complex arms ahead of the "promote to float"
block, promoting INT/BOOL (and FLOAT, for complex) to the heap type, plus the
TypeError guard extended so a DECIMAL/COMPLEX operand that neither arm could
handle *stops* instead of falling into integer arithmetic on its pointer.

**Still open, deliberately:** only `+ - * /` are covered. `Decimal // int` and
`Decimal % int` now raise TypeError here rather than silently doing pointer
arithmetic — see BUG-DECIMAL-FLOORDIV-IS-TRUEDIV below for the related static
path, which is separately wrong.

### ~~BUG-COMPLEX-REPR-FREES-HEADERED-STRING. `print([1 + 2j])` aborts with heap corruption~~ — FIXED 2026-07-27

**What:** `print([1 + 2j])` died with STATUS_HEAP_CORRUPTION (0xc0000374)
before printing anything. `print(c[0])` was fine, because it never reached this
repr.

**Where:** the `FPY_TAG_COMPLEX` case of `fpy_value_repr` (`runtime/objects.c`)
called `free()` on `fpy_complex_to_str`'s result. Unlike its siblings
`fpy_bigint_to_str` / `fpy_decimal_to_str`, which hand back a bare `malloc`,
`fpy_complex_to_str` returns `fpy_str_buf`'s *header-backed* buffer, whose
`char*` points 8 bytes into the malloc block. Root-caused with `cdb`
(`RtlFreeHeap` ← `ucrtbase!free_base`) and A/B'd against HEAD to confirm it was
pre-existing.

**FIXED 2026-07-27.** `fpy_rc_decref(FPY_TAG_STR, …)` instead of `free()`, and
the ownership contract is now documented on the declaration in
`runtime/objects.h` so the next caller cannot make the same mistake.

**Severity:** memory corruption — the worst class in the tracker, and reachable
from a one-line program.

### ~~BUG-SUM-BARE-I64-OVER-HEAP-ELEMENTS. `sum()` adds pointers~~ — FIXED 2026-07-27

**What:** `print(sum([2 ** 80, 2 ** 80]))` printed `4413044692288` instead of
`2417851639229258349412352`.

**Where:** `_emit_builtin_sum` has exactly two accumulators, i64 and double,
and both read the element with `_list_get_as_bare(..., "int")`, which throws
the runtime tag away and keeps the raw i64. For a BigInt, Decimal or complex
that i64 is the value's address. FVALUE/MIXED elements had the same problem for
a different reason: nothing is statically known about them, so the bare read is
a guess that is wrong for every float element too.

**FIXED 2026-07-27.** A third accumulator keeping `(tag, data)` and folding
with `fastpy_fv_binop` — the one place that knows how to add every tag
combination, and which also raises the right TypeError for `sum(["a"])` instead
of silently adding two string pointers. It is selected only for element kinds
the bare read misreads (BIGINT, DECIMAL, COMPLEX, FVALUE, MIXED), so the plain
scalar loops are untouched.

### ~~BUG-DECIMAL-COMPLEX-COMPARE-BY-POINTER. `Decimal("1.5") < Decimal("2.5")` answers on heap address order~~ — FIXED 2026-07-27

**What:** non-deterministic comparison. The same binary printed `True False`
on one run and `False True` on the next:

```python
from decimal import Decimal
a = Decimal("1.5")
b = Decimal("2.5")
print(a < b, a > b)      # flips between runs
```

**Where:** `_emit_compare` has a BIGINT arm but none for DECIMAL or COMPLEX.
Two Decimals share a *kind*, so they also missed the cross-type `fv_compare`
branch — which requires the two kinds to *differ* — and fell all the way
through to the generic pointer/integer comparison at the bottom of the chain.
The answer was therefore whatever the allocator happened to do, which ASLR
varies per run.

**FIXED 2026-07-27.** A DECIMAL/COMPLEX arm routing to `fastpy_fv_compare` via
`_to_tag_data_ir`. It deliberately does not open-code the promotion the way the
BIGINT arm does: the runtime helper covers every partner tag (INT, BOOL, FLOAT)
in one place, and `_to_tag_data_ir` reaches the same `_infer_type_tag` the
container element paths use, so the tag stamped here and the tag a list stores
agree by construction.

**Severity:** non-deterministic wrong answers — the hardest kind to notice,
since a passing test proves nothing.

### ~~BUG-FV-COMPARE-NO-DECIMAL-COMPLEX. `fastpy_fv_compare` compared Decimal and complex pointers~~ — FIXED 2026-07-27

**What:** the runtime half of the bug above. `fastpy_fv_compare` had STR and
BIGINT arms but nothing for DECIMAL or COMPLEX, so both fell into the
"integer/bool comparison (default)" at the bottom and compared addresses.

**Where:** `fastpy_fv_compare` and `_fpy_tags_order_compatible` in
`runtime/objects.c`.

**FIXED 2026-07-27.** Decimal and complex arms ahead of the FLOAT and default
branches, plus `_fpy_tags_order_compatible` taught that DECIMAL and COMPLEX are
comparable with INT/BOOL/FLOAT. Complex is equality-only: ordering raises
TypeError exactly as CPython does — including *complex vs complex*, which the
`tag1 == tag2` shortcut at the top of the function used to wave straight
through.

### ~~BUG-CALL-ON-CALL-STALE-ARG-TAG. `C()(x)` let the callee read the *previous* call's argument tag~~ — FIXED 2026-07-27

**What:** a callee whose parameter is UNKNOWN gets only a bare `i64` and
recovers the type from the `fastpy_{set,get}_arg_tag` side-channel. That
channel is global and sticky — it keeps whatever the last call site wrote.
`_emit_call_on_call` wrote nothing, so `__call__`'s parameter inherited the tag
of some unrelated earlier argument.

**Reproduce:** `tests/regressions/call_on_call_arg_tag.py`. Minimal form — a
str argument anywhere earlier poisons slot 0, then `Doubler()(7)` runs `x * 2`
with `x` tagged STR:

```python
class Greeter:
    def __init__(self, name): self.name = name
    def __call__(self): return "Hello " + self.name
print(Greeter("World")())

class Doubler:
    def __call__(self, x): return x * 2
print(Doubler()(7))          # → strlen((char *)7) → segfault
```

**Where:** `_emit_call_on_call` in `compiler/codegen.py`; every arm
(`call_ptr1`, `call_ptr2`, `obj_call_method1`) had the same hole.

**FIXED 2026-07-27.** One shared `_emit_set_arg_tags` helper, used by all of
them and by the direct-dispatch `__call__` path that previously open-coded it.

**History:** latent until the UNKNOWN⊗INT binop grew its generic
`fastpy_fv_binop` edge (BUG-UNKNOWN-INT-BINOP-FLOAT-EDGE). Before that a STR
tag fell down the float edge and produced a *silently wrong number*; afterwards
it reached the runtime's genuine string arms and dereferenced the integer. The
crash was the fix doing its job — the wrong tag was always there.

### ~~BUG-CALL-ON-CALL-IGNORES-RET-TAG. `Echo()("xyz")` printed the string's address~~ — FIXED 2026-07-27

**What:** `fastpy_obj_call_methodN` and `fastpy_call_ptrN` return a bare `i64`;
`_emit_call_on_call` wrapped it with a hard-coded INT tag. Any `__call__` (or
call-on-call closure) returning a str / float / bool / list / tuple therefore
printed as an integer.

**Where:** `_emit_call_on_call` in `compiler/codegen.py`.

**FIXED 2026-07-27.** `_wrap_with_ret_tag` reads `fastpy_get_ret_tag()` and
rebuilds the FpyValue. Applied only where the callee provably publishes a tag —
`fastpy.class.*` methods (every `return <expr>` path calls `set_ret_tag`, see
`_needs_ret_tag` in `_emit_return`) and `fastpy.closure.*` bodies — because the
ret-tag channel is as sticky as the arg-tag one; see
`_recover_closure_ret_tag`'s doctrine.

### ~~BUG-CALL-ON-CALL-2ARG-OBJ-RETURNS-ZERO. `Pair()(3, 4)` silently produced 0~~ — FIXED 2026-07-27

**What:** the object arm of `_emit_call_on_call` handled 0 and 1 arguments and
fell off the end returning `None` for 2+, so `C()(a, b)` produced `0` with no
diagnostic.

**Where:** `_emit_call_on_call` in `compiler/codegen.py`.

**FIXED 2026-07-27.** When the inner call is a constructor of a known user
class the callee is statically resolvable, so the new
`_emit_direct_dunder_call` calls `__call__` directly instead of going through
the runtime's name-based dispatcher. That removes the arity ceiling, coerces
arguments to the callee's real signature, and recovers the return tag — the
same helper the `f = F(); f(x)` path now uses, so the two shapes can no longer
drift apart. The dispatcher path remains as the fallback for objects whose
class is not known at the call site, and still tops out at two arguments.

### ~~BUG-STR-HEADER-PROBES-BEFORE-RUNTIME-STATIC-BUFFERS. Increfing an exception message reads out of bounds~~ — FIXED 2026-07-27

**What:** `fpy_str_header(s)` decides whether a `char*` is refcounted by reading
the magic at `s - offsetof(FpyString, data)`. That probe is only *defined* when
`s` really points into an `FpyString`. Compiler-emitted literals are fine — the
`.str.N` globals are laid out as `{i32 magic, i32 refcount, [N x i8]}` with an
immortal refcount, precisely so the probe lands inside them. The C runtime's
static message buffers are not: `_err_buf`, `fastpy_fv_compare`'s `_cmp_err`
and `_cx_err`, and their siblings are bare `char[256]` globals, so the probe
reads the 8 bytes *before* the array.

**Reproduce:** any runtime-raised exception bound with `as e`, under
`tools/pure_harness.py`:

```python
try:
    x = 1 / 0
except ZeroDivisionError as e:
    print("caught:", e)
```

ASan: `global-buffer-overflow ... READ of size 4 ... in fpy_str_header`, from
`fpy_rc_incref` on the message string. Present at HEAD, so it long predates the
Decimal/complex work that surfaced it.

**Where:** `fpy_str_header` in `runtime/objects.h`; `fastpy_raise` in
`runtime/runtime.c`, which stores the caller's `const char *msg` into
`fpy_exc_msg` verbatim.

**Proper fix:** copy the message inside `fastpy_raise` into a single
thread-local *header-backed* buffer (`FpyString`-shaped, `magic =
FPY_STR_MAGIC`, `refcount = FPY_RC_IMMORTAL`) and point `fpy_exc_msg` at its
`.data`. That preserves today's semantics exactly — the message already lives
only until the next raise, since most producers share `_err_buf` — while making
the header probe well-defined for every producer at once. Fixing the producers
instead does not scale: of the ~89 `fastpy_raise` call sites only three use a
static buffer; the rest pass plain C string literals, which are just as
headerless. Do **not** "fix" it by weakening `fpy_str_header` — the probe is
load-bearing and a laxer test would misclassify real strings.

**Severity:** benign on real hardware (an in-bounds-of-the-image read that
almost never matches the magic), but it is genuine UB and it aborts every
ASan run that raises an exception, which blocks the harness from vetting
anything downstream of a `raise`.

**Fixed** by `fpy_exc_msg_store` in `runtime/runtime.c`: `fastpy_raise` and
`fastpy_raise_with_obj` now copy the message into one immortal, header-backed
thread-local buffer (with a heap overflow buffer for messages past 512 bytes)
and publish *that* as `fpy_exc_msg`. Lifetime is unchanged — valid until the
next raise on the thread, exactly what the shared `_err_buf` already gave. The
`__exc_msg__` attribute set by `raise_with_obj` deliberately keeps the
caller's pointer instead, since it has to outlive the next raise and codegen
only reaches it with a compiler-emitted (header-backed, immortal) literal.
Regression test `tests/regressions/exc_msg_header_backed.py`; verified by A/B
under `tools/pure_harness.py` (ASan aborts without the change, clean with it).
This also unblocked `list_literal_heap_numeric_elems.py` under the harness.

### ~~BUG-MODULO-BY-ZERO-MESSAGE-WORDING. `1 % 0` reports a different message than CPython~~ — FIXED 2026-07-27

**What:** fastpy raises `ZeroDivisionError: integer modulo by zero`; CPython
3.14 says `division by zero` for `%` just as it does for `/` and `//`. (The
older wording matches CPython ≤3.11, so this is a version drift, not a typo.)

**Reproduce:**

```python
try:
    1 % 0
except ZeroDivisionError as e:
    print(e)      # fastpy: integer modulo by zero;  CPython 3.14: division by zero
```

**Where:** the `fastpy_raise(FPY_EXC_ZERODIVISION, "integer modulo by zero")`
call in `runtime/runtime.c` (around the int-modulo helper).

**Proper fix:** change the literal to `"division by zero"`, then check the
sibling messages for the same drift against 3.14 rather than fixing this one
in isolation. Cheap, but it needs the message audit to be worth doing once.

**Severity:** cosmetic, but it makes any test that prints a caught modulo
message diverge from CPython — `tests/regressions/exc_msg_header_backed.py`
has to compare only the length because of it.

**Fixed:** the audit found three sites, not one. `fastpy_safe_mod` in
`runtime/runtime.c` said "integer modulo by zero", `fpy_complex_div` in
`runtime/objects.c` named the operand type, and `fpy_bigint_floordiv` in
`runtime/bigint.c` did not raise at all — it printed and called `exit(1)`,
which made `(2 ** 80) // 0` the one division by zero in the language a `try`
could not catch. All three now say `division by zero`, and the bigint one
raises like its siblings and returns zero (callers there don't check for
NULL, and the pending flag stops the program at the next check anyway).
Verified against CPython 3.14.6 that `/`, `//`, `%` and `divmod` agree on
that wording for int, float, bigint and complex; only `0 ** -1` differs
("zero to a negative power"), and that one already matched.

Making bigint.c able to raise meant giving it the `FPY_EXC_*` codes, which
had been re-`#define`d per file — runtime.c had a copy and objects.c had one
labelled "mirror runtime.c". Rather than add a third, the codes moved to a
new `runtime/exceptions.h` that all three include. That in turn exposed a
build bug: `_obj_is_current` in `compiler/toolchain.py` compared each runtime
`.c` against its `.obj` and ignored headers entirely, so a header-only edit
silently kept a stale `.obj` and appeared to have no effect. It now also
requires the `.obj` to be newer than the newest `.h` in the runtime
directory.

### ~~BUG-KEYERROR-STR-NOT-REPR. `str(KeyError)` doesn't quote the key~~ — FIXED 2026-07-27

**What:** CPython's `KeyError.__str__` is the *repr* of the missing key, so a
string key prints quoted. fastpy stores the bare key text as the message.

**Reproduce:**

```python
try:
    {"a": 1}["missing"]
except KeyError as e:
    print(e)      # fastpy: missing;  CPython: 'missing'
```

**Proper fix:** the dict-lookup raise site should format the key with the
runtime's repr routine rather than its str routine — the same distinction
already exists for printing a string inside a container, so it is a matter of
calling the existing repr path. Note this is only `KeyError`; every other
builtin exception's `str` really is the plain message.

**Severity:** cosmetic, same caveat as above — the regression test can't
compare the text.

**Fixed:** the runtime had fourteen `FPY_EXC_KEYERROR` raise sites giving
three different answers to one question — the raw key text, a bare
`"KeyError"`, and a hand-`snprintf`'d integer. They now all go through one
`fpy_raise_key_error(FpyValue)` in `runtime/objects.c`, which reprs the key
via the existing `fpy_value_repr`, so the type decides the quoting (`'a'` vs
`5`) instead of the call site. The message-shaped ones are covered by the
same helper rather than special-cased: `set().pop()` raises
`KeyError('pop from an empty set')` and CPython quotes that string like any
other argument.

`raise KeyError(x)` in user code needed the same treatment on the compiler
side, since fastpy stores only the rendered message and never an args tuple —
the raise is the last point where the argument's type is known.
`_exc_arg_to_message` in `compiler/codegen.py` applies the repr for KeyError
only, and only when the argument's type is unambiguous; anything the front
end can't type falls through to `str()`, which is what it did before, so an
un-inferable case is no worse rather than newly wrong. Getting `"fmt-%d" % n`
into that set meant teaching `_infer_expr_kind` that `str % x` and `str + x`
are strings, which every other consumer of that helper benefits from too.

Regression test `tests/regressions/keyerror_str_is_repr.py` covers subscript,
`pop`, `del`, the empty-set/empty-dict messages, and user raises with a
literal, a variable, an int, a `%`-format and an f-string.

### BUG-REPR-ALWAYS-SINGLE-QUOTES. `repr("it's")` escapes instead of switching quote character — 2026-07-27

**What:** CPython *picks* the quote when it reprs a string: one containing
`'` but no `"` is wrapped in double quotes, so `repr("it's")` is `"it's"`, not
`'it\'s'`. Only when both appear does the single quote get a backslash.
fastpy always used single quotes and always escaped.

**Reproduce:**

```python
print(repr("a'b"))      # fastpy: 'a\'b'   CPython: "a'b"
print(["it's"])         # fastpy: ['it\'s'] CPython: ["it's"]
```

**Where:** `runtime/objects.c` had *two* independent repr routines —
`fpy_value_repr`'s `FPY_TAG_STR` case (the container path) and
`fastpy_str_repr` (what `repr()` itself calls). Both hardcoded the quote, and
they also disagreed with each other about control characters: the first
emitted `\xNN`, the second passed the raw byte straight through.

**Fixed 2026-07-27:** both now share `fpy_repr_quote` (which quote CPython
would use) and `fpy_repr_escape_body` (the escaping), so there is one answer
to what a repr'd string looks like. The `FPY_TAG_BYTES` case follows the same
quote rule with its own escaping, since a byte ≥ 127 has no character to
print and stays `\xNN`. `fastpy_str_repr`'s buffer also had to grow from
`len*2+2` to `len*4+2`, which the `\xNN` form it previously never emitted now
needs. Regression test `tests/regressions/repr_quote_choice.py` covers str,
bytes, and the container path for each.

### ~~BUG-EXC-MSG-BUFFER-ALIASES-ACROSS-RAISES. `str(e)` returns a borrowed pointer into a buffer the next raise overwrites~~ — FIXED 2026-07-27

**Fixed:** as the entry required, in one change across both halves.
`fpy_exc_msg_store` in `runtime/runtime.c` now publishes a fresh refcounted
`FpyString` per raise and drops the previous one (also on `fastpy_exc_clear`),
reusing the buffer in place only while the exception slot is its sole owner
(`refcount == 1`), so back-to-back raises with nobody holding on still cost no
allocation. The compiler half is `_retain_exc_msg_slot`, which gives the
`saved.exc.msg` slot behind a bare `raise` a real reference by routing it
through `_retain_native_store` — that brings the entry-block zero-init, the
release of the previous iteration's message when a `try` runs in a loop, and
the release at function exit. The `as e` binding already increfed through
`_store_variable`. `fastpy_raise_with_obj` also switched to storing the
published copy on `__exc_msg__` rather than the caller's pointer, since the
copy is refcounted and `fastpy_obj_set_fv` increfs, so the attribute keeps
itself alive. Two neighbouring bugs surfaced while testing it —
BUG-BARE-RAISE-TAKES-INNERMOST-HANDLER and BUG-RAISE-MESSAGE-TEMP-LEAKS —
both fixed in the same change. Covered by
`tests/regressions/exc_msg_alias_across_raises.py`.

**What:** the exception message lives in one reused, thread-local,
*immortal* header-backed buffer (see BUG-STR-HEADER-PROBES-BEFORE-RUNTIME-
STATIC-BUFFERS above). `str(e)` hands back a pointer into it. Because the
buffer is immortal, increfing it is a no-op, so storing the result keeps a
pointer to storage the *next* raise rewrites — every stored message ends up
reading as the most recent one.

**Reproduce:**

```python
seen = []
for d in [0, 1, 2]:
    try:
        raise ValueError("v%d" % d)
    except ValueError as e:
        seen.append(str(e))
print(seen)     # fastpy: ['v2', 'v2', 'v2']   CPython: ['v0', 'v1', 'v2']
```

Concatenating (`seen.append("" + str(e))`) copies and gives the right answer,
which is why this went unnoticed — the existing tests all happened to
concatenate.

**Where:** `fpy_exc_msg_store` / `fpy_exc_msg_inline` / `fpy_exc_msg_big` in
`runtime/runtime.c` (~line 700), published via `fpy_exc_msg`.

**Proper fix:** make each raise publish a *fresh, owned* header-backed string
(refcount 1) instead of rewriting a shared immortal one, and release the
previous one when a new raise replaces it. Then a normal incref really does
extend the lifetime and the aliasing disappears.

This cannot be done in the runtime alone. Today the immortal buffer is
memory-*safe* and only gives a wrong value; a mortal one introduces a
use-after-free unless the handler's binding of `e` takes a reference. So the
fix has to land together with an incref where codegen saves the message at
`except ... as e` (`_saved_exc_msg` in `compiler/codegen.py`) — otherwise a
raise *inside* a handler would free the message the handler still holds.
Trading a wrong value for a UAF would be a regression, so the two halves must
go in as one change.

**Severity:** silent wrong output. Any program that collects exception
messages in a list or dict gets N copies of the last one.

### ~~BUG-BARE-RAISE-TAKES-INNERMOST-HANDLER. A nested `try` inside a handler steals the enclosing handler's bare `raise`~~ — FIXED 2026-07-27

**Fixed:** `_push_saved_exc_slots` / `_pop_saved_exc_slots` in
`compiler/codegen.py` save and restore `_saved_exc_type/_msg/_class` around
`_emit_try` and `_emit_try_star`.

**What:** those three attributes name the allocas a bare `raise` re-raises
from. Every try statement overwrote them while emitting its handlers and never
restored them, so after a nested try finished emitting, the outer handler's
`raise` read the *inner* try's saved exception.

**Reproduce:**

```python
try:
    raise ValueError("outer message")
except ValueError:
    try:
        raise KeyError("inner")
    except KeyError:
        pass
    raise            # fastpy re-raised KeyError('inner')
```

**Where:** `_emit_try` (~line 26830) and `_emit_try_star` (~line 26071) in
`compiler/codegen.py`; read by `_emit_raise`'s `node.exc is None` branch.

Emission order makes the nested try's *body* correct without further work: the
body is emitted before the handlers, so a bare `raise` there still sees the
enclosing handler's slots — which is also what Python does, since that body
runs inside the outer handler.

**Severity:** was wrong control flow — the wrong exception type propagated out
of a handler, so an outer `except` could catch a class that was never raised
there.

### ~~BUG-RAISE-MESSAGE-TEMP-LEAKS. A computed exception message is never released~~ — FIXED 2026-07-27

**Fixed:** `_emit_raise` takes an `_rc_temps` watermark before evaluating the
exception's arguments and calls `_flush_rc_temps_to` immediately after the
`fastpy_raise` call, while the block is still unterminated.

**What:** the statement-boundary flush is emitted in the *no-exception*
continuation block (see `_emit_try`'s body loop and `_emit_stmts`), which a
`raise` never reaches, so every temp built for the message leaked. Releasing at
the raise is safe only because `fastpy_raise` copies the message into the
exception slot's own refcounted string — which was not true before
BUG-STR-HEADER-PROBES-BEFORE-RUNTIME-STATIC-BUFFERS, and is the reason the old
comment in `_emit_assert` claimed the leak was *required*.

**Reproduce** — peak working set, not output:

```python
total = 0
for i in range(500000):
    try:
        raise ValueError("m" * (i % 700))
    except ValueError as e:
        total += len(str(e))
```

189 MB before, 13 MB after.

**Where:** `_emit_raise` in `compiler/codegen.py`.

**Severity:** unbounded memory growth in any loop that raises with a computed
message. Invisible to the test suite, which compares output only.

### ~~BUG-STR-REPEAT-RESULT-LEAKS. `s * n` never releases the string it allocates~~ — FIXED 2026-07-27

**Fixed:** `_owned_str_repeat` in `compiler/codegen.py` registers the result as
a Model-2 owned temp, mirroring `_owned_str_concat`; the three `str_repeat`
call sites (both `_emit_binop` orders and the `*=` augmented assignment) go
through it.

**What:** `fastpy_str_repeat` always allocates — even `s * 0` returns a fresh
empty buffer — but its result was the one statically-typed string producer
nobody registered, so the `+1` was never released. A consumer that stored it
increfed to 2 and dropped back to 1, never 0.

**Reproduce** — peak working set, not output:

```python
for i in range(500000):
    s = "m" * 350
```

187 MB before, 13 MB after.

**Where:** `compiler/codegen.py`, `_emit_binop`'s STR×INT fast paths and
`_emit_augassign`'s `STR *=` branch.

**Severity:** unbounded memory growth for any repeated string built in a loop —
padding, separators, test fixtures. Found while measuring
BUG-RAISE-MESSAGE-TEMP-LEAKS; the two are independent.

### BUG-STR-EMBEDDED-NUL-TRUNCATES. A `str` containing `\x00` is cut at the null — 2026-07-27

**What:** fastpy's `str` is a NUL-terminated C string, so `"\x00\x1f"` is
length 0 and reprs as `''`. CPython's `str` carries an explicit length and
round-trips the null.

**Reproduce:**

```python
s = "\x00abc"
print(len(s), repr(s))   # fastpy: 0 '';   CPython: 4 '\x00abc'
```

**Where:** the representation itself — `FpyString` stores `char data[]` and
every str helper is `strlen`-based. Note `bytes` does *not* have this
problem: `FpyBytes` keeps a length field and `fpy_bytes_len` uses it, which
is why `repr(b"\x00\xff")` is already correct (see BUG-BYTES-EMBEDDED-NULL
work above).

**Proper fix:** give `FpyString` the explicit length field `FpyBytes` already
has and move the str helpers off `strlen`, the same migration the bytes side
already went through. That is a large, mechanical change across every str
producer and consumer.

**Severity:** low in practice — embedded nulls in text are rare — but it is a
silent truncation, not an error. Noted here because
`tests/regressions/repr_quote_choice.py` has to skip the `\x00` case for it.

### ~~BUG-SUITE-DEFAULT-TIMEOUT-FLAKES-UNDER-LOAD. Regression tests spuriously fail on a busy machine~~ — FIXED 2026-07-27

**What:** `tests/conftest.py` gave every collected regression/program file a
fixed `timeout = 10.0` seconds covering the run and the CPython reference
run. On an otherwise-busy machine that was not enough headroom for the slower
files, and the test reported a failure rather than a timeout.

**Reproduce:** run `pytest tests/ -q` while a large native build is running.
Observed twice. First: `list_literal_heap_numeric_elems` failed in a full run
that took 627 s, then passed standalone in 1.77 s and passed again in a quiet
full run (1009 passed, 741 s). Then, on the run that prompted this fix,
`int_float_of_tagged_value` failed in two consecutive full runs
(1 failed / 1016 passed, 593 s) while passing standalone in 1 s, passing in
`pytest tests/regressions -q` (334 passed), and finally passing in a third
full run (1017 passed, 570 s) with nothing changed. Neither failure output
identified a timeout, which is what made both expensive to diagnose.

**Where:** the `timeout` defaults in the `assert_compiles` /
`assert_file_compiles` fixtures in `tests/conftest.py`, and `diff_test` /
`diff_test_file` / `run_cpython` / `run_executable` in `tests/harness.py`.

**Fixed:** both halves of the proper fix.

1. The budget is now one shared `DEFAULT_TIMEOUT = 30.0` in
   `tests/harness.py`, which `conftest.py`'s two fixtures import rather than
   restating. The slowest legitimate file runs in ~2 s, so this is a 15×
   margin instead of a 5× one, and it still bounds a genuine hang. The
   headroom costs nothing on a green run because nothing waits on it.
2. A timeout reports itself. `diff_test` checks `compiled_result.timed_out`
   *before* the generic output diff and fails with `compiled program timed
   out after 30s (CPython finished the same program in 0.04s)`. Previously a
   killed process fell through to the diff, which described it as `stdout
   differs; exit code: CPython=0, Compiled=-1` — indistinguishable from a
   real miscompilation. `DiffResult.detail()` also stops dumping the
   empty-vs-expected stdout pair in that case, since the summary line is the
   whole story.

`RunResult` grew a `duration` field for the same reason: on the next
occurrence it separates "this hung" (normally 0.1 s, burned the whole
budget) from "this was merely slow" (took 29.9 s of 30 s).

Note the asymmetry that stays: a *CPython* timeout is still a SKIP, not a
FAIL — a reference run that won't finish means the test can't be judged.
Only the compiled binary timing out is a failure.

**Severity:** was no product impact, but a suite that fails randomly under
load trains you to re-run rather than investigate, which is how a real
regression gets waved through.

### BUG-DECIMAL-FLOAT-COMPARE-INEXACT. Comparing a Decimal against a float rounds the Decimal — 2026-07-27

**What:** `fastpy_fv_compare`'s new Decimal arm converts the Decimal to a
double when the other operand is a FLOAT. CPython does the opposite — it
converts the *float* to a Decimal, so the comparison is exact.

**Reproduce:** needs a Decimal past 2^53 or a decimal fraction no double
represents; e.g. `Decimal("0.1") == 0.1` is False in CPython (0.1 is not
exactly one tenth) and may come out True here.

**Where:** `_fpy_decimal_to_double` in `runtime/objects.c`, used by the DECIMAL
arm of `fastpy_fv_compare`.

**Proper fix:** a float→Decimal constructor in the runtime — exact, since every
finite double *is* a terminating decimal — then compare with
`fpy_decimal_compare` like every other partner tag. The same helper would let
`fastpy_fv_binop`'s Decimal arm accept a float operand, which it currently
rejects.

**Severity:** wrong answers only at the edges; the common `Decimal("1.5") ==
1.5` shape is right.

### BUG-DECIMAL-FLOORDIV-IS-TRUEDIV. `Decimal(...) // n` does true division — 2026-07-27

**What:** `Decimal("2.5") // 2` gives `1.25`, not `1`.

**Where:** the Decimal fast path in the static binop emitter
(`compiler/codegen.py`) maps `ast.FloorDiv` to the `decimal_div` runtime entry
point — the same one `ast.Div` maps to. `ast.Mod` has no mapping at all.

**Proper fix:** `fpy_decimal_floordiv` and `fpy_decimal_mod` in the runtime
(floor semantics, matching CPython's `Decimal.__floordiv__`, which truncates
toward zero — note that differs from `int //`), wired into both the static path
and `fastpy_fv_binop`'s Decimal arm, which currently raises TypeError for these
two ops rather than doing pointer arithmetic.

**Severity:** silently wrong values.

### ~~BUG-BOOL-PLUS-INT-YIELDS-FLOAT. Adding two tagged values takes the float edge unless *both* are INT~~ — FIXED 2026-07-27

**What:** `True + 3` on two runtime-tagged values gives `4.0`, not `4`. The value
is right; only its type is wrong, so it prints with a spurious `.0` and infects
everything downstream.

**It was worse than "only its type".** Filing it as a cosmetic tag bug
understated it — the float edge is the wrong edge for a bool, not just a
badly-labelled one:

- `True % 2` printed **`5e-324`**. `_emit_float_binop` handed back the integer
  result `1` as an i64, the float edge tagged it FLOAT unconditionally, and the
  payload `0x1` was read as a denormal double.
- `True << 2` **raised** `TypeError: unsupported operand type(s) for <<:
  'float' and 'float'` — a float has no shift, so an operator CPython answers
  `4` for aborted the program.
- `True // 1` printed `0.0` where CPython says `1`.

**Reproduce** — should print `4 4.5`:
```python
m = [3, 4.5, True]
print(m[2] + m[0], m[2] * m[1])   # prints "4.0 4.5"
```

**Where:** the inlined fast paths in `_emit_binop_unknown` (`compiler/codegen.py`)
split on `both tags == INT`, and everything that is not that pair goes down the
float edge. BOOL is a perfectly good integer — CPython's `bool` is a subclass of
`int`, and `True + 3` is `4` — but it fails the `both == INT` test, so it is
converted with `sitofp` and comes back a double.

Note this is *not* the same hole as BUG-BIGINT-FV-RESULT-NOT-CONSUMED, which was
about non-scalar tags reaching the float edge and having a *pointer* bitcast to a
double. That one is fixed: the float edge is now guarded by a real "both operands
are plain scalars" check, and BOOL genuinely is a plain scalar, so it still takes
it.

**Fixed:** the integer test was widened from "both INT" to "both INT-or-BOOL"
via a new `_fv_tag_is_integral` helper in `compiler/codegen.py`, applied to
**three** inlined splits, not the two the original note predicted:

1. `_n_both_int` — the Add-specific `unkn.num_*` split.
2. `_is_int` — the UNKNOWN-op-static-INT split (`unkn_int.*`). This is the one
   `True % 2` took, and the one the original note missed.
3. `_both_int` — the general `_uu` split.

`True / 2` is undisturbed because the *integer* edge already returns a double
for `Div`: `_emit_int_binop` handles that, and the surrounding code tags the
result FLOAT when the result type is a double. Nothing had to special-case it.

Two adjacent defects surfaced while testing and are fixed with it:

- **`&`, `|`, `^` of two bools must stay a bool.** `True & False` is `False`
  in CPython, not `0`, while the shifts and any mixed bool/int pair widen to
  int (`True << 1` is `2`, `True | 3` is `3`). Both edges needed it: the
  inlined one via `_fv_int_result_tag` (a `select` on "both tags BOOL at
  runtime"), and the runtime's `fastpy_fv_binop` bitwise block in
  `runtime/objects.c`, which tagged every result INT.
- **`+True` is `1`, not `True`.** Unary `+` was emitted as a pure identity, so
  it handed the BOOL tag straight back. It now retags BOOL→INT (and only
  BOOL) when its operand is an `FpyValue`.

**Test:** `tests/regressions/bool_is_an_int_in_tagged_arithmetic.py`.

**Severity:** was silently wrong *type* for `+`/`-`/`*`, a silently wrong
*value* for `%` and `//`, and a hard `TypeError` for `<<`/`>>`.

### ~~BUG-BIGINT-RETURNED-FROM-FUNCTION-LOSES-TAG. A BigInt returned through a call comes back as a number~~ — FIXED 2026-07-27

**What:** a function that returns a BigInt hands the caller the *pointer* with a
plain integer tag. Arithmetic on it then operates on the address.

**Reproduce** — should print `0`:
```python
b = 2 ** 80

def neg(x):
    return -x

print(neg(b) + b)          # prints e.g. 1208925819617242555011456
```
The number printed is `2**80` plus a heap address, which is exactly what you get
by adding a pointer to a BigInt. It varies run to run.

**Where — not the return path, the *bare call expression* path.** The title
above is how it looked from outside; the actual split is finer, and worth
recording because it is the same one as BUG-DIRECT-CALL-LEN-STATIC-TAG:

```python
v = f(b); print(v + 0)     # always correct
print(f(b) + 0)            # wrong
```

Storing to a name first consults `_assign_fv_fast_path`, which was right all
along. Only a call consumed *in place* went through `_emit_user_call`'s
`_callee_returns_mixed` check and got unwrapped by a static claim. Passing a
tagged value as an *argument* was likewise fine throughout.

Three holes in how the return is typed, all in `_duf_infer_ret_tag`:

1. **`return <param>` where the param is a BigInt** has an i8_ptr LLVM return
   type, and that branch's default is `ret_tag = "ptr"` — which
   `from_old_tag` maps to `VKind.LIST`. Hence the error message
   `unsupported operand type(s) for +: 'list' and 'int'`. The i64 branch has
   had a `returns_untyped_param -> "mixed"` arm since
   BUG-RETURNS-UNTYPED-PARAM-RET-TAG; the pointer branch never grew one.
   Guessing *list* for an unrecognised pointer is the worst available default
   because every pointer fits it. The param pass-through chain also had arms
   for STR/DICT/LIST/BYTES/SET but none for BIGINT/DECIMAL/COMPLEX, so those
   set no flag at all and fell into that default.
2. **`return -x` and `return x * 2`** were typed `int`/i64 — the right *width*
   but the wrong claim, since in a program that can promote, those operators
   go through `fpy_checked_*` and may yield a BIGINT-tagged FpyValue.
3. **The ABI has to agree.** Saying `"mixed"` is only half the answer: `acc`
   below came out `ret_tag=mixed` but `uses_fv_abi=False`, so there was still
   nowhere to put the tag. `_duf_select_abi` needed the same denial it already
   applies for BUG-MIXED-SCALAR-RETURN-TAG.

**Severity:** silently wrong values that depend on the heap address, so they are
nondeterministic across runs. Only reachable in programs that use big integers.

**FIXED 2026-07-27.** Regression test
`tests/regressions/bigint_returned_from_function.py`, also clean under
ASan/UBSan/LSan.

New `_returns_may_be_bigint(node)` answers hole 2 and 3. It is the return-side
counterpart of the widening clause in `_scan_fv_forced_locals` and deliberately
shares its shape: the same operator set (`_BIGINT_CAPABLE_OPS` — Add, Sub, Mult,
Pow, LShift, the ones `_emit_int_binop` routes through `fpy_checked_*`), the
same `_is_constant_arith` exemption, and the same over-approximating bias, since
a wide return slot is cheap and a pointer read as a number is not. Names are
resolved by a small fixpoint because `r = r * k` refers to itself. Unary minus
is treated as "the operand might already be big" rather than recursing, since
the reported repro is `-x` on a bare parameter. It is wired into both the i64
ret_tag branch and `_duf_select_abi`'s `uses_bare` conjunction. Hole 1 is
answered by giving the i8_ptr branch the missing `mixed` arm.

**A false start worth keeping:** naming the kind statically (`ret_tag =
"bigint"`) only moved the error, from claiming 'list' to claiming 'str'. A bare
call expression's kind is guessed from `static_ret_type`, and i8* covers BigInt,
Decimal and str alike. Committing to a static kind would need a matching arm in
every consumer — which is exactly the fragility that produced this bug family.
`"mixed"` keeps the runtime tag and rides `fastpy_fv_binop` /
`fastpy_fv_compare`, which BUG-BIGINT-FV-RESULT-NOT-CONSUMED had just taught to
read BigInt correctly. That fix is what made `"mixed"` a viable answer here.

### ~~BUG-CALL-ARG-TYPE-GUESSES-FLOAT-FROM-ARGS. A call is typed float because a float literal was passed *into* it~~ — FIXED 2026-07-27

**What:** `_infer_call_arg_type` answers "what kind does this argument
expression produce", so the right specialization of the receiving function is
chosen. For a call it consulted the callee's `ret_tag` and named four kinds —
float, int, bool, str — and then **fell through** to a last-resort heuristic:

```python
has_float = any(isinstance(sub, ast.Constant) and isinstance(sub.value, float)
                for sub in ast.walk(node))
if has_float:
    return "float"
```

On a Call node that `ast.walk` reaches the *arguments*. So `bisect_right(a, 1.5)`
was typed float purely because `1.5` appears inside it, even though the function
returns an index.

**Repro** (needs a BigInt somewhere in the program, so the callee's `ret_tag`
becomes `"mixed"` and the fall-through is reached):

```python
big = 2 ** 80
def idx(a, x):
    lo = 0; hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < a[mid]: hi = mid
        else: lo = mid + 1
    return lo
def show(actual, expected):
    print(actual, type(actual), actual == expected)
show(idx([1, 2], 1.5), 1)     # printed `1.0 <class 'float'>`
```

**Where:** `_infer_call_arg_type`, the `ast.Call`/`ast.Name` branch.

**How it stayed hidden:** while every such function returned a bare i64 its
`ret_tag` was `"int"`, which the line above answers, so the fall-through was
unreachable. BUG-BIGINT-RETURNED-FROM-FUNCTION-LOSES-TAG made BigInt-capable
functions return `"mixed"` and opened it — 14 of `test_bisect`'s 2857
assertions began failing, all of them the float-`x` call sites, each printing
the memorable `FAIL: got 1 expected 1`.

**Severity:** wrong *type* (and, through the specialization it selects, wrong
values) on any program mixing int and float arguments to the same function.

**FIXED 2026-07-27.** The callee's own `ret_tag` is authoritative: a kind the
table has no name for — `"mixed"` above all, but also a container or void —
returns `None`, which the specialization scorer already treats as "no evidence".
Regression test `tests/regressions/call_result_arg_kind.py`.

### ~~BUG-RET-TYPE-FLOAT-FROM-CALL-ARGS. A function's return type is float because a float parameter appears inside a call~~ — FIXED 2026-07-27

**What:** the same shape one level up. `_duf_detect_ret_type` decides a
function's LLVM return type partly by walking each return expression for a float
constant or a float-typed parameter. That walk also descends into calls:

```python
def pick(a, x, k):
    return idx(a, x) + k       # typed `double` in the variant where x is float
```

`idx` returns an index; `x` merely rides through as an argument. Typing `pick`
`double` made its FpyValue return unwrapped with a raw `bitcast`, so
`pick([1, 2, 3], 2.5, 0)` printed `1e-323` — the integer 2 reinterpreted as a
denormal.

**Where:** `_duf_detect_ret_type`, both the `float_vars` scan and the
`returns_float` scan.

**Severity:** silently wrong values, and of the worst kind — a bit pattern
printed as a number.

**FIXED 2026-07-27.** New `_walk_for_float_evidence` replaces `ast.walk` in both
scans. It skips a call whose callee already commits to a non-float result: an
always-integer builtin (`int`, `len`, `ord`, `hash`, `id`, `round`), or a user
function *every* declared specialization of which has a non-float `ret_tag`.
Checking every variant is what makes it safe — in a chain like
`A(x) -> B(x) + 1` where `B` has both an int and a float variant, only the
caller's own float parameter says which is reached, so `A` must keep taking that
parameter as evidence. That is `tests/regressions/monomorphization_chain.py`,
which a first cut consulting only the bare-name entry broke.

### ~~BUG-CSA-ARG-TYPE-FLOAT-FROM-CALL-ARGS. Call-site analysis types a call float from its arguments~~ — FIXED 2026-07-27

**What:** the third copy of the same anti-pattern, in call-site analysis, which
runs *before* codegen and so cannot use `ret_tag` at all. Its `arg_types`
catch-all ends:

```python
has_float = any(isinstance(sub, ast.Constant) and isinstance(sub.value, float)
                for sub in ast.walk(arg))
arg_types.append("float" if has_float else None)
```

so `show(pick([1, 2, 3], 2.5, 0), 2)` gave `show` a bare `double` parameter.

**Where:** `_analyze_call_sites`' `arg_types` construction. There *is* a branch
above it for `arg.func.id in self._user_functions`, but that dict is empty while
CSA runs.

**FIXED 2026-07-27.** A new branch for calls to names in `_csa_func_asts` reads
the *callee's own* return expressions for float evidence (a float constant, or a
`Div`, which is always float) instead of the caller's arguments.

### ~~BUG-INNER-CALL-PICKS-FIRST-SPECIALIZATION. A container argument makes the resolver fall back to specs[0]~~ — FIXED 2026-07-27

**What:** `_resolve_specialization` scores each candidate signature against the
call site's inferred one, rejecting a candidate outright on any disagreement and
falling back to `specs[0]` when every candidate is rejected. Container tags come
in two spellings — the call site infers `"list:int"`, the recorded
specialization may be a bare `"list"` — and the exact-string comparison called
that a conflict. With `("list:int", "float")` against `("list", "int")`,
`("list", "float")` and `("list", "mixed")`, *all three* were rejected and the
resolver took the first: the **int** variant.

So inside `pick__list_d_i`, `idx(a, x)` called `idx__list_i`, which read the
double's bits as an index and walked off the end of the binary search:
`pick([1, 2, 3], 2.5, 1)` answered 4 instead of 3.

**Where:** `_resolve_specialization`, the partial-match scoring loop.

**Severity:** silently wrong values, and arbitrarily so — the fallback is
"whichever specialization happened to be recorded first".

**FIXED 2026-07-27.** Agreeing on the base kind before the `:` now scores +1
while an exact match scores +2, so a bare `"list"` candidate is evidence rather
than a conflict and an exactly-matching candidate still wins. Alongside it,
`_spec_param_tags` records each variant's parameter tags under its mangled name
so `_infer_call_arg_type` can forward a parameter's real kind into an inner call
— an FpyValue-slotted parameter otherwise reads back as MIXED, which is exactly
the "no evidence" that let every candidate tie.
