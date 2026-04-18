# Regression: with statement (context managers).
# Tests __enter__ / __exit__ protocol, `as` binding,
# and cleanup on both normal exit and exception.

class Tracker:
    def __init__(self, name):
        self.name = name
    def __enter__(self):
        print(f"enter {self.name}")
        return self
    def __exit__(self, a, b, c):
        print(f"exit {self.name}")

# Basic with + as binding
with Tracker("basic") as t:
    print(f"body {t.name}")

# Without as
with Tracker("no-as"):
    print("no binding")

# Cleanup on exception
try:
    with Tracker("exc"):
        print("before raise")
        raise ValueError("oops")
except ValueError as e:
    print(f"caught: {e}")

# Normal flow continues after with
print("done")
