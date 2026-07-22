# fastpy vs C++ vs CPython Benchmark Report

All benchmarks compiled with MSVC /O2 (C++) and LLVM -O2 (fastpy).
Times are wall-clock best-of-3 including subprocess startup (~7ms fastpy, ~1ms C++).
fp/C++ ratio uses compute-only time (startup subtracted). Values < 1x
mean fastpy is faster than C++.

## COMMON PATTERNS (loops, functions, containers)

| Benchmark              | fastpy | C++ /O2 | CPython |  fp/C++ | vs CPy |
|------------------------|--------|---------|---------|---------|--------|
| tight int loop 10M     |   11ms |     9ms |  1536ms |    0.5x |  140x  |
| float math loop 1M     |   14ms |     8ms |   190ms |    1.0x |   14x  |
| recursive fib(35)      |   33ms |    44ms |  1666ms |    0.6x |   50x  |
| function calls 10M     |   11ms |    19ms |  1898ms |    0.2x |  173x  |
| list build+sum 100K    |   12ms |     7ms |    56ms |    0.8x |    5x  |
| dict lookup 1K x 1K    |   14ms |    13ms |   217ms |    0.6x |   16x  |
| string concat 100K     |   14ms |     7ms |    42ms |    1.2x |    3x  |

## CLASS/OOP PATTERNS (attributes, methods, inheritance)

| Benchmark              | fastpy | C++ /O2 | CPython |  fp/C++ | vs CPy |
|------------------------|--------|---------|---------|---------|--------|
| attr access 10M        |   10ms |     7ms |  1635ms |    0.5x |  164x  |
| method call 1M         |   15ms |     7ms |   298ms |    1.3x |   20x  |
| dist_sq method 1M      |   14ms |     7ms |   272ms |    1.2x |   19x  |
| object creation 100K   |   31ms |    12ms |    97ms |    2.2x |    3x  |
| inherit + polymorphism |   24ms |    12ms |   116ms |    1.5x |    5x  |

## LESS COMMON / SLOWER PATTERNS

| Benchmark              | fastpy | C++ /O2 | CPython |  fp/C++ | vs CPy |
|------------------------|--------|---------|---------|---------|--------|
| linked list traverse   |   32ms |    12ms |   112ms |    2.3x |    4x  |
| recursive tree sum     |   23ms |     9ms |   119ms |    2.0x |    5x  |
| exception handling     |   13ms |     7ms |    56ms |    1.0x |    4x  |
| list comp + filter     |   16ms |     8ms |    42ms |    1.3x |    3x  |

## Compute-Only Detail (startup subtracted)

| Benchmark              | fp compute | C++ compute | ratio |
|------------------------|------------|-------------|-------|
| tight int loop 10M     |        4ms |         8ms |  0.5x |
| float math loop 1M     |        7ms |         7ms |  1.0x |
| recursive fib(35)      |       26ms |        43ms |  0.6x |
| function calls 10M     |        4ms |        18ms |  0.2x |
| list build+sum 100K    |        5ms |         6ms |  0.8x |
| dict lookup 1K x 1K    |        7ms |        12ms |  0.6x |
| string concat 100K     |        7ms |         6ms |  1.2x |
| attr access 10M        |        3ms |         6ms |  0.5x |
| method call 1M         |        8ms |         6ms |  1.3x |
| dist_sq method 1M      |        7ms |         6ms |  1.2x |
| object creation 100K   |       24ms |        11ms |  2.2x |
| inherit + polymorphism |       17ms |        11ms |  1.5x |
| linked list traverse   |       25ms |        11ms |  2.3x |
| recursive tree sum     |       16ms |         8ms |  2.0x |
| exception handling     |        6ms |         6ms |  1.0x |
| list comp + filter     |        9ms |         7ms |  1.3x |

## Summary

### vs C++ (compute-only, startup subtracted)

**12 of 16 benchmarks within 1.3x of C++ speed.**

4 OOP-heavy benchmarks run at 1.5–2.3x C++ due to GC overhead on mass
object allocation (~160ns/object for malloc + gc_track + gc_maybe_collect).
C++ uses stack allocation with no GC.

| Category         | Typical fp/C++ ratio                         |
|------------------|----------------------------------------------|
| Tight loops      | 0.5–0.6x (faster than C++)                   |
| Function calls   | 0.2x (LLVM inlines across FV boundary)       |
| Dict operations  | 0.6x                                         |
| Attr access      | 0.5x                                         |
| Method calls     | 1.2–1.3x                                     |
| Object-heavy OOP | 1.5–2.3x (GC overhead)                       |

Optimization path for the OOP outliers: arena allocation, GC batching,
or compile-time escape analysis to bypass GC tracking for non-escaping objects.

### vs CPython

| Range     | Description                           |
|-----------|---------------------------------------|
| 140–173x  | Tight loops, function calls           |
| 14–50x    | Float math, recursion, dicts          |
| 3–20x     | Methods, containers, strings, objects |

**Geometric mean across all 16 benchmarks: ~13x faster than CPython.**

## Compiler Speed (compile-time / developer iteration)

These measure how fast fastpy *compiles* a program (not how fast the output
runs). Wall-clock is best-of-5 with warm caches (runtime `.obj` cache and MSVC
env cache both populated). Measured on x64 Windows / MSVC.

### End-to-end compile wall time (small program, `fib(30)`)

| Config                        | compile wall (best-of-5) | vs baseline |
|-------------------------------|--------------------------|-------------|
| Baseline (`ae2da03`)          | 2400 ms                  | —           |
| + MSVC env cache + codegen    | ~200 ms                  | **−92%**    |

The dominant cost in the baseline was re-invoking `vcvars64.bat` on **every**
link to discover `link.exe` and the MSVC environment (~2.1 s per link). The
MSVC environment is now captured once, cached in-process and on disk
(`runtime/_msvc_env_cache.json`, keyed on the vcvars path + mtime), and
`link.exe` is invoked directly with that environment. `_link_windows` dropped
from ~2148 ms to ~141 ms.

### Codegen hotspot (`_detect_class_container_attrs`, class-heavy program: Richards)

| Config                | cumulative (per-call) | vs baseline |
|-----------------------|-----------------------|-------------|
| Baseline (`ae2da03`)  | 7.51 s (179 ms/call)  | —           |
| + hoisted tree walks  | 1.08 s (26 ms/call)   | **−86%**    |

Two nested full-AST walks that were re-run for every candidate receiver were
loop-invariant; they are now precomputed once into `_ctor_first` /
`_ctor_fixpoint` maps before the per-receiver loop. Semantics are identical
(verified against the full differential test suite — 593 tests, no regressions).

### Tunable backend optimization level

The LLVM backend opt level is now controlled by the `FASTPY_OPT` environment
variable (default `2`). `-O3` was A/B-tested and showed no reliable win on
these benchmarks (regressions amid noise), so `-O2` remains the default.
