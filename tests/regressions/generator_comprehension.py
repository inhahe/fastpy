# Regression: list comprehension over generator objects.
# Before fix: [x for x in gen()] produced [] because _emit_list_comprehension
# called list_length() on the FpyObj* generator, which returned 0.
# Fix: materialize generator to FpyList* via list_from_obj_iter before
# the index-based iteration.

# 1. Simple comprehension over generator
def gen3():
    yield 1
    yield 2
    yield 3

print([x for x in gen3()])

# 2. Comprehension with expression
print([x * 2 for x in gen3()])

# 3. Comprehension with filter
print([x for x in gen3() if x > 1])

# 4. Generator with parameter
def count_up(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

print([x for x in count_up(5)])

# 5. Comprehension with expression over parameterized generator
print([x * x for x in count_up(4)])

# 6. String-yielding generator in comprehension
def greet():
    yield "hello"
    yield "world"

print([s for s in greet()])

# 7. Fibonacci generator consumed by comprehension
def fib_gen():
    a, b = 0, 1
    while a < 20:
        yield a
        a, b = b, a + b

print([x for x in fib_gen()])

# 8. Sum/len of comprehension result
nums = [x for x in count_up(5)]
print(sum(nums))
print(len(nums))

# 9. for-loop over string generator (ret_tag fix)
for s in greet():
    print(s)

# 10. enumerate over string generator
for i, s in enumerate(greet()):
    print(i, s)

# 11. next() on string generator
g = greet()
print(next(g))
print(next(g))

# 12. next() on int generator
g2 = gen3()
print(next(g2))
print(next(g2))
print(next(g2))

# 13. sum() of generator
print(sum(gen3()))

# 14. min() and max() of generator
print(min(gen3()))
print(max(gen3()))

# 15. sorted() of generator
def unsorted():
    yield 3
    yield 1
    yield 2

print(sorted(unsorted()))

# 16. tuple() of generator
print(tuple(gen3()))

# 17. any()/all() of generator
def bools():
    yield False
    yield True
    yield False

print(any(bools()))
print(all(bools()))

# 18. set() of generator
def dups():
    yield 1
    yield 2
    yield 1

print(sorted(set(dups())))

# 19. str.join() of string generator
print(",".join(greet()))

# 20. zip() with generator and list
print(list(zip(gen3(), [10, 20, 30])))
