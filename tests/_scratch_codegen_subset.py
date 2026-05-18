# Realistic compiler pattern: code generation with class dispatch
class CodeGen:
    def __init__(self):
        self.output = []
        self.indent = 0
        self.variables = {}
        self._label_count = 0

    def emit(self, line):
        self.output.append("  " * self.indent + line)

    def new_label(self):
        self._label_count = self._label_count + 1
        return "L" + str(self._label_count)

    def generate(self, node):
        kind = node[0]
        if kind == "assign":
            self._gen_assign(node)
        elif kind == "print":
            self._gen_print(node)
        elif kind == "if":
            self._gen_if(node)
        elif kind == "while":
            self._gen_while(node)
        elif kind == "block":
            for stmt in node[1]:
                self.generate(stmt)

    def _gen_assign(self, node):
        name = node[1]
        value = self._gen_expr(node[2])
        self.variables[name] = value
        self.emit(name + " = " + value)

    def _gen_print(self, node):
        value = self._gen_expr(node[1])
        self.emit("print(" + value + ")")

    def _gen_expr(self, expr):
        if isinstance(expr, int):
            return str(expr)
        if isinstance(expr, str):
            if expr in self.variables:
                return expr
            return '"' + expr + '"'
        if isinstance(expr, tuple):
            if expr[0] == "+":
                return self._gen_expr(expr[1]) + " + " + self._gen_expr(expr[2])
            if expr[0] == "<":
                return self._gen_expr(expr[1]) + " < " + self._gen_expr(expr[2])
        return "?"

    def _gen_if(self, node):
        cond = self._gen_expr(node[1])
        lbl_else = self.new_label()
        self.emit("if not " + cond + " goto " + lbl_else)
        self.indent = self.indent + 1
        self.generate(node[2])
        self.indent = self.indent - 1
        self.emit(lbl_else + ":")

    def _gen_while(self, node):
        lbl_top = self.new_label()
        lbl_end = self.new_label()
        self.emit(lbl_top + ":")
        cond = self._gen_expr(node[1])
        self.emit("if not " + cond + " goto " + lbl_end)
        self.indent = self.indent + 1
        self.generate(node[2])
        self.indent = self.indent - 1
        self.emit("goto " + lbl_top)
        self.emit(lbl_end + ":")

# Generate code for a simple program:
# x = 0
# while x < 5:
#     print(x)
#     x = x + 1
program = ("block", [
    ("assign", "x", 0),
    ("while", ("<", "x", 5), ("block", [
        ("print", "x"),
        ("assign", "x", ("+", "x", 1)),
    ])),
])

cg = CodeGen()
cg.generate(program)
for line in cg.output:
    print(line)
