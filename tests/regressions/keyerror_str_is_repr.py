# BUG-KEYERROR-STR-NOT-REPR
#
# KeyError is the one built-in exception whose __str__ is not the message but
# `repr(args[0])`: CPython prints `KeyError: 'a'` for a string key and
# `KeyError: 5` for an int one. fastpy stores only the rendered message, never
# an args tuple, so the repr has to be applied at each raise site — and the
# raise sites had drifted into three different answers (the raw key text, a
# bare "KeyError", and a snprintf'd integer). They now all go through
# fpy_raise_key_error in the runtime, and `raise KeyError(x)` in user code
# goes through the matching path in codegen.
#
# The message-shaped ones count too: set().pop() raises
# KeyError('pop from an empty set'), and CPython quotes that string like any
# other argument.

d = {"a": 1, "bb": 2}

# --- subscript miss, string key ---
try:
    d["missing"]
except KeyError as e:
    print("1", str(e))

# --- subscript miss, int key: repr(int) has no quotes ---
di = {1: "x"}
try:
    di[7]
except KeyError as e:
    print("2", str(e))

# --- pop with no default ---
try:
    d.pop("nope")
except KeyError as e:
    print("3", str(e))

try:
    di.pop(99)
except KeyError as e:
    print("4", str(e))

# --- del ---
try:
    del d["gone"]
except KeyError as e:
    print("5", str(e))

try:
    del di[123]
except KeyError as e:
    print("6", str(e))

# --- the message-shaped ones, which CPython also quotes ---
try:
    set().pop()
except KeyError as e:
    print("7", str(e))

try:
    {}.popitem()
except KeyError as e:
    print("8", str(e))

# --- raised from user code ---
try:
    raise KeyError("literal")
except KeyError as e:
    print("9", str(e))

k = "from-a-variable"
try:
    raise KeyError(k)
except KeyError as e:
    print("10", str(e))

try:
    raise KeyError(42)
except KeyError as e:
    print("11", str(e))

try:
    raise KeyError("fmt-%d" % 7)
except KeyError as e:
    print("12", str(e))

try:
    raise KeyError(f"f-string {k}")
except KeyError as e:
    print("13", str(e))

# --- a key that forces the other quote character ---
try:
    d["it's"]
except KeyError as e:
    print("14", str(e))

# --- every other exception keeps its plain message ---
try:
    raise ValueError("not quoted")
except ValueError as e:
    print("15", str(e))

# --- the repr survives being stored and re-read ---
# The concatenation is not incidental: str(e) hands back a borrowed pointer
# into the one message buffer the thread reuses, so storing it bare would make
# all three entries alias the last raise. That is a separate bug
# (BUG-EXC-MSG-BUFFER-ALIASES-ACROSS-RAISES); copying here keeps this test
# about the repr.
seen = []
for key in ["p", "q", "r"]:
    try:
        d[key]
    except KeyError as e:
        seen.append("k=" + str(e))
print("16", seen)
