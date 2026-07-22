# Ultra-minimal: method returns string constant
class Foo:
    def __init__(self):
        self.x = 0

    def name(self):
        return "hello"

f = Foo()
s = f.name()
print(s)
