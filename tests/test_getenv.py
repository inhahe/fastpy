import os

# Test os.getenv with existing var
path = os.getenv("PATH")
if path is not None:
    print("PATH exists")
else:
    print("PATH missing")

# Test os.getenv with non-existing var
val = os.getenv("FASTPY_NONEXISTENT_VAR_12345")
if val is None:
    print("nonexistent is None")
else:
    print("unexpected:", val)

print("DONE")
