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
#include <stdio.h>
#include <string.h>

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
    PyObject *mod = PyImport_ImportModule(module_name);
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
        case FPY_TAG_NONE:
            Py_RETURN_NONE;
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
