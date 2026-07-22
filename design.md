# fastpy — Design Overview

fastpy is an **ahead-of-time (AOT) Python → native compiler**. It parses typed
Python, lowers it to LLVM IR (via llvmlite), optimizes and emits a native object,
then links it with a small C runtime to produce a standalone executable. Programs
that use stdlib features fastpy doesn't natively support fall back to an embedded
CPython interpreter (the "bridge"), so *any valid Python is valid fastpy*.

This file is a living, high-level map of the architecture. It is intentionally
concise; deeper per-subsystem notes live in `README.md`, `REFACTOR_DESIGN.md`,
`MODULE_SUPPORT.md`, `BRIDGE_FALLBACKS.md`, and `roadmap.md`. Keep this file in
sync when features or architecture change.

## Pipeline

```
.py source
  → parse (compiler/, Python AST)
  → type inference / lowering
  → LLVM IR (llvmlite)
  → compile_ir_to_obj()      (toolchain.py — -O2 passes + backend codegen)
  → link_executable()        (toolchain.py — link runtime + CPython)
  → native executable
```

The two codegen/link entry points live in `compiler/toolchain.py`:

- **`compile_ir_to_obj(ir_string, output_path, target=None)`** — parses IR, runs
  the `-O2` new-pass-manager pipeline, and emits an object file via an LLVM
  `TargetMachine`.
- **`link_executable(obj_files, output_path, install)`** — links objects into an
  executable. Windows uses MSVC `link.exe` (via vcvars); POSIX uses `cc`.
- **`compile_and_link(...)`** — the full IR→exe convenience wrapper.

## Runtime

`runtime/` holds the C runtime linked into every fastpy binary:

- **Shared, Python-independent:** `runtime.c`, `objects.c`, `threading.c`,
  `gc.c`, `bigint.c` — object model, refcounting/GC, threading, big integers.
- **CPython bridge:** `cpython_bridge.c` (compiled per Python version, `py311`–
  `py314`) embeds a real CPython so programs using unsupported stdlib still run.
  The bridge drags `libpython` into the binary.

## Targets (codegen backends)

By default fastpy emits for the **host** triple and links against the host
CPython. `compile_ir_to_obj`/`_make_target_machine` accept a `target` selector so
fastpy can cross-compile for a foreign platform:

- **`target=None`** (default) — host codegen. PIC relocation on POSIX, default on
  Windows; links against host CPython. Unchanged historical behavior.
- **`target=SLATEOS_TARGET`** (`"x86_64-slateos"`) — cross-compile for **SlateOS
  userspace** (the microkernel OS in `D:\visual studio projects\os`). Emits an
  x86-64 **ELF** object using the triple `x86_64-unknown-linux-musl`, the
  data-layout, `static` relocation, `large` code model, and `+sse,+sse2` taken
  verbatim from the OS repo's Rust target spec `toolchain/x86_64-slateos.json`.
  This keeps fastpy objects **ABI-compatible with the OS's Rust sysroot** — in
  particular its `libc.a` (the `posix` crate built as a staticlib, which maps
  libc-shaped calls onto SlateOS native syscalls) — and linkable by the same
  gnu-lld/rust-lld linker. Both host and target are x86_64, so the already
  initialized native X86 backend can emit for this triple with no extra target
  initialization.

  The SlateOS constants (`_SLATEOS_TRIPLE`, `_SLATEOS_DATA_LAYOUT`,
  `_SLATEOS_CPU`, `_SLATEOS_FEATURES`) MUST stay in lockstep with
  `x86_64-slateos.json`. Tested by `tests/test_cross_target.py`.

### SlateOS integration status (OS "initiative F")

Driven by the OS roadmap and its decision log (`design-decisions.md §80`,
resolving open-question Q29). Strategy: **pure-mode native compile first**, add
the CPython bridge for SlateOS later as a superset once CPython is ported.

- [x] **SlateOS codegen target** — `compile_ir_to_obj(target=SLATEOS_TARGET)`
  emits ABI-matched x86-64 ELF objects.
- [x] **SlateOS link step (plumbing)** — `link_executable(target=SLATEOS_TARGET)`
  drives **`rust-lld`** (GNU/ELF flavor, static, non-PIE, `--no-dynamic-linker`)
  via `_link_slateos`, the same LLVM linker the OS repo uses for its userspace.
  `_find_rust_lld()` locates it in the active Rust sysroot (or `$FASTPY_RUST_LLD`
  / PATH).
- [x] **Cross-compile the C runtime** (`runtime/*.c`) to `x86_64-slateos`
  (pure-mode: no `cpython_bridge.c`, no `libpython`). Done via **`zig cc
  --target=x86_64-linux-musl`** — a self-contained clang + bundled musl headers
  + musl libc in one portable download, so no system-wide toolchain and no
  separately vendored musl sysroot is needed (operator approved option A, Q30).
  `_find_zig_cc()` locates it (`$FASTPY_ZIG` / PATH / `D:\utils\zig-*`).
  `ensure_slateos_runtime_built()` compiles the six pure-mode TUs — `runtime`,
  `objects`, `threading`, `gc`, `bigint`, **`bridge_stub`** — into
  `runtime/slateos/*.o` with flags mirroring the codegen ABI (`-mcmodel=large`,
  `-fno-pic -fno-pie`, `-DFPY_PURE_MODE`). Pure-mode specifics:
  - **`bridge_stub.c`** substitutes for `cpython_bridge.c`: refcount hooks are
    no-ops (no bridge objects can exist) and operational entry points raise a
    catchable `RuntimeError`.
  - **`-DFPY_PURE_MODE`** compiles out the JIT symbol table in `runtime.c`
    (which would otherwise force-reference bridge functions pure mode omits).
  The port also fixed latent MSVC-isms in `objects.c`/`objects.h`/`threading.h`
  that MSVC accepted implicitly but Clang rejects (forward decls, `<assert.h>`,
  a `const`-discard cast) — all verified still safe for the host MSVC build.
- [x] **Full program link + crt startup** — `link_executable(target=SLATEOS_TARGET)`
  builds the runtime on demand, resolves the OS repo's static `libc.a`
  (`_find_slateos_sysroot_lib()`: `$FASTPY_SLATEOS_SYSROOT` or the sibling
  `../os/toolchain/sysroot/lib`), and links program object + runtime objects +
  `-lc` via `_link_slateos`. The link entry is **`_start`** (the real ELF
  entry), so rust-lld pulls the crt0 out of `libc.a` — the OS `posix` crate
  (built for `x86_64-unknown-none`, so its `#[cfg(target_os = "none")]` crt is
  present) provides `_start` → `__libc_start_main` (retrieves argv/envp from the
  kernel via syscall, inits environ/signals, runs ELF constructors) → calls
  `main` (runtime.c's `main`, which runs `fastpy_main`) → `exit(ret)`. A real
  fastpy program (lists/iteration/print) links to a ~2.9 MB SlateOS **ET_EXEC**
  ELF with a nonzero `_start` entry and zero undefined symbols (a static non-PIE
  link fails otherwise). Covered by `tests/test_cross_target.py` (skips cleanly
  without zig / rust-lld / sysroot). Note the fastpy program is emitted for the
  `x86_64-unknown-linux-musl` triple while the crt/libc is `x86_64-unknown-none`
  — ABI-identical at the object level (plain x86-64 SysV, static, large model).
- [x] **First real component — on-target execution confirmed** (2026-07-21). A
  fastpy-built SlateOS binary (`services/fastpy-hello` in the OS repo, a real
  fastpy program with lists/iteration) now **boots under the SlateOS kernel and
  runs at ring 3** — the kernel self-test `self_test_fastpy_slateos_tls` spawns
  it via the native ABI and asserts the process reaches `Zombie`. The crt
  startup + native syscalls behave on-target; the pipeline is now validated
  end-to-end, not just at link time.
  - **argv delivery validated on-target** (2026-07-21). The self-test spawns
    the program with a known 3-element argv (`["fastpy-hello","alpha","bravo"]`)
    and the program runs `sys.exit(len(sys.argv))`; the kernel asserts
    `exit_code == 3`. This exercises the full argument path end-to-end: kernel
    `SYS_PROCESS_GET_ARGS` → crt `retrieve_initial_args` → runtime `fpy_argv` →
    Python `sys.argv` → non-zero exit code back to the parent (serial:
    *"fastpy-on-SlateOS TLS … read its 3-element argv via sys.argv, and ran to
    exit(argc): OK"*). Two fixes made this work: (a) runtime `fastpy_sys_argv`
    now allocates each element as a heap `FpyString` (a raw C `char*` is not a
    valid `FPY_TAG_STR` value — reading the length header faults); and (b)
    codegen learned that `sys.argv`/`sys.path` are `list[str]` and
    `sys.version_info` is a `tuple[int]`, so `len()`/iteration/subscript dispatch
    natively instead of routing through the CPython-bridge object path (which,
    in pure mode, raises).
  - **Pure-mode native imports no longer require the CPython bridge.**
    `import sys` (and other native modules) previously emitted
    `fpy_cpython_import("sys")`, which in a pure-mode (no-CPython) build raises
    `RuntimeError` from `bridge_stub.c` — so the very first line of any program
    that imported a native module crashed on-target. Because the *same* IR is
    compiled for both host and pure targets, codegen cannot special-case the
    mode; the fix is at the runtime-C level. Codegen now emits
    `fpy_cpython_import_native` / `fpy_cpython_getattr_native` for native-module
    imports and attribute fallbacks. In the host bridge these forward to the
    real `fpy_cpython_import`/`getattr`; in `bridge_stub.c` they return a
    non-null opaque sentinel with **no raise** (native dispatch never
    dereferences it), so `import sys` links and runs in pure mode and only a
    genuine use of an unsupported non-native attribute fails cleanly.
  - **Q31 resolved — Option A** (operator's call; open-questions.md → OS
    design-decisions.md §82): the `PT_TLS` problem (the C runtime's
    `FPY_THREAD_LOCAL __thread` locals lower to `%fs:offset`, and a native static
    binary starts with `fs_base = 0`) is fixed **in the posix crt**. On startup
    `setup_main_thread_tls()` (`posix/src/crt.rs`, `#[cfg(target_os="none")]`)
    finds `PT_TLS` via the linker-defined `__ehdr_start` (no aux vector needed
    for a static non-PIE), mmaps a variant-II TLS block + TCB, copies the
    `.tdata` init image, writes the `%fs:0` self-pointer, and installs the thread
    pointer via the native `SYS_SET_FS_BASE` syscall — all before the first
    `__thread` access or stack-protector check runs.
  - Latent OS bug found + fixed en route: posix's native `SYS_MMAP`/`SYS_MUNMAP`/
    `SYS_MPROTECT` numbers (30/31/32) collided with the kernel's IRQ syscalls, so
    the crt's TLS mmap came back `PermissionDenied`; corrected to the kernel's
    native numbers (20/21/22). This is an OS-side fix, not a fastpy toolchain
    change — the toolchain remains complete and green.
  - Next: pick a genuinely useful component (candidate: the package manager) as
    the first *shipping* fastpy SlateOS binary now that the runtime path is
    proven. **Prerequisite in progress — pure-mode file I/O** (see below).
- [x] **Pure-mode file I/O — native file objects** (host-verified 2026-07-21;
  SlateOS build+link verified). A
  genuinely useful on-target utility (`cat`, `sysinfo`, the package manager)
  needs `open()`/read/write, but the built-in `open()` used to route through the
  CPython bridge (`builtins.open`), which raises in pure mode. Fix: a **native
  file object** in the runtime, backed by C stdio (`fopen`/`fread`/`fwrite`/
  `fgets`/`fclose` — the SlateOS posix libc implements these over the `SYS_FS_*`
  VFS syscalls, so it works on-target with no bridge). The file object is a
  built-in `FpyObj` class (`file`, registered lazily in `objects.c`) holding the
  `FILE*` in a slot; `open()` returns it tagged `FPY_TAG_OBJ`, so the existing
  object-method dispatch (`fastpy_obj_call_methodN`) and context-manager path
  (`with open(...) as f:` → `__enter__`/`__exit__`) drive `read`/`write`/
  `readline`/`readlines`/`close`/iteration with no per-method codegen. Because
  the `file` class is registered only at runtime (invisible to codegen), method
  calls on `open()` results are routed by codegen through a dedicated path
  (`_emit_method_call_file`): it emits `fastpy_obj_call_methodN` and recovers the
  dynamic return type from the runtime ret-tag side channel (`get_ret_tag`),
  packing the result as an `FpyValue` so `read`/`readline` → str, `readlines` →
  list, `write` → int are correctly typed at the call site (an earlier bug
  mistyped these as int, returning len 0 and segfaulting). Codegen tracks file
  variables (`_file_vars`) from `f = open(...)` assignments and `with open(...)
  as f:` bindings; the `with`/`for line in f` paths bind `f` as `VKind.OBJ` so
  the context-manager and iterator-protocol dispatch drive the runtime methods.
  **Design
  decision (Claude, autonomous):** native file objects are used in **both** host
  and pure mode (uniform behaviour, and it removes the bridge dependency
  entirely for core file I/O) rather than native-only-in-pure. Tradeoff: a native
  file object can't be handed to a *bridge* stdlib function (`json.load(f)`,
  `csv.reader(f)`) in host mode — but the test suite has no such fixture (only
  `shelve.open`, a module method, and the `_run_scratch`/`_dump_ir` harness
  scripts which run under host CPython, not compiled), and the idiomatic
  `json.loads(open(p).read())` still works because `read()` returns a native str.
  Known slice-1 limitations (documented, to extend): text mode only (`read()`
  returns `str`, binary `'rb'`/`bytes` not yet wired); `read(n)` size arg not yet
  supported (`read()` reads all); `FileNotFoundError` is raised by name but not
  yet registered in the OSError hierarchy.
- [ ] **CPython bridge on SlateOS (B)** — later, once CPython is ported, so
  unsupported-stdlib programs also run on-target.

## Tests

`tests/` mixes two things: fastpy *programs* used as differential fixtures
(`test_getenv.py`, etc.) and real **pytest driver modules**
(`test_differential.py`, `test_full_suite.py`, `test_comprehensive.py`,
`test_cross_target.py`). Config in `pyproject.toml` (`[tool.pytest.ini_options]`).

## Git workflow (project rule)

Never `git push` from this working directory. The user pushes by copying files to
`D:\github\fastpy` and pushing there. Committing locally is fine.
