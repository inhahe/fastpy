# Test chained exception handling patterns

# Multiple except clauses
def multi_except(val):
    try:
        if val == 0:
            raise ZeroDivisionError("zero")
        elif val < 0:
            raise ValueError("negative")
        else:
            return val * 2
    except ZeroDivisionError as e:
        return "zdiv: " + str(e)
    except ValueError as e:
        return "val: " + str(e)

print(multi_except(0))    # zdiv: zero
print(multi_except(-1))   # val: negative
print(multi_except(5))    # 10

# try/except/else
def try_else(lst, idx):
    try:
        val = lst[idx]
    except IndexError:
        return "out of range"
    else:
        return "got: " + str(val)

print(try_else([10, 20, 30], 1))   # got: 20
print(try_else([10, 20, 30], 5))   # out of range

# try/except/finally
def try_finally(x):
    try:
        result = 10 // x
    except ZeroDivisionError:
        result = -1
    finally:
        print("finally")
    return result

print(try_finally(2))   # finally\n5
print(try_finally(0))   # finally\n-1

# Re-raise with bare raise
def reraise(x):
    try:
        if x < 0:
            raise ValueError("bad value")
        return x
    except ValueError:
        raise

try:
    reraise(-3)
except ValueError as e:
    print("reraised:", e)  # reraised: bad value

print(reraise(7))  # 7
