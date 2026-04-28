"""
Benchmark for sequence unpacking.
Adapted from pyperformance's bm_unpack_sequence.

Tests simple tuple/list unpacking performance.
"""

import time


def benchmark_tuple_unpacking(loops):
    i = 0
    while i < loops:
        # Tuple unpacking (2 elements)
        a, b = 1, 2
        a, b = 1, 2
        a, b = 1, 2
        a, b = 1, 2
        a, b = 1, 2

        # Tuple unpacking (3 elements)
        a, b, c = 1, 2, 3
        a, b, c = 1, 2, 3
        a, b, c = 1, 2, 3
        a, b, c = 1, 2, 3
        a, b, c = 1, 2, 3

        i += 1


def benchmark_list_unpacking(loops):
    t2 = [1, 2]
    t3 = [1, 2, 3]
    i = 0
    while i < loops:
        a, b = t2
        a, b = t2
        a, b = t2
        a, b = t2
        a, b = t2

        a, b, c = t3
        a, b, c = t3
        a, b, c = t3
        a, b, c = t3
        a, b, c = t3

        i += 1


LOOPS = 500000

t0 = time.perf_counter()
benchmark_tuple_unpacking(LOOPS)
t1 = time.perf_counter()
print("tuple_unpack ms=")
print((t1 - t0) * 1000)

t2 = time.perf_counter()
benchmark_list_unpacking(LOOPS)
t3 = time.perf_counter()
print("list_unpack ms=")
print((t3 - t2) * 1000)

print("total ms=")
print((t3 - t0) * 1000)
