# Regression: function returning None on some paths lost the None tag
# Before fix: _emit_user_call unwrapped the FpyValue return to a bare i64
# based on the static return type ("int"), so return-None became i64(0) tagged
# as INT.  print(r) showed "0" instead of "None", and `r is None` was resolved
# as False at compile time because the variable's static tag was "int".
# Fix: (1) _emit_assign stores the raw FpyValue from FV-ABI calls directly
# (skipping the unwrap/re-wrap that loses the runtime tag).
# (2) _store_variable accepts FpyValue values and stores them without re-wrapping.
# (3) `is None` / `is not None` for FV-backed variables now compares the
# runtime tag with FPY_TAG_NONE instead of using the static type tag.

def maybe_return(flag):
    if flag:
        return 42
    return None

r1 = maybe_return(True)
r2 = maybe_return(False)
print(r1)
print(r2)
print(r1 is None)
print(r2 is None)
print(r1 is not None)
print(r2 is not None)

# Function that only returns None
def do_nothing():
    return None

x = do_nothing()
print(x)
print(x is None)
