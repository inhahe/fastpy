"""
Cross-compilation target tests.

fastpy's default codegen emits for the host (COFF on Windows, ELF/Mach-O on
Linux/macOS) and links against the host CPython. Initiative F ("Python AOT ->
native executables for OS components") adds foreign targets so fastpy can emit
binaries that run *on* SlateOS rather than the dev host.

This module tests the first, self-contained increment: `compile_ir_to_obj`
honoring `target=SLATEOS_TARGET` to emit an x86_64 SlateOS-userspace ELF object
whose triple/data-layout/codegen knobs match the OS repo's Rust target spec
(toolchain/x86_64-slateos.json), so the object is ABI-compatible with that
sysroot's libc.a. Runtime porting and linking are later increments; here we
only verify the object-file shape is correct.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import pytest

from compiler import toolchain

# A minimal, target-independent IR module: `int main() { return 0; }`.
_TRIVIAL_IR = """
define i32 @main() {
entry:
  ret i32 0
}
"""

# ELF constants (see <elf.h>).
_ELFMAG = b"\x7fELF"
_ELFCLASS64 = 2
_ELFDATA2LSB = 1
_ET_REL = 1
_EM_X86_64 = 62


def _compile(target: str | None, name: str) -> bytes:
    d = Path(tempfile.mkdtemp(prefix="fastpy_xtarget_"))
    out = toolchain.compile_ir_to_obj(_TRIVIAL_IR, d / name, target=target)
    return out.read_bytes()


def test_slateos_target_emits_x86_64_elf_relocatable():
    """The SlateOS target produces a 64-bit LE x86-64 ET_REL ELF object."""
    data = _compile(toolchain.SLATEOS_TARGET, "slate.o")

    assert data[:4] == _ELFMAG, "SlateOS object is not an ELF file"
    ei_class, ei_data = data[4], data[5]
    e_type, e_machine = struct.unpack_from("<HH", data, 16)

    assert ei_class == _ELFCLASS64, f"expected ELFCLASS64, got {ei_class}"
    assert ei_data == _ELFDATA2LSB, f"expected little-endian, got {ei_data}"
    assert e_type == _ET_REL, f"expected ET_REL relocatable, got {e_type}"
    assert e_machine == _EM_X86_64, f"expected EM_X86_64 (62), got {e_machine}"


def test_default_target_still_works():
    """target=None keeps the historical host-object behavior (non-empty obj)."""
    data = _compile(None, "host" + toolchain.OBJ_EXT)
    assert len(data) > 0
    # On any host, the SlateOS object and the host object should differ in
    # format tag: only the cross object is ELF (on Windows the host is COFF; on
    # macOS Mach-O; on Linux the host is also ELF but with the host triple).
    if not toolchain.IS_LINUX:
        assert data[:4] != _ELFMAG


def test_unknown_target_rejected():
    """An unrecognized target name is a clear error, not a silent host build."""
    with pytest.raises(ValueError):
        _compile("some-bogus-target", "bogus.o")


# --- Link step (rust-lld) --------------------------------------------------
#
# The SlateOS link step drives rust-lld (GNU/ELF flavor) — the same LLVM
# linker the OS repo uses for its userspace — instead of the host MSVC/cc
# driver. These tests verify fastpy can find that linker and turn a SlateOS
# object into a SlateOS ELF *executable* (ET_EXEC), the counterpart of the
# codegen tests above.

_ET_EXEC = 2


def _rust_lld_available() -> bool:
    return toolchain._find_rust_lld() is not None


def test_slateos_link_produces_x86_64_elf_executable():
    """rust-lld links a SlateOS object into an x86-64 ET_EXEC ELF."""
    if not _rust_lld_available():
        pytest.skip("rust-lld not found (no Rust toolchain); link step untestable")

    d = Path(tempfile.mkdtemp(prefix="fastpy_xlink_"))
    obj = toolchain.compile_ir_to_obj(
        _TRIVIAL_IR, d / "prog.o", target=toolchain.SLATEOS_TARGET)
    # The trivial module's `main` references no external symbols, so a static,
    # entry=main link needs nothing from the sysroot — this isolates the link
    # plumbing from the not-yet-ported C runtime.
    exe = toolchain.link_executable(
        [obj], d / "prog.elf", target=toolchain.SLATEOS_TARGET)

    data = exe.read_bytes()
    assert data[:4] == _ELFMAG, "SlateOS executable is not an ELF file"
    ei_class = data[4]
    e_type, e_machine = struct.unpack_from("<HH", data, 16)
    assert ei_class == _ELFCLASS64, f"expected ELFCLASS64, got {ei_class}"
    assert e_type == _ET_EXEC, f"expected ET_EXEC executable, got {e_type}"
    assert e_machine == _EM_X86_64, f"expected EM_X86_64 (62), got {e_machine}"


def test_slateos_link_unknown_target_rejected():
    """link_executable rejects an unrecognized link target, no silent host link."""
    d = Path(tempfile.mkdtemp(prefix="fastpy_xlink_"))
    with pytest.raises(ValueError):
        toolchain.link_executable([d / "nope.o"], d / "out", target="bogus")


def test_find_rust_lld_returns_path_or_none():
    """The linker locator returns a real file path or None, never a bad path."""
    lld = toolchain._find_rust_lld()
    assert lld is None or lld.exists()
