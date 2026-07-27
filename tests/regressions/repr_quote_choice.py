# BUG-REPR-ALWAYS-SINGLE-QUOTES
#
# CPython *picks* the quote character when it reprs a string rather than
# always escaping: a string containing ' but no " is wrapped in double
# quotes, so repr("it's") is "it's" and not 'it\'s'. Only when both quote
# characters appear does the single quote get a backslash.
#
# fastpy had two independent repr routines — fpy_value_repr's STR case (used
# when a string is printed inside a container) and fastpy_str_repr (used by
# repr() itself) — that both hardcoded a single quote, and that also
# disagreed with each other about control characters: one emitted \xNN, the
# other passed the raw byte straight through. They now share one escaper, so
# both paths have to agree with CPython here.

print(repr("plain"))
print(repr("a'b"))
print(repr('a"b'))
print(repr("""a'b"c"""))
print(repr(""))
print(repr("'"))
print(repr('"'))
print(repr("''\"\""))

# Control characters get the named escapes, then \xNN.
print(repr("tab\there"))
print(repr("nl\nhere"))
print(repr("cr\rhere"))
print(repr("back\\slash"))
print(repr("bell\x07end"))
# \x00 is deliberately absent: fastpy's str is a NUL-terminated C string, so an
# embedded null truncates it long before repr sees it
# (BUG-STR-EMBEDDED-NUL-TRUNCATES). bytes, which carry an explicit length, do
# round-trip one — see the b"\x00\xff\x7f" case below.
print(repr("\x01\x1f\x7f"))

# The container path is the *other* repr routine — same answers required.
print(["it's", 'say "hi"', 'both\' and "'])
print(("tab\there", "nl\nhere"))
print({"k'": 'v"w'})
print({"it's"})

# bytes repr follows the same quote rule, but a non-printable byte has no
# character to show, so it stays \xNN.
print(repr(b"plain"))
print(repr(b"it's"))
print(repr(b'a"b'))
print(repr(b"""a'b"c"""))
print(repr(b"a\nb\tc\\d"))
print(repr(b"\x00\xff\x7f"))

# repr of a str nested one level deeper still round-trips.
print(repr(repr("it's")))
