"""`f(*seq)` must not read past the end of the sequence.

BUG-STARARG-SPLAT-DEFAULT-PARAM.

The splat expansion extracted exactly `info.param_count` elements from the
splatted sequence:

    remaining = info.param_count - len(args)
    for i in range(remaining):
        args.append(self._list_get_as_bare(list_val, i, elem_type))

A sequence supplies as many arguments as it *has*, not as many as the callee
happens to declare, so any callee with a default blew up:

    def d(a, n=1):
        return a + n

    print(d(*[5]))      # IndexError: list index out of range

Required parameters are still extracted unconditionally — a too-short sequence
is a TypeError in Python and the existing `min_args` check reports it. Only the
defaulted slots are ambiguous, and the sequence's length is a runtime property,
so each of those is now resolved at runtime: `seq[i] if i < len(seq) else
<default>`, built as an FpyValue because the two arms need a common LLVM type
and an element need not agree with the default.

Two things this bug exposed are worth stating, because both are covered below:

* **The expansion existed twice.** `_emit_user_call` and `_emit_user_call_fv`
  each carried their own copy, so the first fix left `_emit_user_call_fv` still
  crashing whenever the call result flowed somewhere that wanted the raw
  FpyValue. They share `_splat_positional_args` now. `via_fv()` drives the
  second path by binding the result to a name.

* **A parameter fed only by a splat had no type at all.** `_call_site_param_types`
  classified each positional argument, and a `Starred` classified as nothing, so
  `no_default(*lists)` left `v` untyped and `len(v)` answered 0 instead of 3 —
  the same silent-zero as BUG-PARAM-TYPE-FROM-USER-CALL-ARG, reached from the
  argument side. `_csa_splat_elem_tag` now traces the splatted name back to the
  literal it was bound to and hands that element tag to every *required* slot
  from the splat's position on. `only_splat_called()` covers it.

The element tag is deliberately given to required slots only. A slot with a
default may take either the element or the default depending on the sequence's
runtime length, and neither is safe to assume statically — that residue is
BUG-SPLAT-DEFAULTED-SLOT-TYPE, which is why no case below splats a sequence
whose element kind disagrees with the default it might land on.
"""


def d_int(a, n=1):
    return a + n


def d_two(a, n=1, m=2):
    return a + n + m


def two_pos(a, b):
    return a + b


def d_list(v, n=1):
    return len(v) + n


def no_default(v):
    return len(v)


def d_str(s, suffix="!"):
    return s + suffix


ints = [5]
both = [5, 7]
three = [5, 7, 9]
w = [9, 9, 9]
lists = [w]
strs = ["ab"]


# ── The repro: a splat shorter than the callee's parameter list ──

print(d_int(*ints), d_int(*both))
print(d_two(*ints), d_two(*both), d_two(*three))
print(d_str(*strs))


# ── Required slots are still filled from the sequence ──

print(two_pos(*both))


# ── A parameter whose only evidence is a splat must still be typed ──
# Without the element tag `len(v)` answered 0 rather than faulting.

def only_splat_called():
    print(d_list(*lists), no_default(*lists))


only_splat_called()


# ── The direct-call and splat forms must agree ──

print(d_list(w), no_default(w))
print(d_list(*lists), no_default(*lists))


# ── The second expansion site: a result that wants the raw FpyValue ──

def via_fv():
    a = d_int(*ints)
    b = d_two(*both)
    c = no_default(*lists)
    print(a, b, c)
    print(a + b + c)


via_fv()


# ── The same shapes inside a function, and across a loop ──

def in_func():
    print(d_int(*ints), d_int(*both), d_two(*ints))
    print(two_pos(*both), no_default(*lists))
    t = 0
    i = 0
    while i < 15:
        t = t + d_int(*ints) + d_two(*both)
        i = i + 1
    print(t)


in_func()


# ── A splat that exactly fills every slot, and one that overfills nothing ──

def exact(a, b, c):
    return a * 100 + b * 10 + c


print(exact(*three))


# ── An empty-ish tail: every optional slot comes from the default ──

def all_optional(a, n=3, m=4, k=5):
    return a + n + m + k


print(all_optional(*ints))
print(all_optional(*both))
print(all_optional(*three))
