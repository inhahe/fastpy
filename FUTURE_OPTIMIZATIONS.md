# fastpy future optimization plans (deferred)

Context: after the Phase A-F refactoring, these remaining optimizations
were identified but deferred because their absolute gains are small
(diminishing returns). The compiler currently hits ~250x CPython on tight
int loops and 10-280x on class-heavy code; attribute access is already
at native struct speed. Revisit these if profiling shows a bottleneck.

## 1. Direct struct IR access — ✅ DONE (Phase 8)

Replaced `fastpy_obj_get_slot`/`fastpy_obj_set_slot` calls with inline
GEPs in `_emit_slot_addr_direct()`. FpyObj struct slimmed from 1560 → 24
bytes in Phase 21 (dynamic attrs moved to lazily-allocated side table).

## 2. Type-specialized slots (monomorphic native storage) — ✅ PARTIALLY DONE

Conservative approach implemented: for monomorphic scalar slots (float,
bool) detected via `_per_class_float_attrs` / `_per_class_bool_attrs`,
skip the tag store and all refcounting (rc_incref/rc_decref) on writes.
The read path already used `_emit_slot_get_data_only` (Phase 9) to skip
the tag load for statically-typed accesses.

What's done:
- `_emit_slot_set_direct` accepts `skip_tag=True` for scalar slots
- `_emit_attr_store` detects monomorphic scalar self.attr stores
- Saves 2 memory loads (old tag+data) + 1 function call (rc_decref) +
  1 memory store (tag) per scalar attribute write

What's NOT done (full native slots):
- Slot memory layout unchanged (still FpyValue {tag, data} = 16 bytes)
- Could split into native-typed section (8 bytes) + boxed section
- Would require C runtime changes (fastpy_obj_new, GC scanner)
- Deferred: the conservative approach captures most of the perf gain

## 3. Vtable dispatch — ✅ DONE

Implemented as part of the Phase A-F refactoring. Each class gets a vtable
array in `FpyClassDef`, methods assigned fixed indices at class declaration.
Inherited methods share indices with parent. Runtime dispatch is
`obj->class->vtable[method_idx](obj, args)` — O(1).

Also includes CHA (Class Hierarchy Analysis) for devirtualization: when a
method has only one implementation across all classes, calls are inlined
directly without vtable lookup.

## 4. Native-typed method parameters (eliminate i64 coercion) — ✅ DONE

When call-site analysis (CSA) confirms ALL call sites pass float for a
parameter, the method is declared with `double` instead of `i64`. The
method body receives the native double directly — no i64→double bitcast
at entry. An `.__n64` wrapper function is auto-generated for vtable
dispatch (runtime dispatch still uses the i64 ABI).

Also eliminates `set_arg_tag` / `get_arg_tag` calls for native-typed
params in both direct dispatch and CHA dispatch paths — the type is
statically encoded in the LLVM function signature.

Benchmarks:
- Vec3 dot+update 500K: 3.0ms (vs 562ms CPython = 187x)
- dist_sq float 1M: 4.2ms (vs 444ms CPython = 105x)

## 5. Whole-program method devirtualization + inlining — ✅ MOSTLY DONE

Investigation revealed direct dispatch and CHA dispatch already produce
direct calls to named `ir.Function`s with `internal` linkage — LLVM CAN
and does inline these (methods ≤50 AST nodes get `alwaysinline`, ≤120
get `inlinehint`). The remaining overhead was the `set_arg_tag` /
`get_arg_tag` ceremony per call, which is now eliminated for native-typed
params (Optimization #4).

Only vtable dispatch (polymorphic calls) goes through an indirect function
pointer that LLVM cannot inline. Speculative devirt already handles the
2-4 implementation case with a class_id switch + direct calls.

## What's left

All major optimizations are now implemented. The remaining gap to C++ is:
- Full native slot layout (changing FpyValue slots to raw typed storage)
  — requires C runtime changes, marginal gain over the conservative approach
- Vtable inlining for the polymorphic dispatch case — only matters when
  the receiver class isn't statically known, which is uncommon in practice
