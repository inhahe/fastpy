# BUG-BUILTIN-EXC-HIERARCHY-NOT-MATCHED
#
# An `except` clause matched by comparing the raised exception's *type code*
# to the code of the handler's name.  The abstract builtins have no code of
# their own — `ArithmeticError` is not a thing anything raises, it is the
# parent of the three things that are — so `fastpy_exc_name_to_id` answered
# FPY_EXC_GENERIC for it, the equality failed, and:
#
#     try:
#         1 / 0
#     except ArithmeticError:     # never fired
#
# `except LookupError:` missed IndexError and KeyError the same way.  Worse,
# the *tuple* arm compared codes and nothing else, so `except (LookupError,
# X):` could not catch either, and the bare-name arm gated its user-class
# walk on *both* sides being FPY_EXC_GENERIC — so `except ValueError:` did
# not catch a user class derived from ValueError either.
#
# There were three of these arms (bare name, tuple element, dotted
# attribute) and each had drifted from the others.  They now share
# `_emit_exc_handler_matches`, which asks two questions: does the code match
# exactly, and does `fastpy_exc_class_matches` find the handler's name while
# walking up from the raised class.  The walk consults
# `fpy_builtin_exc_parent` — one table in the runtime, next to the code
# definitions it has to agree with — so a builtin parent and a user-defined
# base are answered by the same code.  A handler name that resolves to
# GENERIC no longer matches on the code alone, which is what made every
# unknown name catch every user-raised exception.

# --- the abstract builtins, which have no code of their own ---
try:
    1 / 0
except ArithmeticError as e:
    print("arith:", type(e).__name__)

try:
    1 // 0
except ArithmeticError as e:
    print("arith floordiv:", type(e).__name__)

try:
    1 % 0
except ArithmeticError as e:
    print("arith mod:", type(e).__name__)

try:
    {}["k"]
except LookupError as e:
    print("lookup dict:", type(e).__name__)

try:
    [1][9]
except LookupError as e:
    print("lookup list:", type(e).__name__)

try:
    (1, 2)[5]
except LookupError as e:
    print("lookup tuple:", type(e).__name__)

# --- the same names inside a tuple handler ---
try:
    [1][9]
except (LookupError, TypeError) as e:
    print("tuple lookup:", type(e).__name__)

try:
    1 / 0
except (TypeError, ArithmeticError) as e:
    print("tuple arith:", type(e).__name__)

try:
    {}["k"]
except (ValueError, LookupError) as e:
    print("tuple key:", type(e).__name__)

# --- the exact names still match, and only the right one ---
try:
    1 / 0
except ZeroDivisionError as e:
    print("exact zero:", type(e).__name__)

try:
    {}["z"]
except IndexError:
    print("WRONG: IndexError caught a KeyError")
except KeyError as e:
    print("exact key:", type(e).__name__)

try:
    [1][9]
except KeyError:
    print("WRONG: KeyError caught an IndexError")
except IndexError as e:
    print("exact index:", type(e).__name__)

try:
    int("x")
except ValueError as e:
    print("exact value:", type(e).__name__)

# --- a sibling in the hierarchy must NOT catch ---
try:
    1 / 0
except LookupError:
    print("WRONG: LookupError caught a ZeroDivisionError")
except ArithmeticError:
    print("sibling ok: arith caught it")

try:
    {}["k"]
except ArithmeticError:
    print("WRONG: ArithmeticError caught a KeyError")
except LookupError:
    print("sibling ok: lookup caught it")


# --- user-defined classes, matched through their declared base ---
class MyErr(ValueError):
    pass


class Deeper(MyErr):
    pass


try:
    raise MyErr("boom")
except ValueError as e:
    print("user via base:", type(e).__name__)

try:
    raise MyErr("boom")
except MyErr as e:
    print("user exact:", type(e).__name__)

try:
    raise Deeper("boom")
except ValueError as e:
    print("user via grandparent:", type(e).__name__)

try:
    raise Deeper("boom")
except MyErr as e:
    print("user via parent:", type(e).__name__)

try:
    raise MyErr("boom")
except Deeper:
    print("WRONG: a subclass handler caught its base")
except MyErr as e:
    print("not the subclass:", type(e).__name__)

try:
    raise MyErr("boom")
except TypeError:
    print("WRONG: TypeError caught a ValueError subclass")
except Exception as e:
    print("fallthrough:", type(e).__name__)

try:
    raise MyErr("boom")
except (KeyError, ValueError) as e:
    print("user in tuple:", type(e).__name__)


# --- a user class derived from an abstract builtin ---
class MyLookup(LookupError):
    pass


try:
    raise MyLookup("nope")
except LookupError as e:
    print("user under abstract base:", type(e).__name__)


# --- NameError and its subclass ---
def unbound(t):
    if t:
        v = 1
    return v


try:
    unbound(0)
except NameError as e:
    print("unbound via NameError:", type(e).__name__)

try:
    unbound(0)
except UnboundLocalError as e:
    print("unbound exact:", type(e).__name__)

try:
    unbound(0)
except (TypeError, NameError) as e:
    print("unbound in tuple:", type(e).__name__)


# --- every builtin is an Exception, and every Exception a BaseException ---
for thunk in ("zero", "key", "index", "value", "user"):
    try:
        if thunk == "zero":
            1 / 0
        elif thunk == "key":
            {}["k"]
        elif thunk == "index":
            [][0]
        elif thunk == "value":
            int("q")
        else:
            raise MyErr("boom")
    except Exception as e:
        print(thunk, "->", type(e).__name__)

try:
    1 / 0
except BaseException as e:
    print("base:", type(e).__name__)


# --- StopIteration is not an Exception subclass mismatch ---
try:
    next(iter([]))
except StopIteration as e:
    print("stop:", type(e).__name__)


# --- the handler that does not match falls through to the outer try ---
try:
    try:
        {}["k"]
    except ArithmeticError:
        print("WRONG: inner arith caught a KeyError")
except LookupError as e:
    print("outer lookup:", type(e).__name__)

try:
    try:
        raise MyErr("boom")
    except LookupError:
        print("WRONG: inner lookup caught a ValueError subclass")
except ValueError as e:
    print("outer value:", type(e).__name__)


# --- `finally` still runs on the path that matched ---
def with_finally(kind):
    out = []
    try:
        if kind == "zero":
            1 / 0
        else:
            {}["k"]
    except ArithmeticError:
        out.append("arith")
    except LookupError:
        out.append("lookup")
    finally:
        out.append("finally")
    return out


print(with_finally("zero"), with_finally("key"))


# --- re-raise preserves the class, and an outer abstract handler sees it ---
def reraise():
    try:
        try:
            {}["k"]
        except KeyError:
            raise
    except LookupError as e:
        return type(e).__name__


print("reraise:", reraise())


# --- str(e) survives the hierarchy walk ---
try:
    raise MyErr("the message")
except ValueError as e:
    print("msg:", str(e), type(e).__name__)

try:
    int("nope")
except ArithmeticError:
    print("WRONG")
except ValueError as e:
    print("msg2:", type(e).__name__)
