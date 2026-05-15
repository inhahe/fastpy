# Regression: lambdas capturing module-level variables
# Bug: _declare_lambda (Pass 0) ran before _global_vars existed (Pass 0.72),
# so lambda bodies couldn't find captured variables (NameError).
# Fix: extended Pass 0.72 to scan lambda bodies for global references,
# and improved _declare_lambda return type inference to check module AST.

# Case 1: capture integer
x = 10
f1 = lambda: x
print(f1())

# Case 2: capture string
s = "hello"
f2 = lambda: s
print(f2())

# Case 3: capture float
pi = 3.14
f3 = lambda: pi
print(f3())

# Case 4: capture list
lst = [1, 2, 3]
f4 = lambda i: lst[i]
print(f4(0))
print(f4(2))

# Case 5: capture dict with int values
d1 = {"a": 1, "b": 2}
f5 = lambda k: d1[k]
print(f5("a"))
print(f5("b"))

# Case 6: capture dict with string values
d2 = {"a": "hello", "b": "world"}
f6 = lambda k: d2[k]
print(f6("a"))
print(f6("b"))

# Case 7: dict.get() with string values
f7 = lambda k: d2.get(k, "none")
print(f7("a"))
print(f7("c"))

# Case 8: lambda with param and capture
y = 5
f8 = lambda a: a + y
print(f8(3))

# Case 9: multiple captures
a = 10
b = 20
f9 = lambda: a + b
print(f9())
