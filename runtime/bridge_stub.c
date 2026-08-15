/*
 * fastpy pure-mode CPython-bridge stubs.
 *
 * In "pure mode" (SlateOS / Q29 option A: AOT-compile to native without
 * embedding CPython), the runtime is linked WITHOUT cpython_bridge.c and
 * WITHOUT libpython. The runtime still contains fallback paths that defer to
 * the CPython bridge for operations it cannot handle natively — arbitrary
 * object repr()/str(), dynamic import, duck-typed operators/attribute access
 * on foreign (bridge) objects, etc. Those bridge entry points must still
 * resolve at link time.
 *
 * This translation unit provides them as stubs. Bridge objects can never be
 * created in a pure-mode build (there is no bridge to make one), so the
 * refcount hooks are no-ops and the operational entry points raise a
 * catchable RuntimeError — a pure-mode program links and runs, and only fails
 * (cleanly) if it actually reaches an unsupported bridge path.
 *
 * Compiled in place of cpython_bridge.c for pure-mode / cross targets.
 * Pointer-returning stubs use void* return types; C resolves these by symbol
 * name and pointer returns are ABI-identical to the callers' declared types.
 */

#include <stdint.h>
#include <stdio.h>

/* Raise machinery lives in runtime.c. RuntimeError == 6 (see FPY_EXC_* there). */
extern void fastpy_raise(int exc_type, const char *msg);
#define FPY_STUB_EXC_RUNTIMEERROR 6

static void fpy_pure_unsupported(void) {
    fastpy_raise(FPY_STUB_EXC_RUNTIMEERROR,
        "operation requires the CPython bridge, which is not available in "
        "pure-mode (no-CPython) builds");
}

/* --- Refcount hooks: no-op (no bridge objects exist in pure mode) --- */
void fpy_bridge_pyobj_incref(void *ptr) { (void)ptr; }
void fpy_bridge_pyobj_decref(void *ptr) { (void)ptr; }

/* --- Stringification --- */
const char *fpy_bridge_pyobj_repr(void *p) { (void)p; fpy_pure_unsupported(); return ""; }
const char *fpy_bridge_pyobj_str(void *p)  { (void)p; fpy_pure_unsupported(); return ""; }
const char *fpy_cpython_typeof(void *obj)  { (void)obj; fpy_pure_unsupported(); return "object"; }

/* --- Operators (results returned via out-params: tag/data) --- */
void fpy_cpython_binop(void *a, int32_t bt, int64_t bd, int32_t op,
                       int32_t *out_tag, int64_t *out_data) {
    (void)a; (void)bt; (void)bd; (void)op;
    fpy_pure_unsupported();
    if (out_tag) *out_tag = 0;
    if (out_data) *out_data = 0;
}
void fpy_cpython_rbinop(int32_t at, int64_t ad, void *b, int32_t op,
                        int32_t *out_tag, int64_t *out_data) {
    (void)at; (void)ad; (void)b; (void)op;
    fpy_pure_unsupported();
    if (out_tag) *out_tag = 0;
    if (out_data) *out_data = 0;
}
int32_t fpy_cpython_compare(void *a, void *b, int32_t op) {
    (void)a; (void)b; (void)op; fpy_pure_unsupported(); return 0;
}

/* --- Calls (results returned via out-params: tag/data) --- */
void fpy_cpython_call0(void *f, int32_t *out_tag, int64_t *out_data) {
    (void)f; fpy_pure_unsupported();
    if (out_tag) *out_tag = 0;
    if (out_data) *out_data = 0;
}
void fpy_cpython_call1(void *f, int32_t t1, int64_t d1,
                       int32_t *out_tag, int64_t *out_data) {
    (void)f; (void)t1; (void)d1; fpy_pure_unsupported();
    if (out_tag) *out_tag = 0;
    if (out_data) *out_data = 0;
}
void fpy_cpython_call2(void *f, int32_t t1, int64_t d1, int32_t t2, int64_t d2,
                       int32_t *out_tag, int64_t *out_data) {
    (void)f; (void)t1; (void)d1; (void)t2; (void)d2; fpy_pure_unsupported();
    if (out_tag) *out_tag = 0;
    if (out_data) *out_data = 0;
}
void fpy_cpython_call3(void *f, int32_t t1, int64_t d1, int32_t t2, int64_t d2,
                       int32_t t3, int64_t d3,
                       int32_t *out_tag, int64_t *out_data) {
    (void)f; (void)t1; (void)d1; (void)t2; (void)d2; (void)t3; (void)d3;
    fpy_pure_unsupported();
    if (out_tag) *out_tag = 0;
    if (out_data) *out_data = 0;
}

/* --- Introspection / access --- */
int64_t fpy_cpython_bool(void *o) { (void)o; fpy_pure_unsupported(); return 0; }
int64_t fpy_cpython_len(void *o)  { (void)o; fpy_pure_unsupported(); return 0; }
void   *fpy_cpython_getattr(void *o, const char *n) { (void)o; (void)n; fpy_pure_unsupported(); return (void *)0; }
void   *fpy_cpython_getitem(void *o, int32_t kt, int64_t kd) { (void)o; (void)kt; (void)kd; fpy_pure_unsupported(); return (void *)0; }
void   *fpy_cpython_import(const char *name) { (void)name; fpy_pure_unsupported(); return (void *)0; }

/* --- Native-module import/getattr: graceful degradation, NOT a hard error ---
 *
 * A native module (sys, os, math, ...) is dispatched natively for its known
 * attributes; the real CPython module object is only needed as a *fallback*
 * for the rare non-native attribute (e.g. os.supports_fd).  In pure mode
 * there is no CPython to import, but `import sys` itself must NOT fail — only
 * an actual use of an unsupported attribute should.  So these return a
 * non-NULL opaque sentinel with no raise: native dispatch never dereferences
 * it, and any genuine fallback (cpython_getattr / a call on a from-imported
 * name) still routes to the raising stubs above and fails cleanly at the
 * point of use.  The refcount hooks are no-ops, so the sentinel is safe to
 * store and decref. */
void   *fpy_cpython_import_native(const char *name) { (void)name; return (void *)1; }
void   *fpy_cpython_getattr_native(void *o, const char *n) { (void)o; (void)n; return (void *)1; }
void   *fpy_cpython_to_list(void *o) { (void)o; fpy_pure_unsupported(); return (void *)0; }

/* --- Output --- */
void fpy_cpython_print_obj(void *pyobj) { (void)pyobj; fpy_pure_unsupported(); }
/* Flush native stdout — there are no CPython buffers to flush in pure mode. */
void fpy_cpython_flush(void) { fflush(stdout); }
