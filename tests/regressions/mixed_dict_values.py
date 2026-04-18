# Regression: mixed-value-type dicts with per-key type inference.
# Before fix: a dict literal with both int and str values made
# `d["age"]` fall through to `fv_str`, returning the string "30"
# instead of the int 30. `p["age"] >= 30` then compared i8* with i64.
#
# Fix: at literal-assignment time, build a {key: type_tag} map from
# each string-keyed entry. `_emit_subscript` consults the map before
# falling through. The map is also propagated through list-of-dicts
# iteration (list comp + for loop) so the loop variable's subscripts
# pick the right unwrap path.

# Direct case: mixed-value dict, int key access.
person = {"name": "alice", "age": 30}
print(person["name"])       # alice
print(person["age"])        # 30
print(person["age"] + 5)    # 35
print(person["age"] >= 30)  # True

# List comp filter over list-of-dicts: the target of Phase 20.
people = [
    {"name": "alice", "age": 30},
    {"name": "bob", "age": 25},
    {"name": "carol", "age": 40},
]
adults = [p for p in people if p["age"] >= 30]
print(len(adults))          # 2
for p in adults:
    print(p["name"], p["age"])
# alice 30
# carol 40

# For-loop variant: same source, explicit loop.
total_age = 0
for p in people:
    total_age = total_age + p["age"]
print(total_age)            # 95

# Extract mixed-type fields via separate comprehensions.
names = [p["name"] for p in people]
print(names)                # ['alice', 'bob', 'carol']

ages = [p["age"] for p in people]
print(ages)                 # [30, 25, 40]

# Three-type-mixed dict (int + str + float).
record = {"label": "widget", "count": 7, "ratio": 0.5}
print(record["label"])      # widget
print(record["count"] + 1)  # 8
print(record["ratio"] * 2)  # 1.0

# Filter with int key vs string key check.
# `p["age"]` is int, so `p["age"] > 25` should be int vs int, not ptr.
young = [p for p in people if p["age"] < 30]
print(len(young))           # 1
for p in young:
    print(p["name"])
# bob

# Append-built list of dicts — exercises the empty-list + .append path.
built = []
built.append({"name": "dan", "age": 22})
built.append({"name": "eve", "age": 55})
for p in built:
    print(p["name"], p["age"])
# dan 22
# eve 55

# Mixed-type sum from append-built list.
total = 0
for p in built:
    total = total + p["age"]
print(total)                # 77
