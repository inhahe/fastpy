# Regression: inner functions and closures inside class methods
# Bug 1: _scan_for_closures didn't scan class method bodies, so inner
#         functions inside methods were never registered.
# Bug 2: _emit_method_body didn't set _current_func_name, so
#         _emit_nested_funcdef couldn't match the closure info.

# 1. Hoisted inner function inside method (no captures)
class Math:
    def compute(self, values):
        def square(x):
            return x * x
        total = 0
        for v in values:
            total += square(v)
        return total

m = Math()
print(m.compute([1, 2, 3, 4]))  # 30

# 2. Closure inside method (captures method parameter)
class Counter:
    def make_adder(self, base):
        def add(x):
            return x + base
        return add

c = Counter()
f = c.make_adder(10)
print(f(5))   # 15
print(f(20))  # 30

# 3. Inner function used in list comprehension
class Processor:
    def process(self, data):
        def helper(x):
            return x * 2
        return [helper(d) for d in data]

p = Processor()
print(p.process([1, 2, 3]))  # [2, 4, 6]
