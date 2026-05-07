# global keyword in nested scopes

x = 10

def modify_global():
    global x
    x = 20

modify_global()
print(x)  # 20

# Global inside nested function
counter = 0

def outer():
    def inner():
        global counter
        counter += 1
    inner()
    inner()

outer()
print(counter)  # 2

# Global declared but not yet assigned at module level
def set_new_global():
    global new_var
    new_var = 42

set_new_global()
print(new_var)  # 42

# Multiple globals
a = 1
b = 2

def swap_globals():
    global a, b
    a, b = b, a

swap_globals()
print(a)  # 2
print(b)  # 1

# Global in conditional
flag = False

def set_flag():
    global flag
    if True:
        flag = True

set_flag()
print(flag)  # True
