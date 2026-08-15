"""A `f(*seq)` slot with no single static type must carry its runtime tag.

BUG-SPLAT-DEFAULTED-SLOT-TYPE and BUG-SPLAT-HETEROGENEOUS-ELEM.

Two different ways a splatted argument can fail to have one static type, both
of which used to be answered with a static guess and a bit-reinterpretation:

* **A defaulted slot the splat can reach.** Whether `b` in `def g(a, b=0)`
  receives the sequence's element or the literal `0` depends on the sequence's
  *runtime* length. Typing it from the default truncated a float element:

      def g(a, b=0):
          return a + b
      print(g(*[1.5, 2.5]))      # 4.0 in CPython; printed 3.5

  Typing it from the element instead is no better — it breaks the mirror case,
  `d_list(v, n=1)` splatted from a one-element list of lists, where the slot
  really does take the integer default and would then be read as a pointer.
  Both directions were tried and measured; each fixes one case and breaks the
  other, so *neither* is right and the slot is now recorded as `"mixed"`.

* **A heterogeneous sequence.** `_get_list_elem_type` answers with a single
  element type even for a sequence that has no single element type, and the
  required slots took that answer literally:

      def two(a, b):
          return b
      print(two(*[1, 2.5]))      # 2.5 in CPython; printed 4612811918334230528

  — the IEEE-754 bits of 2.5 read as an i64. This one needed no type
  bookkeeping at all: the element is read as a tagged `FpyValue` and narrowed
  to the parameter's type through the runtime tag, exactly as the defaulted
  slots already were.

What makes `"mixed"` work now is that it reaches the callee. It is cleared to
`None` in `_call_site_param_types` (the merge cannot refine it further), but
`_function_signatures` keeps it, and the FV-ABI prologue now treats a `"mixed"`
signature entry as ambiguity rather than as one known type. Before that, a lone
`"mixed"` signature looked like `len(_sig_types) == 1` — a *known* type — and
the parameter was tagged `"int"` anyway, which is why the earlier attempt at
this fix printed a float's bit pattern instead of dispatching.
"""


def g(a, b=0):
    return a + b


def h(a, n=1, m=2):
    return a + n + m


def cat(a, b=""):
    return a + b


def flag(a, on=False):
    if on:
        return a * 2
    return a


def d_list(v, n=1):
    return len(v) + n


def two(a, b):
    return b


def three(a, b, c):
    return a * 100 + b * 10 + c


floats = [1.5, 2.5]
one_float = [1.5]
three_floats = [1.0, 2.0, 4.0]
ints = [3]
hetero = [1, 2.5]
strs = ["x", "y"]
w = [9, 9, 9]
lists = [w]


# ── The repro: a float element landing in a slot defaulted to an int ──

print(g(*floats))
print(g(*one_float))
print(h(*floats))
print(h(*three_floats))
print(h(*ints))


# ── The mirror case: the slot really does take the integer default ──
# Typing the slot from the element would read `1` as a pointer here.

print(d_list(*lists))
print(d_list(w))
print(d_list(w, 5))


# ── The same function called directly must be unaffected ──

print(g(3, 4), g(2.5, 3.5), g(4), g(4.5))
print(h(1), h(1, 2), h(1, 2, 3), h(1.5, 2.5, 3.5))


# ── Pointer and bool defaults ──

print(cat(*strs))
print(cat(*["x"]))
print(cat("a", "b"), cat("a"))
print(flag(*[3, True]))
print(flag(*ints))
print(flag(3), flag(3, True))


# ── A heterogeneous sequence filling *required* slots ──

print(two(*hetero))
print(two(*[1, 2.5]))
print(two(*[2.5, 1]))
print(three(*[1, 2, 3]))


# ── ...and filling a defaulted one ──

def opt(a, b=0):
    return b


print(opt(*hetero))
print(opt(*[1]))
print(opt(*[1, 2, 3][0:2]))


# ── Inside a function, and repeated so the value cannot be constant-folded ──

def inner():
    print(g(*floats), h(*three_floats), two(*hetero))
    t = 0.0
    i = 0
    while i < 20:
        t = t + g(*floats) + h(*floats)
        i = i + 1
    print(t)


inner()


# ── The FV-result path: the call result bound to a name ──

def via_fv():
    a = g(*floats)
    b = h(*three_floats)
    c = two(*hetero)
    print(a, b, c)
    print(a + b + c)


via_fv()


# ── Every optional slot supplied, none supplied, and a partial fill ──

def all_optional(a, n=3, m=4, k=5):
    return a + n + m + k


print(all_optional(*one_float))
print(all_optional(*floats))
print(all_optional(*three_floats))
print(all_optional(*[1.0, 2.0, 4.0, 8.0]))


# ── A splat whose element kind disagrees with a *string* default ──

def suffix(s, suf="!"):
    return str(s) + suf


print(suffix(*["ab", "?"]))
print(suffix(*["ab"]))
print(suffix(*[7]))
