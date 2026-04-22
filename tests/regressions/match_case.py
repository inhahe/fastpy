# Regression tests for match/case structural pattern matching

# Test: literal integer patterns
def classify_int(x):
    match x:
        case 0:
            return "zero"
        case 1:
            return "one"
        case 2:
            return "two"
        case _:
            return "other"

print(classify_int(0))    # zero
print(classify_int(1))    # one
print(classify_int(2))    # two
print(classify_int(99))   # other

# Test: literal string patterns
def classify_str(s):
    match s:
        case "hello":
            return "greeting"
        case "bye":
            return "farewell"
        case _:
            return "unknown"

print(classify_str("hello"))  # greeting
print(classify_str("bye"))    # farewell
print(classify_str("what"))   # unknown

# Test: capture pattern (bind to variable)
def capture(x):
    match x:
        case val:
            return val * 2

print(capture(5))     # 10
print(capture(100))   # 200

# Test: wildcard pattern
def wildcard(x):
    match x:
        case 42:
            return "found it"
        case _:
            return "nope"

print(wildcard(42))   # found it
print(wildcard(7))    # nope

# Test: or patterns
def classify_or(x):
    match x:
        case 1 | 2 | 3:
            return "small"
        case 4 | 5 | 6:
            return "medium"
        case _:
            return "large"

print(classify_or(1))    # small
print(classify_or(3))    # small
print(classify_or(5))    # medium
print(classify_or(100))  # large

# Test: guard clauses
def classify_guard(x):
    match x:
        case n if n < 0:
            return "negative"
        case n if n == 0:
            return "zero"
        case n if n > 0:
            return "positive"

print(classify_guard(-5))   # negative
print(classify_guard(0))    # zero
print(classify_guard(10))   # positive

# Test: sequence patterns (tuple unpacking)
def process_pair(pair):
    match pair:
        case (0, y):
            return "x is zero, y=" + str(y)
        case (x, 0):
            return "y is zero, x=" + str(x)
        case (x, y):
            return "x=" + str(x) + " y=" + str(y)

print(process_pair((0, 5)))    # x is zero, y=5
print(process_pair((3, 0)))    # y is zero, x=3
print(process_pair((2, 7)))    # x=2 y=7

# Test: nested match
def nested_match(data):
    match data:
        case (1, (2, 3)):
            return "exact"
        case (1, (a, b)):
            return "partial " + str(a) + " " + str(b)
        case _:
            return "no match"

print(nested_match((1, (2, 3))))   # exact
print(nested_match((1, (4, 5))))   # partial 4 5
print(nested_match((9, 9)))        # no match

# Test: match with multiple statements in case body
def multi_body(x):
    match x:
        case 1:
            a = 10
            b = 20
            return a + b
        case 2:
            return 42
        case _:
            return -1

print(multi_body(1))   # 30
print(multi_body(2))   # 42
print(multi_body(3))   # -1

# Test: match used as a statement (no return)
results = []
for item in [1, 2, 3, 4, 5]:
    match item:
        case 1 | 3 | 5:
            results.append("odd")
        case 2 | 4:
            results.append("even")
print(results)  # ['odd', 'even', 'odd', 'even', 'odd']
