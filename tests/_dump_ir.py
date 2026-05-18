"""Dump LLVM IR for a source file."""
import ast, sys
sys.path.insert(0, r"D:\visual studio projects\fastpy")
from compiler.codegen import CodeGen

import sys
src_file = sys.argv[1] if len(sys.argv) > 1 else r"D:\visual studio projects\fastpy\tests\_scratch_pipeline2.py"
out_file = src_file.replace(".py", ".ll")
source = open(src_file).read()
tree = ast.parse(source)
cg = CodeGen()
ir_str = cg.generate(tree)
with open(out_file, "w") as f:
    f.write(ir_str)
print(f"IR dumped to {out_file}")
