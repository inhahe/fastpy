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

## 2. Type-specialized slots (full native slot layout) — ✅ DONE

Full two-region slot layout implemented. Object memory layout after the
56-byte FpyObj header:

    [native region: n_native × i64 (8 bytes each)]
    [boxed region:  n_boxed × FpyValue (16 bytes each)]

Monomorphic scalar attributes (int, float, bool) detected via
`_detect_class_int_attrs` / `_detect_class_float_attrs` /
`_detect_class_bool_attrs` are placed in the native region as raw i64
values (no tag overhead). Non-scalar attributes remain in the boxed
region as full FpyValue {tag, data} pairs.

What's done:
- `_assign_attribute_slots` partitions attrs into native vs boxed
- `_emit_slot_addr_direct` computes addresses for both regions
- `_emit_slot_get_direct` / `_emit_slot_set_direct` handle native slots
  (raw i64 load/store, tag reconstructed from `native_slot_tags[]`)
- `fastpy_obj_new` initializes native slots to 0, boxed to {NONE, 0}
- `_is_mono_scalar` optimization: skip tag store on non-first writes
  (tag never changes for scalar slots after initial write in __init__)
- `_fresh` optimization: first store in __init__ skips old-value decref
  (slot guaranteed to be zero-initialized)
- FpyClassDef extended with `n_native_slots`, `native_slot_tags[16]`
- GC scanner skips native slots (scalars can't form reference cycles)
- Per-class `acyclic` flag: all-scalar classes skip GC tracking entirely

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
- Vtable inlining for the polymorphic dispatch case — only matters when
  the receiver class isn't statically known, which is uncommon in practice
