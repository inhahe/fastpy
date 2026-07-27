# fastpy — Design Overview

fastpy is an **ahead-of-time (AOT) Python → native compiler**. It parses typed
Python, lowers it to LLVM IR (via llvmlite), optimizes and emits a native object,
then links it with a small C runtime to produce a standalone executable. Programs
that use stdlib features fastpy doesn't natively support fall back to an embedded
CPython interpreter (the "bridge"), so *any valid Python is valid fastpy*.

This file is a living, high-level map of the architecture. It is intentionally
concise; deeper per-subsystem notes live in `README.md`, `REFACTOR_DESIGN.md`,
`MODULE_SUPPORT.md`, `BRIDGE_FALLBACKS.md`, and `roadmap.md`. Keep this file in
sync when features or architecture change.

## Pipeline

```
.py source
  → parse (compiler/, Python AST)
  → type inference / lowering
  → LLVM IR (llvmlite)
  → compile_ir_to_obj()      (toolchain.py — -O2 passes + backend codegen)
  → link_executable()        (toolchain.py — link runtime + CPython)
  → native executable
```

The two codegen/link entry points live in `compiler/toolchain.py`:

- **`compile_ir_to_obj(ir_string, output_path, target=None)`** — parses IR, runs
  the `-O2` new-pass-manager pipeline, and emits an object file via an LLVM
  `TargetMachine`.
- **`link_executable(obj_files, output_path, install)`** — links objects into an
  executable. Windows uses MSVC `link.exe` (via vcvars); POSIX uses `cc`.
- **`compile_and_link(...)`** — the full IR→exe convenience wrapper.

### Refcounting in codegen: the Model-2 owned-temp rule

Heap values (strings, lists, dicts, objects) are reference counted. Codegen uses
the **Model-2 "borrowed-at-boundary"** discipline: a producer that hands back a
freshly-allocated `+1` value *registers* it as an **owned temp**
(`_register_owned_temp`), every consumer that wants to keep it **increfs to
retain**, and the registered `+1` is released by a **watermark flush**
(`_flush_rc_temps_to(mark)`) at the next statement/expression boundary. Mis-
classifying an owned value as borrowed only leaks; classifying a borrowed value
as owned is a use-after-free — so *retain* is always the safe direction.

Four structural rules follow, and all have been the source of real bugs:

- **A temp must be released in a block that its definition dominates.** An owned
  temp created inside one arm of a conditional *expression* — an if-expression
  branch, an `and`/`or` short-circuit operand — lives in that arm's own basic
  block, but the enclosing statement flushes in the **merge** block, which the
  arm does not dominate. Emitting the release there is invalid IR. Such arms must
  call `_capture_arm_rc_temps(mark)` while the builder is still inside the arm,
  and `_rejoin_arm_rc_temps(arms)` at the top of the merge block, which rebuilds
  each temp as a (tag, data) phi pair that is `0` on every other incoming edge —
  `fpy_rc_decref` no-ops on `data == 0`, so exactly the arm that ran is released.
  This moves the release site only; the `+1` itself is untouched.
  A *terminating* arm — one that returns or raises rather than reaching a merge
  — is simpler: take a watermark before it and call `_flush_rc_temps_to` after
  its terminator, which pops the temps without emitting anything. `_emit_assert`
  does this for the message expression it builds in the `assert.fail` arm, and
  must: `fastpy_raise` borrows the message pointer instead of copying it, so
  releasing there would be a use-after-free (BUG-EXC-MSG-NOT-OWNED).
- **A loop body must release its own temps before the back-edge.** The same
  dominance failure appears in comprehensions — a temp allocated in the body is
  invisible to the block where the enclosing statement flushes, after the loop.
  Here the phi rebuild would be *wrong*: the body runs N times, so releasing one
  merged value would leak N-1 iterations. The rule is a **per-iteration flush**
  (`_flush_rc_temps_to(mark)` with `mark` taken at the top of the body, emitted
  immediately before the branch to the incr block). It is only correct because
  every container store retains — `fpy_list_append` and `fastpy_dict_set_fv`
  incref what they store — so the container's reference outlives the body's. When
  a filter forks the body into keep/skip arms that both reach the incr block,
  `_release_rc_temps_since(mark)` emits the release on the skip arm *without*
  consuming the pending list, so each mutually exclusive path releases once.
- **Every store path must retain, or the flush frees a live variable.** A
  variable that outlives the statement that produced its value has to take its
  own reference; otherwise the boundary flush frees it and the next read is
  garbage. How this is done depends on the slot's representation:
  - An **FpyValue local** is a `{tag, data}` pair, so the slot carries its own
    tag: `_store_variable`'s FV path can incref the incoming value and decref
    whatever the slot held, unless the caller passes `steal=True` to hand over
    an already-owned `+1`.
  - A **native slot** — the bare-ABI path and the `--typed` `_native_vars` fast
    path — is a bare alloca (`i8*`, `i64`) with no runtime tag, so ownership is
    tracked *compiler-side* in `_rc_native_slots`, a per-`ir.Function` map of
    `name -> (alloca, tag)` recording the tag each slot was last **retained**
    with. `_retain_native_store` increfs the new value, then releases the old
    contents using the recorded tag — necessary because a slot can be rebound
    across static kinds (`x = str(5)` then `x = 12`). `_entry_store_null` zeroes
    such allocas in the entry block so a slot assigned on only one branch
    releases NULL instead of stack garbage, and `_emit_scope_decref` walks the
    registry at function exit. Gated on `_NATIVE_HEAP_TAGS` so scalar slots stay
    refcount-traffic-free; PYOBJ is excluded because the CPython bridge owns
    those pointers.
  - **A slot that holds a whole `FpyValue` must be refcounted with the tag *in
    the value*, never a static one.** The bare-ABI store path is not limited to
    genuine native slots: it also takes `{i32, i64}` structs, and there the
    variable's static kind is a guess. A function returning a str on one branch
    and a list on another is typed `list`, so retaining with a constant
    `FPY_TAG_LIST` walks a string through the `FpyList` header offset and writes
    out of bounds. The registry records `_RC_TAG_DYNAMIC` for such slots, and
    both the retain and the release `extract_value` the tag and data out of the
    struct instead of emitting an `ir.Constant`. The test has to precede the
    "no heap tag for this kind" early-out, since a static *scalar* kind likewise
    says nothing about what the struct actually holds.

  Module scope is *not* uniformly outside both, despite how it reads. A
  module-level name that was promoted to an LLVM global (because a function
  reads it, or a `global` statement names it) takes an early-return path in
  `_store_variable` with no refcount traffic at all. Every other module-level
  name is an ordinary local of `fastpy_main` and gets the same treatment as any
  other local — which is why the FpyValue-slot crash above landed at module
  scope.

  **Ordering:** the retain must come *before* the release of the old value, or
  `s = s` drops the last reference and then stores a dangling pointer. Both
  paths now do this — `_retain_native_store` by construction, and the FV path
  since the incref block was hoisted above the decref blocks in
  `_store_variable`.
- **Every statement-list emitter must flush per statement.** `_emit_stmts` takes
  a watermark before each statement and flushes after it; any code that emits a
  statement list *without* going through it inherits none of that. The try-like
  bodies (`_emit_try`, `_emit_try_star`, and the with-statement body) each open a
  fresh `*.cont` block after every statement for the pending-exception check, so
  letting temps accumulate to the enclosing flush produced releases in a block
  that did not dominate them. They now mirror `_emit_stmts`, with the flush
  emitted **in the `cont` block** rather than immediately after the statement:
  on the raising path a partially executed statement can leave a registered temp
  holding an undefined value, and decref'ing that is a UAF, whereas leaking it is
  the safe direction. Dominance holds at either site. If a new construct emits a
  statement list, it must do the same.

### Two local representations, and how one is chosen

A local is stored either as an **FpyValue** (`{i32 tag, i64 data}` — the slot
carries its own runtime tag) or **bare** (a naked `i8*`/`i64`/`double`, tag
known only to the compiler). `_USE_FV_LOCALS` selects FpyValue by default;
`_current_fn_bare_abi` overrides it per function, and bare-ABI exists for speed:
plain arithmetic, no shadow stack, no line tracking, so LLVM can optimise tight
loops at C++ speed.

**For module-level code the choice is made by `_gen_detect_bare_abi`**, which
scans the non-`def`/non-`class` statements of the module and disables bare-ABI
if any of them contains a class, a container/comprehension literal, a
subscript, an attribute access, an f-string, a `try`/`raise`, an import, a
tuple — **or any string constant**. A module docstring is a module-level
`ast.Expr(Constant(str))`, so *having a docstring at all* puts module code on
the FpyValue path. Bear this in mind when a bug reproduces in a scratch file
but not in a regression test, or vice versa: every regression test has a
docstring, so the test suite exercises the FpyValue path for module code almost
exclusively.

The two paths are **not** interchangeable, and the difference is tag fidelity:

- Bare-ABI `_load_variable` does a raw `builder.load(alloca)`. If the store put
  a whole `{i32, i64}` there, the load hands back a fully tagged FpyValue — so
  a value whose kind is only known at runtime survives, *by accident*.
- The FpyValue path calls `_unwrap_fv_for_tag(fv, type_tag)`, which for any
  pointer kind returns `_fv_as_ptr(fv)` and **discards the runtime tag** in
  favour of the compiler's static one.

So a wrong static tag is invisible on the bare-ABI path and fatal on the
FpyValue one. The general rule that follows: **a static kind is only safe to
act on when it is a fact, not an inference.** `VKind.MIXED` exists to say
"runtime dispatch needed", and `_unwrap_fv_for_tag` passes MIXED (and FVALUE)
through as a whole FpyValue rather than unboxing it — so a producer that cannot
commit to one kind must say `mixed` rather than pick a plausible kind.

`_csa_propagate_ret_types` is the cautionary example. Its per-function loop
walks every `ast.Return` and *overwrites* the recorded return type each time,
so it is last-classifiable-return-wins — a function returning a str on one
branch and a list on another was typed `list`, and the str return, which
matched no arm of the chain, lost silently. `_csa_returns_disagree` now runs
after that loop and records `"mixed"` when the returns commit to more than one
**pointer** kind.

Two limits on that check are deliberate and load-bearing:

- **An unclassifiable return is no constraint, not a conflict.** Only kinds
  readable straight off the AST count (literals, comprehensions, f-strings).
  If `return helper()` counted as a distinct kind, nearly every function would
  go MIXED and lose its static paths.
- **Scalars and `None` are out of scope.** `return None` beside `return [...]`
  is ubiquitous and already tolerated everywhere; int-vs-float returns are
  settled by a different mechanism (the i64-vs-double LLVM return type), and
  forcing those to MIXED would change the ABI of many functions. Mixed scalar
  returns are consequently still broken — see BUG-MIXED-SCALAR-RETURN-TAG.

**Two call sites must agree on the MIXED tag.** A callee's result type is
decided in two independent places, and both consult `_func_ret_types`:

- `_assign_fv_fast_path` when *storing* the result to a name, to pick the slot
  representation.
- `_emit_user_call` when emitting a *bare call expression*, via
  `_callee_returns_mixed`, to decide whether to unwrap at all. A MIXED callee
  skips `_unwrap_return_value` and yields the whole tagged FpyValue;
  `_emit_expr` types any `fpy_val`-shaped result as `VKind.FVALUE`, which is
  what routes `len`, subscript, slicing, `in`, iteration and truthiness through
  runtime dispatch.

They must agree, or `v = f(x); len(v)` and `len(f(x))` give different answers —
they did, which was BUG-DIRECT-CALL-LEN-STATIC-TAG. `_emit_user_call`
deliberately reads `_func_ret_types` and not `info.ret_tag`: the latter is
fixed in the declaration pass, before call-site analysis has run, so it holds
only the coarse first guess.

**The argument side is an ordering problem, solved by a fixed-point step.**
Call-argument types are classified early in `_analyze_call_sites`, before
`_csa_propagate_ret_types` has run and while `_user_functions` is still empty,
so `f(helper())` contributes nothing and a parameter passed *only* that way
stays untyped. An untyped parameter does not fail loudly — `len()` on it
answers 0, and using it properly faults. `_csa_refine_params_from_call_returns`
runs after the propagation and fills slots that are still unknown, never
overriding what the main merge decided. Its two rules point in opposite
directions on purpose:

- An *unresolvable* caller poisons that position, keeping the conservative
  untyped ABI. Keyword and `*args` call sites disable refinement for the whole
  callee, since positional slots cannot be aligned through them.
- Callers that all *resolve but disagree* yield MIXED rather than unknown —
  every caller is known there, they are simply different kinds, which is what
  MIXED means.

Coverage is bounded by what `_func_ret_types` records: list/dict/tuple/float
and MIXED, but not str/bytes/set, since the propagation chain has no arm for a
plain `return "abcd"`. Widening that belongs on the callee side.

**The bare ABI requires positive evidence about every parameter.** `param_types`
falls back to `i64` when nothing is known, so by the time `_duf_select_abi` runs
an untyped parameter is indistinguishable from a known `int` one and used to
qualify the function for the bare ABI. Bare ABI has nowhere to put a runtime
tag: the caller unwrapped the tagged `FpyValue` down to a naked `i64` and the
body read a string pointer as an integer, so `len()` answered 0 instead of
faulting. Bare ABI now additionally requires every parameter to carry an
annotation or to have been classified at some call site — silence is not
evidence of scalarity. This is the shared root cause behind several separately
observed symptoms (`len()` on a parameter fed only by a call, a `"mixed"`
parameter tag still landing on a bare `i64`, and subscripting an untyped
parameter falling to the CPython bridge), which is why it is fixed at the ABI
rather than at each use. In the regression corpus 11 of 641 functions changed
ABI, all of them nested or closure functions.

**Returning an untyped parameter is a `mixed` return.** `_duf_determine_ret_tag`
inherits a `return <param>` from the call site's classification, but when no
call site classified the parameter there was nothing to inherit and the tag
fell through to the `int` default. The value itself was fine — an FV-ABI callee
really does return a tagged `{i32, i64}` — but the caller believed the tag and
unwrapped it away, so `len(echo(opaque_str()))` measured a string pointer as an
integer while `r = echo(...); len(r)` was right, the same two-forms-disagree
split as BUG-DIRECT-CALL-LEN-STATIC-TAG. The honest tag is `mixed`, since the
kind is whatever the caller passed, and `_callee_returns_mixed` now consults
`info.ret_tag` when `_func_ret_types` has no entry: the declaration pass is the
only pass that can see "returns a parameter", so the two answers are combined
rather than one deferring to the other. Annotated parameters are excluded —
the annotation is evidence enough for the bare ABI, whose `i64` return has
nowhere to carry a `mixed` tag. `_duf_propagate_mixed_ret_tags` then spreads
that tag through plain forwarding wrappers (`def wrap(v): return inner(v)`) to
a fixed point, in either definition order; `_csa_propagate_ret_types` does the
same for the tags it knows, but it runs before the declaration pass and so
cannot see this one.

**Indexing an untyped parameter dispatches on the tag.** The same "silence
means scalar" guess ran a second time in `_efd_store_parameters`, which reads
`static_param_types`' `i64` fallback as a real answer. Its *pointer* branch
already had an "every caller unresolvable → `mixed`" arm; the non-pointer branch
did not, and that asymmetry sent `s[i]` on an unannotated parameter past the
`fastpy_fv_subscript` runtime-dispatch arm and into the generic CPython
`__getitem__` bridge — NULL in pure mode, an access violation on Windows. Both
branches now answer `mixed` when nothing is known and the parameter has no
annotation. Two consequences follow. `return v[i]` is a `mixed` return, because
an element of an untyped container is itself of unknown kind and saying `int`
would only throw the runtime tag away again. And **slices** had no dispatch arm
at all — `v[1:3]` took whichever static path the compiler guessed, so a list
arriving on `str_slice` quietly sliced to `""` rather than faulting; the new
`fastpy_fv_slice` picks str/bytes or list/tuple from the tag and echoes that tag
back, since a slice has the same kind as what it came from.

**One slot per local, decided before the body is emitted.** A local's storage
class used to be decided by its *first* store — `t = 0` opens an `i64` alloca —
and a later store that needed an `FpyValue` allocated a **second**, wider slot.
Straight-line code survives that because every subsequent load reads the new
slot, but a loop does not: in `t = 0; while …: t = t + at(lst, i)` the load was
emitted before the widening and stays bound to the dead slot forever, so the
accumulation is discarded on every iteration (420 came out as 60). The same
split drops the initial value when the widening happens inside an `if`.
`_scan_fv_forced_locals` now pre-scans each scope for locals that can hold a
runtime-tagged value — assigned from a `mixed`-returning call, from an element
or slice of such a value, or from arithmetic involving one, to a fixed point
across back edges — and `_store_variable` gives those an `FpyValue` slot and a
`mixed` tag from their first store. Over-approximating is safe: an `FpyValue`
slot holds any value, it is merely wider than it needs to be. Parameters are
excluded, since `_efd_store_parameters` creates their slots first.

**`bytes` and `set` are pointer kinds, and every step of the return chain has
to say so.** `str`, `list`, `dict` and `tuple` had arms in all three stages of
the return-type chain; `bytes` had none anywhere and `set` had only half of
one, and each missing arm hid the next behind it. `_csa_propagate_ret_types`
now records `bytes`/`set` (literal, `.encode()`, `bytes`/`set`/`frozenset`
call — `bytearray` is deliberately excluded, since fastpy has no mutable bytes
type and answering with an `FpyBytes` would make it print as `b'..'`) so a call
site passing one can be classified;
`_duf_detect_ret_type` returns `i8_ptr` for those shapes, because leaving the
function declared `i64` makes every pointer-gated path decline to fire — the
bytes arm of the subscript emitter is behind an `isinstance(obj.type,
PointerType)` test, so `ob()[0]` fell into the CPython `__getitem__` bridge and
faulted; and `_duf_determine_ret_tag`'s pointer arm names them, since its
fall-through default `"ptr"` means *list*, which made `ob() + b"d"`
concatenate as a list and print `()`. The consumers of the kind follow the same
rule: `_is_bytes_expr` reads the callee's declared return tag rather than only
recognising variables, and it is the single definition — `_infer_type_tag`'s
private duplicate was deleted. `in` on a bytes had no arm in `_emit_in_compare`
either; the new `fastpy_bytes_contains` takes the left operand *tagged*, since
an int asks about a byte value and a bytes/str about a contiguous subsequence,
and works from stored lengths so an embedded null byte is matched rather than
ending the search.

**A `bytes` is not a `str` that happens to be tagged differently.** The two
share an LLVM type and nothing else, and every place that blurred them was a
bug. `bytes(x)` had no native lowering at all and went to the CPython bridge,
which answers NULL in pure mode; `fastpy_fv_to_bytes` takes the argument
*tagged* so one helper covers the int count, the bytes copy, the
str-without-encoding `TypeError` and — by routing through `fastpy_fv_to_list` —
every iterable, without an arm per container. Slicing went through
`fastpy_str_slice`, which indexes by code point and returns an `FpyString`;
tagging that allocation BYTES made every later `fpy_bytes_len` probe for the
bytes magic 16 bytes before a smaller-header buffer, a heap-buffer-overflow read
that usually landed somewhere plausible. `fastpy_bytes_slice` /
`fastpy_bytes_slice_step` are byte-indexed and `fpy_bytes_alloc`-backed, and
all three lowering sites choose them from the receiver's kind. And a bytes
stored in a list came back out as a `str`, because the element-tagging fallback
labels every unrecognised pointer STR and neither the list-literal element
inference nor the `.append()` pre-pass had a bytes arm. The lesson each time is
the same: the answer to "is this bytes?" belongs in exactly one function.
`_is_bytes_expr` is it, and it takes an optional name table so the static
pre-passes — which run before any variable exists — can consult it rather than
re-deriving a weaker version of it.

**Giving a builtin a native lowering is two edits, not one.** `_emit_assign`
keeps a `native_builtins` set and tags `x = f(...)` as `pyobj` for every builtin
*not* in it, on the reasoning that anything else came back from the CPython
bridge as a `PyObject*`. Adding `_emit_builtin_bytes` without adding `"bytes"`
to that set left `x = bytes(3)` declared `pyobj` while the emitter produced a
native `FpyBytes`, so `print(x)` handed the buffer to `PyObject_Str` and took an
access violation — the `binascii`/`gzip`/`zlib` stdlib tests caught it. The set
is the authoritative list of "builtins whose result is a native value"; a new
native lowering has to appear in both places or the two disagree.

**A splat is evidence about the required slots, and an admission of ignorance
about the rest.** `f(*seq)` had no arm in the per-argument classification at
all, so a parameter fed only that way hit the same silent-zero.
`_csa_build_seq_binds` maps each name to the sequence literal it was bound to —
`_csa_var_types` records only the coarse kind `"list"`, never the element type
— and `_csa_splat_elem_tag` resolves that to an element tag, poisoning any name
that is rebound anywhere. The element tag is given to every slot from the
splat's position up to `min_args`. Past `min_args` the slot may take the
element *or* the default depending on the sequence's runtime length, so unless
the two types are positively known to agree the slot is recorded as `"mixed"`
— which is what it is, a slot with no single static type — and that denies the
function the bare ABI so the value arrives carrying its own runtime tag. This
arm runs even when the element tag is unreadable: an unreadable sequence is not
evidence that the default wins (BUG-SPLAT-DEFAULTED-SLOT-TYPE).

**"Mixed" only helps if every consumer agrees it is not a type.** `"mixed"` is
cleared to `None` in `_call_site_param_types` — the merge cannot refine it —
but `_function_signatures` keeps it, and the FV-ABI prologue reads those
signatures to decide each parameter's tag. It used to treat one `"mixed"`
signature as `len(_sig_types) == 1`, i.e. as a single *known* type, and tag the
parameter statically anyway; both halves of that branch now test for MIXED
first. A tag that says "no static type" has to be recognised by everything
downstream, or recording it changes nothing.

**Splat expansion lives in one place.** `_splat_positional_args` is shared by
`_emit_user_call` and `_emit_user_call_fv`, which previously each had a copy —
so BUG-STARARG-SPLAT-DEFAULT-PARAM had to be fixed twice and one copy was
missed. A splatted sequence supplies as many arguments as it *has*, so required
parameters are extracted unconditionally (a short sequence is a TypeError, and
the `min_args` check reports it) while each defaulted slot is resolved at
runtime by `_splat_elem_or_default` as `seq[i] if i < len(seq) else <default>`.
Every element — required or defaulted — is read as a tagged `FpyValue` and
narrowed by the shared `_splat_fv_to_param`: passed straight through for an
FV-ABI callee, and converted through the runtime tag
(`_splat_fv_as_double` / `_splat_fv_as_i64`) for a bare-ABI one. The required
slots used to take the shortcut of unwrapping by the sequence's *static*
element type, which `_get_list_elem_type` reports even for a sequence that has
no single element type (BUG-SPLAT-HETEROGENEOUS-ELEM).

**A splat call cannot re-derive its own signature at codegen time.**
`_resolve_specialization` rebuilds a call's signature from its argument nodes,
and a `Starred` node classifies as `None` while standing for an unknown number
of parameter slots — so every specialization scored zero and the first one was
taken (BUG-SPLAT-CALL-PICKS-FIRST-SPECIALIZATION). Call-site analysis has
already computed the right answer, having both the callee's parameter list and
the sequence-binding map, so it records it against `id()` of the `Starred` node
in `_csa_splat_call_sigs` and the resolver consults that.

## Runtime

`runtime/` holds the C runtime linked into every fastpy binary:

- **Shared, Python-independent:** `runtime.c`, `objects.c`, `threading.c`,
  `gc.c`, `bigint.c` — object model, refcounting/GC, threading, big integers.
- **CPython bridge:** `cpython_bridge.c` (compiled per Python version, `py311`–
  `py314`) embeds a real CPython so programs using unsupported stdlib still run.
  The bridge drags `libpython` into the binary.

**Method dispatch ABI.** User classes register their methods with
`fastpy_register_method(class_id, name, func, arg_count, returns_value)`, and
the string dispatchers (`fastpy_obj_call_methodN`) call the stored pointer
through a function-pointer cast. That cast must match the callee's real
signature: a Python method with no `return <expr>` is compiled to a **void**
LLVM function, and calling it through an `int64_t`-returning type yields
whatever is in the return register, not 0. Hence the `returns_value` flag and
the `FpyMethod*VoidFunc` typedefs in `objects.h` — the dispatchers branch on it.
The same rule holds anywhere else a method pointer is called (the vtable path in
codegen checks `direct_func.return_value.type` for exactly this reason). Getting
it wrong is not a crash but a wrong *value*, and `with` turns a wrong value into
lost control flow: a truthy `__exit__` result means "suppress the exception".

**The compiler-side counterpart: a void call's Python value is `None`.** Because
a function/method with no `return <expr>` compiles to a void LLVM function,
codegen has nothing to hand back and substitutes the placeholder `i64 0`. That
placeholder's LLVM type says INT, which is a lie — the Python value is `None`.
Anywhere codegen derives a *tag* rather than an LLVM type (print wrapping,
FpyValue boxing, `is` comparison, variable type inference), it must ask
`CodeGen._call_is_void(node)` rather than look at the value, or the call reads
back as the integer `0`. A void method also never calls `set_ret_tag()`, so the
`get_ret_tag()` recovery used for obj-method calls does not apply to it.

**Indirect calls: the ret-tag side channel is a protocol, and silence is not a
default.** `fastpy_call_ptrN` returns a bare `i64`, so a callee reached through a
function pointer — a nested `def` lowered to a closure object, a lambda, a
decorator result — loses its Python type unless it publishes one. The channel is
the single global `fpy_ret_tag`, written by `set_ret_tag()` and read by
`get_ret_tag()`. Two consequences follow, and both have bitten:

- *Every* indirectly-callable body must call `set_ret_tag()` on every return
  path. Not publishing does **not** mean "the caller assumes int" — it means the
  caller reads a value left by some earlier, unrelated call. A str-returning
  nested def executed before a lambda call was enough to make `print(f(1))`
  interpret an int as a `char*` and segfault. Closure bodies
  (`fastpy.closure.*`) and the `__i64_wrap` thunk already did this; lambda
  bodies were the hole.
- Symmetrically, a call site may only *read* the tag when it knows the callee
  publishes a *trustworthy* one. `_recover_closure_ret_tag` therefore recovers
  only for callees it can resolve to a `FuncInfo` that is either `uses_fv_abi`
  (reached through `__i64_wrap`) or a `fastpy.closure.*` body; unknown callees
  keep the plain `i64` path. **Decorated names are excluded** — `f` in
  `@deco def f(...)` is bound to the decorator's wrapper, not to the function
  `_user_functions["f"]` describes, and a wrapper shared across several
  decorated callees publishes one statically-inferred tag for all of them
  (BUG-DECORATOR-WRAPPER-STATIC-RET-TAG).

A *static* return tag is not an alternative here. `FuncInfo.ret_tag` stays
`"int"` for FpyValue-ABI functions by design — their real tag rides inside the
returned `{i32, i64}` struct, which only a direct call can see — and a function
may return different kinds on different branches regardless.

**Function names are made unique before analysis, because the analysis maps are
flat.** Nearly every map the compiler builds about a function —
`_csa_func_asts`, `_func_ret_types`, `_call_site_param_types`, `_monomorphized`,
`_user_functions`, `_function_def_nodes` — is keyed by the function's **bare**
name, and `_csa_func_asts` is populated with a `setdefault` over `ast.walk`, so
the first `def` with a given name wins module-wide. Two sibling nested
`def build(...)`s in different enclosing functions therefore shared one analysis:
its return type, its call-site parameter types, its string-param detection
(BUG-NESTED-DEF-NAME-COLLISION).

`_uniquify_nested_def_names(tree)` runs as the **first** statement of
`generate()`, ahead of `_gen_prescan` and so ahead of every one of those maps. It
alpha-renames a nested `def` whose bare name is used by another `def` anywhere in
the module to `name__nK` and rewrites references throughout the owner scope. The
alternative — re-keying every map by scope — would have meant auditing dozens of
lookup sites and would have left the flat ones as latent traps.

The pass is conservative by design and keeps the original name whenever renaming
would be unsafe: a `global`/`nonlocal` names it, the owner scope rebinds it
(another def, an assignment, a parameter, an import), or the def is module-level
or a class method — those names are externally visible. `_rewrite` also stops
descending into a nested scope that shadows the name with a parameter of its own.
Two defs of the same name in *one* scope are declined too; resolving a use there
needs flow analysis (BUG-SAME-SCOPE-DEF-REBIND).

**Callee lookup is scope-first regardless.** A nested `def` with no free
variables is hoisted to module scope and registered in `_user_functions` under
its bare name, while a capturing one is registered as `outer.inner`.
`_lookup_user_function(name)` tries `f"{_current_func_name}.{name}"` before
`name` and returns the key it hit, so callers can index `_function_def_nodes`
consistently. That is what Python scoping says anyway, and it covers the cases
the renaming pass declines.

## Targets (codegen backends)

By default fastpy emits for the **host** triple and links against the host
CPython. `compile_ir_to_obj`/`_make_target_machine` accept a `target` selector so
fastpy can cross-compile for a foreign platform:

- **`target=None`** (default) — host codegen. PIC relocation on POSIX, default on
  Windows; links against host CPython. Unchanged historical behavior.
- **`target=SLATEOS_TARGET`** (`"x86_64-slateos"`) — cross-compile for **SlateOS
  userspace** (the microkernel OS in `D:\visual studio projects\os`). Emits an
  x86-64 **ELF** object using the triple `x86_64-unknown-linux-musl`, the
  data-layout, `static` relocation, `large` code model, and `+sse,+sse2` taken
  verbatim from the OS repo's Rust target spec `toolchain/x86_64-slateos.json`.
  This keeps fastpy objects **ABI-compatible with the OS's Rust sysroot** — in
  particular its `libc.a` (the `posix` crate built as a staticlib, which maps
  libc-shaped calls onto SlateOS native syscalls) — and linkable by the same
  gnu-lld/rust-lld linker. Both host and target are x86_64, so the already
  initialized native X86 backend can emit for this triple with no extra target
  initialization.

  The SlateOS constants (`_SLATEOS_TRIPLE`, `_SLATEOS_DATA_LAYOUT`,
  `_SLATEOS_CPU`, `_SLATEOS_FEATURES`) MUST stay in lockstep with
  `x86_64-slateos.json`. Tested by `tests/test_cross_target.py`.

### SlateOS integration status (OS "initiative F")

Driven by the OS roadmap and its decision log (`design-decisions.md §80`,
resolving open-question Q29). Strategy: **pure-mode native compile first**, add
the CPython bridge for SlateOS later as a superset once CPython is ported.

- [x] **SlateOS codegen target** — `compile_ir_to_obj(target=SLATEOS_TARGET)`
  emits ABI-matched x86-64 ELF objects.
- [x] **SlateOS link step (plumbing)** — `link_executable(target=SLATEOS_TARGET)`
  drives **`rust-lld`** (GNU/ELF flavor, static, non-PIE, `--no-dynamic-linker`)
  via `_link_slateos`, the same LLVM linker the OS repo uses for its userspace.
  `_find_rust_lld()` locates it in the active Rust sysroot (or `$FASTPY_RUST_LLD`
  / PATH).
- [x] **Cross-compile the C runtime** (`runtime/*.c`) to `x86_64-slateos`
  (pure-mode: no `cpython_bridge.c`, no `libpython`). Done via **`zig cc
  --target=x86_64-linux-musl`** — a self-contained clang + bundled musl headers
  + musl libc in one portable download, so no system-wide toolchain and no
  separately vendored musl sysroot is needed (operator approved option A, Q30).
  `_find_zig_cc()` locates it (`$FASTPY_ZIG` / PATH / `D:\utils\zig-*`).
  `ensure_slateos_runtime_built()` compiles the seven pure-mode TUs — `runtime`,
  `objects`, `threading`, `gc`, `bigint`, **`bridge_stub`**, **`pathlib_pure`** — into
  `runtime/slateos/*.o` with flags mirroring the codegen ABI (`-mcmodel=large`,
  `-fno-pic -fno-pie`, `-DFPY_PURE_MODE`). Pure-mode specifics:
  - **`bridge_stub.c`** substitutes for `cpython_bridge.c`: refcount hooks are
    no-ops (no bridge objects can exist) and operational entry points raise a
    catchable `RuntimeError`.
  - **`-DFPY_PURE_MODE`** compiles out the JIT symbol table in `runtime.c`
    (which would otherwise force-reference bridge functions pure mode omits).
  The port also fixed latent MSVC-isms in `objects.c`/`objects.h`/`threading.h`
  that MSVC accepted implicitly but Clang rejects (forward decls, `<assert.h>`,
  a `const`-discard cast) — all verified still safe for the host MSVC build.
- [x] **Full program link + crt startup** — `link_executable(target=SLATEOS_TARGET)`
  builds the runtime on demand, resolves the OS repo's static `libc.a`
  (`_find_slateos_sysroot_lib()`: `$FASTPY_SLATEOS_SYSROOT` or the sibling
  `../os/toolchain/sysroot/lib`), and links program object + runtime objects +
  `-lc` via `_link_slateos`. The link entry is **`_start`** (the real ELF
  entry), so rust-lld pulls the crt0 out of `libc.a` — the OS `posix` crate
  (built for `x86_64-unknown-none`, so its `#[cfg(target_os = "none")]` crt is
  present) provides `_start` → `__libc_start_main` (retrieves argv/envp from the
  kernel via syscall, inits environ/signals, runs ELF constructors) → calls
  `main` (runtime.c's `main`, which runs `fastpy_main`) → `exit(ret)`. A real
  fastpy program (lists/iteration/print) links to a ~2.9 MB SlateOS **ET_EXEC**
  ELF with a nonzero `_start` entry and zero undefined symbols (a static non-PIE
  link fails otherwise). Covered by `tests/test_cross_target.py` (skips cleanly
  without zig / rust-lld / sysroot). Note the fastpy program is emitted for the
  `x86_64-unknown-linux-musl` triple while the crt/libc is `x86_64-unknown-none`
  — ABI-identical at the object level (plain x86-64 SysV, static, large model).
- [x] **First real component — on-target execution confirmed** (2026-07-21). A
  fastpy-built SlateOS binary (`services/fastpy-hello` in the OS repo, a real
  fastpy program with lists/iteration) now **boots under the SlateOS kernel and
  runs at ring 3** — the kernel self-test `self_test_fastpy_slateos_tls` spawns
  it via the native ABI and asserts the process reaches `Zombie`. The crt
  startup + native syscalls behave on-target; the pipeline is now validated
  end-to-end, not just at link time.
  - **argv delivery validated on-target** (2026-07-21). The self-test spawns
    the program with a known 3-element argv (`["fastpy-hello","alpha","bravo"]`)
    and the program runs `sys.exit(len(sys.argv))`; the kernel asserts
    `exit_code == 3`. This exercises the full argument path end-to-end: kernel
    `SYS_PROCESS_GET_ARGS` → crt `retrieve_initial_args` → runtime `fpy_argv` →
    Python `sys.argv` → non-zero exit code back to the parent (serial:
    *"fastpy-on-SlateOS TLS … read its 3-element argv via sys.argv, and ran to
    exit(argc): OK"*). Two fixes made this work: (a) runtime `fastpy_sys_argv`
    now allocates each element as a heap `FpyString` (a raw C `char*` is not a
    valid `FPY_TAG_STR` value — reading the length header faults); and (b)
    codegen learned that `sys.argv`/`sys.path` are `list[str]` and
    `sys.version_info` is a `tuple[int]`, so `len()`/iteration/subscript dispatch
    natively instead of routing through the CPython-bridge object path (which,
    in pure mode, raises).
  - **Pure-mode native imports no longer require the CPython bridge.**
    `import sys` (and other native modules) previously emitted
    `fpy_cpython_import("sys")`, which in a pure-mode (no-CPython) build raises
    `RuntimeError` from `bridge_stub.c` — so the very first line of any program
    that imported a native module crashed on-target. Because the *same* IR is
    compiled for both host and pure targets, codegen cannot special-case the
    mode; the fix is at the runtime-C level. Codegen now emits
    `fpy_cpython_import_native` / `fpy_cpython_getattr_native` for native-module
    imports and attribute fallbacks. In the host bridge these forward to the
    real `fpy_cpython_import`/`getattr`; in `bridge_stub.c` they return a
    non-null opaque sentinel with **no raise** (native dispatch never
    dereferences it), so `import sys` links and runs in pure mode and only a
    genuine use of an unsupported non-native attribute fails cleanly.
  - **Q31 resolved — Option A** (operator's call; open-questions.md → OS
    design-decisions.md §82): the `PT_TLS` problem (the C runtime's
    `FPY_THREAD_LOCAL __thread` locals lower to `%fs:offset`, and a native static
    binary starts with `fs_base = 0`) is fixed **in the posix crt**. On startup
    `setup_main_thread_tls()` (`posix/src/crt.rs`, `#[cfg(target_os="none")]`)
    finds `PT_TLS` via the linker-defined `__ehdr_start` (no aux vector needed
    for a static non-PIE), mmaps a variant-II TLS block + TCB, copies the
    `.tdata` init image, writes the `%fs:0` self-pointer, and installs the thread
    pointer via the native `SYS_SET_FS_BASE` syscall — all before the first
    `__thread` access or stack-protector check runs.
  - Latent OS bug found + fixed en route: posix's native `SYS_MMAP`/`SYS_MUNMAP`/
    `SYS_MPROTECT` numbers (30/31/32) collided with the kernel's IRQ syscalls, so
    the crt's TLS mmap came back `PermissionDenied`; corrected to the kernel's
    native numbers (20/21/22). This is an OS-side fix, not a fastpy toolchain
    change — the toolchain remains complete and green.
  - Next: pick a genuinely useful component (candidate: the package manager) as
    the first *shipping* fastpy SlateOS binary now that the runtime path is
    proven. **Prerequisite in progress — pure-mode file I/O** (see below).
- [x] **Pure-mode file I/O — native file objects** (host-verified 2026-07-21;
  SlateOS build+link verified). A
  genuinely useful on-target utility (`cat`, `sysinfo`, the package manager)
  needs `open()`/read/write, but the built-in `open()` used to route through the
  CPython bridge (`builtins.open`), which raises in pure mode. Fix: a **native
  file object** in the runtime, backed by C stdio (`fopen`/`fread`/`fwrite`/
  `fgets`/`fclose` — the SlateOS posix libc implements these over the `SYS_FS_*`
  VFS syscalls, so it works on-target with no bridge). The file object is a
  built-in `FpyObj` class (`file`, registered lazily in `objects.c`) holding the
  `FILE*` in a slot; `open()` returns it tagged `FPY_TAG_OBJ`, so the existing
  object-method dispatch (`fastpy_obj_call_methodN`) and context-manager path
  (`with open(...) as f:` → `__enter__`/`__exit__`) drive `read`/`write`/
  `readline`/`readlines`/`close`/iteration with no per-method codegen. Because
  the `file` class is registered only at runtime (invisible to codegen), method
  calls on `open()` results are routed by codegen through a dedicated path
  (`_emit_method_call_file`): it emits `fastpy_obj_call_methodN` and recovers the
  dynamic return type from the runtime ret-tag side channel (`get_ret_tag`),
  packing the result as an `FpyValue` so `read`/`readline` → str, `readlines` →
  list, `write` → int are correctly typed at the call site (an earlier bug
  mistyped these as int, returning len 0 and segfaulting). Codegen tracks file
  variables (`_file_vars`) from `f = open(...)` assignments and `with open(...)
  as f:` bindings; the `with`/`for line in f` paths bind `f` as `VKind.OBJ` so
  the context-manager and iterator-protocol dispatch drive the runtime methods.
  **Design
  decision (Claude, autonomous):** native file objects are used in **both** host
  and pure mode (uniform behaviour, and it removes the bridge dependency
  entirely for core file I/O) rather than native-only-in-pure. Tradeoff: a native
  file object can't be handed to a *bridge* stdlib function (`json.load(f)`,
  `csv.reader(f)`) in host mode — but the test suite has no such fixture (only
  `shelve.open`, a module method, and the `_run_scratch`/`_dump_ir` harness
  scripts which run under host CPython, not compiled), and the idiomatic
  `json.loads(open(p).read())` still works because `read()` returns a native str.
  Known slice-1 limitations (documented, to extend): text mode only (`read()`
  returns `str`, binary `'rb'`/`bytes` not yet wired); `read(n)` size arg not yet
  supported (`read()` reads all); `FileNotFoundError` is raised by name but not
  yet registered in the OSError hierarchy.
- [x] **Native `os.*` syscall surface (pure-mode, bridge-free)** — a growing set
  of `os` functions lower directly to native runtime C calls (`fastpy_os_*` in
  `runtime/objects.c`, declared `extern` in `runtime.c`) that call the SlateOS
  posix libc, which dispatches to the kernel `SYS_*` syscalls — no CPython
  bridge (only the `fpy_cpython_import_native` sentinel from `import os`). Each
  lowering has **five sites** in `compiler/codegen.py`: (1) runtime `ir.Function`
  registration (`self.runtime["os_X"]`), (2) return-type inference in the
  `mod == "os"` chain, (3) an emit handler in `_emit_os_call` (raw-fd args are
  coerced to i64 via the inline `_fd_i64` helper; string args via
  `_ensure_ptr`), (4) an entry in the `_CSA_MODULE_FUNC_RETURNS` map, plus (5)
  the C impl + extern. Surface so far:
  - **process/identity:** `getpid`, `getppid`, `gettid`, `getcwd`, `getenv`.
  - **raw-fd I/O:** `open(path, flags[, mode])` → raw file fd (SYS_FS_OPEN; the
    raw-fd counterpart to the high-level builtin `open()`), `read(fd, n)` → str,
    `write(fd, data)` → int, `close(fd)` (posix dispatches by fd kind:
    SYS_PIPE_* for pipe ends, SYS_FS_* for files), `dup(fd)` (shares the kernel
    handle — a pipe dup aliases the same buffer), `dup2(oldfd, newfd)` (installs
    the handle at a *caller-chosen* fd, closing whatever was there — fd
    redirection), `lseek(fd, off, whence)`
    (SYS_FS_SEEK), `ftruncate(fd, len)` (SYS_FS_FTRUNCATE — distinct from the
    path-based `truncate()`/SYS_FS_TRUNCATE), `pwrite`/`pread(fd, …, offset)`
    (positioned I/O that leaves the fd offset untouched).
  - **pipes:** `pipe()` → `[r, w]` (SYS_PIPE_CREATE). NOTE: this exercise
    uncovered and fixed a systemic kernel ABI bug — the native SYSCALL exit
    path dropped `SyscallResult::value2` (the RDX second return), so *every*
    two-value syscall (SYS_PIPE_CREATE, SYS_CHANNEL_CREATE, dma_alloc, …) lost
    its second value in userspace until fixed.
  - **path helpers:** `path.exists`/`isfile`/`isdir`/`join`/`dirname`/…,
    `listdir`, `remove`/`unlink`/`mkdir`/`rmdir`/`rename`/`truncate`/…
  Each new raw-fd syscall ships with a **false-pass-proof ring-3 kernel
  self-test** in the OS repo (`services/fastpy-<name>/` tool +
  `self_test_fastpy_slateos_<name>` in `kernel/src/proc/spawn.rs`): the tool
  round-trips data through the kernel path and writes the result to a file the
  harness asserts byte-for-byte, so a stub/mis-lowering cannot fake a pass.
- [x] **Pure-mode `pathlib.Path`** (`runtime/pathlib_pure.c`, on-target verified)
  — the CPython-free implementation of the whole `Path` surface codegen emits:
  construction, `/` and `joinpath`, `name`/`stem`/`suffix`/`parent`,
  `exists`/`is_file`/`is_dir`, `resolve`, `read_text`/`write_text`,
  `with_suffix`, `iterdir`, and the `Path.cwd()` classmethod. Predicates
  delegate to the native `fastpy_os_path_*` helpers in `objects.c`, so no new
  struct-stat ABI dependency.

  **Representation (matters — it is an ABI contract with codegen):** a Path is
  OBJ-tagged (`FPY_TAG_OBJ`), and fastpy's OBJ refcount dispatcher
  (`fpy_rc_incref`/`decref`) has no type information, so it *blind-probes* the
  pointee for an `FpyObj` magic at **byte offset 32** and an `FpyClosure` magic
  at **offset 0**. The obvious "a Path is just a `char*`" representation puts
  path *text* under both probes — a filename whose bytes 32..35 spell "SJBO"
  (`FPY_OBJ_MAGIC`) was therefore mistaken for a live object and had its own
  bytes decremented as a refcount. That is user-controllable and deterministic,
  not a rare collision. So a pure-mode Path is an **`FpyPurePath` header block**:
  magic at offset 0, a zero guard word at offset 32, NUL-terminated text at
  offset 40. Consumers must use `_p()` / the exported `fastpy_path_as_cstr()`;
  never cast a Path to `char*`. Two consequences: `fastpy_path_with_suffix` has
  a pure-mode implementation here (the `runtime.c` one is `#ifndef
  FPY_PURE_MODE`), and codegen converts a Path right-hand join operand through
  `path_str` (`_emit_path_join_operand`).

  **String results** (`name`/`stem`/`suffix`/`str()`/`read_text`) are tagged
  `FPY_TAG_STR` and so must be `fpy_str_alloc`-headed, never bare `strdup` — the
  refcount machinery reads an 8-byte header at `data - 8`, and on the SlateOS
  allocator a bare `strdup`'s preceding word can collide with `FPY_STR_MAGIC`
  and free a wild pointer.

  **`iterdir()`** is typed `list[Path]` by codegen (`_is_path_iterdir_call`),
  and *both* runtimes return an `FpyList*` of OBJ-tagged Paths — codegen is
  deliberately mode-agnostic, so the bridge was changed to match rather than
  returning a raw PyObject* list. CPython's laziness is the one semantic
  difference; the bridge was always eager too.
- [ ] **CPython bridge on SlateOS (B)** — later, once CPython is ported, so
  unsupported-stdlib programs also run on-target.

## `tools/pure_harness.py` — fast memory-safety loop for pure mode

Pure-mode bugs used to be found only by a ~6-minute QEMU boot that reports a
single exit code and no memory-safety signal. `tools/pure_harness.py` closes
that loop to seconds: it takes a fastpy program, generates IR with the **real**
`CodeGen`, strips the target triple/datalayout, and builds it under WSL clang
against the **real** pure-mode runtime TUs (`-DFPY_PURE_MODE`) with
`-fsanitize=address,undefined -fno-sanitize-recover=all`. Same codegen, same C,
native Linux instead of SlateOS — so anything that is a genuine out-of-bounds,
use-after-free, or misaligned access shows up with a stack trace and an
allocation site instead of a silently wrong answer. Both live Path bugs this
session (the offset-32 heap-buffer-overflow and a misaligned `FpyObj` access
from `Path.cwd()`) were pinpointed this way. Regression programs live in
`tests/pure/*.py` and print a bitmask (Linux truncates exit codes to 8 bits;
SlateOS does not, which is why the on-target tools exit with theirs). They
currently cover the `Path` surface — its construction and accessors
(`pathlib_checks`, `path_boundary_checks`, `path_magic_collision_checks`,
`path_iterdir_checks`), its *display* through the generic OBJ consumers
(`path_display_checks`), and its use *as an argument* to `os.*` / `os.path.*` /
the builtin `open()` (`path_arg_checks`) — plus exception handling
(`exception_checks`), which establishes that pure mode really does catch a
`fastpy_raise` raised from inside a runtime function, the premise any runtime
error-reporting design depends on.

The argument case deserves its own file because the conversion is per-call-site:
a Path is a headed object, so a runtime entry point taking `const char *` must
receive `fastpy_path_str(p)`, not the Path pointer. Codegen does this with
`_emit_path_text_arg`; **any new runtime entry point that takes a path string
must emit its argument the same way.** Miss one and the callee reads the
header — historically answering about a file literally named `PATH` — which is
silent, per-call-site, and invisible to a suite written with string paths.

## Tests

`tests/` mixes two things: fastpy *programs* used as differential fixtures
(`test_getenv.py`, etc.) and real **pytest driver modules**
(`test_differential.py`, `test_full_suite.py`, `test_comprehensive.py`,
`test_cross_target.py`). Config in `pyproject.toml` (`[tool.pytest.ini_options]`).

## Git workflow (project rule)

Never `git push` from this working directory. The user pushes by copying files to
`D:\github\fastpy` and pushing there. Committing locally is fine.
