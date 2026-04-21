"""
Runtime JIT compilation for fastpy.

When exec()/eval() is called with a dynamic string at runtime, this module
compiles the source to a native shared library (.dll/.so), loads it, and
calls the resulting function. Results are cached by source hash.

Usage (from C bridge via embedded CPython):
    from compiler.jit import jit_exec, jit_eval
    jit_exec("x = 42; print(x)")
    result = jit_eval("2 + 3")
"""

import ast
import sys
import os
import hashlib
import tempfile
import ctypes
from pathlib import Path

# Cache of compiled shared libraries: hash → (lib_handle, func_ptr)
_jit_cache = {}
_jit_dir = None


def _get_jit_dir():
    """Get/create the JIT cache directory."""
    global _jit_dir
    if _jit_dir is None:
        _jit_dir = os.path.join(tempfile.gettempdir(), "fastpy_jit")
        os.makedirs(_jit_dir, exist_ok=True)
    return _jit_dir


def _source_hash(source: str) -> str:
    """Hash source code for cache lookup."""
    return hashlib.md5(source.encode()).hexdigest()[:16]


def jit_compile(source: str) -> int:
    """
    JIT-compile Python source to a native function.
    Returns a function pointer (as int) to the compiled fastpy_main(),
    or 0 if compilation fails (caller should fall back to CPython).
    """
    h = _source_hash(source)
    if h in _jit_cache:
        return _jit_cache[h]

    try:
        from compiler.codegen import CodeGen
        from compiler.toolchain import compile_ir_to_obj, link_executable, \
            ensure_runtime_built, RUNTIME_OBJS, OBJ_EXT, IS_WINDOWS

        # Parse source
        tree = ast.parse(source, mode="exec")

        # Compile to IR (suppress errors — JIT is best-effort)
        codegen = CodeGen()
        try:
            ir_string = codegen.generate(tree)
        except Exception as gen_err:
            print(f"[fastpy JIT] compilation failed: {gen_err}", file=sys.stderr)
            return 0

        # Compile IR to object file
        jit_dir = Path(_get_jit_dir())
        obj_path = jit_dir / f"jit_{h}{OBJ_EXT}"
        compile_ir_to_obj(ir_string, obj_path)

        # Link as shared library (DLL on Windows, .so on Linux/macOS)
        if IS_WINDOWS:
            lib_path = jit_dir / f"jit_{h}.dll"
        else:
            lib_path = jit_dir / f"jit_{h}.so"

        # Link with runtime
        runtime_objs = ensure_runtime_built()
        _link_shared(obj_path, runtime_objs, lib_path)

        # Load the shared library
        if IS_WINDOWS:
            lib = ctypes.CDLL(str(lib_path))
        else:
            lib = ctypes.CDLL(str(lib_path))

        # Get the fastpy_main function pointer
        func = lib.fastpy_main
        func.restype = None
        func.argtypes = []

        # Cache it
        func_ptr = ctypes.cast(func, ctypes.c_void_p).value
        _jit_cache[h] = func_ptr

        # Clean up object file
        if obj_path.exists():
            obj_path.unlink()

        return func_ptr

    except Exception as e:
        # JIT compilation failed — caller falls back to CPython interpreter
        print(f"[fastpy JIT] compilation failed: {e}", file=sys.stderr)
        return 0


def _link_shared(obj_path, runtime_objs, output_path):
    """Link object file as a shared library."""
    import subprocess
    from compiler.toolchain import IS_WINDOWS, PYTHON_LIB_DIR, PYTHON_LIB

    if IS_WINDOWS:
        # Use MSVC to create a DLL
        obj_list = f'"{obj_path}" ' + " ".join(f'"{p}"' for p in runtime_objs)
        bat_content = (
            '@echo off\r\n'
            'call "C:\\Program Files\\Microsoft Visual Studio\\2022\\Community'
            '\\VC\\Auxiliary\\Build\\vcvars64.bat" 1>NUL 2>NUL\r\n'
            'if errorlevel 1 (\r\n'
            '    call "C:\\Program Files\\Microsoft Visual Studio\\2022\\Enterprise'
            '\\VC\\Auxiliary\\Build\\vcvars64.bat" 1>NUL 2>NUL\r\n'
            ')\r\n'
            f'link.exe /NOLOGO /DLL /OUT:"{output_path}" {obj_list} '
            f'/LIBPATH:"{PYTHON_LIB_DIR}" {PYTHON_LIB} '
            '/DEFAULTLIB:ucrt /DEFAULTLIB:msvcrt '
            '/DEFAULTLIB:legacy_stdio_definitions '
            '/EXPORT:fastpy_main\r\n'
        )
        bat_path = output_path.parent / "_jit_link.bat"
        bat_path.write_text(bat_content, encoding="ascii")
        result = subprocess.run(
            ["cmd.exe", "/c", str(bat_path)],
            capture_output=True, text=True, timeout=30)
        bat_path.unlink(missing_ok=True)
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"JIT link failed: {result.stderr}")
    else:
        import shutil
        cc = shutil.which("cc") or shutil.which("gcc") or "cc"
        cmd = [cc, "-shared", "-o", str(output_path), str(obj_path)]
        cmd += [str(p) for p in runtime_objs]
        cmd += [f"-L{PYTHON_LIB_DIR}", f"-l{PYTHON_LIB}"]
        cmd += ["-lm", "-ldl"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"JIT link failed: {result.stderr}")


def jit_exec(source: str) -> None:
    """JIT-compile and execute source code."""
    func_ptr = jit_compile(source)
    if func_ptr:
        # Call the native function
        cfunc = ctypes.CFUNCTYPE(None)
        cfunc(func_ptr)()
    else:
        # Fallback to CPython
        exec(source)


def jit_eval(source: str):
    """JIT-compile and evaluate an expression. Returns the result."""
    # For eval, we wrap in a function that returns the value
    # This is complex — for now, fall back to CPython for eval
    return eval(source)


# ── Compile-on-load for dynamic imports ──────────────────────────────

# Cache of compiled modules: module_name → func_ptr
_import_cache = {}


def _find_module_file(name: str) -> str | None:
    """Find a .py file for the given module name on sys.path."""
    parts = name.split(".")
    # Try as a package (dir/__init__.py) or module (file.py)
    candidates = [
        os.path.join(*parts) + ".py",
        os.path.join(*parts, "__init__.py"),
    ]
    for base in sys.path:
        if not base:
            base = "."
        for candidate in candidates:
            full = os.path.join(base, candidate)
            if os.path.isfile(full):
                return full
    # Also check current directory
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def jit_import(name: str) -> int:
    """
    Compile-on-load: find a .py module, compile it natively, execute it.
    Returns a function pointer to the compiled module's fastpy_main,
    or 0 if the module can't be found or compiled (caller uses CPython import).

    The compiled module's top-level code runs (registering functions/classes
    in the fastpy runtime), making them available for subsequent calls.
    """
    if name in _import_cache:
        return _import_cache[name]

    # Find the .py source file
    filepath = _find_module_file(name)
    if filepath is None:
        return 0  # Not a .py file — use CPython import (e.g., .pyd, .so, builtin)

    try:
        # Read source
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        # Compile using the same JIT infrastructure
        func_ptr = jit_compile(source)
        if func_ptr:
            _import_cache[name] = func_ptr
            # Execute the module (runs top-level code, registers functions/classes)
            cfunc = ctypes.CFUNCTYPE(None)
            cfunc(func_ptr)()
            return func_ptr
        return 0

    except Exception as e:
        print(f"[fastpy JIT import] {name}: {e}", file=sys.stderr)
        return 0
