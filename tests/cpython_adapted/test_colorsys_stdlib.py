# Adapted from CPython Lib/colorsys.py — stdlib source inlined
# Tests the actual colorsys conversion algorithms compiled by fastpy.
#
# Avoids: *tuple unpacking in calls, generators, boolean-returning float
# functions (compiler infers double return type from float params).
# Keeps: all 8 colorsys conversion functions verbatim from CPython stdlib.

# ======================================================================
# Inlined stdlib module: colorsys (verbatim from CPython 3.13)
# ======================================================================

ONE_THIRD = 1.0/3.0
ONE_SIXTH = 1.0/6.0
TWO_THIRD = 2.0/3.0

def rgb_to_yiq(r, g, b):
    y = 0.30*r + 0.59*g + 0.11*b
    i = 0.74*(r-y) - 0.27*(b-y)
    q = 0.48*(r-y) + 0.41*(b-y)
    return (y, i, q)

def yiq_to_rgb(y, i, q):
    r = y + 0.9468822170900693*i + 0.6235565819861433*q
    g = y - 0.27478764629897834*i - 0.6356910791873801*q
    b = y - 1.1085450346420322*i + 1.7090069284064666*q
    if r < 0.0:
        r = 0.0
    if g < 0.0:
        g = 0.0
    if b < 0.0:
        b = 0.0
    if r > 1.0:
        r = 1.0
    if g > 1.0:
        g = 1.0
    if b > 1.0:
        b = 1.0
    return (r, g, b)

def rgb_to_hls(r, g, b):
    maxc = max(r, g, b)
    minc = min(r, g, b)
    sumc = (maxc+minc)
    rangec = (maxc-minc)
    l = sumc/2.0
    if minc == maxc:
        return 0.0, l, 0.0
    if l <= 0.5:
        s = rangec / sumc
    else:
        s = rangec / (2.0-maxc-minc)
    rc = (maxc-r) / rangec
    gc = (maxc-g) / rangec
    bc = (maxc-b) / rangec
    if r == maxc:
        h = bc-gc
    elif g == maxc:
        h = 2.0+rc-bc
    else:
        h = 4.0+gc-rc
    h = (h/6.0) % 1.0
    return h, l, s

def hls_to_rgb(h, l, s):
    if s == 0.0:
        return l, l, l
    if l <= 0.5:
        m2 = l * (1.0+s)
    else:
        m2 = l+s-(l*s)
    m1 = 2.0*l - m2
    return (_v(m1, m2, h+ONE_THIRD), _v(m1, m2, h), _v(m1, m2, h-ONE_THIRD))

def _v(m1, m2, hue):
    hue = hue % 1.0
    if hue < ONE_SIXTH:
        return m1 + (m2-m1)*hue*6.0
    if hue < 0.5:
        return m2
    if hue < TWO_THIRD:
        return m1 + (m2-m1)*(TWO_THIRD-hue)*6.0
    return m1

def rgb_to_hsv(r, g, b):
    maxc = max(r, g, b)
    minc = min(r, g, b)
    rangec = (maxc-minc)
    v = maxc
    if minc == maxc:
        return 0.0, 0.0, v
    s = rangec / maxc
    rc = (maxc-r) / rangec
    gc = (maxc-g) / rangec
    bc = (maxc-b) / rangec
    if r == maxc:
        h = bc-gc
    elif g == maxc:
        h = 2.0+rc-bc
    else:
        h = 4.0+gc-rc
    h = (h/6.0) % 1.0
    return h, s, v

def hsv_to_rgb(h, s, v):
    if s == 0.0:
        return v, v, v
    i = int(h*6.0)
    f = (h*6.0) - i
    p = v*(1.0 - s)
    q = v*(1.0 - s*f)
    t = v*(1.0 - s*(1.0-f))
    i = i%6
    if i == 0:
        return v, t, p
    if i == 1:
        return q, v, p
    if i == 2:
        return p, v, t
    if i == 3:
        return p, q, v
    if i == 4:
        return t, p, v
    if i == 5:
        return v, p, q
    return v, v, v

# ======================================================================
# Tests — all comparisons inline (no boolean-returning float functions)
# ======================================================================

EPS = 0.0001

def test_hsv_roundtrip():
    passed = 0
    failed = 0
    r = 0.0
    while r <= 1.01:
        g = 0.0
        while g <= 1.01:
            b = 0.0
            while b <= 1.01:
                h, s, v = rgb_to_hsv(r, g, b)
                r2, g2, b2 = hsv_to_rgb(h, s, v)
                dr = r - r2
                dg = g - g2
                db = b - b2
                if dr < 0.0:
                    dr = 0.0 - dr
                if dg < 0.0:
                    dg = 0.0 - dg
                if db < 0.0:
                    db = 0.0 - db
                if dr < EPS and dg < EPS and db < EPS:
                    passed = passed + 1
                else:
                    failed = failed + 1
                b = b + 0.2
            g = g + 0.2
        r = r + 0.2
    if failed == 0:
        print("ColorsysTest.test_hsv_roundtrip: PASS")
    else:
        print("ColorsysTest.test_hsv_roundtrip: FAIL -", failed, "failures")

def test_hsv_values():
    ok = 0
    # black → (0, 0, 0)
    h, s, v = rgb_to_hsv(0.0, 0.0, 0.0)
    if abs(h) < EPS and abs(s) < EPS and abs(v) < EPS:
        ok = ok + 1
    # blue → (4/6, 1, 1)
    h, s, v = rgb_to_hsv(0.0, 0.0, 1.0)
    if abs(h - 4.0/6.0) < EPS and abs(s - 1.0) < EPS and abs(v - 1.0) < EPS:
        ok = ok + 1
    # green → (2/6, 1, 1)
    h, s, v = rgb_to_hsv(0.0, 1.0, 0.0)
    if abs(h - 2.0/6.0) < EPS and abs(s - 1.0) < EPS and abs(v - 1.0) < EPS:
        ok = ok + 1
    # red → (0, 1, 1)
    h, s, v = rgb_to_hsv(1.0, 0.0, 0.0)
    if abs(h) < EPS and abs(s - 1.0) < EPS and abs(v - 1.0) < EPS:
        ok = ok + 1
    # white → (0, 0, 1)
    h, s, v = rgb_to_hsv(1.0, 1.0, 1.0)
    if abs(h) < EPS and abs(s) < EPS and abs(v - 1.0) < EPS:
        ok = ok + 1
    # gray → (0, 0, 0.5)
    h, s, v = rgb_to_hsv(0.5, 0.5, 0.5)
    if abs(h) < EPS and abs(s) < EPS and abs(v - 0.5) < EPS:
        ok = ok + 1
    # Reverse: hsv_to_rgb(0, 1, 1) → red (1, 0, 0)
    r, g, b = hsv_to_rgb(0.0, 1.0, 1.0)
    if abs(r - 1.0) < EPS and abs(g) < EPS and abs(b) < EPS:
        ok = ok + 1
    # hsv_to_rgb(2/6, 1, 1) → green (0, 1, 0)
    r, g, b = hsv_to_rgb(2.0/6.0, 1.0, 1.0)
    if abs(r) < EPS and abs(g - 1.0) < EPS and abs(b) < EPS:
        ok = ok + 1
    if ok == 8:
        print("ColorsysTest.test_hsv_values: PASS")
    else:
        print("ColorsysTest.test_hsv_values: FAIL -", ok, "of 8")

def test_hls_roundtrip():
    passed = 0
    failed = 0
    r = 0.0
    while r <= 1.01:
        g = 0.0
        while g <= 1.01:
            b = 0.0
            while b <= 1.01:
                h, l, s = rgb_to_hls(r, g, b)
                r2, g2, b2 = hls_to_rgb(h, l, s)
                dr = r - r2
                dg = g - g2
                db = b - b2
                if dr < 0.0:
                    dr = 0.0 - dr
                if dg < 0.0:
                    dg = 0.0 - dg
                if db < 0.0:
                    db = 0.0 - db
                if dr < EPS and dg < EPS and db < EPS:
                    passed = passed + 1
                else:
                    failed = failed + 1
                b = b + 0.2
            g = g + 0.2
        r = r + 0.2
    if failed == 0:
        print("ColorsysTest.test_hls_roundtrip: PASS")
    else:
        print("ColorsysTest.test_hls_roundtrip: FAIL -", failed, "failures")

def test_hls_values():
    ok = 0
    # black → (0, 0, 0)
    h, l, s = rgb_to_hls(0.0, 0.0, 0.0)
    if abs(h) < EPS and abs(l) < EPS and abs(s) < EPS:
        ok = ok + 1
    # blue → (4/6, 0.5, 1)
    h, l, s = rgb_to_hls(0.0, 0.0, 1.0)
    if abs(h - 4.0/6.0) < EPS and abs(l - 0.5) < EPS and abs(s - 1.0) < EPS:
        ok = ok + 1
    # red → (0, 0.5, 1)
    h, l, s = rgb_to_hls(1.0, 0.0, 0.0)
    if abs(h) < EPS and abs(l - 0.5) < EPS and abs(s - 1.0) < EPS:
        ok = ok + 1
    # white → (0, 1, 0)
    h, l, s = rgb_to_hls(1.0, 1.0, 1.0)
    if abs(h) < EPS and abs(l - 1.0) < EPS and abs(s) < EPS:
        ok = ok + 1
    # Reverse: hls_to_rgb(0, 0.5, 1) → red
    r, g, b = hls_to_rgb(0.0, 0.5, 1.0)
    if abs(r - 1.0) < EPS and abs(g) < EPS and abs(b) < EPS:
        ok = ok + 1
    if ok == 5:
        print("ColorsysTest.test_hls_values: PASS")
    else:
        print("ColorsysTest.test_hls_values: FAIL -", ok, "of 5")

def test_yiq_roundtrip():
    passed = 0
    failed = 0
    r = 0.0
    while r <= 1.01:
        g = 0.0
        while g <= 1.01:
            b = 0.0
            while b <= 1.01:
                y, i, q = rgb_to_yiq(r, g, b)
                r2, g2, b2 = yiq_to_rgb(y, i, q)
                dr = r - r2
                dg = g - g2
                db = b - b2
                if dr < 0.0:
                    dr = 0.0 - dr
                if dg < 0.0:
                    dg = 0.0 - dg
                if db < 0.0:
                    db = 0.0 - db
                if dr < EPS and dg < EPS and db < EPS:
                    passed = passed + 1
                else:
                    failed = failed + 1
                b = b + 0.2
            g = g + 0.2
        r = r + 0.2
    if failed == 0:
        print("ColorsysTest.test_yiq_roundtrip: PASS")
    else:
        print("ColorsysTest.test_yiq_roundtrip: FAIL -", failed, "failures")

def test_yiq_values():
    ok = 0
    # black → (0, 0, 0)
    y, i, q = rgb_to_yiq(0.0, 0.0, 0.0)
    if abs(y) < EPS and abs(i) < EPS and abs(q) < EPS:
        ok = ok + 1
    # white → (1, 0, 0)
    y, i, q = rgb_to_yiq(1.0, 1.0, 1.0)
    if abs(y - 1.0) < EPS and abs(i) < EPS and abs(q) < EPS:
        ok = ok + 1
    # red → (0.3, 0.599, 0.213)
    y, i, q = rgb_to_yiq(1.0, 0.0, 0.0)
    if abs(y - 0.3) < EPS and abs(i - 0.599) < EPS and abs(q - 0.213) < EPS:
        ok = ok + 1
    # Reverse: (0, 0, 0) → black
    r, g, b = yiq_to_rgb(0.0, 0.0, 0.0)
    if abs(r) < EPS and abs(g) < EPS and abs(b) < EPS:
        ok = ok + 1
    # Reverse: (1, 0, 0) → white
    r, g, b = yiq_to_rgb(1.0, 0.0, 0.0)
    if abs(r - 1.0) < EPS and abs(g - 1.0) < EPS and abs(b - 1.0) < EPS:
        ok = ok + 1
    if ok == 5:
        print("ColorsysTest.test_yiq_values: PASS")
    else:
        print("ColorsysTest.test_yiq_values: FAIL -", ok, "of 5")

def test_hls_nearwhite():
    ok = 0
    h, l, s = rgb_to_hls(0.9999999999999999, 1.0, 1.0)
    if abs(h - 0.5) < EPS and abs(l - 1.0) < EPS and abs(s - 1.0) < EPS:
        ok = ok + 1
    r, g, b = hls_to_rgb(0.5, 1.0, 1.0)
    if abs(r - 1.0) < EPS and abs(g - 1.0) < EPS and abs(b - 1.0) < EPS:
        ok = ok + 1
    h, l, s = rgb_to_hls(1.0, 0.9999999999999999, 0.9999999999999999)
    if abs(h) < EPS and abs(l - 1.0) < EPS and abs(s - 1.0) < EPS:
        ok = ok + 1
    r, g, b = hls_to_rgb(0.0, 1.0, 1.0)
    if abs(r - 1.0) < EPS and abs(g - 1.0) < EPS and abs(b - 1.0) < EPS:
        ok = ok + 1
    if ok == 4:
        print("ColorsysTest.test_hls_nearwhite: PASS")
    else:
        print("ColorsysTest.test_hls_nearwhite: FAIL -", ok, "of 4")

# ======================================================================
# Run all tests
# ======================================================================

try:
    test_hsv_roundtrip()
except Exception as _e:
    print("ColorsysTest.test_hsv_roundtrip: FAIL -", _e)
try:
    test_hsv_values()
except Exception as _e:
    print("ColorsysTest.test_hsv_values: FAIL -", _e)
try:
    test_hls_roundtrip()
except Exception as _e:
    print("ColorsysTest.test_hls_roundtrip: FAIL -", _e)
try:
    test_hls_values()
except Exception as _e:
    print("ColorsysTest.test_hls_values: FAIL -", _e)
try:
    test_hls_nearwhite()
except Exception as _e:
    print("ColorsysTest.test_hls_nearwhite: FAIL -", _e)
try:
    test_yiq_roundtrip()
except Exception as _e:
    print("ColorsysTest.test_yiq_roundtrip: FAIL -", _e)
try:
    test_yiq_values()
except Exception as _e:
    print("ColorsysTest.test_yiq_values: FAIL -", _e)
