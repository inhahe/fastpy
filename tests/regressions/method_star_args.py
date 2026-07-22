"""Regression test: *args in class methods.

Previously, methods with *args (e.g., def bar(self, *args)) would crash
with NameError because the method parameter setup loop only iterated
positional parameters, never creating the *args variable. Fixed by:
1. Adding *args as an i8_ptr (FpyList*) parameter in the method signature
2. Creating the args variable in _emit_method_body after positional params
3. Packing extra arguments into a list at call sites (direct dispatch)
4. Runtime vararg-aware dispatch (obj_call_methodN packs args into a list)
"""


# Test 1: basic *args
class A:
    def show(self, *args):
        print(len(args))
        for a in args:
            print(a)

A().show(1, 2, 3)

# Test 2: *args with positional params before it
class B:
    def method(self, x, *args):
        print(x)
        print(len(args))
        for a in args:
            print(a)

B().method(10, 20, 30)

# Test 3: empty *args
class C:
    def empty(self, *args):
        print(len(args))

C().empty()

# Test 4: *args indexing
class D:
    def first(self, *args):
        if len(args) > 0:
            print(args[0])

D().first(42, 99)

# Test 5: __exit__ with *args (context manager protocol)
class Ctx:
    def __enter__(self):
        print("enter")
        return self
    def __exit__(self, *args):
        print("exit")
        print(len(args))

with Ctx() as c:
    print("body")

# Test 6: *args stored in variable
class F:
    def store(self, *args):
        data = args
        print(len(data))

F().store(1, 2, 3, 4)

# Test 7: *args forwarding to another function
def show_all(*args):
    for a in args:
        print(a)

class G:
    def forward(self, *args):
        show_all(*args)

G().forward(7, 8, 9)
