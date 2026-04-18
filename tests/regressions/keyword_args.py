# Regression: keyword arguments for functions, constructors, and methods.
#
# Before fix: `func(arg=value)` was silently ignored — the compiler
# would use the default value instead of the keyword value.
# Also bool-default params were tagged as int, printing True/False as 1/0.
#
# Fix: _emit_user_call, _emit_user_call_fv, _emit_constructor, and
# _emit_method_call all resolve keywords to positional slots using the
# target's AST. _detect_class_bool_attrs and _emit_method_body now check
# bool defaults.

# Function keyword args
def greet(name, greeting="Hello"):
    return greeting + ", " + name

print(greet("World"))
print(greet("World", "Hi"))
print(greet("World", greeting="Hey"))

# Multiple kwargs, mixed with positional
def config(name, age=0, city="unknown"):
    return name + "," + str(age) + "," + city

print(config("alice"))
print(config("bob", age=25))
print(config("charlie", city="boston"))
print(config("dave", age=30, city="nyc"))

# Class constructor kwargs
class Settings:
    def __init__(self, name="default", value=42, enabled=True):
        self.name = name
        self.value = value
        self.enabled = enabled

s1 = Settings()
print(s1.name, s1.value, s1.enabled)

s2 = Settings("custom")
print(s2.name, s2.value, s2.enabled)

s3 = Settings(value=100)
print(s3.name, s3.value, s3.enabled)

s4 = Settings(enabled=False)
print(s4.name, s4.value, s4.enabled)

s5 = Settings("special", enabled=False, value=999)
print(s5.name, s5.value, s5.enabled)

# Method kwargs
class Greeter:
    def __init__(self, name):
        self.name = name

    def say(self, greeting="Hi"):
        return greeting + ", " + self.name

g = Greeter("Alice")
print(g.say())
print(g.say("Hello"))
print(g.say(greeting="Hey"))

# Kwargs through nested method call
class Inner:
    def calc(self, x, factor=2):
        return x * factor

class Outer:
    def __init__(self):
        self.inner = Inner()

    def compute(self, val):
        return self.inner.calc(val, factor=5)

o = Outer()
print(o.compute(10))
