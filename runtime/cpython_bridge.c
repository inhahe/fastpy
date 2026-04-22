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
#include "bigint.h"
#include "threading.h"
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif

/* GIL release/acquire macros for CPython bridge calls.
 * Release fastpy's GIL before calling CPython (which has its own GIL).
 * Reacquire after returning. No-op in single-threaded mode. */
#define FPY_BRIDGE_ENTER() do { if (fpy_threading_mode == FPY_THREADING_GIL) fpy_gil_release(); } while(0)
#define FPY_BRIDGE_LEAVE() do { if (fpy_threading_mode == FPY_THREADING_GIL) fpy_gil_acquire(); } while(0)

/* ── Initialization ─────────────────────────────────────────────── */

static int cpython_initialized = 0;

/* Python version baked in at compile time (from Python.h headers).
 * Compared against the runtime version to detect ABI mismatches. */
static const int fpy_compiled_python_major = PY_MAJOR_VERSION;
static const int fpy_compiled_python_minor = PY_MINOR_VERSION;

void fpy_cpython_init(void) {
    if (cpython_initialized) return;
    /* Set PYTHONHOME so CPython finds its stdlib. Without this,
     * Py_Initialize fails when the exe is in a temp directory.
     * On POSIX, the linked libpython usually self-discovers its prefix,
     * so we only override on Windows where the exe runs from a temp dir. */
#ifdef _WIN32
    {
        static wchar_t home[512];
        swprintf(home, 512, L"%hs", PYTHON_HOME_STR);
        Py_SetPythonHome(home);
    }
#endif
    Py_Initialize();
    /* ABI version check: compare the compile-time Python version (from
     * headers) with the actual runtime version (from the loaded DLL/SO).
     * Py_GetVersion() returns the runtime version string like "3.14.0".
     * A mismatch means the wrong libpython was loaded at runtime. */
    {
        const char *runtime_ver = Py_GetVersion();  /* e.g. "3.14.0 ..." */
        int rt_major = 0, rt_minor = 0;
        sscanf(runtime_ver, "%d.%d", &rt_major, &rt_minor);
        if (rt_major != fpy_compiled_python_major ||
            rt_minor != fpy_compiled_python_minor) {
            fprintf(stderr,
                "fastpy: Python ABI mismatch! "
                "Compiled against %d.%d, running with %d.%d.\n"
                "Recompile with the correct Python version or install Python %d.%d.\n",
                fpy_compiled_python_major, fpy_compiled_python_minor,
                rt_major, rt_minor,
                fpy_compiled_python_major, fpy_compiled_python_minor);
            exit(1);
        }
    }
    cpython_initialized = 1;
#ifdef _WIN32
    /* Py_Initialize() may switch stdout/stderr to binary (UTF-8) mode.
     * Restore text mode so printf's \n → \r\n conversion matches
     * CPython's behavior (csv.writer's \r\n line terminators, etc.). */
    _setmode(_fileno(stdout), _O_TEXT);
    _setmode(_fileno(stderr), _O_TEXT);
#endif
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

/* ── Forward declarations ──────────────────────────────────────── */
static PyObject* fpy_to_pyobject(int32_t tag, int64_t data);

/* ── Exception propagation ─────────────────────────────────────── */
/* Convert a pending Python exception into a fastpy raise, so the
 * compiled try/except machinery can catch it.  Replaces PyErr_Print()
 * in bridge call functions.  Returns the fastpy exc-type id.         */
extern void  fastpy_raise(int, const char*);
extern int   fastpy_exc_name_to_id(const char*);
extern char* fpy_strdup(const char*);

static void bridge_propagate_exception(void) {
    PyObject *ptype, *pvalue, *ptb;
    PyErr_Fetch(&ptype, &pvalue, &ptb);
    if (!ptype) { return; }       /* nothing pending – shouldn't happen */

    /* Get exception class name → fastpy exc id */
    const char *cls_name = "Exception";
    if (ptype && PyType_Check(ptype))
        cls_name = ((PyTypeObject*)ptype)->tp_name;
    int exc_id = fastpy_exc_name_to_id(cls_name);

    /* Get error message string */
    const char *msg = "";
    if (pvalue) {
        PyObject *s = PyObject_Str(pvalue);
        if (s) { msg = fpy_strdup(PyUnicode_AsUTF8(s)); Py_DECREF(s); }
    }

    Py_XDECREF(ptype);
    Py_XDECREF(pvalue);
    Py_XDECREF(ptb);

    fastpy_raise(exc_id, msg);
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

/* Set an attribute on a PyObject*. Takes a tag+data FpyValue. */
void fpy_cpython_setattr(void *obj, const char *attr_name,
                         int32_t val_tag, int64_t val_data) {
    PyObject *value = fpy_to_pyobject(val_tag, val_data);
    if (PyObject_SetAttrString((PyObject*)obj, attr_name, value) < 0) {
        PyErr_Print();
        fprintf(stderr, "Error setting attribute '%s'\n", attr_name);
    }
    Py_DECREF(value);
}

/* Check if a PyObject* has an attribute. Returns 1 (True) or 0 (False). */
int32_t fpy_cpython_hasattr(void *obj, const char *attr_name) {
    return PyObject_HasAttrString((PyObject*)obj, attr_name) ? 1 : 0;
}

/* ── Forward declarations ──────────────────────────────────────── */

/* Magic number for FpyClosure (defined in objects.c) */
#ifndef FPY_CLOSURE_MAGIC
#define FPY_CLOSURE_MAGIC 0x434C4F53  /* "CLOS" */
#endif

/* Closure proxy (defined below FpyNativeCallable section) */
typedef struct { PyObject_HEAD void *closure; int return_tag; } FpyClosureProxy;
static PyObject* fpy_closure_to_pyobject(void *closure_ptr);
static PyTypeObject FpyClosureProxyType;
static int fpy_closure_proxy_type_ready;

/* List sync-back (defined below closure proxy section) */
static void fpy_sync_pylist_to_fpylist(FpyList *orig, PyObject *mutated);
static void fpy_sync_list_args(int32_t argc, int32_t *arg_tags,
                                int64_t *arg_data, PyObject *args_tuple);

/* Refcount helpers (defined in objects.c) */
extern void fpy_rc_incref(int32_t tag, int64_t data);
extern void fpy_rc_decref(int32_t tag, int64_t data);

/* Dict constructor (defined in objects.c, missing from objects.h) */
extern FpyDict* fpy_dict_new(int64_t capacity);

/* Object instance proxy (defined below closure proxy section) */
typedef struct { PyObject_HEAD FpyObj *obj; } FpyObjProxy;
typedef struct { PyObject_HEAD FpyObj *obj; FpyMethodDef *method; } FpyBoundMethodProxy;
static PyObject* fpy_obj_to_pyobject(FpyObj *obj);
static PyTypeObject FpyObjProxyType;
static int fpy_obj_proxy_type_ready;
static PyTypeObject FpyBoundMethodProxyType;
static int fpy_bound_method_type_ready;

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
            /* Distinguish fastpy objects from real PyObject* using magic
             * numbers. FpyClosure and FpyObj are NOT PyObjects and must
             * be wrapped in a proxy before crossing to CPython. */
            void *ptr = (void*)(intptr_t)data;
            if (!ptr) Py_RETURN_NONE;
            int32_t first_word = *(int32_t*)ptr;
            if (first_word == FPY_CLOSURE_MAGIC) {
                /* fastpy closure → wrap as a callable CPython proxy */
                return fpy_closure_to_pyobject(ptr);
            }
            if (first_word > 0 && first_word < 100000) {
                FpyObj *fobj = (FpyObj*)ptr;
                if (fobj->magic == FPY_OBJ_MAGIC) {
                    /* fastpy class instance → wrap as a proxy with
                     * __getattr__, __setattr__, __str__, __repr__,
                     * __hash__, __eq__, and __call__ support. */
                    return fpy_obj_to_pyobject(fobj);
                }
            }
            /* Real CPython PyObject* — pass through */
            PyObject *obj = (PyObject*)ptr;
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
        case FPY_TAG_COMPLEX: {
            /* Convert FpyComplex to PyComplex */
            FpyComplex *c = (FpyComplex*)(intptr_t)data;
            if (!c) Py_RETURN_NONE;
            return PyComplex_FromDoubles(c->real, c->imag);
        }
        case FPY_TAG_SET: {
            /* Convert FpyDict (used as set) to PySet */
            FpyDict *dict = (FpyDict*)(intptr_t)data;
            if (!dict) return PySet_New(NULL);
            PyObject *pyset = PySet_New(NULL);
            for (int64_t i = 0; i < dict->length; i++) {
                PyObject *pk = fpy_to_pyobject(dict->keys[i].tag,
                                                dict->keys[i].data.i);
                PySet_Add(pyset, pk);
                Py_DECREF(pk);
            }
            return pyset;
        }
        case FPY_TAG_BIGINT: {
            /* Convert FpyBigInt to PyLong via string representation */
            FpyBigInt *bi = (FpyBigInt*)(intptr_t)data;
            if (!bi) return PyLong_FromLong(0);
            const char *s = fpy_bigint_to_str(bi);
            PyObject *result = PyLong_FromString(s, NULL, 10);
            free((void*)s);
            return result ? result : PyLong_FromLong(0);
        }
        case FPY_TAG_DECIMAL: {
            /* Convert FpyDecimal to Python decimal.Decimal via string */
            FpyDecimal *d = (FpyDecimal*)(intptr_t)data;
            if (!d) Py_RETURN_NONE;
            char *s = fpy_decimal_to_str(d);
            PyObject *decimal_mod = PyImport_ImportModule("decimal");
            if (!decimal_mod) { free(s); Py_RETURN_NONE; }
            PyObject *dec_cls = PyObject_GetAttrString(decimal_mod, "Decimal");
            Py_DECREF(decimal_mod);
            if (!dec_cls) { free(s); Py_RETURN_NONE; }
            PyObject *str_arg = PyUnicode_FromString(s);
            free(s);
            PyObject *result = PyObject_CallOneArg(dec_cls, str_arg);
            Py_DECREF(dec_cls);
            Py_DECREF(str_arg);
            return result ? result : Py_None;
        }
        default:
            /* Unknown type — return None */
            Py_RETURN_NONE;
    }
}

/* ── Type conversion: PyObject* → FpyValue ──────────────────────── */

static void pyobject_to_fpy(PyObject *obj, int32_t *out_tag, int64_t *out_data) {
    if (!obj) {
        /* NULL from a failed bridge call (TypeError, etc.) — return None
         * instead of tagging NULL as a real value and segfaulting later. */
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
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
        char *copy = fpy_strdup(s ? s : "");
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
    } else if (PyBytes_Check(obj)) {
        *out_tag = FPY_TAG_BYTES;
        /* Extract raw bytes data — copy since the PyObject may be freed.
         * Note: this uses strlen-based copy, so embedded nulls are truncated.
         * For full binary fidelity, a length-prefixed buffer would be needed. */
        const char *data = PyBytes_AS_STRING(obj);
        Py_ssize_t len = PyBytes_GET_SIZE(obj);
        char *copy = (char*)malloc(len + 1);
        memcpy(copy, data, len);
        copy[len] = '\0';
        *out_data = (int64_t)(intptr_t)copy;
    } else if (PyTuple_Check(obj)) {
        /* Convert PyTuple to FpyList (with is_tuple flag) */
        *out_tag = FPY_TAG_LIST;
        Py_ssize_t n = PyTuple_GET_SIZE(obj);
        FpyList *lst = fpy_list_new(n);
        lst->is_tuple = 1;
        for (Py_ssize_t i = 0; i < n; i++) {
            PyObject *item = PyTuple_GET_ITEM(obj, i);
            FpyValue v;
            pyobject_to_fpy(item, &v.tag, &v.data.i);
            fpy_list_append(lst, v);
        }
        *out_data = (int64_t)(intptr_t)lst;
    } else if (PyComplex_Check(obj)) {
        *out_tag = FPY_TAG_COMPLEX;
        double real = PyComplex_RealAsDouble(obj);
        double imag = PyComplex_ImagAsDouble(obj);
        FpyComplex *c = fpy_complex_new(real, imag);
        *out_data = (int64_t)(intptr_t)c;
    } else if (PySet_Check(obj) || PyFrozenSet_Check(obj)) {
        *out_tag = FPY_TAG_SET;
        Py_ssize_t n = PySet_GET_SIZE(obj);
        FpyDict *dict = fpy_dict_new(n > 4 ? (int32_t)n : 4);
        /* Iterate the set */
        PyObject *iter = PyObject_GetIter(obj);
        if (iter) {
            PyObject *item;
            while ((item = PyIter_Next(iter)) != NULL) {
                FpyValue fk;
                pyobject_to_fpy(item, &fk.tag, &fk.data.i);
                /* For sets, store element as key with None as value */
                FpyValue fv;
                fv.tag = FPY_TAG_NONE;
                fv.data.i = 0;
                fpy_dict_set(dict, fk, fv);
                Py_DECREF(item);
            }
            Py_DECREF(iter);
        }
        *out_data = (int64_t)(intptr_t)dict;
    } else if (fpy_closure_proxy_type_ready &&
               Py_TYPE(obj) == &FpyClosureProxyType) {
        /* Unwrap closure proxy — return the original fastpy closure */
        FpyClosureProxy *proxy = (FpyClosureProxy*)obj;
        *out_tag = FPY_TAG_OBJ;
        *out_data = (int64_t)(intptr_t)proxy->closure;
        fpy_rc_incref(FPY_TAG_OBJ, *out_data);
    } else if (fpy_obj_proxy_type_ready &&
               Py_TYPE(obj) == &FpyObjProxyType) {
        /* Unwrap object proxy — return the original fastpy FpyObj */
        FpyObjProxy *proxy = (FpyObjProxy*)obj;
        *out_tag = FPY_TAG_OBJ;
        *out_data = (int64_t)(intptr_t)proxy->obj;
        fpy_rc_incref(FPY_TAG_OBJ, *out_data);
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

    /* Sync-back: copy mutated PyList contents to original FpyList */
    fpy_sync_list_args(argc, arg_tags, arg_data, args);
    Py_DECREF(args);

    if (!result) {
        bridge_propagate_exception();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }

    pyobject_to_fpy(result, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
    Py_DECREF(result);
}

/* Convert a PyObject* to FpyValue (tag + data). Used for attribute
 * access on modules: `math.pi` returns a PyFloat which needs to be
 * converted to FpyValue{FLOAT, bits}. */
void fpy_cpython_to_fv(void *obj, int32_t *out_tag, int64_t *out_data) {
    pyobject_to_fpy((PyObject*)obj, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep the reference alive
     * (since we're giving the caller a raw pointer) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF((PyObject*)obj);
    Py_DECREF((PyObject*)obj);
}

/* Convert an FpyValue (tag, data) to a PyObject*.
 * Exported wrapper around the static fpy_to_pyobject. */
void* fpy_cpython_to_pyobj(int32_t tag, int64_t data) {
    return (void*)fpy_to_pyobject(tag, data);
}

/* Direct subscript on a PyObject*. Returns raw PyObject* (no conversion).
 * Keeps the result in Python object form for chained operations. */
void* fpy_cpython_getitem(void *obj, int32_t key_tag, int64_t key_data) {
    PyObject *key = fpy_to_pyobject(key_tag, key_data);
    PyObject *result = PyObject_GetItem((PyObject*)obj, key);
    Py_DECREF(key);
    if (!result) {
        bridge_propagate_exception();
        Py_RETURN_NONE;
    }
    /* Don't decref — caller owns the reference */
    return result;
}

/* Direct attribute access on a PyObject*. Returns raw PyObject*. */
void* fpy_cpython_getattr_val(void *obj, const char *name) {
    PyObject *result = PyObject_GetAttrString((PyObject*)obj, name);
    if (!result) {
        bridge_propagate_exception();
        Py_RETURN_NONE;
    }
    return result;
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
        bridge_propagate_exception();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
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

    /* Sync-back: if the argument was a list, copy mutations back */
    if (arg_tag == FPY_TAG_LIST) {
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)arg_data,
                                    PyTuple_GET_ITEM(args, 0));
    }
    Py_DECREF(args);

    if (!result) {
        bridge_propagate_exception();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
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

    /* Sync-back: if any argument was a list, copy mutations back */
    if (tag1 == FPY_TAG_LIST)
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)data1,
                                    PyTuple_GET_ITEM(args, 0));
    if (tag2 == FPY_TAG_LIST)
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)data2,
                                    PyTuple_GET_ITEM(args, 1));
    Py_DECREF(args);

    if (!result) {
        bridge_propagate_exception();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
    Py_DECREF(result);
}

/* Raw call variants: return PyObject* directly without conversion.
 * Used when the result will be stored as pyobj for downstream method
 * calls, subscript access, etc. The caller owns the reference. */
void* fpy_cpython_call0_raw(void *callable) {
    PyObject *result = PyObject_CallNoArgs((PyObject*)callable);
    if (!result) { bridge_propagate_exception(); return NULL; }
    return (void*)result;
}

void* fpy_cpython_call1_raw(void *callable,
                             int32_t arg_tag, int64_t arg_data) {
    PyObject *arg = fpy_to_pyobject(arg_tag, arg_data);
    PyObject *args = PyTuple_Pack(1, arg);
    Py_DECREF(arg);
    PyObject *result = PyObject_CallObject((PyObject*)callable, args);
    if (arg_tag == FPY_TAG_LIST)
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)arg_data,
                                    PyTuple_GET_ITEM(args, 0));
    Py_DECREF(args);
    if (!result) { bridge_propagate_exception(); return NULL; }
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
    if (t1 == FPY_TAG_LIST)
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)d1,
                                    PyTuple_GET_ITEM(args, 0));
    if (t2 == FPY_TAG_LIST)
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)d2,
                                    PyTuple_GET_ITEM(args, 1));
    Py_DECREF(args);
    if (!result) { bridge_propagate_exception(); return NULL; }
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

    /* Sync-back: if any argument was a list, copy mutations back */
    if (tag1 == FPY_TAG_LIST)
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)data1,
                                    PyTuple_GET_ITEM(args, 0));
    if (tag2 == FPY_TAG_LIST)
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)data2,
                                    PyTuple_GET_ITEM(args, 1));
    if (tag3 == FPY_TAG_LIST)
        fpy_sync_pylist_to_fpylist((FpyList*)(intptr_t)data3,
                                    PyTuple_GET_ITEM(args, 2));
    Py_DECREF(args);

    if (!result) {
        bridge_propagate_exception();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
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

    /* Sync-back: copy mutated PyList contents to original FpyList */
    fpy_sync_list_args(n_args, arg_tags, arg_data, args);
    Py_DECREF(args);
    if (kwargs) Py_DECREF(kwargs);
    if (!result) {
        bridge_propagate_exception();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
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
    fpy_sync_list_args(n_args, arg_tags, arg_data, args);
    Py_DECREF(args);
    if (kwargs) Py_DECREF(kwargs);
    if (!result) { bridge_propagate_exception(); return NULL; }
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

/* ── Closure proxy ──────────────────────────────────────────────
 * Wraps a fastpy FpyClosure as a CPython callable PyObject* so it
 * can be passed to CPython code that expects a callable (e.g.
 * _functools.reduce, _collections.defaultdict, map, filter, etc.).
 *
 * The proxy converts CPython args → FpyList, calls the closure via
 * fastpy_closure_call_list(), and converts the i64 result back to a
 * PyObject*.  When the proxy is destroyed, the closure's refcount is
 * decremented. */

/* FpyClosureProxy is forward-declared near the top of this file.
 * The actual fields: { PyObject_HEAD; void *closure; int return_tag; } */

/* Forward: declared in objects.h / objects.c */
extern int64_t fastpy_closure_call_list(void *closure, void *args_list);

static PyObject* fpy_closure_proxy_call(FpyClosureProxy *self,
                                         PyObject *args, PyObject *kwargs) {
    if (!self->closure) Py_RETURN_NONE;

    /* Convert Python args → FpyList for fastpy_closure_call_list */
    Py_ssize_t n = args ? PyTuple_GET_SIZE(args) : 0;
    FpyList *fpy_args = fpy_list_new(n);
    for (Py_ssize_t i = 0; i < n; i++) {
        FpyValue v;
        pyobject_to_fpy(PyTuple_GET_ITEM(args, i), &v.tag, &v.data.i);
        fpy_list_append(fpy_args, v);
    }

    int64_t result_i64 = fastpy_closure_call_list(self->closure, fpy_args);

    /* The closure returns a raw i64. Convert to PyObject* based on the
     * return tag. In most callback scenarios (map, filter, reduce) the
     * result is an int, but we try to be smart about it. */
    PyObject *result;
    switch (self->return_tag) {
        case FPY_TAG_FLOAT: {
            double d;
            memcpy(&d, &result_i64, sizeof(double));
            result = PyFloat_FromDouble(d);
            break;
        }
        case FPY_TAG_STR:
            result = PyUnicode_FromString((const char*)(intptr_t)result_i64);
            break;
        case FPY_TAG_BOOL:
            result = PyBool_FromLong((long)result_i64);
            break;
        case FPY_TAG_NONE:
            Py_RETURN_NONE;
        default:
            /* INT or unknown — return as Python int */
            result = PyLong_FromLongLong((long long)result_i64);
            break;
    }
    return result;
}

static void fpy_closure_proxy_dealloc(PyObject *self) {
    FpyClosureProxy *proxy = (FpyClosureProxy*)self;
    if (proxy->closure) {
        fpy_rc_decref(FPY_TAG_OBJ, (int64_t)(intptr_t)proxy->closure);
    }
    Py_TYPE(self)->tp_free(self);
}

static PyObject* fpy_closure_proxy_repr(PyObject *self) {
    FpyClosureProxy *proxy = (FpyClosureProxy*)self;
    return PyUnicode_FromFormat("<fastpy closure at %p>", proxy->closure);
}

static PyTypeObject FpyClosureProxyType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fastpy.ClosureProxy",
    .tp_basicsize = sizeof(FpyClosureProxy),
    .tp_dealloc = fpy_closure_proxy_dealloc,
    .tp_repr = fpy_closure_proxy_repr,
    .tp_call = (ternaryfunc)fpy_closure_proxy_call,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
};

static int fpy_closure_proxy_type_ready = 0;

/* Wrap a fastpy closure as a CPython callable. */
static PyObject* fpy_closure_to_pyobject(void *closure_ptr) {
    if (!fpy_closure_proxy_type_ready) {
        PyType_Ready(&FpyClosureProxyType);
        fpy_closure_proxy_type_ready = 1;
    }
    FpyClosureProxy *proxy = PyObject_New(FpyClosureProxy,
                                           &FpyClosureProxyType);
    proxy->closure = closure_ptr;
    proxy->return_tag = FPY_TAG_INT;  /* default — most callbacks return int */
    fpy_rc_incref(FPY_TAG_OBJ, (int64_t)(intptr_t)closure_ptr);
    return (PyObject*)proxy;
}

/* ── FpyObj instance proxy ──────────────────────────────────────────
 * Wraps a fastpy FpyObj (class instance) as a CPython PyObject* so it
 * can participate in CPython operations: attribute access, method calls,
 * comparisons, hashing, printing, and (if __call__ exists) be used as a
 * callable.
 *
 * Also provides FpyBoundMethodProxy — a callable that wraps a specific
 * method bound to an instance, returned by __getattr__. */

/* Forward declarations from objects.c */
extern FpyClassDef fpy_classes[];
extern FpyMethodDef* fastpy_find_method(int class_id, const char *name);
extern const char*   fastpy_obj_to_str(FpyObj *obj);
extern int64_t fastpy_obj_call_method0(FpyObj *obj, const char *name);
extern int64_t fastpy_obj_call_method1(FpyObj *obj, const char *name, int64_t a);
extern int64_t fastpy_obj_call_method2(FpyObj *obj, const char *name, int64_t a, int64_t b);

/* Safe attribute lookup: returns 1 if found, 0 if not (does NOT exit). */
static int fpy_obj_try_get_attr(FpyObj *obj, const char *name,
                                 int32_t *out_tag, int64_t *out_data) {
    FpyClassDef *cls = &fpy_classes[obj->class_id];
    /* Static slots */
    for (int i = 0; i < cls->slot_count; i++) {
        if (cls->slot_names[i] &&
            (cls->slot_names[i] == name ||
             strcmp(cls->slot_names[i], name) == 0)) {
            *out_tag = obj->slots[i].tag;
            *out_data = obj->slots[i].data.i;
            return 1;
        }
    }
    /* Dynamic attrs */
    FpyObjAttrs *a = obj->dynamic_attrs;
    if (a) {
        for (int i = 0; i < a->count; i++) {
            if (a->names[i] == name ||
                strcmp(a->names[i], name) == 0) {
                *out_tag = a->values[i].tag;
                *out_data = a->values[i].data.i;
                return 1;
            }
        }
    }
    return 0;
}

/* ── Bound method proxy ──────────────────────────────────────────── */

/* FpyBoundMethodProxy is forward-declared near the top of this file. */

static PyObject* fpy_bound_method_call(FpyBoundMethodProxy *self,
                                        PyObject *args, PyObject *kwargs) {
    if (!self->obj || !self->method) Py_RETURN_NONE;

    Py_ssize_t n = args ? PyTuple_GET_SIZE(args) : 0;
    int64_t a[4] = {0};
    for (Py_ssize_t i = 0; i < n && i < 4; i++) {
        int32_t tag; int64_t data;
        pyobject_to_fpy(PyTuple_GET_ITEM(args, i), &tag, &data);
        a[i] = data;
    }

    typedef int64_t (*m0_t)(FpyObj*);
    typedef int64_t (*m1_t)(FpyObj*, int64_t);
    typedef int64_t (*m2_t)(FpyObj*, int64_t, int64_t);
    typedef int64_t (*m3_t)(FpyObj*, int64_t, int64_t, int64_t);
    typedef int64_t (*m4_t)(FpyObj*, int64_t, int64_t, int64_t, int64_t);

    int64_t result;
    switch (n) {
        case 0: result = ((m0_t)self->method->func)(self->obj); break;
        case 1: result = ((m1_t)self->method->func)(self->obj, a[0]); break;
        case 2: result = ((m2_t)self->method->func)(self->obj, a[0], a[1]); break;
        case 3: result = ((m3_t)self->method->func)(self->obj, a[0], a[1], a[2]); break;
        case 4: result = ((m4_t)self->method->func)(self->obj, a[0], a[1], a[2], a[3]); break;
        default: result = ((m0_t)self->method->func)(self->obj); break;
    }

    if (self->method->returns_value) {
        return PyLong_FromLongLong((long long)result);
    }
    Py_RETURN_NONE;
}

static void fpy_bound_method_dealloc(PyObject *self) {
    FpyBoundMethodProxy *proxy = (FpyBoundMethodProxy*)self;
    if (proxy->obj)
        fpy_rc_decref(FPY_TAG_OBJ, (int64_t)(intptr_t)proxy->obj);
    Py_TYPE(self)->tp_free(self);
}

static PyObject* fpy_bound_method_repr(PyObject *self) {
    FpyBoundMethodProxy *proxy = (FpyBoundMethodProxy*)self;
    return PyUnicode_FromFormat("<bound method %s of %s object at %p>",
                                proxy->method ? proxy->method->name : "?",
                                proxy->obj ?
                                    fpy_classes[proxy->obj->class_id].name : "?",
                                proxy->obj);
}

static PyTypeObject FpyBoundMethodProxyType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fastpy.BoundMethod",
    .tp_basicsize = sizeof(FpyBoundMethodProxy),
    .tp_dealloc = fpy_bound_method_dealloc,
    .tp_repr = fpy_bound_method_repr,
    .tp_call = (ternaryfunc)fpy_bound_method_call,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
};

static int fpy_bound_method_type_ready = 0;

static PyObject* fpy_make_bound_method(FpyObj *obj, FpyMethodDef *method) {
    if (!fpy_bound_method_type_ready) {
        PyType_Ready(&FpyBoundMethodProxyType);
        fpy_bound_method_type_ready = 1;
    }
    FpyBoundMethodProxy *proxy = PyObject_New(FpyBoundMethodProxy,
                                               &FpyBoundMethodProxyType);
    proxy->obj = obj;
    proxy->method = method;
    fpy_rc_incref(FPY_TAG_OBJ, (int64_t)(intptr_t)obj);
    return (PyObject*)proxy;
}

/* ── FpyObj proxy slots ──────────────────────────────────────────── */

/* FpyObjProxy is forward-declared near the top of this file. */

static PyObject* fpy_obj_proxy_getattr(PyObject *self, PyObject *name_obj) {
    FpyObjProxy *proxy = (FpyObjProxy*)self;
    FpyObj *obj = proxy->obj;
    if (!obj) {
        PyErr_SetString(PyExc_AttributeError, "null fastpy object");
        return NULL;
    }
    const char *name = PyUnicode_AsUTF8(name_obj);
    if (!name) return NULL;

    /* Check for methods first (walk MRO) */
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (m) return fpy_make_bound_method(obj, m);

    /* Check data attributes (slots + dynamic) */
    int32_t tag; int64_t data;
    if (fpy_obj_try_get_attr(obj, name, &tag, &data)) {
        return fpy_to_pyobject(tag, data);
    }

    PyErr_Format(PyExc_AttributeError,
                 "'%s' object has no attribute '%.200s'",
                 fpy_classes[obj->class_id].name, name);
    return NULL;
}

static int fpy_obj_proxy_setattr(PyObject *self, PyObject *name_obj,
                                  PyObject *value) {
    FpyObjProxy *proxy = (FpyObjProxy*)self;
    FpyObj *obj = proxy->obj;
    if (!obj) {
        PyErr_SetString(PyExc_AttributeError, "null fastpy object");
        return -1;
    }
    const char *name = PyUnicode_AsUTF8(name_obj);
    if (!name) return -1;

    /* Declared in objects.c */
    extern void fastpy_obj_set_fv(FpyObj *, const char *, int32_t, int64_t);

    int32_t tag; int64_t data;
    pyobject_to_fpy(value, &tag, &data);
    fastpy_obj_set_fv(obj, name, tag, data);
    return 0;
}

static PyObject* fpy_obj_proxy_str(PyObject *self) {
    FpyObjProxy *proxy = (FpyObjProxy*)self;
    if (!proxy->obj) return PyUnicode_FromString("<null fastpy object>");
    const char *s = fastpy_obj_to_str(proxy->obj);
    return PyUnicode_FromString(s ? s : "<fastpy object>");
}

static PyObject* fpy_obj_proxy_repr(PyObject *self) {
    FpyObjProxy *proxy = (FpyObjProxy*)self;
    if (!proxy->obj) return PyUnicode_FromString("<null fastpy object>");
    /* Try __repr__ specifically */
    FpyMethodDef *m = fastpy_find_method(proxy->obj->class_id, "__repr__");
    if (m) {
        int64_t result = ((FpyMethodFunc)m->func)(proxy->obj);
        const char *s = (const char*)(intptr_t)result;
        return PyUnicode_FromString(s ? s : "<fastpy object>");
    }
    return PyUnicode_FromFormat("<%s object at %p>",
                                fpy_classes[proxy->obj->class_id].name,
                                proxy->obj);
}

static Py_hash_t fpy_obj_proxy_hash(PyObject *self) {
    FpyObjProxy *proxy = (FpyObjProxy*)self;
    if (!proxy->obj) return 0;
    FpyMethodDef *m = fastpy_find_method(proxy->obj->class_id, "__hash__");
    if (m) {
        int64_t h = ((FpyMethodFunc)m->func)(proxy->obj);
        return (Py_hash_t)h;
    }
    /* Default: hash by pointer identity */
    return (Py_hash_t)(intptr_t)proxy->obj;
}

static PyObject* fpy_obj_proxy_richcompare(PyObject *self, PyObject *other,
                                            int op) {
    FpyObjProxy *proxy = (FpyObjProxy*)self;
    if (!proxy->obj) Py_RETURN_NOTIMPLEMENTED;

    /* Map CPython op → dunder method name */
    const char *dunder = NULL;
    switch (op) {
        case Py_EQ: dunder = "__eq__"; break;
        case Py_NE: dunder = "__ne__"; break;
        case Py_LT: dunder = "__lt__"; break;
        case Py_LE: dunder = "__le__"; break;
        case Py_GT: dunder = "__gt__"; break;
        case Py_GE: dunder = "__ge__"; break;
        default: Py_RETURN_NOTIMPLEMENTED;
    }
    FpyMethodDef *m = fastpy_find_method(proxy->obj->class_id, dunder);
    if (!m) {
        /* For __eq__, default to identity comparison */
        if (op == Py_EQ) {
            if (Py_TYPE(other) == &FpyObjProxyType) {
                FpyObjProxy *op2 = (FpyObjProxy*)other;
                return PyBool_FromLong(proxy->obj == op2->obj);
            }
            Py_RETURN_FALSE;
        }
        if (op == Py_NE) {
            if (Py_TYPE(other) == &FpyObjProxyType) {
                FpyObjProxy *op2 = (FpyObjProxy*)other;
                return PyBool_FromLong(proxy->obj != op2->obj);
            }
            Py_RETURN_TRUE;
        }
        Py_RETURN_NOTIMPLEMENTED;
    }

    /* Convert 'other' to i64 for the fastpy method */
    int32_t tag; int64_t data;
    pyobject_to_fpy(other, &tag, &data);
    int64_t result = ((FpyMethod1Func)m->func)(proxy->obj, data);
    return PyBool_FromLong(result != 0);
}

static PyObject* fpy_obj_proxy_call(PyObject *self,
                                     PyObject *args, PyObject *kwargs) {
    FpyObjProxy *proxy = (FpyObjProxy*)self;
    if (!proxy->obj) {
        PyErr_SetString(PyExc_TypeError, "null fastpy object is not callable");
        return NULL;
    }
    FpyMethodDef *m = fastpy_find_method(proxy->obj->class_id, "__call__");
    if (!m) {
        PyErr_Format(PyExc_TypeError,
                     "'%s' object is not callable",
                     fpy_classes[proxy->obj->class_id].name);
        return NULL;
    }

    Py_ssize_t n = args ? PyTuple_GET_SIZE(args) : 0;
    int64_t a[4] = {0};
    for (Py_ssize_t i = 0; i < n && i < 4; i++) {
        int32_t tag; int64_t data;
        pyobject_to_fpy(PyTuple_GET_ITEM(args, i), &tag, &data);
        a[i] = data;
    }

    typedef int64_t (*m0_t)(FpyObj*);
    typedef int64_t (*m1_t)(FpyObj*, int64_t);
    typedef int64_t (*m2_t)(FpyObj*, int64_t, int64_t);
    typedef int64_t (*m3_t)(FpyObj*, int64_t, int64_t, int64_t);
    typedef int64_t (*m4_t)(FpyObj*, int64_t, int64_t, int64_t, int64_t);

    int64_t result;
    switch (n) {
        case 0: result = ((m0_t)m->func)(proxy->obj); break;
        case 1: result = ((m1_t)m->func)(proxy->obj, a[0]); break;
        case 2: result = ((m2_t)m->func)(proxy->obj, a[0], a[1]); break;
        case 3: result = ((m3_t)m->func)(proxy->obj, a[0], a[1], a[2]); break;
        case 4: result = ((m4_t)m->func)(proxy->obj, a[0], a[1], a[2], a[3]); break;
        default: result = ((m0_t)m->func)(proxy->obj); break;
    }

    if (m->returns_value)
        return PyLong_FromLongLong((long long)result);
    Py_RETURN_NONE;
}

static void fpy_obj_proxy_dealloc(PyObject *self) {
    FpyObjProxy *proxy = (FpyObjProxy*)self;
    if (proxy->obj)
        fpy_rc_decref(FPY_TAG_OBJ, (int64_t)(intptr_t)proxy->obj);
    Py_TYPE(self)->tp_free(self);
}

static PyTypeObject FpyObjProxyType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fastpy.ObjectProxy",
    .tp_basicsize = sizeof(FpyObjProxy),
    .tp_dealloc = fpy_obj_proxy_dealloc,
    .tp_repr = fpy_obj_proxy_repr,
    .tp_str = fpy_obj_proxy_str,
    .tp_hash = fpy_obj_proxy_hash,
    .tp_call = fpy_obj_proxy_call,
    .tp_getattro = fpy_obj_proxy_getattr,
    .tp_setattro = fpy_obj_proxy_setattr,
    .tp_richcompare = fpy_obj_proxy_richcompare,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
};

static int fpy_obj_proxy_type_ready = 0;

/* Wrap a fastpy FpyObj instance as a CPython PyObject*. */
static PyObject* fpy_obj_to_pyobject(FpyObj *obj) {
    if (!fpy_obj_proxy_type_ready) {
        PyType_Ready(&FpyObjProxyType);
        fpy_obj_proxy_type_ready = 1;
    }
    FpyObjProxy *proxy = PyObject_New(FpyObjProxy, &FpyObjProxyType);
    proxy->obj = obj;
    fpy_rc_incref(FPY_TAG_OBJ, (int64_t)(intptr_t)obj);
    return (PyObject*)proxy;
}

/* ── List sync-back ────────────────────────────────────────────────
 * After a bridge call, if an argument was FPY_TAG_LIST, CPython may
 * have mutated the temporary PyList (e.g. heapq.heapify, list.sort).
 * This function copies the mutated PyList contents back to the
 * original FpyList so the mutation is visible to fastpy code. */

static void fpy_sync_pylist_to_fpylist(FpyList *orig, PyObject *mutated) {
    if (!orig || !mutated || !PyList_Check(mutated)) return;
    Py_ssize_t new_len = PyList_GET_SIZE(mutated);

    /* Overwrite existing slots (fpy_list_set handles decref/incref) */
    Py_ssize_t common = (new_len < orig->length) ? new_len : orig->length;
    for (Py_ssize_t i = 0; i < common; i++) {
        FpyValue v;
        pyobject_to_fpy(PyList_GET_ITEM(mutated, i), &v.tag, &v.data.i);
        fpy_list_set(orig, (int64_t)i, v);
    }
    /* If the list grew (e.g. heappush), append new items */
    for (Py_ssize_t i = common; i < new_len; i++) {
        FpyValue v;
        pyobject_to_fpy(PyList_GET_ITEM(mutated, i), &v.tag, &v.data.i);
        fpy_list_append(orig, v);
    }
    /* If the list shrank (e.g. heappop), truncate.
     * Decref removed items via fpy_rc_decref. */
    for (int64_t i = new_len; i < orig->length; i++) {
        fpy_rc_decref(orig->items[i].tag, orig->items[i].data.i);
    }
    if (new_len < orig->length) {
        orig->length = new_len;
    }
}

/* Sync all LIST-tagged positional arguments from a PyTuple back to
 * their original FpyList after a bridge call. */
static void fpy_sync_list_args(int32_t argc, int32_t *arg_tags,
                                int64_t *arg_data, PyObject *args_tuple) {
    for (int i = 0; i < argc; i++) {
        if (arg_tags[i] == FPY_TAG_LIST) {
            FpyList *orig = (FpyList*)(intptr_t)arg_data[i];
            PyObject *mutated = PyTuple_GET_ITEM(args_tuple, i);
            fpy_sync_pylist_to_fpylist(orig, mutated);
        }
    }
}

/* ── Exec+Get ──────────────────────────────────────────────────── */

/* ── Compiled code cache for exec/eval ──────────────────────────── */
/* Caches compiled PyCodeObjects keyed by source hash.
 * Avoids re-parsing the same string on repeated exec/eval calls. */

#define FPY_CODE_CACHE_SIZE 128
static struct {
    uint64_t hash;
    PyObject *code;  /* compiled PyCodeObject */
} fpy_code_cache[FPY_CODE_CACHE_SIZE];
static int fpy_code_cache_used = 0;

static uint64_t fpy_hash_str(const char *s) {
    uint64_t h = 14695981039346656037ULL;
    while (*s) {
        h ^= (uint8_t)*s++;
        h *= 1099511628211ULL;
    }
    return h;
}

static PyObject* fpy_get_cached_code(const char *source, int mode) {
    uint64_t h = fpy_hash_str(source) ^ (uint64_t)mode;
    /* Check cache */
    for (int i = 0; i < fpy_code_cache_used; i++) {
        if (fpy_code_cache[i].hash == h)
            return fpy_code_cache[i].code;
    }
    /* Compile and cache */
    PyObject *code = Py_CompileString(source,
        "<fastpy-exec>",
        mode == 0 ? Py_file_input : Py_eval_input);
    if (!code) return NULL;
    if (fpy_code_cache_used < FPY_CODE_CACHE_SIZE) {
        fpy_code_cache[fpy_code_cache_used].hash = h;
        fpy_code_cache[fpy_code_cache_used].code = code;
        fpy_code_cache_used++;
    }
    return code;
}

/* ── Native JIT compilation ──────────────────────────────────────── */
/* Attempts to compile source to native code via the fastpy compiler.
 * Returns a function pointer if successful, NULL if fallback needed.
 * The JIT module (compiler/jit.py) must be importable. */

typedef void (*FpyJitFunc)(void);

static FpyJitFunc fpy_jit_try_compile(const char *source) {
    fpy_cpython_init();

    /* Import the JIT module */
    PyObject *jit_module = PyImport_ImportModule("compiler.jit");
    if (!jit_module) {
        PyErr_Clear();
        return NULL;  /* JIT not available — fall back to interpreter */
    }

    /* Call jit_compile(source) → function pointer as int */
    PyObject *compile_func = PyObject_GetAttrString(jit_module, "jit_compile");
    Py_DECREF(jit_module);
    if (!compile_func) {
        PyErr_Clear();
        return NULL;
    }

    PyObject *py_source = PyUnicode_FromString(source);
    PyObject *result = PyObject_CallOneArg(compile_func, py_source);
    Py_DECREF(py_source);
    Py_DECREF(compile_func);

    if (!result) {
        PyErr_Clear();
        return NULL;
    }

    long long func_ptr = PyLong_AsLongLong(result);
    Py_DECREF(result);

    if (func_ptr == 0 || func_ptr == -1) {
        PyErr_Clear();
        return NULL;
    }

    return (FpyJitFunc)(intptr_t)func_ptr;
}

/* Execute source natively if JIT succeeds, otherwise fall back to CPython.
 * Called from the runtime when exec(dynamic_string) is encountered. */
void fpy_jit_exec(const char *source) {
    /* Try native JIT first */
    FpyJitFunc func = fpy_jit_try_compile(source);
    if (func) {
        func();  /* Call the native compiled function */
        return;
    }

    /* Fallback: use CPython interpreter */
    fpy_cpython_init();
    PyObject *globals = PyDict_New();
    PyObject *builtins = PyImport_ImportModule("builtins");
    PyDict_SetItemString(globals, "__builtins__", builtins);
    Py_DECREF(builtins);

    PyObject *code = fpy_get_cached_code(source, 0);
    PyObject *result;
    if (code) {
        result = PyEval_EvalCode(code, globals, globals);
    } else {
        PyErr_Clear();
        result = PyRun_String(source, Py_file_input, globals, globals);
    }
    if (!result) PyErr_Print();
    else Py_DECREF(result);
    Py_DECREF(globals);
    fpy_cpython_flush();
}

/* ── Compile-on-load for dynamic imports ─────────────────────────── */
/* When importlib.import_module(name) is called, try to find and compile
 * the .py source natively before falling back to CPython's import. */

void* fpy_jit_import(const char *module_name) {
    fpy_cpython_init();

    /* Try the JIT import path */
    PyObject *jit_module = PyImport_ImportModule("compiler.jit");
    if (!jit_module) {
        PyErr_Clear();
        /* JIT not available — fall through to CPython import */
        return fpy_cpython_import(module_name);
    }

    PyObject *import_func = PyObject_GetAttrString(jit_module, "jit_import");
    Py_DECREF(jit_module);
    if (!import_func) {
        PyErr_Clear();
        return fpy_cpython_import(module_name);
    }

    PyObject *py_name = PyUnicode_FromString(module_name);
    PyObject *result = PyObject_CallOneArg(import_func, py_name);
    Py_DECREF(py_name);
    Py_DECREF(import_func);

    if (!result) {
        PyErr_Clear();
        return fpy_cpython_import(module_name);
    }

    long long func_ptr = PyLong_AsLongLong(result);
    Py_DECREF(result);

    if (func_ptr == 0 || func_ptr == -1) {
        /* JIT compilation failed or module not found as .py
         * Fall back to CPython's standard import */
        PyErr_Clear();
        return fpy_cpython_import(module_name);
    }

    /* Module was compiled and executed natively. Still return the CPython
     * module object so downstream cpython_getattr calls work. */
    return fpy_cpython_import(module_name);
}

/* Execute Python source code in a temporary namespace, then extract
 * a named object (typically a function) and return it as a PyObject*.
 * Used for async def, generators needing send/close, etc. that must
 * run as real CPython functions.
 * Uses code cache for repeated exec of the same source. */
void* fpy_cpython_exec_get(const char *code_str, const char *name) {
    fpy_cpython_init();  /* lazy init */

    PyObject *globals = PyDict_New();
    /* builtins must be present for the exec'd code to access print, etc. */
    PyObject *builtins = PyImport_ImportModule("builtins");
    PyDict_SetItemString(globals, "__builtins__", builtins);
    Py_DECREF(builtins);

    /* Try cached compiled code first */
    PyObject *code = fpy_get_cached_code(code_str, 0);
    PyObject *result;
    if (code) {
        result = PyEval_EvalCode(code, globals, globals);
    } else {
        PyErr_Clear();
        result = PyRun_String(code_str, Py_file_input, globals, globals);
    }
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
 * from the caller's local variables. Returns the result as FpyValue.
 * Uses code cache for repeated eval of the same expression. */
void fpy_cpython_eval_locals(const char *expr, FpyDict *locals_dict,
                              int32_t *out_tag, int64_t *out_data) {
    fpy_cpython_init();

    PyObject *globals = PyDict_New();
    PyObject *builtins = PyImport_ImportModule("builtins");
    PyDict_SetItemString(globals, "__builtins__", builtins);
    Py_DECREF(builtins);

    PyObject *locals = locals_dict ? fpy_dict_to_pydict(locals_dict) : PyDict_New();

    /* Try cached compiled code */
    PyObject *code = fpy_get_cached_code(expr, 1);
    PyObject *result;
    if (code) {
        result = PyEval_EvalCode(code, globals, locals);
    } else {
        PyErr_Clear();
        result = PyRun_String(expr, Py_eval_input, globals, locals);
    }
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
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
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

/* ============================================================
 * Extended bridge: type(), iteration, arithmetic
 * ============================================================ */

/* type(pyobj) → returns the type name as a string (e.g., "int", "list") */
const char* fpy_cpython_typeof(void *obj) {
    if (!obj) return "NoneType";
    PyObject *type = PyObject_Type((PyObject*)obj);
    if (!type) return "unknown";
    PyObject *name = PyObject_GetAttrString(type, "__name__");
    Py_DECREF(type);
    if (!name) return "unknown";
    const char *s = PyUnicode_AsUTF8(name);
    /* Copy since the PyObject may be freed */
    const char *result = s ? fpy_strdup(s) : "unknown";
    Py_DECREF(name);
    return result;
}

/* type(pyobj) → returns "<class 'TypeName'>" format string */
const char* fpy_cpython_type_repr(void *obj) {
    const char *name = fpy_cpython_typeof(obj);
    size_t len = strlen(name);
    char *buf = (char*)malloc(len + 12); /* "<class ''>" + name + null */
    snprintf(buf, len + 12, "<class '%s'>", name);
    return buf;
}

/* iter(pyobj) → returns a PyObject* iterator */
void* fpy_cpython_iter(void *obj) {
    PyObject *iter = PyObject_GetIter((PyObject*)obj);
    if (!iter) { PyErr_Clear(); return NULL; }
    return (void*)iter;
}

/* next(iterator) → returns 1 if got value (stored in out_tag/out_data),
 *                   0 if StopIteration (iterator exhausted).
 * Does NOT print errors for StopIteration. */
int32_t fpy_cpython_iter_next(void *iter,
                               int32_t *out_tag, int64_t *out_data) {
    PyObject *item = PyIter_Next((PyObject*)iter);
    if (!item) {
        /* StopIteration or error */
        if (PyErr_Occurred()) PyErr_Clear();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return 0;  /* exhausted */
    }
    pyobject_to_fpy(item, out_tag, out_data);
    Py_DECREF(item);
    return 1;  /* got value */
}

/* iter_next that returns raw PyObject* without pyobject_to_fpy conversion.
 * Returns the PyObject* directly (caller owns the reference), or NULL if exhausted. */
void* fpy_cpython_iter_next_raw(void *iter) {
    PyObject *item = PyIter_Next((PyObject*)iter);
    if (!item) {
        if (PyErr_Occurred()) PyErr_Clear();
        return NULL;
    }
    return (void*)item;
}

/* Arithmetic on pyobj: call a binary operator via Python C API.
 * op: 0=add, 1=sub, 2=mul, 3=truediv, 4=floordiv, 5=mod, 6=pow
 * Returns result as FpyValue. */
void fpy_cpython_binop(void *left, int32_t right_tag, int64_t right_data,
                        int32_t op,
                        int32_t *out_tag, int64_t *out_data) {
    PyObject *r = fpy_to_pyobject(right_tag, right_data);
    PyObject *result = NULL;
    switch (op) {
        case 0: result = PyNumber_Add((PyObject*)left, r); break;
        case 1: result = PyNumber_Subtract((PyObject*)left, r); break;
        case 2: result = PyNumber_Multiply((PyObject*)left, r); break;
        case 3: result = PyNumber_TrueDivide((PyObject*)left, r); break;
        case 4: result = PyNumber_FloorDivide((PyObject*)left, r); break;
        case 5: result = PyNumber_Remainder((PyObject*)left, r); break;
        case 6: result = PyNumber_Power((PyObject*)left, r, Py_None); break;
        default: break;
    }
    Py_DECREF(r);
    if (!result) {
        PyErr_Print();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
    Py_DECREF(result);
}

/* Reverse arithmetic: native_value op pyobj.
 * Converts native to PyObject*, performs op, converts back. */
void fpy_cpython_rbinop(int32_t left_tag, int64_t left_data,
                         void *right, int32_t op,
                         int32_t *out_tag, int64_t *out_data) {
    PyObject *l = fpy_to_pyobject(left_tag, left_data);
    PyObject *result = NULL;
    switch (op) {
        case 0: result = PyNumber_Add(l, (PyObject*)right); break;
        case 1: result = PyNumber_Subtract(l, (PyObject*)right); break;
        case 2: result = PyNumber_Multiply(l, (PyObject*)right); break;
        case 3: result = PyNumber_TrueDivide(l, (PyObject*)right); break;
        case 4: result = PyNumber_FloorDivide(l, (PyObject*)right); break;
        case 5: result = PyNumber_Remainder(l, (PyObject*)right); break;
        case 6: result = PyNumber_Power(l, (PyObject*)right, Py_None); break;
        default: break;
    }
    Py_DECREF(l);
    if (!result) {
        PyErr_Print();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    /* For OBJ-tagged results, incref to keep alive (caller holds raw ptr) */
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
    Py_DECREF(result);
}

/* ── PyObject* refcount helpers for objects.c ─────────────────────
 * objects.c cannot include Python.h, so these wrappers let
 * fpy_rc_incref/decref handle OBJ-tagged PyObject* values safely
 * by delegating to Py_INCREF/Py_DECREF. */

void fpy_bridge_pyobj_incref(void *ptr) {
    if (ptr) Py_INCREF((PyObject*)ptr);
}

void fpy_bridge_pyobj_decref(void *ptr) {
    if (ptr) Py_DECREF((PyObject*)ptr);
}

/* Convert a CPython PyObject* to its str() representation.
 * Returns a newly allocated C string (caller must free). */
const char* fpy_bridge_pyobj_str(void *ptr) {
    if (!ptr) return fpy_strdup("None");
    PyObject *s = PyObject_Str((PyObject*)ptr);
    if (!s) {
        PyErr_Clear();
        return fpy_strdup("<object>");
    }
    const char *utf8 = PyUnicode_AsUTF8(s);
    const char *result = fpy_strdup(utf8 ? utf8 : "<object>");
    Py_DECREF(s);
    return result;
}

/* ── PyObject* comparison ─────────────────────────────────────────
 * Compare two PyObject* values using Python's rich comparison.
 * op: 0=Eq, 1=NotEq, 2=Lt, 3=LtE, 4=Gt, 5=GtE
 * Returns 1 for true, 0 for false. */
int32_t fpy_cpython_compare(void *left, void *right, int32_t op) {
    if (!left || !right) return (op == 0) ? (left == right) : (left != right);
    int py_op;
    switch (op) {
        case 0: py_op = Py_EQ; break;
        case 1: py_op = Py_NE; break;
        case 2: py_op = Py_LT; break;
        case 3: py_op = Py_LE; break;
        case 4: py_op = Py_GT; break;
        case 5: py_op = Py_GE; break;
        default: return 0;
    }
    PyObject *result = PyObject_RichCompare((PyObject*)left, (PyObject*)right, py_op);
    if (!result) {
        PyErr_Clear();
        return 0;
    }
    int truthy = PyObject_IsTrue(result);
    Py_DECREF(result);
    return truthy > 0 ? 1 : 0;
}

/* ── PyObject* sequence concatenation ─────────────────────────────
 * Concatenate two PyObject* values (bytes, etc.) using PySequence_Concat.
 * Returns result via tag+data output pointers. */
void fpy_cpython_concat(void *left, void *right,
                         int32_t *out_tag, int64_t *out_data) {
    if (!left || !right) {
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    PyObject *result = PySequence_Concat((PyObject*)left, (PyObject*)right);
    if (!result) {
        PyErr_Print();
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    pyobject_to_fpy(result, out_tag, out_data);
    if (*out_tag == FPY_TAG_OBJ) Py_INCREF(result);
    Py_DECREF(result);
}
