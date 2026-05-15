# Key test: generator with for-loop over string (uses _gen_for_to_while)
# The for-loop is transformed to iter()/next() with try/except StopIteration
# Variables become self._<name> attributes

# Equivalent expanded form:
def chars(s):
    _iter_c = iter(s)
    _done_c = False
    while not _done_c:
        try:
            c = next(_iter_c)
        except StopIteration:
            _done_c = True
        if not _done_c:
            yield c

g = chars("hi")
print(next(g))
print(next(g))
