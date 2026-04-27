"""
Spectral norm benchmark - adapted to avoid first-class function passing,
tuple unpacking, enumerate, and zip.
"""

import time


DEFAULT_N = 130


def eval_A(i, j):
    return 1.0 / ((i + j) * (i + j + 1) // 2 + i + 1)


def eval_A_times_u(u):
    n = len(u)
    result = []
    i = 0
    while i < n:
        partial_sum = 0.0
        j = 0
        while j < n:
            partial_sum += eval_A(i, j) * u[j]
            j += 1
        result.append(partial_sum)
        i += 1
    return result


def eval_At_times_u(u):
    n = len(u)
    result = []
    i = 0
    while i < n:
        partial_sum = 0.0
        j = 0
        while j < n:
            partial_sum += eval_A(j, i) * u[j]
            j += 1
        result.append(partial_sum)
        i += 1
    return result


def eval_AtA_times_u(u):
    tmp = eval_A_times_u(u)
    return eval_At_times_u(tmp)


LOOPS = 15

if __name__ == "__main__":
    t0 = time.perf_counter()
    for loop_i in range(LOOPS):
        u = [1.0] * DEFAULT_N

        for dummy in range(10):
            v = eval_AtA_times_u(u)
            u = eval_AtA_times_u(v)

        vBv = 0.0
        vv = 0.0

        idx = 0
        while idx < len(u):
            ue = u[idx]
            ve = v[idx]
            vBv += ue * ve
            vv += ve * ve
            idx += 1
    elapsed = time.perf_counter() - t0
    result = (vBv / vv) ** 0.5
    print(result)
    print("elapsed ms=")
    print(elapsed * 1000)
