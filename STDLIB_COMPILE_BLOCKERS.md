# Stdlib Native Compilation Blockers

**Status: 5 compiled / 124 failed** out of 129 pure Python stdlib `.py` files.

These are errors that occur when our compiler tries to natively compile the
CPython standard library source files. Fixing these would allow the JIT to
compile stdlib modules to native code instead of falling back to CPython.

## Blockers by frequency

| Count | Category | Fix difficulty |
|-------|----------|---------------|
| 13 | LLVM type mismatch in codegen | Medium |
| 11 | CodeGen._singledispatch missing (JIT init) | Easy |
| 8 | Undefined variable: sys | Easy |
| 7 | Subscript on unsupported type | Medium |
| 6 | Undefined variable: os | Easy |
| 5 | isinstance() with non-Name type args | Medium |
| 4 | `is` comparison on non-None types | Easy |
| 4 | Tuple unpacking from non-tuple source | Medium |
| 4 | Complex dict comprehension targets | Medium |
| 3 | Undefined: threading/other cross-module refs | Easy |
| 6 | len() on unsupported type | Medium |
| 2 | Undefined: __name__ | Easy |
| 2 | Undefined: self (outside method context) | Medium |
| 2 | Unknown format field: !r | Easy |
| 2 | Unsupported operand type mismatches | Medium |
| 2 | Lambda naming conflicts | Medium |
| ~20 | Various one-off undefined variables | Medium |

## Top fixes by impact (modules unblocked)

### 1. Fix CodeGen JIT init (11 modules)
`_singledispatch` and `_singledispatch_variants` not initialized.
**Modules:** ast, contextlib, enum, fileinput, functools, inspect, locale,
pathlib, pydoc, re, typing
**Fix:** Initialize these dicts in CodeGen.__init__ or the JIT wrapper.

### 2. Add sys/os/__name__/__doc__ as implicit globals (16+ modules)
Stdlib modules reference `sys`, `os`, `__name__`, `__doc__` without importing.
**Modules:** bdb, cmd, gettext, glob, poplib, shelve, socket, tracemalloc (sys);
filecmp, genericpath, getpass, netrc, pty, shutil (os); calendar, warnings (__name__)
**Fix:** Pre-populate these as variables in the module scope. `sys` and `os` can
be imported via bridge at startup. `__name__` = `"__main__"`, `__doc__` = `""`.

### 3. Fix LLVM type mismatches (13 modules)
`Type of #N arg mismatch: i8* != i64` — pointer vs integer confusion in
FpyValue wrapping/unwrapping at call boundaries.
**Modules:** abc, dis, graphlib, hashlib, ipaddress, locale, lzma, nntplib,
pdb, shelve, smtplib, tarfile, typing
**Fix:** Audit `_bare_to_tag_data` and `_emit_cpython_call_with_ptr` for cases
where pointer arguments get passed as i64 or vice versa.

### 4. Support subscript on arbitrary types (7 modules)
`Subscript on unsupported type` — accessing `x[i]` where `x` is not a known
list/dict/tuple/string.
**Modules:** antigravity, codeop, difflib, ntpath, posixpath, statistics, token
**Fix:** Fall back to `__getitem__` call via bridge for unknown types.

### 5. Support `is` on non-None types (4 modules)
`'is' only supported for None/Ellipsis comparisons` — `x is y` where y is
not None or Ellipsis.
**Modules:** csv, io, operator, py_compile
**Fix:** Compile `x is y` as pointer equality (`icmp eq` on the i64 values).

### 6. Support isinstance() with complex type args (5 modules)
`isinstance(x, bytes)`, `isinstance(x, (str, bytes))` — type arg not a
simple Name that we recognize.
**Modules:** base64, compileall, fnmatch, gzip, zipapp
**Fix:** Map `bytes` to a type tag. Support tuple of types by OR-ing checks.

### 7. General tuple unpacking (4 modules)
`Tuple unpacking from non-tuple not yet supported` — `a, b = func()` where
func doesn't return a known tuple.
**Modules:** nturl2path, smtplib, tabnanny, tempfile
**Fix:** Use `list_get_fv` on index 0, 1, ... for any iterable result.

### 8. Complex dict comprehension targets (4 modules)
`Only simple variable targets in dict comprehensions` — `{k: v for k, v in items}`
where the target is a tuple unpack.
**Modules:** sre_compile, sre_constants, sre_parse, token
**Fix:** Support tuple unpacking in comprehension iteration variable.

### 9. Format string !r conversion (2 modules)
`Unknown format field: !r` — f-string `{x!r}` not supported.
**Modules:** selectors, ssl
**Fix:** Route `!r` to `repr()` call on the value.

### 10. Cross-module variable references (~20 modules)
Various variables referenced but not imported (module-level names from
conditional imports, class bodies, etc.)
**Fix:** These are case-by-case. Most would be resolved by fixing the
above categories first (since many are side effects of earlier failures
in the same file).
