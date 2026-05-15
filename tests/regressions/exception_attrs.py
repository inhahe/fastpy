# Regression: exception variable attribute access.
# Before fix: exception variables were stored as plain strings (the message),
# so e.args crashed (accessed .args on a str) and repr(e) returned the
# string repr 'msg' instead of ExcName('msg').

# 1. e.args[0] — direct subscript on exception tuple
try:
    raise ValueError("hello")
except ValueError as e:
    print(e.args[0])

# 2. e.args via variable
try:
    raise ValueError("test msg")
except ValueError as e:
    a = e.args
    print(len(a))
    print(a[0])

# 3. print(e.args) directly
try:
    raise ValueError("direct")
except ValueError as e:
    print(e.args)

# 4. repr(e) — should format as ExcName('msg')
try:
    raise ValueError("hello")
except ValueError as e:
    print(repr(e))

# 5. str(e) and type(e).__name__ still work
try:
    raise ValueError("hello")
except ValueError as e:
    print(str(e))
    print(type(e).__name__)

# 6. Different exception types
try:
    raise TypeError("bad type")
except TypeError as e:
    print(e.args[0])
    print(repr(e))

# 7. Exception with empty message
try:
    raise RuntimeError("")
except RuntimeError as e:
    print(len(e.args))
    print(repr(e))
