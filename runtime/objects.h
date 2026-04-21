/*
 * fastpy runtime object system.
 *
 * Tagged value representation: every Python value is a FpyValue which
 * is a struct { tag, data }. The tag identifies the type, the data
 * holds the actual value (as a union).
 *
 * For LLVM codegen, FpyValue* is an opaque pointer. The compiler emits
 * calls to runtime functions that create, manipulate, and inspect values.
 */

#ifndef FASTPY_OBJECTS_H
#define FASTPY_OBJECTS_H

#include <stdint.h>
#include "threading.h"
#include "gc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Cross-platform strdup: MSVC uses _strdup, POSIX uses strdup */
#ifdef _MSC_VER
#define fpy_strdup _strdup
#else
#define fpy_strdup strdup
#endif

/* Type tags */
#define FPY_TAG_INT    0
#define FPY_TAG_FLOAT  1
#define FPY_TAG_STR    2
#define FPY_TAG_BOOL   3
#define FPY_TAG_NONE   4
#define FPY_TAG_LIST   5
#define FPY_TAG_OBJ    6
#define FPY_TAG_DICT   7
#define FPY_TAG_BYTES  8
#define FPY_TAG_SET    9
#define FPY_TAG_BIGINT 10
#define FPY_TAG_COMPLEX 11
#define FPY_TAG_DECIMAL 12

/* Complex number (heap-allocated pair of doubles) */
typedef struct {
    double real;
    double imag;
} FpyComplex;

FpyComplex* fpy_complex_new(double real, double imag);
FpyComplex* fpy_complex_add(FpyComplex *a, FpyComplex *b);
FpyComplex* fpy_complex_sub(FpyComplex *a, FpyComplex *b);
FpyComplex* fpy_complex_mul(FpyComplex *a, FpyComplex *b);
FpyComplex* fpy_complex_div(FpyComplex *a, FpyComplex *b);
FpyComplex* fpy_complex_neg(FpyComplex *a);
double fpy_complex_abs(FpyComplex *a);
void fpy_complex_print(FpyComplex *c);
char* fpy_complex_to_str(FpyComplex *c);

/* Decimal number (fixed-precision: 18 digits via int64 coefficient) */
typedef struct {
    int64_t coefficient;  /* significand (absolute value, up to 10^18) */
    int32_t exponent;     /* power of 10 (negative = fractional digits) */
    int8_t sign;          /* 1 = positive, -1 = negative, 0 = zero */
} FpyDecimal;

FpyDecimal* fpy_decimal_new(int64_t coeff, int32_t exp, int8_t sign);
FpyDecimal* fpy_decimal_from_str(const char *s);
FpyDecimal* fpy_decimal_from_int(int64_t val);
FpyDecimal* fpy_decimal_add(FpyDecimal *a, FpyDecimal *b);
FpyDecimal* fpy_decimal_sub(FpyDecimal *a, FpyDecimal *b);
FpyDecimal* fpy_decimal_mul(FpyDecimal *a, FpyDecimal *b);
FpyDecimal* fpy_decimal_div(FpyDecimal *a, FpyDecimal *b);
int fpy_decimal_compare(FpyDecimal *a, FpyDecimal *b);
char* fpy_decimal_to_str(FpyDecimal *d);
FpyDecimal* fpy_decimal_neg(FpyDecimal *a);
FpyDecimal* fpy_decimal_abs(FpyDecimal *a);

/* Forward declarations */
typedef struct FpyList FpyList;
typedef struct FpyObj FpyObj;

/* Tagged value */
typedef struct {
    int tag;
    union {
        int64_t i;
        double f;
        const char *s;
        int b;          /* 0 or 1 */
        FpyList *list;
        FpyObj *obj;
    } data;
} FpyValue;

/* --- Object system --- */

/* Method function pointer: takes (self, args...) as tagged values */
/* For simplicity, methods take self as FpyObj* and up to 4 i64 args */
typedef int64_t (*FpyMethodFunc)(FpyObj *self);
typedef int64_t (*FpyMethod1Func)(FpyObj *self, int64_t a);
typedef int64_t (*FpyMethod2Func)(FpyObj *self, int64_t a, int64_t b);
typedef int64_t (*FpyMethod3Func)(FpyObj *self, int64_t a, int64_t b, int64_t c);
typedef int64_t (*FpyMethod4Func)(FpyObj *self, int64_t a, int64_t b, int64_t c, int64_t d);

/* Method entry in a class */
typedef struct {
    const char *name;
    void *func;          /* cast to appropriate signature */
    int arg_count;       /* number of args (excluding self) */
    int returns_value;   /* 1 if returns a value, 0 if void */
} FpyMethodDef;

/* Class definition */
typedef struct {
    int class_id;
    const char *name;
    int parent_id;          /* -1 if no parent */
    FpyMethodDef *methods;
    int method_count;
    int slot_count;         /* number of pre-declared attribute slots */
    const char **slot_names; /* slot_names[i] = attribute name for slot i */
    void (*destructor)(FpyObj *obj); /* per-class destructor, NULL if none */
    void **vtable;                  /* vtable[i] = method func ptr, NULL-filled */
    int vtable_size;                /* number of vtable entries */
} FpyClassDef;

#define FPY_MAX_VTABLE 64  /* max methods per class hierarchy */

#define FPY_MAX_CLASSES 256

/* Dynamic-attribute side table, lazily allocated on first set_fv() that
 * misses the static slot path. Keeps FpyObj itself tiny (~24 bytes) so
 * the 99%-common slot-only case gets better cache behavior. */
typedef struct FpyObjAttrs {
    const char **names;      /* heap-allocated, length = capacity */
    FpyValue *values;        /* heap-allocated, length = capacity */
    int count;               /* number of entries in use */
    int capacity;            /* allocated slots in names/values */
} FpyObjAttrs;

/* Object instance.
 * Static attrs use `slots[]` (heap-allocated based on class slot_count) for
 * O(1) access. Dynamic attrs (from getattr/setattr or attrs the compiler
 * didn't pre-declare) fall back to the lazily-allocated `dynamic_attrs`
 * side table — NULL unless any dynamic attr has ever been written. */
/* ── Reference counting ──────────────────────────────────────────
 * Every heap-allocated object starts with a refcount field.
 * INT32_MAX = immortal (never freed: arena-allocated, constants).
 * Refcount is manipulated by fpy_incref/fpy_decref. When it hits
 * zero, the type-specific destructor frees the object. */
#define FPY_RC_IMMORTAL INT32_MAX

static inline void fpy_incref(int32_t *rc) {
    if (*rc != FPY_RC_IMMORTAL) (*rc)++;
}
static inline int fpy_decref(int32_t *rc) {
    if (*rc == FPY_RC_IMMORTAL) return 0;
    return (--(*rc) == 0);
}
/* Thread-safe variants — used in free-threaded mode. Defined in gc.c. */
void fpy_incref_atomic(int32_t *rc);
int fpy_decref_atomic(int32_t *rc);

#define FPY_OBJ_MAGIC 0x4F424A53  /* "OBJS" — distinguishes FpyObj from PyObject* */

struct FpyObj {
    int32_t refcount;                    /* reference count (first field for all GC'd objects) */
    FpyGCNode gc_node;                   /* cycle collector tracking */
    int magic;                           /* FPY_OBJ_MAGIC for native objects */
    int class_id;
    FpyValue *slots;                 /* size = class's slot_count, NULL if 0 */
    FpyObjAttrs *dynamic_attrs;      /* NULL unless used */
    fpy_mutex_t lock;                /* per-object lock (free-threaded mode) */
};

/* List: growable array of FpyValue. `is_tuple` distinguishes tuple-
   typed lists for display purposes (they print with parens). */
struct FpyList {
    int32_t refcount;
    FpyGCNode gc_node;                   /* cycle collector tracking */
    FpyValue *items;
    int64_t length;
    int64_t capacity;
    int is_tuple;
    fpy_mutex_t lock;                /* per-object lock (free-threaded mode) */
};

/* --- Refcounted strings ---
 * String constants (from .rodata) are NOT refcounted — they live
 * forever. Dynamically allocated strings (concat, format, slice, etc.)
 * are wrapped in FpyString with a magic number and refcount.
 * The FpyValue data pointer points to str->data (the chars), so
 * existing code sees a normal const char*. To check if a string is
 * owned, look for the magic 8 bytes before the char data. */
#define FPY_STR_MAGIC 0x53545243  /* "STRC" */

typedef struct {
    int32_t magic;      /* FPY_STR_MAGIC */
    int32_t refcount;
    char data[];        /* flexible array member — null-terminated UTF-8 */
} FpyString;

/* Allocate a refcounted string of `len` chars (+ null terminator). */
FpyString* fpy_str_alloc(int64_t len);
/* Get the FpyString header from a char* data pointer. Returns NULL if not owned. */
static inline FpyString* fpy_str_header(const char *s) {
    FpyString *h = (FpyString*)((char*)s - offsetof(FpyString, data));
    return (h->magic == FPY_STR_MAGIC) ? h : NULL;
}
static inline void fpy_str_incref(const char *s) {
    FpyString *h = fpy_str_header(s);
    if (h && h->refcount != FPY_RC_IMMORTAL) h->refcount++;
}
static inline int fpy_str_decref(const char *s) {
    FpyString *h = fpy_str_header(s);
    if (!h || h->refcount == FPY_RC_IMMORTAL) return 0;
    return (--h->refcount == 0);  /* returns 1 if should be freed */
}

/* --- Value constructors --- */

static inline FpyValue fpy_int(int64_t v) {
    FpyValue val; val.tag = FPY_TAG_INT; val.data.i = v; return val;
}
static inline FpyValue fpy_float(double v) {
    FpyValue val; val.tag = FPY_TAG_FLOAT; val.data.f = v; return val;
}
static inline FpyValue fpy_str(const char *v) {
    FpyValue val; val.tag = FPY_TAG_STR; val.data.s = v; return val;
}
static inline FpyValue fpy_bool(int v) {
    FpyValue val; val.tag = FPY_TAG_BOOL; val.data.b = v; return val;
}
static inline FpyValue fpy_none(void) {
    FpyValue val; val.tag = FPY_TAG_NONE; val.data.i = 0; return val;
}
static inline FpyValue fpy_list(FpyList *v) {
    FpyValue val; val.tag = FPY_TAG_LIST; val.data.list = v; return val;
}

/* --- List operations --- */

FpyList* fpy_list_new(int64_t capacity);
void fpy_list_append(FpyList *list, FpyValue value);
FpyValue fpy_list_get(FpyList *list, int64_t index);
void fpy_list_set(FpyList *list, int64_t index, FpyValue value);
int64_t fpy_list_len(FpyList *list);

/* --- Value operations --- */

/* Print a value with repr formatting (for list elements) */
void fpy_value_repr(FpyValue val, char *buf, int bufsize);

/* Print a value with str formatting (for print()) */
void fpy_value_print(FpyValue val);
void fpy_value_write(FpyValue val);  /* no newline */

/* Print a list in [a, b, c] format */
void fpy_list_print(FpyList *list);
void fpy_list_write(FpyList *list);  /* no newline */

/* --- Dict --- */

/* Open-addressing hash table with compact key/value storage.
 * `indices` is the hash table: maps hash slots to entry indices in
 * the compact keys/values arrays. -1 = empty, -2 = deleted.
 * Keys and values are stored in insertion order for O(n) iteration
 * and correct `dict.keys()` ordering. */
#define FPY_DICT_EMPTY   (-1)
#define FPY_DICT_DELETED (-2)

typedef struct {
    int32_t refcount;
    FpyGCNode gc_node;                   /* cycle collector tracking */
    int64_t *indices;      /* hash table → entry index (size = table_size) */
    FpyValue *keys;        /* compact entries: keys[0..length-1] */
    FpyValue *values;      /* compact entries: values[0..length-1] */
    int64_t length;        /* number of active entries */
    int64_t capacity;      /* allocated size of keys/values arrays */
    int64_t table_size;    /* size of indices array (power of 2) */
    fpy_mutex_t lock;      /* per-object lock (free-threaded mode) */
} FpyDict;

/* Variadic closure call: takes a list of args, unpacks and dispatches. */
int64_t fastpy_closure_call_list(void *closure, void *args_list);

#endif /* FASTPY_OBJECTS_H */
