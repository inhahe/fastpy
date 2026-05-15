# Regression: closure default args with same-name shadowing
# Bug 1: def g(i=i) inside a loop — parameter name 'i' shadows outer 'i',
#         causing the default value to not be set on the hoisted function.
# Bug 2: closures stored in lists had wrong FpyValue tag (STR instead of OBJ),
#         causing use-after-free when the defining function returned.

# 1. Module-level: loop with i=i defaults
funcs = []
for i in range(3):
    def g(i=i):
        return i
    funcs.append(g)

print(funcs[0]())  # 0
print(funcs[1]())  # 1
print(funcs[2]())  # 2

# 2. Module-level: two-arg with i=i default
funcs2 = []
for i in range(3):
    def h(x, i=i):
        return x + i
    funcs2.append(h)

print(funcs2[0](10))  # 10
print(funcs2[1](10))  # 11
print(funcs2[2](10))  # 12

# 3. Returned from a function (tests refcount correctness)
def make_adders():
    adders = []
    for i in range(3):
        def adder(x, i=i):
            return x + i
        adders.append(adder)
    return adders

for f in make_adders():
    print(f(100))
# 100, 101, 102

# 4. Returned closures with val=i (non-shadowing defaults)
def make_funcs():
    funcs = []
    for i in range(3):
        def f(val=i):
            return val
        funcs.append(f)
    return funcs

result = make_funcs()
for fn in result:
    print(fn())
# 0, 1, 2

# 5. Closures called inside defining function (should still work)
def test_inside():
    funcs = []
    for i in range(3):
        def g(i=i):
            return i
        funcs.append(g)
    for fn in funcs:
        print(fn())

test_inside()
# 0, 1, 2
