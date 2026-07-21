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
  / PATH). Verified end-to-end on a self-contained object → SlateOS **ET_EXEC**
  ELF (`tests/test_cross_target.py`). Full program linking (fastpy objects +
  runtime objects + sysroot `libc.a`) awaits the runtime port below; the
  function already accepts a `sysroot_lib_dir`/`libs` for that.
- [ ] **Cross-compile the C runtime** (`runtime/*.c`) to `x86_64-slateos`
  (pure-mode: no `cpython_bridge.c`, no `libpython`). The runtime already has a
  working POSIX code path (it builds via `cc`/`gcc`/`clang` on Linux/macOS today
  with `#ifdef _WIN32` separation), so this is a small port, **not** a rewrite.
  **Gated on tooling** (operator decision): needs a C compiler that emits
  `x86_64-unknown-linux-musl` ELF (e.g. `clang --target=…`) plus musl/SlateOS C
  headers. The dev host has neither — no `clang` on PATH, and the OS sysroot
  (`toolchain/sysroot/lib`) ships only Rust-built `.a` archives, no C headers.
  Installing a clang cross-toolchain is heavyweight/system-wide → see
  `open-questions.md` in the OS repo.
- [ ] **First real component** — compile an actual OS component (candidate: the
  package manager) as the first fastpy-built SlateOS binary.
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
