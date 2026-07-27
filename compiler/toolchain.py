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

# LLVM optimization level for host codegen (both the IR pass pipeline and
# backend instruction selection). Defaults to -O2, which measures fastest for
# fastpy's generated code — -O3 regressed tight loops and cross-FV-boundary
# inlining in A/B testing. Override with FASTPY_OPT=0..3 for experimentation.
try:
    _BACKEND_OPT_LEVEL = int(os.environ.get("FASTPY_OPT", "2"))
    if _BACKEND_OPT_LEVEL not in (0, 1, 2, 3):
        _BACKEND_OPT_LEVEL = 2
except ValueError:
    _BACKEND_OPT_LEVEL = 2

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


# --- Cross-compilation targets ---
# Passing target=None to the codegen entry points keeps the existing behavior:
# emit for the host triple (COFF on Windows, ELF/Mach-O on Linux/macOS), linked
# against the host CPython. A named cross-target instead emits an object for a
# foreign platform. The first supported one is SlateOS userspace.
SLATEOS_TARGET = "x86_64-slateos"

# LLVM parameters for the SlateOS x86_64 userspace target. These MUST stay in
# lockstep with the OS repo's Rust target spec (toolchain/x86_64-slateos.json)
# so fastpy-emitted objects are ABI-compatible with that sysroot's libc.a (the
# `posix` crate compiled as a staticlib) and can be linked by the same
# gnu-lld/rust-lld linker. Both host and target are x86_64, so the already
# initialized native X86 backend can emit for this triple with no extra target
# initialization — we only need the foreign triple, data layout, and codegen
# knobs (static relocation + large code model + SSE2, matching the JSON).
_SLATEOS_TRIPLE = "x86_64-unknown-linux-musl"
_SLATEOS_DATA_LAYOUT = (
    "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
)
_SLATEOS_CPU = "x86-64"
_SLATEOS_FEATURES = "+sse,+sse2"

# Link step for the SlateOS target. Unlike the host link paths (MSVC link.exe /
# cc), a SlateOS executable is an ELF for a foreign platform, so we drive the
# LLVM linker (`rust-lld` in GNU/ELF flavor) directly. rust-lld ships inside the
# installed Rust toolchain that the OS repo already uses to build its userspace
# (the same lld/rust-lld referenced by toolchain/x86_64-slateos.json), so no new
# tool is required. The SlateOS loader maps userspace binaries at a fixed base,
# and the sysroot is static-only, hence: static link, no dynamic linker, non-PIE.
_SLATEOS_LLD_FLAVOR = "gnu"

# Directory where the cross-compiled pure-mode SlateOS runtime objects are
# cached (out-of-tree from the host .obj/.o so the two never collide).
SLATEOS_RUNTIME_DIR = RUNTIME_DIR / "slateos"

# Pure-mode runtime translation units for the SlateOS target. Unlike the host
# build (which links cpython_bridge.c against libpython), a SlateOS pure-mode
# build omits the CPython bridge entirely and substitutes bridge_stub.c — its
# operational entry points raise a catchable RuntimeError and the refcount
# hooks are no-ops (no bridge objects can exist). The JIT symbol table in
# runtime.c is compiled out via -DFPY_PURE_MODE (it would otherwise
# force-reference bridge functions pure mode omits).
_SLATEOS_RUNTIME_NAMES = [
    "runtime", "objects", "threading", "gc", "bigint", "bridge_stub",
    # pathlib_pure.c: native (CPython-free) pathlib.Path surface for pure mode.
    # The bridge's PyObject*-backed path functions live in cpython_bridge.c,
    # which pure mode omits; this TU supplies them treating a Path as a heap C
    # string. Pure-only — never compiled into the host build (see
    # _SHARED_RUNTIME_NAMES), so no symbol collision with the bridge.
    "pathlib_pure",
]

# The C cross-compiler target passed to `zig cc`. `zig cc --target=<t>` is a
# self-contained clang plus bundled musl headers and libc, so no system-wide
# toolchain or separately vendored musl sysroot is required. The flags below
# mirror the codegen ABI in `_make_target_machine`: static relocation
# (-fno-pic/-fno-pie), large code model, and -O2 to match the IR opt level.
_SLATEOS_ZIG_TARGET = "x86_64-linux-musl"


def _find_zig_cc() -> Path | None:
    """
    Locate the `zig` executable used as the SlateOS C cross-compiler.

    `zig cc --target=x86_64-linux-musl` bundles clang + musl headers + musl
    libc in one portable download, so it needs neither a system-wide install
    nor a separately vendored musl sysroot. Resolution order:

    1. ``$FASTPY_ZIG`` — explicit override (path to ``zig[.exe]``).
    2. A bare ``zig`` on PATH.
    3. A portable unpack under ``D:\\utils\\zig-*`` / ``C:\\utils\\zig-*``
       (dev-machine fallback).

    Returns the path to zig, or None if not found.
    """
    import shutil
    import glob

    override = os.environ.get("FASTPY_ZIG")
    if override:
        p = Path(override)
        if p.exists():
            return p

    found = shutil.which("zig")
    if found:
        return Path(found)

    # Dev-machine portable-install fallback.
    for base in (r"D:\utils", r"C:\utils"):
        for m in sorted(glob.glob(os.path.join(base, "zig-*", "zig.exe")),
                        reverse=True):
            return Path(m)
    return None


def _find_slateos_sysroot_lib() -> Path | None:
    """
    Locate the SlateOS sysroot ``lib`` directory that holds ``libc.a``.

    A pure-mode SlateOS executable links the fastpy program + runtime objects
    against the OS repo's static ``libc.a`` (the ``posix`` crate built as a
    libc-shaped staticlib). Resolution order:

    1. ``$FASTPY_SLATEOS_SYSROOT`` — either the sysroot root (its ``lib``
       subdir is tried) or the ``lib`` dir itself.
    2. A sibling ``os`` checkout at ``<fastpy>/../os/toolchain/sysroot/lib``.

    Returns the directory containing ``libc.a``, or None if not found.
    """
    candidates: list[Path] = []
    env = os.environ.get("FASTPY_SLATEOS_SYSROOT")
    if env:
        p = Path(env)
        candidates.append(p / "lib")
        candidates.append(p)
    candidates.append(
        _PROJECT_ROOT.parent / "os" / "toolchain" / "sysroot" / "lib"
    )
    for c in candidates:
        if (c / "libc.a").exists():
            return c
    return None


def _find_rust_lld() -> Path | None:
    """
    Locate `rust-lld` (the LLVM linker bundled with the Rust toolchain).

    The SlateOS link step reuses the very linker the OS repo builds its
    userspace with, so a fastpy SlateOS binary is produced by the same
    gnu-lld/rust-lld path as the rest of the OS. Resolution order:

    1. `$FASTPY_RUST_LLD` — explicit override.
    2. The active Rust sysroot (`rustc --print sysroot`), under
       `lib/rustlib/<host>/bin/rust-lld[.exe]`.
    3. A bare `rust-lld` / `ld.lld` on PATH.

    Returns the path, or None if no linker was found.
    """
    import shutil

    override = os.environ.get("FASTPY_RUST_LLD")
    if override:
        p = Path(override)
        if p.exists():
            return p

    # Query the Rust sysroot and scan its rustlib bin dirs for rust-lld.
    rustc = shutil.which("rustc")
    if rustc:
        try:
            sysroot = subprocess.run(
                [rustc, "--print", "sysroot"],
                capture_output=True, text=True, timeout=15,
            )
            if sysroot.returncode == 0:
                root = Path(sysroot.stdout.strip())
                rustlib = root / "lib" / "rustlib"
                if rustlib.is_dir():
                    exe = "rust-lld.exe" if IS_WINDOWS else "rust-lld"
                    for host_dir in rustlib.iterdir():
                        cand = host_dir / "bin" / exe
                        if cand.exists():
                            return cand
        except (subprocess.SubprocessError, OSError):
            pass

    # Fall back to a linker on PATH.
    for name in ("rust-lld", "ld.lld"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


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


def _check_python_dll_on_path(install: PythonInstall | None = None) -> None:
    """Warn if the Python DLL isn't findable at runtime.

    On Windows the compiled exe links against pythonXY.dll.  If the DLL
    directory isn't on PATH, the exe fails silently (no output, no error
    message) because the OS loader terminates the process before main().
    """
    import ctypes
    import ctypes.util
    if install is not None:
        dll_name = f"python{install.version[0]}{install.version[1]}.dll"
        py_dir = install.prefix
    else:
        dll_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        py_dir = Path(sys.prefix)
    # Check if Windows can find the DLL via normal search order
    try:
        ctypes.WinDLL(dll_name)
        return  # DLL found, all good
    except OSError:
        pass
    # DLL not on PATH — emit a prominent warning
    print(
        f"\n  WARNING: {dll_name} is not on your PATH.\n"
        f"  The compiled .exe will fail silently without it.\n"
        f"\n"
        f"  Fix: add your Python directory to PATH:\n"
        f"    set PATH={py_dir};%PATH%\n"
        f"\n"
        f"  Or copy {dll_name} next to the .exe:\n"
        f"    copy \"{py_dir / dll_name}\" .\n",
        flush=True,
    )


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


def _find_vcvars_bat() -> Path | None:
    """Locate vcvars64.bat by enumerating VS installations.

    Enumerates all VS installations under both Program Files directories
    (handles year-named and version-named folders like '2022', '18', etc.)
    and falls back to vswhere.exe. Returns the Path, or None if not found.
    """
    editions = ["Community", "Enterprise", "Professional", "BuildTools"]
    bases = [
        Path(r"C:\Program Files\Microsoft Visual Studio"),
        Path(r"C:\Program Files (x86)\Microsoft Visual Studio"),
    ]
    for base in bases:
        if not base.is_dir():
            continue
        # Enumerate version/year subdirectories, newest first
        subdirs = sorted(
            [d for d in base.iterdir() if d.is_dir() and d.name != "Installer"],
            key=lambda d: d.name,
            reverse=True,
        )
        for subdir in subdirs:
            for edition in editions:
                vcvars = subdir / edition / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
                if vcvars.exists():
                    return vcvars
    # Last resort: use vswhere.exe (handles any edition/year/path)
    vswhere = Path(
        r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    )
    if vswhere.exists():
        import subprocess
        result = subprocess.run(
            [str(vswhere), "-latest", "-property", "installationPath"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            vcvars = (
                Path(result.stdout.strip())
                / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
            )
            if vcvars.exists():
                return vcvars
    return None


def _find_msvc_cl() -> str | None:
    """Find cl.exe by setting up MSVC environment via vcvars64.bat.

    Returns a bat preamble string that sets up the environment, or None
    if MSVC cannot be found.
    """
    vcvars = _find_vcvars_bat()
    if vcvars is not None:
        return f'call "{vcvars}" >NUL'
    return None


# Cached MSVC environment (in-process). Running vcvars64.bat is slow (~1-2s of
# environment setup); we do it once, capture the resulting environment, and
# reuse it to invoke link.exe/cl.exe directly on subsequent calls. This is the
# single biggest compile-time win — a bare link previously re-ran vcvars every
# time. A disk cache (keyed on the vcvars path + mtime) extends the win across
# separate one-shot CLI compiles.
_MSVC_ENV_CACHE: dict[str, str] | None = None
_MSVC_ENV_TRIED = False


def _msvc_env_cache_file() -> Path:
    return RUNTIME_DIR / "_msvc_env_cache.json"


def _get_msvc_env() -> dict[str, str] | None:
    """Return a cached environment dict (for subprocess `env=`) that has the
    MSVC toolchain (link.exe/cl.exe, INCLUDE, LIB, PATH) set up, or None if
    MSVC can't be found. Runs vcvars64.bat at most once per process.
    """
    global _MSVC_ENV_CACHE, _MSVC_ENV_TRIED
    if _MSVC_ENV_CACHE is not None:
        return _MSVC_ENV_CACHE
    if _MSVC_ENV_TRIED:
        return None
    _MSVC_ENV_TRIED = True

    vcvars = _find_vcvars_bat()
    if vcvars is None:
        return None
    vcvars_key = str(vcvars.resolve())
    try:
        vcvars_mtime = vcvars.stat().st_mtime
    except OSError:
        vcvars_mtime = 0.0

    # Try the disk cache first.
    cache_file = _msvc_env_cache_file()
    if cache_file.exists():
        try:
            import json
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if (data.get("vcvars") == vcvars_key
                    and data.get("mtime") == vcvars_mtime
                    and isinstance(data.get("env"), dict)
                    and data["env"]):
                _MSVC_ENV_CACHE = {str(k): str(v) for k, v in data["env"].items()}
                return _MSVC_ENV_CACHE
        except (ValueError, OSError):
            pass

    # Run vcvars once and capture the resulting environment via `set`.
    # Pass a single command *string* (not an argv list) with `cmd /s /c` so
    # cmd strips exactly the outer quote pair — this is the robust way to run
    # a quoted batch path followed by `&& set` without cmd mangling quotes.
    cmd_str = f'cmd.exe /s /c ""{vcvars}" >NUL && set"'
    try:
        result = subprocess.run(
            cmd_str, capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            if key:
                env[key] = val
    # Sanity check: a valid MSVC env must expose PATH and LIB.
    keys_upper = {k.upper() for k in env}
    if "PATH" not in keys_upper or "LIB" not in keys_upper:
        return None

    _MSVC_ENV_CACHE = env
    try:
        import json
        cache_file.write_text(
            json.dumps({"vcvars": vcvars_key, "mtime": vcvars_mtime, "env": env}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return env


def _env_path_value(env: dict[str, str]) -> str:
    """Extract the PATH value from an env dict, case-insensitively."""
    for k, v in env.items():
        if k.upper() == "PATH":
            return v
    return ""


def _newest_runtime_header_mtime() -> float:
    """Newest mtime among the runtime's headers.

    Every runtime .c includes some of these, and several of them carry
    layout-critical declarations (`FpyValue`, `FpyString`, the FPY_EXC_*
    constants) that the .obj bakes in. Comparing a .c against its .obj alone
    therefore silently keeps a stale .obj whenever only a header changed — the
    edit appears to have no effect, which is a miserable thing to debug. Using
    the newest header in the directory over-rebuilds a little (any header
    change rebuilds every .obj) and that is the right trade: a runtime build is
    seconds, and the alternative is trusting a hand-maintained per-file
    dependency list to stay correct.
    """
    newest = 0.0
    try:
        for h in RUNTIME_DIR.glob("*.h"):
            m = h.stat().st_mtime
            if m > newest:
                newest = m
    except OSError:
        # An unreadable runtime dir is the build's problem, not the cache's;
        # returning 0 just means "no header constraint".
        return 0.0
    return newest


def _obj_is_current(src: Path, obj: Path) -> bool:
    """Check if an object file exists and is newer than its source *and headers*."""
    if not obj.exists():
        return False
    obj_mtime = obj.stat().st_mtime
    if obj_mtime < src.stat().st_mtime:
        return False
    return obj_mtime >= _newest_runtime_header_mtime()


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
                capture_output=True, text=True, timeout=120,
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
            capture_output=True, text=True, timeout=120,
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
            capture_output=True, text=True, timeout=120,
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
        capture_output=True, text=True, timeout=120,
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


def _compile_shared_runtime_slateos(force: bool = False) -> list[Path]:
    """Cross-compile the pure-mode C runtime to SlateOS (musl) ELF objects.

    Drives ``zig cc --target=x86_64-linux-musl`` over the pure-mode runtime
    translation units (``_SLATEOS_RUNTIME_NAMES``), emitting one ``.o`` per
    source into ``SLATEOS_RUNTIME_DIR``. The compile flags mirror the codegen
    ABI (static relocation, large code model) and define ``FPY_PURE_MODE`` so
    the CPython-bridge fallbacks resolve to ``bridge_stub.c`` and the JIT
    symbol table is compiled out. Objects that are already newer than their
    source are skipped unless ``force`` is set.

    Returns the list of object paths (in ``_SLATEOS_RUNTIME_NAMES`` order).
    """
    zig = _find_zig_cc()
    if zig is None:
        raise RuntimeError(
            "Cannot find `zig` for the SlateOS runtime cross-compile. Install "
            "zig (it bundles clang + musl), put it on PATH, or set FASTPY_ZIG "
            "to the zig executable path.")

    SLATEOS_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    objs: list[Path] = []
    for name in _SLATEOS_RUNTIME_NAMES:
        src = RUNTIME_DIR / f"{name}.c"
        obj = SLATEOS_RUNTIME_DIR / f"{name}.o"
        objs.append(obj)
        if not force and _obj_is_current(src, obj):
            continue
        cmd = [
            str(zig), "cc",
            f"--target={_SLATEOS_ZIG_TARGET}",
            "-c", "-O2",
            "-mcmodel=large",     # match codegen code-model=large
            "-fno-pic", "-fno-pie",  # match relocation-model=static
            "-DFPY_PURE_MODE",    # no CPython bridge / no JIT symbol table
            str(src),
            "-o", str(obj),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(RUNTIME_DIR),
        )
        if result.returncode != 0 or not obj.exists():
            raise RuntimeError(
                f"Failed to cross-compile {src.name} for SlateOS:\n"
                f"{result.stdout}\n{result.stderr}")
    return objs


def ensure_slateos_runtime_built(force: bool = False) -> list[Path]:
    """Ensure the pure-mode SlateOS C runtime objects are built; return paths.

    Public entry point mirroring :func:`ensure_runtime_built` for the SlateOS
    cross-target. Pure mode has no per-Python-version bridge, so there is a
    single shared set of objects independent of any ``PythonInstall``.
    """
    return _compile_shared_runtime_slateos(force=force)


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


def _make_target_machine(target: str | None):
    """
    Build the LLVM `TargetMachine` for a codegen target.

    `target=None` -> host machine (the historical behavior: PIC on POSIX,
    default relocation on Windows). `target=SLATEOS_TARGET` -> a foreign
    x86_64 SlateOS-userspace machine using the triple/data-layout/codegen
    knobs from `toolchain/x86_64-slateos.json` (static relocation, large code
    model, SSE2), so the emitted object matches the OS's Rust sysroot ABI.
    """
    if target is None:
        # Host codegen. Use PIC relocation on POSIX (required for ASLR and
        # shared objects); leave Windows at its default.
        tm = llvm.Target.from_default_triple()
        return tm.create_target_machine(
            opt=_BACKEND_OPT_LEVEL,  # -O3 backend codegen (override w/ FASTPY_OPT)
            reloc="pic" if not IS_WINDOWS else "default",
            codemodel="default",
        )
    if target == SLATEOS_TARGET:
        tm = llvm.Target.from_triple(_SLATEOS_TRIPLE)
        return tm.create_target_machine(
            cpu=_SLATEOS_CPU,
            features=_SLATEOS_FEATURES,
            opt=2,
            # Match x86_64-slateos.json: relocation-model=static,
            # code-model=large, non-PIE. The SlateOS loader maps userspace
            # binaries at a fixed base, so static relocation is correct and
            # avoids needing a PLT/GOT the minimal sysroot doesn't set up.
            reloc="static",
            codemodel="large",
        )
    raise ValueError(f"Unknown codegen target {target!r}")


def compile_ir_to_obj(
    ir_string: str, output_path: Path, target: str | None = None
) -> Path:
    """
    Compile LLVM IR text to a native object file.

    Runs IR-level optimization passes (-O2 equivalent) before backend
    codegen: inlining, GVN, dead-code elimination, loop opts, etc.

    Args:
        ir_string: LLVM IR as a string.
        output_path: Path for the output object file.
        target: Codegen target. `None` (default) emits for the host; pass
            `SLATEOS_TARGET` to cross-compile an x86_64 SlateOS-userspace
            object (ELF, ABI-matched to the Rust `x86_64-slateos` sysroot).

    Returns:
        Path to the generated object file.
    """
    # Parse the IR
    mod = llvm.parse_assembly(ir_string)
    mod.verify()

    # For a cross-target, override the module's triple and data layout so the
    # emitted object is tagged for the foreign platform (the IR text carries
    # the host's triple/layout from codegen). Both host and target are x86_64
    # with the standard layout, so this is a re-tag, not an ABI change.
    if target == SLATEOS_TARGET:
        mod.triple = _SLATEOS_TRIPLE
        mod.data_layout = _SLATEOS_DATA_LAYOUT

    # Create target machine (backend-level opts).
    target_machine = _make_target_machine(target)

    # Run IR-level optimization passes (-O2 pipeline).
    # Uses the new LLVM pass manager API (PassBuilder + PipelineTuningOptions).
    pto = llvm.PipelineTuningOptions(speed_level=_BACKEND_OPT_LEVEL, size_level=0)
    # -O3 uses a larger inline threshold (275) than -O2 (225).
    pto.inlining_threshold = 275 if _BACKEND_OPT_LEVEL >= 3 else 225
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
    """Link object files using MSVC's link.exe (Windows).

    Fast path: use the cached MSVC environment (captured once via vcvars) and
    invoke link.exe directly — this avoids re-running vcvars64.bat (~1-2s) on
    every link, which dominates compile time. Falls back to the vcvars-batch
    method if the cached-env path is unavailable or fails.
    """
    py_lib_dir = _find_python_lib_dir(install)
    py_lib = _find_python_lib_name(install)

    env = _get_msvc_env()
    if env is not None:
        import shutil
        link_exe = shutil.which("link.exe", path=_env_path_value(env))
        if link_exe:
            args = [
                link_exe, "/NOLOGO", f"/OUT:{output_path}",
                *[str(p) for p in obj_files],
                f"/LIBPATH:{py_lib_dir}", py_lib,
                "/DEFAULTLIB:ucrt", "/DEFAULTLIB:msvcrt",
                "/DEFAULTLIB:legacy_stdio_definitions",
                "/SUBSYSTEM:CONSOLE", "/STACK:8388608",
                "/EXPORT:fastpy_get_jit_symbols",
                "/EXPORT:fastpy_get_jit_symbol_count",
            ]
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True,
                    timeout=300, env=env,
                )
            except (OSError, subprocess.SubprocessError):
                result = None
            if result is not None and result.returncode == 0 \
                    and output_path.exists():
                return output_path
            # Otherwise fall through to the batch fallback below, which
            # produces a full diagnostic if linking genuinely fails.

    return _link_windows_batch(obj_files, output_path, py_lib_dir, py_lib)


def _link_windows_batch(obj_files: list[Path], output_path: Path,
                        py_lib_dir: Path, py_lib: str) -> Path:
    """Fallback linker path: set up MSVC via a vcvars batch, then link."""
    obj_list = " ".join(f'"{p}"' for p in obj_files)
    out_str = str(output_path)

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
        '/STACK:8388608 '
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
            capture_output=True, text=True, timeout=300,
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
    # 8 MB stack — prevents stack overflow from recursive refcount release
    # on deep object chains (e.g. 100K-node linked lists).
    cmd += ["-Wl,-z,stacksize=8388608"]
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


def _link_slateos(
    obj_files: list[Path],
    output_path: Path,
    entry: str = "_start",
    sysroot_lib_dir: Path | None = None,
    libs: list[str] | None = None,
) -> Path:
    """
    Link object files into a SlateOS-userspace ELF executable via rust-lld.

    This is the foreign-target counterpart of `_link_windows`/`_link_posix`.
    Instead of the host's MSVC/cc driver it invokes `rust-lld` in GNU/ELF
    flavor — the same LLVM linker the OS repo uses for its `x86_64-slateos`
    userspace — so the resulting binary matches that sysroot's ABI.

    The link is static and non-PIE with no dynamic linker, matching
    `toolchain/x86_64-slateos.json` (relocation-model=static, crt-static,
    the loader maps userspace at a fixed base). Pure-mode fastpy programs
    (no CPython bridge) link their own objects plus the fastpy C runtime
    objects and the sysroot `libc.a`.

    Args:
        obj_files: Object files to link (fastpy program + runtime objects).
        output_path: Path for the output ELF executable.
        entry: Entry symbol. Defaults to ``_start`` — the real ELF entry, which
            the sysroot ``libc.a`` provides (crt0: ``_start`` →
            ``__libc_start_main`` retrieves argv/envp from the kernel, inits
            environ/signals, runs ELF constructors, calls ``main``, then
            ``exit``s with its return value). Setting the entry to ``_start``
            pulls that crt member out of the archive. Pass ``"main"`` only to
            link a bare object with no crt (e.g. the low-level plumbing test).
        sysroot_lib_dir: Optional directory added to the linker search path
            (e.g. the OS repo's ``toolchain/sysroot/lib`` holding ``libc.a``).
        libs: Optional archive names to link (e.g. ``["c"]`` for ``libc.a``).

    Returns:
        Path to the generated executable.
    """
    lld = _find_rust_lld()
    if lld is None:
        raise RuntimeError(
            "Cannot find rust-lld for the SlateOS link step. Install a Rust "
            "toolchain (it bundles rust-lld) or set FASTPY_RUST_LLD to the "
            "linker path.")

    cmd: list[str] = [
        str(lld),
        "-flavor", _SLATEOS_LLD_FLAVOR,
        "-static",            # crt-static: no dynamic loader on SlateOS
        "--no-dynamic-linker",
        "-e", entry,          # SlateOS loader jumps to this entry symbol
        "-o", str(output_path),
    ]
    cmd += [str(p) for p in obj_files]
    if sysroot_lib_dir is not None:
        cmd.append(f"-L{sysroot_lib_dir}")
    for lib in libs or []:
        cmd.append(f"-l{lib}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"SlateOS link failed:\n{result.stdout}\n{result.stderr}")
    if not output_path.exists():
        raise RuntimeError(
            f"SlateOS link appeared to succeed but {output_path} not found.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}")
    return output_path


def link_executable(
    obj_files: list[Path],
    output_path: Path,
    install: PythonInstall | None = None,
    target: str | None = None,
) -> Path:
    """
    Link object files into a native executable.

    On Windows, uses MSVC link.exe. On Linux/macOS, uses cc (gcc/clang).
    With ``target=SLATEOS_TARGET``, cross-links a SlateOS-userspace ELF via
    rust-lld instead (see `_link_slateos`); the host CPython is not linked.

    Args:
        obj_files: List of object files to link.
        output_path: Path for the output executable.
        install: PythonInstall to link against. If None, uses current Python.
            Ignored for the SlateOS target (pure-mode, no CPython bridge).
        target: Link target. ``None`` (default) links a host executable; pass
            ``SLATEOS_TARGET`` to cross-link a SlateOS ELF.

    Returns:
        Path to the generated executable.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if target == SLATEOS_TARGET:
        # Pure-mode SlateOS link: program objects + cross-compiled fastpy
        # runtime objects, resolved against the OS repo's static libc.a. The
        # runtime is built on demand (cached under SLATEOS_RUNTIME_DIR).
        runtime_objs = ensure_slateos_runtime_built()
        sysroot_lib = _find_slateos_sysroot_lib()
        if sysroot_lib is None:
            raise RuntimeError(
                "Cannot find the SlateOS sysroot libc.a. Set "
                "FASTPY_SLATEOS_SYSROOT to the sysroot directory (holding "
                "lib/libc.a), or check out the OS repo as a sibling of fastpy "
                "(../os/toolchain/sysroot/lib).")
        return _link_slateos(
            list(obj_files) + runtime_objs,
            output_path,
            sysroot_lib_dir=sysroot_lib,
            libs=["c"],
        )
    if target is not None:
        raise ValueError(f"Unknown link target {target!r}")

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
        exe = link_executable([ir_obj] + runtime_objs, output_path, install)
    finally:
        # Clean up intermediate obj
        if ir_obj.exists():
            ir_obj.unlink()

    # On Windows, warn if the Python DLL isn't on PATH — the exe will
    # fail silently (no output, no error) when the OS loader can't find it.
    if IS_WINDOWS:
        _check_python_dll_on_path(install)

    return exe
