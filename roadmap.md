# Fastpy Roadmap — Path to Full CPython Compatibility

## Completed (this session)

### Core features
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
- Vtable dispatch for O(1) polymorphic method calls
- Per-class typed attributes (float/str/bool)
- FV ABI for native-typed method parameters

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

### 2. ~~Runtime JIT compilation for exec/eval~~ ✅ DONE
Two-tier system for dynamic `exec()`/`eval()`:
1. **Native JIT** (compiler/jit.py): Compiles source → LLVM IR → shared library
   (.dll/.so) → loads and calls `fastpy_main()`. Cached by source hash.
   Requires fastpy compiler + llvmlite importable at runtime.
2. **Bytecode cache** fallback: `Py_CompileString` → `PyEval_EvalCode` with
   128-entry FNV-1a hash cache. Used when JIT module not available.
The C bridge (`fpy_jit_exec`) tries native JIT first, falls back automatically.
No speed regression (fib=179ms vs 174ms baseline, within noise).

### 3. ~~Compile-on-load for dynamic imports~~ ✅ DONE
`fpy_jit_import(name)` tries to find a `.py` file on `sys.path`, compile it
natively via the JIT infrastructure (CodeGen → LLVM IR → shared lib → load),
and execute its top-level code. Falls back to CPython's import system for
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
`.joinpath()`. Path is stored as a string pointer with "path" type tag.

### 17. ~~Linux/macOS support~~ ✅ DONE
~~Clang/GCC build scripts for the runtime.~~ Implemented:
- Dynamic LLVM triple + data layout (auto-detects host platform)
- Platform-adaptive toolchain: gcc/clang linking on POSIX, MSVC on Windows
- `build_runtime.sh` for Linux/macOS (cc -fPIC, dynamic Python include)
- `fpy_strdup` compat macro (replaces all `_strdup` calls)
- PIC relocation on POSIX, conditional Py_SetPythonHome
- Dynamic Python lib discovery via sysconfig

### 18. ~~REPL mode~~ SKIPPED
Doesn't apply to an AOT compiler. Use CPython for interactive work.
