"""N-body benchmark - adapted to avoid nested tuple unpacking and dict."""

import time

PI = 3.14159265358979323
SOLAR_MASS = 4 * PI * PI
DAYS_PER_YEAR = 365.24

# Bodies stored as flat lists: [x, y, z, vx, vy, vz, mass]
sun = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, SOLAR_MASS]

jupiter = [4.84143144246472090e+00, -1.16032004402742839e+00, -1.03622044471123109e-01,
           1.66007664274403694e-03 * DAYS_PER_YEAR, 7.69901118419740425e-03 * DAYS_PER_YEAR, -6.90460016972063023e-05 * DAYS_PER_YEAR,
           9.54791938424326609e-04 * SOLAR_MASS]

saturn = [8.34336671824457987e+00, 4.12479856412430479e+00, -4.03523417114321381e-01,
          -2.76742510726862411e-03 * DAYS_PER_YEAR, 4.99852801234917238e-03 * DAYS_PER_YEAR, 2.30417297573763929e-05 * DAYS_PER_YEAR,
          2.85885980666130812e-04 * SOLAR_MASS]

uranus = [1.28943695621391310e+01, -1.51111514016986312e+01, -2.23307578892655734e-01,
          2.96460137564761618e-03 * DAYS_PER_YEAR, 2.37847173959480950e-03 * DAYS_PER_YEAR, -2.96589568540237556e-05 * DAYS_PER_YEAR,
          4.36624404335156298e-05 * SOLAR_MASS]

neptune = [1.53796971148509165e+01, -2.59193146099879641e+01, 1.79258772950371181e-01,
           2.68067772490389322e-03 * DAYS_PER_YEAR, 1.62824170038242295e-03 * DAYS_PER_YEAR, -9.51592254519715870e-05 * DAYS_PER_YEAR,
           5.15138902046611451e-05 * SOLAR_MASS]

SYSTEM = [sun, jupiter, saturn, uranus, neptune]

# Precompute pairs as list of [i, j] lists
PAIRS = [[0, 1], [0, 2], [0, 3], [0, 4],
         [1, 2], [1, 3], [1, 4],
         [2, 3], [2, 4],
         [3, 4]]


def advance(dt, n):
    bodies = SYSTEM
    pairs = PAIRS
    for step in range(n):
        for pair in pairs:
            bi = pair[0]
            bj = pair[1]
            b1 = bodies[bi]
            b2 = bodies[bj]
            dx = b1[0] - b2[0]
            dy = b1[1] - b2[1]
            dz = b1[2] - b2[2]
            dist2 = dx * dx + dy * dy + dz * dz
            mag = dt * (dist2 ** (-1.5))
            b1m = b1[6] * mag
            b2m = b2[6] * mag
            b1[3] -= dx * b2m
            b1[4] -= dy * b2m
            b1[5] -= dz * b2m
            b2[3] += dx * b1m
            b2[4] += dy * b1m
            b2[5] += dz * b1m
        for body in bodies:
            body[0] += dt * body[3]
            body[1] += dt * body[4]
            body[2] += dt * body[5]


def report_energy():
    bodies = SYSTEM
    pairs = PAIRS
    e = 0.0
    for pair in pairs:
        bi = pair[0]
        bj = pair[1]
        b1 = bodies[bi]
        b2 = bodies[bj]
        dx = b1[0] - b2[0]
        dy = b1[1] - b2[1]
        dz = b1[2] - b2[2]
        e -= (b1[6] * b2[6]) / ((dx * dx + dy * dy + dz * dz) ** 0.5)
    for body in bodies:
        vx = body[3]
        vy = body[4]
        vz = body[5]
        m = body[6]
        e += m * (vx * vx + vy * vy + vz * vz) / 2.0
    return e


def offset_momentum():
    ref = SYSTEM[0]
    px = 0.0
    py = 0.0
    pz = 0.0
    for body in SYSTEM:
        m = body[6]
        px -= body[3] * m
        py -= body[4] * m
        pz -= body[5] * m
    ref[3] = px / ref[6]
    ref[4] = py / ref[6]
    ref[5] = pz / ref[6]


ITERATIONS = 100000

if __name__ == "__main__":
    offset_momentum()
    t0 = time.perf_counter()
    e1 = report_energy()
    advance(0.01, ITERATIONS)
    e2 = report_energy()
    elapsed = time.perf_counter() - t0
    print("energy1=")
    print(e1)
    print("energy2=")
    print(e2)
