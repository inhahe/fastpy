# Test: generator as filter/map
def evens(n):
    for i in range(n):
        if i % 2 == 0:
            yield i

def squares(n):
    for i in range(n):
        yield i * i

print(list(evens(10)))
print(list(squares(5)))
print(sum(squares(10)))
