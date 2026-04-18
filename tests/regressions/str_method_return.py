def to_upper(s):
    return s.upper()

def to_lower(s):
    return s.lower()

def stripped(s):
    return s.strip()

def replaced(s, a, b):
    return s.replace(a, b)

def greet(name, age):
    return f"{name} is {age}"

print(to_upper("hello"))
print(to_lower("HELLO"))
print(stripped("  spaces  "))
print(replaced("abc", "b", "X"))
print(greet("alice", 30))
print(greet("bob", 25))
