# Test: try/except around next() without generator
it = iter("hi")
done = False
while not done:
    try:
        c = next(it)
    except StopIteration:
        done = True
    if not done:
        print(c)
