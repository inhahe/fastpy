# BUG-FILEREAD-FN-RETTAG
#
# A function's return type is inferred in a pre-pass, before any body is
# emitted.  The fact "this local holds a file object" lived only in
# `CodeGen._file_vars`, which `_emit_assign` fills in *during* emission — so at
# inference time the set was empty, `f.read()` looked like a method call on an
# object of unknown type, and the function's return type fell through to the
# `int` default.  The call site then re-tagged a live string pointer as an
# integer:
#
#     def cat(path):
#         f = open(path, "r")
#         data = f.read()
#         f.close()
#         return data
#
#     "v: " + cat(p)      # TypeError: str + int
#     cat(p).strip()      # segfault — a str method dispatched on an int
#
# The inline form always worked, which is what made this look like a bug about
# files rather than about ordering.  The pre-pass now reads the same fact off
# the AST (`_scope_file_names`), so it can answer before the body exists.

import os

PATH = "fileread_rettag_tmp.txt"

_w = open(PATH, "w")
_w.write("alpha\nbeta\ngamma\n")
_w.close()


# --- the original shape: read into a local, return the local ---
def cat(path):
    f = open(path, "r")
    data = f.read()
    f.close()
    return data


whole = cat(PATH)
print("len:", len(whole))
print("concat:", "v: " + whole, end="")
print("method:", cat(PATH).upper(), end="")
print("index:", whole[0], whole[5])
print("count:", whole.count("a"))


# --- returned directly out of the call, no local ---
def first_line(path):
    f = open(path, "r")
    line = f.readline()
    f.close()
    return line


print("first:", first_line(PATH).strip())
print("first len:", len(first_line(PATH)))


# --- the `with` form, returning from inside the block ---
def first_via_with(path):
    with open(path, "r") as fh:
        return fh.readline()


print("with:", first_via_with(PATH).strip())


# --- the `with` form, binding a local and returning after the block ---
def first_via_with_local(path):
    with open(path, "r") as fh:
        s = fh.readline()
    return s


print("with local:", first_via_with_local(PATH).strip())


# --- two reads, and a return under a condition ---
def pick(path, which):
    f = open(path, "r")
    a = f.readline()
    b = f.readline()
    f.close()
    if which:
        return a
    return b


print("pick 1:", pick(PATH, 1).strip())
print("pick 0:", pick(PATH, 0).strip())


# --- the read passes through another local before the return ---
def relabelled(path):
    f = open(path, "r")
    raw = f.read()
    f.close()
    out = raw
    return out


print("relabelled:", len(relabelled(PATH)))


# --- a str method applied inside the function, then returned ---
def shouted(path):
    f = open(path, "r")
    t = f.readline()
    f.close()
    return t.strip().upper()


print("shouted:", shouted(PATH))


# --- concatenated inside the function ---
def prefixed(path):
    f = open(path, "r")
    t = f.readline()
    f.close()
    return "> " + t


print("prefixed:", prefixed(PATH), end="")


# --- the result feeds another function that takes a str ---
def width(s):
    return len(s)


print("through:", width(first_line(PATH)))


# (`return open(path, "r").read()` — a read straight off the open() call with
# no name in between — is the one shape this file does not cover, even though
# the fix handles it.  The file object is never closed and is not collected
# when the expression ends, so on Windows the handle outlives the program and
# `os.remove` cannot delete the file; the test would leave a stray temp file in
# the repo.  BUG-TEMP-FILE-OBJECT-HANDLE-LEAKED, and the reason it goes
# unnoticed is BUG-OS-REMOVE-IGNORES-FAILURE.)


# --- called in a loop, so a leaked handle or a stale tag would show ---
def count_reads(path, n):
    total = 0
    for _ in range(n):
        total += len(cat(path))
    return total


print("loop:", count_reads(PATH, 50))


# --- a name that is a file in one function and something else in another ---
# (The scan is per-scope, so `f` being a file in `cat` must not make `f` here
# one too — this would misroute `f.upper()` to the file-method emitter.)
def not_a_file(s):
    f = s
    return f.upper()


print("shadow:", not_a_file("beta"))


# --- a name assigned from open() *and* from something else is not claimed ---
def ambiguous(path, use_file):
    if use_file:
        g = open(path, "r")
        out = g.readline()
        g.close()
    else:
        g = "fallback\n"
        out = g
    return out


print("ambiguous 1:", ambiguous(PATH, 1).strip())
print("ambiguous 0:", ambiguous(PATH, 0).strip())


# --- writing through a function, then reading it back ---
def write_out(path, text):
    f = open(path, "w")
    f.write(text)
    f.close()
    return path


P2 = "fileread_rettag_tmp2.txt"
print("wrote:", write_out(P2, "delta\n"))
print("read back:", cat(P2).strip())

os.remove(P2)
os.remove(PATH)
print("cleaned:", os.path.exists(PATH), os.path.exists(P2))
