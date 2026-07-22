# Adapted from CPython Lib/test/test_colorsys.py
# Tests colorsys module algorithms (pure Python)

# HSV to RGB conversion
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
    return v, v, v  # shouldn't happen

# RGB to HSV
def rgb_to_hsv(r, g, b):
    maxc = max(r, g, b)
    minc = min(r, g, b)
    v = maxc
    if minc == maxc:
        return 0.0, 0.0, v
    s = (maxc - minc) / maxc
    rc = (maxc - r) / (maxc - minc)
    gc = (maxc - g) / (maxc - minc)
    bc = (maxc - b) / (maxc - minc)
    if r == maxc:
        h = bc - gc
    elif g == maxc:
        h = 2.0 + rc - bc
    else:
        h = 4.0 + gc - rc
    h = (h / 6.0) % 1.0
    return h, s, v

# HLS to RGB
def hls_to_rgb(h, l, s):
    if s == 0.0:
        return l, l, l
    if l <= 0.5:
        m2 = l * (1.0 + s)
    else:
        m2 = l + s - (l * s)
    m1 = 2.0 * l - m2
    return (_v(m1, m2, h + 1.0/3.0),
            _v(m1, m2, h),
            _v(m1, m2, h - 1.0/3.0))

def _v(m1, m2, hue):
    hue = hue % 1.0
    if hue < 1.0/6.0:
        return m1 + (m2 - m1) * hue * 6.0
    if hue < 0.5:
        return m2
    if hue < 2.0/3.0:
        return m1 + (m2 - m1) * (2.0/3.0 - hue) * 6.0
    return m1

# Test HSV round-trip
test_colors = [
    (1.0, 0.0, 0.0),  # red
    (0.0, 1.0, 0.0),  # green
    (0.0, 0.0, 1.0),  # blue
    (1.0, 1.0, 0.0),  # yellow
    (0.5, 0.5, 0.5),  # gray
    (0.0, 0.0, 0.0),  # black
    (1.0, 1.0, 1.0),  # white
]

print("HSV round-trip:")
for r, g, b in test_colors:
    h, s, v = rgb_to_hsv(r, g, b)
    r2, g2, b2 = hsv_to_rgb(h, s, v)
    # Check round-trip accuracy
    ok = (abs(r - r2) < 0.001 and abs(g - g2) < 0.001 and abs(b - b2) < 0.001)
    print(ok)

# Test specific HSV conversions
print("\nHSV conversions:")
print(hsv_to_rgb(0.0, 1.0, 1.0))    # pure red
print(hsv_to_rgb(1.0/3.0, 1.0, 1.0))  # pure green
print(hsv_to_rgb(2.0/3.0, 1.0, 1.0))  # pure blue
print(hsv_to_rgb(0.0, 0.0, 0.5))    # gray

# Test HLS
print("\nHLS conversions:")
print(hls_to_rgb(0.0, 0.5, 1.0))    # red at 50% lightness
r, g, b = hls_to_rgb(0.0, 0.5, 1.0)
print(round(r, 4), round(g, 4), round(b, 4))

r, g, b = hls_to_rgb(1.0/3.0, 0.5, 1.0)
print(round(r, 4), round(g, 4), round(b, 4))

# Test edge cases
print("\nEdge cases:")
print(rgb_to_hsv(0.0, 0.0, 0.0))  # black
print(rgb_to_hsv(1.0, 1.0, 1.0))  # white
print(hsv_to_rgb(0.0, 0.0, 0.0))  # black from HSV
print(hsv_to_rgb(0.0, 0.0, 1.0))  # white from HSV

# Gradient test
print("\nGradient (hue sweep):")
for i in range(6):
    h = i / 6.0
    r, g, b = hsv_to_rgb(h, 1.0, 1.0)
    print(round(r, 2), round(g, 2), round(b, 2))
