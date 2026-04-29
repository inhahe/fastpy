# Regression: with statement __exit__ returning True suppresses exception

class Suppressor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Return True to suppress any exception
        return True

class NoSuppress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

# Test 1: exception is suppressed
try:
    with Suppressor():
        raise ValueError("boom")
    print("suppressed")  # Should reach here
except ValueError:
    print("not suppressed")

# Test 2: exception is NOT suppressed
try:
    with NoSuppress():
        raise ValueError("boom2")
    print("suppressed2")
except ValueError:
    print("not suppressed2")  # Should reach here

# Test 3: no exception — normal flow
with Suppressor():
    print("normal")
print("done")
