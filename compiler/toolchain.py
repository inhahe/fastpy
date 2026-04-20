"""
Build toolchain — compiles LLVM IR to object files and links with the
C runtime to produce native executables.

On Windows, uses MSVC (cl.exe + link.exe) via vcvars64.bat.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import llvmlite.binding as llvm

# Initialize LLVM targets (required before any target operations)
llvm.initialize_native_target()
llvm.initialize_native_asmprinter()

# Path to the pre-compiled runtime object files
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = _PROJECT_ROOT / "runtime"
RUNTIME_OBJS = [RUNTIME_DIR / "runtime.obj", RUNTIME_DIR / "objects.obj",
                RUNTIME_DIR / "cpython_bridge.obj", RUNTIME_DIR / "threading.obj",
                RUNTIME_DIR / "gc.obj"]

# CPython library for linking (needed for .pyd import support)
PYTHON_LIB_DIR = Path(r"D:\python314\libs")
PYTHON_LIB = "python314.lib"
RUNTIME_BUILD_BAT = RUNTIME_DIR / "build_runtime.bat"


def ensure_runtime_built() -> list[Path]:
    """Ensure the C runtime is compiled. Returns list of .obj paths."""
    if all(obj.exists() for obj in RUNTIME_OBJS):
        return RUNTIME_OBJS

    # Try to build it
    if RUNTIME_BUILD_BAT.exists():
        result = subprocess.run(
            ["cmd.exe", "/c", str(RUNTIME_BUILD_BAT)],
            capture_output=True,
            text=True,
        )
        if all(obj.exists() for obj in RUNTIME_OBJS):
            return RUNTIME_OBJS
        raise RuntimeError(
            f"Failed to build runtime: {result.stdout}\n{result.stderr}"
        )

    raise FileNotFoundError(f"Runtime objects not found: {RUNTIME_OBJS}")


def compile_ir_to_obj(ir_string: str, output_path: Path) -> Path:
    """
    Compile LLVM IR text to a native object file.

    Runs IR-level optimization passes (-O2 equivalent) before backend
    codegen: inlining, GVN, dead-code elimination, loop opts, etc.

    Args:
        ir_string: LLVM IR as a string.
        output_path: Path for the output .obj file.

    Returns:
        Path to the generated object file.
    """
    # Parse the IR
    mod = llvm.parse_assembly(ir_string)
    mod.verify()

    # Create target machine (backend-level opts)
    target = llvm.Target.from_default_triple()
    target_machine = target.create_target_machine(
        opt=2,  # -O2 backend codegen
        reloc="default",
        codemodel="default",
    )

    # Run IR-level optimization passes (-O2 pipeline).
    # Uses the new LLVM pass manager API (PassBuilder + PipelineTuningOptions).
    pto = llvm.PipelineTuningOptions(speed_level=2, size_level=0)
    pto.inlining_threshold = 225  # standard -O2 inlining
    pb = llvm.create_pass_builder(target_machine, pto)
    mpm = pb.getModulePassManager()
    mpm.run(mod, pb)

    # Emit object code
    obj_data = target_machine.emit_object(mod)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(obj_data)
    return output_path


def link_executable(
    obj_files: list[Path],
    output_path: Path,
) -> Path:
    """
    Link object files into a native executable using MSVC's link.exe.

    Args:
        obj_files: List of .obj files to link.
        output_path: Path for the output .exe file.

    Returns:
        Path to the generated executable.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a batch script that sets up MSVC env and links
    obj_list = " ".join(f'"{p}"' for p in obj_files)
    out_str = str(output_path)

    bat_content = (
        '@echo off\r\n'
        'call "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community'
        '\\VC\\Auxiliary\\Build\\vcvars64.bat" 1>NUL 2>NUL\r\n'
        'if errorlevel 1 (\r\n'
        '    call "C:\\Program Files\\Microsoft Visual Studio\\2022\\Enterprise'
        '\\VC\\Auxiliary\\Build\\vcvars64.bat" 1>NUL 2>NUL\r\n'
        ')\r\n'
        f'link.exe /NOLOGO /OUT:"{out_str}" {obj_list} '
        f'/LIBPATH:"{PYTHON_LIB_DIR}" {PYTHON_LIB} '
        '/DEFAULTLIB:ucrt /DEFAULTLIB:msvcrt '
        '/DEFAULTLIB:legacy_stdio_definitions '
        '/SUBSYSTEM:CONSOLE\r\n'
        'if errorlevel 1 (\r\n'
        '    echo LINK_FAILED\r\n'
        '    exit /b 1\r\n'
        ')\r\n'
        'echo LINK_OK\r\n'
    )

    # Write to temp bat file
    bat_path = output_path.parent / "_link.bat"
    bat_path.write_text(bat_content, encoding="ascii")

    try:
        result = subprocess.run(
            ["cmd.exe", "/c", str(bat_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if "LINK_FAILED" in result.stdout or result.returncode != 0:
            raise RuntimeError(
                f"Linking failed:\n{result.stdout}\n{result.stderr}"
            )

        if not output_path.exists():
            raise RuntimeError(
                f"Link appeared to succeed but {output_path} not found.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

        return output_path
    finally:
        if bat_path.exists():
            bat_path.unlink()


def compile_and_link(ir_string: str, output_path: Path) -> Path:
    """
    Full pipeline: LLVM IR string → object file → linked executable.

    Args:
        ir_string: LLVM IR as a string.
        output_path: Path for the output .exe file.

    Returns:
        Path to the generated executable.
    """
    runtime_objs = ensure_runtime_built()

    # Compile IR to obj in same directory as output
    ir_obj = output_path.with_suffix(".obj")
    compile_ir_to_obj(ir_string, ir_obj)

    try:
        return link_executable([ir_obj] + runtime_objs, output_path)
    finally:
        # Clean up intermediate obj
        if ir_obj.exists():
            ir_obj.unlink()
