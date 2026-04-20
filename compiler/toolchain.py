"""
Build toolchain — compiles LLVM IR to object files and links with the
C runtime to produce native executables.

On Windows, uses MSVC (cl.exe + link.exe) via vcvars64.bat.
On Linux/macOS, uses cc (gcc/clang) for compilation and linking.
"""

from __future__ import annotations

import os
import sys
import subprocess
import sysconfig
import tempfile
from pathlib import Path

import llvmlite.binding as llvm

# Initialize LLVM targets (required before any target operations)
llvm.initialize_native_target()
llvm.initialize_native_asmprinter()

# --- Platform detection ---
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# --- Object file extension ---
OBJ_EXT = ".obj" if IS_WINDOWS else ".o"
EXE_EXT = ".exe" if IS_WINDOWS else ""

# Path to the pre-compiled runtime object files
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = _PROJECT_ROOT / "runtime"
_RUNTIME_NAMES = ["runtime", "objects", "cpython_bridge", "threading", "gc", "bigint"]
RUNTIME_OBJS = [RUNTIME_DIR / (name + OBJ_EXT) for name in _RUNTIME_NAMES]

# --- CPython library for linking ---
def _find_python_lib_dir() -> Path:
    if IS_WINDOWS:
        return Path(sys.prefix) / "libs"
    else:
        libdir = sysconfig.get_config_var("LIBDIR")
        return Path(libdir) if libdir else Path("/usr/lib")

def _find_python_lib_name() -> str:
    if IS_WINDOWS:
        ver = f"{sys.version_info.major}{sys.version_info.minor}"
        return f"python{ver}.lib"
    else:
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        return f"python{ver}"

PYTHON_LIB_DIR = _find_python_lib_dir()
PYTHON_LIB = _find_python_lib_name()

# --- Runtime build scripts ---
RUNTIME_BUILD_BAT = RUNTIME_DIR / "build_runtime.bat"
RUNTIME_BUILD_SH = RUNTIME_DIR / "build_runtime.sh"


def ensure_runtime_built() -> list[Path]:
    """Ensure the C runtime is compiled. Returns list of .obj/.o paths."""
    if all(obj.exists() for obj in RUNTIME_OBJS):
        return RUNTIME_OBJS

    if IS_WINDOWS:
        if RUNTIME_BUILD_BAT.exists():
            result = subprocess.run(
                ["cmd.exe", "/c", str(RUNTIME_BUILD_BAT)],
                capture_output=True, text=True,
            )
    else:
        if RUNTIME_BUILD_SH.exists():
            result = subprocess.run(
                ["bash", str(RUNTIME_BUILD_SH)],
                capture_output=True, text=True,
            )
        else:
            raise FileNotFoundError(
                f"Runtime build script not found: {RUNTIME_BUILD_SH}")

    if all(obj.exists() for obj in RUNTIME_OBJS):
        return RUNTIME_OBJS

    stdout = result.stdout if 'result' in dir() else ""
    stderr = result.stderr if 'result' in dir() else ""
    raise RuntimeError(
        f"Failed to build runtime:\n{stdout}\n{stderr}")


def compile_ir_to_obj(ir_string: str, output_path: Path) -> Path:
    """
    Compile LLVM IR text to a native object file.

    Runs IR-level optimization passes (-O2 equivalent) before backend
    codegen: inlining, GVN, dead-code elimination, loop opts, etc.

    Args:
        ir_string: LLVM IR as a string.
        output_path: Path for the output object file.

    Returns:
        Path to the generated object file.
    """
    # Parse the IR
    mod = llvm.parse_assembly(ir_string)
    mod.verify()

    # Create target machine (backend-level opts)
    # Use PIC relocation on POSIX (required for ASLR and shared objects)
    target = llvm.Target.from_default_triple()
    target_machine = target.create_target_machine(
        opt=2,  # -O2 backend codegen
        reloc="pic" if not IS_WINDOWS else "default",
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


def _link_windows(obj_files: list[Path], output_path: Path) -> Path:
    """Link object files using MSVC's link.exe (Windows)."""
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

    bat_path = output_path.parent / "_link.bat"
    bat_path.write_text(bat_content, encoding="ascii")

    try:
        result = subprocess.run(
            ["cmd.exe", "/c", str(bat_path)],
            capture_output=True, text=True, timeout=30,
        )
        if "LINK_FAILED" in result.stdout or result.returncode != 0:
            raise RuntimeError(
                f"Linking failed:\n{result.stdout}\n{result.stderr}")
        if not output_path.exists():
            raise RuntimeError(
                f"Link appeared to succeed but {output_path} not found.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}")
        return output_path
    finally:
        if bat_path.exists():
            bat_path.unlink()


def _link_posix(obj_files: list[Path], output_path: Path) -> Path:
    """Link object files using cc (gcc/clang) on Linux/macOS."""
    import shutil
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise RuntimeError("No C compiler found. Install gcc or clang.")

    cmd = [cc, "-o", str(output_path)]
    cmd += [str(p) for p in obj_files]
    cmd += [f"-L{PYTHON_LIB_DIR}", f"-l{PYTHON_LIB}"]
    cmd += ["-lm", "-ldl"]
    if IS_LINUX:
        cmd += ["-lpthread"]
    # Add rpath so the executable can find libpython at runtime
    if IS_MACOS:
        cmd += ["-Wl,-rpath,@executable_path"]
    else:
        cmd += ["-Wl,-rpath,$ORIGIN"]
        cmd += [f"-Wl,-rpath,{PYTHON_LIB_DIR}"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(
            f"Linking failed:\n{result.stdout}\n{result.stderr}")
    if not output_path.exists():
        raise RuntimeError(
            f"Link appeared to succeed but {output_path} not found.")
    return output_path


def link_executable(
    obj_files: list[Path],
    output_path: Path,
) -> Path:
    """
    Link object files into a native executable.

    On Windows, uses MSVC link.exe. On Linux/macOS, uses cc (gcc/clang).

    Args:
        obj_files: List of object files to link.
        output_path: Path for the output executable.

    Returns:
        Path to the generated executable.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if IS_WINDOWS:
        return _link_windows(obj_files, output_path)
    else:
        return _link_posix(obj_files, output_path)


def compile_and_link(ir_string: str, output_path: Path) -> Path:
    """
    Full pipeline: LLVM IR string → object file → linked executable.

    Args:
        ir_string: LLVM IR as a string.
        output_path: Path for the output executable.

    Returns:
        Path to the generated executable.
    """
    runtime_objs = ensure_runtime_built()

    # Compile IR to obj in same directory as output
    ir_obj = output_path.with_suffix(OBJ_EXT)
    compile_ir_to_obj(ir_string, ir_obj)

    try:
        return link_executable([ir_obj] + runtime_objs, output_path)
    finally:
        # Clean up intermediate obj
        if ir_obj.exists():
            ir_obj.unlink()
