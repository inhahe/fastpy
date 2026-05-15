# Bug 12: __mro__ access segfaults
class A:
    pass

class B(A):
    pass

class C(A):
    pass

class D(B, C):
    pass

print([cls.__name__ for cls in D.__mro__])
# Expected: ['D', 'B', 'C', 'A']
