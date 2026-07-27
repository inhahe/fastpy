"""Slicing a bytes has to use a byte-indexed, FpyBytes-backed helper.

`bytes` and `str` are both `i8*` to the compiler, and for a long time that
similarity was taken one step too far: every slice — of either kind — was
lowered to `fastpy_str_slice` / `fastpy_str_slice_step`, and the result of a
bytes slice was simply re-tagged BYTES afterwards.

Two things are wrong with that.  The str helpers walk the buffer by *code
point*, so `b"\xc3\xa9"[0:1]` gave a two-byte result where CPython gives one;
and they allocate an `FpyString`, whose header is smaller than an `FpyBytes`
header.  Tagging that allocation BYTES means every later `fpy_bytes_len` reads
the magic field 16 bytes before the buffer — off the front of the allocation.
ASan caught it as a heap-buffer-overflow read on `b = b"abcd"; print(b[1:3])`;
without a sanitizer it silently read whatever the allocator happened to leave
there, so the length was garbage or, more often, accidentally plausible.

The fix is a real pair of byte-indexed helpers backed by `fpy_bytes_alloc`,
selected at all three lowering sites: the static slice path when the receiver
is known to be bytes, the pointer fallback, and `fastpy_fv_slice`'s runtime
dispatch for a receiver whose kind is only known then.  BUG-BYTES-SLICE-VIA-STR.

So the interesting part of this test is not just the printed slice — it is that
`len()` of the slice is right, that the slice survives being concatenated and
sliced again, and that a non-ASCII payload is indexed by byte rather than by
character.
"""

# ── Static path: the receiver's kind is known from the literal ──
b = b"abcd"
print(b[1:3], b[:2], b[2:], b[:], b[::-1], b[::2], b[1::2], b[-2:], b[:-1])
print(len(b[1:3]), len(b[:2]), len(b[::-1]), len(b[::2]))

# Empty and out-of-range slices clamp rather than fault.
print(b[9:], b[:0], b[3:1], len(b[9:]), len(b[3:1]))

# A slice is a real bytes, so it composes with everything else.
print(b[1:3] + b"XY", b[1:3] * 2, b[1:3][0], b[1:3][::-1])
print(b[1:3] == b"bc", b[1:3] == b"cb", b"b" in b[1:3])

# ── Byte indexing, not code-point indexing ──
u = "é€".encode()
print(len(u), u[0:1], u[:2], len(u[0:1]))
print(list(u))

# Embedded NULs must not end the slice early.
z = b"a\x00b\x00c"
print(len(z), len(z[1:]), z[1:], list(z[1:4]))

# ── Pointer fallback: receiver is a call, not a name ──
def mk():
    return b"wxyz"

print(mk()[1:3], mk()[::-1], len(mk()[1:3]))

# ── Runtime dispatch: the parameter has no declared kind at all ──
def sl(v):
    return v[1:3]

def sl_step(v):
    return v[::-1]

print(sl(b"abcd"), len(sl(b"abcd")))
print(sl("abcd"), len(sl("abcd")))
print(sl([1, 2, 3, 4]), len(sl([1, 2, 3, 4])))
print(sl_step(b"abcd"), sl_step("abcd"), sl_step([1, 2, 3]))
print(sl(mk()), len(sl(mk())))

# ── The slice is durable: it outlives the expression that made it ──
parts = []
for i in range(4):
    parts.append(b[i:i + 2])
print(parts, [len(p) for p in parts])

acc = b""
for p in parts:
    acc = acc + p
print(acc, len(acc))

# ── str slicing is untouched by all of this ──
s = "abcd"
print(s[1:3], s[:2], s[::-1], s[::2], len(s[1:3]))
print("héllo"[1:3], len("héllo"[1:3]))
