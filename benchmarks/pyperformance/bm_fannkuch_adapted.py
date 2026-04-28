"""Fannkuch benchmark - adapted to avoid bound method refs and slice-with-step.
Also uses in-place element copy instead of perm1[:] to avoid allocation overhead."""

import time


def fannkuch(n):
    count = list(range(1, n + 1))
    max_flips = 0
    m = n - 1
    r = n
    perm1 = list(range(n))
    perm = list(range(n))

    while True:
        while r != 1:
            count[r - 1] = r
            r -= 1

        if perm1[0] != 0 and perm1[m] != m:
            # In-place copy instead of perm = perm1[:] (avoids allocation)
            ci = 0
            while ci < n:
                perm[ci] = perm1[ci]
                ci += 1
            flips_count = 0
            k = perm[0]
            while k:
                # Manual reverse of perm[0:k+1]
                i = 0
                j = k
                while i < j:
                    tmp = perm[i]
                    perm[i] = perm[j]
                    perm[j] = tmp
                    i += 1
                    j -= 1
                flips_count += 1
                k = perm[0]

            if flips_count > max_flips:
                max_flips = flips_count

        done = False
        while r != n:
            # perm1.insert(r, perm1.pop(0))
            front = perm1[0]
            i = 0
            while i < r:
                perm1[i] = perm1[i + 1]
                i += 1
            perm1[r] = front
            count[r] -= 1
            if count[r] > 0:
                done = False
                break
            r += 1
            done = True

        if done:
            return max_flips


ARG = 10

if __name__ == "__main__":
    t0 = time.perf_counter()
    result = fannkuch(ARG)
    elapsed = time.perf_counter() - t0
    print("fannkuch result=")
    print(result)
    print("expected: 38")
