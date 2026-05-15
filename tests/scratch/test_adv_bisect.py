# Test: count = count + 1 in closure with constant init
def make_counter():
    count = 0
    def increment():
        nonlocal count
        count = count + 1
        return count
    return increment

c = make_counter()
print(c())
