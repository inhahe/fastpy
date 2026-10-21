"""Dump LLVM IR for a source file."""
import ast, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from compiler.codegen import CodeGen

src_file = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "_scratch_pipeline2.py")
out_file = str(Path(src_file).with_suffix(".ll"))
source = open(src_file, encoding="utf-8").read()
tree = ast.parse(source)
cg = CodeGen()
ir_str = cg.generate(tree)
with open(out_file, "w", encoding="utf-8") as f:
    f.write(ir_str)
print(f"IR dumped to {out_file}")
