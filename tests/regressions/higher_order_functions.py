# Regression: higher-order function patterns
# Bug: functions stored in dicts and called indirectly segfaulted because
# (a) _funcs_used_as_values was never populated, leaving _duf_select_abi
# and _efd_store_parameters checks as dead code, and (b) _bare_to_tag_data
# wrapped function pointers with cpython_wrap_native instead of storing raw
# pointers for native dispatch.
# Fix: Added _funcs_used_as_values pre-scan in _analyze_call_sites, changed
# _bare_to_tag_data to store raw function pointers, and added FVALUE/MIXED/OBJ
# dispatch in _emit_call_expr to route through _emit_closure_call.

# Case 1: Function stored in dict and called
def add(a, b):
    return a + b

def sub(a, b):
    return a - b

ops = {"add": add, "sub": sub}
func = ops["add"]
print(func(10, 3))

func2 = ops["sub"]
print(func2(10, 3))

# Case 2: Function passed as argument to another function
def apply(f, x, y):
    return f(x, y)

print(apply(add, 5, 3))
print(apply(sub, 20, 7))

# Case 3: Function stored in list and called
funcs = [add, sub]
print(funcs[0](100, 1))
print(funcs[1](100, 1))

# Case 4: Function assigned to variable directly
callback = add
print(callback(7, 8))

# Case 5: Function returned from another function
def get_op(name):
    if name == "add":
        return add
    return sub

op = get_op("add")
print(op(3, 4))
op2 = get_op("sub")
print(op2(10, 4))

# Case 6: Decorator pattern (manual application)
def decorator(func):
    def wrapper(*args):
        print("calling")
        return func(*args)
    return wrapper

decorated = decorator(add)
print(decorated(1, 2))

# Case 7: String-returning function stored in dict
def greet(name):
    return "Hello, " + name

def farewell(name):
    return "Bye, " + name

actions = {"hi": greet, "bye": farewell}
f = actions["hi"]
print(f("Alice"))
f2 = actions["bye"]
print(f2("Bob"))

# Case 8: Function returning list, stored in dict
def make_list(n):
    result = []
    for i in range(n):
        result.append(i)
    return result

builders = {"mk": make_list}
fn = builders["mk"]
print(fn(4))
