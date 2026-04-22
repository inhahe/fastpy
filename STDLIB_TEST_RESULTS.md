# Stdlib Module Test Results

**Date:** 2026-04-22 (last updated)
**Python:** 3.14 (Windows)
**Tests:** 134 individual module test snippets run through differential harness

## Summary

| Result | Count | Percentage |
|--------|-------|------------|
| PASS   | 134   | 100.0%     |
| FAIL   | 0     | 0.0%       |
| SKIP   | 0     | 0.0%       |

Every test compiled successfully (0 skips). All 134 produced output identical
to CPython.

---

## Progression

| Milestone | Pass | Fail | Key fixes |
|-----------|------|------|-----------|
| Initial baseline | 85 | 44 | First full test suite run |
| RC-2 bridge fallback | 89 | 40 | Native module handlers return None for unhandled functions |
| Batch fixes (type, bytes, closures, binops, kwargs, complex, sets) | 118 | 11 | Major bug-fix sweep |
| uuid bridge fallback | 119 | 10 | Remove native uuid handler; use bridge for real UUID objects |
| struct bridge fallback | 120 | 9 | Remove struct from native modules; fixes bytes with embedded nulls |
| shelve context manager + exception propagation | 121 | 8 | PyObject* context manager in `_emit_with`; `bridge_propagate_exception()` replaces `PyErr_Print()` |
| graphlib truthiness + sorted pyobj | 122 | 7 | FpyValue struct in `_truthiness_of_expr`; sorted() pyobj conversion |
| csv stdout text mode + repr escaping | 123 | 6 | `_setmode(stdout, _O_TEXT)` in main(); string repr escapes `\r\n\t` |
| types + inspect + calendar + enum | 126 | 3 | `type(f)` returns FunctionType; inspect.signature intercept; pyobj print path; enum bridge routing |
| copy mixed-type lists | 128 | 1 | Mixed-type list elem detection; `_emit_mixed_elem_method` for `b[1].append(5)` |
| threading list-of-pyobj iteration | 129 | 0 | Prescan detects bridge call results in lists; `_emit_for_list` handles pyobj elem type |
| Add `_`-prefixed C extension tests | 134 | 0 | New tests for `_abc`, `_typing`, `_warnings`, `_uuid`, `_asyncio` |

---

## Tests that PASS (134)

_abc, _asyncio, _bisect, _collections, _contextvars, _csv, _datetime,
_decimal, _functools, _hashlib, _heapq, _io, _json, _locale, _operator,
_random, _signal, _socket, _statistics, _string, _struct, _tracemalloc,
_typing, _uuid, _warnings, abc, argparse_mod, array, ast_mod, asyncio_mod,
base64, binascii, bisect, calendar, cmath, codecs_mod, collections_pkg,
colorsys, compileall_mod, configparser_mod, contextlib, copy, csv,
dataclasses, datetime, dbm_mod, decimal_mod, difflib, dis_mod, enum_mod,
errno, filecmp_mod, fnmatch, fractions, functools, gc_mod, getopt,
gettext_mod, glob_mod, graphlib, gzip, hashlib, heapq, hmac_mod, html_mod,
http_mod, inspect_mod, io_mod, ipaddress, itertools, json, json_pkg, keyword,
locale_mod, logging_mod, math, mimetypes_mod, mmap_mod, netrc_mod, numbers,
operator, os_mod, pathlib, pickle, platform, plistlib_mod, pprint_mod,
pyexpat, queue_mod, quopri_mod, random, re, reprlib, sched_mod, secrets,
select, selectors_mod, shelve, shlex, shutil, signal, socket,
socketserver_mod, sqlite3_mod, ssl_mod, stat, statistics, string, struct,
sysconfig_mod, tabnanny_mod, tarfile_mod, tempfile_mod, textwrap,
threading_mod, time, timeit_mod, token, tomllib_mod, traceback_mod, types,
typing_mod, unicodedata, unittest_mod, urllib_mod, uuid, warnings_mod, wave,
weakref, xml_mod, zipfile, zipimport_mod, zlib, zoneinfo_mod
