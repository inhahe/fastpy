# Regression: diamond inheritance with MRO-aware super() dispatch
# In D(B, C) where B(A) and C(A), super() in B should go to C (per MRO),
# not directly to A.

class A:
    def __init__(self):
        self.log = []

    def greet(self):
        return "A"

class B(A):
    def __init__(self):
        super().__init__()
        self.log.append("B")

    def greet(self):
        return "B+" + super().greet()

class C(A):
    def __init__(self):
        super().__init__()
        self.log.append("C")

    def greet(self):
        return "C+" + super().greet()

class D(B, C):
    def __init__(self):
        super().__init__()
        self.log.append("D")

    def greet(self):
        return "D+" + super().greet()

d = D()
print(d.greet())   # D+B+C+A  (MRO: D -> B -> C -> A)
print(d.log)       # ['C', 'B', 'D']  (__init__ MRO: D->B->C->A, A sets log=[], C appends, B appends, D appends)
