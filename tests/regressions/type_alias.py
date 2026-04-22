# Regression test for type statement (PEP 695, Python 3.12+)

type Number = int | float
type StringList = list[str]

x: Number = 42
print(x)           # 42

y: Number = 3.14
print(y)           # 3.14

print("type alias works")  # type alias works
