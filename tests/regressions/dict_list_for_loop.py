# Regression: iterating over a list obtained from a dict value
# The loop variable must support runtime-dispatched subscript/method calls
# since the list's element type isn't statically known.

# Case 1: dict->list->dict via intermediate variable
data = {"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}
users = data["users"]
for user in users:
    print(user["name"], user["age"])

# Case 2: direct iteration over dict subscript
config = {"items": [{"key": "host", "value": "localhost"}, {"key": "port", "value": "8080"}]}
for item in config["items"]:
    print(item["key"], item["value"])

# Case 3: mixed value types in dict-derived list
mixed = {"stuff": [1, "hello", 3.14, True]}
things = mixed["stuff"]
for x in things:
    print(x)

# Case 4: int-only list from dict
scores = {"math": [90, 85, 92]}
for s in scores["math"]:
    print(s)

# Case 5: string-only list from dict
words = {"greetings": ["hello", "hi", "hey"]}
for w in words["greetings"]:
    print(w)

# Verify normal iteration unaffected
nums = [10, 20, 30]
total = 0
for n in nums:
    total = total + n
print(total)
