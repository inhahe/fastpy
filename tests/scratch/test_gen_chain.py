# Test: chained generators
def count_up(start, n):
    for i in range(n):
        yield start + i

def chain(*iterables):
    for it in iterables:
        for x in it:
            yield x

# Test chain of generators (needs yield from or manual iteration)
g1 = count_up(1, 3)
g2 = count_up(10, 3)
result = list(g1) + list(g2)
print(result)
