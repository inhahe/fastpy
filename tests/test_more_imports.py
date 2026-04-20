"""Test that common imports don't crash the compiler."""
import datetime
import platform
import secrets
import threading
import subprocess
import pickle
import csv
import signal
import gc
import inspect
import types
import weakref
import statistics
import numbers
import fractions
import atexit
import array

# platform.system() works natively
p = platform.system()
print(len(p) > 0)  # True

# secrets.randbelow works (uses random internally)
n = secrets.randbelow(100)
print(n >= 0 and n < 100)  # True

print("all imports OK!")
