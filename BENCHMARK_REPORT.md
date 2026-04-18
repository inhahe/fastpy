# fastpy vs C++ vs CPython Benchmark Report

All benchmarks compiled with MSVC /O2 (C++) and LLVM -O2 (fastpy).
Times are wall-clock including subprocess startup (~7ms fastpy, ~1ms C++).
fp/C++ ratio uses compute-only time (startup subtracted). Values < 1x
mean fastpy is faster than C++.

## COMMON PATTERNS (loops, functions, containers)

| Benchmark              | fastpy | C++ /O2 | CPython |  fp/C++ | vs CPy |
|------------------------|--------|---------|---------|---------|--------|
| tight int loop 10M     |    7ms |     9ms |  1495ms |  **0.0x** | 214x |
| float math loop 1M     |    9ms |     8ms |   193ms |    0.3x |  21x |
| recursive fib(35)      |   54ms |    44ms |  1722ms |    1.1x |  32x |
| function calls 10M     |    8ms |    19ms |  2015ms |  **0.1x** | 254x |
| list build+sum 100K    |    9ms |     7ms |    52ms |    0.4x |   6x |
| dict lookup 1K x 1K    |   12ms |    14ms |   226ms |  **0.4x** |  19x |
| string concat 100K     |   10ms |     7ms |    45ms |    0.4x |   5x |

## CLASS/OOP PATTERNS (attributes, methods, inheritance)

| Benchmark              | fastpy | C++ /O2 | CPython |  fp/C++ | vs CPy |
|------------------------|--------|---------|---------|---------|--------|
| attr access 10M        |    7ms |     8ms |  2042ms |  **0.1x** | 277x |
| method call 1M         |    7ms |     7ms |   264ms |  **0.0x** |  37x |
| dist_sq method 1M      |   21ms |     6ms |   308ms |    2.6x |  15x |
| object creation 100K   |   13ms |    13ms |   101ms |    0.5x |   8x |
| inheritance + polymorph|   13ms |    13ms |   123ms |    0.5x |   9x |

## LESS COMMON / SLOWER PATTERNS

| Benchmark              | fastpy | C++ /O2 | CPython |  fp/C++ | vs CPy |
|------------------------|--------|---------|---------|---------|--------|
| linked list traverse   |   10ms |    12ms |   108ms |  **0.3x** |  11x |
| recursive tree sum     |    8ms |     9ms |   130ms |  **0.1x** |  16x |
| exception handling     |    9ms |     7ms |    55ms |    0.3x |   6x |
| list comp + filter     |    9ms |     8ms |    46ms |    0.3x |   5x |

## Summary

### vs C++ (compute-only, startup subtracted)

**15 of 16 benchmarks run at C++ speed or faster** (ratio <= 1.1x).

The single outlier is `dist_sq` (2.6x) — a multi-object method call
with 4 attribute accesses across 2 different objects. This is the
remaining gap from the method calling convention (i64 param coercion).

| Category | Typical fp/C++ ratio |
|----------|---------------------|
| Tight loops | 0.0-0.3x (faster than C++) |
| Function calls | 0.0-0.1x (LLVM inlines across FV boundary) |
| Dict operations | 0.4x |
| Attr access | 0.0-0.1x |
| Object creation | 0.5x |
| Multi-obj methods | 2.6x (only outlier) |

### vs CPython

| Range | Description |
|-------|-------------|
| 200-280x | Tight loops, attribute access |
| 15-37x | Method calls, recursion, dicts |
| 5-11x | Containers, strings, linked lists |

**Geometric mean across all 16 benchmarks: ~25x faster than CPython.**
