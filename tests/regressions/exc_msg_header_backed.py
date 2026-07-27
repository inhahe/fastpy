"""An exception message must be a real string, header and all.

BUG-STR-HEADER-PROBES-BEFORE-RUNTIME-STATIC-BUFFERS.

Binding an exception with `as e` turns its message into an ordinary STR
value, and increfing a STR probes for an `FpyString` header 8 bytes
below the char data.  That probe is only defined for strings that carry
the header.  Compiler-emitted literals do — codegen lays them out as
`{magic, refcount, chars}` precisely so the probe lands inside them —
but the runtime's own message producers did not: bare C string literals
and the static `char[256]` scratch buffers (`_cmp_err`, `_cx_err`, ...)
have whatever happens to sit in front of them.

So every runtime-raised exception that a program actually caught by name
read 8 bytes out of bounds.  It is benign on real hardware — an
in-bounds-of-the-image read that almost never matches the magic — but it
is genuine UB, and it aborted every ASan run that raised at all, which
blocked the harness from vetting anything downstream of a `raise`.

`fastpy_raise` now copies the message into one immortal, header-backed
thread-local buffer and publishes *that*, which makes the probe
well-defined for all ~89 raise sites at once.

Nothing below is unusual Python; the point is that each case *binds* the
message and then does something that increfs it.
"""


# ── Bind, print, and use the message of a runtime-raised exception ──────

try:
    x = 1 / 0
except ZeroDivisionError as e:
    print("caught:", e)

try:
    y = 1 // 0
except ZeroDivisionError as e:
    print("caught:", e)

# The modulo producer uses its own static buffer, so it has to be exercised too.
try:
    z = 1 % 0
except ZeroDivisionError as e:
    print("caught modulo:", e)


# ── str() and concatenation both incref the message ────────────────────

try:
    q = 5 / 0
except ZeroDivisionError as e:
    s = str(e)
    print(s)
    print("msg=" + str(e))
    print(len(str(e)))


# ── The message must survive being stored and read back ────────────────

msgs = []
for d in [0, 1, 0, 2]:
    try:
        msgs.append(str(10 / d))
    except ZeroDivisionError as e:
        msgs.append("E:" + str(e))
print(msgs)


# ── Index and key errors come from different producers ─────────────────

try:
    lst = [1, 2, 3]
    print(lst[99])
except IndexError as e:
    print("index:", e)

# KeyError's str() is the *repr* of the key, so it comes out quoted.
try:
    dd = {"a": 1}
    print(dd["missing"])
except KeyError as e:
    print("key:", e)


# ── A caught message must still be readable after a *later* raise ───────
# (only within the same except block — the buffer is valid until the next
# raise, exactly like the shared _err_buf every producer already used).

try:
    a = 1 / 0
except ZeroDivisionError as e:
    first = str(e)
    print("before:", first)
print("after:", first)


# ── Nested raises: the inner one publishes over the outer's message ─────

def risky(n):
    return 100 / n


try:
    try:
        risky(0)
    except ZeroDivisionError as inner:
        print("inner:", inner)
        raise
except ZeroDivisionError as outer:
    print("outer:", outer)


# ── Many raises in a row must not accumulate or corrupt anything ────────

total = 0
for i in range(50):
    try:
        total += int(100 / (i % 5))
    except ZeroDivisionError as e:
        total += len(str(e))
print(total)
