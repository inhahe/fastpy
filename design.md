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

### Refcounting in codegen: the Model-2 owned-temp rule

Heap values (strings, lists, dicts, objects) are reference counted. Codegen uses
the **Model-2 "borrowed-at-boundary"** discipline: a producer that hands back a
freshly-allocated `+1` value *registers* it as an **owned temp**
(`_register_owned_temp`), every consumer that wants to keep it **increfs to
retain**, and the registered `+1` is released by a **watermark flush**
(`_flush_rc_temps_to(mark)`) at the next statement/expression boundary. Mis-
classifying an owned value as borrowed only leaks; classifying a borrowed value
as owned is a use-after-free — so *retain* is always the safe direction.

Three structural rules follow, and all have been the source of real bugs:

- **A temp must be released in a block that its definition dominates.** An owned
  temp created inside one arm of a conditional *expression* — an if-expression
  branch, an `and`/`or` short-circuit operand — lives in that arm's own basic
  block, but the enclosing statement flushes in the **merge** block, which the
  arm does not dominate. Emitting the release there is invalid IR. Such arms must
  call `_capture_arm_rc_temps(mark)` while the builder is still inside the arm,
  and `_rejoin_arm_rc_temps(arms)` at the top of the merge block, which rebuilds
  each temp as a (tag, data) phi pair that is `0` on every other incoming edge —
  `fpy_rc_decref` no-ops on `data == 0`, so exactly the arm that ran is released.
  This moves the release site only; the `+1` itself is untouched.
- **A loop body must release its own temps before the back-edge.** The same
  dominance failure appears in comprehensions — a temp allocated in the body is
  invisible to the block where the enclosing statement flushes, after the loop.
  Here the phi rebuild would be *wrong*: the body runs N times, so releasing one
  merged value would leak N-1 iterations. The rule is a **per-iteration flush**
  (`_flush_rc_temps_to(mark)` with `mark` taken at the top of the body, emitted
  immediately before the branch to the incr block). It is only correct because
  every container store retains — `fpy_list_append` and `fastpy_dict_set_fv`
  incref what they store — so the container's reference outlives the body's. When
  a filter forks the body into keep/skip arms that both reach the incr block,
  `_release_rc_temps_since(mark)` emits the release on the skip arm *without*
  consuming the pending list, so each mutually exclusive path releases once.
- **Every store path must retain, or the flush frees a live variable.** A
  variable that outlives the statement that produced its value has to take its
  own reference; otherwise the boundary flush frees it and the next read is
  garbage. How this is done depends on the slot's representation:
  - An **FpyValue local** is a `{tag, data}` pair, so the slot carries its own
    tag: `_store_variable`'s FV path can incref the incoming value and decref
    whatever the slot held, unless the caller passes `steal=True` to hand over
    an already-owned `+1`.
  - A **native slot** — the bare-ABI path and the `--typed` `_native_vars` fast
    path — is a bare alloca (`i8*`, `i64`) with no runtime tag, so ownership is
    tracked *compiler-side* in `_rc_native_slots`, a per-`ir.Function` map of
    `name -> (alloca, tag)` recording the tag each slot was last **retained**
    with. `_retain_native_store` increfs the new value, then releases the old
    contents using the recorded tag — necessary because a slot can be rebound
    across static kinds (`x = str(5)` then `x = 12`). `_entry_store_null` zeroes
    such allocas in the entry block so a slot assigned on only one branch
    releases NULL instead of stack garbage, and `_emit_scope_decref` walks the
    registry at function exit. Gated on `_NATIVE_HEAP_TAGS` so scalar slots stay
    refcount-traffic-free; PYOBJ is excluded because the CPython bridge owns
    those pointers.

  Module scope sits outside both: module-level names take an early-return global
  path with no refcount traffic at all.

  **Ordering:** the retain must come *before* the release of the old value, or
  `s = s` drops the last reference and then stores a dangling pointer. The
  native path does this; the FV path still decrefs first
  (**BUG-FV-STORE-DECREF-BEFORE-INCREF**).

## Runtime

`runtime/` holds the C runtime linked into every fastpy binary:

- **Shared, Python-independent:** `runtime.c`, `objects.c`, `threading.c`,
  `gc.c`, `bigint.c` — object model, refcounting/GC, threading, big integers.
- **CPython bridge:** `cpython_bridge.c` (compiled per Python version, `py311`–
  `py314`) embeds a real CPython so programs using unsupported stdlib still run.
  The bridge drags `libpython` into the binary.

**Method dispatch ABI.** User classes register their methods with
`fastpy_register_method(class_id, name, func, arg_count, returns_value)`, and
the string dispatchers (`fastpy_obj_call_methodN`) call the stored pointer
through a function-pointer cast. That cast must match the callee's real
signature: a Python method with no `return <expr>` is compiled to a **void**
LLVM function, and calling it through an `int64_t`-returning type yields
whatever is in the return register, not 0. Hence the `returns_value` flag and
the `FpyMethod*VoidFunc` typedefs in `objects.h` — the dispatchers branch on it.
The same rule holds anywhere else a method pointer is called (the vtable path in
codegen checks `direct_func.return_value.type` for exactly this reason). Getting
it wrong is not a crash but a wrong *value*, and `with` turns a wrong value into
lost control flow: a truthy `__exit__` result means "suppress the exception".

**The compiler-side counterpart: a void call's Python value is `None`.** Because
a function/method with no `return <expr>` compiles to a void LLVM function,
codegen has nothing to hand back and substitutes the placeholder `i64 0`. That
placeholder's LLVM type says INT, which is a lie — the Python value is `None`.
Anywhere codegen derives a *tag* rather than an LLVM type (print wrapping,
FpyValue boxing, `is` comparison, variable type inference), it must ask
`CodeGen._call_is_void(node)` rather than look at the value, or the call reads
back as the integer `0`. A void method also never calls `set_ret_tag()`, so the
`get_ret_tag()` recovery used for obj-method calls does not apply to it.

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
  `ensure_slateos_runtime_built()` compiles the seven pure-mode TUs — `runtime`,
  `objects`, `threading`, `gc`, `bigint`, **`bridge_stub`**, **`pathlib_pure`** — into
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
- [x] **Native `os.*` syscall surface (pure-mode, bridge-free)** — a growing set
  of `os` functions lower directly to native runtime C calls (`fastpy_os_*` in
  `runtime/objects.c`, declared `extern` in `runtime.c`) that call the SlateOS
  posix libc, which dispatches to the kernel `SYS_*` syscalls — no CPython
  bridge (only the `fpy_cpython_import_native` sentinel from `import os`). Each
  lowering has **five sites** in `compiler/codegen.py`: (1) runtime `ir.Function`
  registration (`self.runtime["os_X"]`), (2) return-type inference in the
  `mod == "os"` chain, (3) an emit handler in `_emit_os_call` (raw-fd args are
  coerced to i64 via the inline `_fd_i64` helper; string args via
  `_ensure_ptr`), (4) an entry in the `_CSA_MODULE_FUNC_RETURNS` map, plus (5)
  the C impl + extern. Surface so far:
  - **process/identity:** `getpid`, `getppid`, `gettid`, `getcwd`, `getenv`.
  - **raw-fd I/O:** `open(path, flags[, mode])` → raw file fd (SYS_FS_OPEN; the
    raw-fd counterpart to the high-level builtin `open()`), `read(fd, n)` → str,
    `write(fd, data)` → int, `close(fd)` (posix dispatches by fd kind:
    SYS_PIPE_* for pipe ends, SYS_FS_* for files), `dup(fd)` (shares the kernel
    handle — a pipe dup aliases the same buffer), `dup2(oldfd, newfd)` (installs
    the handle at a *caller-chosen* fd, closing whatever was there — fd
    redirection), `lseek(fd, off, whence)`
    (SYS_FS_SEEK), `ftruncate(fd, len)` (SYS_FS_FTRUNCATE — distinct from the
    path-based `truncate()`/SYS_FS_TRUNCATE), `pwrite`/`pread(fd, …, offset)`
    (positioned I/O that leaves the fd offset untouched).
  - **pipes:** `pipe()` → `[r, w]` (SYS_PIPE_CREATE). NOTE: this exercise
    uncovered and fixed a systemic kernel ABI bug — the native SYSCALL exit
    path dropped `SyscallResult::value2` (the RDX second return), so *every*
    two-value syscall (SYS_PIPE_CREATE, SYS_CHANNEL_CREATE, dma_alloc, …) lost
    its second value in userspace until fixed.
  - **path helpers:** `path.exists`/`isfile`/`isdir`/`join`/`dirname`/…,
    `listdir`, `remove`/`unlink`/`mkdir`/`rmdir`/`rename`/`truncate`/…
  Each new raw-fd syscall ships with a **false-pass-proof ring-3 kernel
  self-test** in the OS repo (`services/fastpy-<name>/` tool +
  `self_test_fastpy_slateos_<name>` in `kernel/src/proc/spawn.rs`): the tool
  round-trips data through the kernel path and writes the result to a file the
  harness asserts byte-for-byte, so a stub/mis-lowering cannot fake a pass.
- [x] **Pure-mode `pathlib.Path`** (`runtime/pathlib_pure.c`, on-target verified)
  — the CPython-free implementation of the whole `Path` surface codegen emits:
  construction, `/` and `joinpath`, `name`/`stem`/`suffix`/`parent`,
  `exists`/`is_file`/`is_dir`, `resolve`, `read_text`/`write_text`,
  `with_suffix`, `iterdir`, and the `Path.cwd()` classmethod. Predicates
  delegate to the native `fastpy_os_path_*` helpers in `objects.c`, so no new
  struct-stat ABI dependency.

  **Representation (matters — it is an ABI contract with codegen):** a Path is
  OBJ-tagged (`FPY_TAG_OBJ`), and fastpy's OBJ refcount dispatcher
  (`fpy_rc_incref`/`decref`) has no type information, so it *blind-probes* the
  pointee for an `FpyObj` magic at **byte offset 32** and an `FpyClosure` magic
  at **offset 0**. The obvious "a Path is just a `char*`" representation puts
  path *text* under both probes — a filename whose bytes 32..35 spell "SJBO"
  (`FPY_OBJ_MAGIC`) was therefore mistaken for a live object and had its own
  bytes decremented as a refcount. That is user-controllable and deterministic,
  not a rare collision. So a pure-mode Path is an **`FpyPurePath` header block**:
  magic at offset 0, a zero guard word at offset 32, NUL-terminated text at
  offset 40. Consumers must use `_p()` / the exported `fastpy_path_as_cstr()`;
  never cast a Path to `char*`. Two consequences: `fastpy_path_with_suffix` has
  a pure-mode implementation here (the `runtime.c` one is `#ifndef
  FPY_PURE_MODE`), and codegen converts a Path right-hand join operand through
  `path_str` (`_emit_path_join_operand`).

  **String results** (`name`/`stem`/`suffix`/`str()`/`read_text`) are tagged
  `FPY_TAG_STR` and so must be `fpy_str_alloc`-headed, never bare `strdup` — the
  refcount machinery reads an 8-byte header at `data - 8`, and on the SlateOS
  allocator a bare `strdup`'s preceding word can collide with `FPY_STR_MAGIC`
  and free a wild pointer.

  **`iterdir()`** is typed `list[Path]` by codegen (`_is_path_iterdir_call`),
  and *both* runtimes return an `FpyList*` of OBJ-tagged Paths — codegen is
  deliberately mode-agnostic, so the bridge was changed to match rather than
  returning a raw PyObject* list. CPython's laziness is the one semantic
  difference; the bridge was always eager too.
- [ ] **CPython bridge on SlateOS (B)** — later, once CPython is ported, so
  unsupported-stdlib programs also run on-target.

## `tools/pure_harness.py` — fast memory-safety loop for pure mode

Pure-mode bugs used to be found only by a ~6-minute QEMU boot that reports a
single exit code and no memory-safety signal. `tools/pure_harness.py` closes
that loop to seconds: it takes a fastpy program, generates IR with the **real**
`CodeGen`, strips the target triple/datalayout, and builds it under WSL clang
against the **real** pure-mode runtime TUs (`-DFPY_PURE_MODE`) with
`-fsanitize=address,undefined -fno-sanitize-recover=all`. Same codegen, same C,
native Linux instead of SlateOS — so anything that is a genuine out-of-bounds,
use-after-free, or misaligned access shows up with a stack trace and an
allocation site instead of a silently wrong answer. Both live Path bugs this
session (the offset-32 heap-buffer-overflow and a misaligned `FpyObj` access
from `Path.cwd()`) were pinpointed this way. Regression programs live in
`tests/pure/*.py` and print a bitmask (Linux truncates exit codes to 8 bits;
SlateOS does not, which is why the on-target tools exit with theirs). They
currently cover the `Path` surface — its construction and accessors
(`pathlib_checks`, `path_boundary_checks`, `path_magic_collision_checks`,
`path_iterdir_checks`), its *display* through the generic OBJ consumers
(`path_display_checks`), and its use *as an argument* to `os.*` / `os.path.*` /
the builtin `open()` (`path_arg_checks`) — plus exception handling
(`exception_checks`), which establishes that pure mode really does catch a
`fastpy_raise` raised from inside a runtime function, the premise any runtime
error-reporting design depends on.

The argument case deserves its own file because the conversion is per-call-site:
a Path is a headed object, so a runtime entry point taking `const char *` must
receive `fastpy_path_str(p)`, not the Path pointer. Codegen does this with
`_emit_path_text_arg`; **any new runtime entry point that takes a path string
must emit its argument the same way.** Miss one and the callee reads the
header — historically answering about a file literally named `PATH` — which is
silent, per-call-site, and invisible to a suite written with string paths.

## Tests

`tests/` mixes two things: fastpy *programs* used as differential fixtures
(`test_getenv.py`, etc.) and real **pytest driver modules**
(`test_differential.py`, `test_full_suite.py`, `test_comprehensive.py`,
`test_cross_target.py`). Config in `pyproject.toml` (`[tool.pytest.ini_options]`).

## Git workflow (project rule)

Never `git push` from this working directory. The user pushes by copying files to
`D:\github\fastpy` and pushing there. Committing locally is fine.
