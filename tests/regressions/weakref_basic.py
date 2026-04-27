# Test native weakref support: weakref.ref() creates a weak reference,
# calling the weakref dereferences it (returns the target or None).

import weakref

class Foo:
    def __init__(self, name):
        self.name = name

# --- Basic weakref creation and dereference ---
obj = Foo("hello")
r = weakref.ref(obj)
target = r()
print(target.name)  # hello

# --- Multiple weakrefs to same object ---
r2 = weakref.ref(obj)
t2 = r2()
print(t2.name)  # hello

# --- Weakref is alive check via dereference ---
result = r()
if result is not None:
    print("alive")  # alive
else:
    print("dead")

# --- Weakref to different objects ---
obj2 = Foo("world")
r3 = weakref.ref(obj2)
print(r3().name)  # world

# --- Storing weakref result in variable ---
ref_result = r()
print(ref_result.name)  # hello

# --- _weakref module variant ---
import _weakref

obj3 = Foo("native")
r4 = _weakref.ref(obj3)
print(r4().name)  # native

# --- from weakref import ref ---
from weakref import ref

obj4 = Foo("imported")
r5 = ref(obj4)
print(r5().name)  # imported
