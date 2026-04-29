# *args should be a tuple, not a list (display format)
def show(*args):
    print(args)

show(1, 2, 3)

# *args with positional params
def mixed(a, *args):
    print(a, args)

mixed(10, 20, 30)

# *args and **kwargs together
def both(*args, **kwargs):
    print(args)
    print(kwargs)

both(1, 2, x=10, y=20)
