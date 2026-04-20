# fastpy — AOT Python Compiler

## Project Overview

AOT compiler for a strict superset of Python, targeting LLVM via llvmlite.
Produces native executables from Python source. Full CPython compatibility
for the default language; opt-in machine integer types (UInt32, Int32, etc.)
for performance-critical code.

**Motivation:** The user is building a production-quality OS intended to
compete with Linux, macOS, and Windows. The OS uses a microkernel
architecture with compiled Python (fastpy) for userspace services and
applications, Rust for the kernel core and general drivers, and Ada/SPARK
for formally-verified kernel-space drivers on the critical path. The
compiler exists to make Python fast enough for OS-level userspace work.

## File Map

| File/Dir | Role |
|----------|------|
| `compiler/` | The compiler itself (Python) |
| `compiler/pipeline.py` | Main compilation pipeline: source -> parse -> analyze -> codegen -> link |
| `compiler/__main__.py` | CLI entry point: `python -m compiler source.py -o output [-t] [--threading {none,gil,free}]` |
| `fastpy/` | CPython shim package — provides opt-in types that work under both CPython and the compiler |
| `fastpy/ints.py` | Fixed-width integer types: Int32, UInt32, Int64, UInt64 |
| `runtime/` | C runtime (GC, BigInt, containers, threading) — linked into compiled binaries |
| `runtime/threading.h` | Threading primitives: mutex, condvar, atomics, GIL, TLS macros |
| `runtime/threading.c` | GIL implementation, print mutex |
| `tests/harness.py` | Differential test engine: runs programs under CPython and compiler, compares output |
| `tests/conftest.py` | Pytest fixtures and auto-collection of test program files |
| `tests/test_differential.py` | Inline differential tests covering language features |
| `tests/test_generated.py` | Hypothesis-based random program tests |
| `tests/test_shim.py` | Tests for the fastpy CPython shim types |
| `tests/generator/gen.py` | Random valid Python program generator |
| `tests/programs/` | Hand-written test programs (auto-discovered by pytest) |
| `tests/regressions/` | Regression test programs (auto-discovered by pytest) |

## Architecture

### Compiler pipeline (future)

```
source.py -> ast.parse() -> typed IR -> optimized IR -> LLVM IR -> native binary
```

The pipeline stub in `compiler/pipeline.py` reports what it can't compile yet.
As features are implemented, tests automatically transition from SKIP to PASS.

### Testing Strategy

The primary correctness mechanism is **differential testing against CPython**.
Every test program is run under both CPython and the compiled binary; any
output difference is a compiler bug. The user will NOT manually review
compiler code — correctness relies entirely on automated testing.

Three test outcomes:
- **PASS**: compiled output matches CPython
- **SKIP**: compiler can't handle this program yet (not a bug)
- **FAIL**: compiled output differs from CPython (always a bug)

Testing layers:
1. **Differential tests** — hand-written and auto-discovered Python programs
   run under both CPython and the compiler, outputs compared
2. **Property-based tests** — Hypothesis generates random valid Python programs,
   feeds them through the differential harness
3. **Regression tests** — every bug found gets a test in `tests/regressions/`
4. **Runtime assertion mode** (future) — debug builds emit checks that verify
   the compiler's own assumptions (e.g., devirtualization type checks)
5. **Shim tests** — verify the CPython shim types produce correct fixed-width
   arithmetic (the reference behavior the compiler must match)

### Adding a test

**Inline test**: Add a method to the appropriate class in `test_differential.py`:
```python
def test_my_feature(self, assert_compiles):
    assert_compiles("print(my_feature_code)")
```

**Program test**: Drop a `.py` file in `tests/programs/` or `tests/regressions/`.
It will be auto-discovered and run through the differential harness.

### Running tests

```bash
python -m pytest tests/ -v          # full suite
python -m pytest tests/ -v -x       # stop on first failure
python -m pytest tests/test_shim.py # just the shim tests
```

### Threading

Three compile-time modes, selected via CLI flag:

| Mode | Flag | Runtime behavior |
|------|------|-----------------|
| Single-threaded | `--threading none` (default) | No locks, no TLS overhead |
| GIL | `--threading gil` | Global lock, one thread at a time (matches CPython) |
| Free-threaded | `--threading free` or `-t` | Per-object locks, true parallelism (matches CPython 3.13t) |

**Architecture:**
- `fpy_threading_mode` global (0/1/2) emitted by codegen, read by runtime
- Exception state is always thread-local (`__declspec(thread)` / `__thread`)
- Bump allocator is always per-thread (each thread gets its own arena chain)
- GIL: mutex + condvar in `threading.c`, acquired by main thread at startup,
  released around CPython bridge calls (`FPY_BRIDGE_ENTER/LEAVE`)
- Free-threaded: `fpy_mutex_t lock` field on FpyObj, FpyList, FpyDict;
  `FPY_LOCK/FPY_UNLOCK` macros wrap mutations (no-op in other modes)
- Native function wrapper: `fpy_cpython_wrap_native` creates a CPython
  callable from a compiled function pointer, enabling
  `threading.Thread(target=compiled_func)`
- Keyword argument support in CPython bridge: `fpy_cpython_call_kw` /
  `fpy_cpython_call_kw_raw` handle `target=func` style calls

**Key files:** `runtime/threading.h` (primitives), `runtime/threading.c`
(GIL impl), `compiler/__main__.py` (CLI flags).

---

## Language and Compiler Design Decisions

This section documents all design decisions and the reasoning behind them,
worked out over an extended design conversation. It serves as the authoritative
reference for why the compiler is built the way it is.

### 1. The language is a strict superset of Python

Any valid Python program is valid fastpy. The compiler adds opt-in features
(machine integer types, annotations for optimization) but never changes
Python semantics for code that doesn't use those features. This means:

- **CPython is the interpreter tier.** Users iterate and debug under CPython
  with instant startup, normal PDB, normal IDE integration. The compiler is
  only invoked for production builds or benchmarking. No need to build a
  REPL, debugger, package manager, or interactive development environment.
- **CPython is the test oracle.** For any program, the correct output is
  whatever CPython produces. Differential testing catches bugs automatically.
- **The entire Python ecosystem is inherited.** pip, pytest, mypy, Jupyter,
  every IDE — all work unchanged.

### 2. What blocks static compilation of Python, and how we handle each

Static compilation of Python is blocked by a small set of features that
prevent knowing at compile time what an operation means. Here is each
blocker and our approach:

**eval() / exec() / compile() on arbitrary strings.**
These can introduce new names, classes, and methods at runtime. Our approach:
treat any new binding created by these as untrackable, routed through a
fallback name-keyed dictionary. The bigger issue is that eval/exec require
an embedded compiler or interpreter to work — we accept this and will
optionally link a small interpreter for programs that use eval. Every global
access after an eval call becomes a dict lookup (pessimized). Programs that
don't use eval pay nothing.

**Monkey-patching of classes and modules (SomeClass.method = other_fn).**
Our approach: whole-program closed-world analysis. The compiler sees all
modules at once and can prove whether a class or module attribute is ever
mutated from outside. If it is, that attribute becomes a pointer/dict entry
(indirect dispatch). If it isn't, it becomes a direct call/access (zero
overhead). For attributes the compiler can't prove are stable, it uses a
tiered dispatch hierarchy — the same design as V8's hidden classes / PyPy's
map transitions. The tiers are two independent axes (lookup method x value
indirection), producing four combinations:

  | | Direct value | Indirect (pointer) |
  |---|---|---|
  | **Static offset** (no lookup) | Tier 1: struct field / direct call. Zero overhead. | Tier 2: one extra load to follow pointer. ~3-5 cycles. Like C++ vtable dispatch. |
  | **Dict lookup** (string key) | Tier 3: dict lookup, then use value. | Tier 4: dict lookup, then follow pointer. |

  - **Tier 1** (static offset, direct value): the compiler proved the
    attribute is never mutated and the class is sealed. Access is a single
    load at a known byte offset. Method calls are direct `call` instructions.
    Identical to C struct field access. Zero overhead.
  - **Tier 2** (static offset, indirect pointer): the compiler knows the
    slot exists at a fixed offset, but can't prove the value isn't swapped
    at runtime (e.g., `MyClass.method = other_fn` might happen). The slot
    holds a function pointer. Access is two loads: one for the slot, one
    to follow the pointer. This is exactly C++ vtable dispatch. Cost: ~3-5
    cycles vs ~1 for Tier 1, well-predicted by the branch predictor.
  - **Tier 3** (dict lookup, direct value): the attribute name is looked up
    in the object's `__dict__` at runtime. Used when the compiler can't
    prove the attribute exists at a static offset (e.g., dynamically added
    attributes). Cost: hash + probe + comparison.
  - **Tier 4** (dict lookup, indirect pointer): dict lookup, and the value
    is itself a pointer that may be swapped. Used for fully dynamic methods
    on fully dynamic classes. Rarest tier.

  The compiler assigns each attribute the cheapest tier it can prove safe.
  Most attributes in typical code land at Tier 1 (sealed class, proven
  stable). Tier 2 covers the "probably stable but can't prove it" case.
  Tiers 3-4 are fallbacks for genuinely dynamic code.

  **Parallel dict for getattr/setattr:** Even for Tier 1/2 attributes with
  static offsets, a parallel dict entry is maintained if the compiler can't
  prove that no `getattr(obj, variable)` or `setattr(obj, variable, val)`
  call with an arbitrary string argument reaches the class. The fast path
  still goes through the static offset; the dict is only consulted on the
  getattr/setattr code path. If the compiler CAN prove no dynamic
  getattr/setattr reaches the class (which is the common case), the dict
  is omitted entirely. Memory cost when present: one pointer per attribute
  per class (not per instance), usually negligible.

**Stack frame introspection (sys._getframe, inspect.currentframe).**
Fundamentally incompatible with register allocation if handled naively.
Our approach: deoptimization tables (same technique as V8, HotSpot, LuaJIT).
The compiler emits side tables mapping safepoint PCs to source-level variable
locations. When someone calls sys._getframe(), the runtime reconstructs a
synthetic frame from the machine state. Cost: compile-time bookkeeping and
binary size overhead for the side tables, but zero runtime cost when
introspection is not used. For v1, we may simply not support frame
introspection and skip the deopt tables entirely.

**Writable globals() and locals().**
globals(): module globals are already dict-backed; globals() just exposes
that dict. The compiler decides when to cache a global reference vs. going
through the dict.
locals(): handled via PEP 667 semantics (Python 3.13+). locals() returns a
write-through proxy; reads see current fast locals, writes go to an overlay
dict. The compiler can still register-allocate fast locals because the
function itself never reads from the overlay. Deleting keys is only allowed
for dynamically-added keys.

**Metaclasses with custom __call__ / __instancecheck__ / __subclasscheck__.**
Makes isinstance() non-trivial and construction return type unpredictable.
Our approach: for classes with standard metaclasses (the vast majority), the
compiler devirtualizes normally. For classes with custom metaclasses:
  - Attributes declared in `__slots__` still get static offsets (Tier 1 or
    2) — `__slots__` explicitly declares the attribute set, so the compiler
    knows the layout even with a custom metaclass.
  - Attributes NOT in `__slots__` (anything that would go in `__dict__`)
    use dict-based dispatch (Tier 3 or 4).
  - Only classes with a custom metaclass AND no `__slots__` need fully
    dict-based dispatch on all attributes.
  - `isinstance()` calls out to `__instancecheck__` on the metaclass,
    which is a function call (can't be lowered to a type-tag check). Same
    for `issubclass()` via `__subclasscheck__`.
  - `MyClass(...)` dispatches through `type(MyClass).__call__()`, which
    can return any type — construction return type is not statically known.

**Dynamic class creation via type(name, bases, dict).**
Our approach: if the compiler can track the name and bases at compile time,
it generates a static class with a pre-computed layout. If it can't track
bases, it uses a runtime class-creation path:
  - MRO (C3 linearization) is computed once when the class is created and
    cached as a tuple on the class object. This is what CPython itself does.
    Dynamic bases don't cost per-call, only per-class-creation.
  - If we can track the `dict` parameter's keys at compile time (even if
    not the values), we know the attribute names and can assign static slot
    indices. Values become Tier 2 (function pointers) rather than Tier 1.
  - If we can track only the values (but not the keys), we need dict lookup
    but can use direct calls once resolved.
  - If we can't track either, full Tier 4 dispatch.
  - For single/linear inheritance, attribute offsets are fixed and monotonic
    down the hierarchy — trivial to compile, no MRO overhead at all.
  - For multiple inheritance, C3 linearization determines method resolution
    order. The MRO is computed once per class and cached. Method dispatch
    walks the cached MRO. Diamond hierarchies may require adjusting
    attribute offsets per subclass (similar to C++ virtual inheritance).
  - For v1, we may simply not optimize dynamically-created classes and
    fall back to dict-based dispatch for all their attributes.

**Import hooks and import-time side effects.**
These are not an independent blocker — imports are just code execution, and
if we've handled monkey-patching and eval, we've handled imports. The
ordering concern is no different from normal program-order.

### 3. Integer type system

**Default int: Python's BigInt-capable int.** Full CPython compatibility.
The compiler uses speculative unboxing on the fast path: assume small int,
do machine arithmetic, check overflow flag, fall back to BigInt heap
allocation on overflow. Per-operation cost: ~10-30% slower than raw machine
int due to overflow check branch (but branch predictor hides most of it).
Range analysis can prove many variables stay in small-int range and eliminate
the check entirely.

**Opt-in unchecked machine int types: UInt32, Int32, UInt64, Int64.**
Used via `from fastpy import UInt32` etc. These are raw machine integers
with wraparound semantics (no overflow check, no BigInt fallback). They
exist for:
  - Hash functions, cryptographic primitives, CRC/checksums
  - Bit manipulation with fixed-width semantics
  - Performance-critical numeric loops where SIMD vectorization matters
Under CPython, these are provided by a shim package with faithful
wraparound arithmetic via masking. Under the compiler, they're raw
machine registers.

**No separate "checked int" type in v1.** We considered a type that uses
machine-width integers but raises OverflowError instead of wrapping. We
decided against it for v1 because:
  - The per-op cost of a checked int is nearly identical to the default
    int's overflow-check-with-BigInt-fallback (~2 instructions either way)
  - The main advantage of checked int (guaranteed dense representation,
    enabling SIMD) can often be recovered via range analysis on default ints
  - Simplifying the type system reduces implementation and testing burden
  - Can be added later if real workloads demonstrate the need

**Why not BigInt everywhere?** BigInt-only (no machine int opt-in) would
leave 4-16x performance on the table for numeric loops due to lost SIMD
autovectorization. The unchecked machine int types are what close the gap
to C speed for numeric code.

**Why not machine int by default (like Julia)?** That would silently change
Python semantics — 2**100 would overflow instead of working. Full Python
compatibility requires BigInt as the default. Users who want machine-int
speed annotate explicitly.

### 4. Performance expectations

With the full compiler implemented (whole-program analysis, type inference,
tiered dispatch, LLVM backend, speculative unboxing, range analysis):

| Code type | vs CPython | vs C/C++ |
|-----------|-----------|----------|
| Tight numeric loops (annotated with machine ints) | 50-200x faster | C speed (sometimes faster via autovectorization) |
| Numeric loops (unannotated, range analysis succeeds) | 20-50x faster | C speed |
| Numeric loops (unannotated, range analysis fails) | 10-20x faster | ~1.3-2x slower (tagged int overhead) |
| OO business logic (annotated hot paths) | 15-40x faster | ~1.1-1.3x slower (same as C++ with virtual methods) |
| OO business logic (unannotated) | 10-30x faster | ~1.2-1.5x slower |
| Dict-heavy code | 10-20x faster | ~1.2-1.5x slower (insertion-order preservation cost) |
| String-heavy code | 5-15x faster | ~1.0-2x slower (Unicode vs byte strings) |
| Float-heavy code | 20-50x faster | ~1.0-1.1x (IEEE 754 is the same everywhere) |

**Key insight:** most of the residual gap vs C++ is not a "Python tax" — it's
the cost of safety features (bounds checks, GC write barriers) and richer
semantics (ordered dicts, Unicode strings) that C++ also pays when it uses
equivalent data structures. The compiler doesn't make Python slower than
equivalent C++; it makes Python roughly as fast as C++ that uses the same
safety guarantees and data structure choices.

**Attribute lookup** is essentially free for typical code — sealed classes with
known layouts become struct field accesses at known offsets, identical to C.

**Method dispatch** is free for monomorphic call sites (direct call, no vtable).
Polymorphic sites use vtable dispatch, same cost as C++ virtual methods.

### 5. Compiler implementation language: Python

The compiler itself is written in Python, using llvmlite for LLVM IR
generation. Reasons:

- **Fast iteration.** Edit-test cycle is 1-3 seconds (no build step). This
  is critical for AI-assisted development where the bottleneck is
  edit-test-fix cycle count.
- **Self-hosting-adjacent.** The compiler compiles Python; tests for the
  compiler are Python programs. Everything is the same language.
- **llvmlite is production-quality.** Numba ships it and uses it for real
  JIT compilation. It exposes enough of LLVM for a full AOT compiler.
- **The compiler's speed doesn't matter.** Users run it once to build;
  the runtime speed is what matters. A slower compiler that produces
  equally fast binaries is fine.
- **AI-assisted development is fastest in Python.** The feedback loop per
  edit is seconds, not minutes.

### 6. Runtime implementation language: C

The runtime (GC, BigInt, containers, string handling, exception unwinding)
is written in C. It links into every compiled binary. Reasons:

- **Universal ABI.** Every language on every platform can call C functions
  directly. The OS kernel is in Rust, which calls C via `extern "C"`
  blocks (trivial). C ABI is the universal interop point between the
  compiled Python userspace, the C runtime, and the Rust kernel.
- The runtime is small (~5-15k lines), low-level, and heavily tested by
  the differential test infrastructure. Rust's safety guarantees add less
  value here than they would in a larger codebase, and the FFI friction
  of exposing Rust internals via `extern "C"` wrappers is not worth it.

### 7. Why LLVM (via llvmlite) rather than transpiling to C

We considered transpiling to C instead of generating LLVM IR directly.
Both are viable (Nim transpiles to C and gets excellent performance).
We chose LLVM because:

- **GC integration.** LLVM has `gc.statepoint` and `gc.relocate` intrinsics
  for precise stack maps. In C, you'd need conservative stack scanning
  (slower) or shadow stacks (overhead on every function).
- **Exception handling.** LLVM has first-class zero-cost exception handling
  via `landingpad`/`invoke`. C requires `setjmp`/`longjmp` (slow) or
  compiler-specific extensions.
- **Precise aliasing information.** LLVM's `noalias` metadata lets the
  optimizer reason about what doesn't alias. C's `restrict` is limited
  to function parameters.
- **Tail calls.** LLVM's `musttail` guarantees TCO. C doesn't guarantee it.
- **SIMD.** LLVM has target-independent vector types. C has per-compiler
  intrinsic headers.
- **No double-parse.** Direct IR generation is faster than emitting C text
  and re-parsing it.

The performance difference between the two approaches is typically 5-15%.
The engineering advantage of LLVM direct is larger for a GC'd language
with exceptions.

Note: Clang IS an LLVM frontend — "through LLVM" uses the exact same
backend as C/C++ compiled with Clang. LLVM produces native machine code,
not bytecode. There is no interpreter or VM in the output.

### 8. Conservative analysis ("sound but incomplete")

The compiler uses conservative analysis that deliberately misses some
optimization opportunities in exchange for never producing wrong code.

#### Full list of analyses

These are all the analyses the compiler will eventually perform. Each
enables specific optimizations. LLVM handles some at the IR level; our
frontend handles the Python-specific ones.

**Frontend analyses (Python-specific, we implement these):**
- **Range analysis / interval analysis** — track possible value ranges of
  integer variables through the program. Proves: no overflow (enabling
  unboxing to machine int), index in bounds (enabling bounds check
  elimination), value non-negative (enabling unsigned operations).
- **Type inference** — infer the concrete type of every expression without
  requiring user annotations. Proves: what methods/attributes exist,
  whether a value can be None, whether a container is homogeneous.
- **Devirtualization** — prove a call site is monomorphic (single concrete
  type). Enables: direct call instead of vtable/dict dispatch, inlining
  of the target function.
- **Sealed class detection** — prove no subclass of a class exists or can
  be created anywhere in the program. Enables: fixed object layout,
  direct attribute access, direct method calls.
- **Escape analysis** — prove an object doesn't outlive its creating
  function and isn't stored in any container or captured by a closure.
  Enables: stack allocation instead of heap allocation, elimination of
  GC overhead for that object.
- **None/null elimination** — prove a variable is never None on a given
  code path. Enables: elimination of None checks before attribute access
  or method calls.
- **Write barrier elision** — prove a store doesn't need a GC write barrier
  (e.g., storing into a newly-created object the GC hasn't seen yet, or
  storing a value that's already reachable from roots). Enables: skipping
  the GC card-table mark on writes.
- **Aliasing analysis** (Python-level) — prove two references don't point
  to the same object. Enables: reordering of loads/stores, hoisting
  computations out of loops.
- **Constant folding / propagation** — evaluate expressions whose inputs
  are all known at compile time. Includes tracking "effectively constant"
  module-level variables.

**LLVM-level analyses (LLVM does these for us on the generated IR):**
- Dead code elimination
- Constant folding at the instruction level
- Loop-invariant code motion (LICM)
- Inlining (after our frontend has resolved call targets)
- Autovectorization (SIMD)
- Register allocation
- Instruction scheduling and selection

#### Conservative coverage vs. implementation complexity

For each analysis, there's an "obvious yes" region, an "obvious no"
region, and a "maybe with careful analysis" region. We take only the
obvious cases first:

| Analysis | "Obvious yes" coverage | Implementation complexity |
|----------|----------------------|--------------------------|
| Devirtualization | ~70-85% of opportunities | ~20% of full analyzer |
| Bounds check elimination | ~60-80% | ~15% |
| Unboxing / range proofs | ~70% of loop counters/indices | ~20% |
| Escape analysis (stack alloc) | ~50-70% | ~15% |
| Write barrier elision | ~40-60% | ~10% |

A conservative-first analyzer lands at ~60-75% of peak performance for
~15-25% of the implementation complexity. That's ~1.5-2.5x of C++ instead
of ~1.1-1.3x, but with dramatically less engineering effort and dramatically
lower risk of soundness bugs.

#### Conservative no-go paths

Each analysis has an **early bail-out threshold**: if the situation looks
too complex to prove safe with the current analysis depth, immediately
take the slow path rather than attempting a deeper (and potentially buggy)
proof. Examples:

- Devirtualization: if the receiver type flows through more than N function
  calls, bail out and use vtable dispatch.
- Range analysis: if a variable's range depends on a loop whose bound is
  another variable with unknown range, bail out and keep the overflow check.
- Escape analysis: if the object is passed to any function that isn't
  inlined, bail out and heap-allocate.

These bail-out thresholds are **always suppressible**: the user can force
the fast path via annotations (see section 9), or force the slow path
via `@dynamic` / `@no_optimize`, or configure per-file/per-project which
analyses to skip entirely (see section 10).

Later, we can add more sophisticated analyses for the cases that currently
bail out, but they'll always remain suppressible when the user wants fast
compilation or wants to avoid depending on a complex proof.

#### The "ratchet" approach

Ship v1 with the simplest analyses. Profile real workloads. Strengthen
the specific analyses that would pay off most. Each step is:
- **Testable in isolation** — turn the new analysis on/off and compare
  outputs against CPython
- **Recoverable** — if the new analysis is buggy, revert to the previous
  conservative version
- **Driven by real data** — strengthen the analyses that matter for real
  code, not the ones that look clever in theory

Never build a sophisticated analyzer upfront.

#### User annotations recover the lost ground

The 25-40% of performance left on the table is concentrated in a small
number of hot functions. Users annotate those with `@sealed`, `@final`,
explicit machine-int types, etc. The annotations are CPython-compatible
(see section 9) and optional.

### 9. Annotations are CPython-compatible

All compiler hints are expressed as standard Python constructs that CPython
can parse and run (even if it ignores their optimization meaning):

- **Type hints** (PEP 484): `def f(x: Int32) -> Int32:` — CPython evaluates
  the annotation but doesn't act on it.
- **Decorators**: `@sealed`, `@final`, `@inline` — in CPython these are
  identity functions. In the compiler they're optimization directives.
- **Importable wrapper classes**: `x = UInt32(5)` — in CPython this is a
  shim class with faithful arithmetic. In the compiler it's a raw machine int.
- **`__slots__`**: already part of Python, already means "fixed attribute set."
  The compiler attaches additional meaning (sealed layout).
- **Module-level imports**: `from fastpy import ...` — CPython imports the
  shim; the compiler recognizes the import as a directive.

No comments, no pragmas, no special syntax. Everything is a regular Python
construct. The shim package (`fastpy/`) provides the CPython-side
implementations.

**Fast-path annotations** (user asserts facts the compiler can't prove,
forcing the fast path — user takes responsibility for correctness):
- `@sealed` — no subclasses exist or will be created. Enables: fixed
  layout, direct dispatch, no vtable.
- `@final` — method is not overridden by any subclass. Enables: direct
  call, inlining.
- `@inline` — inline this function at call sites. Enables: cross-function
  optimization.
- `@no_escape` — return value doesn't escape the caller. Enables: stack
  allocation.
- Explicit machine-int types (`UInt32`, `Int32`, etc.) — value is a
  fixed-width machine integer. Enables: unboxing, SIMD.

**Slow-path annotations** (user forces the compiler to skip optimization,
useful for working around compiler bugs, speeding up compilation, or
documenting intentionally dynamic code):
- `@dynamic` — don't try to seal or devirtualize this class. All attribute
  access goes through dict dispatch.
- `@no_inline` — don't inline this function, even if the compiler wants to.
- `@no_optimize` — skip all analyses on this function/class. Emit the
  safest, most conservative code.

Both directions are optional. Unannotated code gets whatever the
compiler's automatic analysis can prove.

**Shim design for unchecked int types:** The CPython shim implements faithful
fixed-width wraparound arithmetic via bit-masking (`result & 0xFFFFFFFF`).
This is important because unchecked ints are often used for hash functions
and crypto where the wraparound IS the algorithm — a transparent wrapper
around Python int would produce wrong values. The shim is pure Python for
now; a C extension will replace it for better CPython-mode performance.

### 10. Compile-time flags and per-file optimization levels

Compile times will be substantial (LLVM optimization is slow, whole-program
analysis is slow). Mitigations at three granularity levels:

**Project-level flags** (set in a project config file or CLI args):
- **Optimization level** (`-O0` through `-O3`):
  - `-O0`: no analysis, no optimization, fastest possible compilation.
    Every call is indirect, every int is tagged, every attribute is a dict
    lookup. Useful for "does it compile at all?" testing.
  - `-O1`: local analysis only (within a single function). Type inference,
    basic constant folding, basic devirtualization. No whole-program work.
    Fast compilation, moderate speedup.
  - `-O2`: whole-module analysis. Devirtualization across functions within
    a module. Range analysis. Escape analysis. Default for most builds.
  - `-O3`: whole-program closed-world analysis. Cross-module devirtualization,
    aggressive inlining, full range analysis, LLVM `-O3`. Slowest
    compilation, best runtime performance. For release builds.
- **Analysis toggles**: explicitly enable/disable specific analyses
  project-wide. E.g., `--no-escape-analysis` to skip escape analysis
  everywhere (faster compilation, no stack allocation optimization).
  `--no-range-analysis` to skip range proofs (faster compilation, all
  ints keep overflow checks). These are mainly useful during compiler
  development (to isolate bugs) and for users who want fast builds.
- **Debug assertion mode**: `--debug-assertions` emits runtime checks
  verifying the compiler's analysis assumptions. Slower binaries but
  catches soundness bugs.

**File-level flags** (set via a decorator or module-level call):
- `from fastpy import optimize_level; optimize_level(3)` — override the
  project optimization level for this file only. Mark hot files for
  aggressive optimization; leave cold files at `-O0` or `-O1`.
- `from fastpy import skip_analysis; skip_analysis('escape', 'range')` —
  skip specific analyses for this file. Useful when a file is known to be
  all-dynamic or when the user wants to speed up incremental builds.

**Incremental compilation with analysis caching**: only re-analyze files
that changed (and their dependents). Cache type inference, range analysis,
devirtualization results per file. Dependency tracking is by import graph.

**Pragma-based hints** (per-function or per-class): `@sealed`, `@final`,
`@no_optimize`, etc. (see section 9). These let the user force fast or
slow paths on individual code elements, skipping the analysis entirely.

Note: compile-time cost applies only to production builds. For development
iteration, users run code under CPython (instant startup). The compiler is
invoked at release-build frequency, not save-and-run frequency.

### 11. No manual code review — testing is the correctness mechanism

The user will not manually review AI-generated compiler code. Correctness
relies entirely on automated testing infrastructure:

1. **Differential testing against CPython** — the primary mechanism. For any
   input program, run under CPython, compile and run, compare outputs. Any
   difference is a bug.
2. **Property-based testing (Hypothesis)** — generates random valid Python
   programs and feeds them through the differential harness. Finds edge
   cases that hand-written tests miss.
3. **Runtime assertion mode** (future) — debug builds emit defensive checks
   verifying the compiler's own assumptions at runtime (e.g., if the
   compiler devirtualized a call, assert the type matches).
4. **Regression directory** — every bug found gets a test file in
   `tests/regressions/`. Bugs never come back. Git tracks history.
5. **CPython's own test suite** (future) — run it under the compiler as a
   massive correctness check.

**The GC is the highest-risk component** for this approach, because GC bugs
manifest as memory corruption that may not show up as output differences.
Plan: start with simplest possible GC (non-moving mark-sweep, or Boehm GC
as a library) and only build a custom GC once testing infrastructure is
strong enough to catch subtle memory bugs.

### 12. Alternatives considered and rejected

**Hybrid Rust-Python language.** Considered making a language with Python
syntax but Rust's ownership model, borrow checker, and type system. Rejected
because:
- Python's semantics (GC, reference aliasing, mutable sharing) are
  fundamentally opposed to Rust's (ownership, borrow checker, no GC)
- Every semantic question (what does assignment mean? what about closures?)
  requires a novel design decision
- No test oracle — the language would be new, so there's no reference
  implementation to diff against
- Very high risk of never finishing

**Transpiler from hybrid language to Rust.** Considered but rejected because:
- Inherits Rust's compile times (can't fix)
- Inherits Rust's lifetime annotations (partially fixable)
- Inherits Rust's orphan rules, async coloring, lack of variadic generics
  (can't fix)
- Error messages reference generated Rust code, not user source
- Can't diverge from Rust's ownership model
- Roughly half of Rust's commonly-cited shortcomings aren't fixable by a
  transpiler

**Writing the compiler in Rust.** Would give stronger compile-time guarantees
on the compiler's own code, but edit-test cycle would be 30-90 seconds
instead of 1-3 seconds. For AI-assisted development where cycle count is
the bottleneck, Python's fast iteration wins.

**Writing the runtime in Rust.** Would give memory safety in the runtime, but
adds FFI friction (`extern "C"` wrappers, `#[no_mangle]`, type conversions)
at every boundary with the OS's other languages. C ABI is universal and the
runtime is small enough that differential testing covers correctness.

### 13. Comparison with existing projects

| Project | Approach | Speed vs CPython | Python-compatible? |
|---------|----------|------------------|--------------------|
| **CPython** | Bytecode interpreter | 1x (baseline) | Yes (it IS Python) |
| **PyPy** | Tracing JIT | 4-10x | Yes (mostly) |
| **mypyc** | AOT, CPython object model | 2-5x | Yes (limited subset) |
| **Cython** | Transpile to C, opt-in C types | 2-1000x depending on annotations | Partially (cdef diverges) |
| **Nuitka** | Transpile to C via CPython API | 1.3-2x | Yes |
| **Shed Skin** | Whole-program type inference, own model | 2-40x | No (restricted subset) |
| **Mojo** | New language, Python-inspired, LLVM | 10-35000x on kernels | No (different language) |
| **Julia** | Type inference, LLVM, JIT | Matches C on numeric | No (different language) |
| **fastpy (this project)** | AOT, whole-program, LLVM, BigInt default | Target: 10-50x typical, C speed on annotated numeric | Yes (strict superset) |

fastpy's unique position: full Python compatibility (any Python program
runs unchanged) with near-C++ performance on annotated code. No existing
tool occupies this exact niche. mypyc is closest but limited by keeping
CPython's object model; Mojo is closest in ambition but isn't Python-compatible.

### 14. The autonomous development loop

The edit-test-debug cycle for compiler development:

```
edit compiler code (any .py file in compiler/)
  -> python -m pytest tests/ -v
  -> tests transition from SKIP to PASS (progress)
  -> tests transition from SKIP to FAIL (bugs to fix)
  -> fix, repeat
```

No build step. 3-4 seconds per cycle. The AI can run this loop autonomously
without the user being in the loop for every iteration. As the compiler
grows, more tests light up. The test suite is the progress meter.

### 15. Implementation roadmap

Each milestone produces a working compiler that does something end-to-end.
Tests transition from SKIP to PASS at each stage, giving continuous visible
progress. No milestone depends on features from a later milestone — each
is self-contained and shippable.

#### Milestone 1: "Hello World" — print literals

**Goal:** Compile `print("hello world")` and `print(42)` to a native
Windows executable that produces the correct output.

**What this requires building:**
- Parse source with `ast.parse()` (already done — Python stdlib)
- Walk the AST and recognize `print(literal)` patterns
- Generate LLVM IR via llvmlite: a `main()` function that calls a C
  runtime `print` function
- The C runtime: a minimal `fastpy_print_str(const char*)` and
  `fastpy_print_int(int64_t)` function, plus a `main()` entry point
  that calls the generated code
- Link the LLVM-generated object file with the C runtime into an .exe
- Verify via differential test harness

**What this proves:** The entire toolchain works end-to-end: Python
source → AST → LLVM IR → object code → linked executable → correct
output. Every subsequent milestone builds on this proven pipeline.

**Tests that light up:** `test_none`, basic `print` tests.

#### Milestone 2: Integer and float arithmetic

**Goal:** Compile programs that do arithmetic on int/float literals and
print the results. Variables, assignment, multiple statements.

**What this requires building:**
- AST walking for: `Assign`, `BinOp`, `UnaryOp`, `Name` (load/store)
- A simple symbol table (name → LLVM value) for local variables
- LLVM IR generation for arithmetic ops (`add`, `sub`, `mul`, `sdiv`,
  `srem`, `fadd`, `fsub`, `fmul`, `fdiv`)
- Runtime: `fastpy_print_float(double)`
- For now, all ints are i64 and all floats are double. No BigInt yet —
  that comes later. Programs that would overflow i64 will differ from
  CPython; that's acceptable at this stage.

**Tests that light up:** `TestArithmetic` (most of it), basic variable
assignment tests.

#### Milestone 3: Control flow

**Goal:** `if`/`elif`/`else`, `while`, `for i in range(n)`, `break`,
`continue`.

**What this requires building:**
- LLVM basic blocks and branching (`br`, `condbr`)
- Comparison operations (`icmp`, `fcmp`)
- Boolean operations (`and`, `or`, `not`)
- `range()` as a compiler built-in (lowered to a counted loop)
- `for` over range only (general iteration comes later)

**Tests that light up:** `TestControlFlow` (all of it).

#### Milestone 4: Functions

**Goal:** `def`, `return`, function calls, local scopes. Recursion works.

**What this requires building:**
- LLVM function definitions and calls
- Local scope per function (separate symbol tables)
- Argument passing
- Return values
- Recursion (just works — functions are already defined before called)
- For now, no default arguments, no `*args`/`**kwargs`, no closures.

**Tests that light up:** `test_simple_function`, `test_multiple_args`,
`test_recursive`, `test_lambda` (if lambda is just an anonymous def).

#### Milestone 5: Strings

**Goal:** String literals, concatenation, `len()`, indexing, slicing,
f-strings, basic methods like `.lower()`, `.split()`, `.join()`.

**What this requires building:**
- Runtime string representation: a struct with pointer, length, and
  capacity (or use a reference-counted immutable representation)
- Runtime string operations: concat, len, index, slice, format
- The f-string desugaring (Python's AST already does this — f-strings
  become `JoinedStr` nodes with `FormattedValue` children)
- GC integration: strings are heap-allocated and need to be tracked.
  This is where we first need the garbage collector.

**GC decision point:** Before this milestone, nothing is heap-allocated
(ints and floats live in registers/stack). Strings force the GC question.
Start with the simplest option: reference counting (like CPython) or
Boehm GC as a linked library. Switch to a real tracing GC later.

**Tests that light up:** `TestStrings` (all of it).

#### Milestone 6: Lists and dicts

**Goal:** List and dict literals, indexing, append, iteration, `len()`,
`in` operator, basic methods.

**What this requires building:**
- Runtime list representation: growable array of tagged values
- Runtime dict representation: insertion-ordered hash table
- Tagged value representation: a union type that can hold int, float,
  string, None, bool, list, dict, or object pointer. This is the
  fundamental "Python object" representation.
- `for x in list` iteration (general `__iter__`/`__next__` protocol)
- `in` operator
- List/dict methods: `.append()`, `.pop()`, `.get()`, `.keys()`, etc.

**This is a big milestone** — it introduces the general "Python object"
type and the tagged-value representation that everything else builds on.
Take time to get the representation right because every subsequent
milestone depends on it.

**Tests that light up:** `TestContainers` (most of it), `test_for_list`,
comprehensions (if implemented as syntactic sugar over loops).

#### Milestone 7: Classes

**Goal:** `class` definitions, `__init__`, methods, attribute access,
`isinstance`, basic inheritance.

**What this requires building:**
- Object representation: tagged value pointing to a heap struct with a
  type pointer and attribute storage
- Class representation: a type object with a method table and layout info
- Attribute access: look up in instance, then class, then MRO
- Method dispatch: bound methods (self is passed as first arg)
- `isinstance()`: walk the MRO chain
- `__init__`, `__str__`, `__repr__`, `__eq__` — the core dunders
- Single inheritance (just chain the MRO)

**Tests that light up:** `TestClasses` (all of it), `test_str_repr`.

#### Milestone 8: Exceptions

**Goal:** `try`/`except`/`finally`/`raise`, exception types, traceback
info.

**What this requires building:**
- Exception representation: an object with type, message, traceback
- LLVM exception handling: `invoke` + `landingpad` or a simpler
  setjmp/longjmp approach for v1
- `try`/`except` matching by exception type
- `finally` blocks
- `raise` statement
- Built-in exception types: `ValueError`, `TypeError`, `KeyError`,
  `IndexError`, `ZeroDivisionError`, `StopIteration`, `RuntimeError`

**Tests that light up:** `TestExceptions` (all of it).

#### Milestone 9: Closures, generators, comprehensions

**Goal:** Nested functions with captured variables, `yield`, list/dict/set
comprehensions, generator expressions.

**What this requires building:**
- Closure representation: function pointer + captured environment
- `nonlocal` keyword
- Generator representation: a coroutine frame that can be suspended/resumed
- Comprehensions: desugar to generator expressions or inline loops
- `*args`, `**kwargs`, default arguments

**Tests that light up:** `test_closure`, `test_star_args`, `test_kwargs`,
`test_default_args`, `test_list_comprehension`, `test_dict_comprehension`,
`test_walrus`.

#### Milestone 10: The BigInt and tagged-value overhaul

**Goal:** Default integers are BigInt-capable (matching CPython exactly).
Speculative unboxing on the fast path. The unchecked machine int types
(`UInt32`, `Int32`, etc.) are recognized and compiled to raw machine ints.

**What this requires building:**
- BigInt runtime library (or link GMP/libtommath)
- Speculative unboxing: inline fast path with i64, overflow check,
  fallback to BigInt
- Recognition of `from fastpy import UInt32` etc. in the compiler
- Codegen for machine int operations (direct LLVM i32/i64 without tags)
- `2 ** 100` works correctly

**Why this is milestone 10 and not earlier:** The earlier milestones use
plain i64 for all ints, which is wrong for programs that overflow 64 bits
but lets us build and test the entire rest of the compiler without the
complexity of the tagged-value / BigInt system. Once everything else works,
we retrofit the correct int representation. Many tests will already pass
because they don't use values that overflow i64.

**Tests that light up:** `test_big_int`, any test that depends on exact
Python int semantics.

#### Milestone 11: Optimization passes

**Goal:** Type inference, devirtualization, range analysis, escape
analysis, sealed class detection. This is where the compiler goes from
"correct but slow" to "correct and fast."

**What this requires building:**
- Type inference pass over the typed IR
- Devirtualization based on inferred types
- Range analysis for loop bounds and arithmetic
- Escape analysis for stack allocation
- The annotation system (`@sealed`, `@final`, etc.)
- Integration with LLVM optimization levels

**Not a single milestone in practice** — this is an ongoing process.
Each analysis is added independently, tested independently, and can be
turned on/off independently. The ratchet approach applies here: add the
simplest version of each analysis first, then refine based on profiling
real workloads.

#### Milestone 12: Standard library, imports, and C extension compatibility

**Goal:** Import resolution, standard library access, and eventually
loading existing CPython C extensions (.pyd/.so files).

**Pure Python standard library modules are automatic.** Once the compiler
handles the full Python language (milestones 1-9), any pure-Python module
compiles as-is: `json`, `pathlib`, `dataclasses`, `http`, `email`,
`urllib`, `argparse`, `textwrap`, `configparser`, etc. These are just
Python files in CPython's `Lib/` directory — no reimplementation needed.

Many "pure Python" modules import a C accelerator under the hood (e.g.,
`json` imports `_json`, `collections` imports `_collections`). Without
C extension support, most of these fall back to their pure-Python
implementation, which is still much faster than CPython once compiled
by us. With C extension support, they get the C accelerator too.

**C extension compatibility via CPython C API implementation.** Rather
than reimplementing each C extension from scratch, we implement CPython's
C API in our runtime. Existing compiled `.pyd`/`.so` files can then be
loaded and called directly. This is a one-time investment that unlocks
the entire ecosystem (numpy, sqlite3, _json, _csv, etc.) rather than
requiring per-extension reimplementation.

How this works:
- Our runtime implements the CPython C API functions (`PyLong_AsLong`,
  `PyList_SetItem`, `PyDict_GetItem`, etc.) against our internal object
  representations.
- When a C extension asks for a `PyObject*`, our runtime provides a
  CPython-compatible wrapper around our internal representation (with a
  refcount and type pointer in the expected layout).
- The wrapper acts as a bridge: C extensions see a normal `PyObject*`,
  while our GC tracks the wrapper as a root while C code holds a
  reference.
- We implement the API incrementally, driven by which extensions we
  actually need to load. The 50-100 most-used API functions cover ~90%
  of extensions.

Challenges:
- **Object layout mismatch.** Our compiled objects may have different
  internal layouts than CPython's. The wrapper layer bridges this but
  adds overhead on API-boundary crossings.
- **Reference counting bridge.** If our GC is tracing-based, we need
  to bridge: refcount operations from C extensions maintain a count on
  the wrapper, and our GC treats wrappers with nonzero refcounts as
  roots.
- **Direct struct access.** Some C extensions bypass the API and access
  struct fields directly (e.g., `((PyListObject*)obj)->ob_item[i]`).
  These break with our layout. The "stable ABI" (PEP 384 / abi3)
  forbids this; extensions targeting abi3 will work. Extensions that
  access internals directly will need per-extension fixes or won't be
  supported.
- **API surface size.** The full CPython C API is hundreds of functions.
  We don't need all of them — we implement on-demand as extensions
  require them.

The stable ABI (abi3) subset is much smaller and well-defined. Python
3.13+ is actively pushing extensions toward the stable ABI, so the
trend favors our approach. For the OS project specifically, the first
extensions needed would likely be stdlib accelerators (`_json`, `_csv`,
`_socket`, `_ssl`, `_sqlite3`) which are simpler and use fewer API
functions than scientific computing extensions.

**Import resolution** is the prerequisite for all of this — the compiler
needs to find and compile (or load) imported modules. This includes:
- Resolving `import foo` to a file path (following Python's import rules)
- Compiling imported pure-Python modules as part of whole-program analysis
- Loading pre-compiled `.pyd`/`.so` C extensions via the C API bridge
- Handling `__init__.py`, relative imports, and package structure

#### Milestone ordering rationale

The order is chosen so that:
1. **Every milestone produces a runnable binary.** No milestone requires
   "build half the infrastructure" before seeing results.
2. **Each milestone builds on the previous one.** Functions need
   arithmetic, classes need functions, etc.
3. **Complexity increases gradually.** The GC isn't needed until strings
   (milestone 5). The tagged-value representation isn't needed until
   lists (milestone 6). BigInt isn't needed until milestone 10.
4. **Tests light up continuously.** The existing test suite covers all
   milestones. As each feature lands, tests automatically transition
   from SKIP to PASS.
5. **The hardest parts (optimization, milestone 11) come last** — by the
   time we get there, the rest of the compiler is stable and well-tested,
   giving us a solid foundation to add analyses on top of.
6. **The user's OS project can start before the compiler is "done."**
   After milestone 8 (exceptions), the compiler handles enough of Python
   to write real programs. Milestones 9+ add convenience and performance.

### 16. Working style

**Always work autonomously for as long as possible.** When the user asks
you to work on something, keep going through the build-test-debug loop
without stopping for input. Don't pause after each milestone to ask what
to do next — just move to the next milestone in the roadmap. Only stop
when you genuinely need a decision from the user that the CLAUDE.md and
os.md don't answer, or when you've run out of planned work.

**Always document new architectural debt and limitations immediately.**
Whenever you introduce a new hack, correctness shortcut, or known
limitation — or discover an existing one — add it to §17 below BEFORE
continuing. This includes:

- Shortcuts that trade correctness for progress (compile-time heuristics
  that only work in common cases, type assumptions that could break).
- Unsupported language features that the codegen silently accepts but
  compiles incorrectly (as opposed to features that cleanly raise a
  CodeGenError — those self-document).
- Runtime invariants that aren't enforced at the type level.

This is load-bearing: context may get lost between sessions, and §17 is
the durable record of what's genuinely broken-but-scheduled-for-fix vs.
what's correct. Without this record, a future session can't distinguish
"this code is wrong but intentional" from "this code is wrong and should
be fixed."

**Never silently defer a known bug.** If you discover a bug or incorrect
behavior but choose not to fix it immediately (e.g., because you're in
the middle of a different task), you MUST document it before moving on.
Add it to §17, to UNIMPLEMENTED.md, or as a code comment at the site —
whichever is most appropriate. The rule is: if you say "I'll fix this
later" or "this is less important," the next line of work must be writing
down what's broken and where. Undocumented deferred bugs are lost bugs.

### 17. Known hacks and architectural debt

These are correctness issues in the current compiler that need to be
fixed properly. They exist because the codegen uses bare LLVM types
(i64/double/i8*) without a tagged-value system, losing type information
at function boundaries.

**Root cause:** The runtime has a tagged-value system (FpyValue with
tag+union), but the codegen doesn't use it. Function params are all i64,
returns are i64, and type information is recovered via AST heuristics.
The proper fix is carrying tagged values through the codegen so every
value knows its own type at runtime.

**Refactor in progress (as of 2026-04-14):** User responded to the
growing hack count by requesting the full tagged-value refactor
(Milestone 10). Phased plan tracked as Tasks #25–#30.

- Phase 1 (infrastructure): DONE — LLVM `{i32, i64}` FpyValue type,
  codegen helpers, ABI conventions (output-pointer for returns to sidestep
  MSVC x64 struct-return quirks).
- Phase 2 (user function boundaries): DONE — `def foo(x):` now takes and
  returns FpyValue.
- Phase 3 (object attributes): DONE — `self.x = y` and `obj.attr` use
  `obj_set_fv` / `obj_get_fv`. Hack 2 (pointer-magnitude heuristic)
  **deleted** from both compiler and runtime.
- Phase 4 (containers, append/set): DONE — `list.append()`, `list[i] = v`,
  `d[k] = v` use FV-ABI. The 14 typed variants
  (obj_set_*/obj_get_*/list_append_*/list_set_*) **deleted** from runtime.
- Phase 5 (variables and operations): IN PROGRESS. Locals and function/
  method params now stored as `%fpyvalue` allocas (opt-in via
  `CodeGen._USE_FV_LOCALS = True`). `_store_variable` wraps bare values
  into FpyValue on write; `_load_variable` unwraps based on the variable's
  current type_tag on read. This fixes a subtle class of bugs where
  re-assigning a variable's type mid-function would create a new alloca
  that subsequent loads ignored. Exceptions kept on legacy path:
  globals (i64 direct), closure cells (heap FpyCell), classmethod `cls`
  (i32 class_id). Print/write go through `fv_print`/`fv_write` for
  runtime dispatch. F-string `{self.attr}` uses `obj_get_fv` + `fv_str`.
  Container access converted to FV-ABI: `dict[k]` → `dict_get_fv`,
  `list[i]` → `list_get_fv`, `for x in list:` → `list_get_fv`, `x in list`
  → `list_get_fv`. Added `FPY_TAG_DICT` for proper dict tagging.
  `_load_or_wrap_fv` helper preserves runtime tag at print/truthiness
  boundaries — Names backed by FV allocas and dict/list subscripts now
  bypass static-type unwrap and dispatch via the actual runtime tag.
  `_truthiness_of_expr` and `fv_truthy` cover all 8 tags including
  DICT. `_emit_dict_literal` and friends now use `dict_set_fv` with
  AST-aware tag inference (so `{"k": [1,2]}` correctly stores its
  value as LIST). Function return-type detection extended to direct
  dict/list/string-literal returns. Remaining work: make arithmetic
  dispatch by runtime tag. Most type-inference hacks still used as
  scaffolding for choosing the unwrap type on load.
- Phase 6 (cleanup): PARTIAL — 43 dead runtime functions deleted
  (14 from Phase 4: obj_set_*/obj_get_*/list_append_*/list_set_*; 18
  from Phase 5 print conversion: print_*/write_*/list_print/
  tuple_print/dict_print/obj_print/obj_write/obj_get_as_str; 3 from
  Phase 5 dict subscript: dict_get_int/dict_get_str/dict_get_as_str;
  8 from Phase 5 list/dict cleanup (2026-04-14): list_get_int,
  list_get_float, list_get_str, list_get_as_str, list_get_tag,
  value_str, dict_set_str_int, dict_set_str_str). Hacks 2, 11, and 12
  fully resolved.

Annotations on the hacks below:
- **DELETED**: code removed from both compiler and runtime.
- **ELIMINATED**: no longer reachable in generated code; C runtime may
  still have the dead function (pending full Phase 6 cleanup).
- **SCAFFOLDING**: still used to drive wrap/unwrap at FV boundaries.
  Goes away in Phase 5 when variables become FpyValue.
- **PENDING**: hack targeted by a future phase.

#### Hack 1: String parameter detection (SCAFFOLDING)

**What:** Scans function body AST for params used in f-strings, string
concat, or stored to class attributes used in f-strings elsewhere.
Detected params get `inttoptr` at function entry to recover the string
pointer from the i64 parameter.

**Why it exists:** Function params are declared as i64 in LLVM IR.
String pointers get cast to i64 at call sites via ptrtoint. Inside the
function, the codegen needs to know which params are strings to cast
them back.

**What it breaks:** Any string param not detected by the heuristic
(e.g., only used in comparisons, or passed to another function) will
be treated as an integer. The string pointer address will be formatted
as a number in print/f-string contexts.

**Proper fix:** Tagged-value parameters. Every function param is a
`{tag, value}` pair. No heuristic needed — the tag says what it is.

#### Hack 2: obj_set_int pointer heuristic (DELETED)

Attribute set now goes through `obj_set_fv(obj, name, tag, data)` which
stores the exact tag. The old `obj_set_int` (with its pointer-magnitude
heuristic) and its siblings `obj_set_float`, `obj_set_str`, `obj_get_int`,
`obj_get_float`, `obj_get_str` have been deleted from the runtime
(2026-04-14, Phase 6 of the tagged-value refactor).

---
Historical description (kept for posterity):

**What:** When storing an i64 value as an object attribute, checks if
the value is > 0x100000000 and assumes it's a string pointer if so.
Stores it as FPY_TAG_STR instead of FPY_TAG_INT.

**Why it exists:** Constructor params like `Dog("Rex")` pass "Rex" as
i64 (pointer cast). Inside `__init__`, `self.name = name` stores via
`obj_set_int(obj, "name", i64_value)`. Without the heuristic, the
string pointer is stored as an integer.

**What it breaks:** Large integer values (> ~4 billion) stored as object
attributes would be misidentified as pointers and corrupted. Also
fragile on systems with low heap addresses.

**Proper fix:** Tagged-value parameters. The constructor receives a
tagged value, and `obj_set` stores the tag alongside the value.

#### Hack 3: Return type detection (SCAFFOLDING)

**What:** Scans function body AST for return statements containing
float constants, string constants, JoinedStr (f-strings), or Tuple
nodes. Sets the LLVM return type accordingly.

**Why it exists:** Functions are declared before their bodies are
compiled. The return type must be decided at declaration time. Without
type inference, we guess from AST patterns.

**What it breaks:** Functions whose return type depends on control flow
(`if x: return 1` else `return "hello"`) or on runtime values. Also
misses cases where the return value comes from a variable whose type
isn't obvious from the AST.

**Proper fix:** Either (a) proper type inference that analyzes the
function body, or (b) all functions return tagged values, eliminating
the need to know the return type at declaration time.

#### Hack 4: Empty-list append pre-scan

**What:** `_prescan_list_append_types()` scans a function body for
`x = []` followed by `x.append(...)` calls, and records the inferred
element type (list/obj) in `_list_append_types`. The type tag of the
empty-list assignment is then overridden from `list:int` to
`list:list` or `list:obj`.

**Why it exists:** An empty list literal has no element type information
from the AST alone. Without the pre-scan, code like
`result = []; for row in ...: result.append(row)` would tag `result` as
`list:int`, and later indexing `result[0][k]` would fail (since `result[0]`
wouldn't be recognized as a list).

**What it breaks:** Any append pattern the pre-scan doesn't recognize:
appending the return value of a user function, appending through
intermediate variables assigned in complex ways, or appending different
types across conditional branches. Only simple patterns are handled.

**Proper fix:** Proper dataflow-based type inference. Or tagged values —
an empty list becomes `list:any`, and element types are carried at runtime.

#### Hack 5: Return "ptr:list" detection

**What:** When a function's return type is i8* (pointer), scans return
statements for `return x` where `x` was built via `x.append(list_expr)`
calls. If so, sets the function's `ret_tag` to `"ptr:list"` instead of
`"ptr"`, so callers know it returns a list-of-lists.

**Why it exists:** Function return types are fixed at declaration time,
but the element type of a returned list isn't part of the LLVM signature.
Without this, calling a function that returns a list-of-lists would lose
the nested structure and `result[i][j]` would fail at the call site.

**What it breaks:** Returns that can't be statically traced to an
append-pattern (e.g., returning a list built by a helper function,
returning based on conditional branches, returning from a list comp).

**Proper fix:** Parametric list types in the return-type signature, or
tagged values at boundaries.

#### Hack 6: Class attribute container detection

**What:** `_detect_class_container_attrs()` scans a class's `__init__`
for `self.attr = [...]` or `self.attr = {...}` and records attr names as
list-attrs or dict-attrs. Attribute loads then use `obj_get_as_str`
(pointer return) instead of `obj_get_int` (integer return), and
`_is_list_expr`/`_is_dict_expr` return True for `obj.attr` if the class
has that attr as a container.

**Why it exists:** Attribute access `obj.attr` goes through the runtime's
object dispatch which returns i64 by default. For container attributes,
we need to return the pointer so subscript/iteration work.

**What it breaks:** Attributes assigned container values outside `__init__`,
attributes whose type depends on runtime state, attributes of a class
the compiler doesn't know the type of (e.g., polymorphic accesses where
`obj` could be any class).

**Proper fix:** Tagged values at attribute access boundaries.

#### Hack 7: Tuple-iter element type inference (SCAFFOLDING — print path uses runtime tag)

Updated 2026-04-14: For-tuple-unpack now stores via `_fv_store_from_list`
which preserves the runtime tag of each element. So `print(a)` /
`print(b)` are correct even when the inferred type is wrong (e.g.
`for k, v in dict.items()` where v is mixed). The compile-time
inference still drives the unwrap-to-bare-LLVM type for arithmetic
sites; eliminating that requires arithmetic-on-FpyValue (Phase 5
follow-up). Heterogeneous-tuple-element-types-across-tuples still
breaks for arithmetic.

#### Hack 8: Object variable class tracking

**What:** `_obj_var_class` dict maps `variable_name -> class_name` for
variables assigned from class constructors (`a = Foo(...)`). This lets
`_infer_object_class()` look up the class of `a` for attribute-type
detection.

**Why it exists:** Type tags only say "obj" generically, not which class.
Without this, `a.items[0]` can't find that `items` is a list attribute
of class `A`.

**What it breaks:** Any code path that assigns an object through
something other than a direct constructor call: reassignment from a
function return, from subscript of a list of objects, etc. The variable
keeps its stale class name or has no class info at all.

**Proper fix:** Obj tag in tagged values carries the class id; attribute
access is dispatched by class id at runtime.

#### Hack 9: Starred call expansion

**What:** `f(*args)` at the call site is expanded into individual
`list_get_int` or `list_get_as_str` calls, based on the source list's
compile-time element type, filling up to the callee's arity.

**Why it exists:** Our function calls use fixed arity LLVM signatures.
There's no varargs marshalling layer, so we have to know how many to
pass. We determine this from the callee signature; we determine types
from the source list's tag.

**What it breaks:** Lists of mixed-type values won't work. Lists whose
element type isn't statically known (e.g., return value of a helper
function) fall back to `list_get_int` and misrepresent non-int elements.
Also, `*args` calls to functions declared as `is_vararg` still go
through the vararg path, not this one — these two paths don't interact.

**Proper fix:** Tagged values + runtime-marshalled arg passing.

#### Hack 10: Object var class inference falls back to last-seen class

**What:** `_obj_var_class[var]` is updated only on direct
`var = ClassName(...)` assignment. Reassignment from a function call,
subscript, or anything else does NOT update it. If the variable was
first assigned `A()` and later reassigned to a `B()` via a function
return, subsequent attribute access will use `A`'s attribute info.

**Why it exists:** Tracking object class through arbitrary expressions
would require full type inference. The direct-constructor case covers
the common pattern.

**What it breaks:** Polymorphic variables; factory functions. The
compiler may use stale class info for method/attribute dispatch.

**Proper fix:** Carry class identity in the tagged-value header at runtime.

#### Hack 11: `_truthiness_of_expr` relies on AST-level container detection (ELIMINATED for FV-backed Names)

Updated 2026-04-14: Names backed by `%fpyvalue` allocas now route
through `fastpy_fv_truthy(tag, data)` which discriminates every type
at runtime (INT/BOOL/FLOAT/STR/NONE/LIST/DICT/OBJ). The AST-level
checks remain only as a fast path for literals and other expressions
where the type is known at compile time and we can skip the FV
round-trip. Function return values of pointer type, dict expressions
referenced indirectly, and any other previously-broken case now get
the correct truthiness via the runtime tag.

#### Hack 12: List equality limited to runtime tag comparisons (FIXED)

Updated 2026-04-14: `fastpy_list_equal` now handles `FPY_TAG_LIST`
elements via recursive equality. Nested lists (`[[1, 2], [3]] ==
[[1, 2], [3]]`) now return True correctly. Dict values still fall into
the `default: return 0` branch — fixing that requires either a dict
recursion case or runtime tag discovery from pointers.

---
Historical description (kept for posterity):

**What:** `fastpy_list_equal` compared two lists element-wise using
each FpyValue's runtime tag. It handled int, bool, float, string, and
None leaves. Nested containers (list-of-lists, dict values) were NOT
recursively compared.

**Why it existed:** Containers were stored as opaque pointers; no
runtime way to know what kind of container a pointer points to.

**What it broke:** `[[1, 2], [3]] == [[1, 2], [3]]` returned False.

#### Hack 13: divmod result as FpyList passed off as tuple (RESOLVED via is_tuple flag)

Updated 2026-04-14: `FpyList` now has `is_tuple` field set by
`fastpy_tuple_new` and read by `fpy_value_repr`/`fv_print`/etc.
The divmod result is built via `tuple_new` so it has the flag set —
the codegen's "tuple" expression tag is no longer load-bearing for
print formatting; the runtime tag dispatches correctly. Static "tuple"
type tag remains for compile-time `_is_tuple_expr` checks (e.g. tuple
unpacking syntax requires knowing the operand is a tuple).

**What it breaks:** Storing a divmod result in a list or iterating over
it works fine (same runtime). But any type-sensitive code that needs
to distinguish real tuples from divmod results relies solely on the
codegen's static tag, not runtime info.

**Proper fix:** Actually distinguish tuples from lists at runtime, or
accept that tuples are just lists and don't try.

#### Hack 14: Method return "list" inference via AST walk

**What:** `_method_returns_list()` walks a method's AST looking for
`return <list_literal>` or `return <var>` where the var was assigned
a list. If found, the method call is tagged as returning a list.
Separately, `_declare_class` sets the LLVM return type to i8* when it
sees a return-of-list statement.

**Why it exists:** Methods don't have a ret_tag like user functions.
Without inspecting the body, the compiler defaults to i64 returns, and
callers don't know to treat the result as a list (breaks `len(lst)`,
`lst[0]`).

**What it breaks:** Methods returning lists through complex paths
(conditional branches, helper-function calls, etc.) that the AST walk
doesn't capture. Element type is always assumed `"list:int"`.

**Proper fix:** Tagged values carry type info across the call boundary.

#### Hack 15: `type()` builtin returns a compile-time string

**What:** `type(x)` produces a literal string like `"<class 'int'>"`
based on the AST-level type tag of `x`. This happens entirely at
compile time — no runtime type query.

**Why it exists:** There's no actual type object in the runtime. For
most uses (printing, comparison-to-literal, branching on static types)
this works.

**What it breaks:** `type(x) == type(y)` doesn't work: both sides
resolve to static strings, so the comparison is lexical. Polymorphic
patterns like `isinstance(obj, type(other))` also won't work.

**Proper fix:** Runtime type representation (needed for proper
`isinstance`, `type()`, and class comparison semantics).

#### Hack 16: `sorted(key=fn)` assumes int→int key function (PARTIALLY FIXED)

Updated 2026-04-19: `sorted(key=len)`, `sorted(key=abs)`, `sorted(key=lambda)`
with int-returning lambdas, and `min/max(key=abs/len)` all work now. Builtin
key functions (`abs`, `len`, `str`, `int`) are emitted as i64(i64) shim
functions. Lambda params are typed based on the list's element type.

**What still breaks:** User functions used as key= that take string
parameters (e.g. `def last(s): return s[-1]`) fail because the FV-ABI
param isn't recognized as a string — the call-site analysis doesn't
trace through `sorted(key=func)` to infer parameter types.

**Proper fix:** Extend call-site analysis to trace key= arguments in
sorted/min/max and populate `_call_site_param_types` for the key
function, or carry type info in tagged values.
Any non-int element goes through with data.i = 0 (see `list_sorted_by_key_int`
in the runtime).

**Proper fix:** Tagged values + polymorphic callable dispatch.

#### Hack 17: `% s`/`% d` format string interpretation is runtime-only

**What:** `fmt % args` is emitted as a call to
`fastpy_str_format_percent(fmt, args_list)` — the C code parses the
format string at runtime. The compiler doesn't sanity-check spec
letters or arg counts at compile time.

**Why it exists:** Simpler than AST-level format string parsing, and
handles cases where the format string is in a variable.

**What it breaks:** Format specs other than `%s`/`%d`/`%f`/`%%` are
emitted literally (e.g., `%x`, `%5d`, `%.2f`). Width / precision /
flags are unsupported.

**Proper fix:** Either full format-string parser at compile time (like
we did for `.format()`) or full runtime formatter that mirrors CPython.

#### Hack 18: Dict-with-list-values detection (SCAFFOLDING — print path uses runtime tag)

Updated 2026-04-14: Dict literals now go through `dict_set_fv` with
proper tag inference (LIST/DICT/OBJ/STR/INT/FLOAT/BOOL), and printing a
dict subscript routes through `_load_or_wrap_fv` → `fv_print` which
dispatches on the runtime tag. So `print(d[k])` for mixed-type dicts
prints correctly without consulting `_dict_var_list_values`.
The set is still consulted in `_emit_subscript` to choose how to
unwrap to a bare LLVM type for arithmetic / iteration. Eliminating it
fully requires plumbing FpyValue through downstream consumers.

#### Hack 19: FpyValue compare uses tag-then-value lex order

**What:** `fpy_value_compare` in the runtime sorts by tag first, then
by value within the tag. For lists (FPY_TAG_LIST), it recurses
element-wise.

**Why it exists:** qsort needs a total order; we need some definition
for mixed-type lists and lists-of-tuples.

**What it breaks:** CPython's behavior is "can't compare mixed-type
values" — raises TypeError. Our behavior silently picks an order.
Also, cross-type equality after sort may differ subtly.

**Proper fix:** Emit TypeError for mixed-type comparisons to match
Python semantics, once we have richer tag-based dispatch.

#### Hack 20: Class constant attributes are compile-time substitution

**What:** `_class_const_attrs[class_name][attr] → ast.expr` holds the
RHS of class-body assignments like `class Config: MAX = 100`. Access
`Config.MAX` is resolved at compile time to the literal value — it
emits the same code as if the user had typed the value inline.

**Why it exists:** We don't have a runtime class-object with attribute
storage. Class-level data only exists in the codegen.

**What it breaks:** Class constants that are themselves expressions
referring to state (e.g., `X = some_function()`) are re-evaluated at
every access site rather than once at class-definition time. Mutation
of class-level attributes (e.g., `Config.MAX = 200`) is not supported —
classes behave as immutable namespaces.

**Proper fix:** Emit class objects at runtime and dispatch attribute
access through them.

#### Hack 21: `map()` and `filter()` assume int-int function signatures (PARTIALLY FIXED)

Updated 2026-04-19: `map()` now uses an inline codegen loop instead of
`list_map_int`. Each element is loaded via `list_get_fv` and the mapped
function is called with proper type handling: builtin converters (`str`,
`int`, `float`) are special-cased to emit correct tags; user functions
and lambdas are called as `i64(*)(i64)` with tag inference from the
function's return type. `map(str, [1,2,3])` now returns `['1','2','3']`
correctly. `filter()` still uses the old `list_filter_int` path and
has the same int-int limitation.

**What still breaks:** `filter()` with string-returning predicates or
non-int elements. `map()` with multi-arg functions. `map()` with closures
that capture variables (closures work as variable-backed func pointers
but not as magic-number closures).

**Proper fix:** Tagged values + dynamic callable dispatch for filter too.

#### Hack 22: Dict-with-int-values detection (SCAFFOLDING — print path uses runtime tag)

Updated 2026-04-14: Same as Hack 18. Dict access for printing now
preserves the runtime tag via `_load_or_wrap_fv` → `dict_get_fv` →
`fv_print`, so `print(d[k])` is correct regardless of the
`_dict_var_int_values` set. The set is still used in `_emit_subscript`
to unwrap the dict value as i64 for direct arithmetic; eliminating it
requires running arithmetic on FpyValue too (a Phase 5 follow-up).

#### Hack 23: `return` inside try-with-finally re-emits the finally inline

**What:** `_finally_stack` tracks pending finally bodies. When `return`
is emitted inside a try block with a finally, the finally body is
emitted *inline* before the actual ret instruction — the finally stack
is temporarily cleared during its emission so nested returns don't
recurse.

**Why it exists:** Python semantics require finally to run before the
return value is returned. Our LLVM-level representation has no
"landing pad" equivalent that would let us set up cleanup handlers the
way C++/MSVC SEH does.

**What it breaks:** Large finally bodies are duplicated at every return
site, bloating the IR. Exceptions escaping through a finally body
(e.g., finally body itself has unhandled exception) may not propagate
correctly. `break`/`continue` inside a try-with-finally don't run the
finally (only return is handled).

**Proper fix:** Proper EH landing pads + Python-like cleanup semantics
for all non-local control flow — not just returns.

#### Hack 24: Inline lambda emitted as standalone i64(i64) function

**What:** `_emit_inline_unary_lambda` emits `lambda x: expr` as a
top-level LLVM function named `fastpy.inline_lambda.N`. The function
takes one i64 and returns one i64. Callers (map/filter/sorted) get a
function pointer to this.

**Why it exists:** Matches Hack 16's "functions are int→int" ABI. Gives
us inline lambdas without closure support — the body can only refer
to the parameter, not to enclosing scope variables.

**What it breaks:** Lambdas closing over outer scope variables fail
(undefined variable). Lambdas returning non-int types silently coerce
to i64 (strings become pointer-cast integers, floats are truncated).

**Proper fix:** Full closure support via captured-environment passing,
combined with tagged values for the parameter and return.

#### Hack 25: Tuple runtime distinction via `is_tuple` field

**What:** Added an `is_tuple` int field to `FpyList`. Tuple literals call
`fastpy_tuple_new()` which sets it to 1. All list-printing functions
(`fpy_list_write`, `fpy_value_repr`, `fastpy_list_to_str`) check this
flag and emit parens with trailing comma for length-1 tuples.

**Why it exists:** Tuples and lists share the same FpyList runtime
representation (growable FpyValue array). Without this flag, there's
no way to tell at print time whether `[1, 2]` should print as `[1, 2]`
or `(1, 2)`.

**What it breaks:** Converting between tuple/list — e.g., `list(t)` on
a tuple should produce a list but currently returns the same FpyList
(with is_tuple still 1). Similarly `tuple(lst)` returns the list
unchanged. Mutation operations on an is_tuple=1 list don't raise
TypeError (as Python would).

**Proper fix:** Separate tuple representation with real immutability.

#### Hack 26: `cls()` inside classmethod calls `obj_new` directly

**What:** Inside a `@classmethod`, calling `cls()` or `cls(args)` is
recognized by `_emit_closure_call` when the callable variable is named
`cls` with type i32. It emits `obj_new(class_id)` + `obj_call_init*`
directly, bypassing constructor dispatch.

**Why it exists:** Classmethods receive the class_id as an i32 param.
Calling it as a function would go through closure dispatch, which
doesn't know how to construct instances.

**What it breaks:** The param *must* be named `cls` for this to work.
Renaming breaks the special case. Also, calling `cls` as a method
receiver (e.g., `cls.other_method()`) isn't supported — it's only
callable as a constructor.

**Proper fix:** Real class objects at runtime with callable semantics.

#### Hack 27: Fluent-chain class inference walks `return self`/`return cls()`

**What:** `_infer_object_class` recursively walks method call chains,
checking if each method returns `self` or `cls(...)`. If so, the class
propagates through the chain, enabling `Fluent().add(1).add(2).v`.

**Why it exists:** Method call return types don't carry class info.
Walking the return AST patterns gives us enough to chain.

**What it breaks:** Methods that return `self` through complex paths
(e.g., conditionally, via helper functions) aren't detected. Chains
that go through non-self-returning methods lose the class info.

**Proper fix:** Class info in tagged values.

#### Architectural debt: no tagged values in codegen

The runtime's FpyValue (tag + union) is used for list/dict element
storage and object attributes. But the codegen (LLVM IR generation)
uses bare types: i64 for ints and pointers-cast-to-int, double for
floats, i8* for strings/lists/dicts/objects. Type information is
tracked via string tags ("int", "str", "obj", "list:int") in the
Python-level symbol table, but this information is lost at every
function call boundary (all params become i64).

The fix: make the codegen use a uniform tagged-value representation
for all Python values. This eliminates all three hacks above and
enables proper mixed-type containers, polymorphic function params,
and dynamic dispatch. It's the natural prerequisite for Milestone 11
(optimization passes), because the optimizer needs to know value types
to specialize them.

#### Hack 28: Closures returning booleans crash via call_ptr

**What:** Closures whose body returns a comparison (`return x > n`)
crash at runtime when called via `call_ptr1`. The crash is an access
violation (rc=3221225477 on Windows).

**Root cause:** Closures are declared with legacy i64 ABI
(`_scan_for_closures` at line ~1164 sets `ret_type = i64`). But when
`_USE_FV_LOCALS` is True, the closure body's `_emit_return` wraps the
comparison result as an FpyValue `{i32, i64}` and tries to `ret` it.
The LLVM function signature says `i64` return but the `ret` instruction
returns `{i32, i64}` — this is invalid IR that causes UB at runtime.

**What it breaks:** Any closure that returns a comparison, boolean
expression, or any value that gets FV-wrapped in the body. This blocks
`filter(closure, list)` with boolean predicates.

**Attempted fix (reverted):** Setting `_USE_FV_LOCALS = False` in
`_emit_closure_body` fixed the boolean return but caused regressions
in other closure patterns — nested closures and decorator chains broke
because the outer function's FV state was corrupted by the flag change.

**Recommended fix approach (per user):** Selectively disable FV
wrapping in the *return path only* for closure bodies, rather than
globally disabling `_USE_FV_LOCALS`. Specifically:
1. In `_emit_return`, detect when `self.function` is a closure
   (i64 return type, not FpyValue struct return).
2. When the return value is an FpyValue, extract just the data (i64)
   before returning — this is the unwrap that `_unwrap_fv_for_tag`
   does. For booleans: `extract_value(fv, 1)` then zext to i64.
3. This should be safe because the closure's callers (call_ptr1,
   closure_call1) expect i64 returns, and the closure's internal
   variables can still use FV locals — only the final `ret` needs
   to strip the FpyValue wrapper.

The key insight: FV locals should stay ON inside closures (variables,
comparisons, intermediate expressions all benefit from runtime tags).
Only the return instruction needs to convert from FpyValue back to i64.

### 18. OS design

The OS architecture, language choices, driver model, hardware support
strategy, package management, snapshot/dedup design, cross-compilation
workflow, and self-hosting roadmap are documented in **`os.md`**.

Summary: production-quality microkernel OS. Rust kernel, Rust userspace
drivers (MMIO-mapped, process-isolated), Ada/SPARK kernel-space drivers
(formally verified), compiled Python (fastpy) for userspace services
and applications. Cross-compiled from Windows, tested in VMs.
