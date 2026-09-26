# Fastpy Roadmap — Path to Full CPython Compatibility

## Completed

### Core features (this session)
- Native @dataclass (AST expansion)
- Native @singledispatch (switch dispatch)
- Native complex numbers (FPY_TAG_COMPLEX)
- Native json module (parser + serializer)
- Native os/os.path module (Win32/POSIX)
- Native asyncio.run/gather/sleep
- Native frozenset
- Compile-time eval/exec for literal strings
- Native generators with send/close/throw (state machine)
- Native yield from (delegation protocol)
- Native yield inside try/finally and with
- Generator finally cleanup on GC (per-class destructor)
- Full metaclass support (__new__, __init_subclass__, __class_getitem__)
- Multi-file compilation (local imports, packages, relative imports)
- Module namespacing (name collision avoidance)
- import X with dotted access (X.func → X__func rewriting)
- Native collections module (Counter, defaultdict, deque, OrderedDict, namedtuple, ChainMap)
- Native typing module (Optional, List, Dict, Union, TYPE_CHECKING — all no-ops)
- Native abc module (ABC base class, @abstractmethod decorator)
- Native functools.reduce (inline loop with direct call)
- Native logging module (basicConfig, levels, named loggers, format strings)
- Native contextlib module (contextmanager/suppress as no-ops)
- Native sys module (exit, platform, maxsize, argv, version_info, path)
- Native time module (time, time_ns, perf_counter, sleep, monotonic)
- pyobj type() support (calls CPython's type() for bridge objects)
- pyobj iteration protocol (for x in cpython_object via __iter__/__next__)
- pyobj arithmetic via CPython number protocol (binop/rbinop)
- deque iteration support (for x in deque)
- functools.partial (compile-time wrapper function generation)
- Native itertools module (chain, repeat, product, zip_longest, islice, accumulate, combinations, permutations)
- Native enum/dataclasses imports (no-op, handled by class system)
- functools.lru_cache (per-function dict cache with maxsize, decorator skip)
- Linux/macOS support (dynamic triple/layout, POSIX linker, build_runtime.sh)
- Native random module (xoshiro256** PRNG: random, randint, randrange, choice, shuffle, sample, uniform, gauss)
- Native hashlib/string imports (no-op, avoids crash)
- Native pathlib module (Path with /, .name, .parent, .suffix, .stem, .exists, .read_text, etc.)
- Native copy module (copy.copy shallow, copy.deepcopy recursive for list/dict/set)
- Native operator module (add, sub, mul + integration with functools.reduce)
- Native struct module (pack, unpack, calcsize — big/little endian, int/float types)
- Native base64 module (b64encode, b64decode)
- Native uuid module (uuid4 — random UUID generation)
- Native textwrap module (dedent, indent)
- Native shutil module (copy, rmtree)
- Native glob module (glob.glob with wildcard matching)
- Native tempfile module (gettempdir, mkdtemp)
- Native heapq module (heapify, heappush, heappop, nsmallest)
- Native bisect module (bisect_left, bisect_right, insort)
- Metaclass super().__init__/__new__ in type-inheriting classes (no-op/obj_new)
- Hybrid metaclass: bridge metaclasses run for side effects, methods stay native vtable
- Runtime JIT for exec/eval (native compilation via compiler/jit.py + bytecode cache fallback)
- Compile-on-load for dynamic imports (jit_import: find .py → compile → load .dll/.so)
- Native platform module (system, python_version)
- Native secrets module (token_hex, randbelow)
- No-op stdlib imports: datetime, statistics, array, weakref, threading, subprocess,
  pickle, csv, signal, atexit, gc, inspect, types, numbers, fractions,
  traceback, pprint, unittest, argparse, io, warnings, hashlib, string

### Performance optimizations
- Internal linkage + alwaysinline for whole-program inlining
- Vtable dispatch for O(1) polymorphic method calls (with CHA devirtualization)
- Per-class typed attributes (float/str/bool)
- FV ABI for native-typed method parameters
- FpyClassDef struct alignment fix (72→88 bytes, correct array stride for vtable lookup)
- Void return type detection in vtable dispatch (eliminates calling convention UB)
- Native double params for float methods (CSA-driven, eliminates i64↔double coercion)
- set_arg_tag elimination for native-typed params (direct + CHA dispatch)
- Monomorphic scalar slot optimization (skip tag store + refcount for float/bool attrs)

### Codegen refactor (Phases 1-4 complete)
- Phase 1: TypedValue foundation (VKind, ValueType, TypedValue classes)
- Phase 2: Expression emitters converted to TypedValue
- Phase 3: Variable storage uses ValueType (replaces string tags)
- Phase 4: Bridge fallbacks for all CodeGenError paths
- SafeIRBuilder: auto-coerces all LLVM type mismatches (call, icmp, fadd, store, ret, phi, select)
- Result: 104/104 stdlib .py files compile (up from 17)

### First-class functions
- Function aliases (`callback = some_func; callback(x)`)
- Indirect calls through variables
- `__call__` dispatch for callable objects
- Function return type propagation (list-of-lists from append patterns)

### CPython bridge improvements
- PyBytes_Check, PyTuple_Check for correct type identification
- PYOBJ binops/comparisons via `fpy_cpython_binop`/`fpy_cpython_compare`
- 4+ arg bridge calls via `fpy_cpython_call_kw`
- Safe refcounting across FpyClosure, FpyObj, and PyObject* types
- ABI version check at startup (compile-time vs runtime Python version)

### Multi-Python version targeting
- Compile against any installed Python (3.11, 3.12, 3.13, 3.14)
- Dynamic Python include/lib discovery via sysconfig

### Exception handling
- noinline fix for raise-containing functions (prevents LLVM optimizer issues)

### Bug fixes
- Linked list None traversal
- Set union size
- Mixed-type dict values
- Cross-function list parameter propagation
- Module-level constants in functions
- Computed float expression globals
- Nested list-of-lists element type tracking (nbody benchmark)

## Planned — High Priority

### 1. ~~Fully native metaclass protocol~~ ✅ DONE
User-defined metaclasses with `__new__` and `__init__` compile natively.
`super().__new__/init()` in type-inheriting classes resolved to obj_new/no-op.
Hybrid approach for bridge metaclasses: metaclass runs through CPython for
side effects (validation, hooks), but method bodies stay native with vtable
dispatch. No speed regression (benchmarks: fib=175ms, loop=99ms, list=15ms).

**What it means:** `type.__new__(mcs, name, bases, namespace)` implemented in C:
- Build namespace dict from class body (methods + assignments)
- Call `Meta.__prepare__` if defined (returns custom namespace)
- Execute class body to populate namespace
- Call `Meta.__new__` with (mcs, name, bases, namespace)
- Call `Meta.__init__` with (cls, name, bases, namespace)
- Register methods from namespace dict into our class system
- Method BODIES are always compiled natively

**Slow paths (native C, not CPython):**
- Dict-backed namespace instead of compile-time slot allocation
- Runtime method registration instead of compile-time direct dispatch
- Dynamic attribute lookup instead of compile-time slot indices

**Fast paths (unchanged):**
- Method bodies compiled to native LLVM IR
- Attribute access on instances uses slots when statically known
- Direct dispatch when class is known at call site

**Runtime function:** `fastpy_type_new(meta_id, name, bases, namespace) → class_id`

### 2. ~~Runtime JIT compilation for exec/eval~~ ✅ DONE — ⚠️ crashes when enabled (found 2026-09-26)
Two-tier system for dynamic `exec()`/`eval()`:
1. **Native JIT** (compiler/jit.py): compiles source → LLVM IR → machine code
   in memory with llvmlite's MCJIT — in-process since 9d162bc (2026-04-20),
   no shared library — maps its runtime calls through the exported
   `fastpy_get_jit_symbols` table, and calls `fastpy_main()`. Cached by source
   hash. Used only when the fastpy compiler + llvmlite are importable at
   runtime. `eval()` never reaches it: the bridge calls only `jit_compile`
   (for `exec`) and `jit_import`.
   **Broken, found 2026-09-26:** on 64-bit Windows the symbol table is never
   found, so the first runtime call from JIT'd code kills the program; and
   even with that fixed, the table covers 230 of the 656 runtime functions and
   none of the runtime variables, and one unresolved reference is enough to
   crash a module. See `BUG-JIT-SYMBOL-TABLE-ALWAYS-EMPTY-ON-WIN64` and
   `BUG-JIT-RESOLVES-230-OF-656-RUNTIME-FUNCTIONS-AND-NO-GLOBALS` in
   `known-issues.md`.
2. **Bytecode cache** fallback: `Py_CompileString` → `PyEval_EvalCode` with
   128-entry FNV-1a hash cache. Used when JIT module not available.
The C bridge (`fpy_jit_exec`) tries native JIT first and falls back when
`jit_compile` returns 0 — which the crashes above never do.
No speed regression (fib=179ms vs 174ms baseline, within noise).

### 3. ~~Compile-on-load for dynamic imports~~ ✅ DONE
`fpy_jit_import(name)` tries to find a `.py` file on `sys.path`, compile it
natively via the JIT infrastructure (CodeGen → LLVM IR → MCJIT, in process),
and execute its top-level code. It goes through `jit_compile`, so item 2's
two JIT bugs apply here too. Falls back to CPython's import system for
.pyd/.so modules or when the JIT compiler isn't available.
Static imports already compile natively at build time via multi-file compilation.
No speed regression (fib=172ms vs 174ms baseline).

### 4. ~~Native collections module~~ ✅ DONE
~~Implement the most-used collections types natively.~~
All implemented: Counter, defaultdict, deque, OrderedDict, namedtuple, ChainMap.

### 5. ~~Hybrid pyobj method compilation~~ ✅ DONE
Method bodies are ALWAYS compiled to native LLVM IR regardless of metaclass.
When a bridge metaclass is used, methods are wrapped via `cpython_wrap_native()`
for the metaclass call, but the class uses native vtable dispatch for runtime
method invocation. Inheritance chains (including polymorphism) all work natively.
- Pass wrapped callables in the namespace dict to Meta.__new__

**Result:** Class creation uses CPython's metaclass protocol, but
method execution is native speed.

## Planned — Medium Priority

### 6. ~~Native `type()` on pyobj values~~ ✅ DONE
~~`type(x)` where x is from CPython.~~ Implemented: calls `fpy_cpython_typeof()`
at runtime for OBJ-tagged values, returns actual Python type name.

### 7. ~~pyobj iteration protocol~~ ✅ DONE
~~`for x in cpython_object` through the bridge.~~ Implemented:
`fpy_cpython_iter()` + `fpy_cpython_iter_next()` with StopIteration detection.

### 8. ~~pyobj arithmetic~~ ✅ DONE
~~`cpython_value + native_value` through the bridge.~~ Implemented:
`fpy_cpython_binop()` / `fpy_cpython_rbinop()` using Python number protocol.

### 9. ~~Native `re` module~~ SKIPPED
Uses CPython bridge — implementing a full regex engine from scratch isn't practical.

### 10. ~~Native `logging` module~~ ✅ DONE
~~Django uses logging extensively.~~ Implemented: basicConfig, root logger,
named loggers, setLevel, format strings with %(levelname)s/%(message)s/%(name)s,
message interpolation with %s/%d/%f, file output.

### 11. ~~Native `typing` module~~ ✅ DONE
~~All typing constructs are no-ops at runtime.~~ Implemented: Optional, List,
Dict, Union, TYPE_CHECKING=False, @overload → no-op, cast() → identity.

### 12. ~~Native `abc` module~~ ✅ DONE
~~Abstract Base Classes.~~ Implemented: ABC as normal base class,
@abstractmethod as no-op decorator.

## Planned — Lower Priority

### 13. ~~Native `functools` module~~ ✅ DONE
- `wraps` → ✅ no-op decorator
- `reduce` → ✅ inline loop with direct function call
- `singledispatch` → ✅ already native!
- `partial` → ✅ compile-time wrapper function generation
- `lru_cache` → ✅ per-function dict cache with maxsize eviction

### 14. ~~Native `contextlib` module~~ ✅ DONE
~~contextmanager/suppress.~~ Implemented: contextmanager and suppress as no-op
decorators/context managers (generators already support with-statement natively).

### 15. ~~Native `decimal` module~~ ✅ DONE
~~Fixed-point decimal arithmetic.~~ Implemented: 18-digit precision via int64
coefficient + exponent. Supports Decimal(str), Decimal(int), arithmetic
(+, -, *, /), comparison, string conversion. Used by Django's DecimalField.

### 16. ~~Native `pathlib` module~~ ✅ DONE
~~Object-oriented filesystem paths.~~ Implemented: Path construction, `/` operator,
`.name`, `.parent`, `.suffix`, `.stem`, `.exists()`, `.is_file()`, `.is_dir()`,
`.resolve()`, `.read_text()`, `.write_text()`, `.iterdir()`, `.with_suffix()`,
`.joinpath()`, `Path.cwd()`. `.iterdir()` is typed `list[Path]` — both runtimes
materialize the listing into an `FpyList*` of OBJ-tagged Paths.

Representation: a Path is an opaque pointer carrying the "path" type tag. In
host/bridge builds that is a `PyObject*`; in pure mode (`runtime/pathlib_pure.c`,
no CPython) it is an `FpyPurePath` header block whose text lives at offset 40 —
past the offsets the OBJ refcount dispatcher blind-probes for object magics.
Path text is therefore never at offset 0; reach it via `fastpy_path_as_cstr()`.

### 17. ~~Linux/macOS support~~ ✅ DONE
~~Clang/GCC build scripts for the runtime.~~ Implemented:
- Dynamic LLVM triple + data layout (auto-detects host platform)
- Platform-adaptive toolchain: gcc/clang linking on POSIX, MSVC on Windows
- `build_runtime.sh` for Linux/macOS (cc -fPIC, dynamic Python include)
- `fpy_strdup` compat macro (replaces all `_strdup` calls)
- PIC relocation on POSIX, conditional Py_SetPythonHome
- Dynamic Python lib discovery via sysconfig

### 18. ~~REPL mode~~ ✅ DONE as a statement-replay REPL (2026-04-28) — to be replaced by 19
The "SKIPPED — doesn't apply to an AOT compiler" note that stood here was
overtaken: `python -m compiler --repl` (`compiler/repl.py`, commit 7e931b2,
with the web playground) has existed since 2026-04-28. Each input is compiled
with the whole session so far replayed in front of it — every earlier
statement, with function and class redefinitions deduplicated — then linked
into an executable and run as a new process, with the replayed output hidden
behind a sentinel line.

That is correct for pure computation, and has costs built into the design:
- **Every input pays a full build and a process start** (codegen, LLVM, the
  MSVC link, launch) — about a second for a one-line input even on an empty
  session.
- **The cost grows with the session**, because each input recompiles and
  re-runs everything before it: a session is quadratic in its length.
- **Side effects repeat.** Replay re-executes earlier statements, so file
  writes, network calls and `input()` happen again on every later line, and
  random or time-based values are re-drawn — a name shown holding one value
  can hold another by the next line. Only replayed *stdout* is hidden.
- **Redefinition rewrites history.** An old definition is replaced by `pass`
  in the log, so on replay an earlier statement that called the old version
  calls the new one, or nothing.
- An input that raises is dropped, and a successful input's stderr is
  discarded.

### 19. In-process JIT REPL — PLANNED
Replace item 18's replay with a REPL that compiles each input in memory and
runs it in the same process, on the MCJIT path `exec()` already uses (item 2,
`compiler/jit.py`): the runtime is loaded once, the session's objects stay
live between inputs, and nothing is replayed, linked, or launched.

**Cost per input, measured 2026-09-26** — the steps `jit_compile` runs,
warm, for inputs from `x = 2` to a six-line class: codegen 50–95 ms, LLVM
parse + verify + machine code 10–50 ms, so about 60–130 ms, flat however long
the session gets (item 18: a second or more, growing). Codegen dominates, and
every module's IR carries the same 656 runtime declarations (~40 KB) that a
REPL session could emit once.

**Prerequisites and design points:**
1. **The two JIT bugs first** (item 2): today the JIT cannot run
   `print(1, 2)`, and a REPL exercises the whole language, so it needs every
   runtime function *and variable* codegen can reference to resolve — and an
   input that still cannot be JIT-compiled to fall back to CPython rather
   than crash the session.
2. **Host process.** JIT'd code resolves the runtime inside the running
   executable, and only a fastpy-built executable contains the runtime (it is
   linked statically; no runtime DLL is built). So the REPL runs inside a
   small fastpy-compiled host, which already embeds CPython to run the
   compiler exactly as `exec()` does, and `--repl` launches it. Building the
   runtime as a DLL for a plain Python process to load is the alternative;
   it is more build machinery for nothing the host lacks.
3. **Globals that persist.** Each JIT'd module is standalone today, and its
   top-level names die with it. In REPL mode, top-level names become session
   globals the runtime holds as tagged values, looked up by name, so a later
   input sees them and may rebind one to a value of another type — which
   static typing across inputs cannot allow, since an earlier input was
   compiled before the later one existed. Function bodies keep fastpy's
   specialisation of their locals; only the module level is dynamic.
4. **Late binding by name**, as in CPython: a call to a module-level function
   or class goes through its global, so a redefinition in a later input is
   seen by code compiled earlier (including the old function's own recursive
   calls) instead of being bound statically.
5. **An exception ends the input, not the session.** It is printed as a
   traceback and the REPL continues with the state the input left — nothing
   is re-run.
6. **Display as CPython's REPL does:** a bare expression's `repr()` unless it
   is `None`, with `_` bound to the last result; multi-line blocks end at a
   blank line.

Item 18's replay REPL stays until this passes its tests, then goes.

### Phase 5-6: Module registry + Cleanup — ✅ DONE (via REFACTORING_ANALYSIS Phases B-D)
- 6 dispatch registry dicts replace if/elif chains
- VKind migration: 1400+ VKind refs, string-tag comparisons eliminated
- God methods decomposed (1400→300 lines each)
- elif chain conversion across ~25 dispatch sites

## Stats

| Metric | Value |
|--------|-------|
| Total tests passing | 836 (1 skipped — django not installed) |
| Stdlib .py files compiling | 104/104 |
| Stdlib module tests | 134/134 |
| Platforms | Windows x64, Linux x64 (WSL Ubuntu tested) |
| Python versions | 3.11, 3.12, 3.13, 3.14 |
| Codegen refactor phases | 4/6 complete |
