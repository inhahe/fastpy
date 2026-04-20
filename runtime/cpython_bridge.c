/*
 * CPython bridge: enables fastpy-compiled programs to import and call
 * CPython extension modules (.pyd files).
 *
 * Embeds the CPython interpreter, provides functions to import modules,
 * get attributes, and call functions with automatic type conversion
 * between fastpy's FpyValue and CPython's PyObject*.
 */

#include <Python.h>
#include "objects.h"
#include "threading.h"
#include <stdio.h>
#include <string.h>

/* GIL release/acquire macros for CPython bridge calls.
 * Release fastpy's GIL before calling CPython (which has its own GIL).
 * Reacquire after returning. No-op in single-threaded mode. */
#define FPY_BRIDGE_ENTER() do { if (fpy_threading_mode == FPY_THREADING_GIL) fpy_gil_release(); } while(0)
#define FPY_BRIDGE_LEAVE() do { if (fpy_threading_mode == FPY_THREADING_GIL) fpy_gil_acquire(); } while(0)

/* ── Initialization ─────────────────────────────────────────────── */

static int cpython_initialized = 0;

void fpy_cpython_init(void) {
    if (cpython_initialized) return;
    /* Set PYTHONHOME so CPython finds its stdlib. Without this,
     * Py_Initialize fails when the exe is in a temp directory. */
    Py_SetPythonHome(L"D:\\python314");
    Py_Initialize();
    cpython_initialized = 1;
}

void fpy_cpython_fini(void) {
    if (!cpython_initialized) return;
    Py_FinalizeEx();
    cpython_initialized = 0;
}

/* ── Import ─────────────────────────────────────────────────────── */

/* Import a module by name. Returns an opaque PyObject* (as i8*).
 * The reference is owned — caller must eventually decref. */
void* fpy_cpython_import(const char *module_name) {
    fpy_cpython_init();  /* lazy init on first import */
    FPY_BRIDGE_ENTER();
    PyObject *mod = PyImport_ImportModule(module_name);
    FPY_BRIDGE_LEAVE();
    if (!mod) {
        PyErr_Print();
        fprintf(stderr, "ImportError: cannot import '%s'\n", module_name);
        exit(1);
    }
    return (void*)mod;
}

/* ── Attribute access ───────────────────────────────────────────── */

/* Get an attribute from a PyObject*. Returns a new reference. */
void* fpy_cpython_getattr(void *obj, const char *attr_name) {
    PyObject *result = PyObject_GetAttrString((PyObject*)obj, attr_name);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "AttributeError: '%s'\n", attr_name);
        exit(1);
    }
    return (void*)result;
}

/* ── Type conversion: FpyValue → PyObject* ──────────────────────── */

static PyObject* fpy_to_pyobject(int32_t tag, int64_t data) {
    switch (tag) {
        case FPY_TAG_INT:
            return PyLong_FromLongLong((long long)data);
        case FPY_TAG_FLOAT: {
            /* data holds bitcast of double */
            double d;
            memcpy(&d, &data, sizeof(double));
            return PyFloat_FromDouble(d);
        }
        case FPY_TAG_STR:
            return PyUnicode_FromString((const char*)(intptr_t)data);
        case FPY_TAG_BOOL:
            return PyBool_FromLong((long)data);
        case FPY_TAG_BYTES:
            return PyBytes_FromString((const char*)(intptr_t)data);
        case FPY_TAG_NONE:
            Py_RETURN_NONE;
        case FPY_TAG_OBJ: {
            /* Opaque PyObject* — pass through unchanged */
            PyObject *obj = (PyObject*)(intptr_t)data;
            Py_INCREF(obj);
            return obj;
        }
        case FPY_TAG_LIST: {
            /* Convert FpyList to PyList */
            FpyList *lst = (FpyList*)(intptr_t)data;
            PyObject *pylist = PyList_New(lst->length);
            for (int64_t i = 0; i < lst->length; i++) {
                FpyValue v = lst->items[i];
                PyList_SET_ITEM(pylist, i, fpy_to_pyobject(v.tag, v.data.i));
            }
            return pylist;
        }
        case FPY_TAG_DICT: {
            /* Convert FpyDict to PyDict */
            FpyDict *dict = (FpyDict*)(intptr_t)data;
            PyObject *pydict = PyDict_New();
            for (int64_t i = 0; i < dict->length; i++) {
                PyObject *pk = fpy_to_pyobject(dict->keys[i].tag,
                                                dict->keys[i].data.i);
                PyObject *pv = fpy_to_pyobject(dict->values[i].tag,
                                                dict->values[i].data.i);
                PyDict_SetItem(pydict, pk, pv);
                Py_DECREF(pk);
                Py_DECREF(pv);
            }
            return pydict;
        }
        default:
            /* Unknown type — return None */
            Py_RETURN_NONE;
    }
}

/* ── Type conversion: PyObject* → FpyValue ──────────────────────── */

static void pyobject_to_fpy(PyObject *obj, int32_t *out_tag, int64_t *out_data) {
    if (obj == Py_None) {
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
    } else if (PyBool_Check(obj)) {
        *out_tag = FPY_TAG_BOOL;
        *out_data = (obj == Py_True) ? 1 : 0;
    } else if (PyLong_Check(obj)) {
        *out_tag = FPY_TAG_INT;
        *out_data = (int64_t)PyLong_AsLongLong(obj);
    } else if (PyFloat_Check(obj)) {
        *out_tag = FPY_TAG_FLOAT;
        double d = PyFloat_AsDouble(obj);
        memcpy(out_data, &d, sizeof(double));
    } else if (PyUnicode_Check(obj)) {
        *out_tag = FPY_TAG_STR;
        /* Get UTF-8 string — we strdup because the PyObject may be freed */
        const char *s = PyUnicode_AsUTF8(obj);
        char *copy = _strdup(s ? s : "");
        *out_data = (int64_t)(intptr_t)copy;
    } else if (PyList_Check(obj)) {
        *out_tag = FPY_TAG_LIST;
        Py_ssize_t n = PyList_GET_SIZE(obj);
        FpyList *lst = fpy_list_new(n);
        for (Py_ssize_t i = 0; i < n; i++) {
            PyObject *item = PyList_GET_ITEM(obj, i);
            FpyValue v;
            pyobject_to_fpy(item, &v.tag, &v.data.i);
            fpy_list_append(lst, v);
        }
        *out_data = (int64_t)(intptr_t)lst;
    } else if (PyDict_Check(obj)) {
        *out_tag = FPY_TAG_DICT;
        FpyDict *dict = fpy_dict_new(4);
        PyObject *key, *value;
        Py_ssize_t pos = 0;
        while (PyDict_Next(obj, &pos, &key, &value)) {
            FpyValue fk, fv;
            pyobject_to_fpy(key, &fk.tag, &fk.data.i);
            pyobject_to_fpy(value, &fv.tag, &fv.data.i);
            fpy_dict_set(dict, fk, fv);
        }
        *out_data = (int64_t)(intptr_t)dict;
    } else {
        /* Opaque PyObject* — store as a tagged pointer.
         * We increment the refcount so it stays alive. */
        Py_INCREF(obj);
        *out_tag = FPY_TAG_OBJ;  /* reuse OBJ tag for opaque PyObject* */
        *out_data = (int64_t)(intptr_t)obj;
    }
}

/* ── Function calling ───────────────────────────────────────────── */

/* Call a PyObject* callable with fastpy-typed arguments.
 * Args are passed as parallel tag/data arrays (matching the FV ABI).
 * Returns the result as tag + data via output pointers. */
void fpy_cpython_call(void *callable, int32_t argc,
                       int32_t *arg_tags, int64_t *arg_data,
                       int32_t *out_tag, int64_t *out_data) {
    PyObject *args = PyTuple_New(argc);
    for (int i = 0; i < argc; i++) {
        PyObject *a = fpy_to_pyobject(arg_tags[i], arg_data[i]);
        PyTuple_SET_ITEM(args, i, a);  /* steals reference */
    }

    PyObject *result = PyObject_CallObject((PyObject*)callable, args);
    Py_DECREF(args);

    if (!result) {
        PyErr_Print();
        fprintf(stderr, "Error calling Python function\n");
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }

    pyobject_to_fpy(result, out_tag, out_data);
    Py_DECREF(result);
}

/* Convert a PyObject* to FpyValue (tag + data). Used for attribute
 * access on modules: `math.pi` returns a PyFloat which needs to be
 * converted to FpyValue{FLOAT, bits}. */
void fpy_cpython_to_fv(void *obj, int32_t *out_tag, int64_t *out_data) {
    pyobject_to_fpy((PyObject*)obj, out_tag, out_data);
    Py_DECREF((PyObject*)obj);  /* getattr returns a new reference */
}

/* Direct len() on a PyObject*. Returns the length as int64. */
int64_t fpy_cpython_len(void *obj) {
    Py_ssize_t n = PyObject_Length((PyObject*)obj);
    if (n < 0) { PyErr_Print(); return 0; }
    return (int64_t)n;
}

/* Direct bool() on a PyObject*. Returns 0 or 1. */
int64_t fpy_cpython_bool(void *obj) {
    return PyObject_IsTrue((PyObject*)obj) ? 1 : 0;
}

/* Simplified call for 0-arg functions (common: module.func()) */
void fpy_cpython_call0(void *callable,
                        int32_t *out_tag, int64_t *out_data) {
    PyObject *result = PyObject_CallNoArgs((PyObject*)callable);
    if (!result) {
        PyErr_Print();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    Py_DECREF(result);
}

/* Simplified call for 1-arg functions (common: math.sqrt(x)) */
void fpy_cpython_call1(void *callable,
                        int32_t arg_tag, int64_t arg_data,
                        int32_t *out_tag, int64_t *out_data) {
    PyObject *arg = fpy_to_pyobject(arg_tag, arg_data);
    PyObject *args = PyTuple_Pack(1, arg);
    Py_DECREF(arg);

    PyObject *result = PyObject_CallObject((PyObject*)callable, args);
    Py_DECREF(args);

    if (!result) {
        PyErr_Print();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    Py_DECREF(result);
}

/* Simplified call for 2-arg functions */
void fpy_cpython_call2(void *callable,
                        int32_t tag1, int64_t data1,
                        int32_t tag2, int64_t data2,
                        int32_t *out_tag, int64_t *out_data) {
    PyObject *a1 = fpy_to_pyobject(tag1, data1);
    PyObject *a2 = fpy_to_pyobject(tag2, data2);
    PyObject *args = PyTuple_Pack(2, a1, a2);
    Py_DECREF(a1);
    Py_DECREF(a2);

    PyObject *result = PyObject_CallObject((PyObject*)callable, args);
    Py_DECREF(args);

    if (!result) {
        PyErr_Print();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    Py_DECREF(result);
}

/* Raw call variants: return PyObject* directly without conversion.
 * Used when the result will be stored as pyobj for downstream method
 * calls, subscript access, etc. The caller owns the reference. */
void* fpy_cpython_call0_raw(void *callable) {
    PyObject *result = PyObject_CallNoArgs((PyObject*)callable);
    if (!result) { PyErr_Print(); return NULL; }
    return (void*)result;
}

void* fpy_cpython_call1_raw(void *callable,
                             int32_t arg_tag, int64_t arg_data) {
    PyObject *arg = fpy_to_pyobject(arg_tag, arg_data);
    PyObject *args = PyTuple_Pack(1, arg);
    Py_DECREF(arg);
    PyObject *result = PyObject_CallObject((PyObject*)callable, args);
    Py_DECREF(args);
    if (!result) { PyErr_Print(); return NULL; }
    return (void*)result;
}

void* fpy_cpython_call2_raw(void *callable,
                             int32_t t1, int64_t d1,
                             int32_t t2, int64_t d2) {
    PyObject *a1 = fpy_to_pyobject(t1, d1);
    PyObject *a2 = fpy_to_pyobject(t2, d2);
    PyObject *args = PyTuple_Pack(2, a1, a2);
    Py_DECREF(a1);
    Py_DECREF(a2);
    PyObject *result = PyObject_CallObject((PyObject*)callable, args);
    Py_DECREF(args);
    if (!result) { PyErr_Print(); return NULL; }
    return (void*)result;
}

/* Simplified call for 3-arg functions */
void fpy_cpython_call3(void *callable,
                        int32_t tag1, int64_t data1,
                        int32_t tag2, int64_t data2,
                        int32_t tag3, int64_t data3,
                        int32_t *out_tag, int64_t *out_data) {
    PyObject *a1 = fpy_to_pyobject(tag1, data1);
    PyObject *a2 = fpy_to_pyobject(tag2, data2);
    PyObject *a3 = fpy_to_pyobject(tag3, data3);
    PyObject *args = PyTuple_Pack(3, a1, a2, a3);
    Py_DECREF(a1);
    Py_DECREF(a2);
    Py_DECREF(a3);

    PyObject *result = PyObject_CallObject((PyObject*)callable, args);
    Py_DECREF(args);

    if (!result) {
        PyErr_Print();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    Py_DECREF(result);
}

/* ── General call with keyword arguments ──────────────────────────
 * Calls a callable with positional args (tag/data arrays) and
 * keyword args (name/tag/data arrays). Returns result via out ptrs. */
void fpy_cpython_call_kw(void *callable,
                          int32_t n_args, int32_t *arg_tags, int64_t *arg_data,
                          int32_t n_kwargs, const char **kw_names,
                          int32_t *kw_tags, int64_t *kw_data,
                          int32_t *out_tag, int64_t *out_data) {
    PyObject *args = PyTuple_New(n_args);
    for (int i = 0; i < n_args; i++) {
        PyObject *a = fpy_to_pyobject(arg_tags[i], arg_data[i]);
        PyTuple_SET_ITEM(args, i, a);
    }
    PyObject *kwargs = NULL;
    if (n_kwargs > 0) {
        kwargs = PyDict_New();
        for (int i = 0; i < n_kwargs; i++) {
            PyObject *v = fpy_to_pyobject(kw_tags[i], kw_data[i]);
            PyDict_SetItemString(kwargs, kw_names[i], v);
            Py_DECREF(v);
        }
    }
    FPY_BRIDGE_ENTER();
    PyObject *result = PyObject_Call((PyObject*)callable, args, kwargs);
    FPY_BRIDGE_LEAVE();
    Py_DECREF(args);
    if (kwargs) Py_DECREF(kwargs);
    if (!result) {
        PyErr_Print();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    Py_DECREF(result);
}

/* Same but returns raw PyObject* */
void* fpy_cpython_call_kw_raw(void *callable,
                               int32_t n_args, int32_t *arg_tags, int64_t *arg_data,
                               int32_t n_kwargs, const char **kw_names,
                               int32_t *kw_tags, int64_t *kw_data) {
    PyObject *args = PyTuple_New(n_args);
    for (int i = 0; i < n_args; i++) {
        PyObject *a = fpy_to_pyobject(arg_tags[i], arg_data[i]);
        PyTuple_SET_ITEM(args, i, a);
    }
    PyObject *kwargs = NULL;
    if (n_kwargs > 0) {
        kwargs = PyDict_New();
        for (int i = 0; i < n_kwargs; i++) {
            PyObject *v = fpy_to_pyobject(kw_tags[i], kw_data[i]);
            PyDict_SetItemString(kwargs, kw_names[i], v);
            Py_DECREF(v);
        }
    }
    FPY_BRIDGE_ENTER();
    PyObject *result = PyObject_Call((PyObject*)callable, args, kwargs);
    FPY_BRIDGE_LEAVE();
    Py_DECREF(args);
    if (kwargs) Py_DECREF(kwargs);
    if (!result) { PyErr_Print(); return NULL; }
    return (void*)result;
}

/* ── Flush Python's stdout (important for subprocess capture) ──── */

void fpy_cpython_flush(void) {
    if (!cpython_initialized) return;
    PyObject *sys = PyImport_ImportModule("sys");
    if (sys) {
        PyObject *out = PyObject_GetAttrString(sys, "stdout");
        if (out) {
            PyObject *r = PyObject_CallMethod(out, "flush", NULL);
            if (r) Py_DECREF(r);
            Py_DECREF(out);
        }
        Py_DECREF(sys);
    }
    PyErr_Clear();
}

/* ── Print a PyObject* via CPython's str() ─────────────────────── */

void fpy_cpython_print_obj(void *pyobj) {
    fpy_cpython_init();
    PyObject *s = PyObject_Str((PyObject*)pyobj);
    if (s) {
        const char *utf8 = PyUnicode_AsUTF8(s);
        if (utf8) printf("%s", utf8);
        Py_DECREF(s);
    } else {
        PyErr_Clear();
        printf("<object at %p>", pyobj);
    }
}

/* ── Native function wrapper ─────────────────────────────────────
 * Wraps a compiled function pointer as a CPython callable so it can
 * be passed to threading.Thread(target=...), map(), etc. through
 * the CPython bridge. The wrapper calls back into the native code. */

/* Stored function pointer for the wrapper callback */
typedef struct {
    PyObject_HEAD
    void (*func)(void);  /* native function pointer (void→void for workers) */
} FpyNativeCallable;

static PyObject* fpy_native_call(FpyNativeCallable *self,
                                  PyObject *args, PyObject *kwargs) {
    if (!self->func) Py_RETURN_NONE;

    Py_ssize_t n = args ? PyTuple_GET_SIZE(args) : 0;
    if (n == 0) {
        /* void(*)(void) */
        self->func();
    } else {
        /* Convert Python args to i64 and call with appropriate arity */
        typedef int64_t (*fn1_t)(int64_t);
        typedef int64_t (*fn2_t)(int64_t, int64_t);
        typedef int64_t (*fn3_t)(int64_t, int64_t, int64_t);
        int64_t a[4];
        for (Py_ssize_t i = 0; i < n && i < 4; i++) {
            int32_t tag; int64_t data;
            pyobject_to_fpy(PyTuple_GET_ITEM(args, i), &tag, &data);
            a[i] = data;
        }
        switch (n) {
            case 1: ((fn1_t)self->func)(a[0]); break;
            case 2: ((fn2_t)self->func)(a[0], a[1]); break;
            case 3: ((fn3_t)self->func)(a[0], a[1], a[2]); break;
            default: self->func(); break;
        }
    }
    fflush(stdout);
    Py_RETURN_NONE;
}

static PyTypeObject FpyNativeCallableType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fastpy.NativeCallable",
    .tp_basicsize = sizeof(FpyNativeCallable),
    .tp_call = (ternaryfunc)fpy_native_call,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
};

static int fpy_native_type_ready = 0;

/* Create a CPython callable that wraps a native void(*)(void) function. */
void* fpy_cpython_wrap_native(void *func_ptr) {
    fpy_cpython_init();
    if (!fpy_native_type_ready) {
        PyType_Ready(&FpyNativeCallableType);
        fpy_native_type_ready = 1;
    }
    FpyNativeCallable *obj = PyObject_New(FpyNativeCallable,
                                           &FpyNativeCallableType);
    obj->func = (void (*)(void))func_ptr;
    return (void*)obj;
}

/* ── Exec+Get ──────────────────────────────────────────────────── */

/* Execute Python source code in a temporary namespace, then extract
 * a named object (typically a function) and return it as a PyObject*.
 * Used for async def, generators needing send/close, etc. that must
 * run as real CPython functions. */
void* fpy_cpython_exec_get(const char *code, const char *name) {
    fpy_cpython_init();  /* lazy init */

    PyObject *globals = PyDict_New();
    /* builtins must be present for the exec'd code to access print, etc. */
    PyObject *builtins = PyImport_ImportModule("builtins");
    PyDict_SetItemString(globals, "__builtins__", builtins);
    Py_DECREF(builtins);

    PyObject *result = PyRun_String(code, Py_file_input, globals, globals);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "fpy_cpython_exec_get: failed to exec code\n");
        Py_DECREF(globals);
        exit(1);
    }
    Py_DECREF(result);  /* Py_None from exec */

    PyObject *value = PyDict_GetItemString(globals, name);
    if (!value) {
        fprintf(stderr, "fpy_cpython_exec_get: name '%s' not found after exec\n", name);
        Py_DECREF(globals);
        exit(1);
    }
    Py_INCREF(value);  /* we own a reference */
    Py_DECREF(globals);
    return (void*)value;
}

/* ── eval/exec with local variable namespace ──────────────────────── */

/* Convert an FpyDict to a CPython PyDict. */
static PyObject* fpy_dict_to_pydict(FpyDict *dict) {
    PyObject *pydict = PyDict_New();
    for (int64_t i = 0; i < dict->length; i++) {
        PyObject *pk = fpy_to_pyobject(dict->keys[i].tag, dict->keys[i].data.i);
        PyObject *pv = fpy_to_pyobject(dict->values[i].tag, dict->values[i].data.i);
        PyDict_SetItem(pydict, pk, pv);
        Py_DECREF(pk);
        Py_DECREF(pv);
    }
    return pydict;
}

/* eval(expr) with locals dict — evaluates expr in a namespace populated
 * from the caller's local variables. Returns the result as FpyValue. */
void fpy_cpython_eval_locals(const char *expr, FpyDict *locals_dict,
                              int32_t *out_tag, int64_t *out_data) {
    fpy_cpython_init();

    PyObject *globals = PyDict_New();
    PyObject *builtins = PyImport_ImportModule("builtins");
    PyDict_SetItemString(globals, "__builtins__", builtins);
    Py_DECREF(builtins);

    PyObject *locals = locals_dict ? fpy_dict_to_pydict(locals_dict) : PyDict_New();

    PyObject *result = PyRun_String(expr, Py_eval_input, globals, locals);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "fpy_cpython_eval_locals: eval failed\n");
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        Py_DECREF(globals);
        Py_DECREF(locals);
        return;
    }

    pyobject_to_fpy(result, out_tag, out_data);
    Py_DECREF(result);
    Py_DECREF(globals);
    Py_DECREF(locals);
}

/* exec(code) with locals dict — executes code in a namespace populated
 * from the caller's local variables. Returns void (exec has no value). */
void fpy_cpython_exec_locals(const char *code, FpyDict *locals_dict) {
    fpy_cpython_init();

    PyObject *globals = PyDict_New();
    PyObject *builtins = PyImport_ImportModule("builtins");
    PyDict_SetItemString(globals, "__builtins__", builtins);
    Py_DECREF(builtins);

    PyObject *locals = locals_dict ? fpy_dict_to_pydict(locals_dict) : PyDict_New();

    PyObject *result = PyRun_String(code, Py_file_input, globals, locals);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "fpy_cpython_exec_locals: exec failed\n");
    } else {
        Py_DECREF(result);
    }

    Py_DECREF(globals);
    Py_DECREF(locals);
    /* Flush CPython stdout immediately so exec'd print output
     * appears in the correct order relative to native printf. */
    fpy_cpython_flush();
}
