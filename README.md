# fastpy

An ahead-of-time Python compiler that produces native executables. Compiles Python source to LLVM IR via [llvmlite](https://github.com/numba/llvmlite), then links against a lightweight C runtime to produce standalone binaries.

**Any valid Python program is valid fastpy.** The compiler adds performance, not restrictions.

## Performance

Benchmarked against C++ (`/O2`) and CPython 3.14 on x64 Windows:

| Benchmark | fastpy | C++ | CPython | vs C++ | vs CPython |
|-----------|--------|-----|---------|--------|------------|
| Integer loop (1B iterations) | 7ms | 9ms | 1495ms | **faster** | **254x** |
| Float math | 9ms | 8ms | 193ms | ~1x | **21x** |
| Recursive fibonacci | 54ms | 44ms | 1722ms | 1.1x | **32x** |
| Function calls | 8ms | 19ms | 2015ms | **faster** | **254x** |
| Dict lookup | 12ms | 14ms | 226ms | **faster** | **19x** |
| Attribute access | 7ms | 8ms | 2042ms | **faster** | **277x** |
| Method dispatch | 7ms | 7ms | 264ms | **equal** | **37x** |
| Linked list traversal | 10ms | 12ms | 108ms | **faster** | **11x** |

fastpy is typically **10-250x faster than CPython** and **within 1-2x of C++** on equivalent code. LLVM's optimizer enables constant folding, inlining, and autovectorization that sometimes beats hand-written C++.

## Quick start

```bash
# Compile and run
python -m compiler hello.py -o hello.exe
./hello.exe

# Or compile in Python
from compiler.pipeline import compile_source
result = compile_source('print("hello world")')
```

### Requirements

- Python 3.13+ with llvmlite (`pip install llvmlite`)
- MSVC Build Tools (for linking on Windows)
- CPython 3.14 headers/libs (for .pyd module import support)

## What's supported

### Language features (66/66 audit, 405/405 tests)

- **Core**: functions, classes, closures, decorators, generators, lambda, recursion, `*args`/`**kwargs`, default arguments, global/nonlocal
- **Control flow**: if/elif/else, for/while (with break/continue/else), try/except/finally/else, with, match/case, assert, raise/raise from
- **OOP**: inheritance, multiple inheritance, super, `@staticmethod`, `@classmethod`, `@property` (get/set), nested classes, metaclass, `__slots__`
- **Dunders**: `__add__`, `__sub__`, `__mul__`, `__neg__`, `__eq__`, `__lt__`, `__str__`, `__repr__`, `__getitem__`/`__setitem__`/`__delitem__`, `__len__`, `__bool__`, `__contains__`, `__iter__`/`__next__`, `__call__`, `__hash__`
- **Containers**: list, dict, tuple, set (O(1) hash-table-backed), frozenset, comprehensions (list/dict/set with filters), `{**a, **b}` unpacking, slice assignment
- **Strings**: f-strings (with `=`, `!r`, format specs), all common methods (split, join, replace, strip, find, upper, lower, etc.), `%` formatting, `.format()`
- **Generators**: yield, yield from, generator expressions, send/close/throw (via CPython bridge)
- **Async**: async def, await (via CPython bridge)
- **Pattern matching**: match/case with literal, capture, guard, or, wildcard, sequence patterns
- **Exceptions**: try/except/finally/else, except* (ExceptionGroup), bare raise, raise from
- **Imports**: `import module`, `from module import name` (native math, .pyd bridge for everything else)
- **Builtins**: print, range, len, sorted (with key=, reverse=), min/max (with key=), int, float, str, bool, abs, sum, map, filter, enumerate, zip, isinstance, type, any, all, hash, next, iter, eval, repr, pow, divmod, chr, ord, hex, oct, bin, round, dict, list, tuple, set, getattr/setattr/hasattr/delattr
- **Type hints**: accepted and ignored (full compatibility with annotated code)

### Threading

Three compile-time modes:

```bash
python -m compiler program.py                    # single-threaded (default, fastest)
python -m compiler program.py --threading gil     # GIL mode (matches CPython)
python -m compiler program.py -t                  # free-threaded (true parallelism)
```

- Thread-local exception state and per-thread arena allocators
- Per-object locking on all container mutations (free-threaded mode)
- `threading.Thread(target=compiled_func)` works — native functions auto-wrapped as CPython callables
- GIL released around CPython bridge calls

### .pyd module support

Import any CPython extension module (.pyd):

```python
import numpy as np
a = np.array([1, 2, 3])
print(np.sum(a))        # works
print(a.shape)           # works
print(np.zeros(5))       # works
```

Tested with: math (native), json, os, os.path, hashlib, datetime, re, collections, random, string, numpy.

The `math` module is compiled natively (direct C libm calls, no Python runtime needed). All other modules route through an embedded CPython interpreter.

## Architecture

```
source.py  -->  ast.parse()  -->  CodeGen  -->  LLVM IR  -->  .obj  -->  .exe
                                    |                          |
                              compiler/codegen.py        MSVC linker
                              (Python, ~14k lines)            |
                                                     runtime/*.c (linked in)
```

### File map

| Path | Description |
|------|-------------|
| `compiler/codegen.py` | LLVM IR code generation from Python AST |
| `compiler/pipeline.py` | Compilation pipeline: parse, check, codegen, link |
| `compiler/__main__.py` | CLI: `python -m compiler source.py [-o output] [-t]` |
| `compiler/toolchain.py` | MSVC toolchain detection and linking |
| `runtime/objects.c` | Object system: FpyValue, FpyList, FpyDict, FpyObj, sets, closures |
| `runtime/runtime.c` | Core runtime: print, exceptions, math, string ops, entry point |
| `runtime/cpython_bridge.c` | CPython embedding for .pyd imports and eval/exec |
| `runtime/threading.h/c` | Threading primitives: GIL, mutexes, TLS, per-object locks |
| `runtime/objects.h` | Type definitions, tag constants, value constructors |
| `tests/` | Differential test suite (405 tests, compared against CPython) |
| `audit_features.py` | Python 3.14 feature coverage audit (66 features) |
| `benchmarks/` | Performance benchmarks vs C++ and CPython |

### Runtime value representation

Every Python value is an `FpyValue`: a tagged union of `{i32 tag, i64 data}`.

| Tag | Type | Data |
|-----|------|------|
| 0 | int | 64-bit signed integer |
| 1 | float | IEEE 754 double (bitcast) |
| 2 | str | pointer to null-terminated UTF-8 |
| 3 | bool | 0 or 1 |
| 4 | None | 0 |
| 5 | list | pointer to FpyList (growable array) |
| 6 | obj | pointer to FpyObj (class instance) |
| 7 | dict | pointer to FpyDict (hash table) |
| 8 | bytes | pointer to byte string |
| 9 | set | pointer to FpyDict (keys only) |

Objects use a bump allocator (1MB arena blocks, per-thread in threaded mode). Dicts and sets use open-addressing hash tables with FNV-1a/splitmix64 hashing. Class instances have static attribute slots at known offsets (like C structs) with a dynamic-attrs side table as fallback.

## Testing

```bash
# Full differential test suite (compiles programs, runs them, compares output to CPython)
python -m pytest tests/ -v

# Feature audit (66 Python 3.14 patterns)
python audit_features.py

# Single file
python -m compiler myprogram.py -o myprogram.exe
./myprogram.exe
```

## Known limitations

- **Generators with send()** and **async/await** run through the CPython bridge (correct but not native-speed)
- **eval()/exec()** route through CPython (no access to compiled locals)
- **Complex numbers** use the CPython bridge (no native complex arithmetic)
- **Dataclasses** compile but decorator-generated methods don't override native class methods
- **Call-on-call** `f(3)(5)` hangs — use `x = f(3); x(5)` as workaround
- No garbage collection (arena allocator, objects never freed — suitable for batch programs)

See [UNIMPLEMENTED.md](UNIMPLEMENTED.md) for the full list.

## License

MIT
