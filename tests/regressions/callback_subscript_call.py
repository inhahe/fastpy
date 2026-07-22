# Regression: function/lambda called via list subscript or iteration
# Previously, calling fns[0]("arg") passed args without type info,
# and lambda parameters defaulted to INT, printing pointer values.

# 1. Direct subscript call with arg tag
def greet(name):
    print(name)

fns = [greet]
fns[0]("sub_call")

# 2. Closure lambda called from list subscript
events = []
fns3 = [lambda d: events.append(f"got: {d}")]
fns3[0]("via_sub")
print(events)

# 3. Two-arg subscript call
def add(a, b):
    return a + b

ops = [add]
print(ops[0](3, 4))

# 4. Closure lambdas iterated from a plain list
results = []
callbacks = [lambda d: results.append(f"A: {d}"), lambda d: results.append(f"B: {d}")]
for cb in callbacks:
    cb("test")
print(results)
