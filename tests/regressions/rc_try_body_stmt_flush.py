"""Try/except*/with bodies must flush owned temps per *statement*.

BUG-DECREF-DOES-NOT-DOMINATE, facet (c).

Model-2 refcounting registers every freshly allocated `+1` heap value as an
*owned temp*, and `_emit_stmts` releases the pending set at each statement
boundary with a watermark flush:

    for stmt in stmts:
        _rc_mark = len(self._rc_temps)
        self._emit_stmt(stmt)
        self._flush_rc_temps_to(_rc_mark)

The three try-like body loops — `_emit_try`, `_emit_try_star` and the
with-statement body — did NOT go through `_emit_stmts`. They iterated
`node.body` calling `_emit_stmt` directly, so no flush ever ran between
statements. Two things followed:

  * every temp produced anywhere in the body piled up in `_rc_temps`, and
  * the pile was finally released wherever the *enclosing* flush happened —
    typically `try.end`.

But each statement in a try body is followed by a pending-exception check that
opens a *new* block (`try.cont` / `trystar.cont` / `with.cont`). So a value
defined in `try.cont.4` was decref'd in `try.end.2`, which does not dominate
it. LLVM rejected the whole module:

    Instruction does not dominate all uses!
      %.36 = ptrtoint ptr %.35 to i64
      call void @fpy_rc_decref(i32 2, i64 %.36)

That is a hard compile failure, not a silent miscompile — every program with
two heap-producing statements in a try body failed to build.

The fix mirrors `_emit_stmts`, with one deliberate difference: the flush is
emitted **in `cont_block`**, i.e. after the pending-exception branch, rather
than immediately after `_emit_stmt`. On the raising path a partially executed
statement may have registered a temp whose value is undefined (a runtime call
that sets an exception still returns *something*), and decref'ing that is a
use-after-free; leaking it is the safe direction under the project's
owned/borrowed asymmetry rule. Definitions dominate `cont_block` either way,
so the IR is valid regardless.

The `is_terminated` early-outs still call the flush so the temps are popped
from the compiler-side list; `_flush_rc_temps_to` emits no decrefs once the
block is terminated.
"""


def two_producers_in_try():
    # The original repro: two str() temps in one try body.
    try:
        s = str(7)
        s = str(8)
        print(s)
    except ValueError:
        print("no")


def many_producers_in_try():
    # More statements => more `try.cont` blocks => more dominance edges.
    try:
        a = str(1) + "a"
        b = str(2) + "b"
        c = str(3) + "c"
        d = ",".join([a, b, c])
        e = d.upper()
        print(a, b, c, d, e)
    except ValueError:
        print("no")


def try_with_except_taken():
    # The handler runs, so the body's temps are abandoned mid-way. This must
    # still compile and must not double-release.
    try:
        s = str(9) + "!"
        print(s)
        raise ValueError("boom")
    except ValueError as exc:
        print("caught", exc)


def try_finally_runs():
    try:
        s = str(11) + "?"
        t = s + s
        print(len(t))
    finally:
        print("fin")


def try_in_loop():
    # 50 iterations: a missing per-iteration release leaks without bound.
    total = 0
    i = 0
    while i < 50:
        try:
            u = str(i) + "-"
            v = u + u
            total = total + len(v)
        except ValueError:
            pass
        i = i + 1
    print(total)


def try_with_return():
    # `return` terminates the block mid-body; the flush must pop the pending
    # temps without emitting decrefs into a terminated block.
    try:
        s = str(21) + "!"
        return s
    except ValueError:
        return "no"


def nested_try():
    try:
        outer = str(31) + "o"
        try:
            inner = str(32) + "i"
            print(outer, inner)
        except ValueError:
            print("inner-no")
        print(outer)
    except ValueError:
        print("outer-no")


def try_else_clause():
    try:
        s = str(41) + "e"
    except ValueError:
        print("no")
    else:
        t = s + s
        print(t)


def assert_with_dynamic_msg_in_try(n):
    # `assert` splits into pass/fail arms and the message is built in the
    # *fail* arm, which always terminates (it raises). Those temps must not
    # escape to the try body's per-statement flush, which runs in `try.cont`
    # — a block the fail arm does not dominate. Adding the flush above turned
    # that pre-existing leak into an invalid-IR failure until `_emit_assert`
    # was taught to drop its own arm's temps.
    #
    # They are *dropped*, not released: `fastpy_raise` stores the message
    # pointer instead of copying it, so the handler still needs it.
    try:
        assert n > 10, f"expected > 10, got {n}"
        print("ok")
    except AssertionError as e:
        print("caught:", e)
    try:
        assert n > 10, "got " + str(n)
        print("ok")
    except AssertionError as e:
        print("caught:", e)


class _Ctx:
    def __enter__(self):
        print("enter")
        return self

    def __exit__(self, exc_type, exc_value, tb):
        print("exit")
        return False


def with_body_producers():
    # The with-statement body loop had the identical bypass.
    with _Ctx():
        a = str(51) + "w"
        b = a.upper()
        c = ",".join([a, b])
        print(a, b, c)


def with_body_in_loop():
    i = 0
    while i < 20:
        with _Ctx():
            s = str(i) + "!"
            t = s + s
            print(len(t))
        i = i + 1


two_producers_in_try()
many_producers_in_try()
try_with_except_taken()
try_finally_runs()
try_in_loop()
print(try_with_return())
nested_try()
try_else_clause()
assert_with_dynamic_msg_in_try(3)
assert_with_dynamic_msg_in_try(30)
with_body_producers()
with_body_in_loop()
