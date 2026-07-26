# fastpy — Known Issues

Running list of unsolved bugs and technical debt. Each entry should have
enough context to act on later: what the bug is, where in the code it lives,
how to reproduce it, and what the proper fix looks like.

---

## Active Bugs

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

### BUG-NESTED-DEF-NAME-COLLISION. Two sibling nested `def`s that share a name silently resolve to one another — 2026-07-26

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
bare `build`. The failure is downstream, in the **call-site type inference**,
which looks the callee up by bare name (`if node.func.id in self._user_functions`
in `_infer_call_value_type`, ~19655, and ~40 similar sites) without first trying
the scope-qualified key. So the call dispatches correctly but the *result type*
comes from the sibling.

**Proper fix:** a single `_resolve_callee_info(name)` helper that tries
`f"{self._current_func_name}.{name}"` before the bare name, used at every
`self._user_functions[...]` call-site lookup. `_recover_closure_ret_tag` already
resolves scope-first this way (added for BUG-INDIRECT-CALL-RET-TAG-INT) and is
the model to generalise. The wider audit is what makes this more than a
five-minute change — the lookups are scattered.

**Not a regression:** reproduces identically at the parent commit. Called out in
the docstring of `tests/regressions/indirect_call_ret_tag.py`, which gives every
nested helper a unique name so it tests the tag bug rather than this one.

### BUG-EXC-MSG-NOT-OWNED. A raised exception borrows its message string, so every dynamic message must leak — 2026-07-26

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
