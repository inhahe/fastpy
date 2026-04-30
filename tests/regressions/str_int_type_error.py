# Bug #112: str + int and str + float silently succeeded instead of TypeError
# In Python, "hello" + 5 and "hello" + 1.5 are always TypeError.
# The compiler was silently converting: str+int → str_concat(s, int_to_str(i))
# and str+float fell through to float arithmetic (treating the string pointer
# as a number). Both are wrong.

# str + int should be TypeError
try:
    result = "hello" + 5
    print("BUG: should have raised TypeError")
except TypeError:
    print("caught str+int TypeError")

# int + str should be TypeError
try:
    result = 5 + "hello"
    print("BUG: should have raised TypeError")
except TypeError:
    print("caught int+str TypeError")

# str + float should be TypeError
try:
    result = "hello" + 1.5
    print("BUG: should have raised TypeError")
except TypeError:
    print("caught str+float TypeError")

# float + str should be TypeError
try:
    result = 1.5 + "hello"
    print("BUG: should have raised TypeError")
except TypeError:
    print("caught float+str TypeError")

# str * float should be TypeError (only str * int is valid)
try:
    result = "hello" * 1.5
    print("BUG: should have raised TypeError")
except TypeError:
    print("caught str*float TypeError")

# list + float should be TypeError
try:
    result = [1, 2] + 1.5
    print("BUG: should have raised TypeError")
except TypeError:
    print("caught list+float TypeError")

# Valid operations should still work
print("hello" + " world")
print("ha" * 3)
print(1 + 2.5)
print(True + 1.5)

print("all type error tests passed")
