# Regression: fn.__name__ on function parameters and aliases
# Previously crashed (segfault) because the compiler tried obj_get_fv
# on a raw function pointer which is not an FpyObj.

# Direct function __name__
def hello():
    pass

print(hello.__name__)

# Function alias __name__
fn = hello
print(fn.__name__)

# Parameter __name__ (single call site → alias resolves)
def show_name(f):
    print(f.__name__)

show_name(hello)
