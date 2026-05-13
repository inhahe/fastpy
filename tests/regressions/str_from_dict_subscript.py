# Regression: string value from dict subscript, appended to list,
# then compared. Tests that prescan detects all-string-value dicts
# and propagates str type through variable assignment and list append.

def check():
    d = {"a": "hello", "b": "world"}
    val = d["a"]

    lst = []
    lst.append(val)

    print(lst[-1] == "hello")  # True
    print(lst[-1])             # hello
    print(lst[0] == "hello")   # True

check()

# Also test direct subscript append (no intermediate variable)
def check2():
    mapping = {"x": "yes", "y": "no"}
    results = []
    for k in mapping:
        results.append(mapping[k])
    print(results)

check2()
