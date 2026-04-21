"""
Runtime JIT compilation for fastpy.

Uses llvmlite's in-process MCJIT (ExecutionEngine) to compile Python source
to native machine code in the same address space. Runtime symbols (fastpy_*
functions) resolve automatically from the current process — no separate
DLL/SO needed.

Usage (from C bridge via embedded CPython):
    from compiler.jit import jit_compile, jit_import
    func_ptr = jit_compile("print(42)")  # returns function pointer or 0
"""

import ast
import sys
import os
import hashlib

# Cache: source_hash → function_pointer (int)
_jit_cache = {}

# Cache: module_name → function_pointer (int)
_import_cache = {}

# Persistent execution engines (prevent GC from freeing JIT'd code)
_engines = []


def _source_hash(source: str) -> str:
    return hashlib.md5(source.encode()).hexdigest()[:16]


def _init_llvm():
    """Initialize LLVM targets (idempotent)."""
    import llvmlite.binding as llvm
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    return llvm


# Runtime symbol table cache: name → address
_sym_table = None


def _load_symbol_table():
    """Load the runtime symbol table from the compiled binary.
    Uses the exported fastpy_get_jit_symbols / fastpy_get_jit_symbol_count
    functions which are marked __declspec(dllexport)."""
    global _sym_table
    if _sym_table is not None:
        return _sym_table

    import ctypes

    _sym_table = {}

    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32")
        GetProcAddress = kernel32.GetProcAddress
        GetProcAddress.restype = ctypes.c_void_p
        GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        hmod = kernel32.GetModuleHandleW(None)

        # Get the exported symbol table function
        get_syms_addr = GetProcAddress(hmod, b"fastpy_get_jit_symbols")
        get_count_addr = GetProcAddress(hmod, b"fastpy_get_jit_symbol_count")

        if not get_syms_addr or not get_count_addr:
            return _sym_table  # symbols not exported (old binary)

        # Call the functions via ctypes
        class SymEntry(ctypes.Structure):
            _fields_ = [("name", ctypes.c_char_p), ("addr", ctypes.c_void_p)]

        get_count = ctypes.CFUNCTYPE(ctypes.c_int)(get_count_addr)
        count = get_count()

        get_syms = ctypes.CFUNCTYPE(ctypes.POINTER(SymEntry))(get_syms_addr)
        syms = get_syms()

        for i in range(count):
            entry = syms[i]
            if entry.name and entry.addr:
                _sym_table[entry.name.decode()] = entry.addr
    else:
        # On Linux/macOS: dlsym with RTLD_DEFAULT
        libc = ctypes.CDLL(None)
        dlsym = libc.dlsym
        dlsym.restype = ctypes.c_void_p
        dlsym.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        RTLD_DEFAULT = ctypes.c_void_p(0)

        # Use the same exported function approach
        get_count_addr = dlsym(RTLD_DEFAULT, b"fastpy_get_jit_symbol_count")
        get_syms_addr = dlsym(RTLD_DEFAULT, b"fastpy_get_jit_symbols")
        if get_count_addr and get_syms_addr:
            class SymEntry(ctypes.Structure):
                _fields_ = [("name", ctypes.c_char_p), ("addr", ctypes.c_void_p)]
            get_count = ctypes.CFUNCTYPE(ctypes.c_int)(get_count_addr)
            count = get_count()
            get_syms = ctypes.CFUNCTYPE(ctypes.POINTER(SymEntry))(get_syms_addr)
            syms = get_syms()
            for i in range(count):
                entry = syms[i]
                if entry.name and entry.addr:
                    _sym_table[entry.name.decode()] = entry.addr

    return _sym_table


def _register_runtime_symbols(engine, mod):
    """Register runtime function addresses with the MCJIT engine."""
    sym_table = _load_symbol_table()

    for func in mod.functions:
        if func.is_declaration and func.name:
            addr = sym_table.get(func.name)
            if addr:
                try:
                    engine.add_global_mapping(func, addr)
                except (OverflowError, OSError):
                    pass


def jit_compile(source: str) -> int:
    """
    JIT-compile Python source to native code in-process via MCJIT.
    Returns a function pointer (as int) to the compiled fastpy_main(),
    or 0 if compilation fails (caller should fall back to CPython).
    """
    h = _source_hash(source)
    if h in _jit_cache:
        return _jit_cache[h]

    try:
        from compiler.codegen import CodeGen

        # Parse
        tree = ast.parse(source, mode="exec")

        # Compile to LLVM IR
        codegen = CodeGen()
        # Ensure pre-scan attributes exist (normally set by generate's pre-scan)
        if not hasattr(codegen, '_singledispatch'):
            codegen._singledispatch = {}
            codegen._singledispatch_variants = {}
        try:
            ir_string = codegen.generate(tree)
        except Exception as gen_err:
            print(f"[fastpy JIT] compilation failed: {gen_err}", file=sys.stderr)
            return 0

        # JIT via in-process ExecutionEngine
        llvm = _init_llvm()

        mod = llvm.parse_assembly(ir_string)
        mod.verify()

        # Create execution engine with MCJIT.
        target = llvm.Target.from_default_triple()
        tm = target.create_target_machine(opt=2)

        engine = llvm.create_mcjit_compiler(mod, tm)

        # Register runtime function addresses with MCJIT
        try:
            _register_runtime_symbols(engine, mod)
        except Exception as sym_err:
            print(f"[fastpy JIT] symbol registration failed: {sym_err}", file=sys.stderr)
            return 0

        try:
            engine.finalize_object()
        except Exception as fin_err:
            print(f"[fastpy JIT] finalize failed: {fin_err}", file=sys.stderr)
            return 0

        # Get function pointer to fastpy_main
        func_ptr = engine.get_function_address("fastpy_main")
        if func_ptr == 0:
            print("[fastpy JIT] fastpy_main not found in compiled module", file=sys.stderr)
            return 0

        # Keep engine alive (prevent GC from freeing the machine code)
        _engines.append(engine)

        # Cache
        _jit_cache[h] = func_ptr
        return func_ptr

    except Exception as e:
        print(f"[fastpy JIT] compilation failed: {e}", file=sys.stderr)
        return 0


def jit_exec(source: str) -> None:
    """JIT-compile and execute source code."""
    import ctypes
    func_ptr = jit_compile(source)
    if func_ptr:
        cfunc = ctypes.CFUNCTYPE(None)(func_ptr)
        cfunc()
    else:
        exec(source)


def jit_eval(source: str):
    """JIT-compile and evaluate an expression."""
    return eval(source)


# ── Compile-on-load for dynamic imports ──────────────────────────────


def _find_module_file(name: str) -> str | None:
    """Find a .py file for the given module name on sys.path."""
    parts = name.split(".")
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
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def jit_import(name: str) -> int:
    """
    Compile-on-load: find a .py module, compile it natively in-process,
    execute its top-level code.
    Returns a function pointer (non-zero) on success, 0 on failure.
    """
    if name in _import_cache:
        return _import_cache[name]

    filepath = _find_module_file(name)
    if filepath is None:
        return 0

    # Skip installed packages (site-packages) — their complex code
    # is better handled by CPython. Only JIT-compile local user files.
    if "site-packages" in filepath or "Lib" + os.sep in filepath:
        return 0

    try:
        import ctypes

        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        func_ptr = jit_compile(source)
        if func_ptr:
            _import_cache[name] = func_ptr
            # Execute the module's top-level code
            cfunc = ctypes.CFUNCTYPE(None)(func_ptr)
            cfunc()
            return func_ptr
        return 0

    except Exception as e:
        print(f"[fastpy JIT import] {name}: {e}", file=sys.stderr)
        return 0
