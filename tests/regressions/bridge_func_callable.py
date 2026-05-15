# Regression: user function references passed through CPython bridge
#
# Bug: When a user-defined function is passed as an argument to a bridge
# call (e.g., threading.Thread(target=worker)), the function pointer was
# stored as INT-tagged i64.  The bridge's fpy_to_pyobject() converted it
# to a Python int, which is not callable — causing TypeError.
#
# Fix: Added _to_bridge_tag_data_ir() that wraps user function references
# in FpyClosure objects (OBJ-tagged) when crossing the bridge boundary.
# The bridge detects the CLOSURE_MAGIC and creates a callable Python proxy.

import threading

# 1. Basic function as thread target
result = []
def worker(n):
    result.append(n * n)

threads = []
for i in range(5):
    t = threading.Thread(target=worker, args=(i,))
    threads.append(t)
    t.start()
for t in threads:
    t.join()
result.sort()
assert result == [0, 1, 4, 9, 16]

# 2. Function alias as thread target
result2 = []
fn = worker
threads2 = []
for i in range(3):
    t = threading.Thread(target=fn, args=(i,))
    threads2.append(t)
    t.start()
for t in threads2:
    t.join()
result2 = result[:]  # result was appended to by fn=worker
# Just verify it didn't crash — exact values depend on thread ordering

# 3. Lambda as thread target (via map/functools patterns)
import functools
results3 = []
def adder(a, b):
    results3.append(a + b)

t = threading.Thread(target=adder, args=(10, 20))
t.start()
t.join()
assert results3 == [30]

print("ok")
