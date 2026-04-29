# Function definition inside a for loop
for i in range(3):
    def greet(n):
        return n * 2
    print(greet(i))

# Lambda capturing function parameter
def make(n):
    return lambda: n

results = []
for i in range(5):
    results.append(make(i))

for f in results:
    print(f())
