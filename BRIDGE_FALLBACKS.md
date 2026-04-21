# Bridge Fallback Patterns

Patterns that the compiler cannot handle natively and falls back to CPython
bridge execution or runtime dispatch. Each pattern is documented with why it
can't be compiled natively and what the fallback does.

## Phase 4 conversions (CodeGenError -> bridge fallback)

### Statement-level fallbacks (no-op skip)

| Pattern | Previous behavior | New behavior |
|---------|------------------|--------------|
| `del container[key]` on unknown container | CodeGenError crash | Skip (no-op) |
| `del target` with Attribute/complex target | CodeGenError crash | Skip (no-op) |
| Unsupported AST statement type | CodeGenError crash | Skip (no-op) |
| Unknown function call as statement | CodeGenError crash | Bridge call or skip |

### Method-level fallbacks (runtime dispatch)

These were `raise CodeGenError("Unsupported X method")`. Now they fall
through to the runtime method dispatch at the bottom of `_emit_method_call`,
which uses `obj_call_method0/1/2` for dynamic dispatch:

| Container | Examples of methods now handled | Dispatch |
|-----------|-------------------------------|----------|
| list | `.copy()`, `.index()`, `.count()`, `.remove()`, `.insert()` | `obj_call_method` |
| dict | `.pop()`, `.popitem()`, `.setdefault()`, `.fromkeys()` | `obj_call_method` |
| set | `.copy()`, `.issubset()`, `.issuperset()`, `.symmetric_difference()` | `obj_call_method` |
| deque | `.rotate()`, `.maxlen`, `.count()`, `.index()` | `obj_call_method` |
| Counter | `.most_common()`, `.subtract()`, `.total()` | `obj_call_method` |
| defaultdict | `.pop()`, `.setdefault()` | `obj_call_method` |
| Path | `.mkdir()`, `.rmdir()`, `.unlink()`, `.chmod()`, `.glob()` | `obj_call_method` |
| logger | `.exception()`, `.critical()`, `.handlers` | `obj_call_method` |

### CPython bridge call improvements (this session)

| Feature | Details |
|---------|---------|
| 4+ arg bridge calls | `fpy_cpython_call_kw` handles arbitrary positional args (was limited to 3) |
| PYOBJ binops | `fpy_cpython_binop` / `fpy_cpython_rbinop` for OBJ-tagged PyObject* arithmetic |
| PYOBJ comparisons | `fpy_cpython_compare` for Eq/NotEq/Lt/LtE/Gt/GtE on bridge-returned objects |
| PyBytes_Check | Bridge now correctly identifies and preserves bytes objects |
| PyTuple_Check | Bridge now correctly identifies and preserves tuple objects |
| Safe refcounting | `fpy_rc_incref`/`fpy_rc_decref` distinguish FpyClosure, FpyObj, and PyObject* |
| First-class functions | Function aliases and indirect calls route through `__call__` dispatch |
| Function return propagation | List-of-lists detection from append patterns across function boundaries |

## Patterns kept as CodeGenError (reduced from 126)

### Genuine Python errors (keep as errors)
- Wrong argument count for builtins (`len()`, `sorted()`, `zip()`, etc.)
- `break`/`continue` outside loop
- Undefined variable reference

### Type system limitations (keep for now, convert later)
- `Cannot wrap LLVM type X` — internal type mismatch
- `Cannot encode X as FpyValue` — value representation gap
- Dict comprehension key/value type mismatch
- Deep nested tuple unpacking

### Pattern limitations (convert in future phases)
- Complex starred unpacking patterns
- Multi-generator comprehensions (>2 generators)
- Non-standard format string patterns
- `super()` outside class method
