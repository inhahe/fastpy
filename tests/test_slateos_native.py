"""
fastpy running on SlateOS, where the host is the SlateOS target.

On SlateOS fastpy builds for itself the way other hosts cross-build for it --
pure mode, the system's `libc.a` -- except that fastpy's C runtime is
installed there as one archive, `libfastpy_rt.a`, because SlateOS has no C
compiler to build `runtime/*.c` with. `build_slateos_runtime_archive` makes
that archive on a build machine.

Nothing here runs on SlateOS, so the SlateOS tests pretend: they set
`toolchain.IS_SLATEOS` and point the system library directory at a temporary
one holding a real `libc.a` and an archive built by
`build_slateos_runtime_archive`. What that proves is that the SlateOS route
links a complete program from exactly those two files and nothing else --
which is all that differs on SlateOS itself, where the OS repository's boot
test then runs the result.
"""

from __future__ import annotations

import ast
import os
import shutil
import struct
import tempfile
import types
from pathlib import Path

import pytest

from compiler import toolchain

_ELF_MAGIC = b"\x7fELF"
_ET_EXEC = 2
_EM_X86_64 = 62


def _uname(release: str):
    return lambda: types.SimpleNamespace(release=release)


def _zig_available() -> bool:
    return toolchain._find_zig_cc() is not None


needs_zig = pytest.mark.skipif(not _zig_available(), reason="zig not found")


def _ar_members(data: bytes) -> dict[str, bytes]:
    """The members of an `ar` archive by name, in GNU or BSD format, without
    its symbol table."""
    assert data[:8] == b"!<arch>\n", "not an ar archive"
    members: dict[str, bytes] = {}
    long_names = b""
    pos = 8
    while pos < len(data):
        header = data[pos:pos + 60]
        name = header[:16].decode("ascii").rstrip()
        size = int(header[48:58].decode("ascii").strip())
        body = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size & 1)
        if name in ("/", "/SYM64/"):          # GNU symbol table
            continue
        if name == "//":                      # GNU long-name table
            long_names = body
            continue
        if name.startswith("#1/"):            # BSD: the name opens the body
            length = int(name[3:])
            name, body = body[:length].rstrip(b"\0").decode("ascii"), body[length:]
            if name.startswith("__.SYMDEF"):
                continue
        elif name.startswith("/") and name[1:].isdigit():
            start = int(name[1:])
            name = long_names[start:long_names.index(b"/\n", start)].decode("ascii")
        elif name.endswith("/"):
            name = name[:-1]
        members[name] = body
    return members


# ------------------------------------------------------------ recognising it

def test_slateos_is_recognised_by_its_kernel_release(monkeypatch):
    monkeypatch.setattr(toolchain, "IS_LINUX", True)
    monkeypatch.setattr(os, "uname", _uname("6.6.0-slateos"), raising=False)
    assert toolchain._host_is_slateos()
    for other in ("6.6.87.2-microsoft-standard-WSL2", "6.8.0-45-generic",
                  "6.6.0-slateos-but-not-at-the-end"):
        monkeypatch.setattr(os, "uname", _uname(other), raising=False)
        assert not toolchain._host_is_slateos(), other


def test_only_a_linux_like_system_can_be_slateos(monkeypatch):
    monkeypatch.setattr(toolchain, "IS_LINUX", False)
    monkeypatch.setattr(os, "uname", _uname("6.6.0-slateos"), raising=False)
    assert not toolchain._host_is_slateos()


def test_this_machine_is_not_slateos():
    # The suite runs on build machines; were this ever true here, every
    # host-link test would be exercising the wrong route.
    assert toolchain.IS_SLATEOS is False


# ----------------------------------------------------------- where things are

def test_on_slateos_the_sysroot_is_the_system_library_directory(monkeypatch, tmp_path):
    (tmp_path / "libc.a").write_bytes(b"!<arch>\n")
    monkeypatch.delenv("FASTPY_SLATEOS_SYSROOT", raising=False)
    monkeypatch.setattr(toolchain, "IS_SLATEOS", True)
    monkeypatch.setattr(toolchain, "SLATEOS_SYSTEM_LIB_DIR", tmp_path)
    assert toolchain._find_slateos_sysroot_lib() == tmp_path


def test_the_sysroot_variable_still_wins_on_slateos(monkeypatch, tmp_path):
    system, chosen = tmp_path / "system", tmp_path / "chosen"
    for d in (system, chosen / "lib"):
        d.mkdir(parents=True)
        (d / "libc.a").write_bytes(b"!<arch>\n")
    monkeypatch.setattr(toolchain, "IS_SLATEOS", True)
    monkeypatch.setattr(toolchain, "SLATEOS_SYSTEM_LIB_DIR", system)
    monkeypatch.setenv("FASTPY_SLATEOS_SYSROOT", str(chosen))
    assert toolchain._find_slateos_sysroot_lib() == chosen / "lib"


def _sysroot_at(checkout):
    lib = checkout / "toolchain" / "sysroot" / "lib"
    lib.mkdir(parents=True)
    (lib / "libc.a").write_bytes(b"!<arch>\n")
    return lib


def test_elsewhere_the_checkout_the_build_runs_in_comes_before_the_sibling(
        monkeypatch, tmp_path):
    # The OS repo is worked in several checkouts beside one named `os`; from
    # any other, the sibling is a different tree's libc.a.
    lane = _sysroot_at(tmp_path / "os-lane-d")
    _sysroot_at(tmp_path / "os")
    inside = tmp_path / "os-lane-d" / "services" / "fastpy-hello"
    inside.mkdir(parents=True)
    monkeypatch.delenv("FASTPY_SLATEOS_SYSROOT", raising=False)
    monkeypatch.setattr(toolchain, "IS_SLATEOS", False)
    monkeypatch.setattr(toolchain, "_PROJECT_ROOT", tmp_path / "fastpy")
    monkeypatch.chdir(inside)
    assert toolchain._find_slateos_sysroot_lib() == lane


def test_elsewhere_outside_any_checkout_the_sibling_os_is_used(monkeypatch, tmp_path):
    sibling = _sysroot_at(tmp_path / "os")
    elsewhere = tmp_path / "work"
    elsewhere.mkdir()
    monkeypatch.delenv("FASTPY_SLATEOS_SYSROOT", raising=False)
    monkeypatch.setattr(toolchain, "IS_SLATEOS", False)
    monkeypatch.setattr(toolchain, "_PROJECT_ROOT", tmp_path / "fastpy")
    monkeypatch.chdir(elsewhere)
    assert toolchain._find_slateos_sysroot_lib() == sibling


def test_the_sysroot_variable_wins_over_the_checkout_the_build_runs_in(
        monkeypatch, tmp_path):
    _sysroot_at(tmp_path / "os-lane-d")
    chosen = _sysroot_at(tmp_path / "chosen")
    monkeypatch.setattr(toolchain, "IS_SLATEOS", False)
    monkeypatch.setenv("FASTPY_SLATEOS_SYSROOT", str(chosen))
    monkeypatch.chdir(tmp_path / "os-lane-d")
    assert toolchain._find_slateos_sysroot_lib() == chosen


def test_on_slateos_the_runtime_is_the_installed_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(toolchain, "IS_SLATEOS", True)
    with pytest.raises(RuntimeError, match="libfastpy_rt.a"):
        toolchain._slateos_runtime_inputs(tmp_path)
    archive = tmp_path / toolchain.SLATEOS_RUNTIME_ARCHIVE
    archive.write_bytes(b"!<arch>\n")
    assert toolchain._slateos_runtime_inputs(tmp_path) == [archive]


def test_elsewhere_an_archive_in_the_sysroot_is_not_used(monkeypatch, tmp_path):
    # It could be older than runtime/*.c, and nothing would say so.
    (tmp_path / toolchain.SLATEOS_RUNTIME_ARCHIVE).write_bytes(b"!<arch>\n")
    built = [tmp_path / "runtime.o"]
    monkeypatch.setattr(toolchain, "IS_SLATEOS", False)
    monkeypatch.setattr(toolchain, "ensure_slateos_runtime_built", lambda force=False: built)
    assert toolchain._slateos_runtime_inputs(tmp_path) == built


def test_on_slateos_a_missing_libc_names_the_system_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("FASTPY_SLATEOS_SYSROOT", raising=False)
    monkeypatch.setattr(toolchain, "IS_SLATEOS", True)
    monkeypatch.setattr(toolchain, "SLATEOS_SYSTEM_LIB_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="no libc.a in"):
        toolchain.link_executable([tmp_path / "p.o"], tmp_path / "p",
                                  target=toolchain.SLATEOS_TARGET)


def test_ld_lld_beside_opt_and_llc_is_the_linker(monkeypatch, tmp_path):
    lld = tmp_path / ("ld.lld" + toolchain.EXE_EXT)
    lld.write_bytes(b"")
    monkeypatch.delenv("FASTPY_RUST_LLD", raising=False)
    monkeypatch.setenv("FASTPY_LLVM_BIN", str(tmp_path))
    assert toolchain._find_rust_lld() == lld


def test_a_tool_directory_without_ld_lld_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.delenv("FASTPY_RUST_LLD", raising=False)
    monkeypatch.setenv("FASTPY_LLVM_BIN", str(tmp_path))
    found = toolchain._find_rust_lld()     # whatever else there is, or None
    assert found is None or Path(found).exists()


# --------------------------------------------------------------- the archive

@needs_zig
def test_the_archive_holds_the_runtime_objects_exactly(tmp_path):
    dest = tmp_path / "lib" / toolchain.SLATEOS_RUNTIME_ARCHIVE
    # A stale archive with a member the runtime no longer has must not
    # survive into the new one: `ar r` would keep it.
    dest.parent.mkdir()
    dest.write_bytes(b"!<arch>\nstale")
    assert toolchain.build_slateos_runtime_archive(dest) == dest
    members = _ar_members(dest.read_bytes())
    objects = toolchain.ensure_slateos_runtime_built()
    assert sorted(members) == sorted(o.name for o in objects)
    for obj in objects:
        assert members[obj.name] == obj.read_bytes(), obj.name


@needs_zig
def test_the_archive_is_the_same_bytes_every_time(tmp_path):
    first = toolchain.build_slateos_runtime_archive(tmp_path / "a" / "libfastpy_rt.a")
    second = toolchain.build_slateos_runtime_archive(tmp_path / "b" / "libfastpy_rt.a")
    assert first.read_bytes() == second.read_bytes()


# ------------------------------------------------------------- end to end

_PROGRAM = (
    "import sys\n"
    "xs = [1, 2, 3]\n"
    "total = 0\n"
    "for x in xs:\n"
    "    total += x * x\n"
    "print('squares', total)\n"
    "sys.exit(len(sys.argv))\n"
)


@needs_zig
def test_on_slateos_a_program_is_linked_from_the_installed_archives(monkeypatch, tmp_path):
    """The SlateOS route, end to end but for running the result.

    The system library directory holds a real `libc.a` and an archive built by
    `build_slateos_runtime_archive`, and nothing else is allowed to be used:
    building runtime objects, or finding a CPython, fails the test.
    """
    from compiler.codegen import CodeGen

    if toolchain._find_rust_lld() is None:
        pytest.skip("no rust-lld or ld.lld to link with")
    real_sysroot = toolchain._find_slateos_sysroot_lib()
    if real_sysroot is None:
        pytest.skip("no SlateOS libc.a (set FASTPY_SLATEOS_SYSROOT)")

    system = tmp_path / "usr" / "lib" / "x86_64-slateos"
    system.mkdir(parents=True)
    shutil.copyfile(real_sysroot / "libc.a", system / "libc.a")
    toolchain.build_slateos_runtime_archive(system / toolchain.SLATEOS_RUNTIME_ARCHIVE)
    ir = CodeGen().generate(ast.parse(_PROGRAM))

    def forbidden(*args, **kwargs):
        raise AssertionError("the SlateOS route must not build or find this")

    monkeypatch.delenv("FASTPY_SLATEOS_SYSROOT", raising=False)
    monkeypatch.setattr(toolchain, "IS_SLATEOS", True)
    monkeypatch.setattr(toolchain, "SLATEOS_SYSTEM_LIB_DIR", system)
    monkeypatch.setattr(toolchain, "ensure_slateos_runtime_built", forbidden)
    monkeypatch.setattr(toolchain, "resolve_python", forbidden)

    # Named like an object on purpose: the intermediate object must not be
    # mistaken for it and deleted.
    out = tmp_path / "prog.o"
    exe = toolchain.compile_and_link(ir, out, python_version="3.99")
    assert exe == out
    data = exe.read_bytes()
    assert data[:4] == _ELF_MAGIC
    e_type, e_machine = struct.unpack_from("<HH", data, 16)
    e_entry = struct.unpack_from("<Q", data, 24)[0]
    assert (e_type, e_machine) == (_ET_EXEC, _EM_X86_64)
    assert e_entry != 0, "no _start: libc.a's crt was not linked"
    assert len(data) > 100_000
    assert sorted(p.name for p in tmp_path.iterdir()) == ["prog.o", "usr"], \
        "the intermediate object was left beside the output"


# -------------------------------------------------------- the default output

def test_an_unwritable_install_builds_in_the_temp_directory(monkeypatch):
    """With no `-o`, the pipeline builds in `<fastpy>/.build`; an installed
    compiler may not write there (SlateOS installs it in /usr/lib/fastpy)."""
    from compiler import pipeline

    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(suffix=None, prefix=None, dir=None):
        if dir is not None and Path(dir).name == ".build":
            raise PermissionError(13, "Permission denied", str(dir))
        return real_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    seen: dict[str, Path] = {}

    def compile_and_link(ir_string, output, **kwargs):
        seen["output"] = output
        output.write_bytes(b"")
        return output

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(toolchain, "compile_and_link", compile_and_link)
    result = pipeline.compile_source("print(1)\n")
    try:
        assert result.success, result.errors
        assert Path(tempfile.gettempdir()).resolve() in seen["output"].resolve().parents
    finally:
        if "output" in seen:
            shutil.rmtree(seen["output"].parent, ignore_errors=True)
