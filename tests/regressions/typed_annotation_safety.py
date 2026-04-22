# Regression test: typed annotation safety validation
# compile_flags: --typed
# With --typed, annotations contradicted by later assignments should
# fall back to full box instead of silently miscompiling.

# Case 1: annotation matches all assignments → should use native (fast)
x: int = 0
x = 42
print(x)  # 42

# Case 2: annotation contradicted by None assignment → should fall back to box
y: int = 0
if False:
    y = None  # contradicts int annotation
print(y)  # 0

# Case 3: annotation contradicted by string → should fall back to box
z: int = 5
if False:
    z = "hello"  # contradicts int annotation
print(z)  # 5

# Case 4: float annotation, consistent
w: float = 3.14
w = 2.71
print(w)  # 2.71

# Case 5: inside a function
def test_func():
    a: int = 10
    a = 20
    print(a)  # 20

    b: int = 10
    if False:
        b = [1, 2]  # contradicts int
    print(b)  # 10

test_func()
