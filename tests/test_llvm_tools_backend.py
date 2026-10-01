"""
The tools backend: LLVM reached through its own programs, `opt` and `llc`,
instead of in-process through `llvmlite.binding`.

It exists for systems with no dynamic linker, where llvmlite.binding cannot
load -- SlateOS links every program statically -- and is selected there
automatically. Anywhere else `FASTPY_LLVM_BACKEND=tools` selects it, which is
how these tests exercise it: the unit tests need nothing installed, the object
tests need `opt` and `llc` on PATH (versioned names such as `opt-18` count),
and the end-to-end test compiles one program both ways and compares what the
two executables print.
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from compiler import toolchain

_TRIVIAL_IR = """; ModuleID = "m"
target triple = "x86_64-pc-windows-msvc"
target datalayout = "e-m:w-x"

define i32 @main() {
entry:
  ret i32 0
}
"""


def _tools_available() -> bool:
    try:
        toolchain._find_llvm_tool("opt")
        toolchain._find_llvm_tool("llc")
    except FileNotFoundError:
        return False
    return True


needs_tools = pytest.mark.skipif(
    not _tools_available(), reason="LLVM's opt and llc are not on PATH"
)


# --------------------------------------------------------------- unit tests

def test_retarget_replaces_the_triple_and_layout():
    out = toolchain._retarget_ir(_TRIVIAL_IR, "x86_64-unknown-linux-musl", "e-L")
    assert 'target triple = "x86_64-unknown-linux-musl"' in out
    assert 'target datalayout = "e-L"' in out
    assert "windows" not in out
    assert "e-m:w-x" not in out
    # Still one of each, after the ModuleID comment, where llvmlite puts them.
    lines = out.split("\n")
    assert lines[0].startswith("; ModuleID")
    assert lines[1].startswith("target triple = ")
    assert sum(line.startswith("target triple = ") for line in lines) == 1


def test_retarget_adds_them_when_absent():
    out = toolchain._retarget_ir("define void @f() {\n  ret void\n}\n", "t", "l")
    assert out.startswith('target triple = "t"\ntarget datalayout = "l"\n')


def test_the_backend_is_chosen_by_the_environment(monkeypatch):
    monkeypatch.setenv("FASTPY_LLVM_BACKEND", "tools")
    assert toolchain.llvm_backend() == "tools"
    monkeypatch.setenv("FASTPY_LLVM_BACKEND", "LLVMLITE")
    assert toolchain.llvm_backend() == "llvmlite"
    monkeypatch.setenv("FASTPY_LLVM_BACKEND", "auto")
    expected = "llvmlite" if toolchain._binding() is not None else "tools"
    assert toolchain.llvm_backend() == expected
    monkeypatch.delenv("FASTPY_LLVM_BACKEND")
    assert toolchain.llvm_backend() == expected


def test_a_misspelt_backend_is_an_error(monkeypatch):
    monkeypatch.setenv("FASTPY_LLVM_BACKEND", "tool")
    with pytest.raises(ValueError, match="FASTPY_LLVM_BACKEND"):
        toolchain.llvm_backend()


def _executable(directory: Path, name: str) -> Path:
    path = directory / (name + toolchain.EXE_EXT)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_the_tool_directory_is_looked_in_first(monkeypatch, tmp_path):
    tool = _executable(tmp_path, "opt")
    monkeypatch.setenv("FASTPY_LLVM_BIN", str(tmp_path))
    assert toolchain._find_llvm_tool("opt") == str(tool)
    # A directory that lacks it is an error, not a fall-back to PATH: the
    # setting says where the tools are.
    with pytest.raises(FileNotFoundError, match="FASTPY_LLVM_BIN"):
        toolchain._find_llvm_tool("llc")


def test_the_newest_versioned_tool_is_found(monkeypatch, tmp_path):
    _executable(tmp_path, "opt-17")
    newest = _executable(tmp_path, "opt-18")
    monkeypatch.delenv("FASTPY_LLVM_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert toolchain._find_llvm_tool("opt") == str(newest)


def test_a_missing_tool_says_how_to_supply_it(monkeypatch, tmp_path):
    monkeypatch.delenv("FASTPY_LLVM_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="FASTPY_LLVM_BIN"):
        toolchain._find_llvm_tool("llc")


# ------------------------------------------------------------- object tests

@needs_tools
def test_the_slateos_target_emits_its_elf_object_through_the_tools(monkeypatch):
    monkeypatch.setenv("FASTPY_LLVM_BACKEND", "tools")
    out = Path(tempfile.mkdtemp(prefix="fastpy_tools_")) / "slate.o"
    data = toolchain.compile_ir_to_obj(_TRIVIAL_IR, out, target=toolchain.SLATEOS_TARGET).read_bytes()
    assert data[:4] == b"\x7fELF"
    e_type, e_machine = struct.unpack_from("<HH", data, 16)
    assert (data[4], data[5], e_type, e_machine) == (2, 1, 1, 62)


@needs_tools
def test_the_host_target_emits_an_object_through_the_tools(monkeypatch):
    monkeypatch.setenv("FASTPY_LLVM_BACKEND", "tools")
    ir = toolchain._retarget_ir(
        _TRIVIAL_IR, toolchain.host_triple(),
        toolchain.host_data_layout(toolchain.host_triple()),
    )
    out = Path(tempfile.mkdtemp(prefix="fastpy_tools_")) / ("host" + toolchain.OBJ_EXT)
    data = toolchain.compile_ir_to_obj(ir, out).read_bytes()
    if toolchain.IS_LINUX:
        assert data[:4] == b"\x7fELF"
    elif toolchain.IS_WINDOWS:
        assert struct.unpack_from("<H", data, 0)[0] == 0x8664  # COFF, x86-64
    assert len(data) > 0


@needs_tools
def test_bad_ir_reports_the_tools_error(monkeypatch):
    monkeypatch.setenv("FASTPY_LLVM_BACKEND", "tools")
    out = Path(tempfile.mkdtemp(prefix="fastpy_tools_")) / "bad.o"
    with pytest.raises(RuntimeError, match="opt"):
        toolchain.compile_ir_to_obj("this is not IR\n", out, target=toolchain.SLATEOS_TARGET)


# ------------------------------------------------------------ end to end

_PROGRAM = """
xs = [1, 2, 3]
total = 0
for x in xs:
    total += x * x
print("squares", total)
print({"a": 1, "b": 2}["b"], len("fastpy"))
"""


@pytest.mark.slow
@needs_tools
@pytest.mark.skipif(toolchain._binding() is None, reason="llvmlite is needed to compare against")
def test_one_program_compiles_alike_both_ways(tmp_path):
    src = tmp_path / "prog.py"
    src.write_text(_PROGRAM, encoding="utf-8")
    root = Path(__file__).resolve().parent.parent
    outputs = {}
    for backend in ("llvmlite", "tools"):
        exe = tmp_path / ("prog_" + backend + toolchain.EXE_EXT)
        env = dict(os.environ, FASTPY_LLVM_BACKEND=backend)
        build = subprocess.run(
            [sys.executable, "-m", "compiler", str(src), "-o", str(exe)],
            cwd=root, env=env, capture_output=True, text=True, timeout=900,
        )
        assert build.returncode == 0, build.stderr
        ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        assert ran.returncode == 0, ran.stderr
        outputs[backend] = ran.stdout
    assert outputs["tools"] == outputs["llvmlite"] == "squares 14\n2 6\n"
