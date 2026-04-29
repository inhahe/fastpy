# Regression: nested dict access with per-key types

# Mixed-type dict with nested dict value
config = {
    "database": {"host": "localhost", "port": 5432},
    "debug": True
}
print(config["database"]["host"])
print(config["database"]["port"])

# Assign intermediate, then access
db = config["database"]
print(db["host"])

# Simple nested
d = {"inner": {"x": 10, "y": 20}}
print(d["inner"]["x"])
print(d["inner"]["y"])
