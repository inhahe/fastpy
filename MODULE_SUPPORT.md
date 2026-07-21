# Module Support

## Status: 70+ native / all others via CPython bridge

Fastpy recognizes 70+ standard library modules natively (compiled to native code or
no-op imports). All 104 stdlib `.py` files compile successfully. All remaining modules
route through the embedded CPython bridge (`fpy_cpython_import`), which works
correctly but runs at interpreter speed. Linux and Windows are both supported.

## Modules that COULD be native but aren't yet (low priority)

These modules are pure Python or simple C wrappers that could theoretically
be compiled natively, but work fine through the CPython bridge:

- `re` — regex (would need a full NFA engine; bridge works fine)
- `decimal` — arbitrary-precision decimals (large implementation; bridge works)
- `cmath` — complex math (could map to C's complex.h; low demand)
- `fnmatch` — filename matching (simple glob logic; could be native)
- `configparser` — INI file parsing (pure Python; could multi-file compile)
- `colorsys` — color space conversion (pure math; trivial but rarely imported)
- `queue` — thread-safe queue (could use our threading primitives)
- `hmac` — HMAC signing (wraps hashlib; bridge works)
- `shlex` — shell lexing (pure Python; rarely hot)
- `locale` — i18n (wraps C locale; bridge works)
- `errno` — error codes (just constants; could be native)

## Modules that use CPython bridge (work, but not native)

These require CPython internals, external libraries, or OS kernel interfaces
that can't be reasonably reimplemented natively:

### Requires CPython internals
- `ast` — Python parser (IS the CPython parser)
- `importlib` — import system (needs CPython's module loader)
- `inspect` — frame introspection (needs CPython frames)
- `gc` — garbage collector (CPython's GC, not ours)
- `tracemalloc` — memory tracing (CPython allocator hooks)
- `sys` (partial) — some attrs need CPython state (sys.modules, sys._getframe)

### Requires external C libraries
- `sqlite3` — needs libsqlite3
- `ssl` — needs OpenSSL/LibreSSL
- `zlib`, `gzip`, `bz2`, `lzma` — need compression libraries
- `curses` — needs ncurses
- `tkinter` — needs Tk toolkit
- `ctypes` — FFI (needs libffi)

### Requires OS kernel interfaces
- `socket`, `select`, `selectors` — BSD socket API
- `multiprocessing` — process spawning + IPC
- `signal` — POSIX signal handling
- `fcntl`, `termios`, `pty` — Unix terminal control
- `mmap` — memory-mapped files

### Protocol implementations (too large to reimplement)
- `http`, `urllib` — HTTP client/server
- `email` — MIME parsing
- `xml` — XML parsing (expat/ElementTree)
- `html` — HTML parsing
- `ftplib`, `smtplib`, `imaplib`, `poplib` — mail/FTP protocols

## Architecture note

All unsupported modules still WORK — they just run through the CPython bridge
at interpreter speed. This is acceptable because:
1. Most are used for setup/teardown, not hot loops
2. The bridge handles type conversion automatically (PyObject* <-> FpyValue)
3. Method calls on bridge objects use `__getattr__`/`__call__` protocol
4. Bridge calls now support 4+ positional args (`fpy_cpython_call_kw`)
5. PYOBJ binops/comparisons dispatch through `fpy_cpython_binop`/`fpy_cpython_compare`
6. PyBytes_Check and PyTuple_Check correctly identify and preserve types across the bridge
7. Safe refcounting across FpyClosure, FpyObj, and PyObject* types

The compiler can target any installed Python version (3.11, 3.12, 3.13, 3.14)
with an ABI version check at startup to prevent version mismatches.

The only scenario where bridge performance matters is tight loops calling
bridge functions millions of times. For those cases, the solution is either:
- Roadmap #2: Runtime JIT (compile dynamic code to native at runtime)
- Or: move the hot logic into a natively-compiled function
