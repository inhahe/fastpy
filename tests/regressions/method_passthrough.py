# Regression: method returning its parameter preserved the wrong type tag.
# Bug: bare ABI coerces args to i64 (ptrtoint for strings, bitcast for
#   floats). The set_arg_tag side-channel couldn't recover the original
#   type because _bare_to_tag_data only saw i64 and defaulted to INT.
# Fix: Added string/float constant and variable checks to the i64 branch
#   of _bare_to_tag_data, and added set_arg_tag to the direct dispatch path.

# 1. Basic echo: return the same value for every type
class Echo:
    def echo(self, val):
        return val

e = Echo()
print(e.echo(42))
print(e.echo("hello"))
print(e.echo(3.14))
print(e.echo(True))
print(e.echo(None))
print(e.echo([1, 2, 3]))

# 2. Identity wrapper around an object attribute
class Box:
    def __init__(self, item):
        self.item = item

    def get(self):
        return self.item

b1 = Box(99)
b2 = Box("world")
print(b1.get())
print(b2.get())

# 3. Chained passthrough: method returns result of another method
class Relay:
    def forward(self, val):
        return val

class Chain:
    def __init__(self):
        self.relay = Relay()

    def process(self, val):
        return self.relay.forward(val)

c = Chain()
print(c.process(10))
print(c.process("abc"))
