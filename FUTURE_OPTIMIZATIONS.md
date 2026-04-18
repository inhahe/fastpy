# fastpy future optimization plans (deferred)

Context: after the big correctness + optimization session, these remaining
optimizations were identified but deferred because their absolute gains are
small (diminishing returns). The compiler currently hits ~147x CPython on
tight int loops and 8-22x on class-heavy code; attribute access is already
at ~1.5ns/op (near native struct speed). Revisit these if profiling shows
attribute access is still a bottleneck.

## 1. Direct struct IR access — ✅ DONE (Phase 8)

Replaced `fastpy_obj_get_slot`/`fastpy_obj_set_slot` calls with inline
GEPs in `_emit_slot_addr_direct()`. FpyObj struct slimmed from 1560 → 24
bytes in Phase 21 (dynamic attrs moved to lazily-allocated side table).

## 2. Type-specialized slots (monomorphic native storage)

When an attribute is provably always one type (float, int, bool, str),
store it as the native type without the FpyValue tag:

- `class Point: def __init__(self, x, y): self.x = x; self.y = y`
  where call sites always pass floats → `x` and `y` are native doubles.

Design:
- Detect monomorphic attrs during slot assignment pass
- Mark slot as "native float" / "native int" / "native ptr" / etc.
- Allocate slot storage as `double[]` / `int64_t[]` / `void*[]` based on types
- Codegen emits direct typed load/store instead of FV tag+data pair
- Falls back to FV representation if an assignment violates monomorphism
  (option A: reject at compile time; option B: reserve extra bit for
   "boxed" state that promotes the slot when needed)

Expected gain: ~1ns per monomorphic access (skip tag check + no
extract/insert of the union). Also saves memory: typed slots are 8 bytes
instead of 12 (tag + data).

Risk: significant compiler complexity; monomorphism analysis must be
conservative or handle demotion correctly.

## 3. Vtable dispatch (for the remaining dynamic method calls)

Still not done. Direct dispatch already handles ~95% of method calls
(when class is statically known). For the remaining cases (polymorphic
calls on list-of-mixed-classes, function params without class info),
dispatch goes through `obj_call_methodN` which does name lookup.

A vtable would:
- Assign each method a fixed index at class declaration
- Inherited methods share indices with parent
- Runtime dispatch becomes `obj->vtable[method_idx](obj, args)`
- O(1) instead of O(N) linear scan

Expected gain: ~3ns per polymorphic method call (skip name scan).
Risk: low — similar structure to the existing slot work.

## 4. Native-typed method parameters (eliminate i64 coercion)

Method calls currently pass all non-self args as i64, then the method
body coerces them back to the expected type (inttoptr for pointers,
bitcast for floats). For methods where parameter types are known from
call-site analysis (the common case with direct dispatch), this
round-trip is wasted work.

Design:
- When declaring a method, if ALL call sites agree on param types,
  declare with native LLVM types (i64, double, i8*) instead of i64
- At direct-dispatch call sites, pass bare values directly
- Keep i64 ABI for runtime dispatch (`obj_call_methodN`) as fallback
- May need two entry points per method: native (for direct calls)
  and i64 (for runtime dispatch)

Expected gain: ~2-4ns per method call (skip coercion per arg).
On dist_sq benchmark: ~4 args coerced → ~8-16ns savings → 12ns → ~4ns
(approaching C++ struct method speed).

Risk: medium — need to handle the dual-entry-point cleanly and ensure
the right one is called. Similar to function monomorphization but for
methods.

## 5. Whole-program method devirtualization + inlining

Currently LLVM can't inline method bodies even with direct dispatch
because the function is called through a separately-compiled function
pointer. If the method body were emitted at the call site (or marked
`alwaysinline` with guaranteed direct calls), LLVM could inline and
optimize across the method boundary.

Design:
- For small methods (< ~20 AST nodes) with direct dispatch, emit
  the method body inline at the call site instead of calling through
  a function pointer
- Or: ensure the direct-dispatch function pointer is visible to LLVM
  as a known constant (not loaded from a global), enabling LLVM's
  own inliner
- The `inlinehint` attribute (Phase 26) is already added but doesn't
  help when LLVM can't resolve the call target

Expected gain: eliminates ALL per-call overhead for small methods.
On dist_sq: method body inlined → 4 attr accesses become 4 GEPs →
LLVM can hoist loop-invariant reads → near-zero cost.

Risk: code size increase for frequently-called small methods.
Must not apply to recursive or very large methods.

## Why these aren't urgent

The compiler already hits ~280x CPython on inlinable functions and
18-37x on class-heavy code. The remaining gap to C++ (~4x on method
calls) comes from optimizations #4 and #5. They're worth doing if
the target is truly native-speed OOP, but for most Python programs
the current speed is more than sufficient.
