# Known Test Failures — Architectural Limitations

All 129 stdlib tests pass. No known architectural limitations block any test.

## Test results: 129 / 129 passing (100.0 %)

---

## Previously failing tests (now fixed)

| Test | Fix | Session |
|------|-----|---------|
| `types` | `type(f)` returns `types.FunctionType` for user functions via bridge | Session 2 |
| `inspect_mod` | `inspect.signature(f)` intercept builds dummy function with correct params | Session 2 |
| `calendar` | Print pyobj call results via `cpython_print_obj` to preserve IntEnum names | Session 2 |
| `enum_mod` | Route `class Color(enum.Enum)` through CPython bridge class system | Session 2 |
| `copy` | Mixed-type list detection (`list:mixed`); `_emit_mixed_elem_method` for `b[1].append(5)` | Session 3 |
| `threading_mod` | Prescan detects bridge call results appended to lists (`list:pyobj`); `_emit_for_list` loads elements as pyobj so `t.join()` routes through CPython bridge | Session 3 |
