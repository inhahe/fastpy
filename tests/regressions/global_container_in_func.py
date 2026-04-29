# Regression: global containers (set/dict/list) accessed inside functions.
# _infer_type_tag, _is_dict_expr, _is_set_expr, _is_tuple_expr
# didn't check _global_vars; global set/tuple vars were declared as i64
# instead of i8_ptr, losing type info and causing segfaults.

# Global set
valid_names = {"alice", "bob", "charlie"}

def check_set():
    x = "bob"
    print(x in valid_names)       # True
    print("dave" in valid_names)  # False

check_set()

# Global dict with string variable key
config = {"host": "localhost", "port": 8080}

def read_config():
    key = "host"
    print(key in config)         # True
    print("missing" in config)   # False

read_config()

# Global list
numbers = [10, 20, 30]

def sum_numbers():
    total = 0
    for n in numbers:
        total += n
    return total

print(sum_numbers())  # 60

# Global list 'in' check from function
names = ["alice", "bob"]

def check_list():
    n = "bob"
    print(n in names)             # True
    print("charlie" in names)     # False

check_list()
