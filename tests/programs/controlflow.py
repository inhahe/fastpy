# Control flow test program
# Tests if/elif/else, for, while, break, continue, nested loops

# if/elif/else
for x in [1, 5, 15]:
    if x > 10:
        print(f"{x}: big")
    elif x > 3:
        print(f"{x}: medium")
    else:
        print(f"{x}: small")

# for with range
total = 0
for i in range(10):
    total += i
print(f"sum 0..9 = {total}")

# for with list
fruits = ["apple", "banana", "cherry"]
for fruit in fruits:
    print(fruit)

# while
n = 1
while n < 100:
    n *= 2
print(f"first power of 2 >= 100: {n}")

# break
for i in range(100):
    if i * i > 50:
        print(f"first i where i^2 > 50: {i}")
        break

# continue
evens = []
for i in range(10):
    if i % 2 != 0:
        continue
    evens.append(i)
print(f"evens: {evens}")

# nested loops
for i in range(3):
    row = []
    for j in range(4):
        row.append(i * 4 + j)
    print(row)

# for/else
for i in range(5):
    if i == 10:  # never true
        break
else:
    print("loop completed normally")

# while/else
x = 0
while x < 3:
    x += 1
else:
    print(f"while completed, x = {x}")
