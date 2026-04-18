# Regression: nested dict subscript failed when dicts were built via function
# Before fix: _dict_var_dict_values was only populated during codegen from
# direct subscript stores (d[k] = {}). When a function's dict parameter
# received dict values (d[k] = {} inside the function body), this knowledge
# didn't propagate to the call site. Module-level code reading data["user"]["name"]
# didn't know data held dict values, so _emit_subscript used fv_str (string
# representation) for the intermediate result, then tried str_index on it.
# Fix: (1) _analyze_call_sites detects d[k] = {} patterns in function bodies
# and refines var_types to "dict:dict" at the call site.
# (2) Module-level dict value types from var_types populate _dict_var_dict_values
# so nested subscripts work at module level too.

# Case 1: function builds nested dicts on its dict parameter
def update_nested(d, key1, key2, val):
    if key1 not in d:
        d[key1] = {}
    d[key1][key2] = val

data = {}
update_nested(data, "user", "name", "Alice")
update_nested(data, "user", "age", "30")
update_nested(data, "settings", "theme", "dark")
print(data["user"]["name"])
print(data["user"]["age"])
print(data["settings"]["theme"])

# Case 2: module-level nested dict passed to function for reading
config = {}
config["db"] = {}
config["db"]["host"] = "localhost"
config["db"]["port"] = "5432"

def read_config(cfg):
    return cfg["db"]["host"]

print(read_config(config))
print(config["db"]["port"])

# Case 3: triple-nested dict (recursive _is_dict_expr check)
deep = {}
deep["a"] = {}
deep["a"]["b"] = {}
deep["a"]["b"]["c"] = "found"
print(deep["a"]["b"]["c"])
