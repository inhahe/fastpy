"""
Fannkuch benchmark from pyperformance (the official CPython benchmark suite).

The Computer Language Benchmarks Game
http://benchmarksgame.alioth.debian.org/

Contributed by Sokolov Yura, modified by Tupteq.

Source: pyperformance 1.14.0 (bm_fannkuch/run_benchmark.py)
Adapted for standalone timing (no pyperf dependency).
"""

import time


def fannkuch(n):
    count = list(range(1, n + 1))
    max_flips = 0
    m = n - 1
    r = n
    perm1 = list(range(n))
    perm = list(range(n))
    perm1_ins = perm1.insert
    perm1_pop = perm1.pop

    while 1:
        while r != 1:
            count[r - 1] = r
            r -= 1

        if perm1[0] != 0 and perm1[m] != m:
            perm = perm1[:]
            flips_count = 0
            k = perm[0]
            while k:
                perm[:k + 1] = perm[k::-1]
                flips_count += 1
                k = perm[0]

            if flips_count > max_flips:
                max_flips = flips_count

        while r != n:
            perm1_ins(r, perm1_pop(0))
            count[r] -= 1
            if count[r] > 0:
                break
            r += 1
        else:
            return max_flips


ARG = 10

if __name__ == "__main__":
    t0 = time.perf_counter()
    result = fannkuch(ARG)
    elapsed = time.perf_counter() - t0
    print("fannkuch(%d): %d flips, %.1f ms" % (ARG, result, elapsed * 1000))
