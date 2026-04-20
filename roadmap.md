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

### 1. Fully native metaclass protocol
Replace CPython exec_get fallback with native implementation.

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

### 2. Runtime JIT compilation for compile()/exec()
When `compile(source, ...)` or `exec(dynamic_string)` is called at runtime:
- Parse the string with Python's ast module (via embedded CPython)
- Feed the AST to our compiler (CodeGen)
- Generate LLVM IR → machine code
- Execute the machine code

**Benefit:** Django's template engine compiles templates once, executes many
times. With JIT, the template code runs at native speed instead of
interpreter speed.

**Implementation:**
- `fpy_runtime_compile(source_str) → function_pointer`
- Uses llvmlite's MCJIT to compile IR to machine code in-process
- Cache compiled code keyed by source hash

### 3. Compile-on-load for dynamic imports
When `importlib.import_module(name)` resolves to a `.py` file:
- Read the source
- Compile it with our compiler (single-file compilation)
- Execute the compiled module
- Cache the compiled module

**Benefit:** Dynamically loaded modules run at native speed, not
interpreter speed. Django's app loading, middleware discovery, URL
routing all benefit.

**Implementation:**
- Runtime function: `fpy_import_module(name) → module_object`
- Checks local filesystem for .py files
- Falls back to CPython for .pyd/.so extensions and frozen modules

### 4. ~~Native collections module~~ ✅ DONE
~~Implement the most-used collections types natively.~~
All implemented: Counter, defaultdict, deque, OrderedDict, namedtuple, ChainMap.

### 5. Hybrid pyobj method compilation
When a class routes through CPython bridge (because of complex metaclass
or imported base class), compile its method bodies natively:
- Parse the class AST
- Compile each method as a native function
- Wrap native functions as CPython callables (FpyNativeCallable)
- Pass wrapped callables in the namespace dict to Meta.__new__

**Result:** Class creation uses CPython's metaclass protocol, but
method execution is native speed.

## Planned — Medium Priority

### 6. Native `type()` on pyobj values
`type(x)` where x is from CPython should call CPython's `type()`
and return the correct type name, not our internal tag name.

### 7. pyobj iteration protocol
`for x in cpython_object:` should call `__iter__`/`__next__` through
the bridge. Currently only works for native lists/dicts.

### 8. pyobj arithmetic
`cpython_value + native_value` should convert through the bridge.
Currently fails silently or produces garbage.

### 9. Native `re` module (regex)
Implement a regex engine in C. Large but bounded:
- NFA construction from pattern
- Thompson's algorithm for matching
- Capture groups
- Common Python re API (match, search, findall, sub, split)

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

### 13. Native `functools` module (partially done)
- `wraps` → ✅ no-op decorator (metadata not tracked at native level)
- `reduce` → ✅ inline loop with direct function call
- `singledispatch` → ✅ already native!
- `partial` → TODO: emit closure wrapper
- `lru_cache` → TODO: memoization with LRU eviction

### 14. ~~Native `contextlib` module~~ ✅ DONE
~~contextmanager/suppress.~~ Implemented: contextmanager and suppress as no-op
decorators/context managers (generators already support with-statement natively).

### 15. Native `decimal` module
Fixed-point decimal arithmetic. Used by Django's DecimalField.

### 16. Native `pathlib` module
Object-oriented filesystem paths. Pure Python, would benefit from
multi-file compilation.

### 17. Linux/macOS support
- Clang/GCC build scripts for the runtime
- ELF linking instead of PE/COFF
- POSIX paths in toolchain.py

### 18. REPL mode
Interactive compilation: compile and execute each line as it's entered.
Requires incremental compilation support.
