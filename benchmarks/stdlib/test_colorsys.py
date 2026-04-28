"""
Stdlib colorsys module — compiled natively by fastpy.

Tests ported from CPython Lib/test/test_colorsys.py.
Module source inlined from CPython Lib/colorsys.py (pure float math, zero imports).
"""

# ── colorsys module source (inlined) ─────────────────────────────────────

ONE_THIRD = 1.0 / 3.0
ONE_SIXTH = 1.0 / 6.0
TWO_THIRD = 2.0 / 3.0


def rgb_to_yiq(r, g, b):
    y = 0.30 * r + 0.59 * g + 0.11 * b
    i = 0.74 * (r - y) - 0.27 * (b - y)
    q = 0.48 * (r - y) + 0.41 * (b - y)
    return (y, i, q)


def yiq_to_rgb(y, i, q):
    r = y + 0.9468822170900693 * i + 0.6235565819861433 * q
    g = y - 0.27478764629897834 * i - 0.6356910791873801 * q
    b = y - 1.1085450346420322 * i + 1.7090069284064666 * q
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


def _v(m1, m2, hue):
    hue = hue % 1.0
    if hue < ONE_SIXTH:
        return m1 + (m2 - m1) * hue * 6.0
    if hue < 0.5:
        return m2
    if hue < TWO_THIRD:
        return m1 + (m2 - m1) * (TWO_THIRD - hue) * 6.0
    return m1


def rgb_to_hls(r, g, b):
    maxc = max(r, g, b)
    minc = min(r, g, b)
    sumc = maxc + minc
    rangec = maxc - minc
    l = sumc / 2.0
    if minc == maxc:
        return 0.0, l, 0.0
    if l <= 0.5:
        s = rangec / sumc
    else:
        s = rangec / (2.0 - maxc - minc)
    rc = (maxc - r) / rangec
    gc = (maxc - g) / rangec
    bc = (maxc - b) / rangec
    if r == maxc:
        h = bc - gc
    elif g == maxc:
        h = 2.0 + rc - bc
    else:
        h = 4.0 + gc - rc
    h = (h / 6.0) % 1.0
    return h, l, s


def hls_to_rgb(h, l, s):
    if s == 0.0:
        return l, l, l
    if l <= 0.5:
        m2 = l * (1.0 + s)
    else:
        m2 = l + s - (l * s)
    m1 = 2.0 * l - m2
    return (_v(m1, m2, h + ONE_THIRD), _v(m1, m2, h), _v(m1, m2, h - ONE_THIRD))


def rgb_to_hsv(r, g, b):
    maxc = max(r, g, b)
    minc = min(r, g, b)
    rangec = maxc - minc
    v = maxc
    if minc == maxc:
        return 0.0, 0.0, v
    s = rangec / maxc
    rc = (maxc - r) / rangec
    gc = (maxc - g) / rangec
    bc = (maxc - b) / rangec
    if r == maxc:
        h = bc - gc
    elif g == maxc:
        h = 2.0 + rc - bc
    else:
        h = 4.0 + gc - rc
    h = (h / 6.0) % 1.0
    return h, s, v


def hsv_to_rgb(h, s, v):
    if s == 0.0:
        return v, v, v
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
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
    return 0.0, 0.0, 0.0


# ── test helpers ─────────────────────────────────────────────────────────

def almost_equal(a, b):
    """Like unittest assertAlmostEqual: 7 decimal places."""
    diff = a - b
    if diff < 0.0:
        diff = 0.0 - diff
    return diff < 1e-7


def assert_triple(r0, r1, r2, e0, e1, e2, msg):
    if not almost_equal(r0, e0) or not almost_equal(r1, e1) or not almost_equal(r2, e2):
        print("FAIL: " + msg)
        print("  expected: (" + str(e0) + ", " + str(e1) + ", " + str(e2) + ")")
        print("  actual:   (" + str(r0) + ", " + str(r1) + ", " + str(r2) + ")")
        return False
    return True


# ── tests ────────────────────────────────────────────────────────────────

def test_hsv_roundtrip():
    """HSV roundtrip: rgb -> hsv -> rgb should recover original."""
    passed = 0
    total = 0
    values = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    for r in values:
        for g in values:
            for b in values:
                total += 1
                h, s, v = rgb_to_hsv(r, g, b)
                r2, g2, b2 = hsv_to_rgb(h, s, v)
                if assert_triple(r2, g2, b2, r, g, b,
                                 "hsv roundtrip (" + str(r) + "," + str(g) + "," + str(b) + ")"):
                    passed += 1
    print("  hsv_roundtrip: " + str(passed) + "/" + str(total))
    return passed, total


def test_hsv_values():
    """Known HSV conversion values."""
    passed = 0
    total = 0

    # (r,g,b) -> (h,s,v) known pairs
    # black
    total += 1
    h, s, v = rgb_to_hsv(0.0, 0.0, 0.0)
    if assert_triple(h, s, v, 0.0, 0.0, 0.0, "hsv black"):
        passed += 1
    # blue
    total += 1
    h, s, v = rgb_to_hsv(0.0, 0.0, 1.0)
    if assert_triple(h, s, v, 4.0/6.0, 1.0, 1.0, "hsv blue"):
        passed += 1
    # green
    total += 1
    h, s, v = rgb_to_hsv(0.0, 1.0, 0.0)
    if assert_triple(h, s, v, 2.0/6.0, 1.0, 1.0, "hsv green"):
        passed += 1
    # cyan
    total += 1
    h, s, v = rgb_to_hsv(0.0, 1.0, 1.0)
    if assert_triple(h, s, v, 3.0/6.0, 1.0, 1.0, "hsv cyan"):
        passed += 1
    # red
    total += 1
    h, s, v = rgb_to_hsv(1.0, 0.0, 0.0)
    if assert_triple(h, s, v, 0.0, 1.0, 1.0, "hsv red"):
        passed += 1
    # purple
    total += 1
    h, s, v = rgb_to_hsv(1.0, 0.0, 1.0)
    if assert_triple(h, s, v, 5.0/6.0, 1.0, 1.0, "hsv purple"):
        passed += 1
    # yellow
    total += 1
    h, s, v = rgb_to_hsv(1.0, 1.0, 0.0)
    if assert_triple(h, s, v, 1.0/6.0, 1.0, 1.0, "hsv yellow"):
        passed += 1
    # white
    total += 1
    h, s, v = rgb_to_hsv(1.0, 1.0, 1.0)
    if assert_triple(h, s, v, 0.0, 0.0, 1.0, "hsv white"):
        passed += 1
    # grey
    total += 1
    h, s, v = rgb_to_hsv(0.5, 0.5, 0.5)
    if assert_triple(h, s, v, 0.0, 0.0, 0.5, "hsv grey"):
        passed += 1

    # Reverse: hsv -> rgb
    # black
    total += 1
    r, g, b = hsv_to_rgb(0.0, 0.0, 0.0)
    if assert_triple(r, g, b, 0.0, 0.0, 0.0, "hsv->rgb black"):
        passed += 1
    # blue
    total += 1
    r, g, b = hsv_to_rgb(4.0/6.0, 1.0, 1.0)
    if assert_triple(r, g, b, 0.0, 0.0, 1.0, "hsv->rgb blue"):
        passed += 1
    # green
    total += 1
    r, g, b = hsv_to_rgb(2.0/6.0, 1.0, 1.0)
    if assert_triple(r, g, b, 0.0, 1.0, 0.0, "hsv->rgb green"):
        passed += 1
    # cyan
    total += 1
    r, g, b = hsv_to_rgb(3.0/6.0, 1.0, 1.0)
    if assert_triple(r, g, b, 0.0, 1.0, 1.0, "hsv->rgb cyan"):
        passed += 1
    # red
    total += 1
    r, g, b = hsv_to_rgb(0.0, 1.0, 1.0)
    if assert_triple(r, g, b, 1.0, 0.0, 0.0, "hsv->rgb red"):
        passed += 1
    # purple
    total += 1
    r, g, b = hsv_to_rgb(5.0/6.0, 1.0, 1.0)
    if assert_triple(r, g, b, 1.0, 0.0, 1.0, "hsv->rgb purple"):
        passed += 1
    # yellow
    total += 1
    r, g, b = hsv_to_rgb(1.0/6.0, 1.0, 1.0)
    if assert_triple(r, g, b, 1.0, 1.0, 0.0, "hsv->rgb yellow"):
        passed += 1
    # white
    total += 1
    r, g, b = hsv_to_rgb(0.0, 0.0, 1.0)
    if assert_triple(r, g, b, 1.0, 1.0, 1.0, "hsv->rgb white"):
        passed += 1
    # grey
    total += 1
    r, g, b = hsv_to_rgb(0.0, 0.0, 0.5)
    if assert_triple(r, g, b, 0.5, 0.5, 0.5, "hsv->rgb grey"):
        passed += 1

    print("  hsv_values: " + str(passed) + "/" + str(total))
    return passed, total


def test_hls_roundtrip():
    """HLS roundtrip: rgb -> hls -> rgb should recover original."""
    passed = 0
    total = 0
    values = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    for r in values:
        for g in values:
            for b in values:
                total += 1
                h, l, s = rgb_to_hls(r, g, b)
                r2, g2, b2 = hls_to_rgb(h, l, s)
                if assert_triple(r2, g2, b2, r, g, b,
                                 "hls roundtrip (" + str(r) + "," + str(g) + "," + str(b) + ")"):
                    passed += 1
    print("  hls_roundtrip: " + str(passed) + "/" + str(total))
    return passed, total


def test_hls_values():
    """Known HLS conversion values."""
    passed = 0
    total = 0

    # (r,g,b) -> (h,l,s) known pairs
    # black
    total += 1
    h, l, s = rgb_to_hls(0.0, 0.0, 0.0)
    if assert_triple(h, l, s, 0.0, 0.0, 0.0, "hls black"):
        passed += 1
    # blue
    total += 1
    h, l, s = rgb_to_hls(0.0, 0.0, 1.0)
    if assert_triple(h, l, s, 4.0/6.0, 0.5, 1.0, "hls blue"):
        passed += 1
    # green
    total += 1
    h, l, s = rgb_to_hls(0.0, 1.0, 0.0)
    if assert_triple(h, l, s, 2.0/6.0, 0.5, 1.0, "hls green"):
        passed += 1
    # cyan
    total += 1
    h, l, s = rgb_to_hls(0.0, 1.0, 1.0)
    if assert_triple(h, l, s, 3.0/6.0, 0.5, 1.0, "hls cyan"):
        passed += 1
    # red
    total += 1
    h, l, s = rgb_to_hls(1.0, 0.0, 0.0)
    if assert_triple(h, l, s, 0.0, 0.5, 1.0, "hls red"):
        passed += 1
    # purple
    total += 1
    h, l, s = rgb_to_hls(1.0, 0.0, 1.0)
    if assert_triple(h, l, s, 5.0/6.0, 0.5, 1.0, "hls purple"):
        passed += 1
    # yellow
    total += 1
    h, l, s = rgb_to_hls(1.0, 1.0, 0.0)
    if assert_triple(h, l, s, 1.0/6.0, 0.5, 1.0, "hls yellow"):
        passed += 1
    # white
    total += 1
    h, l, s = rgb_to_hls(1.0, 1.0, 1.0)
    if assert_triple(h, l, s, 0.0, 1.0, 0.0, "hls white"):
        passed += 1
    # grey
    total += 1
    h, l, s = rgb_to_hls(0.5, 0.5, 0.5)
    if assert_triple(h, l, s, 0.0, 0.5, 0.0, "hls grey"):
        passed += 1

    # Reverse: hls -> rgb
    # black
    total += 1
    r, g, b = hls_to_rgb(0.0, 0.0, 0.0)
    if assert_triple(r, g, b, 0.0, 0.0, 0.0, "hls->rgb black"):
        passed += 1
    # blue
    total += 1
    r, g, b = hls_to_rgb(4.0/6.0, 0.5, 1.0)
    if assert_triple(r, g, b, 0.0, 0.0, 1.0, "hls->rgb blue"):
        passed += 1
    # green
    total += 1
    r, g, b = hls_to_rgb(2.0/6.0, 0.5, 1.0)
    if assert_triple(r, g, b, 0.0, 1.0, 0.0, "hls->rgb green"):
        passed += 1
    # cyan
    total += 1
    r, g, b = hls_to_rgb(3.0/6.0, 0.5, 1.0)
    if assert_triple(r, g, b, 0.0, 1.0, 1.0, "hls->rgb cyan"):
        passed += 1
    # red
    total += 1
    r, g, b = hls_to_rgb(0.0, 0.5, 1.0)
    if assert_triple(r, g, b, 1.0, 0.0, 0.0, "hls->rgb red"):
        passed += 1
    # purple
    total += 1
    r, g, b = hls_to_rgb(5.0/6.0, 0.5, 1.0)
    if assert_triple(r, g, b, 1.0, 0.0, 1.0, "hls->rgb purple"):
        passed += 1
    # yellow
    total += 1
    r, g, b = hls_to_rgb(1.0/6.0, 0.5, 1.0)
    if assert_triple(r, g, b, 1.0, 1.0, 0.0, "hls->rgb yellow"):
        passed += 1
    # white
    total += 1
    r, g, b = hls_to_rgb(0.0, 1.0, 0.0)
    if assert_triple(r, g, b, 1.0, 1.0, 1.0, "hls->rgb white"):
        passed += 1
    # grey
    total += 1
    r, g, b = hls_to_rgb(0.0, 0.5, 0.0)
    if assert_triple(r, g, b, 0.5, 0.5, 0.5, "hls->rgb grey"):
        passed += 1

    print("  hls_values: " + str(passed) + "/" + str(total))
    return passed, total


def test_hls_nearwhite():
    """gh-106498: near-white HLS edge case."""
    passed = 0
    total = 0

    # (0.9999999999999999, 1, 1) -> hls (0.5, 1.0, 1.0)
    total += 1
    h, l, s = rgb_to_hls(0.9999999999999999, 1.0, 1.0)
    if assert_triple(h, l, s, 0.5, 1.0, 1.0, "nearwhite hls 1"):
        passed += 1
    total += 1
    r, g, b = hls_to_rgb(0.5, 1.0, 1.0)
    if assert_triple(r, g, b, 1.0, 1.0, 1.0, "nearwhite hls->rgb 1"):
        passed += 1

    # (1, 0.9999999999999999, 0.9999999999999999) -> hls (0.0, 1.0, 1.0)
    total += 1
    h, l, s = rgb_to_hls(1.0, 0.9999999999999999, 0.9999999999999999)
    if assert_triple(h, l, s, 0.0, 1.0, 1.0, "nearwhite hls 2"):
        passed += 1
    total += 1
    r, g, b = hls_to_rgb(0.0, 1.0, 1.0)
    if assert_triple(r, g, b, 1.0, 1.0, 1.0, "nearwhite hls->rgb 2"):
        passed += 1

    print("  hls_nearwhite: " + str(passed) + "/" + str(total))
    return passed, total


def test_yiq_roundtrip():
    """YIQ roundtrip: rgb -> yiq -> rgb should recover original."""
    passed = 0
    total = 0
    values = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    for r in values:
        for g in values:
            for b in values:
                total += 1
                y, i, q = rgb_to_yiq(r, g, b)
                r2, g2, b2 = yiq_to_rgb(y, i, q)
                if assert_triple(r2, g2, b2, r, g, b,
                                 "yiq roundtrip (" + str(r) + "," + str(g) + "," + str(b) + ")"):
                    passed += 1
    print("  yiq_roundtrip: " + str(passed) + "/" + str(total))
    return passed, total


def test_yiq_values():
    """Known YIQ conversion values."""
    passed = 0
    total = 0

    # black
    total += 1
    y, i, q = rgb_to_yiq(0.0, 0.0, 0.0)
    if assert_triple(y, i, q, 0.0, 0.0, 0.0, "yiq black"):
        passed += 1
    # blue
    total += 1
    y, i, q = rgb_to_yiq(0.0, 0.0, 1.0)
    if assert_triple(y, i, q, 0.11, -0.3217, 0.3121, "yiq blue"):
        passed += 1
    # green
    total += 1
    y, i, q = rgb_to_yiq(0.0, 1.0, 0.0)
    if assert_triple(y, i, q, 0.59, -0.2773, -0.5251, "yiq green"):
        passed += 1
    # cyan
    total += 1
    y, i, q = rgb_to_yiq(0.0, 1.0, 1.0)
    if assert_triple(y, i, q, 0.7, -0.599, -0.213, "yiq cyan"):
        passed += 1
    # red
    total += 1
    y, i, q = rgb_to_yiq(1.0, 0.0, 0.0)
    if assert_triple(y, i, q, 0.3, 0.599, 0.213, "yiq red"):
        passed += 1
    # purple
    total += 1
    y, i, q = rgb_to_yiq(1.0, 0.0, 1.0)
    if assert_triple(y, i, q, 0.41, 0.2773, 0.5251, "yiq purple"):
        passed += 1
    # yellow
    total += 1
    y, i, q = rgb_to_yiq(1.0, 1.0, 0.0)
    if assert_triple(y, i, q, 0.89, 0.3217, -0.3121, "yiq yellow"):
        passed += 1
    # white
    total += 1
    y, i, q = rgb_to_yiq(1.0, 1.0, 1.0)
    if assert_triple(y, i, q, 1.0, 0.0, 0.0, "yiq white"):
        passed += 1
    # grey
    total += 1
    y, i, q = rgb_to_yiq(0.5, 0.5, 0.5)
    if assert_triple(y, i, q, 0.5, 0.0, 0.0, "yiq grey"):
        passed += 1

    # Reverse: yiq -> rgb
    total += 1
    r, g, b = yiq_to_rgb(0.0, 0.0, 0.0)
    if assert_triple(r, g, b, 0.0, 0.0, 0.0, "yiq->rgb black"):
        passed += 1
    total += 1
    r, g, b = yiq_to_rgb(0.11, -0.3217, 0.3121)
    if assert_triple(r, g, b, 0.0, 0.0, 1.0, "yiq->rgb blue"):
        passed += 1
    total += 1
    r, g, b = yiq_to_rgb(0.59, -0.2773, -0.5251)
    if assert_triple(r, g, b, 0.0, 1.0, 0.0, "yiq->rgb green"):
        passed += 1
    total += 1
    r, g, b = yiq_to_rgb(0.7, -0.599, -0.213)
    if assert_triple(r, g, b, 0.0, 1.0, 1.0, "yiq->rgb cyan"):
        passed += 1
    total += 1
    r, g, b = yiq_to_rgb(0.3, 0.599, 0.213)
    if assert_triple(r, g, b, 1.0, 0.0, 0.0, "yiq->rgb red"):
        passed += 1
    total += 1
    r, g, b = yiq_to_rgb(0.41, 0.2773, 0.5251)
    if assert_triple(r, g, b, 1.0, 0.0, 1.0, "yiq->rgb purple"):
        passed += 1
    total += 1
    r, g, b = yiq_to_rgb(0.89, 0.3217, -0.3121)
    if assert_triple(r, g, b, 1.0, 1.0, 0.0, "yiq->rgb yellow"):
        passed += 1
    total += 1
    r, g, b = yiq_to_rgb(1.0, 0.0, 0.0)
    if assert_triple(r, g, b, 1.0, 1.0, 1.0, "yiq->rgb white"):
        passed += 1
    total += 1
    r, g, b = yiq_to_rgb(0.5, 0.0, 0.0)
    if assert_triple(r, g, b, 0.5, 0.5, 0.5, "yiq->rgb grey"):
        passed += 1

    print("  yiq_values: " + str(passed) + "/" + str(total))
    return passed, total


# ── runner ───────────────────────────────────────────────────────────────

def run_all_tests():
    total_passed = 0
    total_tests = 0

    print("colorsys stdlib tests (compiled natively):")

    results = []
    results.append(test_hsv_roundtrip())
    results.append(test_hsv_values())
    results.append(test_hls_roundtrip())
    results.append(test_hls_values())
    results.append(test_hls_nearwhite())
    results.append(test_yiq_roundtrip())
    results.append(test_yiq_values())

    for p, t in results:
        total_passed += p
        total_tests += t

    print("")
    if total_passed == total_tests:
        print("ALL TESTS PASSED: " + str(total_passed) + "/" + str(total_tests))
    else:
        print("SOME TESTS FAILED: " + str(total_passed) + "/" + str(total_tests))


run_all_tests()
