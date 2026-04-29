"""Test contextlib module import support."""
from contextlib import contextmanager, suppress

# The contextlib module is recognized as a native module.
# @contextmanager and suppress() are no-ops at compile time.
# Generator-based context managers work via the existing
# generator + with statement infrastructure.

print("contextlib imported OK")
print("contextlib tests passed!")
