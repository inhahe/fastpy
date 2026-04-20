"""Test native pathlib module."""
from pathlib import Path

# Construction and basic methods
p = Path(".")
print(p.exists())       # 1
print(p.is_dir())       # 1

# Path with subdirectory
f = Path("compiler/codegen.py")
print(f.exists())       # 1
print(f.is_file())      # 1

# Attributes
name = f.name
print(name)             # codegen.py
suffix = f.suffix
print(suffix)           # .py
stem = f.stem
print(stem)             # codegen
parent = f.parent
print(parent)           # compiler

# read_text
content = Path("pyproject.toml").read_text()
print(len(content) > 0)  # True

# Path / operator
sub = Path(".") / "compiler"
print(sub.is_dir())     # 1

print("pathlib tests passed!")
