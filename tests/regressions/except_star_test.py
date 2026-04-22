# Regression test for except* (exception groups)

# Test 1: Single except* handler
try:
    raise ExceptionGroup("grp", [ValueError("val")])
except* ValueError as e:
    print("caught ValueError")
# caught ValueError

# Test 2: Two except* handlers — second should fire
try:
    raise ExceptionGroup("grp", [TypeError("type err")])
except* ValueError as e:
    print("caught ValueError")
except* TypeError as e:
    print("caught TypeError")
# caught TypeError

# Test 3: except* with no ExceptionGroup (plain exception)
try:
    raise ValueError("plain")
except* ValueError as e:
    print("caught plain ValueError")
# caught plain ValueError

# Test 4: bare except* (catch-all)
try:
    raise ExceptionGroup("grp", [RuntimeError("oops")])
except* RuntimeError:
    print("caught RuntimeError")
# caught RuntimeError
