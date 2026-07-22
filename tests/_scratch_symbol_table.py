# Symbol table with scoping (like compiler's variable tracking)
class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.symbols = {}

    def define(self, name, value):
        self.symbols[name] = value

    def lookup(self, name):
        if name in self.symbols:
            return self.symbols[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        return None

    def child(self):
        return Scope(parent=self)

# Build a scope chain
global_scope = Scope()
global_scope.define("print", "builtin")
global_scope.define("len", "builtin")
global_scope.define("x", "int")

func_scope = global_scope.child()
func_scope.define("y", "float")
func_scope.define("local_var", "str")

inner_scope = func_scope.child()
inner_scope.define("z", "bool")

# Lookups
print(inner_scope.lookup("z"))      # local
print(inner_scope.lookup("y"))      # parent
print(inner_scope.lookup("x"))      # grandparent
print(inner_scope.lookup("print"))  # global
print(inner_scope.lookup("missing"))  # not found

# Shadowing
func_scope.define("x", "shadowed_float")
print(inner_scope.lookup("x"))  # should find shadowed version
