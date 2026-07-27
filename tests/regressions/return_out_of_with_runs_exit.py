# BUG-RETURN-IN-WITH-SKIPS-EXIT
#
# `_emit_with` lowers the block by hand instead of desugaring to a real
# try/finally, and the `__exit__` call it emits lives in a block that a
# `return` inside the body branches straight past.  To cover that, the with
# pushed a *placeholder* onto the finally stack:
#
#     self._finally_stack.append([])   # placeholder
#
# `_emit_return` walks that stack and emits each entry's statements.  An empty
# list emits nothing, so
#
#     def f():
#         with T():
#             return 1
#
# left the block without calling `__exit__` at all — no cleanup, no close, and
# for a contextlib.contextmanager the generator never resumed past its yield.
#
# The stack now carries a callback for a `with`, since its cleanup is IR that
# was never an AST, and `_emit_return` invokes it.
#
# The same walk was missing entirely from `break` and `continue`, for both
# `with` and `try/finally` — they just branched to the loop's exit.  Those
# leave only the cleanups pushed *inside* the loop, so `_push_loop` now records
# the finally depth at loop entry and `_emit_break`/`_emit_continue` unwind
# down to it.


# (The per-iteration names below are built into a local first, rather than
# written inline as `T("b" + str(i), log)`.  A BinOp passed straight as a
# constructor argument types `__init__`'s parameter as an int and then every
# call site of that constructor reads the attribute back as one — which is
# BUG-CTOR-ARG-BINOP-TYPES-PARAM-INT, unrelated to this file's subject.)


class T:
    def __init__(self, n, log):
        self.n = n
        self.log = log

    def __enter__(self):
        self.log.append("enter " + self.n)
        return self

    def __exit__(self, a, b, c):
        self.log.append("exit " + self.n)


# --- the original shape ---
def ret_from_with(log):
    with T("one", log):
        return "r1"


lg = []
print("ret:", ret_from_with(lg))
print("ret log:", lg)


# --- returning a value computed inside the block ---
def ret_computed(n, log):
    with T("two", log):
        return n * 3


lg2 = []
print("computed:", ret_computed(7, lg2))
print("computed log:", lg2)


# --- returning the bound name ---
def ret_bound(log):
    with T("three", log) as t:
        return t.n


lg3 = []
print("bound:", ret_bound(lg3))
print("bound log:", lg3)


# --- nested withs unwind outward, both running ---
def ret_nested(log):
    with T("out", log):
        with T("in", log):
            return "rn"


lg4 = []
print("nested:", ret_nested(lg4))
print("nested log:", lg4)


# --- a return under a condition, and the fall-through path too ---
def ret_maybe(a, log):
    nm = "maybe" + str(a)
    with T(nm, log):
        if a:
            return "early"
    return "late"


lg5 = []
print("maybe:", ret_maybe(1, lg5), ret_maybe(0, lg5))
print("maybe log:", lg5)


# --- with inside try/finally: both cleanups, innermost first ---
def ret_with_in_finally(log):
    try:
        with T("w", log):
            return "rwf"
    finally:
        log.append("fin")


lg6 = []
print("with-in-try:", ret_with_in_finally(lg6))
print("with-in-try log:", lg6)


# --- try/finally inside with: the finally, then __exit__ ---
def ret_finally_in_with(log):
    with T("outer", log):
        try:
            return "rfw"
        finally:
            log.append("inner fin")


lg7 = []
print("try-in-with:", ret_finally_in_with(lg7))
print("try-in-with log:", lg7)


# --- break out of a with inside a loop ---
def break_from_with(log):
    for i in range(4):
        nm = "b" + str(i)
        with T(nm, log):
            if i == 1:
                break
    return "bd"


lg8 = []
print("break:", break_from_with(lg8))
print("break log:", lg8)


# --- continue out of a with ---
def continue_from_with(log):
    kept = 0
    for i in range(3):
        nm = "c" + str(i)
        with T(nm, log):
            if i == 1:
                continue
            kept += 1
    return kept


lg9 = []
print("continue:", continue_from_with(lg9))
print("continue log:", lg9)


# --- break and continue out of a try/finally ---
def break_from_finally(log):
    for i in range(4):
        try:
            if i == 2:
                break
        finally:
            log.append("bf" + str(i))
    return "bfd"


lgA = []
print("break-finally:", break_from_finally(lgA))
print("break-finally log:", lgA)


def continue_from_finally(log):
    total = 0
    for i in range(3):
        try:
            if i == 1:
                continue
            total += i
        finally:
            log.append("cf" + str(i))
    return total


lgB = []
print("continue-finally:", continue_from_finally(lgB))
print("continue-finally log:", lgB)


# --- a break inside a with that is itself inside a loop inside a with ---
def break_only_to_the_loop(log):
    with T("keep", log):
        for i in range(3):
            nm = "body" + str(i)
            with T(nm, log):
                if i == 1:
                    break
        log.append("after loop")
    return "bo"


lgC = []
print("bounded:", break_only_to_the_loop(lgC))
print("bounded log:", lgC)


# --- a while loop, which is a different lowering ---
def while_break(log):
    i = 0
    while True:
        nm = "w" + str(i)
        with T(nm, log):
            i += 1
            if i == 2:
                break
    return i


lgD = []
print("while:", while_break(lgD))
print("while log:", lgD)


# --- at module level, not in a function ---
lgE = []
for i in range(3):
    nm = "m" + str(i)
    with T(nm, lgE):
        if i == 1:
            break
print("module log:", lgE)


# --- run enough times that a leaked or unbalanced cleanup would show ---
def many(n, log):
    hits = 0
    for i in range(n):
        nm = "m" + str(i)
        with T(nm, log):
            if i % 2:
                continue
            hits += 1
    return hits


lgF = []
print("many:", many(200, lgF), len(lgF))


# --- a cleanup that really is a resource release ---
class Handle:
    def __init__(self, log):
        self.log = log
        self.open = False

    def __enter__(self):
        self.open = True
        self.log.append("open")
        return self

    def __exit__(self, a, b, c):
        self.open = False
        self.log.append("close")


def use_handle(log):
    h = Handle(log)
    with h:
        return h.open


lgG = []
inside = use_handle(lgG)
print("handle:", inside, lgG)


# --- the motivating case: a real file, closed by the return ---
# (The line is printed as-is rather than `.strip()`ed.  A str returned out of a
# function that read it from a file arrives re-tagged as an int, so calling a
# str method on it segfaults — BUG-FILEREAD-FN-RETTAG, nothing to do with the
# `with`.  `len()` and printing both work, and are enough to show the read
# happened.)
def read_first_line(path):
    with open(path, "r") as fh:
        return fh.readline()


_w = open("with_exit_tmp.txt", "w")
_w.write("line one\nline two\n")
_w.close()
_first = read_first_line("with_exit_tmp.txt")
print("file:", len(_first), _first)

# A skipped __exit__ leaves the handle open.  Reopening the same path for
# writing, and then removing it, is what that would break.
_w = open("with_exit_tmp.txt", "w")
_w.write("rewritten\n")
_w.close()
_again = read_first_line("with_exit_tmp.txt")
print("reopened:", len(_again), _again)

import os
os.remove("with_exit_tmp.txt")
print("removed:", os.path.exists("with_exit_tmp.txt"))
