# Regression: augmented assignment on object attributes
# Bug 1: self.attr += val inside methods stored the raw RHS instead of
#   the computed result because _emit_attr_store's FV-locals fast path
#   hijacked the store when value_node was an ast.Name with FpyValue alloca.
# Bug 2: list_attr += list was treated as string concatenation because
#   the STR += fallback (isinstance(rhs.type, ir.PointerType)) fired
#   before the LIST += check.
# self.attr += val for int, float, string, list, and OBJ dunders

class Counter:
    def __init__(self, n):
        self.count = n

# 1. Integer attributes
c = Counter(10)
c.count += 5
print(c.count)   # 15
c.count -= 3
print(c.count)   # 12
c.count *= 2
print(c.count)   # 24
c.count //= 5
print(c.count)   # 4

# 2. Float attributes
class Point:
    def __init__(self, x):
        self.x = x

p = Point(1.5)
p.x += 2.5
print(p.x)   # 4.0
p.x *= 3.0
print(p.x)   # 12.0
p.x -= 2.0
print(p.x)   # 10.0

# 3. String attributes
class Person:
    def __init__(self, name):
        self.name = name

p = Person("Alice")
p.name += " Smith"
print(p.name)   # Alice Smith

# 4. Multiple augmented assigns in sequence
c2 = Counter(0)
for i in range(5):
    c2.count += 1
print(c2.count)   # 5

# 5. Augmented assignment INSIDE a method (regression: FV-locals fast
#    path stored the raw RHS parameter instead of the computed result)
class BankAccount:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance

    def deposit(self, amount):
        self.balance += amount
        return self.balance

    def withdraw(self, amount):
        if amount > self.balance:
            return -1
        self.balance -= amount
        return self.balance

acc = BankAccount("Alice", 100)
print(acc.deposit(50))   # 150
print(acc.deposit(25))   # 175
print(acc.withdraw(30))  # 145
print(acc.withdraw(200)) # -1
print(acc.balance)       # 145

# 6. Augmented assignment in a loop inside a method
class Accumulator:
    def __init__(self):
        self.total = 0

    def add_all(self, items):
        for x in items:
            self.total += x

a = Accumulator()
a.add_all([10, 20, 30, 40])
print(a.total)  # 100

# 7. List attribute += (regression: STR += path stole list concat)
class Holder:
    def __init__(self):
        self.items = [1, 2]

    def extend(self, more):
        self.items += more

h = Holder()
h.items += [3, 4]
print(h.items)       # [1, 2, 3, 4]
h.extend([5, 6])
print(h.items)       # [1, 2, 3, 4, 5, 6]
print(len(h.items))  # 6
