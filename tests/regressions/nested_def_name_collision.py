"""Two sibling nested `def`s that share a name must stay distinct.

BUG-NESTED-DEF-NAME-COLLISION.

Nearly every analysis map in the compiler is keyed by a function's **bare**
name, and `_csa_func_asts` is built with a flat
`func_asts.setdefault(node.name, node)` over `ast.walk(tree)`. So the *first*
`def build(...)` in the file won, and every other `build` in the module
inherited its analysis — its return type, its call-site parameter types, its
string-param detection:

    def list_return():
        def build(n):
            return [n, n + 1, n + 2]
        print(build(10))

    def dict_return():
        def build(k):
            return {k: str(k) + "v"}
        d = build("x")
        print(d["x"], len(d))       # IndexError: list index out of range

`d` was typed LIST from the *other* `build`, so `d["x"]` compiled to a list
index. Renaming either helper made it pass, which is why this survived: the
name only has to be unique, and in most real code it is.

The fix is an alpha-renaming pass (`_uniquify_nested_def_names`) that runs
before any analysis and gives colliding nested defs unique names. Re-keying
every map by scope would have meant auditing dozens of lookup sites and would
have left the flat ones as latent traps.

It is deliberately conservative — a nested def keeps its name when renaming
would be unsafe (a `global`/`nonlocal` naming it, or a rebinding assignment in
the owner scope), and module-level defs and class methods are never touched.
Those cases are exercised below to prove the pass leaves them alone *and*
still produces correct output.
"""


# ── The original repro: same name, different return kinds ──

def list_return():
    def build(n):
        return [n, n + 1, n + 2]
    a = build(10)
    print(a, len(a), a[0], a[2])


def dict_return():
    def build(k):
        return {k: str(k) + "v"}
    d = build("x")
    print(d["x"], len(d))


def str_return():
    def build(n):
        return str(n) + "s"
    s = build(3)
    print(s, len(s))


def int_return():
    def build(n):
        return n * 7
    v = build(6)
    print(v, v + 1)


# ── A nested def colliding with a module-level def of the same name ──

def helper(n):
    # Module-level: keeps its name, since that name is externally visible.
    return "module:" + str(n)


def shadows_module_helper():
    def helper(n):
        return ["nested", n]
    r = helper(5)
    print(r, len(r))
    print(helper(6)[0])


def uses_module_helper():
    print(helper(1))


# ── Recursion inside a renamed nested def ──

def recursive_nested():
    def fact(n):
        if n <= 1:
            return 1
        return n * fact(n - 1)
    print(fact(6))


def recursive_nested_other():
    # Same name, different body and return kind.
    def fact(n):
        return "f" + str(n)
    print(fact(6))


# ── Captures: the renamed def is a real closure ──

def capturing_a():
    tag = "-A"

    def fmt(n):
        return str(n) + tag
    print(fmt(1))


def capturing_b():
    tag = 100

    def fmt(n):
        return n + tag
    print(fmt(1))


# ── Two levels deep, colliding at both levels ──

def two_deep_a():
    def mid(n):
        def leaf(m):
            return str(m) + "a"
        return leaf(n) + "!"
    print(mid(2))


def two_deep_b():
    def mid(n):
        def leaf(m):
            return m * 10
        return leaf(n) + 1
    print(mid(2))


# ── The name is also a parameter elsewhere: must not be rewritten there ──

def takes_param_named_build(build):
    # `build` here is an int parameter, not the nested function.
    return build + 1


def calls_with_param_named_build():
    print(takes_param_named_build(41))


# ── Class methods share a name with nested defs; never renamed ──

class _Box:
    def __init__(self, v):
        self.v = v

    def build(self):
        return "box:" + str(self.v)


def uses_class_build():
    b = _Box(9)
    print(b.build())


# ── The pass bails out: an assignment rebinds the name in the owner scope ──

def rebound_in_scope():
    # `pick` is both a nested def and an assignment target, so the renaming
    # pass leaves it alone. Behaviour must still match CPython.
    def pick(n):
        return n + 1
    print(pick(1))
    pick = 5
    print(pick)


# ── Same name in a loop body and in a conditional ──

def collide_in_loop():
    total = 0
    i = 0
    while i < 5:
        def step(n):
            return str(n) + "#"
        total = total + len(step(i))
        i = i + 1
    print(total)


def collide_in_branch(flag):
    # A branch-local nested def colliding with `step` in `collide_in_loop`
    # above. Two same-name defs in the *same* scope are a different problem —
    # Python rebinds the name and resolving a use needs flow analysis, which
    # this pass does not do (BUG-SAME-SCOPE-DEF-REBIND).
    if flag:
        def step(n):
            return n * 2
        return step(4)
    return 12


list_return()
dict_return()
str_return()
int_return()
shadows_module_helper()
uses_module_helper()
recursive_nested()
recursive_nested_other()
capturing_a()
capturing_b()
two_deep_a()
two_deep_b()
calls_with_param_named_build()
uses_class_build()
rebound_in_scope()
collide_in_loop()
print(collide_in_branch(True), collide_in_branch(False))
