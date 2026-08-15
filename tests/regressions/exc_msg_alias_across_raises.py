# BUG-EXC-MSG-BUFFER-ALIASES-ACROSS-RAISES
#
# The exception message used to live in one reused, immortal, thread-local
# buffer.  `str(e)` handed back a pointer into it, and because the buffer was
# immortal an incref was a no-op — so a stored message was really a pointer to
# storage the *next* raise overwrote.  Every message collected in a container
# read as the most recent one.
#
# Concatenating (`"" + str(e)`) copied and hid the bug, which is why the older
# tests never caught it; nothing here concatenates before storing.
#
# The fix makes each raise publish a fresh refcounted string and release the
# previous one, so the runtime half only works together with the compiler
# increfing wherever it keeps a message past the next raise: the `as e` binding
# and the saved-message slot behind a bare `raise`.

# --- the plain case: three messages, three distinct answers ---
seen = []
for d in [0, 1, 2]:
    try:
        raise ValueError("v%d" % d)
    except ValueError as e:
        seen.append(str(e))
print(seen)

# --- the message must survive being kept while later raises happen ---
first = ""
try:
    raise KeyError("k1")
except KeyError as e:
    first = str(e)
for i in [1, 2, 3]:
    try:
        raise ValueError("later %d" % i)
    except ValueError:
        pass
print("first still:", first)

# --- a message longer than the inline buffer takes the malloc path ---
longs = []
for n in [300, 400]:
    try:
        raise RuntimeError("x" * n)
    except RuntimeError as e:
        longs.append(len(str(e)))
print(longs)

# --- messages as dict values ---
by_key = {}
for k in ["a", "b", "c"]:
    try:
        raise ValueError("msg-" + k)
    except ValueError as e:
        by_key[k] = str(e)
print(by_key["a"], by_key["b"], by_key["c"])

# --- a bare `raise` after an intervening raise re-raises the right one ---
def reraise():
    try:
        raise ValueError("outer message")
    except ValueError:
        try:
            raise KeyError("inner")
        except KeyError:
            pass
        raise

try:
    reraise()
except ValueError as e:
    print("reraised:", e)

# --- the same, but the handler also keeps its own binding ---
def reraise_bound():
    try:
        raise ValueError("bound outer")
    except ValueError as e:
        held = str(e)
        try:
            raise RuntimeError("noise")
        except RuntimeError:
            pass
        print("held:", held)
        raise

try:
    reraise_bound()
except ValueError as e:
    print("reraised2:", e)

# --- messages captured in a loop that also nests a try ---
pairs = []
for i in [0, 1]:
    try:
        raise IndexError("idx%d" % i)
    except IndexError as e:
        try:
            raise ValueError("noise%d" % i)
        except ValueError as e2:
            pairs.append(str(e) + "/" + str(e2))
print(pairs)

# --- a user-defined exception keeps its message after the handler clears ---
class AppError(Exception):
    pass

msgs = []
for i in [0, 1]:
    try:
        raise AppError("app%d" % i)
    except AppError as e:
        msgs.append(str(e))
print(msgs)

# --- runtime-raised messages (no literal anywhere) behave the same ---
zde = []
for d in [0, 0]:
    try:
        print(1 // d)
    except ZeroDivisionError as e:
        zde.append(str(e))
print(zde)
