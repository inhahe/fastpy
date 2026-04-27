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
# Windows
python -m compiler hello.py -o hello.exe
./hello.exe

# Linux / macOS
python -m compiler hello.py -o hello
./hello

# Or compile in Python
from compiler.pipeline import compile_source
result = compile_source('print("hello world")')
```

### Requirements

- Python 3.11+ with llvmlite (`pip install llvmlite`)
- **Windows:** MSVC Build Tools (for linking)
- **Linux/macOS:** gcc or clang (for linking), Python headers (`python3-dev`)
- CPython headers/libs for the target Python version (for .pyd/.so module import support)

### Multi-Python version targeting

Compile against any installed Python version:

```bash
python -m compiler hello.py --python-version 3.12
python -m compiler hello.py --python-version 3.14
```

An ABI version check at startup verifies the compiled-against Python version matches the runtime Python version.

## What's supported

### Language features (66/66 audit, 405/405 tests, 101/101 regressions)

**Error reporting:**
- **Syntax errors**: CPython-quality display with source line, caret, and column position (via `traceback.format_exception_only`)
- **Runtime errors**: Python-style tracebacks with shadow call stack showing `File "source.py", line N, in func(arg=value)` for each frame, with per-frame call-site line accuracy and function argument values. All runtime errors (IndexError, KeyError, ValueError, AttributeError, ZeroDivisionError) are catchable via try/except

- **Core**: functions, classes, closures, decorators, generators, lambda, recursion, `*args`/`**kwargs`, default arguments, global/nonlocal, `@singledispatch` (native switch dispatch), first-class functions (function aliases, indirect calls, `__call__` dispatch)
- **Control flow**: if/elif/else, for/while (with break/continue/else), try/except/finally/else, with, match/case, assert, raise/raise from
- **OOP**: inheritance, multiple inheritance, super, `@staticmethod`, `@classmethod`, `@property` (get/set), nested classes, full metaclass support (`metaclass=`, `__new__`, `__init_subclass__`, `__class_getitem__`), `__slots__`
- **Dunders**: `__add__`, `__sub__`, `__mul__`, `__matmul__` (`@`), `__neg__`, `__eq__`, `__lt__`, `__str__`, `__repr__`, `__getitem__`/`__setitem__`/`__delitem__`, `__len__`, `__bool__`, `__contains__`, `__iter__`/`__next__`, `__call__`, `__hash__`
- **Containers**: list, dict, tuple, set (O(1) hash-table-backed), frozenset, comprehensions (list/dict/set with filters), `{**a, **b}` unpacking, slice assignment
- **Strings**: f-strings (with `=`, `!r`, format specs), all common methods (split, join, replace, strip, find, upper, lower, etc.), `%` formatting, `.format()`
- **Generators**: yield, yield from, generator expressions, native send/close/throw (state-machine compilation)
- **Async**: async def, await, `asyncio.run()`, `asyncio.gather()`, `asyncio.sleep()` — all compiled natively (sequential execution, no CPython bridge)
- **Pattern matching**: match/case with literal, capture, guard, or, wildcard, sequence, singleton (None/True/False) patterns (missing: star/mapping/class patterns — see [UNIMPLEMENTED.md](UNIMPLEMENTED.md))
- **Exceptions**: try/except/finally/else, except* (ExceptionGroup), bare raise, raise from
- **Multi-file compilation**: `from mymodule import func` resolves local `.py` files and packages (`mylib/module.py`), compiles them inline. Recursive import resolution with circular import detection.
- **Imports**: native math/json/os/asyncio/weakref, local `.py` modules compiled inline, `.pyd` modules via CPython bridge
- **Builtins**: print, range, len, sorted (with key=, reverse=), min/max (with key=), int, float, str, bool, abs, sum, map, filter, enumerate, zip, isinstance, type, any, all, hash, next, iter, eval, exec, repr, pow, divmod, chr, ord, hex, oct, bin, round, dict, list, tuple, set, locals, globals, getattr/setattr/hasattr/delattr
- **Type hints**: accepted and ignored (full compatibility with annotated code). With `--typed`/`-T`, type annotations drive native LLVM code generation for annotated variables (skip FpyValue overhead). Container annotations (`list[int]`, `list[str]`, `dict[str, int]`) provide element type info for optimized subscript access and iteration. Annotations are validated: if any assignment in scope contradicts the declared type, the variable silently falls back to full box (with a compile-time warning). With `--typed --int64`, annotated `int` arithmetic uses LLVM overflow intrinsics (SIMD-friendly, no runtime calls). Per-variable overflow control via `typing.Annotated` markers and constructor functions for both 64-bit (`Unchecked`/`Checked`, `unchecked_int()`/`checked_int()`) and 32-bit (`Unchecked32`/`Checked32`, `unchecked_int32()`/`checked_int32()`) arithmetic — see [fastpy shim package](#fastpy-shim-package)

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

Tested with: math (native), json, os, os.path, hashlib, datetime, re, collections, random, string, numpy. **134/134 stdlib modules now compile successfully.**

The `math` module is compiled natively (direct C libm calls, no Python runtime needed). All other modules route through an embedded CPython interpreter.

### fastpy shim package

The `fastpy` package provides CPython-compatible types and markers that the compiler recognizes for native code generation. Code using these features runs identically under CPython (for development/testing) and under the fastpy compiler (for native performance).

#### Per-variable integer overflow control

```python
from typing import Annotated
from fastpy import Unchecked, Checked, Unchecked32, Checked32
from fastpy import unchecked_int, checked_int, unchecked_int32, checked_int32

# 64-bit modes
x: Annotated[int, Unchecked] = 0   # raw i64, wraps on overflow
y: Annotated[int, Checked] = 0     # i64 overflow → OverflowError

# 32-bit modes (arithmetic in i32, stored as i64)
a: Annotated[int, Unchecked32] = 0 # raw i32, wraps at 32-bit boundary
b: Annotated[int, Checked32] = 0   # i32 overflow → OverflowError

# Constructor functions — equivalent to Annotated markers
p = unchecked_int(42)               # same as Annotated[int, Unchecked]
q = checked_int(42)                 # same as Annotated[int, Checked]
r = unchecked_int32(42)             # same as Annotated[int, Unchecked32]
s = checked_int32(42)               # same as Annotated[int, Checked32]
```

| Mode | Width | Overflow behavior | How to enable |
|------|-------|------------------|---------------|
| **Default** | 64-bit | BigInt promotion | No annotation needed |
| **Checked** | 64-bit | `OverflowError` | `Annotated[int, Checked]` / `checked_int()` / `--typed --int64` |
| **Unchecked** | 64-bit | Silent wrap | `Annotated[int, Unchecked]` / `unchecked_int()` |
| **Checked32** | 32-bit | `OverflowError` | `Annotated[int, Checked32]` / `checked_int32()` |
| **Unchecked32** | 32-bit | Silent wrap at 2^31 | `Annotated[int, Unchecked32]` / `unchecked_int32()` |

Under CPython: markers are ignored by `Annotated`; i64 constructors return `int(x)`, i32 constructors wrap to the signed 32-bit range.

## Architecture

```
source.py  -->  ast.parse()  -->  CodeGen  -->  LLVM IR  -->  .obj  -->  .exe/.elf
                                    |                          |
                              compiler/codegen.py     MSVC (Windows) / gcc/clang (Linux/macOS)
                              (Python, ~21k lines)            |
                                                     runtime/*.c (linked in)
```

### File map

| Path | Description |
|------|-------------|
| `compiler/codegen.py` | LLVM IR code generation from Python AST |
| `compiler/pipeline.py` | Compilation pipeline: parse, check, codegen, link |
| `compiler/__main__.py` | CLI: `python -m compiler source.py [-o output] [-t]` |
| `compiler/toolchain.py` | Platform toolchain detection and linking (MSVC on Windows, gcc/clang on Linux/macOS) |
| `runtime/objects.c` | Object system: FpyValue, FpyList, FpyDict, FpyObj, sets, closures |
| `runtime/runtime.c` | Core runtime: print, exceptions, math, string ops, entry point |
| `runtime/cpython_bridge.c` | CPython embedding for .pyd imports and eval/exec |
| `runtime/threading.h/c` | Threading primitives: GIL, mutexes, TLS, per-object locks |
| `runtime/objects.h` | Type definitions, tag constants, value constructors |
| `runtime/build_runtime.sh` | Linux/macOS runtime build script (gcc/clang) |
| `fastpy/` | CPython-compatible shim package: `Unchecked`/`Checked`/`Unchecked32`/`Checked32` markers, `unchecked_int()`/`checked_int()`/`unchecked_int32()`/`checked_int32()`, `Int32`/`UInt32`/`Int64`/`UInt64` |
| `fastpy/_fastints.c` | CPython C extension for `Int32`/`UInt32`/`Int64`/`UInt64` fixed-width types (replaces pure-Python `ints.py` for speed) |
| `setup.py` | Build script for the C extension (`python setup.py build_ext --inplace`) |
| `tests/` | Differential test suite (405 tests, compared against CPython) + 96 regression tests |
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

- **eval()/exec()** with literal string arguments are compiled inline at compile time (zero overhead). Dynamic strings route through CPython with automatic locals namespace injection
- **`re` module** routes through CPython bridge (full regex engine is impractical to reimplement natively)
- **.pyd/.so imports** (numpy, etc.) use CPython bridge for bindings — the extension's C code runs natively, only the PyObject* marshalling goes through the bridge

See [UNIMPLEMENTED.md](UNIMPLEMENTED.md) for the full list.

## License

MIT
