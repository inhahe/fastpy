# Regression: global declaration inside a closure that also captures variables
# Previously the global write was silently dropped because _global_vars
# wasn't populated yet when closure bodies were compiled during prescan.

x = 10

def outer():
    z = 99
    def inner():
        global x
        x = 100
        _ = z  # capture z to force closure
    inner()

outer()
print(x)

# Also test nonlocal + global in same closure
y = 20

def outer2():
    a = 30
    def inner2():
        nonlocal a
        global y
        a = 300
        y = 200
    inner2()
    print(f"a={a}")

outer2()
print(f"y={y}")
