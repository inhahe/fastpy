# Regression: nested dict/list value access from unknown-type dict
# Tests that dict subscript on dynamic dicts (json.loads) and mixed-value
# literal dicts correctly dispatches through runtime FpyValue tags.

import json

# 1. json.loads: nested dict access
data = json.loads('{"name": "Alice", "age": 30, "scores": [90, 85, 92], "address": {"city": "NYC"}}')
print(data["name"])        # Alice
print(data["age"])         # 30

# Nested list access
scores = data["scores"]
print(scores)              # [90, 85, 92]
print(len(scores))         # 3
print(scores[0])           # 90

# Nested dict access
addr = data["address"]
print(addr)                # {'city': 'NYC'}
print(addr["city"])        # NYC

# 2. Literal dict with mixed value types
d = {"name": "Bob", "count": 42, "items": [1, 2, 3], "meta": {"key": "val"}}
name = d["name"]
print(name)                # Bob

items = d["items"]
print(items)               # [1, 2, 3]
print(len(items))          # 3

meta = d["meta"]
print(meta)                # {'key': 'val'}
print(meta["key"])         # val

# 3. Double nesting
nested = json.loads('{"a": {"b": {"c": "deep"}}}')
inner = nested["a"]
print(inner["b"])          # {'c': 'deep'}
