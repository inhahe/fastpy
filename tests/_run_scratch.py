"""Run a scratch test through the proper compilation pipeline."""
import sys
sys.path.insert(0, r"D:\visual studio projects\fastpy")
from compiler.pipeline import compile_source
import subprocess

src_file = sys.argv[1] if len(sys.argv) > 1 else r"D:\visual studio projects\fastpy\tests\_scratch_irbuilder2.py"
source = open(src_file).read()

result = compile_source(source)
if not result.success:
    print("Compilation failed:")
    for e in result.errors:
        print(f"  {e}")
    sys.exit(1)

print(f"Compiled to: {result.executable}")
proc = subprocess.run([str(result.executable)], capture_output=True, text=True, timeout=10)
print("=== STDOUT ===")
print(proc.stdout)
if proc.stderr:
    print("=== STDERR ===")
    print(proc.stderr)
print(f"=== EXIT CODE: {proc.returncode} ===")
