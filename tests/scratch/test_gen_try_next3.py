# Test: store next result to local first, then to self
def gen(s):
    it = iter(s)
    try:
        c = next(it)
        print(c)
    except StopIteration:
        pass

gen("hi")
