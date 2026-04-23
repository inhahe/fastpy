/*
 * _fastints.c -- CPython C extension providing fixed-width integer types.
 *
 * Types: Int32, UInt32, Int64, UInt64
 *
 * All types store their value as int64_t internally. Arithmetic wraps to the
 * declared bit width after every operation, matching C semantics:
 *   - Signed types use two's complement wrapping.
 *   - Unsigned types mask to the bit width.
 *   - Division truncates toward zero (C-style, not Python-style).
 *   - Right shift is arithmetic for signed, logical for unsigned.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <structmember.h>
#include <stdint.h>
#include <inttypes.h>
#include <math.h>

/* ================================================================
 * Forward declarations -- we need all four type objects visible so
 * that binary ops can recognise any FixedInt peer.
 * ================================================================ */
static PyTypeObject Int32_Type;
static PyTypeObject UInt32_Type;
static PyTypeObject Int64_Type;
static PyTypeObject UInt64_Type;

/* ================================================================
 * Common struct -- every fixed-int object has the same layout.
 * ================================================================ */
typedef struct {
    PyObject_HEAD
    int64_t value;
} FixedIntObject;

/* ================================================================
 * Helper: check whether a PyObject* is one of our four types.
 * ================================================================ */
static inline int
is_fixedint(PyObject *obj)
{
    PyTypeObject *tp = Py_TYPE(obj);
    return (tp == &Int32_Type || tp == &UInt32_Type ||
            tp == &Int64_Type || tp == &UInt64_Type);
}

/* ================================================================
 * Helper: extract an int64_t from a Python int or FixedInt.
 * Returns 0 on success, -1 on failure (with exception set).
 * Sets *out to the extracted value.
 * Sets *handled to 0 if the type is unrecognized (caller should
 * return Py_NotImplemented), 1 if handled.
 * ================================================================ */
static int
extract_int64(PyObject *obj, int64_t *out, int *handled)
{
    *handled = 1;
    if (is_fixedint(obj)) {
        *out = ((FixedIntObject *)obj)->value;
        return 0;
    }
    if (PyLong_Check(obj)) {
        int overflow;
        long long v = PyLong_AsLongLongAndOverflow(obj, &overflow);
        if (overflow) {
            /* Value is outside long long range; still extract via
               Python's __int__ and mask later. */
            PyObject *as_long = PyNumber_Long(obj);
            if (!as_long) return -1;
            /* Use unsigned conversion to get bit pattern */
            unsigned long long uv = PyLong_AsUnsignedLongLongMask(as_long);
            Py_DECREF(as_long);
            *out = (int64_t)uv;
            return 0;
        }
        if (v == -1 && PyErr_Occurred()) return -1;
        *out = (int64_t)v;
        return 0;
    }
    if (PyFloat_Check(obj)) {
        double d = PyFloat_AsDouble(obj);
        if (d == -1.0 && PyErr_Occurred()) return -1;
        *out = (int64_t)d;
        return 0;
    }
    /* Unrecognized type */
    *handled = 0;
    return 0;
}

/* ================================================================
 * Wrapping helpers (used by the macros).
 * ================================================================ */
static inline int64_t
wrap_signed32(int64_t v)
{
    uint32_t masked = (uint32_t)(v & 0xFFFFFFFFULL);
    /* Sign extend from bit 31 */
    return (int64_t)(int32_t)masked;
}

static inline int64_t
wrap_unsigned32(int64_t v)
{
    return (int64_t)(uint32_t)(v & 0xFFFFFFFFULL);
}

static inline int64_t
wrap_signed64(int64_t v)
{
    /* Already in the int64_t range by virtue of being int64_t.
       But we need to handle the wrap from arbitrary-precision Python ints
       that were converted via unsigned mask. The bit pattern is already
       correct since int64_t is two's-complement. */
    return v;
}

static inline int64_t
wrap_unsigned64(int64_t v)
{
    /* Interpret the bit pattern as uint64_t, store back as int64_t.
       This preserves all 64 bits. For display, unsigned types will
       cast to uint64_t. */
    return v;
}

/* ================================================================
 * C-style truncation division (toward zero) and modulo.
 * ================================================================ */
static inline int64_t
trunc_div(int64_t a, int64_t b)
{
    /* C99 guarantees truncation toward zero for integer division. */
    return a / b;
}

static inline int64_t
trunc_mod(int64_t a, int64_t b)
{
    /* C99: a == (a/b)*b + a%b */
    return a % b;
}

/* ================================================================
 * Power: compute a**b with wrapping.
 * b must be >= 0.  For large b the result quickly wraps to 0.
 * ================================================================ */
static int64_t
int_pow(int64_t base, int64_t exp)
{
    int64_t result = 1;
    if (exp < 0) return 0;  /* caller should have raised ValueError */
    /* Use uint64_t for wrapping multiplication */
    uint64_t b = (uint64_t)base;
    uint64_t r = 1;
    uint64_t e = (uint64_t)exp;
    while (e > 0) {
        if (e & 1)
            r *= b;
        b *= b;
        e >>= 1;
    }
    result = (int64_t)r;
    return result;
}


/* ================================================================
 * MACRO: DEFINE_FIXEDINT_TYPE
 *
 * Generates all methods, number protocol, and type object for one
 * fixed-width integer type.
 *
 * Parameters:
 *   TypeName  -- C identifier prefix, e.g. Int32
 *   BITS      -- 32 or 64
 *   SIGNED    -- 1 for signed, 0 for unsigned
 *   wrap_fn   -- wrapping function: wrap_signed32, etc.
 *   TypeObj   -- the PyTypeObject variable, e.g. Int32_Type
 *   py_name   -- Python-visible name string, e.g. "Int32"
 * ================================================================ */

#define DEFINE_FIXEDINT_TYPE(TypeName, BITS, SIGNED, wrap_fn, TypeObj, py_name)  \
                                                                                \
/* ---- new / init ------------------------------------------------ */          \
static PyObject *                                                               \
TypeName##_new(PyTypeObject *type, PyObject *args, PyObject *kwds)              \
{                                                                               \
    FixedIntObject *self;                                                       \
    self = (FixedIntObject *)type->tp_alloc(type, 0);                           \
    if (self) self->value = 0;                                                  \
    return (PyObject *)self;                                                    \
}                                                                               \
                                                                                \
static int                                                                      \
TypeName##_init(FixedIntObject *self, PyObject *args, PyObject *kwds)           \
{                                                                               \
    static char *kwlist[] = {"value", NULL};                                    \
    PyObject *value_obj = NULL;                                                 \
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|O", kwlist, &value_obj))     \
        return -1;                                                              \
    if (value_obj) {                                                            \
        int64_t v;                                                              \
        int handled;                                                            \
        if (extract_int64(value_obj, &v, &handled) < 0) return -1;             \
        if (!handled) {                                                         \
            /* Try __int__ protocol */                                          \
            PyObject *as_int = PyNumber_Long(value_obj);                        \
            if (!as_int) return -1;                                             \
            if (extract_int64(as_int, &v, &handled) < 0) {                     \
                Py_DECREF(as_int);                                              \
                return -1;                                                      \
            }                                                                   \
            Py_DECREF(as_int);                                                  \
        }                                                                       \
        self->value = wrap_fn(v);                                               \
    }                                                                           \
    return 0;                                                                   \
}                                                                               \
                                                                                \
/* ---- Helper: create a new instance of this type from int64 ----- */          \
static PyObject *                                                               \
TypeName##_from_int64(int64_t v)                                                \
{                                                                               \
    FixedIntObject *obj = (FixedIntObject *)TypeObj.tp_alloc(&TypeObj, 0);      \
    if (!obj) return NULL;                                                      \
    obj->value = wrap_fn(v);                                                    \
    return (PyObject *)obj;                                                     \
}                                                                               \
                                                                                \
/* ---- repr / str ------------------------------------------------ */          \
static PyObject *                                                               \
TypeName##_repr(FixedIntObject *self)                                           \
{                                                                               \
    if (SIGNED) {                                                               \
        return PyUnicode_FromFormat(py_name "(%lld)",                            \
                                   (long long)self->value);                     \
    } else {                                                                    \
        return PyUnicode_FromFormat(py_name "(%llu)",                            \
                                   (unsigned long long)(uint64_t)self->value);  \
    }                                                                           \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_str(FixedIntObject *self)                                            \
{                                                                               \
    if (SIGNED) {                                                               \
        return PyUnicode_FromFormat("%lld", (long long)self->value);             \
    } else {                                                                    \
        return PyUnicode_FromFormat("%llu",                                      \
                                   (unsigned long long)(uint64_t)self->value);  \
    }                                                                           \
}                                                                               \
                                                                                \
/* ---- hash ------------------------------------------------------ */          \
static Py_hash_t                                                                \
TypeName##_hash(FixedIntObject *self)                                           \
{                                                                               \
    /* Hash the wrapped value; use Python's int hash for consistency. */         \
    PyObject *pyint;                                                            \
    if (SIGNED) {                                                               \
        pyint = PyLong_FromLongLong((long long)self->value);                    \
    } else {                                                                    \
        pyint = PyLong_FromUnsignedLongLong(                                    \
            (unsigned long long)(uint64_t)self->value);                         \
    }                                                                           \
    if (!pyint) return -1;                                                      \
    Py_hash_t h = PyObject_Hash(pyint);                                         \
    Py_DECREF(pyint);                                                           \
    return h;                                                                   \
}                                                                               \
                                                                                \
/* ---- richcompare ----------------------------------------------- */          \
static PyObject *                                                               \
TypeName##_richcompare(PyObject *self, PyObject *other, int op)                 \
{                                                                               \
    int64_t a = ((FixedIntObject *)self)->value;                                \
    int64_t b;                                                                  \
    int handled;                                                                \
    if (extract_int64(other, &b, &handled) < 0) return NULL;                    \
    if (!handled) Py_RETURN_NOTIMPLEMENTED;                                     \
    int cmp;                                                                    \
    if (SIGNED) {                                                               \
        switch (op) {                                                           \
            case Py_EQ: cmp = (a == b); break;                                  \
            case Py_NE: cmp = (a != b); break;                                  \
            case Py_LT: cmp = (a < b);  break;                                  \
            case Py_LE: cmp = (a <= b); break;                                  \
            case Py_GT: cmp = (a > b);  break;                                  \
            case Py_GE: cmp = (a >= b); break;                                  \
            default: Py_RETURN_NOTIMPLEMENTED;                                  \
        }                                                                       \
    } else {                                                                    \
        uint64_t ua = (uint64_t)a, ub = (uint64_t)b;                           \
        switch (op) {                                                           \
            case Py_EQ: cmp = (ua == ub); break;                                \
            case Py_NE: cmp = (ua != ub); break;                                \
            case Py_LT: cmp = (ua < ub);  break;                                \
            case Py_LE: cmp = (ua <= ub); break;                                \
            case Py_GT: cmp = (ua > ub);  break;                                \
            case Py_GE: cmp = (ua >= ub); break;                                \
            default: Py_RETURN_NOTIMPLEMENTED;                                  \
        }                                                                       \
    }                                                                           \
    if (cmp) Py_RETURN_TRUE;                                                    \
    Py_RETURN_FALSE;                                                            \
}                                                                               \
                                                                                \
/* ---- conversions: __int__, __float__, __bool__, __index__ ------ */          \
static PyObject *                                                               \
TypeName##_int(FixedIntObject *self)                                            \
{                                                                               \
    if (SIGNED)                                                                 \
        return PyLong_FromLongLong((long long)self->value);                     \
    else                                                                        \
        return PyLong_FromUnsignedLongLong(                                     \
            (unsigned long long)(uint64_t)self->value);                         \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_float(FixedIntObject *self)                                          \
{                                                                               \
    if (SIGNED)                                                                 \
        return PyFloat_FromDouble((double)self->value);                         \
    else                                                                        \
        return PyFloat_FromDouble((double)(uint64_t)self->value);               \
}                                                                               \
                                                                                \
static int                                                                      \
TypeName##_bool(FixedIntObject *self)                                           \
{                                                                               \
    return self->value != 0;                                                    \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_index(FixedIntObject *self)                                          \
{                                                                               \
    return TypeName##_int(self);                                                \
}                                                                               \
                                                                                \
/* ---- Binary arithmetic ops ------------------------------------- */          \
/* Helper macro for a single binary op */                                       \
                                                                                \
static PyObject *                                                               \
TypeName##_add(PyObject *left, PyObject *right)                                 \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    return TypeName##_from_int64(a + b);                                        \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_sub(PyObject *left, PyObject *right)                                 \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    return TypeName##_from_int64(a - b);                                        \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_mul(PyObject *left, PyObject *right)                                 \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    return TypeName##_from_int64(a * b);                                        \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_floordiv(PyObject *left, PyObject *right)                            \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    if (b == 0) {                                                               \
        PyErr_SetString(PyExc_ZeroDivisionError,                                \
                        py_name " division by zero");                           \
        return NULL;                                                            \
    }                                                                           \
    /* Handle INT64_MIN / -1 for signed types to avoid UB */                    \
    if (SIGNED && a == INT64_MIN && b == -1)                                    \
        return TypeName##_from_int64(INT64_MIN);                                \
    return TypeName##_from_int64(trunc_div(a, b));                              \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_mod(PyObject *left, PyObject *right)                                 \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    if (b == 0) {                                                               \
        PyErr_SetString(PyExc_ZeroDivisionError,                                \
                        py_name " modulo by zero");                             \
        return NULL;                                                            \
    }                                                                           \
    if (SIGNED && a == INT64_MIN && b == -1)                                    \
        return TypeName##_from_int64(0);                                        \
    return TypeName##_from_int64(trunc_mod(a, b));                              \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_pow_impl(PyObject *left, PyObject *right,                            \
                    PyObject *mod_unused)                                        \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    if (b < 0) {                                                                \
        PyErr_SetString(PyExc_ValueError,                                       \
                        py_name " negative exponent not supported");            \
        return NULL;                                                            \
    }                                                                           \
    return TypeName##_from_int64(int_pow(a, b));                                \
}                                                                               \
                                                                                \
/* ---- Unary ops ------------------------------------------------- */          \
static PyObject *                                                               \
TypeName##_neg(FixedIntObject *self)                                            \
{                                                                               \
    return TypeName##_from_int64(-self->value);                                 \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_pos(FixedIntObject *self)                                            \
{                                                                               \
    Py_INCREF(self);                                                            \
    return (PyObject *)self;                                                    \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_abs(FixedIntObject *self)                                            \
{                                                                               \
    int64_t v = self->value;                                                    \
    if (SIGNED && v < 0) v = -v;                                                \
    return TypeName##_from_int64(v);                                            \
}                                                                               \
                                                                                \
/* ---- Bitwise ops ----------------------------------------------- */          \
static PyObject *                                                               \
TypeName##_and(PyObject *left, PyObject *right)                                 \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    return TypeName##_from_int64(a & b);                                        \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_or(PyObject *left, PyObject *right)                                  \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    return TypeName##_from_int64(a | b);                                        \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_xor(PyObject *left, PyObject *right)                                 \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    return TypeName##_from_int64(a ^ b);                                        \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_invert(FixedIntObject *self)                                         \
{                                                                               \
    return TypeName##_from_int64(~self->value);                                 \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_lshift(PyObject *left, PyObject *right)                              \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    if (b < 0) {                                                                \
        PyErr_SetString(PyExc_ValueError, "negative shift count");              \
        return NULL;                                                            \
    }                                                                           \
    if (b >= BITS) return TypeName##_from_int64(0);                             \
    return TypeName##_from_int64((int64_t)((uint64_t)a << b));                  \
}                                                                               \
                                                                                \
static PyObject *                                                               \
TypeName##_rshift(PyObject *left, PyObject *right)                              \
{                                                                               \
    int64_t a, b; int ha, hb;                                                   \
    if (extract_int64(left, &a, &ha) < 0) return NULL;                          \
    if (extract_int64(right, &b, &hb) < 0) return NULL;                         \
    if (!ha || !hb) Py_RETURN_NOTIMPLEMENTED;                                   \
    if (b < 0) {                                                                \
        PyErr_SetString(PyExc_ValueError, "negative shift count");              \
        return NULL;                                                            \
    }                                                                           \
    if (SIGNED) {                                                               \
        /* Arithmetic right shift -- C standard guarantees this for             \
           non-negative values, and most compilers do arithmetic shift          \
           for signed too.  We do it explicitly for portability. */             \
        if (b >= BITS)                                                          \
            return TypeName##_from_int64(a < 0 ? -1 : 0);                      \
        return TypeName##_from_int64(a >> b);                                   \
    } else {                                                                    \
        /* Logical right shift */                                               \
        if (b >= BITS)                                                          \
            return TypeName##_from_int64(0);                                    \
        return TypeName##_from_int64((int64_t)((uint64_t)a >> b));              \
    }                                                                           \
}                                                                               \
                                                                                \
/* ---- Number protocol struct ------------------------------------ */          \
static PyNumberMethods TypeName##_as_number = {                                 \
    .nb_add             = (binaryfunc)TypeName##_add,                           \
    .nb_subtract        = (binaryfunc)TypeName##_sub,                           \
    .nb_multiply        = (binaryfunc)TypeName##_mul,                           \
    .nb_remainder       = (binaryfunc)TypeName##_mod,                           \
    .nb_power           = (ternaryfunc)TypeName##_pow_impl,                     \
    .nb_negative        = (unaryfunc)TypeName##_neg,                            \
    .nb_positive        = (unaryfunc)TypeName##_pos,                            \
    .nb_absolute        = (unaryfunc)TypeName##_abs,                            \
    .nb_bool            = (inquiry)TypeName##_bool,                             \
    .nb_invert          = (unaryfunc)TypeName##_invert,                         \
    .nb_lshift          = (binaryfunc)TypeName##_lshift,                        \
    .nb_rshift          = (binaryfunc)TypeName##_rshift,                        \
    .nb_and             = (binaryfunc)TypeName##_and,                           \
    .nb_xor             = (binaryfunc)TypeName##_xor,                           \
    .nb_or              = (binaryfunc)TypeName##_or,                            \
    .nb_int             = (unaryfunc)TypeName##_int,                            \
    .nb_float           = (unaryfunc)TypeName##_float,                          \
    .nb_floor_divide    = (binaryfunc)TypeName##_floordiv,                      \
    .nb_index           = (unaryfunc)TypeName##_index,                          \
    /* in-place ops return new objects (immutable), but we register them         \
       so that +=, -=, *= dispatch to our type instead of falling back          \
       to the generic binary op path with a plain int result. */                \
    .nb_inplace_add      = (binaryfunc)TypeName##_add,                          \
    .nb_inplace_subtract = (binaryfunc)TypeName##_sub,                          \
    .nb_inplace_multiply = (binaryfunc)TypeName##_mul,                          \
};                                                                              \
                                                                                \
/* ---- Type object ----------------------------------------------- */          \
static PyTypeObject TypeObj = {                                                 \
    PyVarObject_HEAD_INIT(NULL, 0)                                              \
    .tp_name        = "fastpy._fastints." py_name,                              \
    .tp_basicsize   = sizeof(FixedIntObject),                                   \
    .tp_itemsize    = 0,                                                        \
    .tp_flags       = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,                \
    .tp_doc         = py_name " fixed-width integer type.",                     \
    .tp_repr        = (reprfunc)TypeName##_repr,                                \
    .tp_str         = (reprfunc)TypeName##_str,                                 \
    .tp_hash        = (hashfunc)TypeName##_hash,                                \
    .tp_richcompare = (richcmpfunc)TypeName##_richcompare,                      \
    .tp_as_number   = &TypeName##_as_number,                                    \
    .tp_new         = TypeName##_new,                                           \
    .tp_init        = (initproc)TypeName##_init,                                \
};                                                                              \
/* end of DEFINE_FIXEDINT_TYPE */


/* ================================================================
 * Instantiate the four types.
 * ================================================================ */
DEFINE_FIXEDINT_TYPE(Int32,   32, 1, wrap_signed32,   Int32_Type,   "Int32")
DEFINE_FIXEDINT_TYPE(UInt32,  32, 0, wrap_unsigned32,  UInt32_Type,  "UInt32")
DEFINE_FIXEDINT_TYPE(Int64,   64, 1, wrap_signed64,   Int64_Type,   "Int64")
DEFINE_FIXEDINT_TYPE(UInt64,  64, 0, wrap_unsigned64,  UInt64_Type,  "UInt64")


/* ================================================================
 * Module definition.
 * ================================================================ */
static PyModuleDef fastints_module = {
    PyModuleDef_HEAD_INIT,
    .m_name    = "_fastints",
    .m_doc     = "Fixed-width integer types: Int32, UInt32, Int64, UInt64.",
    .m_size    = -1,
};

PyMODINIT_FUNC
PyInit__fastints(void)
{
    PyObject *m;

    if (PyType_Ready(&Int32_Type) < 0)  return NULL;
    if (PyType_Ready(&UInt32_Type) < 0) return NULL;
    if (PyType_Ready(&Int64_Type) < 0)  return NULL;
    if (PyType_Ready(&UInt64_Type) < 0) return NULL;

    m = PyModule_Create(&fastints_module);
    if (!m) return NULL;

    Py_INCREF(&Int32_Type);
    if (PyModule_AddObject(m, "Int32", (PyObject *)&Int32_Type) < 0) {
        Py_DECREF(&Int32_Type);
        Py_DECREF(m);
        return NULL;
    }

    Py_INCREF(&UInt32_Type);
    if (PyModule_AddObject(m, "UInt32", (PyObject *)&UInt32_Type) < 0) {
        Py_DECREF(&UInt32_Type);
        Py_DECREF(m);
        return NULL;
    }

    Py_INCREF(&Int64_Type);
    if (PyModule_AddObject(m, "Int64", (PyObject *)&Int64_Type) < 0) {
        Py_DECREF(&Int64_Type);
        Py_DECREF(m);
        return NULL;
    }

    Py_INCREF(&UInt64_Type);
    if (PyModule_AddObject(m, "UInt64", (PyObject *)&UInt64_Type) < 0) {
        Py_DECREF(&UInt64_Type);
        Py_DECREF(m);
        return NULL;
    }

    /* Add MIN/MAX class attributes to each type's __dict__. */
    {
        PyObject *v, *d;

        /* Int32: [-2^31, 2^31-1] */
        d = Int32_Type.tp_dict;
        v = PyLong_FromLongLong(-2147483648LL);
        if (v) { PyDict_SetItemString(d, "MIN", v); Py_DECREF(v); }
        v = PyLong_FromLongLong(2147483647LL);
        if (v) { PyDict_SetItemString(d, "MAX", v); Py_DECREF(v); }

        /* UInt32: [0, 2^32-1] */
        d = UInt32_Type.tp_dict;
        v = PyLong_FromLongLong(0);
        if (v) { PyDict_SetItemString(d, "MIN", v); Py_DECREF(v); }
        v = PyLong_FromUnsignedLongLong(4294967295ULL);
        if (v) { PyDict_SetItemString(d, "MAX", v); Py_DECREF(v); }

        /* Int64: [-2^63, 2^63-1] */
        d = Int64_Type.tp_dict;
        v = PyLong_FromLongLong(-9223372036854775807LL - 1LL);
        if (v) { PyDict_SetItemString(d, "MIN", v); Py_DECREF(v); }
        v = PyLong_FromLongLong(9223372036854775807LL);
        if (v) { PyDict_SetItemString(d, "MAX", v); Py_DECREF(v); }

        /* UInt64: [0, 2^64-1] */
        d = UInt64_Type.tp_dict;
        v = PyLong_FromLongLong(0);
        if (v) { PyDict_SetItemString(d, "MIN", v); Py_DECREF(v); }
        v = PyLong_FromUnsignedLongLong(18446744073709551615ULL);
        if (v) { PyDict_SetItemString(d, "MAX", v); Py_DECREF(v); }
    }

    return m;
}
