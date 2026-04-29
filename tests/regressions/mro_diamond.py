# Multiple inheritance MRO: D(B, C) where both override method from A
class A:
    def method(self):
        return "A"

class B(A):
    def method(self):
        return "B"

class C(A):
    def method(self):
        return "C"

class D(B, C):
    pass

d = D()
print(d.method())  # Should be "B" (MRO: D -> B -> C -> A)

# Secondary base method accessible when primary doesn't have it
class E:
    def only_e(self):
        return "E"

class F(B, E):
    pass

f = F()
print(f.method())    # "B" from primary
print(f.only_e())    # "E" from secondary
