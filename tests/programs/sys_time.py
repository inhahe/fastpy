"""Test sys and time module support."""
import sys
import time

# sys.platform
platform = sys.platform
print(platform)       # "win32" on Windows

# sys.maxsize
print(sys.maxsize > 0)  # True

# time.time() — returns a float
t1 = time.time()
print(t1 > 0.0)      # True

# time.perf_counter() — high-resolution timer
pc1 = time.perf_counter()
print(pc1 > 0.0)     # True

# time.sleep()
time.sleep(0.01)  # 10ms sleep

# Verify time elapsed
pc2 = time.perf_counter()
elapsed = pc2 - pc1
print(elapsed > 0.005)  # True (at least 5ms elapsed)

# sys.exit is available (but we won't call it to avoid terminating the test)

print("sys/time tests passed!")
