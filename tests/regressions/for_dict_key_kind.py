"""Iterating a dict or set must not invent a key kind it cannot prove.

BUG-UNCALLED-FN-PARAM-NAME-POISONS-A-CALLED-ONE and
BUG-FOR-DICT-KEY-KIND-GUESSED — two bugs, one line of code.

`_emit_for_dict` writes the loop variable with `dict_key_fv`, which always
stores the key's *runtime* tag.  The static tag it records alongside is
therefore not an optimisation hint: it is what later statements build new
FpyValues from, with a literal tag, discarding the runtime one.  `out = k`
compiled to

    %".57" = extractvalue {i32, i64} %"k.fv", 1      ; the data, kept
    %".60" = insertvalue {i32, i64} undef, i32 2, 0  ; the tag, invented (STR)

so a wrong static kind is a wrong program, not a slow one.  With the key an
integer `5` and the tag claiming str, the incref read the string header eight
bytes before the payload — address -3 — and the process died with no output.

The old code produced that tag two ways, both of them guesses:

  * a dict it could not prove int-keyed was called **str**-keyed, and
  * every set was called an **int** set ("most common").

"Not proven int" is not evidence of str.  Both unproven cases now answer
`unknown`, which keeps the runtime tag and dispatches dynamically; a concrete
kind is named only when a literal, or `_is_int_keyed_dict` /
`_is_str_keyed_dict`, actually proves it.

The second bug is why proving it mattered so much.  `_is_int_keyed_dict`'s
parameter fallback searched *every* FunctionDef in the module for one with a
parameter of the right bare name, took the first, and stopped.  Parameter
names are scoped, and `_call_site_param_types` only has entries for functions
that are actually called — so a dead `def unused(data)` above a live
`def mode(data)` answered for `mode`, with no call-site evidence and hence no
type.  `mode`'s dict stopped being provably int-keyed and fell into the "str"
guess above.  Lookups are now scoped by `_csa_tag_for_param`, which keys on
(function, parameter) via `self._current_func_name`.
"""

# ── The original repro, verbatim: the dead def must not poison the live one ──


def unused(data):        # never called anywhere
    return 1


def mode(data):
    freq = {}
    for x in data:
        freq[x] = 1
    max_val = data[0]
    for val in freq:
        max_val = val
    return max_val


print(mode([5]))
print(mode([7, 7, 7]))


# Same shape with the names the other way round, and with several decoys, so
# the test does not pass merely because the *first* def happens to be right.


def alsounused(items):
    return 0


def live_first(items):
    seen = {}
    for it in items:
        seen[it] = 1
    first = items[0]
    for k in seen:
        first = k
    return first


def neverused(items):
    return -1


print(live_first([11]))


# ── An int-keyed dict that is genuinely unprovable ──
# `d[n] = 1` for a parameter `n` pins nothing, and the dict crosses a function
# boundary.  There is no analysis that reaches "int" here, and there must not
# be a guess either: the loop variable has to carry its runtime tag.


def build(n):
    d = {}
    d[n] = 1
    return d


def last_key(d):
    out = 0
    for k in d:
        out = k
    return out


print(last_key(build(7)))
print(last_key(build(-3)))


# ── The mirror case: string keys, equally unprovable ──


def build_s(k):
    d = {}
    d[k] = 1
    return d


def last_key_s(d):
    out = ""
    for k in d:
        out = k
    return out


print(last_key_s(build_s("zed")))


# ── A dict whose keys are not all one kind ──
# Nothing may be claimed about this loop variable at all.

mixed = {}
mixed["a"] = 1
mixed[2] = 3
mixed[3.5] = 4
n_mixed = 0
kinds = []
for k in mixed:
    n_mixed = n_mixed + 1
    kinds.append(str(k))
print(n_mixed, sorted(kinds))


# ── The provable cases must keep their concrete kinds ──

lit_int = {1: "a", 2: "b"}
tot = 0
for k in lit_int:
    tot = tot + k
print(tot)

lit_str = {"a": 1, "b": 2}
acc = ""
for k in lit_str:
    acc = acc + k
print(acc)

grown = {}
grown[10] = "x"
grown[20] = "y"
tot2 = 0
for k in grown:
    tot2 = tot2 + k
print(tot2)

grown_s = {}
grown_s["p"] = 1
grown_s["q"] = 2
acc2 = ""
for k in grown_s:
    acc2 = acc2 + k
print(acc2)


# ── Sets: "most sets are int sets" was never a proof ──

si = {1, 2, 3}
st = 0
for e in si:
    st = st + e
print(st)

ss = {"p", "q"}
sacc = []
for e in ss:
    sacc.append(e)
print(sorted(sacc))


def make_set(a, b):
    s = set()
    s.add(a)
    s.add(b)
    return s


def join_set(s):
    out = []
    for e in s:
        out.append(str(e))
    return sorted(out)


print(join_set(make_set("xy", "zw")))
print(join_set(make_set(4, 9)))


# ── A dict comprehension on each side ──

dc_int = {i: i * 2 for i in range(4)}
dsum = 0
for k in dc_int:
    dsum = dsum + k
print(dsum)

dc_str = {str(i): i for i in range(3)}
dacc = ""
for k in dc_str:
    dacc = dacc + k
print(dacc)


# ── The loop variable used every way a wrong tag would show up ──
# Plain rebinding is what crashed; the rest would have printed nonsense.


def uses(d):
    last = None
    n = 0
    parts = []
    for k in d:
        last = k                 # the rebinding that crashed
        n = n + 1
        parts.append(str(k))     # str() on a mis-tagged value
        if k in d:               # the key fed back as a key
            pass
    return last, n, sorted(parts)


print(uses(build(42)))
print(uses(build_s("q")))
print(uses({1: "a", 2: "b"}))
print(uses({"a": 1, "b": 2}))
