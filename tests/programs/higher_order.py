# Higher-order functions: map, filter, lambdas, reduce, closures

from functools import reduce

# map + filter with lambdas
nums = list(range(10))
squares = list(map(lambda x: x * x, nums))
print(squares)

evens = list(filter(lambda x: x % 2 == 0, nums))
print(evens)

# chained map/filter
result = list(map(lambda x: x * 10, filter(lambda x: x > 5, nums)))
print(result)

# reduce
total = reduce(lambda a, b: a + b, range(1, 6))
print(f"reduce_sum={total}")

product = reduce(lambda a, b: a * b, [1, 2, 3, 4, 5])
print(f"reduce_prod={product}")

# closure as callback factory
def make_multiplier(n):
    def mul(x):
        return x * n
    return mul

double = make_multiplier(2)
triple = make_multiplier(3)
print(list(map(double, [1, 2, 3])))
print(list(map(triple, [1, 2, 3])))

# sorted with key
pairs = [(2, "b"), (1, "c"), (3, "a")]
by_first = sorted(pairs, key=lambda p: p[0])
print(by_first)

print("tests passed!")
