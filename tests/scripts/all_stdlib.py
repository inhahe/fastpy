"""
Comprehensive stdlib module test suite.

Tests every importable stdlib module through the fastpy differential test
harness. For each module, creates a small program that imports and exercises
it, then compares output between CPython and the compiled fastpy binary.

Results: PASS (output matches), SKIP (compiler can't handle it), FAIL (wrong output)
"""

import sys
import os
import time

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.harness import diff_test


# ── Test snippets for C/bridge modules ──────────────────────────────

BRIDGE_TESTS = {
    # --- Built-in C modules ---
    "math": """
import math
print(math.sqrt(144))
print(math.pi)
print(math.floor(3.7))
print(math.ceil(3.2))
print(math.gcd(48, 18))
print(math.factorial(6))
""",

    "time": """
import time
t = time.time()
print(type(t).__name__)
print(time.monotonic() > 0)
""",

    "errno": """
import errno
print(errno.ENOENT)
print(errno.EACCES)
""",

    "binascii": """
import binascii
data = bytes([72, 101, 108, 108, 111])
h = binascii.hexlify(data)
print(h)
print(binascii.unhexlify(b"48656c6c6f"))
""",

    "zlib": """
import zlib
data = bytes([72, 101, 108, 108, 111, 32, 87, 111, 114, 108, 100])
c = zlib.compress(data)
d = zlib.decompress(c)
print(d)
print(zlib.crc32(data))
""",

    "cmath": """
import cmath
print(cmath.sqrt(-1))
print(cmath.phase(complex(1, 1)))
""",

    "itertools": """
import itertools
print(list(itertools.chain([1, 2], [3, 4])))
print(list(itertools.repeat("x", 3)))
print(list(itertools.islice(range(100), 5)))
print(list(itertools.combinations([1, 2, 3], 2)))
""",

    "array": """
import array
a = array.array("i", [1, 2, 3, 4, 5])
print(len(a))
print(a[2])
a.append(6)
print(len(a))
""",

    "select": """
import select
print(hasattr(select, "select"))
""",

    "unicodedata": """
import unicodedata
print(unicodedata.name("A"))
print(unicodedata.numeric("5"))
""",

    "gc_mod": """
import gc
gc.collect()
print("gc ok")
""",

    "mmap_mod": """
import mmap
print(hasattr(mmap, "mmap"))
print(mmap.PAGESIZE > 0)
""",

    # --- C modules via underscore prefix ---
    "_collections": """
import _collections
d = _collections.deque([1, 2, 3])
d.append(4)
d.appendleft(0)
print(list(d))
""",

    "_functools": """
import _functools
print(_functools.reduce(lambda a, b: a + b, [1, 2, 3, 4, 5]))
""",

    "_operator": """
import _operator
print(_operator.add(3, 4))
print(_operator.mul(5, 6))
print(_operator.neg(7))
""",

    "_struct": """
import _struct
packed = _struct.pack(">I", 12345)
print(len(packed))
val = _struct.unpack(">I", packed)
print(val[0])
""",

    "_string": """
import _string
parts = list(_string.formatter_field_name_split("name.attr"))
print(parts[0])
""",

    "_heapq": """
import _heapq
h = [5, 3, 8, 1, 9, 2]
_heapq.heapify(h)
print(h[0])
_heapq.heappush(h, 0)
print(h[0])
print(_heapq.heappop(h))
""",

    "_bisect": """
import _bisect
a = [1, 3, 5, 7, 9]
print(_bisect.bisect_left(a, 4))
print(_bisect.bisect_right(a, 5))
""",

    "_csv": """
import _csv
# Basic CSV writer test
print(hasattr(_csv, "reader"))
print(_csv.QUOTE_ALL)
""",

    "_json": """
import _json
# _json is the C accelerator for json
print(hasattr(_json, "encode_basestring"))
""",

    "_datetime": """
import _datetime
d = _datetime.date(2026, 4, 22)
print(d.year)
print(d.month)
print(d.day)
""",

    "_hashlib": """
import _hashlib
h = _hashlib.openssl_md5(bytes([104, 101, 108, 108, 111]))
print(h.hexdigest())
""",

    "_random": """
import _random
r = _random.Random()
r.seed(42)
print(type(r.random()).__name__)
""",

    "_io": """
import _io
buf = _io.BytesIO()
buf.write(bytes([72, 101, 108, 108, 111]))
print(buf.getvalue())
""",

    "_signal": """
import _signal
print(_signal.SIGTERM)
print(hasattr(_signal, "signal"))
""",

    "_locale": """
import _locale
print(hasattr(_locale, "setlocale"))
""",

    "_contextvars": """
import _contextvars
v = _contextvars.ContextVar("test_var", default=42)
print(v.get())
""",

    "_statistics": """
import _statistics
print(hasattr(_statistics, "_normal_dist_inv_cdf"))
""",

    "_tracemalloc": """
import _tracemalloc
print(hasattr(_tracemalloc, "start"))
""",

    "_socket": """
import _socket
print(_socket.AF_INET)
print(hasattr(_socket, "socket"))
""",

    "_decimal": """
import _decimal
a = _decimal.Decimal("1.23")
b = _decimal.Decimal("4.56")
print(a + b)
print(a * b)
""",

    "pyexpat": """
import pyexpat
print(hasattr(pyexpat, "ParserCreate"))
print(pyexpat.version_info[0] > 0)
""",

    "_abc": """
import _abc
token = _abc.get_cache_token()
print(type(token).__name__)
print(token >= 0)
""",

    "_typing": """
import _typing
tv = _typing.TypeVar('T')
print(tv.__name__)
print(type(tv).__name__)
ps = _typing.ParamSpec('P')
print(ps.__name__)
""",

    "_warnings": """
import _warnings
print(type(_warnings.filters).__name__)
print(len(_warnings.filters) > 0)
_warnings.warn('hello')
print('warn done')
print(hasattr(_warnings, 'warn_explicit'))
""",

    "_uuid": """
import _uuid
print(hasattr(_uuid, 'UuidCreate'))
print(_uuid.has_uuid_generate_time_safe)
""",

    "_asyncio": """
import _asyncio
print(hasattr(_asyncio, 'Future'))
print(hasattr(_asyncio, 'Task'))
print(hasattr(_asyncio, 'get_running_loop'))
""",
}


# ── Test snippets for pure Python modules ──────────────────────────

PYTHON_TESTS = {
    "abc": """
import abc
class MyABC(abc.ABC):
    pass
print("abc ok")
""",

    "base64": """
import base64
encoded = base64.b64encode(bytes([72, 101, 108, 108, 111]))
print(encoded)
decoded = base64.b64decode(encoded)
print(decoded)
""",

    "bisect": """
import bisect
a = [1, 3, 5, 7, 9]
print(bisect.bisect_left(a, 4))
bisect.insort(a, 4)
print(a)
""",

    "calendar": """
import calendar
print(calendar.isleap(2024))
print(calendar.isleap(2023))
print(calendar.monthrange(2026, 4))
""",

    "colorsys": """
import colorsys
r, g, b = colorsys.hsv_to_rgb(0.5, 0.5, 0.5)
print(round(r, 4))
print(round(g, 4))
print(round(b, 4))
""",

    "copy": """
import copy
a = [1, [2, 3], 4]
b = copy.copy(a)
c = copy.deepcopy(a)
b[1].append(5)
print(a)
print(c)
""",

    "csv": """
import csv
import _io
buf = _io.StringIO()
w = csv.writer(buf)
w.writerow(["name", "age"])
w.writerow(["Alice", 30])
print(buf.getvalue())
""",

    "contextlib": """
import contextlib
print(hasattr(contextlib, "contextmanager"))
print(hasattr(contextlib, "suppress"))
""",

    "dataclasses": """
import dataclasses
print(hasattr(dataclasses, "dataclass"))
print(hasattr(dataclasses, "field"))
""",

    "datetime": """
import datetime
d = datetime.date(2026, 4, 22)
print(d.year)
print(d.month)
print(d.day)
t = datetime.timedelta(days=5)
d2 = d + t
print(d2.day)
""",

    "decimal_mod": """
import decimal
a = decimal.Decimal("1.1")
b = decimal.Decimal("2.2")
print(a + b)
""",

    "difflib": """
import difflib
s1 = "abcde"
s2 = "abfde"
m = difflib.SequenceMatcher(None, s1, s2)
print(round(m.ratio(), 2))
""",

    "enum_mod": """
import enum
class Color(enum.Enum):
    RED = 1
    GREEN = 2
    BLUE = 3
print(Color.RED.value)
print(Color.GREEN.name)
""",

    "fnmatch": """
import fnmatch
print(fnmatch.fnmatch("hello.py", "*.py"))
print(fnmatch.fnmatch("hello.txt", "*.py"))
print(fnmatch.filter(["a.py", "b.txt", "c.py"], "*.py"))
""",

    "fractions": """
import fractions
f = fractions.Fraction(1, 3)
g = fractions.Fraction(1, 6)
print(f + g)
print(f * g)
""",

    "functools": """
import functools
print(functools.reduce(lambda a, b: a + b, [1, 2, 3, 4, 5]))
""",

    "getopt": """
import getopt
opts, args = getopt.getopt(["-a", "-b", "val", "arg1"], "ab:")
print(opts)
print(args)
""",

    "glob_mod": """
import glob
print(type(glob.glob("*.nonexistent_extension_xyz")))
""",

    "graphlib": """
import graphlib
ts = graphlib.TopologicalSorter()
ts.add("B", "A")
ts.add("C", "A", "B")
ts.prepare()
result = []
while ts.is_active():
    nodes = ts.get_ready()
    result.extend(sorted(nodes))
    for n in nodes:
        ts.done(n)
print(result)
""",

    "gzip": """
import gzip
data = bytes([72, 101, 108, 108, 111])
c = gzip.compress(data)
d = gzip.decompress(c)
print(d)
""",

    "hashlib": """
import hashlib
h = hashlib.md5(bytes([104, 101, 108, 108, 111]))
print(h.hexdigest())
h2 = hashlib.sha256(bytes([104, 101, 108, 108, 111]))
print(h2.hexdigest())
""",

    "heapq": """
import heapq
h = [5, 3, 8, 1, 9, 2]
heapq.heapify(h)
print(heapq.heappop(h))
print(heapq.heappop(h))
heapq.heappush(h, 0)
print(heapq.heappop(h))
""",

    "hmac_mod": """
import hmac
h = hmac.new(bytes([115, 101, 99, 114, 101, 116]),
             bytes([109, 115, 103]),
             "md5")
print(h.hexdigest())
""",

    "ipaddress": """
import ipaddress
addr = ipaddress.ip_address("192.168.1.1")
print(addr)
net = ipaddress.ip_network("10.0.0.0/8")
print(net.num_addresses)
""",

    "json": """
import json
d = {"name": "Alice", "age": 30}
s = json.dumps(d)
print(s)
d2 = json.loads(s)
print(d2["name"])
print(d2["age"])
""",

    "keyword": """
import keyword
print(keyword.iskeyword("if"))
print(keyword.iskeyword("hello"))
""",

    "locale_mod": """
import locale
print(hasattr(locale, "getlocale"))
""",

    "numbers": """
import numbers
print(isinstance(42, numbers.Number))
print(isinstance(3.14, numbers.Real))
""",

    "operator": """
import operator
print(operator.add(3, 4))
print(operator.mul(5, 6))
print(operator.neg(7))
""",

    "os_mod": """
import os
print(os.getcwd() != "")
print(os.getpid() > 0)
print(os.sep)
""",

    "pickle": """
import pickle
data = [1, 2, 3, "hello"]
p = pickle.dumps(data)
d = pickle.loads(p)
print(d)
""",

    "platform": """
import platform
print(platform.system())
print(len(platform.python_version()) > 0)
""",

    "pprint_mod": """
import pprint
s = pprint.pformat([1, 2, 3])
print(s)
""",

    "queue_mod": """
import queue
q = queue.Queue()
q.put(1)
q.put(2)
q.put(3)
print(q.get())
print(q.get())
print(q.qsize())
""",

    "random": """
import random
random.seed(42)
print(type(random.random()).__name__)
print(random.randint(1, 10) > 0)
nums = [1, 2, 3, 4, 5]
random.shuffle(nums)
print(len(nums))
""",

    "re": r"""
import re
m = re.match(r"(\w+) (\w+)", "Hello World")
print(m.group(1))
print(m.group(2))
print(re.findall(r"\d+", "abc 123 def 456"))
""",

    "reprlib": """
import reprlib
r = reprlib.Repr()
print(r.repr(list(range(100))))
""",

    "secrets": """
import secrets
t = secrets.token_hex(4)
print(len(t))
print(type(t).__name__)
""",

    "shelve": """
import shelve
import tempfile
import os
path = tempfile.mktemp(suffix=".db")
try:
    with shelve.open(path) as db:
        db["key"] = "value"
    with shelve.open(path) as db:
        print(db["key"])
finally:
    for ext in ["", ".dir", ".bak", ".dat"]:
        try:
            os.remove(path + ext)
        except:
            pass
""",

    "shlex": """
import shlex
print(shlex.split("echo 'hello world' --flag"))
""",

    "shutil": """
import shutil
print(hasattr(shutil, "copy"))
print(hasattr(shutil, "rmtree"))
""",

    "signal": """
import signal
print(signal.SIGTERM)
print(hasattr(signal, "signal"))
""",

    "socket": """
import socket
print(socket.AF_INET)
print(hasattr(socket, "socket"))
""",

    "stat": """
import stat
print(stat.S_ISDIR(0o40755))
print(stat.S_ISREG(0o100644))
""",

    "statistics": """
import statistics
print(statistics.mean([1, 2, 3, 4, 5]))
print(statistics.median([1, 2, 3, 4, 5]))
print(statistics.stdev([1, 2, 3, 4, 5]))
""",

    "string": """
import string
print(string.ascii_lowercase)
print(string.digits)
print(string.punctuation)
""",

    "struct": """
import struct
packed = struct.pack(">I", 12345)
print(len(packed))
val = struct.unpack(">I", packed)
print(val[0])
""",

    "textwrap": """
import textwrap
text = "This is a long line that should be wrapped to fit within a certain width limit."
wrapped = textwrap.fill(text, width=40)
print(wrapped)
""",

    "threading_mod": """
import threading
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
print(result)
""",

    "timeit_mod": """
import timeit
t = timeit.timeit("sum(range(100))", number=100)
print(t > 0)
""",

    "token": """
import token
print(token.NAME)
print(token.NUMBER)
""",

    "traceback_mod": """
import traceback
print(hasattr(traceback, "format_exc"))
print(hasattr(traceback, "print_exc"))
""",

    "types": """
import types
def f():
    pass
print(type(f) == types.FunctionType)
print(isinstance(lambda: None, types.LambdaType))
""",

    "typing_mod": """
import typing
print(hasattr(typing, "List"))
print(hasattr(typing, "Dict"))
print(hasattr(typing, "Optional"))
""",

    "uuid": """
import uuid
u = uuid.uuid4()
print(len(str(u)))
print(type(u).__name__)
""",

    "warnings_mod": """
import warnings
print(hasattr(warnings, "warn"))
print(hasattr(warnings, "filterwarnings"))
""",

    "wave": """
import wave
print(hasattr(wave, "open"))
""",

    "weakref": """
import weakref
class Foo:
    pass
f = Foo()
print(hasattr(weakref, "ref"))
""",

    "zipfile": """
import zipfile
print(hasattr(zipfile, "ZipFile"))
print(hasattr(zipfile, "is_zipfile"))
""",

    # ── Package modules ──
    "collections_pkg": """
import collections
c = collections.Counter("abracadabra")
print(c.most_common(3))
d = collections.OrderedDict()
d["b"] = 2
d["a"] = 1
print(list(d.keys()))
""",

    "logging_mod": """
import logging
logger = logging.getLogger("test")
print(hasattr(logger, "info"))
print(hasattr(logger, "error"))
""",

    "pathlib": """
import pathlib
p = pathlib.PurePosixPath("/usr/bin/python")
print(p.name)
print(p.parent)
print(p.suffix)
""",

    "html_mod": """
import html
print(html.escape("<b>Hello & World</b>"))
print(html.unescape("&lt;b&gt;Hello&lt;/b&gt;"))
""",

    "http_mod": """
import http
print(http.HTTPStatus.OK.value)
print(http.HTTPStatus.NOT_FOUND.value)
""",

    "urllib_mod": """
import urllib.parse
parsed = urllib.parse.urlparse("https://example.com/path?q=1")
print(parsed.scheme)
print(parsed.netloc)
print(parsed.path)
""",

    "xml_mod": """
import xml.etree.ElementTree as ET
root = ET.Element("root")
child = ET.SubElement(root, "child")
child.text = "Hello"
print(ET.tostring(root, encoding="unicode"))
""",

    "tomllib_mod": """
import tomllib
data = tomllib.loads('[section]\\nkey = "value"\\nnum = 42')
print(data["section"]["key"])
print(data["section"]["num"])
""",

    "asyncio_mod": """
import asyncio
async def hello():
    return 42
result = asyncio.run(hello())
print(result)
""",

    "sqlite3_mod": """
import sqlite3
conn = sqlite3.connect(":memory:")
c = conn.cursor()
c.execute("CREATE TABLE t (id INTEGER, name TEXT)")
c.execute("INSERT INTO t VALUES (1, 'Alice')")
c.execute("INSERT INTO t VALUES (2, 'Bob')")
c.execute("SELECT * FROM t ORDER BY id")
for row in c.fetchall():
    print(row)
conn.close()
""",

    "json_pkg": """
import json
d = {"x": 1, "y": [2, 3]}
s = json.dumps(d, sort_keys=True)
print(s)
d2 = json.loads(s)
print(d2["x"])
print(d2["y"])
""",

    "sysconfig_mod": """
import sysconfig
print(type(sysconfig.get_python_version()).__name__)
""",

    "unittest_mod": """
import unittest
print(hasattr(unittest, "TestCase"))
print(hasattr(unittest, "main"))
""",

    "argparse_mod": """
import argparse
parser = argparse.ArgumentParser(description="test")
parser.add_argument("--name", default="world")
args = parser.parse_args([])
print(args.name)
""",

    "tempfile_mod": """
import tempfile
import os
f = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
fname = f.name
f.write(bytes([72, 73]))
f.close()
print(os.path.exists(fname))
os.remove(fname)
""",

    "configparser_mod": """
import configparser
cp = configparser.ConfigParser()
cp.read_string("[section]\\nkey = value\\nnum = 42")
print(cp.get("section", "key"))
print(cp.getint("section", "num"))
""",

    "gettext_mod": """
import gettext
print(hasattr(gettext, "gettext"))
""",

    "mimetypes_mod": """
import mimetypes
print(mimetypes.guess_type("file.txt")[0])
print(mimetypes.guess_type("file.py")[0])
""",

    "netrc_mod": """
import netrc
print(hasattr(netrc, "netrc"))
""",

    "ssl_mod": """
import ssl
print(hasattr(ssl, "create_default_context"))
print(ssl.PROTOCOL_TLS_CLIENT > 0)
""",

    "selectors_mod": """
import selectors
print(hasattr(selectors, "DefaultSelector"))
""",

    "codecs_mod": """
import codecs
b = codecs.encode("hello", "utf-8")
print(b)
s = codecs.decode(b, "utf-8")
print(s)
""",

    "io_mod": """
import io
buf = io.StringIO()
buf.write("hello world")
print(buf.getvalue())
""",

    "inspect_mod": """
import inspect
def foo(a, b, c=3):
    pass
sig = inspect.signature(foo)
print(len(sig.parameters))
""",

    "filecmp_mod": """
import filecmp
print(hasattr(filecmp, "cmp"))
""",

    "compileall_mod": """
import compileall
print(hasattr(compileall, "compile_dir"))
""",

    "dis_mod": """
import dis
print(hasattr(dis, "dis"))
""",

    "ast_mod": """
import ast
tree = ast.parse("x = 1 + 2")
print(type(tree).__name__)
""",

    "plistlib_mod": """
import plistlib
print(hasattr(plistlib, "dumps"))
print(hasattr(plistlib, "loads"))
""",

    "quopri_mod": """
import quopri
print(hasattr(quopri, "encode"))
print(hasattr(quopri, "decode"))
""",

    "sched_mod": """
import sched
s = sched.scheduler()
print(s.empty())
""",

    "socketserver_mod": """
import socketserver
print(hasattr(socketserver, "TCPServer"))
print(hasattr(socketserver, "UDPServer"))
""",

    "tabnanny_mod": """
import tabnanny
print(hasattr(tabnanny, "check"))
""",

    "tarfile_mod": """
import tarfile
print(hasattr(tarfile, "open"))
print(hasattr(tarfile, "TarFile"))
""",

    "zipimport_mod": """
import zipimport
print(hasattr(zipimport, "zipimporter"))
""",

    "zoneinfo_mod": """
import zoneinfo
print(hasattr(zoneinfo, "ZoneInfo"))
""",

    "dbm_mod": """
import dbm
print(hasattr(dbm, "open"))
""",
}


def run_all_tests():
    """Run all stdlib module tests and report results."""
    all_tests = {}
    all_tests.update(BRIDGE_TESTS)
    all_tests.update(PYTHON_TESTS)

    results = {"pass": [], "skip": [], "fail": []}
    total = len(all_tests)

    print(f"Running {total} stdlib module tests...\n")

    for i, (name, source) in enumerate(sorted(all_tests.items()), 1):
        t0 = time.time()
        try:
            result = diff_test(source, timeout=30.0)
            elapsed = time.time() - t0
            status = result.status
            results[status].append((name, result, elapsed))

            marker = {"pass": "PASS", "skip": "SKIP", "fail": "FAIL"}[status]
            detail = ""
            if status == "skip":
                detail = f" ({result.reason})"
                if result.compile_result and result.compile_result.errors:
                    first_err = result.compile_result.errors[0]
                    if len(first_err) > 80:
                        first_err = first_err[:77] + "..."
                    detail = f" ({first_err})"
            elif status == "fail":
                detail = f" ({result.reason})"

            print(f"  [{i:3d}/{total}] {marker:4s} {name:30s} ({elapsed:.1f}s){detail}")
        except Exception as e:
            elapsed = time.time() - t0
            results["fail"].append((name, None, elapsed))
            print(f"  [{i:3d}/{total}] ERR  {name:30s} ({elapsed:.1f}s) EXCEPTION: {e}")

    # ── Summary ──
    print(f"\n{'='*70}")
    print(f"RESULTS: {len(results['pass'])} pass, {len(results['skip'])} skip, {len(results['fail'])} fail")
    print(f"{'='*70}")

    if results["skip"]:
        print(f"\n-- SKIPPED ({len(results['skip'])}) --")
        for name, result, elapsed in sorted(results["skip"]):
            reason = ""
            if result and result.compile_result and result.compile_result.errors:
                reason = str(result.compile_result.errors[0])
                if len(reason) > 100:
                    reason = reason[:97] + "..."
            print(f"  {name:30s} {reason}")

    if results["fail"]:
        print(f"\n-- FAILED ({len(results['fail'])}) --")
        for name, result, elapsed in sorted(results["fail"]):
            if result:
                cpython_out = (result.cpython.stdout or "(empty)").strip()
                compiled_out = (result.compiled.stdout or "(empty)").strip() if result.compiled else "(no binary)"
                cpython_err = (result.cpython.stderr or "").strip()
                compiled_err = (result.compiled.stderr or "").strip() if result.compiled else ""
                cpython_rc = result.cpython.exit_code if result.cpython else "?"
                compiled_rc = result.compiled.exit_code if result.compiled else "?"
                print(f"\n  {name}:")
                print(f"    exit: cpython={cpython_rc} compiled={compiled_rc}")
                if cpython_out != compiled_out:
                    # Truncate long output
                    if len(cpython_out) > 200: cpython_out = cpython_out[:200] + "..."
                    if len(compiled_out) > 200: compiled_out = compiled_out[:200] + "..."
                    print(f"    cpython stdout: {cpython_out}")
                    print(f"    compiled stdout: {compiled_out}")
                if compiled_err:
                    if len(compiled_err) > 200: compiled_err = compiled_err[:200] + "..."
                    print(f"    compiled stderr: {compiled_err}")
            else:
                print(f"\n  {name}: (exception during test)")

    return results


if __name__ == "__main__":
    run_all_tests()
