"""
Build toolchain — compiles LLVM IR to object files and links with the
C runtime to produce native executables.

On Windows, uses MSVC (cl.exe + link.exe) via vcvars64.bat.
On Linux/macOS, uses cc (gcc/clang) for compilation and linking.

Supports multi-Python-version targeting: cpython_bridge.c is compiled
per Python version (with the correct include path and PYTHON_HOME_STR),
while the Python-independent runtime files are shared.
"""

from __future__ import annotations

import os
import sys
import subprocess
import sysconfig
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional  # used in _probe_python_install return type

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

# Shared (Python-independent) runtime files
_SHARED_RUNTIME_NAMES = ["runtime", "objects", "threading", "gc", "bigint"]
SHARED_RUNTIME_OBJS = [RUNTIME_DIR / (name + OBJ_EXT) for name in _SHARED_RUNTIME_NAMES]

# Legacy flat layout for backward compatibility
_LEGACY_RUNTIME_NAMES = ["runtime", "objects", "cpython_bridge", "threading", "gc", "bigint"]
_LEGACY_RUNTIME_OBJS = [RUNTIME_DIR / (name + OBJ_EXT) for name in _LEGACY_RUNTIME_NAMES]


# --- Python installation descriptor ---
@dataclass
class PythonInstall:
    """Describes a discovered Python installation."""
    version: tuple[int, int]       # e.g. (3, 14)
    executable: Path               # e.g. D:\python314\python.exe
    include_dir: Path              # e.g. D:\python314\include
    lib_dir: Path                  # e.g. D:\python314\libs
    prefix: Path                   # e.g. D:\python314
    stdlib_dir: Path | None = None # e.g. D:\python314\Lib

    @property
    def version_str(self) -> str:
        return f"{self.version[0]}.{self.version[1]}"

    @property
    def version_tag(self) -> str:
        """Short tag for directory naming: 'py312', 'py314', etc."""
        return f"py{self.version[0]}{self.version[1]}"

    @property
    def lib_name(self) -> str:
        """The library file/name to link against."""
        if IS_WINDOWS:
            return f"python{self.version[0]}{self.version[1]}.lib"
        else:
            return f"python{self.version[0]}.{self.version[1]}"

    def __repr__(self) -> str:
        return f"PythonInstall({self.version_str} at {self.prefix})"


def _probe_python_install(executable: Path) -> Optional[PythonInstall]:
    """Probe a Python executable to extract version, include dir, lib dir, and prefix.

    Returns a PythonInstall if the executable is valid and has development
    headers, or None if it cannot be used for compilation.
    """
    exe = Path(executable)
    if not exe.exists():
        return None

    try:
        result = subprocess.run(
            [str(exe), "-c",
             "import sys, sysconfig; "
             "print(sys.version_info.major); "
             "print(sys.version_info.minor); "
             "print(sysconfig.get_path('include')); "
             "print(sys.prefix)"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
    except (subprocess.TimeoutExpired, OSError):
        return None

    lines = result.stdout.strip().splitlines()
    if len(lines) < 4:
        return None

    major, minor = int(lines[0]), int(lines[1])
    include_dir = Path(lines[2])
    prefix = Path(lines[3])

    # Verify the include directory actually has Python.h
    if not (include_dir / "Python.h").exists():
        return None

    # Determine lib directory
    if IS_WINDOWS:
        lib_dir = prefix / "libs"
    else:
        # Query sysconfig for LIBDIR and LDLIBRARY. Relocatable Python
        # distributions (e.g. python-build-standalone) bake in their
        # original build-time LIBDIR (like "/install/lib") that doesn't
        # exist on the target system — so we need to verify the reported
        # directory actually contains libpythonX.Y.so, and fall back to
        # the commonly correct locations if not.
        ver_str = f"{major}.{minor}"
        so_basenames = [
            f"libpython{ver_str}.so",
            f"libpython{ver_str}.dylib",  # macOS
            f"libpython{ver_str}.a",
        ]

        def _has_libpython(d: Path) -> bool:
            return any((d / name).exists() for name in so_basenames)

        lib_dir = None
        # 1. Try reported LIBDIR
        try:
            r2 = subprocess.run(
                [str(exe), "-c",
                 "import sysconfig; print(sysconfig.get_config_var('LIBDIR') or '')"],
                capture_output=True, text=True, timeout=5,
            )
            reported = r2.stdout.strip()
            if reported and Path(reported).is_dir() and _has_libpython(Path(reported)):
                lib_dir = Path(reported)
        except (subprocess.TimeoutExpired, OSError):
            pass

        # 2. Try {prefix}/lib (python-build-standalone, relocatable installs)
        if lib_dir is None:
            candidate = prefix / "lib"
            if _has_libpython(candidate):
                lib_dir = candidate

        # 3. Try /usr/lib/x86_64-linux-gnu (Debian/Ubuntu multiarch)
        if lib_dir is None:
            for candidate in [
                Path("/usr/lib/x86_64-linux-gnu"),
                Path("/usr/lib64"),
                Path("/usr/lib"),
                Path("/usr/local/lib"),
            ]:
                if _has_libpython(candidate):
                    lib_dir = candidate
                    break

        # 4. Final fallback — probably won't link, but don't crash probe
        if lib_dir is None:
            lib_dir = Path("/usr/lib")

    return PythonInstall(
        version=(major, minor),
        executable=exe,
        include_dir=include_dir,
        lib_dir=lib_dir,
        prefix=prefix,
    )


def _current_python_install() -> PythonInstall:
    """Build a PythonInstall for the currently running Python (no subprocess)."""
    include = Path(sysconfig.get_path("include"))
    prefix = Path(sys.prefix)
    stdlib_dir = Path(sysconfig.get_path("stdlib"))
    if IS_WINDOWS:
        lib_dir = prefix / "libs"
    else:
        libdir = sysconfig.get_config_var("LIBDIR")
        lib_dir = Path(libdir) if libdir else Path("/usr/lib")
    return PythonInstall(
        version=(sys.version_info.major, sys.version_info.minor),
        executable=Path(sys.executable),
        include_dir=include,
        lib_dir=lib_dir,
        prefix=prefix,
        stdlib_dir=stdlib_dir,
    )


def discover_pythons() -> list[PythonInstall]:
    """Discover installed Python versions on the system.

    Returns a deduplicated list of PythonInstall objects sorted by version,
    covering the currently running Python plus any found via common paths
    and the system PATH.

    Windows search locations:
        - D:\\pythonXXX\\ (common manual installs)
        - C:\\PythonXX\\
        - %LOCALAPPDATA%\\Programs\\Python\\PythonXX\\
        - python.exe / python3.exe on PATH
        - Windows registry (PythonCore entries)

    Linux/macOS search locations:
        - python3.XX on PATH for XX in 8..20
        - /usr/bin/python3.XX, /usr/local/bin/python3.XX
    """
    seen_versions: dict[tuple[int, int], PythonInstall] = {}

    # Always include the current Python first
    current = _current_python_install()
    seen_versions[current.version] = current

    def _try_add(exe_path: Path | str) -> None:
        p = Path(exe_path)
        if not p.exists():
            return
        # Skip Windows Store stubs — they are slow and may open the Store app
        p_str = str(p)
        if "WindowsApps" in p_str or "PythonSoftwareFoundation" in p_str:
            return
        install = _probe_python_install(p)
        if install and install.version not in seen_versions:
            seen_versions[install.version] = install

    if IS_WINDOWS:
        # Common Windows install directories
        for drive in ["C:", "D:", "E:"]:
            for minor in range(8, 21):
                # D:\python312, D:\python313, D:\python314, etc.
                _try_add(Path(f"{drive}\\python3{minor}\\python.exe"))
                # D:\Python312, etc. (case variant)
                _try_add(Path(f"{drive}\\Python3{minor}\\python.exe"))

        # AppData local installs
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            programs_py = Path(local_appdata) / "Programs" / "Python"
            if programs_py.exists():
                for d in programs_py.iterdir():
                    if d.is_dir():
                        _try_add(d / "python.exe")
            # Also check the newer Python install layout
            py_bin = Path(local_appdata) / "Python" / "bin"
            if py_bin.exists():
                _try_add(py_bin / "python.exe")

        # python / python3 on PATH (via `where`)
        import shutil
        for name in ["python", "python3"]:
            exe = shutil.which(name)
            if exe:
                _try_add(exe)

        # Windows registry discovery
        try:
            import winreg
            for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                try:
                    key = winreg.OpenKey(hive, r"SOFTWARE\Python\PythonCore")
                    i = 0
                    while True:
                        try:
                            ver_str = winreg.EnumKey(key, i)
                        except OSError:
                            break  # no more entries
                        try:
                            install_key = winreg.OpenKey(
                                key, f"{ver_str}\\InstallPath")
                            install_path, _ = winreg.QueryValueEx(
                                install_key, "")
                            _try_add(Path(install_path) / "python.exe")
                            winreg.CloseKey(install_key)
                        except OSError:
                            pass  # this version has no InstallPath
                        i += 1
                    winreg.CloseKey(key)
                except OSError:
                    pass  # PythonCore key doesn't exist in this hive
        except ImportError:
            pass  # winreg not available (non-Windows)

    else:
        # Linux / macOS: check pythonX.Y on PATH and common locations
        import shutil
        for minor in range(8, 21):
            name = f"python3.{minor}"
            exe = shutil.which(name)
            if exe:
                _try_add(exe)
            # Common system locations
            for prefix in ["/usr/bin", "/usr/local/bin", "/opt/local/bin"]:
                _try_add(Path(prefix) / name)

    # Sort by version
    return sorted(seen_versions.values(), key=lambda p: p.version)


def resolve_python(python_version: str | None = None,
                   python_exe: str | Path | None = None) -> PythonInstall:
    """Resolve a Python version specifier or executable path to a PythonInstall.

    Args:
        python_version: Version string like "3.12", "3.14", "312", "314".
            If None and python_exe is None, uses the current Python.
        python_exe: Explicit path to a Python executable. Overrides python_version.

    Returns:
        PythonInstall for the resolved Python.

    Raises:
        ValueError: If the requested version cannot be found.
    """
    if python_exe is not None:
        install = _probe_python_install(Path(python_exe))
        if install is None:
            raise ValueError(
                f"Cannot use Python at {python_exe}: "
                "not found, not working, or missing development headers (Python.h)")
        return install

    if python_version is None:
        return _current_python_install()

    # Parse version string: "3.12", "312", "3.14", etc.
    ver = python_version.strip()
    if "." in ver:
        parts = ver.split(".")
        target = (int(parts[0]), int(parts[1]))
    elif len(ver) == 3 and ver.isdigit():
        # "312" -> (3, 12)
        target = (int(ver[0]), int(ver[1:]))
    elif len(ver) == 2 and ver.isdigit():
        # "14" -> (3, 14) (assume Python 3)
        target = (3, int(ver))
    else:
        raise ValueError(f"Cannot parse Python version: {python_version!r}")

    # Check if current Python matches
    current = _current_python_install()
    if current.version == target:
        return current

    # Search discovered Pythons
    for install in discover_pythons():
        if install.version == target:
            return install

    raise ValueError(
        f"Python {target[0]}.{target[1]} not found. "
        f"Available: {', '.join(p.version_str for p in discover_pythons())}")


# --- CPython library for linking ---
def _find_python_lib_dir(install: PythonInstall | None = None) -> Path:
    if install is not None:
        return install.lib_dir
    if IS_WINDOWS:
        return Path(sys.prefix) / "libs"
    else:
        libdir = sysconfig.get_config_var("LIBDIR")
        return Path(libdir) if libdir else Path("/usr/lib")

def _find_python_lib_name(install: PythonInstall | None = None) -> str:
    if install is not None:
        return install.lib_name
    if IS_WINDOWS:
        ver = f"{sys.version_info.major}{sys.version_info.minor}"
        return f"python{ver}.lib"
    else:
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        return f"python{ver}"


def _version_bridge_obj(install: PythonInstall) -> Path:
    """Path to the version-specific cpython_bridge object file."""
    return RUNTIME_DIR / install.version_tag / ("cpython_bridge" + OBJ_EXT)


def get_runtime_objs(install: PythonInstall | None = None) -> list[Path]:
    """Get the list of runtime object files for a given Python version.

    If a version-specific cpython_bridge object exists, uses that plus shared
    objects. Otherwise falls back to the legacy flat layout (all objects in
    runtime/).
    """
    if install is not None:
        versioned_bridge = _version_bridge_obj(install)
        if versioned_bridge.exists():
            return SHARED_RUNTIME_OBJS + [versioned_bridge]

    # Fall back to legacy flat layout
    return list(_LEGACY_RUNTIME_OBJS)


# --- Runtime build scripts (kept for manual use) ---
RUNTIME_BUILD_BAT = RUNTIME_DIR / "build_runtime.bat"
RUNTIME_BUILD_SH = RUNTIME_DIR / "build_runtime.sh"


def _find_msvc_cl() -> str | None:
    """Find cl.exe by setting up MSVC environment via vcvars64.bat.

    Returns a bat preamble string that sets up the environment, or None
    if MSVC cannot be found. Searches VS 2026, 2025, 2024, 2022 in order
    so the newest available version is preferred.
    """
    for year in ["2026", "2025", "2024", "2022"]:
        for edition in ["Community", "Enterprise", "Professional", "BuildTools"]:
            vcvars = (
                f"C:\\Program Files\\Microsoft Visual Studio\\{year}\\{edition}"
                f"\\VC\\Auxiliary\\Build\\vcvars64.bat"
            )
            if Path(vcvars).exists():
                return f'call "{vcvars}" 1>NUL 2>NUL'
    return None


def _obj_is_current(src: Path, obj: Path) -> bool:
    """Check if an object file exists and is newer than its source."""
    if not obj.exists():
        return False
    return obj.stat().st_mtime >= src.stat().st_mtime


def _compile_shared_runtime_windows(vcvars_cmd: str) -> None:
    """Build the shared (Python-independent) runtime .obj files on Windows."""
    c_files = {
        "runtime":   RUNTIME_DIR / "runtime.c",
        "objects":   RUNTIME_DIR / "objects.c",
        "threading": RUNTIME_DIR / "threading.c",
        "gc":        RUNTIME_DIR / "gc.c",
        "bigint":    RUNTIME_DIR / "bigint.c",
    }
    for name, src in c_files.items():
        obj = RUNTIME_DIR / f"{name}.obj"
        if _obj_is_current(src, obj):
            continue
        bat_content = (
            f"@echo off\r\n"
            f"{vcvars_cmd}\r\n"
            f'cd /d "{RUNTIME_DIR}"\r\n'
            f'cl.exe /c /O2 /nologo {src.name} /Fo"{obj}"\r\n'
            f"if errorlevel 1 exit /b 1\r\n"
        )
        bat_path = RUNTIME_DIR / "_build_tmp.bat"
        bat_path.write_text(bat_content, encoding="ascii")
        try:
            result = subprocess.run(
                ["cmd.exe", "/c", str(bat_path.resolve())],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0 or not obj.exists():
                raise RuntimeError(
                    f"Failed to compile {src.name}:\n"
                    f"{result.stdout}\n{result.stderr}")
        finally:
            bat_path.unlink(missing_ok=True)


def _compile_bridge_windows(vcvars_cmd: str, install: PythonInstall) -> Path:
    """Compile cpython_bridge.c for a specific Python version on Windows.

    Produces runtime/py3XX/cpython_bridge.obj.
    Returns the path to the compiled object file.
    """
    out_dir = RUNTIME_DIR / install.version_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_obj = out_dir / "cpython_bridge.obj"
    bridge_src = RUNTIME_DIR / "cpython_bridge.c"

    if _obj_is_current(bridge_src, out_obj):
        return out_obj

    # For the C preprocessor, PYTHON_HOME_STR must be a string literal.
    # Passing quoted /D values through cmd.exe is unreliable because cmd
    # consumes the quotes. Instead, we use a cl.exe response file (@file)
    # which bypasses cmd's argument parsing entirely.
    pfx_str = str(install.prefix)
    # Double the backslashes for the C string literal
    pfx_c_escaped = pfx_str.replace("\\", "\\\\")

    inc_str = str(install.include_dir)
    out_str = str(out_obj)
    rt_str = str(RUNTIME_DIR)

    # Write cl.exe arguments to a response file.
    # Use backslash-escaped quotes (\") for the /D string value —
    # MSVC's response file parser treats \" as a literal quote character,
    # whereas bare " would be consumed as argument delimiters.
    rsp_path = RUNTIME_DIR / "_bridge_cl.rsp"
    rsp_content = (
        f'/c /O2 /nologo\n'
        f'/I "{inc_str}"\n'
        f'/DPYTHON_HOME_STR=\\"{pfx_c_escaped}\\"\n'
        f'cpython_bridge.c\n'
        f'/Fo"{out_str}"\n'
    )
    rsp_path.write_bytes(rsp_content.encode("ascii"))

    bat_lines = [
        "@echo off",
        vcvars_cmd,
        f'cd /d "{rt_str}"',
        f'cl.exe @"{rsp_path}"',
        "if errorlevel 1 exit /b 1",
    ]
    bat_bytes = b"\r\n".join(line.encode("ascii") for line in bat_lines) + b"\r\n"

    bat_path = RUNTIME_DIR / "_build_bridge_tmp.bat"
    bat_path.write_bytes(bat_bytes)
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", str(bat_path.resolve())],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not out_obj.exists():
            raise RuntimeError(
                f"Failed to compile cpython_bridge.c for "
                f"Python {install.version_str}:\n"
                f"{result.stdout}\n{result.stderr}")
    finally:
        bat_path.unlink(missing_ok=True)
        rsp_path.unlink(missing_ok=True)

    # Maintain legacy flat cpython_bridge.obj for backward compatibility
    legacy_obj = RUNTIME_DIR / "cpython_bridge.obj"
    if not legacy_obj.exists():
        import shutil
        shutil.copy2(out_obj, legacy_obj)

    return out_obj


def _compile_shared_runtime_posix() -> None:
    """Build the shared (Python-independent) runtime .o files on Linux/macOS."""
    import shutil
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise RuntimeError("No C compiler found. Install gcc or clang.")

    c_files = {
        "runtime":   RUNTIME_DIR / "runtime.c",
        "objects":   RUNTIME_DIR / "objects.c",
        "threading": RUNTIME_DIR / "threading.c",
        "gc":        RUNTIME_DIR / "gc.c",
        "bigint":    RUNTIME_DIR / "bigint.c",
    }
    for name, src in c_files.items():
        obj = RUNTIME_DIR / f"{name}.o"
        if _obj_is_current(src, obj):
            continue
        result = subprocess.run(
            [cc, "-c", "-O2", "-fPIC", str(src), "-o", str(obj)],
            capture_output=True, text=True, timeout=30,
            cwd=str(RUNTIME_DIR),
        )
        if result.returncode != 0 or not obj.exists():
            raise RuntimeError(
                f"Failed to compile {src.name}:\n"
                f"{result.stdout}\n{result.stderr}")


def _compile_bridge_posix(install: PythonInstall) -> Path:
    """Compile cpython_bridge.c for a specific Python version on POSIX.

    Produces runtime/py3XX/cpython_bridge.o.
    Returns the path to the compiled object file.
    """
    import shutil
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise RuntimeError("No C compiler found. Install gcc or clang.")

    out_dir = RUNTIME_DIR / install.version_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_obj = out_dir / "cpython_bridge.o"
    bridge_src = RUNTIME_DIR / "cpython_bridge.c"

    if _obj_is_current(bridge_src, out_obj):
        return out_obj

    python_home = str(install.prefix)

    result = subprocess.run(
        [cc, "-c", "-O2", "-fPIC",
         f"-I{install.include_dir}",
         f'-DPYTHON_HOME_STR="{python_home}"',
         "cpython_bridge.c",
         "-o", str(out_obj)],
        capture_output=True, text=True, timeout=30,
        cwd=str(RUNTIME_DIR),
    )
    if result.returncode != 0 or not out_obj.exists():
        raise RuntimeError(
            f"Failed to compile cpython_bridge.c for "
            f"Python {install.version_str}:\n"
            f"{result.stdout}\n{result.stderr}")

    # Maintain legacy flat cpython_bridge.o for backward compatibility
    legacy_obj = RUNTIME_DIR / "cpython_bridge.o"
    if not legacy_obj.exists():
        shutil.copy2(out_obj, legacy_obj)

    return out_obj


def ensure_runtime_built(python_exe: str | Path | None = None,
                         python_version: str | None = None) -> list[Path]:
    """Ensure the C runtime is compiled for the target Python. Returns list of
    .obj/.o paths.

    Builds shared (Python-independent) runtime files if needed, then builds
    the version-specific cpython_bridge for the target Python.

    Args:
        python_exe: Path to a specific Python executable to build against.
            If None and python_version is None, builds for the current Python.
        python_version: Version string like "3.12" to resolve and build for.
            Ignored if python_exe is provided.

    Returns:
        List of object file paths needed for linking.
    """
    install = resolve_python(python_version=python_version, python_exe=python_exe)

    # Check if the version-specific bridge exists and is up to date.
    versioned_bridge = _version_bridge_obj(install)
    bridge_src = RUNTIME_DIR / "cpython_bridge.c"
    need_bridge_build = not _obj_is_current(bridge_src, versioned_bridge)

    # Check shared objects — rebuild any that are missing or stale
    need_shared_build = not all(
        _obj_is_current(RUNTIME_DIR / (name + ".c"), obj)
        for name, obj in zip(_SHARED_RUNTIME_NAMES, SHARED_RUNTIME_OBJS)
    )

    if not need_bridge_build and not need_shared_build:
        return get_runtime_objs(install)

    # Build what's missing
    if IS_WINDOWS:
        vcvars_cmd = _find_msvc_cl()
        if vcvars_cmd is None:
            raise RuntimeError(
                "Cannot find MSVC (Visual Studio 2022 or later). "
                "Install Visual Studio with C++ workload.")

        if need_shared_build:
            _compile_shared_runtime_windows(vcvars_cmd)

        if need_bridge_build:
            _compile_bridge_windows(vcvars_cmd, install)
    else:
        if need_shared_build:
            _compile_shared_runtime_posix()

        if need_bridge_build:
            _compile_bridge_posix(install)

    # Re-check after build
    objs = get_runtime_objs(install)
    if all(obj.exists() for obj in objs):
        return objs

    missing = [str(o) for o in objs if not o.exists()]
    raise RuntimeError(
        f"Failed to build runtime for Python {install.version_str}. "
        f"Missing: {', '.join(missing)}")


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


def _link_windows(obj_files: list[Path], output_path: Path,
                   install: PythonInstall | None = None) -> Path:
    """Link object files using MSVC's link.exe (Windows)."""
    obj_list = " ".join(f'"{p}"' for p in obj_files)
    out_str = str(output_path)

    py_lib_dir = _find_python_lib_dir(install)
    py_lib = _find_python_lib_name(install)

    vcvars_cmd = _find_msvc_cl()
    if vcvars_cmd is None:
        raise RuntimeError(
            "Cannot find MSVC (Visual Studio 2022 or later). "
            "Install Visual Studio with C++ workload.")

    bat_content = (
        '@echo off\r\n'
        f'{vcvars_cmd}\r\n'
        f'link.exe /NOLOGO /OUT:"{out_str}" {obj_list} '
        f'/LIBPATH:"{py_lib_dir}" {py_lib} '
        '/DEFAULTLIB:ucrt /DEFAULTLIB:msvcrt '
        '/DEFAULTLIB:legacy_stdio_definitions '
        '/SUBSYSTEM:CONSOLE '
        '/EXPORT:fastpy_get_jit_symbols /EXPORT:fastpy_get_jit_symbol_count\r\n'
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
            ["cmd.exe", "/c", str(bat_path.resolve())],
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


def _link_posix(obj_files: list[Path], output_path: Path,
                install: PythonInstall | None = None) -> Path:
    """Link object files using cc (gcc/clang) on Linux/macOS."""
    import shutil
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise RuntimeError("No C compiler found. Install gcc or clang.")

    py_lib_dir = _find_python_lib_dir(install)
    py_lib = _find_python_lib_name(install)

    cmd = [cc, "-o", str(output_path)]
    cmd += [str(p) for p in obj_files]
    cmd += [f"-L{py_lib_dir}", f"-l{py_lib}"]
    cmd += ["-lm", "-ldl"]
    if IS_LINUX:
        cmd += ["-lpthread"]
    # Add rpath so the executable can find libpython at runtime
    if IS_MACOS:
        cmd += ["-Wl,-rpath,@executable_path"]
    else:
        cmd += ["-Wl,-rpath,$ORIGIN"]
        cmd += [f"-Wl,-rpath,{py_lib_dir}"]

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
    install: PythonInstall | None = None,
) -> Path:
    """
    Link object files into a native executable.

    On Windows, uses MSVC link.exe. On Linux/macOS, uses cc (gcc/clang).

    Args:
        obj_files: List of object files to link.
        output_path: Path for the output executable.
        install: PythonInstall to link against. If None, uses current Python.

    Returns:
        Path to the generated executable.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if IS_WINDOWS:
        return _link_windows(obj_files, output_path, install)
    else:
        return _link_posix(obj_files, output_path, install)


def compile_and_link(ir_string: str, output_path: Path,
                     python_version: str | None = None,
                     python_exe: str | Path | None = None) -> Path:
    """
    Full pipeline: LLVM IR string -> object file -> linked executable.

    Args:
        ir_string: LLVM IR as a string.
        output_path: Path for the output executable.
        python_version: Target Python version string (e.g. "3.12", "314").
            If None and python_exe is None, uses the current Python.
        python_exe: Explicit path to a Python executable to target.
            Overrides python_version.

    Returns:
        Path to the generated executable.
    """
    install = resolve_python(python_version=python_version, python_exe=python_exe)
    runtime_objs = ensure_runtime_built(
        python_exe=install.executable,
        python_version=None,  # already resolved
    )

    # Compile IR to obj in same directory as output
    ir_obj = output_path.with_suffix(OBJ_EXT)
    compile_ir_to_obj(ir_string, ir_obj)

    try:
        return link_executable([ir_obj] + runtime_objs, output_path, install)
    finally:
        # Clean up intermediate obj
        if ir_obj.exists():
            ir_obj.unlink()
