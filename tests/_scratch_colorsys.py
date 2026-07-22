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
    return v, v, v

# Tests
h, s, v = rgb_to_hsv(0.2, 0.4, 0.6)
print(round(h, 4), round(s, 4), round(v, 4))
r, g, b = hsv_to_rgb(h, s, v)
print(round(r, 4), round(g, 4), round(b, 4))
print(rgb_to_hsv(1.0, 0.0, 0.0))
print(rgb_to_hsv(0.0, 1.0, 0.0))
print(rgb_to_hsv(0.0, 0.0, 1.0))
print(hsv_to_rgb(0.0, 0.0, 0.5))
