# Regression: nested dict subscript store (d["a"]["x"] = value)
# Before fix: _emit_subscript_store didn't update _dict_var_dict_values when
# storing a dict value via subscript (d["a"] = {}), so d["a"] wasn't recognized
# as a dict for subsequent nested access.  Also, _bare_to_tag_data didn't use
# value_node to detect bool constants (emitted as i64, not i32), causing bools
# stored in nested dicts to be tagged as INT and printed as 0/1.
# Fix: (1) Track dict value types through subscript assignments in _emit_assign.
# (2) Pass value_node to _bare_to_tag_data in _emit_subscript_store.
# (3) Check value_node for bool constants/variables in _bare_to_tag_data.

# Basic nested dict with string values
config = {}
config["db"] = {}
config["db"]["host"] = "localhost"
config["db"]["port"] = 5432
config["app"] = {}
config["app"]["debug"] = True
config["app"]["name"] = "myapp"

print(config["db"]["host"])
print(config["db"]["port"])
print(config["app"]["debug"])
print(config["app"]["name"])

# Nested dict with list values
data = {}
data["users"] = {}
data["users"]["alice"] = "admin"
data["users"]["bob"] = "viewer"
print(data["users"]["alice"])
print(data["users"]["bob"])
