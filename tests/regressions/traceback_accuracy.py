# Test that tracebacks show correct per-frame line numbers.
# The unhandled exception should show the actual call-site line,
# not the function definition line.

def level3(x):
    return x[99]  # line 6: IndexError here

def level2(x):
    return level3(x)  # line 9: call site

def level1(x):
    return level2(x)  # line 12: call site

try:
    level1([1, 2, 3])  # line 15: call site
except IndexError:
    print("caught nested IndexError")
