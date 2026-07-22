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
  runs to `exit(0)` at ring 3** — the kernel self-test
  `self_test_fastpy_slateos_tls` spawns it via the native ABI and asserts the
  process reaches `Zombie` with exit 0 (serial: *"fastpy-on-SlateOS TLS … set up
  main-thread ELF TLS via SYS_SET_FS_BASE and ran to exit(0): OK"*). The crt
  startup + native syscalls behave on-target; the pipeline is now validated
  end-to-end, not just at link time.
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
    proven.
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
