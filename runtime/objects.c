/*
 * fastpy runtime object system implementation.
 */

#include "objects.h"
#include "threading.h"
#include "gc.h"
#include "bigint.h"
#include <math.h>

/* Forward declarations */
void fastpy_tuple_write(FpyList *tuple);
void fastpy_dict_write(FpyDict *dict);
void fastpy_obj_write(FpyObj *obj);

/* External exception-raising API (defined in runtime.c) */
extern void fastpy_raise(int exc_type, const char *msg);
extern int fastpy_exc_pending(void);

/* Exception type constants (mirror runtime.c) */
#define FPY_EXC_ZERODIVISION   1
#define FPY_EXC_VALUEERROR     2
#define FPY_EXC_TYPEERROR      3
#define FPY_EXC_INDEXERROR     4
#define FPY_EXC_KEYERROR       5
#define FPY_EXC_ATTRIBUTEERROR 11

/* Thread-local buffer for formatted error messages. Only one exception
 * can be pending per thread, so a single buffer is safe. */
static FPY_THREAD_LOCAL char _err_buf[256];

/* --- List operations --- */

/* --- Refcounted string allocation --- */

FpyString* fpy_str_alloc(int64_t len) {
    FpyString *s = (FpyString*)malloc(sizeof(FpyString) + len + 1);
    s->magic = FPY_STR_MAGIC;
    s->refcount = 1;
    s->data[len] = '\0';
    return s;
}

/* Incref/decref an FpyValue (convenience for container mutations) */
#define FPY_VAL_INCREF(v) fpy_rc_incref((v).tag, (v).data.i)
#define FPY_VAL_DECREF(v) fpy_rc_decref((v).tag, (v).data.i)

/* Forward declarations */
#define FPY_CLOSURE_MAGIC 0x434C4F53  /* "CLOS" — also defined below */
typedef struct {
    int32_t magic;
    int32_t refcount;
    int n_captures;
    int n_params;
    void *func;
    uint8_t capture_is_cell;  /* bitmask: bit i set = captures[i] is a cell pointer */
    int64_t captures[8];
} FpyClosure;

typedef struct {
    int32_t refcount;
    int64_t value;
} FpyCell;

/* Forward declarations for recursive destroy and class registry */
static void fpy_list_destroy(FpyList *list);
static void fpy_dict_destroy(FpyDict *dict);
static int fpy_list_all_scalar(FpyList *list);
void fpy_rc_decref(int32_t tag, int64_t data);
extern FpyClassDef fpy_classes[];  /* defined later in this file */

/* Bridge helpers for PyObject* refcounting (defined in cpython_bridge.c).
 * objects.c cannot include Python.h, so it delegates to these wrappers. */
extern void fpy_bridge_pyobj_incref(void *ptr);
extern void fpy_bridge_pyobj_decref(void *ptr);

/* --- Destructors for refcounted objects --- */

static void fpy_list_destroy(FpyList *list) {
    fpy_gc_untrack(&list->gc_node);
    if (!fpy_list_all_scalar(list)) {
        for (int64_t i = 0; i < list->length; i++) {
            fpy_rc_decref(list->items[i].tag, list->items[i].data.i);
        }
    }
    free(list->items);
    free(list);
}

static void fpy_dict_destroy(FpyDict *dict) {
    fpy_gc_untrack(&dict->gc_node);
    for (int64_t i = 0; i < dict->length; i++) {
        fpy_rc_decref(dict->keys[i].tag, dict->keys[i].data.i);
        fpy_rc_decref(dict->values[i].tag, dict->values[i].data.i);
    }
    free(dict->indices);
    free(dict->keys);
    free(dict->values);
    free(dict);
}

/* Tag-dispatching incref/decref for FpyValue. Checks the tag to
 * determine the object type, then increfs/decrefs accordingly.
 * No-op for scalars (INT, FLOAT, BOOL, NONE). */
void fpy_rc_incref(int32_t tag, int64_t data) {
    if (data == 0) return;  /* NULL pointer guard */
    switch (tag) {
        case FPY_TAG_LIST: case FPY_TAG_SET:
            fpy_incref(&((FpyList*)(intptr_t)data)->refcount); break;
        case FPY_TAG_DICT:
            fpy_incref(&((FpyDict*)(intptr_t)data)->refcount); break;
        case FPY_TAG_OBJ: {
            /* Could be FpyObj, FpyClosure, or CPython PyObject*.
             * FpyClosure starts with magic 0x434C4F53 at offset 0.
             * FpyObj has refcount at offset 0 (small positive int) and
             * magic 0x4F424A53 at offset 32.
             * CPython PyObject* has ob_refcnt at offset 0.
             *
             * Strategy: check closure magic at offset 0 (safe — always
             * readable for any valid heap pointer). Then check FpyObj by
             * reading the refcount first (offset 0) — if it's a sane
             * value (1..10000), it's likely an FpyObj or FpyClosure;
             * read magic at offset 32 to confirm. Otherwise delegate to
             * Py_INCREF via the bridge helper. */
            void *ptr = (void*)(intptr_t)data;
            int32_t first_word = *(int32_t*)ptr;
            if (first_word == FPY_CLOSURE_MAGIC) {
                fpy_incref(&((FpyClosure*)ptr)->refcount);
            } else if (first_word > 0 && first_word < 100000) {
                /* Plausible refcount — check FpyObj magic at offset 32 */
                FpyObj *obj = (FpyObj*)ptr;
                if (obj->magic == FPY_OBJ_MAGIC)
                    fpy_incref(&obj->refcount);
                else
                    fpy_bridge_pyobj_incref(ptr);
            } else {
                /* Not a closure, not a plausible FpyObj refcount —
                 * treat as CPython PyObject* */
                fpy_bridge_pyobj_incref(ptr);
            }
            break;
        }
        case FPY_TAG_STR:
            fpy_str_incref((const char*)(intptr_t)data); break;
        default: break;  /* INT, FLOAT, BOOL, NONE — not heap-allocated */
    }
}

void fpy_rc_decref(int32_t tag, int64_t data) {
    if (data == 0) return;  /* NULL pointer guard */
    switch (tag) {
        case FPY_TAG_STR:
            if (fpy_str_decref((const char*)(intptr_t)data)) {
                FpyString *h = fpy_str_header((const char*)(intptr_t)data);
                if (h) free(h);
            }
            break;
        case FPY_TAG_LIST: case FPY_TAG_SET:
            if (fpy_decref(&((FpyList*)(intptr_t)data)->refcount))
                fpy_list_destroy((FpyList*)(intptr_t)data);
            break;
        case FPY_TAG_DICT:
            if (fpy_decref(&((FpyDict*)(intptr_t)data)->refcount))
                fpy_dict_destroy((FpyDict*)(intptr_t)data);
            break;
        case FPY_TAG_OBJ: {
            void *ptr = (void*)(intptr_t)data;
            int32_t first_word = *(int32_t*)ptr;
            /* Check if this is a closure (not an FpyObj) */
            if (first_word == FPY_CLOSURE_MAGIC) {
                FpyClosure *c = (FpyClosure*)ptr;
                if (fpy_decref(&c->refcount)) {
                    /* Free captured values: cells get freed, others decrefd */
                    for (int i = 0; i < c->n_captures; i++) {
                        if (c->capture_is_cell & (1 << i)) {
                            /* Cell pointer — free the cell */
                            FpyCell *cell = (FpyCell*)(intptr_t)c->captures[i];
                            if (cell) free(cell);
                        }
                        /* Regular captures: the value was borrowed from the
                         * outer scope; don't decref (the scope owns it) */
                    }
                    free(c);
                }
                break;
            }
            /* Check if plausible FpyObj (first word is refcount, small positive) */
            if (first_word > 0 && first_word < 100000) {
                FpyObj *obj = (FpyObj*)ptr;
                if (obj->magic == FPY_OBJ_MAGIC) {
                    if (fpy_decref(&obj->refcount)) {
                        /* Untrack from GC before freeing — the gc_node would
                         * otherwise dangle in the tracked list, causing a
                         * segfault on the next GC traversal. */
                        fpy_gc_untrack(&obj->gc_node);
                        /* Call per-class destructor if set (e.g., generator cleanup).
                         * Runs before slots are freed so the destructor can access attrs. */
                        void (*dtor)(FpyObj*) = fpy_classes[obj->class_id].destructor;
                        if (dtor) dtor(obj);
                        /* Invalidate all weak references to this object.
                         * Walk the singly-linked list and null out target pointers
                         * so deref returns None instead of a dangling pointer. */
                        FpyWeakRef *wr = obj->weakref_list;
                        while (wr) {
                            FpyWeakRef *next = wr->next;
                            wr->target = NULL;
                            /* TODO: invoke callbacks if set */
                            wr = next;
                        }
                        /* Free slots (decref each), dynamic_attrs, and the obj */
                        if (obj->slots) {
                            int sc = fpy_classes[obj->class_id].slot_count;
                            for (int i = 0; i < sc; i++)
                                FPY_VAL_DECREF(obj->slots[i]);
                            /* slots are contiguous with obj (malloc'd together), don't free separately */
                        }
                        if (obj->dynamic_attrs) {
                            for (int i = 0; i < obj->dynamic_attrs->count; i++)
                                FPY_VAL_DECREF(obj->dynamic_attrs->values[i]);
                            free(obj->dynamic_attrs->names);
                            free(obj->dynamic_attrs->values);
                            free(obj->dynamic_attrs);
                        }
                        free(obj);
                    }
                    break;
                }
            }
            /* Not a closure, not an FpyObj — treat as CPython PyObject* */
            fpy_bridge_pyobj_decref(ptr);
            break;
        }
        case FPY_TAG_BIGINT: {
            FpyBigInt *bi = (FpyBigInt*)(intptr_t)data;
            if (bi && fpy_decref(&bi->refcount))
                fpy_bigint_free(bi);
            break;
        }
        default: break;
    }
}

/* --- List operations --- */

FpyList* fpy_list_new(int64_t capacity) {
    if (capacity < 4) capacity = 4;
    FpyList *list = (FpyList*)malloc(sizeof(FpyList));
    list->refcount = 1;
    memset(&list->gc_node, 0, sizeof(FpyGCNode));
    list->items = (FpyValue*)malloc(sizeof(FpyValue) * capacity);
    list->length = 0;
    list->capacity = capacity;
    list->is_tuple = 0;
    if (fpy_threading_mode == FPY_THREADING_FREE) fpy_mutex_init(&list->lock);
    list->gc_node.gc_type = FPY_GC_TYPE_LIST;
    fpy_gc_track(&list->gc_node);
    fpy_gc_maybe_collect();
    return list;
}

/* Create a tuple-typed list (prints with parens, is_tuple=1) */
FpyList* fastpy_tuple_new(void) {
    FpyList *t = fpy_list_new(4);
    t->is_tuple = 1;
    return t;
}

/* Mark an existing FpyList as a tuple (used by tuple() constructor) */
void fastpy_list_mark_tuple(FpyList *list) {
    if (list) list->is_tuple = 1;
}

/* Unlocked append — caller must hold list->lock if needed */
static void fpy_list_append_unlocked(FpyList *list, FpyValue value) {
    if (list->length >= list->capacity) {
        list->capacity *= 2;
        list->items = (FpyValue*)realloc(list->items, sizeof(FpyValue) * list->capacity);
    }
    FPY_VAL_INCREF(value);
    list->items[list->length++] = value;
}

void fpy_list_append(FpyList *list, FpyValue value) {
    FPY_LOCK(list);
    fpy_list_append_unlocked(list, value);
    FPY_UNLOCK(list);
}

FpyValue fpy_list_get(FpyList *list, int64_t index) {
    if (index < 0) index += list->length;
    if (index < 0 || index >= list->length) {
        fastpy_raise(FPY_EXC_INDEXERROR, "list index out of range");
        FpyValue _err = {0}; return _err;
    }
    return list->items[index];
}

void fpy_list_set(FpyList *list, int64_t index, FpyValue value) {
    FPY_LOCK(list);
    if (index < 0) index += list->length;
    if (index < 0 || index >= list->length) {
        FPY_UNLOCK(list);
        fastpy_raise(FPY_EXC_INDEXERROR, "list assignment index out of range");
        return;
    }
    FPY_VAL_DECREF(list->items[index]);
    FPY_VAL_INCREF(value);
    list->items[index] = value;
    FPY_UNLOCK(list);
}

int64_t fpy_list_len(FpyList *list) {
    return list->length;
}

/* Float formatting — implemented in runtime.c */
extern void fastpy_format_float(double value, char *buf, int bufsize);
#define format_float fastpy_format_float

/* Forward declarations for set print (used by fpy_value_write) */
void fastpy_set_print(FpyDict *set);
void fastpy_set_write(FpyDict *set);

/* --- Value repr (for list elements: strings get quotes) --- */

void fpy_value_repr(FpyValue val, char *buf, int bufsize) {
    switch (val.tag) {
        case FPY_TAG_INT:
            snprintf(buf, bufsize, "%lld", (long long)val.data.i);
            break;
        case FPY_TAG_FLOAT:
            format_float(val.data.f, buf, bufsize);
            break;
        case FPY_TAG_STR: {
            /* Escape special characters like CPython's repr() */
            int pos = 0;
            const char *s = val.data.s;
            buf[pos++] = '\'';
            if (s) {
                for (; *s && pos < bufsize - 6; s++) {
                    unsigned char c = (unsigned char)*s;
                    if (c == '\\')      { buf[pos++] = '\\'; buf[pos++] = '\\'; }
                    else if (c == '\'') { buf[pos++] = '\\'; buf[pos++] = '\''; }
                    else if (c == '\n') { buf[pos++] = '\\'; buf[pos++] = 'n'; }
                    else if (c == '\r') { buf[pos++] = '\\'; buf[pos++] = 'r'; }
                    else if (c == '\t') { buf[pos++] = '\\'; buf[pos++] = 't'; }
                    else if (c < 32 || c == 127)
                        pos += snprintf(buf + pos, bufsize - pos, "\\x%02x", c);
                    else buf[pos++] = c;
                }
            }
            if (pos < bufsize - 1) buf[pos++] = '\'';
            buf[pos] = '\0';
            break;
        }
        case FPY_TAG_BOOL:
            snprintf(buf, bufsize, "%s", val.data.b ? "True" : "False");
            break;
        case FPY_TAG_NONE:
            snprintf(buf, bufsize, "None");
            break;
        case FPY_TAG_LIST: {
            /* Recursive list/tuple repr */
            int pos = 0;
            FpyList *lst = val.data.list;
            const char *open = lst->is_tuple ? "(" : "[";
            const char *close = lst->is_tuple ? ")" : "]";
            pos += snprintf(buf + pos, bufsize - pos, "%s", open);
            for (int64_t i = 0; i < lst->length; i++) {
                if (i > 0) pos += snprintf(buf + pos, bufsize - pos, ", ");
                char elem[256];
                fpy_value_repr(lst->items[i], elem, sizeof(elem));
                pos += snprintf(buf + pos, bufsize - pos, "%s", elem);
                if (pos >= bufsize - 1) break;
            }
            if (lst->is_tuple && lst->length == 1) {
                pos += snprintf(buf + pos, bufsize - pos, ",");
            }
            snprintf(buf + pos, bufsize - pos, "%s", close);
            break;
        }
        case FPY_TAG_DICT: {
            /* Dict repr via fastpy_dict_to_str */
            extern const char* fastpy_dict_to_str(FpyDict*);
            const char *s = fastpy_dict_to_str((FpyDict*)val.data.list);
            snprintf(buf, bufsize, "%s", s);
            break;
        }
        case FPY_TAG_OBJ: {
            /* Could be FpyObj or CPython PyObject* — detect via magic */
            void *ptr = val.data.obj;
            int32_t first_word = *(int32_t*)ptr;
            if (first_word == FPY_CLOSURE_MAGIC) {
                snprintf(buf, bufsize, "<closure>");
            } else if (first_word > 0 && first_word < 100000) {
                FpyObj *obj = (FpyObj*)ptr;
                if (obj->magic == FPY_OBJ_MAGIC) {
                    extern const char* fastpy_obj_to_repr(FpyObj*);
                    const char *s = fastpy_obj_to_repr(obj);
                    snprintf(buf, bufsize, "%s", s);
                } else {
                    /* CPython PyObject* — use PyObject_Repr */
                    extern const char* fpy_bridge_pyobj_repr(void*);
                    const char *s = fpy_bridge_pyobj_repr(ptr);
                    if (s) snprintf(buf, bufsize, "%s", s);
                    else snprintf(buf, bufsize, "<PyObject>");
                }
            } else {
                extern const char* fpy_bridge_pyobj_repr(void*);
                const char *s = fpy_bridge_pyobj_repr(ptr);
                if (s) snprintf(buf, bufsize, "%s", s);
                else snprintf(buf, bufsize, "<PyObject>");
            }
            break;
        }
        case FPY_TAG_BIGINT: {
            const char *s = fpy_bigint_to_str((FpyBigInt*)(intptr_t)val.data.i);
            snprintf(buf, bufsize, "%s", s);
            free((void*)s);
            break;
        }
        case FPY_TAG_COMPLEX: {
            char *s = fpy_complex_to_str((FpyComplex*)(intptr_t)val.data.i);
            snprintf(buf, bufsize, "%s", s);
            free(s);
            break;
        }
        case FPY_TAG_DECIMAL: {
            char *s = fpy_decimal_to_str((FpyDecimal*)(intptr_t)val.data.i);
            snprintf(buf, bufsize, "Decimal('%s')", s);
            free(s);
            break;
        }
        case FPY_TAG_SET: {
            FpyDict *set = (FpyDict*)val.data.list;
            int pos = 0;
            pos += snprintf(buf + pos, bufsize - pos, "{");
            for (int64_t i = 0; i < set->length; i++) {
                if (i > 0) pos += snprintf(buf + pos, bufsize - pos, ", ");
                char elem[256];
                fpy_value_repr(set->keys[i], elem, sizeof(elem));
                pos += snprintf(buf + pos, bufsize - pos, "%s", elem);
                if (pos >= bufsize - 1) break;
            }
            snprintf(buf + pos, bufsize - pos, "}");
            break;
        }
        case FPY_TAG_BYTES: {
            /* bytes repr: b'...' */
            const char *data = val.data.s;
            int pos = 0;
            pos += snprintf(buf + pos, bufsize - pos, "b'");
            if (data) {
                size_t len = strlen(data);
                for (size_t i = 0; i < len && pos < bufsize - 6; i++) {
                    unsigned char c = (unsigned char)data[i];
                    if (c == '\\') pos += snprintf(buf + pos, bufsize - pos, "\\\\");
                    else if (c == '\'') pos += snprintf(buf + pos, bufsize - pos, "\\'");
                    else if (c >= 32 && c < 127) pos += snprintf(buf + pos, bufsize - pos, "%c", c);
                    else pos += snprintf(buf + pos, bufsize - pos, "\\x%02x", c);
                }
            }
            snprintf(buf + pos, bufsize - pos, "'");
            break;
        }
    }
}

/* --- Value print (str formatting: strings without quotes) --- */

void fpy_value_print(FpyValue val) {
    fpy_value_write(val);
    printf("\n");
    fflush(stdout);  /* ensure output is visible immediately (threaded context) */
}

/* --- FpyValue ABI wrappers (Phase 1 of tagged-value refactor) ---
 * These take FpyValue as two separate primitives (tag, data_i64) to
 * sidestep the MSVC x64 by-hidden-pointer ABI for 16-byte structs.
 * The LLVM codegen passes two i-values and this wrapper packs them
 * back into an FpyValue locally. */

static inline FpyValue _pack_fv(int32_t tag, int64_t data) {
    FpyValue v;
    v.tag = tag;
    v.data.i = data;
    return v;
}

void fastpy_fv_print(int32_t tag, int64_t data) {
    fpy_value_print(_pack_fv(tag, data));
}

void fastpy_fv_write(int32_t tag, int64_t data) {
    fpy_value_write(_pack_fv(tag, data));
}

/* Return the repr string (allocated) for an FpyValue. */
const char* fastpy_fv_repr(int32_t tag, int64_t data) {
    char *buf = (char*)malloc(4096);
    fpy_value_repr(_pack_fv(tag, data), buf, 4096);
    return buf;
}

/* Forward declaration: defined later in this file */
const char* fastpy_obj_to_str(FpyObj *obj);

/* Return the str string (allocated) for an FpyValue — strings pass
 * through without quotes; OBJ types use __str__; other types use repr. */
const char* fastpy_fv_str(int32_t tag, int64_t data) {
    if (tag == FPY_TAG_STR) return (const char*)data;
    /* OBJ: use __str__ (not __repr__) */
    if (tag == FPY_TAG_OBJ && data != 0) {
        void *ptr = (void*)(intptr_t)data;
        int32_t first_word = *(int32_t*)ptr;
        if (first_word > 0 && first_word < 100000) {
            FpyObj *obj = (FpyObj*)ptr;
            if (obj->magic == FPY_OBJ_MAGIC) {
                return fastpy_obj_to_str(obj);
            }
        }
        /* CPython PyObject* — use PyObject_Str */
        extern const char* fpy_bridge_pyobj_str(void*);
        return fpy_bridge_pyobj_str(ptr);
    }
    char *buf = (char*)malloc(4096);
    fpy_value_repr(_pack_fv(tag, data), buf, 4096);
    return buf;
}

/* FpyValue comparison — op: 0=eq, 1=ne, 2=lt, 3=le, 4=gt, 5=ge.
 * Returns 1 if the comparison is true, 0 otherwise. */
int32_t fastpy_fv_compare(int32_t tag1, int64_t data1,
                           int32_t tag2, int64_t data2, int32_t op) {
    /* String comparison: both are STR → use strcmp */
    if (tag1 == FPY_TAG_STR && tag2 == FPY_TAG_STR) {
        const char *s1 = (const char*)(intptr_t)data1;
        const char *s2 = (const char*)(intptr_t)data2;
        if (!s1) s1 = "";
        if (!s2) s2 = "";
        int cmp = strcmp(s1, s2);
        switch (op) {
            case 0: return cmp == 0;
            case 1: return cmp != 0;
            case 2: return cmp < 0;
            case 3: return cmp <= 0;
            case 4: return cmp > 0;
            case 5: return cmp >= 0;
        }
    }
    /* Float comparison: at least one is FLOAT */
    if (tag1 == FPY_TAG_FLOAT || tag2 == FPY_TAG_FLOAT) {
        double d1, d2;
        if (tag1 == FPY_TAG_FLOAT) {
            union { int64_t i; double d; } u1; u1.i = data1; d1 = u1.d;
        } else {
            d1 = (double)data1;
        }
        if (tag2 == FPY_TAG_FLOAT) {
            union { int64_t i; double d; } u2; u2.i = data2; d2 = u2.d;
        } else {
            d2 = (double)data2;
        }
        switch (op) {
            case 0: return d1 == d2;
            case 1: return d1 != d2;
            case 2: return d1 < d2;
            case 3: return d1 <= d2;
            case 4: return d1 > d2;
            case 5: return d1 >= d2;
        }
    }
    /* Integer/bool comparison (default) */
    switch (op) {
        case 0: return data1 == data2;
        case 1: return data1 != data2;
        case 2: return data1 < data2;
        case 3: return data1 <= data2;
        case 4: return data1 > data2;
        case 5: return data1 >= data2;
    }
    return 0;
}

/* Truthiness — returns i32 (0 or 1). */
int32_t fastpy_fv_truthy(int32_t tag, int64_t data) {
    switch (tag) {
        case FPY_TAG_INT: return data != 0;
        case FPY_TAG_BOOL: return data != 0;
        case FPY_TAG_FLOAT: {
            double d;
            memcpy(&d, &data, sizeof(d));
            return d != 0.0;
        }
        case FPY_TAG_STR: {
            const char *s = (const char*)data;
            return s && s[0] != '\0';
        }
        case FPY_TAG_NONE: return 0;
        case FPY_TAG_LIST: {
            FpyList *lst = (FpyList*)data;
            return lst && lst->length != 0;
        }
        case FPY_TAG_DICT: {
            FpyDict *d = (FpyDict*)data;
            return d && d->length != 0;
        }
        case FPY_TAG_OBJ: {
            if (data == 0) return 0;
            FpyObj *obj = (FpyObj*)(intptr_t)data;
            if (obj->magic != FPY_OBJ_MAGIC) {
                /* CPython PyObject* — use PyObject_IsTrue */
                extern int64_t fpy_cpython_bool(void*);
                return (int32_t)fpy_cpython_bool((void*)(intptr_t)data);
            }
            /* Native FpyObj — check __bool__ / __len__, default true */
            return 1;
        }
        case FPY_TAG_SET: {
            FpyDict *s = (FpyDict*)data;
            return s && s->length != 0;
        }
    }
    return 0;
}

/* FpyValue len() — runtime dispatch based on tag.
 * Returns the length of the value (string length, list/tuple size,
 * dict/set size). Returns 0 for types without length. */
int64_t fastpy_fv_len(int32_t tag, int64_t data) {
    switch (tag) {
        case FPY_TAG_STR: {
            const char *s = (const char*)(intptr_t)data;
            return s ? (int64_t)strlen(s) : 0;
        }
        case FPY_TAG_LIST: {
            FpyList *lst = (FpyList*)(intptr_t)data;
            return lst ? lst->length : 0;
        }
        case FPY_TAG_DICT:
        case FPY_TAG_SET: {
            FpyDict *d = (FpyDict*)(intptr_t)data;
            return d ? d->length : 0;
        }
        case FPY_TAG_OBJ: {
            /* For objects, try __len__ via bridge or return 0 */
            FpyObj *obj = (FpyObj*)(intptr_t)data;
            if (obj && obj->magic != FPY_OBJ_MAGIC) {
                /* CPython PyObject* — use PyObject_Length */
                extern int64_t fpy_cpython_len(void*);
                return fpy_cpython_len((void*)(intptr_t)data);
            }
            return 0;  /* native obj without __len__ */
        }
        case FPY_TAG_BYTES: {
            const char *s = (const char*)(intptr_t)data;
            return s ? fpy_bytes_len(s) : 0;
        }
    }
    return 0;
}

/* FpyValue subscript — runtime dispatch for container[key].
 * Handles list (int key), dict (str or int key), and string (int key).
 * Results are written to *out_tag, *out_data. */
extern const char* fastpy_str_index(const char*, int64_t);
/* Forward-declare dict getters (defined later in this file) */
void fastpy_dict_get_fv(FpyDict*, const char*, int32_t*, int64_t*);
void fastpy_dict_get_int_fv(FpyDict*, int64_t, int32_t*, int64_t*);
void fastpy_fv_subscript(int32_t c_tag, int64_t c_data,
                          int32_t k_tag, int64_t k_data,
                          int32_t *out_tag, int64_t *out_data) {
    switch (c_tag) {
        case FPY_TAG_LIST: {
            FpyList *lst = (FpyList*)(intptr_t)c_data;
            /* key must be int for list subscript */
            int64_t idx = k_data;
            if (idx < 0) idx += lst->length;
            if (idx < 0 || idx >= lst->length) {
                fastpy_raise(FPY_EXC_INDEXERROR, "list index out of range");
                *out_tag = FPY_TAG_NONE;
                *out_data = 0;
                return;
            }
            *out_tag = lst->items[idx].tag;
            *out_data = lst->items[idx].data.i;
            return;
        }
        case FPY_TAG_DICT: {
            FpyDict *d = (FpyDict*)(intptr_t)c_data;
            if (k_tag == FPY_TAG_STR) {
                const char *key = (const char*)(intptr_t)k_data;
                fastpy_dict_get_fv(d, key, out_tag, out_data);
            } else {
                fastpy_dict_get_int_fv(d, k_data, out_tag, out_data);
            }
            return;
        }
        case FPY_TAG_STR: {
            const char *s = (const char*)(intptr_t)c_data;
            int64_t idx = k_data;
            const char *ch = fastpy_str_index(s, idx);
            *out_tag = FPY_TAG_STR;
            *out_data = (int64_t)(intptr_t)ch;
            return;
        }
        case FPY_TAG_BYTES: {
            const char *b = (const char*)(intptr_t)c_data;
            int64_t idx = k_data;
            int64_t len = (int64_t)strlen(b);
            if (idx < 0) idx += len;
            if (idx < 0 || idx >= len) {
                fastpy_raise(FPY_EXC_INDEXERROR, "bytes index out of range");
                *out_tag = FPY_TAG_NONE;
                *out_data = 0;
                return;
            }
            *out_tag = FPY_TAG_INT;
            *out_data = (int64_t)(unsigned char)b[idx];
            return;
        }
        case FPY_TAG_OBJ: {
            /* CPython PyObject* — use bridge __getitem__ */
            FpyObj *obj = (FpyObj*)(intptr_t)c_data;
            if (obj && obj->magic != FPY_OBJ_MAGIC) {
                extern void* fpy_cpython_getitem(void*, int32_t, int64_t);
                void *result = fpy_cpython_getitem(
                    (void*)(intptr_t)c_data, k_tag, k_data);
                *out_tag = FPY_TAG_OBJ;
                *out_data = (int64_t)(intptr_t)result;
                return;
            }
            break;
        }
    }
    /* Fallback: unsupported subscript */
    *out_tag = FPY_TAG_NONE;
    *out_data = 0;
}

/* FpyValue binary operation — runtime dispatch for Add/Sub/Mul/etc.
 * op: 0=add, 1=sub, 2=mul, 3=div, 4=floordiv, 5=mod
 * Results are written to *out_tag, *out_data. */
extern const char* fastpy_str_concat(const char*, const char*);
extern const char* fastpy_str_repeat(const char*, int64_t);
extern FpyList* fastpy_list_concat(FpyList*, FpyList*);
extern FpyList* fastpy_list_repeat(FpyList*, int64_t);
void fastpy_fv_binop(int32_t lt, int64_t ld, int32_t rt, int64_t rd,
                      int32_t op, int32_t *out_tag, int64_t *out_data) {
    /* String + String → concat */
    if (lt == FPY_TAG_STR && rt == FPY_TAG_STR && op == 0) {
        const char *result = fastpy_str_concat((const char*)ld, (const char*)rd);
        *out_tag = FPY_TAG_STR;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    /* String * Int or Int * String → repeat */
    if (lt == FPY_TAG_STR && rt == FPY_TAG_INT && op == 2) {
        const char *result = fastpy_str_repeat((const char*)ld, rd);
        *out_tag = FPY_TAG_STR;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    if (lt == FPY_TAG_INT && rt == FPY_TAG_STR && op == 2) {
        const char *result = fastpy_str_repeat((const char*)rd, ld);
        *out_tag = FPY_TAG_STR;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    /* List + List → concat */
    if (lt == FPY_TAG_LIST && rt == FPY_TAG_LIST && op == 0) {
        FpyList *result = fastpy_list_concat((FpyList*)(intptr_t)ld, (FpyList*)(intptr_t)rd);
        *out_tag = FPY_TAG_LIST;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    /* List * Int or Int * List → repeat */
    if (lt == FPY_TAG_LIST && (rt == FPY_TAG_INT || rt == FPY_TAG_BOOL) && op == 2) {
        FpyList *result = fastpy_list_repeat((FpyList*)(intptr_t)ld, rd);
        *out_tag = FPY_TAG_LIST;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    if ((lt == FPY_TAG_INT || lt == FPY_TAG_BOOL) && rt == FPY_TAG_LIST && op == 2) {
        FpyList *result = fastpy_list_repeat((FpyList*)(intptr_t)rd, ld);
        *out_tag = FPY_TAG_LIST;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    /* Bytes + Bytes → concat */
    if (lt == FPY_TAG_BYTES && rt == FPY_TAG_BYTES && op == 0) {
        const char *a = (const char*)(intptr_t)ld;
        const char *b = (const char*)(intptr_t)rd;
        size_t la = a ? strlen(a) : 0;
        size_t lb = b ? strlen(b) : 0;
        char *result = (char*)malloc(la + lb + 1);
        if (a) memcpy(result, a, la);
        if (b) memcpy(result + la, b, lb);
        result[la + lb] = '\0';
        *out_tag = FPY_TAG_BYTES;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    /* Bytes * Int or Int * Bytes → repeat */
    if (lt == FPY_TAG_BYTES && rt == FPY_TAG_INT && op == 2) {
        const char *a = (const char*)(intptr_t)ld;
        size_t la = a ? strlen(a) : 0;
        int64_t n = rd > 0 ? rd : 0;
        size_t total = la * (size_t)n;
        char *result = (char*)malloc(total + 1);
        for (int64_t i = 0; i < n; i++)
            memcpy(result + i * la, a, la);
        result[total] = '\0';
        *out_tag = FPY_TAG_BYTES;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    /* OBJ + OBJ or OBJ + any → delegate to CPython PyNumber_* */
    if (lt == FPY_TAG_OBJ || rt == FPY_TAG_OBJ) {
        /* Use fpy_cpython_binop/rbinop via bridge */
        extern void fpy_cpython_binop(void*, int32_t, int64_t, int32_t, int32_t*, int64_t*);
        extern void fpy_cpython_rbinop(int32_t, int64_t, void*, int32_t, int32_t*, int64_t*);
        if (lt == FPY_TAG_OBJ) {
            fpy_cpython_binop((void*)(intptr_t)ld, rt, rd, op, out_tag, out_data);
        } else {
            fpy_cpython_rbinop(lt, ld, (void*)(intptr_t)rd, op, out_tag, out_data);
        }
        return;
    }
    /* BigInt arithmetic — promote INT/BOOL to BigInt if needed */
    if (lt == FPY_TAG_BIGINT || rt == FPY_TAG_BIGINT) {
        extern FpyBigInt* fpy_bigint_from_i64(int64_t);
        extern FpyBigInt* fpy_bigint_add(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_sub(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_mul(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_floordiv(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_mod(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_pow(FpyBigInt*, FpyBigInt*);
        FpyBigInt *la, *ra;
        if (lt == FPY_TAG_BIGINT) la = (FpyBigInt*)(intptr_t)ld;
        else la = fpy_bigint_from_i64(ld);
        if (rt == FPY_TAG_BIGINT) ra = (FpyBigInt*)(intptr_t)rd;
        else ra = fpy_bigint_from_i64(rd);
        FpyBigInt *result = NULL;
        switch (op) {
            case 0: result = fpy_bigint_add(la, ra); break;
            case 1: result = fpy_bigint_sub(la, ra); break;
            case 2: result = fpy_bigint_mul(la, ra); break;
            case 3: /* truediv — fall through to float */ break;
            case 4: result = fpy_bigint_floordiv(la, ra); break;
            case 5: result = fpy_bigint_mod(la, ra); break;
            default: break;
        }
        if (result) {
            *out_tag = FPY_TAG_BIGINT;
            *out_data = (int64_t)(intptr_t)result;
            return;
        }
        /* truediv falls through (BigInt / BigInt → float not implemented yet) */
    }
    /* Promote to float if either operand is float */
    if (lt == FPY_TAG_FLOAT || rt == FPY_TAG_FLOAT) {
        double lf, rf;
        if (lt == FPY_TAG_FLOAT) { memcpy(&lf, &ld, sizeof(double)); }
        else if (lt == FPY_TAG_INT) { lf = (double)ld; }
        else if (lt == FPY_TAG_BOOL) { lf = (double)ld; }
        else { lf = 0.0; }
        if (rt == FPY_TAG_FLOAT) { memcpy(&rf, &rd, sizeof(double)); }
        else if (rt == FPY_TAG_INT) { rf = (double)rd; }
        else if (rt == FPY_TAG_BOOL) { rf = (double)rd; }
        else { rf = 0.0; }
        double result;
        switch (op) {
            case 0: result = lf + rf; break;
            case 1: result = lf - rf; break;
            case 2: result = lf * rf; break;
            case 3: result = rf != 0.0 ? lf / rf : 0.0; break;
            case 4: result = rf != 0.0 ? floor(lf / rf) : 0.0; break;
            case 5: result = rf != 0.0 ? fmod(lf, rf) : 0.0; break;
            default: result = 0.0; break;
        }
        *out_tag = FPY_TAG_FLOAT;
        memcpy(out_data, &result, sizeof(double));
        return;
    }
    /* Guard: container types that weren't handled above → TypeError */
    if (lt == FPY_TAG_LIST || lt == FPY_TAG_DICT || lt == FPY_TAG_SET ||
        rt == FPY_TAG_LIST || rt == FPY_TAG_DICT || rt == FPY_TAG_SET ||
        lt == FPY_TAG_STR  || rt == FPY_TAG_STR) {
        /* If we reach here, no valid handler matched (e.g. list+int, dict-int,
         * str+list, etc.) — raise TypeError like CPython does. */
        static const char *_op_syms[] = {"+", "-", "*", "/", "//", "%"};
        static const char *_tnames[] = {
            "int", "float", "str", "bool", "NoneType",
            "list", "object", "dict", "bytes", "set",
            "bigint", "complex", "Decimal"};
        const char *ln = (lt >= 0 && lt <= 12) ? _tnames[lt] : "object";
        const char *rn = (rt >= 0 && rt <= 12) ? _tnames[rt] : "object";
        const char *on = (op >= 0 && op <= 5) ? _op_syms[op] : "?";
        snprintf(_err_buf, sizeof(_err_buf),
                 "unsupported operand type(s) for %s: '%.40s' and '%.40s'",
                 on, ln, rn);
        fastpy_raise(FPY_EXC_TYPEERROR, _err_buf);
        *out_tag = FPY_TAG_NONE; *out_data = 0;
        return;
    }
    /* Int/Bool arithmetic */
    int64_t li = (lt == FPY_TAG_BOOL) ? (int64_t)(ld != 0) : ld;
    int64_t ri = (rt == FPY_TAG_BOOL) ? (int64_t)(rd != 0) : rd;
    int64_t result;
    switch (op) {
        case 0: result = li + ri; break;
        case 1: result = li - ri; break;
        case 2: result = li * ri; break;
        case 3: /* truediv returns float */ {
            double d = ri != 0 ? (double)li / (double)ri : 0.0;
            *out_tag = FPY_TAG_FLOAT;
            memcpy(out_data, &d, sizeof(double));
            return;
        }
        case 4: result = ri != 0 ? li / ri : 0; break;
        case 5: result = ri != 0 ? li % ri : 0; break;
        default: result = 0; break;
    }
    *out_tag = FPY_TAG_INT;
    *out_data = result;
}

void fpy_value_write(FpyValue val) {
    char buf[4096];
    switch (val.tag) {
        case FPY_TAG_INT:
            printf("%lld", (long long)val.data.i);
            break;
        case FPY_TAG_FLOAT:
            format_float(val.data.f, buf, sizeof(buf));
            printf("%s", buf);
            break;
        case FPY_TAG_STR:
            printf("%s", val.data.s);
            break;
        case FPY_TAG_BOOL:
            printf("%s", val.data.b ? "True" : "False");
            break;
        case FPY_TAG_NONE:
            printf("None");
            break;
        case FPY_TAG_LIST:
            fpy_list_write(val.data.list);
            break;
        case FPY_TAG_OBJ:
            fastpy_obj_write(val.data.obj);
            break;
        case FPY_TAG_DICT:
            fastpy_dict_write((FpyDict*)val.data.list);
            break;
        case FPY_TAG_SET:
            fastpy_set_write((FpyDict*)val.data.list);
            break;
        case FPY_TAG_BIGINT: {
            const char *s = fpy_bigint_to_str((FpyBigInt*)(intptr_t)val.data.i);
            printf("%s", s);
            free((void*)s);
            break;
        }
        case FPY_TAG_COMPLEX:
            fpy_complex_print((FpyComplex*)(intptr_t)val.data.i);
            break;
        case FPY_TAG_DECIMAL: {
            char *s = fpy_decimal_to_str((FpyDecimal*)(intptr_t)val.data.i);
            printf("%s", s);
            free(s);
            break;
        }
        case FPY_TAG_BYTES: {
            /* Print bytes in Python b'...' repr format */
            const char *data = val.data.s;
            if (!data) { printf("b''"); break; }
            printf("b'");
            size_t len = strlen(data);
            for (size_t i = 0; i < len; i++) {
                unsigned char c = (unsigned char)data[i];
                if (c == '\\') printf("\\\\");
                else if (c == '\'') printf("\\'");
                else if (c >= 32 && c < 127) printf("%c", c);
                else printf("\\x%02x", c);
            }
            printf("'");
            break;
        }
    }
}

void fpy_list_print(FpyList *list) {
    fpy_list_write(list);
    printf("\n");
}

void fpy_list_write(FpyList *list) {
    char buf[4096];
    int pos = 0;
    const char *open = list->is_tuple ? "(" : "[";
    const char *close = list->is_tuple ? ")" : "]";
    pos += snprintf(buf + pos, sizeof(buf) - pos, "%s", open);
    for (int64_t i = 0; i < list->length; i++) {
        if (i > 0) pos += snprintf(buf + pos, sizeof(buf) - pos, ", ");
        char elem[256];
        fpy_value_repr(list->items[i], elem, sizeof(elem));
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%s", elem);
        if (pos >= (int)sizeof(buf) - 1) break;
    }
    if (list->is_tuple && list->length == 1) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, ",");
    }
    snprintf(buf + pos, sizeof(buf) - pos, "%s", close);
    printf("%s", buf);
}

/* --- Wrapper functions for LLVM codegen --- */
/* These use pointer-based interfaces since LLVM can't easily pass structs by value */

/* Create a new list and return pointer */
FpyList* fastpy_list_new(void) {
    return fpy_list_new(4);
}

/* --- FV-ABI list element access (Phase 4 of tagged-value refactor) ---
 * Takes/returns FpyValue as (tag, data_i64) pairs to sidestep MSVC x64's
 * 16-byte struct ABI. Eliminates the need for compile-time element-type
 * tracking (Hacks 4, 5, 6, 12, 18, 22). */

void fastpy_list_append_fv(FpyList *list, int32_t tag, int64_t data) {
    FpyValue v;
    v.tag = tag;
    v.data.i = data;
    fpy_list_append(list, v);
}

void fastpy_list_get_fv(FpyList *list, int64_t index,
                        int32_t *out_tag, int64_t *out_data) {
    FpyValue v = fpy_list_get(list, index);
    *out_tag = v.tag;
    *out_data = v.data.i;
}

void fastpy_list_set_fv(FpyList *list, int64_t index,
                        int32_t tag, int64_t data) {
    FpyValue v;
    v.tag = tag;
    v.data.i = data;
    fpy_list_set(list, index, v);
}

/* fastpy_dict_set_fv / fastpy_dict_get_fv are defined later in this file,
   after fpy_dict_set and fpy_dict_get are in scope. */

int64_t fastpy_list_length(FpyList *list) {
    return list->length;
}

/* --- Tuple printing (uses FpyList internally, prints with parens) --- */

/* Slice a list */
FpyList* fastpy_list_slice(FpyList *list, int64_t start, int64_t stop,
                           int64_t has_start, int64_t has_stop) {
    int64_t len = list->length;
    if (!has_start) start = 0;
    if (!has_stop) stop = len;
    if (start < 0) start += len;
    if (stop < 0) stop += len;
    if (start < 0) start = 0;
    if (stop > len) stop = len;
    if (start >= stop) {
        FpyList *empty = fpy_list_new(0);
        empty->is_tuple = list->is_tuple;
        return empty;
    }
    int64_t rlen = stop - start;
    FpyList *result = fpy_list_new(rlen);
    result->is_tuple = list->is_tuple;
    if (rlen > 0) {
        memcpy(result->items, list->items + start, rlen * sizeof(FpyValue));
        result->length = rlen;
        if (!fpy_list_all_scalar(result)) {
            for (int64_t i = 0; i < rlen; i++) {
                FPY_VAL_INCREF(result->items[i]);
            }
        }
    }
    return result;
}

/* Slice with step (e.g. x[::2] or x[::-1]) */
FpyList* fastpy_list_slice_step(FpyList *list, int64_t start, int64_t stop,
                                int64_t step, int64_t has_start, int64_t has_stop) {
    int64_t len = list->length;
    if (step == 0) { fastpy_raise(FPY_EXC_VALUEERROR, "slice step cannot be zero"); return NULL; }

    if (step > 0) {
        if (!has_start) start = 0;
        if (!has_stop) stop = len;
    } else {
        if (!has_start) start = len - 1;
        if (!has_stop) stop = -len - 1;
    }
    if (start < 0) start += len;
    if (stop < 0) stop += len;
    if (start < 0) start = 0;
    if (start > len) start = len;
    if (stop < -1) stop = -1;
    if (stop > len) stop = len;

    FpyList *result = fpy_list_new(8);
    result->is_tuple = list->is_tuple;
    if (step > 0) {
        for (int64_t i = start; i < stop; i += step)
            fpy_list_append(result, list->items[i]);
    } else {
        for (int64_t i = start; i > stop; i += step)
            if (i >= 0 && i < len)
                fpy_list_append(result, list->items[i]);
    }
    return result;
}

/* Sort comparison for qsort */
static int fpy_value_compare(const void *a, const void *b) {
    const FpyValue *va = (const FpyValue*)a;
    const FpyValue *vb = (const FpyValue*)b;
    /* Compare by tag first, then by value */
    if (va->tag != vb->tag) return va->tag - vb->tag;
    switch (va->tag) {
        case FPY_TAG_INT:
            return (va->data.i > vb->data.i) - (va->data.i < vb->data.i);
        case FPY_TAG_BOOL:
            return (va->data.i > vb->data.i) - (va->data.i < vb->data.i);
        case FPY_TAG_FLOAT:
            return (va->data.f > vb->data.f) - (va->data.f < vb->data.f);
        case FPY_TAG_STR:
            return strcmp(va->data.s, vb->data.s);
        case FPY_TAG_BIGINT: {
            extern int fpy_bigint_cmp(FpyBigInt*, FpyBigInt*);
            FpyBigInt *ba = (FpyBigInt*)(intptr_t)va->data.i;
            FpyBigInt *bb = (FpyBigInt*)(intptr_t)vb->data.i;
            return fpy_bigint_cmp(ba, bb);
        }
        case FPY_TAG_LIST: {
            /* Lexicographic compare of element lists */
            FpyList *la = va->data.list;
            FpyList *lb = vb->data.list;
            if (!la && !lb) return 0;
            if (!la) return -1;
            if (!lb) return 1;
            int64_t n = la->length < lb->length ? la->length : lb->length;
            for (int64_t i = 0; i < n; i++) {
                int c = fpy_value_compare(&la->items[i], &lb->items[i]);
                if (c != 0) return c;
            }
            return (la->length > lb->length) - (la->length < lb->length);
        }
        case FPY_TAG_OBJ: {
            /* Compare by pointer identity for native objects.
             * For PyObject*, use CPython rich comparison. */
            void *pa = va->data.obj;
            void *pb = vb->data.obj;
            if (!pa && !pb) return 0;
            if (!pa) return -1;
            if (!pb) return 1;
            FpyObj *oa = (FpyObj*)pa;
            if (oa->magic != FPY_OBJ_MAGIC) {
                /* Both are PyObject* (same tag) — use CPython compare */
                extern int32_t fpy_cpython_compare(void*, void*, int32_t);
                /* Lt returns 1 if pa < pb */
                if (fpy_cpython_compare(pa, pb, 2)) return -1;
                if (fpy_cpython_compare(pa, pb, 4)) return 1;
                return 0;
            }
            /* Native FpyObj — compare by pointer identity */
            return (pa > pb) - (pa < pb);
        }
        default:
            return 0;
    }
}

/* Return a new sorted copy of a list */
FpyList* fastpy_list_sorted(FpyList *list) {
    FpyList *result = fpy_list_new(list->length);
    memcpy(result->items, list->items, sizeof(FpyValue) * list->length);
    result->length = list->length;
    /* Incref each copied element (now referenced from both lists) */
    for (int64_t i = 0; i < result->length; i++)
        FPY_VAL_INCREF(result->items[i]);
    qsort(result->items, result->length, sizeof(FpyValue), fpy_value_compare);
    return result;
}

/* Return a new reversed copy of a list */
FpyList* fastpy_list_reversed(FpyList *list) {
    FpyList *result = fpy_list_new(list->length);
    for (int64_t i = 0; i < list->length; i++) {
        FPY_VAL_INCREF(list->items[list->length - 1 - i]);
        result->items[i] = list->items[list->length - 1 - i];
    }
    result->length = list->length;
    return result;
}

/* --- String methods that return lists / take lists --- */

/* Split a string by whitespace, return list of strings */
FpyList* fastpy_str_split(const char *s) {
    FpyList *result = fpy_list_new(8);
    const char *p = s;
    while (*p) {
        /* Skip whitespace */
        while (*p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) p++;
        if (!*p) break;
        /* Find end of word */
        const char *start = p;
        while (*p && *p != ' ' && *p != '\t' && *p != '\n' && *p != '\r') p++;
        /* Copy word */
        int64_t len = p - start;
        char *word = (char*)malloc(len + 1);
        memcpy(word, start, len);
        word[len] = '\0';
        fpy_list_append(result, fpy_str(word));
    }
    return result;
}

/* Join a list of strings with a separator */
const char* fastpy_str_join(const char *sep, FpyList *list) {
    if (list->length == 0) {
        char *result = (char*)malloc(1);
        result[0] = '\0';
        return result;
    }
    size_t sep_len = strlen(sep);
    size_t total = 0;
    for (int64_t i = 0; i < list->length; i++) {
        total += strlen(list->items[i].data.s);
        if (i > 0) total += sep_len;
    }
    char *result = (char*)malloc(total + 1);
    size_t pos = 0;
    for (int64_t i = 0; i < list->length; i++) {
        if (i > 0) { memcpy(result + pos, sep, sep_len); pos += sep_len; }
        size_t len = strlen(list->items[i].data.s);
        memcpy(result + pos, list->items[i].data.s, len);
        pos += len;
    }
    result[pos] = '\0';
    return result;
}

/* Create a deduplicated copy (set-like) of a list */
FpyList* fastpy_list_set(FpyList *list) {
    FpyList *result = fpy_list_new(list->length);
    for (int64_t i = 0; i < list->length; i++) {
        /* Check if element already in result */
        int found = 0;
        for (int64_t j = 0; j < result->length; j++) {
            if (result->items[j].tag == list->items[i].tag) {
                if (list->items[i].tag == FPY_TAG_INT &&
                    result->items[j].data.i == list->items[i].data.i) {
                    found = 1; break;
                }
                if (list->items[i].tag == FPY_TAG_STR &&
                    strcmp(result->items[j].data.s, list->items[i].data.s) == 0) {
                    found = 1; break;
                }
            }
        }
        if (!found) {
            fpy_list_append(result, list->items[i]);
        }
    }
    return result;
}

/* Convert list to string for f-string formatting */
const char* fastpy_list_to_str(FpyList *list) {
    char *buf = (char*)malloc(4096);
    int pos = 0;
    const char *open = list->is_tuple ? "(" : "[";
    const char *close = list->is_tuple ? ")" : "]";
    pos += snprintf(buf + pos, 4096 - pos, "%s", open);
    for (int64_t i = 0; i < list->length; i++) {
        if (i > 0) pos += snprintf(buf + pos, 4096 - pos, ", ");
        char elem[256];
        fpy_value_repr(list->items[i], elem, sizeof(elem));
        pos += snprintf(buf + pos, 4096 - pos, "%s", elem);
        if (pos >= 4095) break;
    }
    /* Single-element tuple prints as (x,) */
    if (list->is_tuple && list->length == 1) {
        pos += snprintf(buf + pos, 4096 - pos, ",");
    }
    snprintf(buf + pos, 4096 - pos, "%s", close);
    return buf;
}

/* Convert tuple to string for f-strings */
const char* fastpy_tuple_to_str(FpyList *tuple) {
    char *buf = (char*)malloc(4096);
    int pos = 0;
    pos += snprintf(buf + pos, 4096 - pos, "(");
    for (int64_t i = 0; i < tuple->length; i++) {
        if (i > 0) pos += snprintf(buf + pos, 4096 - pos, ", ");
        char elem[256];
        fpy_value_repr(tuple->items[i], elem, sizeof(elem));
        pos += snprintf(buf + pos, 4096 - pos, "%s", elem);
        if (pos >= 4095) break;
    }
    if (tuple->length == 1) pos += snprintf(buf + pos, 4096 - pos, ",");
    snprintf(buf + pos, 4096 - pos, ")");
    return buf;
}

void fastpy_tuple_write(FpyList *tuple) {
    char buf[4096];
    int pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "(");
    for (int64_t i = 0; i < tuple->length; i++) {
        if (i > 0) pos += snprintf(buf + pos, sizeof(buf) - pos, ", ");
        char elem[256];
        fpy_value_repr(tuple->items[i], elem, sizeof(elem));
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%s", elem);
        if (pos >= (int)sizeof(buf) - 1) break;
    }
    /* Single-element tuples need trailing comma: (1,) */
    if (tuple->length == 1) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, ",");
    }
    snprintf(buf + pos, sizeof(buf) - pos, ")");
    printf("%s", buf);
}

/* --- Dict operations --- */

/* ------------------------------------------------------------------ */
/* Hash table dict implementation.                                     */
/*                                                                     */
/* Open addressing with linear probing. Hash table (`indices`) maps    */
/* hash slots to entry indices in compact `keys`/`values` arrays.      */
/* Preserves insertion order (iteration scans keys[0..length-1]).      */
/* Resize at 2/3 load factor. Minimum table size 8.                    */
/* ------------------------------------------------------------------ */

static uint64_t fpy_hash_string(const char *s) {
    /* FNV-1a hash */
    uint64_t h = 14695981039346656037ULL;
    for (; *s; s++) {
        h ^= (uint64_t)(unsigned char)*s;
        h *= 1099511628211ULL;
    }
    return h;
}

static uint64_t fpy_hash_value(FpyValue v) {
    if (v.tag == FPY_TAG_STR) return fpy_hash_string(v.data.s);
    if (v.tag == FPY_TAG_INT) {
        /* Mix integer bits (splitmix64-style) */
        uint64_t x = (uint64_t)v.data.i;
        x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
        x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
        return x ^ (x >> 31);
    }
    return (uint64_t)v.data.i;  /* fallback for other types */
}

static int fpy_key_equal(FpyValue a, FpyValue b) {
    if (a.tag != b.tag) return 0;
    if (a.tag == FPY_TAG_INT) return a.data.i == b.data.i;
    if (a.tag == FPY_TAG_STR) {
        return a.data.s == b.data.s || strcmp(a.data.s, b.data.s) == 0;
    }
    return a.data.i == b.data.i;  /* fallback */
}

static void fpy_dict_init_indices(FpyDict *dict) {
    for (int64_t i = 0; i < dict->table_size; i++)
        dict->indices[i] = FPY_DICT_EMPTY;
}

static void fpy_dict_rebuild_indices(FpyDict *dict) {
    /* Rebuild the hash table from the compact entries. Called after
     * resize or when the table has too many tombstones. */
    fpy_dict_init_indices(dict);
    int64_t mask = dict->table_size - 1;
    for (int64_t i = 0; i < dict->length; i++) {
        uint64_t h = fpy_hash_value(dict->keys[i]);
        int64_t slot = (int64_t)(h & (uint64_t)mask);
        while (dict->indices[slot] != FPY_DICT_EMPTY)
            slot = (slot + 1) & mask;
        dict->indices[slot] = i;
    }
}

FpyDict* fpy_dict_new(int64_t capacity) {
    if (capacity < 4) capacity = 4;
    FpyDict *dict = (FpyDict*)malloc(sizeof(FpyDict));
    dict->keys = (FpyValue*)malloc(sizeof(FpyValue) * capacity);
    dict->values = (FpyValue*)malloc(sizeof(FpyValue) * capacity);
    dict->length = 0;
    dict->capacity = capacity;
    /* Hash table starts at 8 (power of 2, ≥ capacity * 3/2) */
    dict->table_size = 8;
    while (dict->table_size < capacity * 3 / 2)
        dict->table_size *= 2;
    dict->indices = (int64_t*)malloc(sizeof(int64_t) * dict->table_size);
    fpy_dict_init_indices(dict);
    dict->refcount = 1;
    memset(&dict->gc_node, 0, sizeof(FpyGCNode));
    dict->gc_node.gc_type = FPY_GC_TYPE_DICT;
    fpy_gc_track(&dict->gc_node);
    fpy_gc_maybe_collect();
    if (fpy_threading_mode == FPY_THREADING_FREE) fpy_mutex_init(&dict->lock);
    return dict;
}

/* Unlocked dict set — caller must hold dict->lock if needed */
static void fpy_dict_set_unlocked(FpyDict *dict, FpyValue key, FpyValue value) {
    uint64_t h = fpy_hash_value(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    int64_t first_deleted = -1;

    /* Probe for existing key or empty slot */
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) {
            break;  /* key not found */
        }
        if (idx == FPY_DICT_DELETED) {
            if (first_deleted < 0) first_deleted = slot;
        } else if (fpy_key_equal(dict->keys[idx], key)) {
            /* Key exists — update value in place */
            FPY_VAL_DECREF(dict->values[idx]);
            FPY_VAL_INCREF(value);
            dict->values[idx] = value;
            return;
        }
        slot = (slot + 1) & mask;
    }

    /* Insert new entry. Use the first deleted slot if available,
     * otherwise use the empty slot we stopped at. */
    int64_t insert_slot = (first_deleted >= 0) ? first_deleted : slot;

    /* Grow entries array if needed */
    if (dict->length >= dict->capacity) {
        dict->capacity = dict->capacity * 2;
        dict->keys = (FpyValue*)realloc(dict->keys,
                                         sizeof(FpyValue) * dict->capacity);
        dict->values = (FpyValue*)realloc(dict->values,
                                           sizeof(FpyValue) * dict->capacity);
    }

    int64_t entry_idx = dict->length;
    FPY_VAL_INCREF(key);
    FPY_VAL_INCREF(value);
    dict->keys[entry_idx] = key;
    dict->values[entry_idx] = value;
    dict->indices[insert_slot] = entry_idx;
    dict->length++;

    /* Resize hash table if load factor > 2/3 */
    if (dict->length * 3 > dict->table_size * 2) {
        dict->table_size *= 2;
        dict->indices = (int64_t*)realloc(dict->indices,
                                           sizeof(int64_t) * dict->table_size);
        fpy_dict_rebuild_indices(dict);
    }
}

void fpy_dict_set(FpyDict *dict, FpyValue key, FpyValue value) {
    FPY_LOCK(dict);
    fpy_dict_set_unlocked(dict, key, value);
    FPY_UNLOCK(dict);
}

FpyValue fpy_dict_get(FpyDict *dict, FpyValue key) {
    uint64_t h = fpy_hash_value(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);

    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;  /* not found */
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], key))
            return dict->values[idx];
        slot = (slot + 1) & mask;
    }
    fastpy_raise(FPY_EXC_KEYERROR, "KeyError");
    FpyValue _err = {0}; return _err;
}

/* --- Dict wrapper functions for LLVM --- */

FpyDict* fastpy_dict_new(void) {
    return fpy_dict_new(4);
}

void fastpy_dict_set_fv(FpyDict *dict, const char *key,
                         int32_t tag, int64_t data) {
    FpyValue k = fpy_str(key);
    FpyValue v; v.tag = tag; v.data.i = data;
    uint64_t h = fpy_hash_string(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    int64_t first_deleted = -1;
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx == FPY_DICT_DELETED) {
            if (first_deleted < 0) first_deleted = slot;
        } else if (dict->keys[idx].tag == FPY_TAG_STR
                   && (dict->keys[idx].data.s == key
                       || strcmp(dict->keys[idx].data.s, key) == 0)) {
            dict->values[idx] = v;
            return;
        }
        slot = (slot + 1) & mask;
    }
    int64_t insert_slot = (first_deleted >= 0) ? first_deleted : slot;
    if (dict->length >= dict->capacity) {
        dict->capacity *= 2;
        dict->keys = (FpyValue*)realloc(dict->keys, sizeof(FpyValue) * dict->capacity);
        dict->values = (FpyValue*)realloc(dict->values, sizeof(FpyValue) * dict->capacity);
    }
    dict->keys[dict->length] = k;
    dict->values[dict->length] = v;
    dict->indices[insert_slot] = dict->length;
    dict->length++;
    if (dict->length * 3 > dict->table_size * 2) {
        dict->table_size *= 2;
        dict->indices = (int64_t*)realloc(dict->indices, sizeof(int64_t) * dict->table_size);
        fpy_dict_rebuild_indices(dict);
    }
}

void fastpy_dict_get_fv(FpyDict *dict, const char *key,
                         int32_t *out_tag, int64_t *out_data) {
    uint64_t h = fpy_hash_string(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED
                && dict->keys[idx].tag == FPY_TAG_STR
                && (dict->keys[idx].data.s == key
                    || strcmp(dict->keys[idx].data.s, key) == 0)) {
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return;
        }
        slot = (slot + 1) & mask;
    }
    fastpy_raise(FPY_EXC_KEYERROR, key);
    *out_tag = FPY_TAG_NONE; *out_data = 0; return;
}

/* Safe variant: returns NONE for missing keys without raising.
 * Used by match/case MatchMapping pattern to probe for keys. */
void fastpy_dict_get_fv_safe(FpyDict *dict, const char *key,
                              int32_t *out_tag, int64_t *out_data) {
    uint64_t h = fpy_hash_string(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED
                && dict->keys[idx].tag == FPY_TAG_STR
                && (dict->keys[idx].data.s == key
                    || strcmp(dict->keys[idx].data.s, key) == 0)) {
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return;
        }
        slot = (slot + 1) & mask;
    }
    *out_tag = FPY_TAG_NONE; *out_data = 0;
}

/* ------------------------------------------------------------------ */
/* Specialized int-key dict operations.                                */
/*                                                                     */
/* These bypass the generic FpyValue wrapping path (fpy_int() +        */
/* fpy_hash_value() + fpy_key_equal()) and operate directly on the     */
/* int64_t key. ~10-15x faster per operation due to avoiding struct    */
/* construction, indirect dispatch, and tag checks on every probe.     */
/* ------------------------------------------------------------------ */

static uint64_t fpy_hash_int(int64_t key) {
    uint64_t x = (uint64_t)key;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

void fastpy_dict_set_int_int(FpyDict *dict, int64_t key, int64_t value) {
    FpyValue k = fpy_int(key);
    FpyValue v = fpy_int(value);
    uint64_t h = fpy_hash_int(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    int64_t first_deleted = -1;
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx == FPY_DICT_DELETED) {
            if (first_deleted < 0) first_deleted = slot;
        } else if (dict->keys[idx].tag == FPY_TAG_INT
                   && dict->keys[idx].data.i == key) {
            dict->values[idx] = v;
            return;
        }
        slot = (slot + 1) & mask;
    }
    int64_t insert_slot = (first_deleted >= 0) ? first_deleted : slot;
    if (dict->length >= dict->capacity) {
        dict->capacity *= 2;
        dict->keys = (FpyValue*)realloc(dict->keys, sizeof(FpyValue) * dict->capacity);
        dict->values = (FpyValue*)realloc(dict->values, sizeof(FpyValue) * dict->capacity);
    }
    dict->keys[dict->length] = k;
    dict->values[dict->length] = v;
    dict->indices[insert_slot] = dict->length;
    dict->length++;
    if (dict->length * 3 > dict->table_size * 2) {
        dict->table_size *= 2;
        dict->indices = (int64_t*)realloc(dict->indices, sizeof(int64_t) * dict->table_size);
        fpy_dict_rebuild_indices(dict);
    }
}

void fastpy_dict_set_int_fv(FpyDict *dict, int64_t key,
                             int32_t tag, int64_t data) {
    FpyValue k = fpy_int(key);
    FpyValue v; v.tag = tag; v.data.i = data;
    uint64_t h = fpy_hash_int(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    int64_t first_deleted = -1;
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx == FPY_DICT_DELETED) {
            if (first_deleted < 0) first_deleted = slot;
        } else if (dict->keys[idx].tag == FPY_TAG_INT
                   && dict->keys[idx].data.i == key) {
            dict->values[idx] = v;
            return;
        }
        slot = (slot + 1) & mask;
    }
    int64_t insert_slot = (first_deleted >= 0) ? first_deleted : slot;
    if (dict->length >= dict->capacity) {
        dict->capacity *= 2;
        dict->keys = (FpyValue*)realloc(dict->keys, sizeof(FpyValue) * dict->capacity);
        dict->values = (FpyValue*)realloc(dict->values, sizeof(FpyValue) * dict->capacity);
    }
    dict->keys[dict->length] = k;
    dict->values[dict->length] = v;
    dict->indices[insert_slot] = dict->length;
    dict->length++;
    if (dict->length * 3 > dict->table_size * 2) {
        dict->table_size *= 2;
        dict->indices = (int64_t*)realloc(dict->indices, sizeof(int64_t) * dict->table_size);
        fpy_dict_rebuild_indices(dict);
    }
}

void fastpy_dict_get_int_fv(FpyDict *dict, int64_t key,
                             int32_t *out_tag, int64_t *out_data) {
    uint64_t h = fpy_hash_int(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED
                && dict->keys[idx].tag == FPY_TAG_INT
                && dict->keys[idx].data.i == key) {
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return;
        }
        slot = (slot + 1) & mask;
    }
    fastpy_raise(FPY_EXC_KEYERROR, "KeyError");
    *out_tag = FPY_TAG_NONE; *out_data = 0; return;
}

/* Direct int-value return for int-keyed dicts with known int values.
 * Returns the value as i64 directly (no output pointers, no tag).
 * Lets LLVM keep everything in registers — ~10x faster in tight loops. */
int64_t fastpy_dict_get_int_val(FpyDict *dict, int64_t key) {
    uint64_t h = fpy_hash_int(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED
                && dict->keys[idx].tag == FPY_TAG_INT
                && dict->keys[idx].data.i == key) {
            return dict->values[idx].data.i;
        }
        slot = (slot + 1) & mask;
    }
    fastpy_raise(FPY_EXC_KEYERROR, "KeyError");
    return 0;
}

int32_t fastpy_dict_has_int_key(FpyDict *dict, int64_t key) {
    uint64_t h = fpy_hash_int(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) return 0;
        if (idx != FPY_DICT_DELETED
                && dict->keys[idx].tag == FPY_TAG_INT
                && dict->keys[idx].data.i == key)
            return 1;
        slot = (slot + 1) & mask;
    }
}

void fastpy_dict_update(FpyDict *dst, FpyDict *src) {
    FPY_LOCK(dst);
    for (int64_t i = 0; i < src->length; i++) {
        fpy_dict_set_unlocked(dst, src->keys[i], src->values[i]);
    }
    FPY_UNLOCK(dst);
}

/* dict.copy() — shallow copy */
FpyDict* fastpy_dict_copy(FpyDict *dict) {
    FpyDict *result = fpy_dict_new(dict->length > 4 ? dict->length : 4);
    for (int64_t i = 0; i < dict->length; i++) {
        fpy_dict_set(result, dict->keys[i], dict->values[i]);
    }
    return result;
}

void fastpy_dict_clear(FpyDict *dict) {
    FPY_LOCK(dict);
    dict->length = 0;
    memset(dict->indices, 0xFF, dict->table_size * sizeof(int64_t));
    FPY_UNLOCK(dict);
}

/* Dict methods returning lists */
FpyList* fastpy_dict_keys(FpyDict *dict) {
    FpyList *result = fpy_list_new(dict->length);
    for (int64_t i = 0; i < dict->length; i++)
        fpy_list_append(result, dict->keys[i]);
    return result;
}

FpyList* fastpy_dict_values(FpyDict *dict) {
    FpyList *result = fpy_list_new(dict->length);
    for (int64_t i = 0; i < dict->length; i++)
        fpy_list_append(result, dict->values[i]);
    return result;
}

/* items() returns a list of 2-element tuples */
FpyList* fastpy_dict_items(FpyDict *dict) {
    FpyList *result = fpy_list_new(dict->length);
    for (int64_t i = 0; i < dict->length; i++) {
        FpyList *pair = fpy_list_new(2);
        pair->is_tuple = 1;
        fpy_list_append(pair, dict->keys[i]);
        fpy_list_append(pair, dict->values[i]);
        fpy_list_append(result, fpy_list(pair));
    }
    return result;
}

int64_t fastpy_dict_length(FpyDict *dict) {
    return dict->length;
}

/* --- Set operations (dict-backed, O(1) membership via hash table) ---
 *
 * Sets are FpyDict where keys = elements, values = fpy_none().
 * This gives O(1) add/remove/contains vs O(n) with the old list approach.
 * The codegen tags set-typed values with FPY_TAG_SET.
 */

/* Check if a set (FpyDict) contains a key. O(1) via hash lookup. */
int fastpy_set_contains(FpyDict *set, FpyValue key) {
    uint64_t h = fpy_hash_value(key);
    int64_t mask = set->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = set->indices[slot];
        if (idx == FPY_DICT_EMPTY) return 0;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(set->keys[idx], key))
            return 1;
        slot = (slot + 1) & mask;
    }
}

/* Check if a set contains an element (FV ABI). O(1) hash lookup. */
int32_t fastpy_set_contains_fv(FpyDict *set, int32_t tag, int64_t data) {
    FpyValue key; key.tag = tag; key.data.i = data;
    return fastpy_set_contains(set, key);
}

/* Add an element to a set. */
void fastpy_set_add_fv(FpyDict *set, int32_t tag, int64_t data) {
    FpyValue key; key.tag = tag; key.data.i = data;
    FpyValue val = fpy_none();
    fpy_dict_set(set, key, val);
}

/* Remove an element from a set (no error if absent). */
void fastpy_set_discard_fv(FpyDict *set, int32_t tag, int64_t data) {
    FpyValue key; key.tag = tag; key.data.i = data;
    uint64_t h = fpy_hash_value(key);
    int64_t mask = set->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = set->indices[slot];
        if (idx == FPY_DICT_EMPTY) return;  /* not found — no error */
        if (idx != FPY_DICT_DELETED && fpy_key_equal(set->keys[idx], key)) {
            /* Decref the removed key */
            FPY_VAL_DECREF(set->keys[idx]);
            /* Mark slot as deleted, compact entries, and rebuild indices. */
            set->indices[slot] = FPY_DICT_DELETED;
            for (int64_t j = idx; j < set->length - 1; j++) {
                set->keys[j] = set->keys[j + 1];
                set->values[j] = set->values[j + 1];
            }
            set->length--;
            fpy_dict_rebuild_indices(set);
            return;
        }
        slot = (slot + 1) & mask;
    }
}

/* Convert a list to a set (dict with keys from list, values = None). */
FpyDict* fastpy_set_from_list(FpyList *list) {
    FpyDict *set = fpy_dict_new(list->length > 4 ? list->length : 4);
    FpyValue none_val = fpy_none();
    for (int64_t i = 0; i < list->length; i++) {
        fpy_dict_set(set, list->items[i], none_val);
    }
    return set;
}

/* Extract set keys as a list (for sorted(), iteration, etc.). */
FpyList* fastpy_set_to_list(FpyDict *set) {
    return fastpy_dict_keys(set);
}

/* Set union: a | b → new set containing elements from both. */
FpyDict* fastpy_set_union(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length + b->length);
    FpyValue none_val = fpy_none();
    for (int64_t i = 0; i < a->length; i++)
        fpy_dict_set(result, a->keys[i], none_val);
    for (int64_t i = 0; i < b->length; i++)
        fpy_dict_set(result, b->keys[i], none_val);
    return result;
}

/* Set intersection: a & b → elements in both. */
FpyDict* fastpy_set_intersection(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length < b->length ? a->length : b->length);
    FpyValue none_val = fpy_none();
    for (int64_t i = 0; i < a->length; i++) {
        if (fastpy_set_contains(b, a->keys[i]))
            fpy_dict_set(result, a->keys[i], none_val);
    }
    return result;
}

/* Set difference: a - b → elements in a but not in b. */
FpyDict* fastpy_set_difference(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length);
    FpyValue none_val = fpy_none();
    for (int64_t i = 0; i < a->length; i++) {
        if (!fastpy_set_contains(b, a->keys[i]))
            fpy_dict_set(result, a->keys[i], none_val);
    }
    return result;
}

/* Set symmetric difference: a ^ b → elements in either but not both. */
FpyDict* fastpy_set_symmetric_diff(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length + b->length);
    FpyValue none_val = fpy_none();
    for (int64_t i = 0; i < a->length; i++) {
        if (!fastpy_set_contains(b, a->keys[i]))
            fpy_dict_set(result, a->keys[i], none_val);
    }
    for (int64_t i = 0; i < b->length; i++) {
        if (!fastpy_set_contains(a, b->keys[i]))
            fpy_dict_set(result, b->keys[i], none_val);
    }
    return result;
}

/* set.issubset(other) — True if every element of self is in other */
int32_t fastpy_set_issubset(FpyDict *a, FpyDict *b) {
    for (int64_t i = 0; i < a->length; i++) {
        if (!fastpy_set_contains(b, a->keys[i])) return 0;
    }
    return 1;
}

/* set.issuperset(other) — True if every element of other is in self */
int32_t fastpy_set_issuperset(FpyDict *a, FpyDict *b) {
    return fastpy_set_issubset(b, a);
}

/* set.isdisjoint(other) — True if no common elements */
int32_t fastpy_set_isdisjoint(FpyDict *a, FpyDict *b) {
    for (int64_t i = 0; i < a->length; i++) {
        if (fastpy_set_contains(b, a->keys[i])) return 0;
    }
    return 1;
}

/* set.copy() — shallow copy */
FpyDict* fastpy_set_copy(FpyDict *set) {
    FpyDict *result = fpy_dict_new(set->length > 4 ? set->length : 4);
    for (int64_t i = 0; i < set->length; i++) {
        fpy_dict_set(result, set->keys[i], set->values[i]);
    }
    return result;
}

/* set.clear() — remove all elements */
void fastpy_set_clear(FpyDict *set) {
    set->length = 0;
    /* Reset hash indices to all -1 (FPY_DICT_EMPTY) */
    if (set->indices) {
        memset(set->indices, 0xFF, set->table_size * sizeof(int64_t));
    }
}

/* set.pop() — remove and return an arbitrary element (via out params) */
void fastpy_set_pop_fv(FpyDict *set, int32_t *out_tag, int64_t *out_data) {
    if (set->length == 0) {
        fastpy_raise(FPY_EXC_KEYERROR, "pop from an empty set");
        *out_tag = 0; *out_data = 0;
        return;
    }
    FpyValue key = set->keys[set->length - 1];
    set->length--;
    *out_tag = key.tag;
    *out_data = key.data.i;
}

/* set.update(other) — add all elements from other */
void fastpy_set_update(FpyDict *a, FpyDict *b) {
    for (int64_t i = 0; i < b->length; i++) {
        if (!fastpy_set_contains(a, b->keys[i])) {
            fpy_dict_set(a, b->keys[i], b->values[i]);
        }
    }
}

/* Print a set in {a, b, c} format. */
void fastpy_set_print(FpyDict *set) {
    printf("{");
    for (int64_t i = 0; i < set->length; i++) {
        if (i > 0) printf(", ");
        char buf[256];
        fpy_value_repr(set->keys[i], buf, sizeof(buf));
        printf("%s", buf);
    }
    printf("}");}

void fastpy_set_write(FpyDict *set) {
    fastpy_set_print(set);
}

/* --- Closure support ---
 * FpyClosure and FPY_CLOSURE_MAGIC are forward-declared at the top of
 * this file for use in fpy_rc_incref/decref. */

/* Check if a pointer is a closure (vs raw function pointer) */
static int fpy_is_closure(void *ptr) {
    /* Closures start with the magic number. Raw function pointers
     * point to executable code which won't start with "CLOS". */
    FpyClosure *c = (FpyClosure*)ptr;
    return c->magic == FPY_CLOSURE_MAGIC;
}

FpyClosure* fastpy_closure_new(void *func, int n_params, int n_captures) {
    FpyClosure *c = (FpyClosure*)malloc(sizeof(FpyClosure));
    c->magic = FPY_CLOSURE_MAGIC;
    c->refcount = 1;
    c->func = func;
    c->n_params = n_params;
    c->n_captures = n_captures;
    c->capture_is_cell = 0;  /* caller sets bits for cell captures */
    return c;
}

/* Mark a capture as a cell pointer (for proper cleanup) */
void fastpy_closure_mark_cell(FpyClosure *c, int index) {
    c->capture_is_cell |= (1 << index);
}

void fastpy_closure_set_capture(FpyClosure *c, int index, int64_t value) {
    c->captures[index] = value;
}

/* Call closure with 0 explicit args + captures */
int64_t fastpy_closure_call0(FpyClosure *c) {
    typedef int64_t (*fn0_t)(void);
    typedef int64_t (*fn1c_t)(int64_t);
    typedef int64_t (*fn2c_t)(int64_t, int64_t);
    typedef int64_t (*fn3c_t)(int64_t, int64_t, int64_t);
    switch (c->n_captures) {
        case 0: return ((fn0_t)c->func)();
        case 1: return ((fn1c_t)c->func)(c->captures[0]);
        case 2: return ((fn2c_t)c->func)(c->captures[0], c->captures[1]);
        case 3: return ((fn3c_t)c->func)(c->captures[0], c->captures[1], c->captures[2]);
        default: return 0;
    }
}

/* Call closure with 1 explicit arg + captures */
int64_t fastpy_closure_call1(FpyClosure *c, int64_t a) {
    typedef int64_t (*fn1_t)(int64_t);
    typedef int64_t (*fn2c_t)(int64_t, int64_t);
    typedef int64_t (*fn3c_t)(int64_t, int64_t, int64_t);
    typedef int64_t (*fn4c_t)(int64_t, int64_t, int64_t, int64_t);
    switch (c->n_captures) {
        case 0: return ((fn1_t)c->func)(a);
        case 1: return ((fn2c_t)c->func)(a, c->captures[0]);
        case 2: return ((fn3c_t)c->func)(a, c->captures[0], c->captures[1]);
        case 3: return ((fn4c_t)c->func)(a, c->captures[0], c->captures[1], c->captures[2]);
        default: return 0;
    }
}

/* Call closure with 2 explicit args + captures */
int64_t fastpy_closure_call2(FpyClosure *c, int64_t a, int64_t b) {
    typedef int64_t (*fn2_t)(int64_t, int64_t);
    typedef int64_t (*fn3c_t)(int64_t, int64_t, int64_t);
    typedef int64_t (*fn4c_t)(int64_t, int64_t, int64_t, int64_t);
    typedef int64_t (*fn5c_t)(int64_t, int64_t, int64_t, int64_t, int64_t);
    switch (c->n_captures) {
        case 0: return ((fn2_t)c->func)(a, b);
        case 1: return ((fn3c_t)c->func)(a, b, c->captures[0]);
        case 2: return ((fn4c_t)c->func)(a, b, c->captures[0], c->captures[1]);
        case 3: return ((fn5c_t)c->func)(a, b, c->captures[0], c->captures[1], c->captures[2]);
        default: return 0;
    }
}

/* Call closure with args passed as a list (for *args unpacking).
 * Extracts elements from the list, combines with captures, and
 * dispatches to the underlying function pointer. Supports up to
 * 4 total args (explicit + captures). */
int64_t fastpy_closure_call_list(void *closure, void *args_list) {
    FpyClosure *c = (FpyClosure *)closure;
    FpyList *args = (FpyList *)args_list;
    int64_t n_args = args ? args->length : 0;
    int64_t n_caps = c->n_captures;
    int64_t total = n_args + n_caps;

    /* Extract list elements as i64 */
    int64_t a[4] = {0, 0, 0, 0};
    for (int64_t i = 0; i < n_args && i < 4; i++) {
        a[i] = args->items[i].data.i;
    }

    /* Build combined args: [list_elems..., captures...] */
    int64_t all[8];
    for (int64_t i = 0; i < n_args && i < 4; i++) all[i] = a[i];
    for (int64_t i = 0; i < n_caps && (n_args + i) < 8; i++)
        all[n_args + i] = c->captures[i];

    /* Dispatch by total arg count */
    typedef int64_t (*fn0_t)(void);
    typedef int64_t (*fn1_t)(int64_t);
    typedef int64_t (*fn2_t)(int64_t, int64_t);
    typedef int64_t (*fn3_t)(int64_t, int64_t, int64_t);
    typedef int64_t (*fn4_t)(int64_t, int64_t, int64_t, int64_t);
    typedef int64_t (*fn5_t)(int64_t, int64_t, int64_t, int64_t, int64_t);

    switch (total) {
        case 0: return ((fn0_t)c->func)();
        case 1: return ((fn1_t)c->func)(all[0]);
        case 2: return ((fn2_t)c->func)(all[0], all[1]);
        case 3: return ((fn3_t)c->func)(all[0], all[1], all[2]);
        case 4: return ((fn4_t)c->func)(all[0], all[1], all[2], all[3]);
        case 5: return ((fn5_t)c->func)(all[0], all[1], all[2], all[3], all[4]);
        default: return 0;
    }
}

/* --- enumerate and zip --- */

/* enumerate(list) -> list of [index, element] pairs */
FpyList* fastpy_enumerate(FpyList *list, int64_t start) {
    FpyList *result = fpy_list_new(list->length);
    for (int64_t i = 0; i < list->length; i++) {
        FpyList *pair = fpy_list_new(2);
        pair->is_tuple = 1;
        fpy_list_append(pair, fpy_int(start + i));
        fpy_list_append(pair, list->items[i]);
        fpy_list_append(result, fpy_list(pair));
    }
    return result;
}

/* zip(list_a, list_b) -> list of (a, b) tuples */
FpyList* fastpy_zip(FpyList *a, FpyList *b) {
    int64_t len = a->length < b->length ? a->length : b->length;
    FpyList *result = fpy_list_new(len);
    for (int64_t i = 0; i < len; i++) {
        FpyList *pair = fpy_list_new(2);
        pair->is_tuple = 1;
        fpy_list_append(pair, a->items[i]);
        fpy_list_append(pair, b->items[i]);
        fpy_list_append(result, fpy_list(pair));
    }
    return result;
}

FpyList* fastpy_zip3(FpyList *a, FpyList *b, FpyList *c) {
    int64_t len = a->length;
    if (b->length < len) len = b->length;
    if (c->length < len) len = c->length;
    FpyList *result = fpy_list_new(len);
    for (int64_t i = 0; i < len; i++) {
        FpyList *t = fpy_list_new(3);
        t->is_tuple = 1;
        fpy_list_append(t, a->items[i]);
        fpy_list_append(t, b->items[i]);
        fpy_list_append(t, c->items[i]);
        fpy_list_append(result, fpy_list(t));
    }
    return result;
}

/* --- Mutable closure cells ---
 * FpyCell is forward-declared at the top of this file. */

FpyCell* fastpy_cell_new(int64_t initial) {
    FpyCell *cell = (FpyCell*)malloc(sizeof(FpyCell));
    cell->refcount = 1;
    cell->value = initial;
    return cell;
}

void fastpy_cell_set(FpyCell *cell, int64_t value) {
    cell->value = value;
}

int64_t fastpy_cell_get(FpyCell *cell) {
    return cell->value;
}

/* List pop — remove and return last element */
int64_t fastpy_list_pop_int(FpyList *list) {
    FPY_LOCK(list);
    if (list->length == 0) {
        FPY_UNLOCK(list);
        fastpy_raise(FPY_EXC_INDEXERROR, "pop from empty list");
        return 0;
    }
    list->length--;
    int64_t result = list->items[list->length].data.i;
    FPY_UNLOCK(list);
    return result;
}

int64_t fastpy_list_pop_at(FpyList *list, int64_t index) {
    FPY_LOCK(list);
    if (index < 0) index += list->length;
    if (index < 0 || index >= list->length) {
        FPY_UNLOCK(list);
        fastpy_raise(FPY_EXC_INDEXERROR, "pop index out of range");
        return 0;
    }
    int64_t result = list->items[index].data.i;
    for (int64_t i = index; i < list->length - 1; i++) {
        list->items[i] = list->items[i + 1];
    }
    list->length--;
    FPY_UNLOCK(list);
    return result;
}

void fastpy_list_delete_at(FpyList *list, int64_t index) {
    FPY_LOCK(list);
    if (index < 0) index += list->length;
    if (index < 0 || index >= list->length) {
        FPY_UNLOCK(list);
        fastpy_raise(FPY_EXC_INDEXERROR, "list index out of range");
        return;
    }
    FPY_VAL_DECREF(list->items[index]);
    for (int64_t i = index; i < list->length - 1; i++) {
        list->items[i] = list->items[i + 1];
    }
    list->length--;
    FPY_UNLOCK(list);
}

void fastpy_dict_delete(FpyDict *dict, const char *key) {
    FPY_LOCK(dict);
    FpyValue k = fpy_str(key);
    uint64_t h = fpy_hash_value(k);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);

    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k)) {
            /* Decref the removed key and value */
            FPY_VAL_DECREF(dict->keys[idx]);
            FPY_VAL_DECREF(dict->values[idx]);
            /* Mark slot as deleted and compact the entries array. */
            dict->indices[slot] = FPY_DICT_DELETED;
            /* Shift entries down to keep compact order. */
            for (int64_t j = idx; j < dict->length - 1; j++) {
                dict->keys[j] = dict->keys[j + 1];
                dict->values[j] = dict->values[j + 1];
            }
            dict->length--;
            /* Rebuild indices since entry indices shifted. */
            fpy_dict_rebuild_indices(dict);
            FPY_UNLOCK(dict);
            return;
        }
        slot = (slot + 1) & mask;
    }
    FPY_UNLOCK(dict);
    fastpy_raise(FPY_EXC_KEYERROR, key);
    return;
}

void fastpy_list_remove(FpyList *list, int64_t value) {
    /* Remove first occurrence of value; if not found, raise ValueError (for int tag) */
    FPY_LOCK(list);
    for (int64_t i = 0; i < list->length; i++) {
        if (list->items[i].tag == FPY_TAG_INT && list->items[i].data.i == value) {
            FPY_VAL_DECREF(list->items[i]);
            for (int64_t j = i; j < list->length - 1; j++) {
                list->items[j] = list->items[j + 1];
            }
            list->length--;
            FPY_UNLOCK(list);
            return;
        }
    }
    FPY_UNLOCK(list);
    fastpy_raise(FPY_EXC_VALUEERROR, "list.remove(x): x not in list");
    return;
}

void fastpy_list_remove_str(FpyList *list, const char *value) {
    FPY_LOCK(list);
    for (int64_t i = 0; i < list->length; i++) {
        if (list->items[i].tag == FPY_TAG_STR && strcmp(list->items[i].data.s, value) == 0) {
            FPY_VAL_DECREF(list->items[i]);
            for (int64_t j = i; j < list->length - 1; j++) {
                list->items[j] = list->items[j + 1];
            }
            list->length--;
            FPY_UNLOCK(list);
            return;
        }
    }
    FPY_UNLOCK(list);
    fastpy_raise(FPY_EXC_VALUEERROR, "list.remove(x): x not in list");
    return;
}

void fastpy_list_insert_int(FpyList *list, int64_t index, int64_t value) {
    FPY_LOCK(list);
    int64_t len = list->length;
    if (index < 0) index += len;
    if (index < 0) index = 0;
    if (index > len) index = len;
    /* Ensure capacity — use unlocked append for growth (we hold the lock) */
    FpyValue v = { .tag = FPY_TAG_INT, .data.i = value };
    fpy_list_append_unlocked(list, v);
    /* Shift elements right from index onward */
    for (int64_t i = list->length - 1; i > index; i--) {
        list->items[i] = list->items[i - 1];
    }
    list->items[index] = v;
    FPY_UNLOCK(list);
}

void fastpy_list_insert_str(FpyList *list, int64_t index, const char *value) {
    FPY_LOCK(list);
    int64_t len = list->length;
    if (index < 0) index += len;
    if (index < 0) index = 0;
    if (index > len) index = len;
    FpyValue v = { .tag = FPY_TAG_STR, .data.s = value };
    fpy_list_append_unlocked(list, v);
    for (int64_t i = list->length - 1; i > index; i--) {
        list->items[i] = list->items[i - 1];
    }
    list->items[index] = v;
    FPY_UNLOCK(list);
}

const char* fastpy_dict_pop(FpyDict *dict, const char *key) {
    FPY_LOCK(dict);
    FpyValue k = fpy_str(key);
    uint64_t h = fpy_hash_value(k);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k)) {
            FpyValue v = dict->values[idx];
            const char *result;
            if (v.tag == FPY_TAG_STR) result = v.data.s;
            else if (v.tag == FPY_TAG_INT) {
                char *buf = (char*)malloc(32);
                snprintf(buf, 32, "%lld", (long long)v.data.i);
                result = buf;
            } else {
                result = "";
            }
            /* Decref the key; value ownership transfers to caller */
            FPY_VAL_DECREF(dict->keys[idx]);
            dict->indices[slot] = FPY_DICT_DELETED;
            for (int64_t j = idx; j < dict->length - 1; j++) {
                dict->keys[j] = dict->keys[j + 1];
                dict->values[j] = dict->values[j + 1];
            }
            dict->length--;
            fpy_dict_rebuild_indices(dict);
            FPY_UNLOCK(dict);
            return result;
        }
        slot = (slot + 1) & mask;
    }
    FPY_UNLOCK(dict);
    fastpy_raise(FPY_EXC_KEYERROR, key);
    return NULL;
}

int64_t fastpy_dict_pop_int(FpyDict *dict, const char *key) {
    FPY_LOCK(dict);
    FpyValue k = fpy_str(key);
    uint64_t h = fpy_hash_value(k);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k)) {
            FpyValue v = dict->values[idx];
            int64_t result = (v.tag == FPY_TAG_INT) ? v.data.i : 0;
            /* Decref the key; value ownership transfers to caller */
            FPY_VAL_DECREF(dict->keys[idx]);
            dict->indices[slot] = FPY_DICT_DELETED;
            for (int64_t j = idx; j < dict->length - 1; j++) {
                dict->keys[j] = dict->keys[j + 1];
                dict->values[j] = dict->values[j + 1];
            }
            dict->length--;
            fpy_dict_rebuild_indices(dict);
            FPY_UNLOCK(dict);
            return result;
        }
        slot = (slot + 1) & mask;
    }
    FPY_UNLOCK(dict);
    fastpy_raise(FPY_EXC_KEYERROR, key);
    return 0;
}

/* dict.pop(key, default) — returns FpyValue via out params */
void fastpy_dict_pop_fv(FpyDict *dict, const char *key,
                         int32_t def_tag, int64_t def_data,
                         int32_t *out_tag, int64_t *out_data) {
    FPY_LOCK(dict);
    FpyValue k = fpy_str(key);
    uint64_t h = fpy_hash_value(k);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k)) {
            FpyValue v = dict->values[idx];
            *out_tag = v.tag;
            *out_data = v.data.i;
            FPY_VAL_DECREF(dict->keys[idx]);
            dict->indices[slot] = FPY_DICT_DELETED;
            for (int64_t j = idx; j < dict->length - 1; j++) {
                dict->keys[j] = dict->keys[j + 1];
                dict->values[j] = dict->values[j + 1];
            }
            dict->length--;
            fpy_dict_rebuild_indices(dict);
            FPY_UNLOCK(dict);
            return;
        }
        slot = (slot + 1) & mask;
    }
    FPY_UNLOCK(dict);
    /* Key not found — return default */
    *out_tag = def_tag;
    *out_data = def_data;
}

void fastpy_dict_setdefault_list(FpyDict *dict, const char *key, FpyList *default_val) {
    if (fastpy_dict_has_key(dict, key)) return;
    FpyValue v = { .tag = FPY_TAG_STR, .data.s = (const char*)default_val };
    fpy_dict_set(dict, fpy_str(key), v);
}

void fastpy_dict_setdefault_int(FpyDict *dict, const char *key, int64_t default_val) {
    if (fastpy_dict_has_key(dict, key)) return;
    fpy_dict_set(dict, fpy_str(key), fpy_int(default_val));
}

/* dict.popitem() — remove and return the last inserted key-value pair */
void fastpy_dict_popitem(FpyDict *dict, int32_t *key_tag, int64_t *key_data,
                          int32_t *val_tag, int64_t *val_data) {
    if (dict->length == 0) {
        fastpy_raise(FPY_EXC_KEYERROR, "popitem(): dictionary is empty");
        *key_tag = 0; *key_data = 0; *val_tag = 0; *val_data = 0;
        return;
    }
    int64_t last = dict->length - 1;
    FpyValue k = dict->keys[last];
    FpyValue v = dict->values[last];
    *key_tag = k.tag; *key_data = k.data.i;
    *val_tag = v.tag; *val_data = v.data.i;
    dict->length--;
    fpy_dict_rebuild_indices(dict);
}

void fastpy_divmod(int64_t a, int64_t b, int64_t *q, int64_t *r) {
    /* Python floor division + mod */
    int64_t qq = a / b;
    int64_t rr = a % b;
    if ((rr != 0) && ((rr < 0) != (b < 0))) {
        qq -= 1;
        rr += b;
    }
    *q = qq;
    *r = rr;
}

/* String upper */
const char* fastpy_str_upper(const char *s) {
    size_t len = strlen(s);
    char *result = (char*)malloc(len + 1);
    for (size_t i = 0; i <= len; i++) {
        result[i] = (s[i] >= 'a' && s[i] <= 'z') ? s[i] - 32 : s[i];
    }
    return result;
}

const char* fastpy_str_capitalize(const char *s) {
    size_t len = strlen(s);
    char *result = (char*)malloc(len + 1);
    for (size_t i = 0; i < len; i++) {
        char c = s[i];
        if (i == 0) {
            result[i] = (c >= 'a' && c <= 'z') ? c - 32 : c;
        } else {
            result[i] = (c >= 'A' && c <= 'Z') ? c + 32 : c;
        }
    }
    result[len] = '\0';
    return result;
}

const char* fastpy_str_title(const char *s) {
    size_t len = strlen(s);
    char *result = (char*)malloc(len + 1);
    int in_word = 0;
    for (size_t i = 0; i < len; i++) {
        char c = s[i];
        int is_alpha = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
        if (!is_alpha) {
            result[i] = c;
            in_word = 0;
        } else if (!in_word) {
            result[i] = (c >= 'a' && c <= 'z') ? c - 32 : c;
            in_word = 1;
        } else {
            result[i] = (c >= 'A' && c <= 'Z') ? c + 32 : c;
        }
    }
    result[len] = '\0';
    return result;
}

const char* fastpy_str_swapcase(const char *s) {
    size_t len = strlen(s);
    char *result = (char*)malloc(len + 1);
    for (size_t i = 0; i < len; i++) {
        char c = s[i];
        if (c >= 'a' && c <= 'z') result[i] = c - 32;
        else if (c >= 'A' && c <= 'Z') result[i] = c + 32;
        else result[i] = c;
    }
    result[len] = '\0';
    return result;
}

const char* fastpy_str_center(const char *s, int64_t width) {
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return fpy_strdup(s);
    int64_t total_pad = width - (int64_t)slen;
    int64_t left = total_pad / 2;
    int64_t right = total_pad - left;
    char *result = (char*)malloc(width + 1);
    for (int64_t i = 0; i < left; i++) result[i] = ' ';
    memcpy(result + left, s, slen);
    for (int64_t i = 0; i < right; i++) result[left + slen + i] = ' ';
    result[width] = '\0';
    return result;
}

const char* fastpy_str_ljust(const char *s, int64_t width) {
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return fpy_strdup(s);
    char *result = (char*)malloc(width + 1);
    memcpy(result, s, slen);
    for (int64_t i = slen; i < width; i++) result[i] = ' ';
    result[width] = '\0';
    return result;
}

const char* fastpy_str_rjust(const char *s, int64_t width) {
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return fpy_strdup(s);
    char *result = (char*)malloc(width + 1);
    int64_t pad = width - (int64_t)slen;
    for (int64_t i = 0; i < pad; i++) result[i] = ' ';
    memcpy(result + pad, s, slen);
    result[width] = '\0';
    return result;
}

const char* fastpy_str_zfill(const char *s, int64_t width) {
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return fpy_strdup(s);
    char *result = (char*)malloc(width + 1);
    int64_t pad = width - (int64_t)slen;
    int src_idx = 0;
    int dst_idx = 0;
    /* Preserve leading sign */
    if (s[0] == '-' || s[0] == '+') {
        result[dst_idx++] = s[0];
        src_idx = 1;
    }
    for (int64_t i = 0; i < pad; i++) result[dst_idx++] = '0';
    for (size_t i = src_idx; i < slen; i++) result[dst_idx++] = s[i];
    result[dst_idx] = '\0';
    return result;
}

/* center/ljust/rjust with custom fill character (Python 3.x) */
const char* fastpy_str_center_fill(const char *s, int64_t width, const char *fill) {
    char fc = fill[0];
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return fpy_strdup(s);
    int64_t total_pad = width - (int64_t)slen;
    int64_t left = total_pad / 2;
    int64_t right = total_pad - left;
    char *result = (char*)malloc(width + 1);
    for (int64_t i = 0; i < left; i++) result[i] = fc;
    memcpy(result + left, s, slen);
    for (int64_t i = 0; i < right; i++) result[left + slen + i] = fc;
    result[width] = '\0';
    return result;
}

const char* fastpy_str_ljust_fill(const char *s, int64_t width, const char *fill) {
    char fc = fill[0];
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return fpy_strdup(s);
    char *result = (char*)malloc(width + 1);
    memcpy(result, s, slen);
    for (int64_t i = slen; i < width; i++) result[i] = fc;
    result[width] = '\0';
    return result;
}

const char* fastpy_str_rjust_fill(const char *s, int64_t width, const char *fill) {
    char fc = fill[0];
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return fpy_strdup(s);
    char *result = (char*)malloc(width + 1);
    int64_t pad = width - (int64_t)slen;
    for (int64_t i = 0; i < pad; i++) result[i] = fc;
    memcpy(result + pad, s, slen);
    result[width] = '\0';
    return result;
}

/* str.isupper() / str.islower() */
int fastpy_str_isupper(const char *s) {
    if (!s || !*s) return 0;
    int has_cased = 0;
    for (const char *p = s; *p; p++) {
        if (*p >= 'a' && *p <= 'z') return 0;
        if (*p >= 'A' && *p <= 'Z') has_cased = 1;
    }
    return has_cased;
}

int fastpy_str_islower(const char *s) {
    if (!s || !*s) return 0;
    int has_cased = 0;
    for (const char *p = s; *p; p++) {
        if (*p >= 'A' && *p <= 'Z') return 0;
        if (*p >= 'a' && *p <= 'z') has_cased = 1;
    }
    return has_cased;
}

/* str.istitle() — True if titlecased: each word starts with uppercase, rest lowercase */
int fastpy_str_istitle(const char *s) {
    if (!s || !*s) return 0;
    int has_cased = 0;
    int prev_cased = 0;
    for (const char *p = s; *p; p++) {
        int upper = (*p >= 'A' && *p <= 'Z');
        int lower = (*p >= 'a' && *p <= 'z');
        if (upper) {
            if (prev_cased) return 0;  /* uppercase after cased char */
            has_cased = 1;
            prev_cased = 1;
        } else if (lower) {
            if (!prev_cased) return 0;  /* lowercase at word start */
            has_cased = 1;
            prev_cased = 1;
        } else {
            prev_cased = 0;  /* non-cased char resets word */
        }
    }
    return has_cased;
}

/* str.isidentifier() — True if valid Python identifier (ASCII subset) */
int fastpy_str_isidentifier(const char *s) {
    if (!s || !*s) return 0;
    /* First char: letter or underscore */
    if (!((*s >= 'a' && *s <= 'z') || (*s >= 'A' && *s <= 'Z') || *s == '_'))
        return 0;
    for (const char *p = s + 1; *p; p++) {
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
              (*p >= '0' && *p <= '9') || *p == '_'))
            return 0;
    }
    return 1;
}

/* str.isprintable() — True if all chars are printable (ASCII 0x20-0x7E) */
int fastpy_str_isprintable(const char *s) {
    if (!s) return 1;  /* empty string is printable */
    if (!*s) return 1;
    for (const char *p = s; *p; p++) {
        unsigned char c = (unsigned char)*p;
        if (c < 0x20 || c > 0x7E) return 0;
    }
    return 1;
}

/* str.isdecimal() — True if all chars are decimal digits (ASCII 0-9) */
int fastpy_str_isdecimal(const char *s) {
    if (!s || !*s) return 0;
    for (const char *p = s; *p; p++) {
        if (*p < '0' || *p > '9') return 0;
    }
    return 1;
}

/* str.isnumeric() — True if all chars are numeric (same as isdecimal for ASCII) */
int fastpy_str_isnumeric(const char *s) {
    if (!s || !*s) return 0;
    for (const char *p = s; *p; p++) {
        if (*p < '0' || *p > '9') return 0;
    }
    return 1;
}

/* str.casefold() — aggressive lowercase for caseless matching (ASCII: same as lower) */
const char* fastpy_str_casefold(const char *s) {
    if (!s) return fpy_strdup("");
    size_t len = strlen(s);
    char *result = (char*)malloc(len + 1);
    for (size_t i = 0; i <= len; i++) {
        char c = s[i];
        if (c >= 'A' && c <= 'Z') c = c + ('a' - 'A');
        result[i] = c;
    }
    return result;
}

/* str.expandtabs(tabsize) */
const char* fastpy_str_expandtabs(const char *s, int64_t tabsize) {
    if (!s) return fpy_strdup("");
    /* First pass: count output length */
    size_t out_len = 0;
    size_t col = 0;
    for (const char *p = s; *p; p++) {
        if (*p == '\t') {
            int64_t spaces = tabsize - (int64_t)(col % (size_t)tabsize);
            if (tabsize <= 0) spaces = 0;
            out_len += (size_t)spaces;
            col += (size_t)spaces;
        } else if (*p == '\n' || *p == '\r') {
            out_len++;
            col = 0;
        } else {
            out_len++;
            col++;
        }
    }
    char *result = (char*)malloc(out_len + 1);
    size_t i = 0;
    col = 0;
    for (const char *p = s; *p; p++) {
        if (*p == '\t') {
            int64_t spaces = tabsize - (int64_t)(col % (size_t)tabsize);
            if (tabsize <= 0) spaces = 0;
            for (int64_t j = 0; j < spaces; j++) result[i++] = ' ';
            col += (size_t)spaces;
        } else if (*p == '\n' || *p == '\r') {
            result[i++] = *p;
            col = 0;
        } else {
            result[i++] = *p;
            col++;
        }
    }
    result[i] = '\0';
    return result;
}

/* str.partition(sep) → tuple of (before, sep, after) stored as FpyList */
FpyList* fastpy_str_partition(const char *s, const char *sep) {
    FpyList *result = fpy_list_new(3);
    result->is_tuple = 1;
    const char *found = strstr(s, sep);
    if (found) {
        size_t before_len = found - s;
        size_t sep_len = strlen(sep);
        char *before = (char*)malloc(before_len + 1);
        memcpy(before, s, before_len);
        before[before_len] = '\0';
        const char *after = found + sep_len;
        char *after_copy = fpy_strdup(after);
        char *sep_copy = fpy_strdup(sep);
        fpy_list_append(result, fpy_str(before));
        fpy_list_append(result, fpy_str(sep_copy));
        fpy_list_append(result, fpy_str(after_copy));
    } else {
        fpy_list_append(result, fpy_str(fpy_strdup(s)));
        fpy_list_append(result, fpy_str(fpy_strdup("")));
        fpy_list_append(result, fpy_str(fpy_strdup("")));
    }
    return result;
}

/* str.rpartition(sep) → tuple of (before, sep, after) stored as FpyList */
FpyList* fastpy_str_rpartition(const char *s, const char *sep) {
    FpyList *result = fpy_list_new(3);
    result->is_tuple = 1;
    size_t slen = strlen(s);
    size_t seplen = strlen(sep);
    /* Find last occurrence */
    const char *last = NULL;
    const char *p = s;
    while ((p = strstr(p, sep)) != NULL) {
        last = p;
        p++;
    }
    if (last) {
        size_t before_len = last - s;
        char *before = (char*)malloc(before_len + 1);
        memcpy(before, s, before_len);
        before[before_len] = '\0';
        const char *after = last + seplen;
        fpy_list_append(result, fpy_str(before));
        fpy_list_append(result, fpy_str(fpy_strdup(sep)));
        fpy_list_append(result, fpy_str(fpy_strdup(after)));
    } else {
        fpy_list_append(result, fpy_str(fpy_strdup("")));
        fpy_list_append(result, fpy_str(fpy_strdup("")));
        fpy_list_append(result, fpy_str(fpy_strdup(s)));
    }
    return result;
}

FpyList* fastpy_str_splitlines(const char *s) {
    FpyList *result = fpy_list_new(0);
    size_t start = 0;
    size_t i = 0;
    size_t len = strlen(s);
    while (i < len) {
        if (s[i] == '\n' || s[i] == '\r') {
            size_t line_len = i - start;
            char *line = (char*)malloc(line_len + 1);
            memcpy(line, s + start, line_len);
            line[line_len] = '\0';
            fpy_list_append(result, fpy_str(line));
            if (s[i] == '\r' && i + 1 < len && s[i + 1] == '\n') i += 2;
            else i++;
            start = i;
        } else {
            i++;
        }
    }
    if (start < len) {
        size_t line_len = len - start;
        char *line = (char*)malloc(line_len + 1);
        memcpy(line, s + start, line_len);
        line[line_len] = '\0';
        fpy_list_append(result, fpy_str(line));
    }
    return result;
}

/* str.rsplit(sep, maxsplit) — split from the right */
FpyList* fastpy_str_rsplit(const char *s, const char *sep, int64_t max_split) {
    size_t s_len = strlen(s);
    size_t sep_len = strlen(sep);
    if (sep_len == 0) {
        FpyList *result = fpy_list_new(1);
        fpy_list_append(result, fpy_str(fpy_strdup(s)));
        return result;
    }
    /* Collect all split positions from left, then take rightmost max_split */
    /* Simple approach: find all occurrences, split from right */
    FpyList *parts = fpy_list_new(0);
    /* Find all separator positions */
    size_t *positions = NULL;
    int64_t n_pos = 0;
    const char *p = s;
    while ((p = strstr(p, sep)) != NULL) {
        n_pos++;
        positions = (size_t*)realloc(positions, n_pos * sizeof(size_t));
        positions[n_pos - 1] = p - s;
        p += sep_len;
    }
    if (n_pos == 0 || max_split == 0) {
        fpy_list_append(parts, fpy_str(fpy_strdup(s)));
        free(positions);
        return parts;
    }
    /* Take only the last max_split separators */
    int64_t start_idx = 0;
    if (max_split >= 0 && max_split < n_pos) {
        start_idx = n_pos - max_split;
    }
    /* Build parts: first part is everything before positions[start_idx] */
    size_t seg_start = 0;
    if (start_idx > 0) {
        /* Everything before the first used separator */
        size_t len = positions[start_idx] - 0;
        char *seg = (char*)malloc(len + 1);
        memcpy(seg, s, len);
        seg[len] = '\0';
        fpy_list_append(parts, fpy_str(seg));
        seg_start = positions[start_idx] + sep_len;
    }
    for (int64_t i = start_idx; i < n_pos; i++) {
        if (i == start_idx && start_idx == 0) {
            size_t len = positions[i];
            char *seg = (char*)malloc(len + 1);
            memcpy(seg, s, len);
            seg[len] = '\0';
            fpy_list_append(parts, fpy_str(seg));
            seg_start = positions[i] + sep_len;
        } else if (i > start_idx) {
            size_t len = positions[i] - seg_start;
            char *seg = (char*)malloc(len + 1);
            memcpy(seg, s + seg_start, len);
            seg[len] = '\0';
            fpy_list_append(parts, fpy_str(seg));
            seg_start = positions[i] + sep_len;
        }
    }
    /* Remainder after last separator */
    size_t rem_len = s_len - seg_start;
    char *rem = (char*)malloc(rem_len + 1);
    memcpy(rem, s + seg_start, rem_len);
    rem[rem_len] = '\0';
    fpy_list_append(parts, fpy_str(rem));
    free(positions);
    return parts;
}

FpyList* fastpy_str_split_max(const char *s, const char *sep, int64_t max_split) {
    FpyList *result = fpy_list_new(0);
    size_t sep_len = strlen(sep);
    size_t s_len = strlen(s);
    if (sep_len == 0) {
        char *copy = fpy_strdup(s);
        fpy_list_append(result, fpy_str(copy));
        return result;
    }
    const char *p = s;
    const char *end = s + s_len;
    int64_t splits = 0;
    while (p < end) {
        if (max_split >= 0 && splits >= max_split) {
            size_t rest_len = end - p;
            char *seg = (char*)malloc(rest_len + 1);
            memcpy(seg, p, rest_len);
            seg[rest_len] = '\0';
            fpy_list_append(result, fpy_str(seg));
            break;
        }
        const char *q = strstr(p, sep);
        if (!q) {
            size_t rest_len = end - p;
            char *seg = (char*)malloc(rest_len + 1);
            memcpy(seg, p, rest_len);
            seg[rest_len] = '\0';
            fpy_list_append(result, fpy_str(seg));
            break;
        }
        size_t seg_len = q - p;
        char *seg = (char*)malloc(seg_len + 1);
        memcpy(seg, p, seg_len);
        seg[seg_len] = '\0';
        fpy_list_append(result, fpy_str(seg));
        p = q + sep_len;
        splits++;
    }
    return result;
}

/* String replace */
const char* fastpy_str_replace(const char *s, const char *old, const char *new_str) {
    size_t s_len = strlen(s);
    size_t old_len = strlen(old);
    size_t new_len = strlen(new_str);
    if (old_len == 0) return s;

    /* Count occurrences */
    int count = 0;
    const char *p = s;
    while ((p = strstr(p, old)) != NULL) { count++; p += old_len; }

    size_t result_len = s_len + count * (new_len - old_len);
    char *result = (char*)malloc(result_len + 1);
    char *dst = result;
    p = s;
    while (*p) {
        if (strncmp(p, old, old_len) == 0) {
            memcpy(dst, new_str, new_len);
            dst += new_len;
            p += old_len;
        } else {
            *dst++ = *p++;
        }
    }
    *dst = '\0';
    return result;
}

/* str.replace(old, new, count) — replace at most count occurrences */
const char* fastpy_str_replace_count(const char *s, const char *old,
                                      const char *new_str, int64_t max_count) {
    size_t s_len = strlen(s);
    size_t old_len = strlen(old);
    size_t new_len = strlen(new_str);
    if (old_len == 0 || max_count == 0) {
        char *copy = (char*)malloc(s_len + 1);
        memcpy(copy, s, s_len + 1);
        return copy;
    }
    /* Count occurrences (up to max_count) */
    int64_t count = 0;
    const char *p = s;
    while ((p = strstr(p, old)) != NULL && count < max_count) {
        count++; p += old_len;
    }
    size_t result_len = s_len + count * (new_len - old_len);
    char *result = (char*)malloc(result_len + 1);
    char *dst = result;
    int64_t replacements = 0;
    p = s;
    while (*p) {
        if (replacements < max_count && strncmp(p, old, old_len) == 0) {
            memcpy(dst, new_str, new_len);
            dst += new_len;
            p += old_len;
            replacements++;
        } else {
            *dst++ = *p++;
        }
    }
    *dst = '\0';
    return result;
}

/* String startswith */
int fastpy_str_startswith(const char *s, const char *prefix) {
    return strncmp(s, prefix, strlen(prefix)) == 0;
}

/* String endswith */
int fastpy_str_endswith(const char *s, const char *suffix) {
    size_t s_len = strlen(s);
    size_t suf_len = strlen(suffix);
    if (suf_len > s_len) return 0;
    return strcmp(s + s_len - suf_len, suffix) == 0;
}

/* String removeprefix (Python 3.9+) */
const char* fastpy_str_removeprefix(const char *s, const char *prefix) {
    size_t plen = strlen(prefix);
    if (strncmp(s, prefix, plen) == 0) {
        size_t slen = strlen(s);
        size_t rlen = slen - plen;
        char *result = (char*)malloc(rlen + 1);
        memcpy(result, s + plen, rlen);
        result[rlen] = '\0';
        return result;
    }
    /* No match — return a copy of the original string */
    size_t slen = strlen(s);
    char *copy = (char*)malloc(slen + 1);
    memcpy(copy, s, slen + 1);
    return copy;
}

/* String removesuffix (Python 3.9+) */
const char* fastpy_str_removesuffix(const char *s, const char *suffix) {
    size_t slen = strlen(s);
    size_t suflen = strlen(suffix);
    if (suflen <= slen && strcmp(s + slen - suflen, suffix) == 0) {
        size_t rlen = slen - suflen;
        char *result = (char*)malloc(rlen + 1);
        memcpy(result, s, rlen);
        result[rlen] = '\0';
        return result;
    }
    /* No match — return a copy of the original string */
    char *copy = (char*)malloc(slen + 1);
    memcpy(copy, s, slen + 1);
    return copy;
}

/* String contains (for 'in' operator) */
int fastpy_str_contains(const char *haystack, const char *needle) {
    return strstr(haystack, needle) != NULL;
}

/* Dict get with default — returns value as string, or default if key not found */
const char* fastpy_dict_get_default(FpyDict *dict, const char *key, const char *default_val) {
    FpyValue k = fpy_str(key);
    uint64_t h = fpy_hash_value(k);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) return default_val;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k)) {
            FpyValue v = dict->values[idx];
            switch (v.tag) {
                case FPY_TAG_STR: return v.data.s;
                case FPY_TAG_INT: {
                    char *buf = (char*)malloc(32);
                    snprintf(buf, 32, "%lld", (long long)v.data.i);
                    return buf;
                }
                default: return "<value>";
            }
        }
        slot = (slot + 1) & mask;
    }
}

/* Dict has key */
int fastpy_dict_has_key(FpyDict *dict, const char *key) {
    FpyValue k = fpy_str(key);
    uint64_t h = fpy_hash_value(k);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) return 0;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k))
            return 1;
        slot = (slot + 1) & mask;
    }
}

/* List index — find first occurrence, return -1 if not found */
int64_t fastpy_list_index(FpyList *list, int64_t value) {
    for (int64_t i = 0; i < list->length; i++) {
        if (list->items[i].tag == FPY_TAG_INT && list->items[i].data.i == value) {
            return i;
        }
    }
    return -1;
}

/* List index for string values */
int64_t fastpy_list_index_str(FpyList *list, const char *value) {
    for (int64_t i = 0; i < list->length; i++) {
        if (list->items[i].tag == FPY_TAG_STR
            && strcmp(list->items[i].data.s, value) == 0) {
            return i;
        }
    }
    return -1;
}

/* List count — count occurrences */
int64_t fastpy_list_count(FpyList *list, int64_t value) {
    int64_t count = 0;
    for (int64_t i = 0; i < list->length; i++) {
        if (list->items[i].tag == FPY_TAG_INT && list->items[i].data.i == value) {
            count++;
        }
    }
    return count;
}

int64_t fastpy_list_count_str(FpyList *list, const char *value) {
    int64_t count = 0;
    for (int64_t i = 0; i < list->length; i++) {
        if (list->items[i].tag == FPY_TAG_STR
            && strcmp(list->items[i].data.s, value) == 0) {
            count++;
        }
    }
    return count;
}

/* String strip */
const char* fastpy_str_strip(const char *s) {
    const char *start = s;
    while (*start == ' ' || *start == '\t' || *start == '\n' || *start == '\r') start++;
    const char *end = s + strlen(s) - 1;
    while (end > start && (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r')) end--;
    size_t len = end - start + 1;
    char *result = (char*)malloc(len + 1);
    memcpy(result, start, len);
    result[len] = '\0';
    return result;
}

const char* fastpy_str_lstrip(const char *s) {
    const char *start = s;
    while (*start == ' ' || *start == '\t' || *start == '\n' || *start == '\r') start++;
    return fpy_strdup(start);
}

const char* fastpy_str_rstrip(const char *s) {
    size_t slen = strlen(s);
    const char *end = s + slen - 1;
    while (end >= s && (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r')) end--;
    size_t len = end - s + 1;
    char *result = (char*)malloc(len + 1);
    memcpy(result, s, len);
    result[len] = '\0';
    return result;
}

const char* fastpy_str_strip_chars(const char *s, const char *chars) {
    const char *start = s;
    while (*start && strchr(chars, *start)) start++;
    const char *end = s + strlen(s) - 1;
    while (end >= start && strchr(chars, *end)) end--;
    size_t len = end - start + 1;
    char *result = (char*)malloc(len + 1);
    memcpy(result, start, len);
    result[len] = '\0';
    return result;
}

const char* fastpy_str_lstrip_chars(const char *s, const char *chars) {
    const char *start = s;
    while (*start && strchr(chars, *start)) start++;
    return fpy_strdup(start);
}

const char* fastpy_str_rstrip_chars(const char *s, const char *chars) {
    size_t slen = strlen(s);
    if (slen == 0) return fpy_strdup(s);
    const char *end = s + slen - 1;
    while (end >= s && strchr(chars, *end)) end--;
    size_t len = end - s + 1;
    char *result = (char*)malloc(len + 1);
    memcpy(result, s, len);
    result[len] = '\0';
    return result;
}

int32_t fastpy_str_isdigit(const char *s) {
    if (!*s) return 0;
    for (const char *p = s; *p; p++) {
        if (*p < '0' || *p > '9') return 0;
    }
    return 1;
}

int32_t fastpy_str_isalpha(const char *s) {
    if (!*s) return 0;
    for (const char *p = s; *p; p++) {
        char c = *p;
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'))) return 0;
    }
    return 1;
}

int32_t fastpy_str_isalnum(const char *s) {
    if (!*s) return 0;
    for (const char *p = s; *p; p++) {
        char c = *p;
        int is_alpha = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
        int is_digit = (c >= '0' && c <= '9');
        if (!is_alpha && !is_digit) return 0;
    }
    return 1;
}

int32_t fastpy_str_isspace(const char *s) {
    if (!*s) return 0;
    for (const char *p = s; *p; p++) {
        char c = *p;
        if (c != ' ' && c != '\t' && c != '\n' && c != '\r') return 0;
    }
    return 1;
}

const char* fastpy_chr(int64_t code) {
    /* Only ASCII — no Unicode support yet */
    char *result = (char*)malloc(2);
    result[0] = (char)(code & 0xff);
    result[1] = '\0';
    return result;
}

int64_t fastpy_ord(const char *s) {
    return (int64_t)(unsigned char)s[0];
}

int64_t fastpy_str_to_int(const char *s) {
    if (!s) {
        fastpy_raise(FPY_EXC_VALUEERROR,
                     "invalid literal for int()");
        return 0;
    }
    /* Skip leading/trailing whitespace (Python allows this) */
    const char *p = s;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    const char *start = p;
    if (*p == '+' || *p == '-') p++;
    /* Must have at least one digit */
    if (*p < '0' || *p > '9') {
        /* Allocate a persistent error message matching CPython's format */
        char *msg = (char*)malloc(64 + strlen(s));
        snprintf(msg, 64 + strlen(s),
                 "invalid literal for int() with base 10: '%s'", s);
        fastpy_raise(FPY_EXC_VALUEERROR, msg);
        return 0;
    }
    char *end;
    int64_t result = (int64_t)strtoll(start, &end, 10);
    /* Check for trailing garbage (other than whitespace) */
    while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r') end++;
    if (*end != '\0') {
        char *msg = (char*)malloc(64 + strlen(s));
        snprintf(msg, 64 + strlen(s),
                 "invalid literal for int() with base 10: '%s'", s);
        fastpy_raise(FPY_EXC_VALUEERROR, msg);
        return 0;
    }
    return result;
}

int64_t fastpy_str_to_int_base(const char *s, int64_t base) {
    if (!s || base < 2 || base > 36) {
        fastpy_raise(FPY_EXC_VALUEERROR, "invalid literal for int()");
        return 0;
    }
    const char *p = s;
    while (*p == ' ' || *p == '\t') p++;
    char *end;
    int64_t result = (int64_t)strtoll(p, &end, (int)base);
    while (*end == ' ' || *end == '\t') end++;
    if (*end != '\0') {
        char *msg = (char*)malloc(64 + strlen(s));
        snprintf(msg, 64 + strlen(s),
                 "invalid literal for int() with base %lld: '%s'",
                 (long long)base, s);
        fastpy_raise(FPY_EXC_VALUEERROR, msg);
        return 0;
    }
    return result;
}

double fastpy_str_to_float(const char *s) {
    if (!s) {
        fastpy_raise(FPY_EXC_VALUEERROR,
                     "could not convert string to float");
        return 0.0;
    }
    const char *p = s;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (*p == '\0') {
        char *msg = (char*)malloc(64 + strlen(s));
        snprintf(msg, 64 + strlen(s),
                 "could not convert string to float: '%s'", s);
        fastpy_raise(FPY_EXC_VALUEERROR, msg);
        return 0.0;
    }
    char *end;
    double result = strtod(p, &end);
    while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r') end++;
    if (*end != '\0' || end == p) {
        char *msg = (char*)malloc(64 + strlen(s));
        snprintf(msg, 64 + strlen(s),
                 "could not convert string to float: '%s'", s);
        fastpy_raise(FPY_EXC_VALUEERROR, msg);
        return 0.0;
    }
    return result;
}

const char* fastpy_hex(int64_t value) {
    char *buf = (char*)malloc(32);
    if (value < 0) {
        snprintf(buf, 32, "-0x%llx", (long long)(-value));
    } else {
        snprintf(buf, 32, "0x%llx", (long long)value);
    }
    return buf;
}

const char* fastpy_oct(int64_t value) {
    char *buf = (char*)malloc(32);
    if (value < 0) {
        snprintf(buf, 32, "-0o%llo", (long long)(-value));
    } else {
        snprintf(buf, 32, "0o%llo", (long long)value);
    }
    return buf;
}

const char* fastpy_bin(int64_t value) {
    char *buf = (char*)malloc(80);
    int neg = value < 0;
    uint64_t v = neg ? (uint64_t)(-value) : (uint64_t)value;
    char tmp[70];
    int i = 0;
    if (v == 0) {
        tmp[i++] = '0';
    } else {
        while (v > 0) {
            tmp[i++] = (char)('0' + (v & 1));
            v >>= 1;
        }
    }
    int out = 0;
    if (neg) buf[out++] = '-';
    buf[out++] = '0';
    buf[out++] = 'b';
    while (i > 0) buf[out++] = tmp[--i];
    buf[out] = '\0';
    return buf;
}

int64_t fastpy_round(double value) {
    /* Python uses banker's rounding (round half to even) */
    double r = value;
    if (r >= 0) {
        double f = r - (int64_t)r;  /* fractional part */
        int64_t i = (int64_t)r;
        if (f > 0.5) return i + 1;
        if (f < 0.5) return i;
        /* f == 0.5: round to even */
        return (i % 2 == 0) ? i : i + 1;
    } else {
        double f = (int64_t)r - r;
        int64_t i = (int64_t)r;
        if (f > 0.5) return i - 1;
        if (f < 0.5) return i;
        return (i % 2 == 0) ? i : i - 1;
    }
}

double fastpy_round_ndigits(double value, int64_t ndigits) {
    /* Python round with ndigits: returns float */
    double mult = 1.0;
    for (int64_t i = 0; i < ndigits; i++) mult *= 10.0;
    for (int64_t i = 0; i < -ndigits; i++) mult /= 10.0;
    double scaled = value * mult;
    /* Banker's rounding on the scaled value */
    double r_int;
    double frac = modf(scaled, &r_int);
    if (frac > 0.5) r_int += 1;
    else if (frac < -0.5) r_int -= 1;
    else if (frac == 0.5) {
        if (((int64_t)r_int) % 2 != 0) r_int += 1;
    } else if (frac == -0.5) {
        if (((int64_t)r_int) % 2 != 0) r_int -= 1;
    }
    return r_int / mult;
}

/* C-style string formatting: "fmt" % (args...).
   We only support %s, %d, %f, %%. The args argument is an FpyList. */
const char* fastpy_str_format_percent(const char *fmt, FpyList *args) {
    size_t cap = strlen(fmt) + 256;
    char *buf = (char*)malloc(cap);
    size_t out = 0;
    int64_t arg_idx = 0;
    int n_args = args ? (int)args->length : 0;

    for (size_t i = 0; fmt[i]; i++) {
        if (fmt[i] != '%') {
            if (out + 1 >= cap) { cap *= 2; buf = (char*)realloc(buf, cap); }
            buf[out++] = fmt[i];
            continue;
        }
        /* Parse Python's %[flags][width][.precision]type format:
         *   flags:     -+ 0#
         *   width:     digits
         *   precision: . digits
         *   type:      s, d, i, f, F, e, E, g, G, x, X, o, %
         * We reconstruct the spec into a local buffer and hand it to
         * snprintf with the correctly-typed argument. */
        char spec_buf[32];
        size_t s_out = 0;
        spec_buf[s_out++] = '%';
        size_t j = i + 1;
        /* flags */
        while (fmt[j] == '-' || fmt[j] == '+' || fmt[j] == ' '
               || fmt[j] == '0' || fmt[j] == '#') {
            if (s_out < sizeof(spec_buf) - 1) spec_buf[s_out++] = fmt[j];
            j++;
        }
        /* width */
        while (fmt[j] >= '0' && fmt[j] <= '9') {
            if (s_out < sizeof(spec_buf) - 1) spec_buf[s_out++] = fmt[j];
            j++;
        }
        /* precision */
        if (fmt[j] == '.') {
            if (s_out < sizeof(spec_buf) - 1) spec_buf[s_out++] = fmt[j];
            j++;
            while (fmt[j] >= '0' && fmt[j] <= '9') {
                if (s_out < sizeof(spec_buf) - 1) spec_buf[s_out++] = fmt[j];
                j++;
            }
        }
        char type = fmt[j];
        /* The consumed characters are from fmt[i+1] to fmt[j] inclusive.
         * After processing, advance i to j so the outer loop's i++ moves
         * past the full spec. */
        if (type == '%') {
            if (out + 1 >= cap) { cap *= 2; buf = (char*)realloc(buf, cap); }
            buf[out++] = '%';
            i = j;
            continue;
        }
        if (arg_idx >= n_args) {
            /* No arg — emit raw spec and move on */
            while ((size_t)(out + s_out + 1) >= cap) { cap *= 2; buf = (char*)realloc(buf, cap); }
            memcpy(buf + out, spec_buf, s_out);
            out += s_out;
            if (type) { buf[out++] = type; }
            i = j;
            continue;
        }
        FpyValue v = args->items[arg_idx++];
        char tmp[256];
        int tlen = 0;
        if (type == 's') {
            spec_buf[s_out++] = 's';
            spec_buf[s_out] = '\0';
            const char *s = (v.tag == FPY_TAG_STR) ? v.data.s : "";
            tlen = snprintf(tmp, sizeof(tmp), spec_buf, s);
        } else if (type == 'd' || type == 'i') {
            /* Use %lld for int64 */
            spec_buf[s_out++] = 'l';
            spec_buf[s_out++] = 'l';
            spec_buf[s_out++] = 'd';
            spec_buf[s_out] = '\0';
            int64_t n = (v.tag == FPY_TAG_INT || v.tag == FPY_TAG_BOOL)
                      ? (v.tag == FPY_TAG_BOOL ? v.data.b : v.data.i)
                      : (v.tag == FPY_TAG_FLOAT ? (int64_t)v.data.f : 0);
            tlen = snprintf(tmp, sizeof(tmp), spec_buf, (long long)n);
        } else if (type == 'f' || type == 'F'
                   || type == 'e' || type == 'E'
                   || type == 'g' || type == 'G') {
            spec_buf[s_out++] = type;
            spec_buf[s_out] = '\0';
            double f = (v.tag == FPY_TAG_FLOAT) ? v.data.f
                     : (v.tag == FPY_TAG_INT) ? (double)v.data.i
                     : (v.tag == FPY_TAG_BOOL) ? (double)v.data.b : 0.0;
            tlen = snprintf(tmp, sizeof(tmp), spec_buf, f);
        } else if (type == 'x' || type == 'X' || type == 'o') {
            spec_buf[s_out++] = 'l';
            spec_buf[s_out++] = 'l';
            spec_buf[s_out++] = type;
            spec_buf[s_out] = '\0';
            int64_t n = (v.tag == FPY_TAG_INT || v.tag == FPY_TAG_BOOL)
                      ? (v.tag == FPY_TAG_BOOL ? v.data.b : v.data.i) : 0;
            tlen = snprintf(tmp, sizeof(tmp), spec_buf, (long long)n);
        } else if (type == 'c') {
            spec_buf[s_out++] = 'c';
            spec_buf[s_out] = '\0';
            int n = 0;
            if (v.tag == FPY_TAG_INT) n = (int)v.data.i;
            else if (v.tag == FPY_TAG_STR && v.data.s && v.data.s[0])
                n = (unsigned char)v.data.s[0];
            tlen = snprintf(tmp, sizeof(tmp), spec_buf, n);
        } else {
            /* Unknown — emit raw spec */
            while ((size_t)(out + s_out + 2) >= cap) { cap *= 2; buf = (char*)realloc(buf, cap); }
            memcpy(buf + out, spec_buf, s_out);
            out += s_out;
            if (type) { buf[out++] = type; }
            i = j;
            continue;
        }
        if (tlen < 0) tlen = 0;
        while ((size_t)(out + tlen + 1) >= cap) { cap *= 2; buf = (char*)realloc(buf, cap); }
        memcpy(buf + out, tmp, tlen);
        out += tlen;
        i = j;
    }
    buf[out] = '\0';
    return buf;
}

const char* fastpy_str_repr(const char *s) {
    /* Wrap in single quotes with escapes for common chars */
    size_t len = strlen(s);
    char *buf = (char*)malloc(len * 2 + 3);
    int out = 0;
    buf[out++] = '\'';
    for (size_t i = 0; i < len; i++) {
        char c = s[i];
        if (c == '\\' || c == '\'') {
            buf[out++] = '\\';
            buf[out++] = c;
        } else if (c == '\n') {
            buf[out++] = '\\'; buf[out++] = 'n';
        } else if (c == '\t') {
            buf[out++] = '\\'; buf[out++] = 't';
        } else if (c == '\r') {
            buf[out++] = '\\'; buf[out++] = 'r';
        } else {
            buf[out++] = c;
        }
    }
    buf[out++] = '\'';
    buf[out] = '\0';
    return buf;
}

/* List extend — append all elements from another list */
void fastpy_list_extend(FpyList *list, FpyList *other) {
    FPY_LOCK(list);
    for (int64_t i = 0; i < other->length; i++) {
        fpy_list_append_unlocked(list, other->items[i]);
    }
    FPY_UNLOCK(list);
}

/* List sort in place */
void fastpy_list_sort(FpyList *list) {
    FPY_LOCK(list);
    qsort(list->items, list->length, sizeof(FpyValue), fpy_value_compare);
    FPY_UNLOCK(list);
}

/* List reverse in place */
void fastpy_list_reverse(FpyList *list) {
    FPY_LOCK(list);
    for (int64_t i = 0; i < list->length / 2; i++) {
        FpyValue tmp = list->items[i];
        list->items[i] = list->items[list->length - 1 - i];
        list->items[list->length - 1 - i] = tmp;
    }
    FPY_UNLOCK(list);
}

/* Reverse the first `count` elements of a list in place.
 * Used to optimize `a[:k+1] = a[k::-1]` (prefix reverse)
 * without allocating a temporary reversed copy.  O(count/2) swaps. */
void fastpy_list_reverse_prefix(FpyList *list, int64_t count) {
    if (count > list->length) count = list->length;
    if (count <= 1) return;
    FPY_LOCK(list);
    for (int64_t i = 0; i < count / 2; i++) {
        FpyValue tmp = list->items[i];
        list->items[i] = list->items[count - 1 - i];
        list->items[count - 1 - i] = tmp;
    }
    FPY_UNLOCK(list);
}

/* String find — return index of substring, -1 if not found */
int64_t fastpy_str_find(const char *s, const char *sub) {
    const char *p = strstr(s, sub);
    if (p == NULL) return -1;
    return (int64_t)(p - s);
}

int64_t fastpy_str_rfind(const char *s, const char *sub) {
    size_t sub_len = strlen(sub);
    size_t s_len = strlen(s);
    if (sub_len == 0) return (int64_t)s_len;
    if (sub_len > s_len) return -1;
    for (int64_t i = (int64_t)(s_len - sub_len); i >= 0; i--) {
        if (memcmp(s + i, sub, sub_len) == 0) {
            return i;
        }
    }
    return -1;
}

/* str.index(sub) — like find but raises ValueError */
int64_t fastpy_str_index_sub(const char *s, const char *sub) {
    int64_t pos = fastpy_str_find(s, sub);
    if (pos < 0) {
        fastpy_raise(FPY_EXC_VALUEERROR, "substring not found");
    }
    return pos;
}

/* str.rindex(sub) — like rfind but raises ValueError */
int64_t fastpy_str_rindex_sub(const char *s, const char *sub) {
    int64_t pos = fastpy_str_rfind(s, sub);
    if (pos < 0) {
        fastpy_raise(FPY_EXC_VALUEERROR, "substring not found");
    }
    return pos;
}

/* String count — count occurrences of substring */
int64_t fastpy_str_count(const char *s, const char *sub) {
    int64_t count = 0;
    size_t sub_len = strlen(sub);
    if (sub_len == 0) return (int64_t)strlen(s) + 1;
    const char *p = s;
    while ((p = strstr(p, sub)) != NULL) {
        count++;
        p += sub_len;
    }
    return count;
}

/* str.find(sub, start) and str.find(sub, start, end) — search within slice */
int64_t fastpy_str_find_range(const char *s, const char *sub,
                               int64_t start, int64_t end) {
    int64_t s_len = (int64_t)strlen(s);
    /* Clamp start/end like Python */
    if (start < 0) { start += s_len; if (start < 0) start = 0; }
    if (end < 0) { end += s_len; if (end < 0) end = 0; }
    if (end > s_len) end = s_len;
    if (start > end) return -1;
    size_t sub_len = strlen(sub);
    if (sub_len == 0) return start;
    if ((int64_t)sub_len > end - start) return -1;
    for (int64_t i = start; i <= end - (int64_t)sub_len; i++) {
        if (memcmp(s + i, sub, sub_len) == 0) return i;
    }
    return -1;
}

/* str.rfind(sub, start, end) — reverse search within slice */
int64_t fastpy_str_rfind_range(const char *s, const char *sub,
                                int64_t start, int64_t end) {
    int64_t s_len = (int64_t)strlen(s);
    if (start < 0) { start += s_len; if (start < 0) start = 0; }
    if (end < 0) { end += s_len; if (end < 0) end = 0; }
    if (end > s_len) end = s_len;
    if (start > end) return -1;
    size_t sub_len = strlen(sub);
    if (sub_len == 0) return end;
    if ((int64_t)sub_len > end - start) return -1;
    for (int64_t i = end - (int64_t)sub_len; i >= start; i--) {
        if (memcmp(s + i, sub, sub_len) == 0) return i;
    }
    return -1;
}

/* str.index(sub, start, end) — like find_range but raises ValueError */
int64_t fastpy_str_index_sub_range(const char *s, const char *sub,
                                    int64_t start, int64_t end) {
    int64_t pos = fastpy_str_find_range(s, sub, start, end);
    if (pos < 0) fastpy_raise(FPY_EXC_VALUEERROR, "substring not found");
    return pos;
}

/* str.rindex(sub, start, end) — like rfind_range but raises ValueError */
int64_t fastpy_str_rindex_sub_range(const char *s, const char *sub,
                                     int64_t start, int64_t end) {
    int64_t pos = fastpy_str_rfind_range(s, sub, start, end);
    if (pos < 0) fastpy_raise(FPY_EXC_VALUEERROR, "substring not found");
    return pos;
}

/* str.count(sub, start, end) — count occurrences within slice */
int64_t fastpy_str_count_range(const char *s, const char *sub,
                                int64_t start, int64_t end) {
    int64_t s_len = (int64_t)strlen(s);
    if (start < 0) { start += s_len; if (start < 0) start = 0; }
    if (end < 0) { end += s_len; if (end < 0) end = 0; }
    if (end > s_len) end = s_len;
    if (start > end) return 0;
    size_t sub_len = strlen(sub);
    if (sub_len == 0) return end - start + 1;
    int64_t count = 0;
    for (int64_t i = start; i <= end - (int64_t)sub_len; i++) {
        if (memcmp(s + i, sub, sub_len) == 0) {
            count++;
            i += sub_len - 1; /* non-overlapping */
        }
    }
    return count;
}

/* str.startswith(prefix, start, end) — check prefix within slice */
int32_t fastpy_str_startswith_range(const char *s, const char *prefix,
                                     int64_t start, int64_t end) {
    int64_t s_len = (int64_t)strlen(s);
    if (start < 0) { start += s_len; if (start < 0) start = 0; }
    if (end < 0) { end += s_len; if (end < 0) end = 0; }
    if (end > s_len) end = s_len;
    if (start > end) return 0;
    size_t plen = strlen(prefix);
    if ((int64_t)plen > end - start) return 0;
    return memcmp(s + start, prefix, plen) == 0;
}

/* str.endswith(suffix, start, end) — check suffix within slice */
int32_t fastpy_str_endswith_range(const char *s, const char *suffix,
                                   int64_t start, int64_t end) {
    int64_t s_len = (int64_t)strlen(s);
    if (start < 0) { start += s_len; if (start < 0) start = 0; }
    if (end < 0) { end += s_len; if (end < 0) end = 0; }
    if (end > s_len) end = s_len;
    if (start > end) return 0;
    size_t slen = strlen(suffix);
    int64_t slice_len = end - start;
    if ((int64_t)slen > slice_len) return 0;
    return memcmp(s + end - slen, suffix, slen) == 0;
}

/* str.startswith(tuple_of_prefixes) — check any prefix matches */
int32_t fastpy_str_startswith_tuple(const char *s, FpyList *prefixes) {
    for (int64_t i = 0; i < prefixes->length; i++) {
        if (prefixes->items[i].tag == FPY_TAG_STR) {
            const char *prefix = prefixes->items[i].data.s;
            if (strncmp(s, prefix, strlen(prefix)) == 0) return 1;
        }
    }
    return 0;
}

/* str.endswith(tuple_of_suffixes) — check any suffix matches */
int32_t fastpy_str_endswith_tuple(const char *s, FpyList *suffixes) {
    size_t s_len = strlen(s);
    for (int64_t i = 0; i < suffixes->length; i++) {
        if (suffixes->items[i].tag == FPY_TAG_STR) {
            const char *suffix = suffixes->items[i].data.s;
            size_t suf_len = strlen(suffix);
            if (suf_len <= s_len && strcmp(s + s_len - suf_len, suffix) == 0)
                return 1;
        }
    }
    return 0;
}

/* list.index(value, start, stop) — search in range, raise ValueError if not found */
int64_t fastpy_list_index_range(FpyList *list, int64_t value,
                                 int64_t start, int64_t stop) {
    if (start < 0) { start += list->length; if (start < 0) start = 0; }
    if (stop < 0) { stop += list->length; if (stop < 0) stop = 0; }
    if (stop > list->length) stop = list->length;
    for (int64_t i = start; i < stop; i++) {
        if (list->items[i].tag == FPY_TAG_INT && list->items[i].data.i == value) {
            return i;
        }
    }
    fastpy_raise(FPY_EXC_VALUEERROR, "value is not in list");
    return -1;
}

/* list.sort(key=func) — sort using a key function pointer.
 * key_func is a compiled function that takes an FpyValue (tag+data) and returns an FpyValue.
 * We build a temporary key array, sort indices by key, then rearrange. */
typedef struct {
    FpyValue key;
    int64_t index;
} KeyIndexPair;

static int key_index_compare(const void *a, const void *b) {
    const KeyIndexPair *ka = (const KeyIndexPair*)a;
    const KeyIndexPair *kb = (const KeyIndexPair*)b;
    return fpy_value_compare(&ka->key, &kb->key);
}

void fastpy_list_sort_key(FpyList *list,
                           void (*key_func)(int32_t, int64_t, int32_t*, int64_t*)) {
    if (list->length <= 1) return;
    FPY_LOCK(list);
    KeyIndexPair *pairs = (KeyIndexPair*)malloc(list->length * sizeof(KeyIndexPair));
    for (int64_t i = 0; i < list->length; i++) {
        int32_t out_tag; int64_t out_data;
        key_func(list->items[i].tag, list->items[i].data.i, &out_tag, &out_data);
        pairs[i].key.tag = out_tag;
        pairs[i].key.data.i = out_data;
        pairs[i].index = i;
    }
    qsort(pairs, list->length, sizeof(KeyIndexPair), key_index_compare);
    /* Rearrange items in-place using the sorted indices */
    FpyValue *temp = (FpyValue*)malloc(list->length * sizeof(FpyValue));
    for (int64_t i = 0; i < list->length; i++) {
        temp[i] = list->items[pairs[i].index];
    }
    memcpy(list->items, temp, list->length * sizeof(FpyValue));
    free(temp);
    free(pairs);
    FPY_UNLOCK(list);
}

/* bytes.decode() — for ASCII/UTF-8, the bytes *are* the string */
const char* fastpy_bytes_decode(const char *bytes) {
    size_t len = strlen(bytes);
    char *result = (char*)malloc(len + 1);
    memcpy(result, bytes, len + 1);
    return result;
}

/* dict.fromkeys(keys, value) — create dict from iterable of keys */
FpyDict* fastpy_dict_fromkeys(FpyList *keys, int32_t val_tag, int64_t val_data) {
    int64_t cap = keys->length > 4 ? keys->length * 2 : 4;
    FpyDict *d = fpy_dict_new(cap);
    FpyValue val;
    val.tag = val_tag;
    val.data.i = val_data;
    for (int64_t i = 0; i < keys->length; i++) {
        FpyValue key_fv = keys->items[i];
        fpy_dict_set(d, key_fv, val);
    }
    return d;
}

/* dict.fromkeys(keys) — create dict with None values */
FpyDict* fastpy_dict_fromkeys_none(FpyList *keys) {
    return fastpy_dict_fromkeys(keys, FPY_TAG_NONE, 0);
}

/* float.as_integer_ratio() — return (numerator, denominator) as FpyList tuple */
FpyList* fastpy_float_as_integer_ratio(double x) {
    /* Handle special cases */
    if (x != x) { /* NaN */
        fastpy_raise(FPY_EXC_VALUEERROR, "cannot convert NaN to integer ratio");
        return NULL;
    }
    if (x == HUGE_VAL || x == -HUGE_VAL) { /* Inf */
        fastpy_raise(FPY_EXC_VALUEERROR, "cannot convert Infinity to integer ratio");
        return NULL;
    }
    if (x == 0.0) {
        FpyList *result = fpy_list_new(2);
        result->items[0].tag = FPY_TAG_INT;
        result->items[0].data.i = 0;
        result->items[1].tag = FPY_TAG_INT;
        result->items[1].data.i = 1;
        result->length = 2;
        result->is_tuple = 1;
        return result;
    }
    /* Decompose: x = mantissa * 2^exponent */
    int exponent;
    double mantissa = frexp(x, &exponent);
    /* mantissa is in [0.5, 1.0), multiply by 2^53 to get integer */
    /* CPython uses 300 iterations of the "exact" algorithm, but for
     * double precision, 53 bits of mantissa suffice. */
    int64_t numerator = (int64_t)(mantissa * (double)(1LL << 53));
    int64_t denominator = 1;
    exponent -= 53;
    if (exponent > 0) {
        /* numerator * 2^exponent — shift numerator up */
        /* For large exponents, this overflows i64. Cap at reasonable values. */
        if (exponent <= 10) {
            numerator <<= exponent;
        } else {
            /* Fall back: multiply step by step */
            for (int i = 0; i < exponent && i < 62; i++) {
                numerator *= 2;
            }
        }
    } else if (exponent < 0) {
        /* denominator = 2^(-exponent) */
        int neg_exp = -exponent;
        if (neg_exp <= 62) {
            denominator = 1LL << neg_exp;
        } else {
            denominator = 1LL << 62; /* cap */
        }
    }
    /* Simplify by GCD */
    int64_t a = numerator < 0 ? -numerator : numerator;
    int64_t b = denominator;
    while (b) { int64_t t = b; b = a % b; a = t; }
    if (a > 1) { numerator /= a; denominator /= a; }

    FpyList *result = fpy_list_new(2);
    result->items[0].tag = FPY_TAG_INT;
    result->items[0].data.i = numerator;
    result->items[1].tag = FPY_TAG_INT;
    result->items[1].data.i = denominator;
    result->length = 2;
    result->is_tuple = 1;
    return result;
}

/* int.to_bytes(length, byteorder) — convert int to bytes */
const char* fastpy_int_to_bytes(int64_t value, int64_t length,
                                 const char *byteorder) {
    char *result = (char*)malloc(length + 1);
    int big = (strcmp(byteorder, "big") == 0);
    uint64_t uval = (uint64_t)value;
    for (int64_t i = 0; i < length; i++) {
        int64_t idx = big ? (length - 1 - i) : i;
        result[idx] = (char)(uval & 0xFF);
        uval >>= 8;
    }
    result[length] = '\0';
    return result;
}

/* int.from_bytes(bytes, byteorder) — convert bytes to int */
int64_t fastpy_int_from_bytes(const char *bytes, int64_t length,
                               const char *byteorder) {
    int big = (strcmp(byteorder, "big") == 0);
    uint64_t result = 0;
    for (int64_t i = 0; i < length; i++) {
        int64_t idx = big ? i : (length - 1 - i);
        result = (result << 8) | ((uint8_t)bytes[idx]);
    }
    return (int64_t)result;
}

/* str.maketrans(from, to) — create a 257-byte translation table.
 * Byte 0 is a magic marker 'T' (0x54), bytes 1-256 are the mapping for
 * chars 0-255. Default = identity (char maps to itself).
 * This avoids null-byte issues with C string representation. */
const char* fastpy_str_maketrans(const char *from_chars, const char *to_chars) {
    char *table = (char*)malloc(258);
    table[0] = 'T'; /* magic marker */
    for (int i = 0; i < 256; i++) table[i + 1] = (char)i;
    table[257] = '\0';
    size_t len = strlen(from_chars);
    size_t to_len = strlen(to_chars);
    for (size_t i = 0; i < len && i < to_len; i++) {
        table[(unsigned char)from_chars[i] + 1] = to_chars[i];
    }
    return table;
}

/* str.translate(table) — apply a translation table created by maketrans.
 * Table format: byte 0 = 'T' (magic), bytes 1-256 = char mapping. */
const char* fastpy_str_translate(const char *s, const char *table) {
    size_t slen = strlen(s);
    if (table[0] != 'T') {
        /* Not a valid translation table, return copy */
        char *copy = (char*)malloc(slen + 1);
        memcpy(copy, s, slen + 1);
        return copy;
    }
    char *result = (char*)malloc(slen + 1);
    for (size_t i = 0; i < slen; i++) {
        unsigned char c = (unsigned char)s[i];
        result[i] = table[c + 1];
    }
    result[slen] = '\0';
    return result;
}

/* Check if all elements are scalar (int/float/bool/none) — no refcounting needed */
static int fpy_list_all_scalar(FpyList *list) {
    for (int64_t i = 0; i < list->length; i++) {
        int tag = list->items[i].tag;
        if (tag != FPY_TAG_INT && tag != FPY_TAG_FLOAT &&
            tag != FPY_TAG_BOOL && tag != FPY_TAG_NONE)
            return 0;
    }
    return 1;
}

/* List copy — shallow copy of the list.
 * Uses memcpy instead of per-element fpy_list_append. Skips incref
 * entirely for scalar-only lists (int/float/bool/none have no refcount). */
FpyList* fastpy_list_copy(FpyList *list) {
    FpyList *result = fpy_list_new(list->length);
    if (list->length > 0) {
        memcpy(result->items, list->items, list->length * sizeof(FpyValue));
        result->length = list->length;
        if (!fpy_list_all_scalar(list)) {
            for (int64_t i = 0; i < list->length; i++) {
                FPY_VAL_INCREF(result->items[i]);
            }
        }
    }
    result->is_tuple = list->is_tuple;
    return result;
}

/* List clear — remove all items */
void fastpy_list_clear(FpyList *list) {
    FPY_LOCK(list);
    for (int64_t i = 0; i < list->length; i++) {
        FPY_VAL_DECREF(list->items[i]);
    }
    list->length = 0;
    FPY_UNLOCK(list);
}

/* Slice assignment: a[start:stop] = new_values
 * Replaces elements a[start..stop) with elements from new_values.
 * The replacement list can be a different length than the slice. */
void fastpy_list_slice_assign(FpyList *list, int64_t start, int64_t stop,
                               FpyList *new_values) {
    FPY_LOCK(list);
    /* Clamp indices */
    if (start < 0) start += list->length;
    if (stop < 0) stop += list->length;
    if (start < 0) start = 0;
    if (stop > list->length) stop = list->length;
    if (start > stop) start = stop;

    int64_t old_len = stop - start;
    int64_t new_len = new_values->length;
    int64_t diff = new_len - old_len;
    int64_t final_len = list->length + diff;

    /* Decref elements being removed from the old slice region */
    for (int64_t i = start; i < stop; i++) {
        FPY_VAL_DECREF(list->items[i]);
    }

    /* Grow capacity if needed */
    while (list->capacity < final_len) {
        list->capacity = list->capacity * 2;
        list->items = (FpyValue*)realloc(list->items,
            sizeof(FpyValue) * list->capacity);
    }

    /* Shift tail elements */
    if (diff != 0) {
        memmove(&list->items[stop + diff], &list->items[stop],
                sizeof(FpyValue) * (list->length - stop));
    }

    /* Copy new values into the gap and incref each */
    for (int64_t i = 0; i < new_len; i++) {
        FPY_VAL_INCREF(new_values->items[i]);
        list->items[start + i] = new_values->items[i];
    }
    list->length = final_len;
    FPY_UNLOCK(list);
}

/* Set discard — remove element if present, no error if absent */
void fastpy_set_discard(FpyList *set, int64_t value) {
    for (int64_t i = 0; i < set->length; i++) {
        if (set->items[i].tag == FPY_TAG_INT && set->items[i].data.i == value) {
            for (int64_t j = i; j < set->length - 1; j++)
                set->items[j] = set->items[j + 1];
            set->length--;
            return;
        }
    }
}

/* Dict merge — create new dict from two dicts (a | b) */
FpyDict* fastpy_dict_merge(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length + b->length);
    for (int64_t i = 0; i < a->length; i++)
        fpy_dict_set(result, a->keys[i], a->values[i]);
    for (int64_t i = 0; i < b->length; i++)
        fpy_dict_set(result, b->keys[i], b->values[i]);
    return result;
}

/* List concatenation */
FpyList* fastpy_list_concat(FpyList *a, FpyList *b) {
    FpyList *result = fpy_list_new(a->length + b->length);
    for (int64_t i = 0; i < a->length; i++) fpy_list_append(result, a->items[i]);
    for (int64_t i = 0; i < b->length; i++) fpy_list_append(result, b->items[i]);
    return result;
}

/* Apply a format spec like .2f, 5d, <10 to a value.
   Value is passed as string — caller converts first.
   spec_str: the format spec (everything after the colon).
   is_float: 1 if the original value was a float, 0 if int/string. */
const char* fastpy_format_spec_float(double value, const char *spec) {
    /* Parse Python format spec:
     *   [[fill]align][sign][#][0][width][,|_][.precision][type]
     * Supported types: f F e E g G (and default which is 'f' with reasonable
     * precision). */
    int i = 0;
    char fill = ' ';
    char align = '>';  /* default right-align for numbers */
    if (spec[i] != '\0' && (spec[i+1] == '<' || spec[i+1] == '>'
                             || spec[i+1] == '^' || spec[i+1] == '=')) {
        fill = spec[i];
        align = spec[i+1];
        i += 2;
    } else if (spec[i] == '<' || spec[i] == '>' || spec[i] == '^' || spec[i] == '=') {
        align = spec[i];
        i++;
    }
    char sign = '\0';
    if (spec[i] == '+' || spec[i] == '-' || spec[i] == ' ') {
        sign = spec[i];
        i++;
    }
    if (spec[i] == '#') i++;
    if (spec[i] == '0') { fill = '0'; align = '='; i++; }
    int width = 0;
    while (spec[i] >= '0' && spec[i] <= '9') {
        width = width * 10 + (spec[i] - '0');
        i++;
    }
    if (spec[i] == ',' || spec[i] == '_') i++;
    int prec = -1;
    if (spec[i] == '.') {
        i++;
        prec = 0;
        while (spec[i] >= '0' && spec[i] <= '9') {
            prec = prec * 10 + (spec[i] - '0');
            i++;
        }
    }
    char type = spec[i] ? spec[i] : 'f';
    /* Build snprintf format */
    char fmt_buf[32];
    int fb = 0;
    fmt_buf[fb++] = '%';
    if (sign == '+' || sign == ' ') fmt_buf[fb++] = sign;
    if (prec >= 0) {
        fb += snprintf(fmt_buf + fb, sizeof(fmt_buf) - fb, ".%d", prec);
    }
    if (type == 'f' || type == 'F' || type == 'e' || type == 'E'
            || type == 'g' || type == 'G') {
        fmt_buf[fb++] = type;
    } else {
        fmt_buf[fb++] = 'f';
    }
    fmt_buf[fb] = '\0';
    char tmp[128];
    int tlen = snprintf(tmp, sizeof(tmp), fmt_buf, value);
    if (tlen < 0) tlen = 0;
    char *buf = (char*)malloc((width > tlen ? width : tlen) + 1);
    if (tlen >= width) {
        memcpy(buf, tmp, tlen);
        buf[tlen] = '\0';
        return buf;
    }
    int pad = width - tlen;
    int out = 0;
    if (align == '<') {
        memcpy(buf + out, tmp, tlen); out += tlen;
        for (int k = 0; k < pad; k++) buf[out++] = ' ';
    } else if (align == '^') {
        int left = pad / 2, right = pad - left;
        for (int k = 0; k < left; k++) buf[out++] = ' ';
        memcpy(buf + out, tmp, tlen); out += tlen;
        for (int k = 0; k < right; k++) buf[out++] = ' ';
    } else if (align == '=' && (tmp[0] == '-' || tmp[0] == '+')) {
        buf[out++] = tmp[0];
        for (int k = 0; k < pad; k++) buf[out++] = fill;
        memcpy(buf + out, tmp + 1, tlen - 1); out += tlen - 1;
    } else {
        for (int k = 0; k < pad; k++) buf[out++] = fill;
        memcpy(buf + out, tmp, tlen); out += tlen;
    }
    buf[out] = '\0';
    return buf;
}

const char* fastpy_format_spec_int(int64_t value, const char *spec) {
    char *buf = (char*)malloc(64);
    /* Handle widthd, 0widthd */
    int i = 0;
    int zero_pad = 0;
    int left_align = 0;
    char fill = ' ';
    if (spec[i] == '<') { left_align = 1; i++; }
    else if (spec[i] == '>') { i++; }
    else if (spec[i] == '0') { zero_pad = 1; fill = '0'; i++; }
    int width = 0;
    while (spec[i] >= '0' && spec[i] <= '9') {
        width = width * 10 + (spec[i] - '0');
        i++;
    }
    char tmp[32];
    snprintf(tmp, sizeof(tmp), "%lld", (long long)value);
    int len = (int)strlen(tmp);
    if (width <= len) {
        strcpy(buf, tmp);
        return buf;
    }
    int pad = width - len;
    if (left_align) {
        strcpy(buf, tmp);
        for (int p = 0; p < pad; p++) buf[len + p] = ' ';
        buf[width] = '\0';
    } else {
        for (int p = 0; p < pad; p++) buf[p] = fill;
        strcpy(buf + pad, tmp);
    }
    return buf;
}

const char* fastpy_format_spec_str(const char *value, const char *spec) {
    char *buf = (char*)malloc(256);
    int i = 0;
    int left_align = 0;
    char fill = ' ';
    if (spec[i] == '<') { left_align = 1; i++; }
    else if (spec[i] == '>') { i++; }
    int width = 0;
    while (spec[i] >= '0' && spec[i] <= '9') {
        width = width * 10 + (spec[i] - '0');
        i++;
    }
    int len = (int)strlen(value);
    if (width <= len) {
        strcpy(buf, value);
        return buf;
    }
    int pad = width - len;
    if (left_align) {
        strcpy(buf, value);
        for (int p = 0; p < pad; p++) buf[len + p] = fill;
        buf[width] = '\0';
    } else {
        for (int p = 0; p < pad; p++) buf[p] = fill;
        strcpy(buf + pad, value);
    }
    return buf;
}

/* Build a list from range(start, stop, step) */
FpyList* fastpy_range(int64_t start, int64_t stop, int64_t step) {
    FpyList *result = fpy_list_new(0);
    if (step == 0) return result;
    if (step > 0) {
        for (int64_t i = start; i < stop; i += step) {
            FpyValue v = { .tag = FPY_TAG_INT, .data.i = i };
            fpy_list_append(result, v);
        }
    } else {
        for (int64_t i = start; i > stop; i += step) {
            FpyValue v = { .tag = FPY_TAG_INT, .data.i = i };
            fpy_list_append(result, v);
        }
    }
    return result;
}

/* Apply a unary int64->int64 function to each element of a list.
   Assumes list elements are int-tagged. */
FpyList* fastpy_list_map_int(FpyList *lst, void *fn) {
    typedef int64_t (*fn_t)(int64_t);
    fn_t f = (fn_t)fn;
    FpyList *result = fpy_list_new(lst->length);
    for (int64_t i = 0; i < lst->length; i++) {
        int64_t v = (lst->items[i].tag == FPY_TAG_INT) ? lst->items[i].data.i : 0;
        int64_t r = f(v);
        fpy_list_append(result, fpy_int(r));
    }
    return result;
}

/* Filter a list by a predicate (int64->int64 truthy check).
   Assumes list elements are int-tagged. */
FpyList* fastpy_list_filter_int(FpyList *lst, void *fn) {
    typedef int64_t (*fn_t)(int64_t);
    fn_t f = (fn_t)fn;
    FpyList *result = fpy_list_new(0);
    for (int64_t i = 0; i < lst->length; i++) {
        int64_t v = (lst->items[i].tag == FPY_TAG_INT) ? lst->items[i].data.i : 0;
        if (f(v)) {
            fpy_list_append(result, lst->items[i]);
        }
    }
    return result;
}

/* List sorted by key function: key_fn is a function pointer int64_t(int64_t) */
FpyList* fastpy_list_sorted_by_key_int(FpyList *lst, void *key_fn) {
    typedef int64_t (*keyfn_t)(int64_t);
    keyfn_t fn = (keyfn_t)key_fn;
    int64_t n = lst->length;
    FpyList *result = fpy_list_new(n);
    /* Copy elements and compute keys */
    int64_t *keys = (int64_t*)malloc(sizeof(int64_t) * n);
    int64_t *order = (int64_t*)malloc(sizeof(int64_t) * n);
    for (int64_t i = 0; i < n; i++) {
        order[i] = i;
        /* Pass element data (int value or pointer-as-int) to key function */
        keys[i] = fn(lst->items[i].data.i);
    }
    /* Simple insertion sort on order by keys (stable) */
    for (int64_t i = 1; i < n; i++) {
        int64_t cur = order[i];
        int64_t cur_key = keys[cur];
        int64_t j = i - 1;
        while (j >= 0 && keys[order[j]] > cur_key) {
            order[j + 1] = order[j];
            j--;
        }
        order[j + 1] = cur;
    }
    /* Build result list in sorted order */
    for (int64_t i = 0; i < n; i++) {
        fpy_list_append(result, lst->items[order[i]]);
    }
    free(keys);
    free(order);
    return result;
}

/* List sorted by key function returning string: key values are compared
   with strcmp. The key_fn returns a char* (as int64_t). */
FpyList* fastpy_list_sorted_by_key_str(FpyList *lst, void *key_fn) {
    typedef int64_t (*keyfn_t)(int64_t);
    keyfn_t fn = (keyfn_t)key_fn;
    int64_t n = lst->length;
    FpyList *result = fpy_list_new(n);
    const char **keys = (const char**)malloc(sizeof(const char*) * n);
    int64_t *order = (int64_t*)malloc(sizeof(int64_t) * n);
    for (int64_t i = 0; i < n; i++) {
        order[i] = i;
        keys[i] = (const char*)(intptr_t)fn(lst->items[i].data.i);
    }
    /* Stable insertion sort by strcmp */
    for (int64_t i = 1; i < n; i++) {
        int64_t cur = order[i];
        const char *cur_key = keys[cur];
        int64_t j = i - 1;
        while (j >= 0 && strcmp(keys[order[j]], cur_key) > 0) {
            order[j + 1] = order[j];
            j--;
        }
        order[j + 1] = cur;
    }
    for (int64_t i = 0; i < n; i++) {
        fpy_list_append(result, lst->items[order[i]]);
    }
    free(keys);
    free(order);
    return result;
}

/* List equality: element-wise comparison */
int32_t fastpy_list_equal(FpyList *a, FpyList *b) {
    if (a == b) return 1;
    if (!a || !b) return 0;
    if (a->length != b->length) return 0;
    for (int64_t i = 0; i < a->length; i++) {
        FpyValue va = a->items[i];
        FpyValue vb = b->items[i];
        if (va.tag != vb.tag) return 0;
        switch (va.tag) {
            case FPY_TAG_INT:
            case FPY_TAG_BOOL:
                if (va.data.i != vb.data.i) return 0;
                break;
            case FPY_TAG_FLOAT:
                if (va.data.f != vb.data.f) return 0;
                break;
            case FPY_TAG_STR:
                if (strcmp(va.data.s, vb.data.s) != 0) return 0;
                break;
            case FPY_TAG_NONE:
                break;
            case FPY_TAG_LIST:
                /* Recursive equality for nested lists/tuples */
                if (!fastpy_list_equal(va.data.list, vb.data.list)) return 0;
                break;
            default:
                return 0;
        }
    }
    return 1;
}

/* Lexicographic list/tuple comparison. Returns -1, 0, 1.
 * Like strcmp — negative if a<b, zero if equal, positive if a>b.
 * Used for Python-style tuple/list ordering: (1,2) < (1,3) -> -1. */
int64_t fastpy_list_compare(FpyList *a, FpyList *b) {
    if (a == b) return 0;
    if (!a) return -1;
    if (!b) return 1;
    int64_t n = a->length < b->length ? a->length : b->length;
    for (int64_t i = 0; i < n; i++) {
        FpyValue va = a->items[i];
        FpyValue vb = b->items[i];
        /* Mixed-type comparison: numeric types compare as numbers; others
         * first compare by tag (Python would raise TypeError, but we
         * return an ordering to avoid crashing). */
        if (va.tag != vb.tag) {
            /* Coerce int/bool/float to double for numeric compare */
            int num_a = va.tag == FPY_TAG_INT || va.tag == FPY_TAG_BOOL
                        || va.tag == FPY_TAG_FLOAT || va.tag == FPY_TAG_BIGINT;
            int num_b = vb.tag == FPY_TAG_INT || vb.tag == FPY_TAG_BOOL
                        || vb.tag == FPY_TAG_FLOAT || vb.tag == FPY_TAG_BIGINT;
            if (num_a && num_b) {
                /* If either is BigInt, use BigInt comparison */
                if (va.tag == FPY_TAG_BIGINT || vb.tag == FPY_TAG_BIGINT) {
                    extern int fpy_bigint_cmp(FpyBigInt*, FpyBigInt*);
                    extern FpyBigInt* fpy_bigint_from_i64(int64_t);
                    FpyBigInt *ba = va.tag == FPY_TAG_BIGINT
                        ? (FpyBigInt*)(intptr_t)va.data.i
                        : fpy_bigint_from_i64(va.data.i);
                    FpyBigInt *bb = vb.tag == FPY_TAG_BIGINT
                        ? (FpyBigInt*)(intptr_t)vb.data.i
                        : fpy_bigint_from_i64(vb.data.i);
                    int r = fpy_bigint_cmp(ba, bb);
                    if (r != 0) { return r < 0 ? -1 : 1; }
                    continue;
                }
                double fa = va.tag == FPY_TAG_FLOAT ? va.data.f : (double)va.data.i;
                double fb = vb.tag == FPY_TAG_FLOAT ? vb.data.f : (double)vb.data.i;
                if (fa < fb) return -1;
                if (fa > fb) return 1;
                continue;
            }
            return va.tag < vb.tag ? -1 : 1;
        }
        switch (va.tag) {
            case FPY_TAG_INT:
            case FPY_TAG_BOOL:
                if (va.data.i < vb.data.i) return -1;
                if (va.data.i > vb.data.i) return 1;
                break;
            case FPY_TAG_FLOAT:
                if (va.data.f < vb.data.f) return -1;
                if (va.data.f > vb.data.f) return 1;
                break;
            case FPY_TAG_STR: {
                int r = strcmp(va.data.s, vb.data.s);
                if (r < 0) return -1;
                if (r > 0) return 1;
                break;
            }
            case FPY_TAG_NONE:
                break;
            case FPY_TAG_BIGINT: {
                extern int fpy_bigint_cmp(FpyBigInt*, FpyBigInt*);
                int r = fpy_bigint_cmp(
                    (FpyBigInt*)(intptr_t)va.data.i,
                    (FpyBigInt*)(intptr_t)vb.data.i);
                if (r != 0) return r < 0 ? -1 : 1;
                break;
            }
            case FPY_TAG_LIST: {
                int64_t r = fastpy_list_compare(va.data.list, vb.data.list);
                if (r != 0) return r;
                break;
            }
            default:
                break;
        }
    }
    if (a->length < b->length) return -1;
    if (a->length > b->length) return 1;
    return 0;
}

/* Dict equality: two dicts are equal if they have the same keys and values.
 * Compares by iterating the compact key/value arrays. */
int32_t fastpy_dict_equal(FpyDict *a, FpyDict *b) {
    if (a == b) return 1;
    if (!a || !b) return 0;
    if (a->length != b->length) return 0;
    /* For each key in a, check that b has the same key with the same value. */
    for (int64_t i = 0; i < a->length; i++) {
        FpyValue key = a->keys[i];
        /* Look up key in b */
        uint64_t h = fpy_hash_value(key);
        int64_t mask = b->table_size - 1;
        int64_t slot = (int64_t)(h & (uint64_t)mask);
        int found = 0;
        while (1) {
            int64_t idx = b->indices[slot];
            if (idx == FPY_DICT_EMPTY) break;
            if (idx != FPY_DICT_DELETED && fpy_key_equal(b->keys[idx], key)) {
                /* Key found — compare values */
                FpyValue va = a->values[i];
                FpyValue vb = b->values[idx];
                if (va.tag != vb.tag) return 0;
                switch (va.tag) {
                    case FPY_TAG_INT:
                    case FPY_TAG_BOOL:
                        if (va.data.i != vb.data.i) return 0;
                        break;
                    case FPY_TAG_FLOAT:
                        if (va.data.f != vb.data.f) return 0;
                        break;
                    case FPY_TAG_STR:
                        if (strcmp(va.data.s, vb.data.s) != 0) return 0;
                        break;
                    case FPY_TAG_NONE:
                        break;
                    case FPY_TAG_LIST:
                        if (!fastpy_list_equal(va.data.list, vb.data.list)) return 0;
                        break;
                    case FPY_TAG_DICT:
                    case FPY_TAG_SET:
                        if (!fastpy_dict_equal((FpyDict*)va.data.list,
                                               (FpyDict*)vb.data.list)) return 0;
                        break;
                    default:
                        /* For other types, compare raw data (pointer identity) */
                        if (va.data.i != vb.data.i) return 0;
                        break;
                }
                found = 1;
                break;
            }
            slot = (slot + 1) & mask;
        }
        if (!found) return 0;
    }
    return 1;
}

/* Set equality: two sets are equal if they have the same elements.
 * Sets are dict-backed, so this checks that every key in a is in b
 * and the lengths are equal (values are all None — ignore them). */
int32_t fastpy_set_equal(FpyDict *a, FpyDict *b) {
    if (a == b) return 1;
    if (!a || !b) return 0;
    if (a->length != b->length) return 0;
    for (int64_t i = 0; i < a->length; i++) {
        FpyValue key = a->keys[i];
        uint64_t h = fpy_hash_value(key);
        int64_t mask = b->table_size - 1;
        int64_t slot = (int64_t)(h & (uint64_t)mask);
        int found = 0;
        while (1) {
            int64_t idx = b->indices[slot];
            if (idx == FPY_DICT_EMPTY) break;
            if (idx != FPY_DICT_DELETED && fpy_key_equal(b->keys[idx], key)) {
                found = 1;
                break;
            }
            slot = (slot + 1) & mask;
        }
        if (!found) return 0;
    }
    return 1;
}

/* List repetition: [1, 2] * 3 = [1, 2, 1, 2, 1, 2] */
FpyList* fastpy_list_repeat(FpyList *lst, int64_t n) {
    if (n <= 0) return fpy_list_new(0);
    FpyList *result = fpy_list_new(lst->length * n);
    for (int64_t r = 0; r < n; r++) {
        for (int64_t i = 0; i < lst->length; i++) {
            fpy_list_append(result, lst->items[i]);
        }
    }
    return result;
}

/* String comparison: returns 0 if equal, <0 if a<b, >0 if a>b */
int64_t fastpy_str_compare(const char *a, const char *b) {
    return (int64_t)strcmp(a, b);
}

/* Call a raw function pointer (for higher-order functions without closures) */
/* Smart function-pointer calls: auto-detect closures via magic number.
 * If the pointer is a closure struct, delegate to closure_callN.
 * If it's a raw function pointer, call directly. This lets closures
 * and raw function pointers be used interchangeably when passed
 * through capture chains (the 3-level closure problem). */
int64_t fastpy_call_ptr0(void *func) {
    if (fpy_is_closure(func))
        return fastpy_closure_call0((FpyClosure*)func);
    typedef int64_t (*fn_t)(void);
    return ((fn_t)func)();
}

int64_t fastpy_call_ptr1(void *func, int64_t a) {
    if (fpy_is_closure(func))
        return fastpy_closure_call1((FpyClosure*)func, a);
    typedef int64_t (*fn_t)(int64_t);
    return ((fn_t)func)(a);
}

int64_t fastpy_call_ptr2(void *func, int64_t a, int64_t b) {
    if (fpy_is_closure(func))
        return fastpy_closure_call2((FpyClosure*)func, a, b);
    typedef int64_t (*fn_t)(int64_t, int64_t);
    return ((fn_t)func)(a, b);
}

/* Convert dict to string for f-strings */
const char* fastpy_dict_to_str(FpyDict *dict) {
    char *buf = (char*)malloc(4096);
    int pos = 0;
    pos += snprintf(buf + pos, 4096 - pos, "{");
    for (int64_t i = 0; i < dict->length; i++) {
        if (i > 0) pos += snprintf(buf + pos, 4096 - pos, ", ");
        char k[256], v[256];
        fpy_value_repr(dict->keys[i], k, sizeof(k));
        fpy_value_repr(dict->values[i], v, sizeof(v));
        pos += snprintf(buf + pos, 4096 - pos, "%s: %s", k, v);
        if (pos >= 4095) break;
    }
    snprintf(buf + pos, 4096 - pos, "}");
    return buf;
}

void fastpy_dict_write(FpyDict *dict) {
    char buf[4096];
    int pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "{");
    for (int64_t i = 0; i < dict->length; i++) {
        if (i > 0) pos += snprintf(buf + pos, sizeof(buf) - pos, ", ");
        char k[256], v[256];
        fpy_value_repr(dict->keys[i], k, sizeof(k));
        fpy_value_repr(dict->values[i], v, sizeof(v));
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%s: %s", k, v);
        if (pos >= (int)sizeof(buf) - 1) break;
    }
    snprintf(buf + pos, sizeof(buf) - pos, "}");
    printf("%s", buf);
}

/* ================================================================
 * Object system
 * ================================================================ */

/* Global class registry */
FpyClassDef fpy_classes[FPY_MAX_CLASSES];
int fpy_class_count = 0;

int fastpy_register_class(const char *name, int parent_id) {
    int id = fpy_class_count++;
    fpy_classes[id].class_id = id;
    fpy_classes[id].name = name;
    fpy_classes[id].parent_id = parent_id;
    fpy_classes[id].methods = NULL;
    fpy_classes[id].method_count = 0;
    fpy_classes[id].slot_count = 0;
    fpy_classes[id].slot_names = NULL;
    fpy_classes[id].destructor = NULL;
    fpy_classes[id].vtable = NULL;
    fpy_classes[id].vtable_size = 0;
    return id;
}

/* Set the number of pre-declared attribute slots for a class.
 * Called after register_class with the slot count determined at compile time. */
void fastpy_set_class_slot_count(int class_id, int slot_count) {
    fpy_classes[class_id].slot_count = slot_count;
    fpy_classes[class_id].slot_names = (const char**)calloc(
        slot_count, sizeof(const char*));
}

/* Set a destructor callback for a class (e.g., generators with finally blocks).
 * Called before object destruction — if non-NULL, the destructor runs before
 * slots are freed. Zero cost for classes without a destructor (NULL check). */
void fastpy_set_class_destructor(int class_id, void (*dtor)(FpyObj*)) {
    fpy_classes[class_id].destructor = dtor;
}

/* Register a slot's name at a given index. Called once per slot after
 * set_class_slot_count. Lets obj_get_fv/obj_set_fv fall back to slot
 * lookup by name for code that can't statically determine the slot. */
void fastpy_register_slot_name(int class_id, int slot_idx, const char *name) {
    if (slot_idx >= 0 && slot_idx < fpy_classes[class_id].slot_count) {
        fpy_classes[class_id].slot_names[slot_idx] = name;
    }
}

/* Find a slot index by attribute name for a given class.
 * Returns -1 if the name isn't a registered slot. */
static int fpy_find_slot(int class_id, const char *name) {
    FpyClassDef *cls = &fpy_classes[class_id];
    for (int i = 0; i < cls->slot_count; i++) {
        if (cls->slot_names[i] == name
                || (cls->slot_names[i] && strcmp(cls->slot_names[i], name) == 0)) {
            return i;
        }
    }
    return -1;
}

void fastpy_register_method(int class_id, const char *name, void *func,
                            int arg_count, int returns_value) {
    FpyClassDef *cls = &fpy_classes[class_id];
    /* Grow methods array */
    cls->method_count++;
    cls->methods = (FpyMethodDef*)realloc(cls->methods,
        sizeof(FpyMethodDef) * cls->method_count);
    FpyMethodDef *m = &cls->methods[cls->method_count - 1];
    m->name = name;
    m->func = func;
    m->arg_count = arg_count;
    m->returns_value = returns_value;
}

/* Native type.__new__ equivalent: create a class from a namespace dict.
 * This implements the metaclass protocol natively:
 * 1. Register a new class with the given name and parent
 * 2. Extract methods from the namespace dict (callable values)
 * 3. Extract class-level attributes (non-callable values)
 * Returns the new class_id. */
int fastpy_type_new_from_dict(const char *name, int parent_id,
                               FpyDict *namespace) {
    int class_id = fastpy_register_class(name, parent_id);

    /* Scan the namespace dict for methods and attributes */
    for (int64_t i = 0; i < namespace->length; i++) {
        FpyValue key = namespace->keys[i];
        FpyValue val = namespace->values[i];

        /* Only process string-keyed entries */
        if (key.tag != FPY_TAG_STR) continue;
        const char *attr_name = key.data.s;

        /* Skip dunder attrs that aren't methods */
        if (attr_name[0] == '_' && attr_name[1] == '_') {
            /* Keep __init__, __repr__, __str__, etc. */
            if (strcmp(attr_name, "__module__") == 0) continue;
            if (strcmp(attr_name, "__qualname__") == 0) continue;
            if (strcmp(attr_name, "__doc__") == 0) continue;
        }

        /* If the value is an OBJ with closure magic or a function pointer,
         * register it as a method. Otherwise store as class attribute. */
        if (val.tag == FPY_TAG_OBJ) {
            void *ptr = (void*)(intptr_t)val.data.i;
            /* Check for closure magic (FPY_CLOSURE_MAGIC) */
            if (ptr && *(int32_t*)ptr == FPY_CLOSURE_MAGIC) {
                /* It's a closure/function — register as method */
                /* For now, assume 0-arg methods. The actual arg count
                 * will be determined at call time via runtime dispatch. */
                fastpy_register_method(class_id, attr_name, ptr, 0, 1);
                continue;
            }
        }
        if (val.tag == FPY_TAG_INT) {
            /* Could be a function pointer stored as i64.
             * For type_new, we trust the caller to put methods
             * in the dict with the right type. Store as class attr. */
        }
        /* Non-method entry — store in the class's slot system or
         * as a class-level constant. For now, just skip. */
    }

    return class_id;
}

/* Set vtable entry: vtable[slot] = func_ptr for class_id. */
void fastpy_set_vtable_entry(int class_id, int slot, void *func) {
    FpyClassDef *cls = &fpy_classes[class_id];
    if (!cls->vtable) {
        cls->vtable_size = (slot + 1 > 16) ? slot + 1 : 16;
        cls->vtable = (void**)calloc(cls->vtable_size, sizeof(void*));
    }
    if (slot >= cls->vtable_size) {
        int new_size = slot + 16;
        cls->vtable = (void**)realloc(cls->vtable, new_size * sizeof(void*));
        for (int i = cls->vtable_size; i < new_size; i++)
            cls->vtable[i] = NULL;
        cls->vtable_size = new_size;
    }
    cls->vtable[slot] = func;
}

/* Fast O(1) vtable dispatch — returns the function pointer for the
 * given slot on the object's class. Falls back to parent chain. */
void* fastpy_vtable_lookup(FpyObj *obj, int slot) {
    int cid = obj->class_id;
    while (cid >= 0) {
        FpyClassDef *cls = &fpy_classes[cid];
        if (cls->vtable && slot < cls->vtable_size && cls->vtable[slot])
            return cls->vtable[slot];
        cid = cls->parent_id;
    }
    return NULL;
}

/* Find a method on a class or its parents */
FpyMethodDef* fastpy_find_method(int class_id, const char *name) {
    while (class_id >= 0) {
        FpyClassDef *cls = &fpy_classes[class_id];
        for (int i = 0; i < cls->method_count; i++) {
            /* Fast path: identical string pointer (common due to codegen
               deduplication + unnamed_addr). Falls back to strcmp when
               pointers differ (e.g. cross-compilation-unit). */
            if (cls->methods[i].name == name
                    || strcmp(cls->methods[i].name, name) == 0) {
                return &cls->methods[i];
            }
        }
        class_id = cls->parent_id;  /* walk up to parent */
    }
    return NULL;
}

/* Dynamic-attribute side-table helpers. Only used when a setattr / getattr
 * or compiler-unknown attr access hits the fallback path. */
static FpyObjAttrs* fpy_attrs_new(int initial_capacity) {
    FpyObjAttrs *a = (FpyObjAttrs*)malloc(sizeof(FpyObjAttrs));
    a->names = (const char**)malloc(sizeof(const char*) * initial_capacity);
    a->values = (FpyValue*)malloc(sizeof(FpyValue) * initial_capacity);
    a->count = 0;
    a->capacity = initial_capacity;
    return a;
}

static void fpy_attrs_grow(FpyObjAttrs *a) {
    int new_cap = a->capacity * 2;
    a->names = (const char**)realloc(a->names,
                                      sizeof(const char*) * new_cap);
    a->values = (FpyValue*)realloc(a->values,
                                    sizeof(FpyValue) * new_cap);
    a->capacity = new_cap;
}

/* ------------------------------------------------------------------ */
/* Bump allocator for object instances.                                */
/*                                                                     */
/* Objects in fastpy are never individually freed (no GC, no refcount) */
/* so a bump allocator is ideal: each allocation is just a pointer     */
/* advance. Falls back to malloc for oversized allocations.            */
/* ------------------------------------------------------------------ */
#define FPY_ARENA_BLOCK_SIZE (1024 * 1024)  /* 1 MB per arena block */

typedef struct FpyArenaBlock {
    struct FpyArenaBlock *prev;
    size_t used;
    size_t capacity;
    char data[];   /* flexible array member */
} FpyArenaBlock;

/* Per-thread arena: each thread gets its own bump allocator chain.
 * No locking needed — threads never share arenas. */
static FPY_THREAD_LOCAL FpyArenaBlock *fpy_arena_current = NULL;

static FpyArenaBlock* fpy_arena_new_block(size_t min_size) {
    size_t cap = min_size > FPY_ARENA_BLOCK_SIZE ? min_size : FPY_ARENA_BLOCK_SIZE;
    FpyArenaBlock *b = (FpyArenaBlock*)malloc(sizeof(FpyArenaBlock) + cap);
    b->prev = fpy_arena_current;
    b->used = 0;
    b->capacity = cap;
    fpy_arena_current = b;
    return b;
}

static void* fpy_arena_alloc(size_t size) {
    /* Align to 16 bytes for safe FpyValue access on x64. */
    size = (size + 15) & ~(size_t)15;
    FpyArenaBlock *b = fpy_arena_current;
    if (b == NULL || b->used + size > b->capacity) {
        b = fpy_arena_new_block(size);
    }
    void *ptr = b->data + b->used;
    b->used += size;
    return ptr;
}

/* Create a new object instance.
 * Single allocation via bump allocator: the FpyObj header and its slot
 * array are contiguous. Each allocation is a pointer advance — no
 * malloc overhead per object.  */
FpyObj* fastpy_obj_new(int class_id) {
    int sc = fpy_classes[class_id].slot_count;
    size_t total = sizeof(FpyObj) + sizeof(FpyValue) * sc;
    FpyObj *obj = (FpyObj*)malloc(total);
    obj->refcount = 1;
    obj->magic = FPY_OBJ_MAGIC;
    obj->class_id = class_id;
    if (fpy_threading_mode == FPY_THREADING_FREE) fpy_mutex_init(&obj->lock);
    obj->dynamic_attrs = NULL;
    obj->weakref_list = NULL;
    if (sc > 0) {
        obj->slots = (FpyValue*)(obj + 1);
        for (int i = 0; i < sc; i++) {
            obj->slots[i].tag = FPY_TAG_NONE;
            obj->slots[i].data.i = 0;
        }
    } else {
        obj->slots = NULL;
    }
    /* Track AFTER the object is fully initialized — gc_maybe_collect may
     * traverse this object's slots, so magic/class_id/slots must be valid. */
    memset(&obj->gc_node, 0, sizeof(FpyGCNode));
    obj->gc_node.gc_type = FPY_GC_TYPE_OBJ;
    fpy_gc_track(&obj->gc_node);
    fpy_gc_maybe_collect();
    return obj;
}

/* Fast-path static slot access. Slot index is known at compile time.
 * Manages refcounts: increfs the new value, decrefs the old. */
void fastpy_obj_set_slot(FpyObj *obj, int slot, int32_t tag, int64_t data) {
    FpyValue old = obj->slots[slot];
    fpy_rc_incref(tag, data);
    obj->slots[slot].tag = tag;
    obj->slots[slot].data.i = data;
    fpy_rc_decref(old.tag, old.data.i);
}

void fastpy_obj_get_slot(FpyObj *obj, int slot,
                          int32_t *out_tag, int64_t *out_data) {
    *out_tag = obj->slots[slot].tag;
    *out_data = obj->slots[slot].data.i;
}

/* Set an attribute on an object */
/* Tagged-value attribute access (post-refactor) — stores with the exact tag
 * provided. Replaced the old typed variants (obj_set_int with its pointer
 * heuristic, obj_set_float, obj_set_str) and their obj_get_* counterparts. */
void fastpy_obj_set_fv(FpyObj *obj, const char *name, int32_t tag, int64_t data) {
    FpyValue v;
    v.tag = tag;
    v.data.i = data;
    /* Incref the new value up-front (before any slot/dyn store). */
    fpy_rc_incref(tag, data);
    /* Check static slots first (covers all compiler-known attrs) */
    int slot = fpy_find_slot(obj->class_id, name);
    if (slot >= 0) {
        FpyValue old = obj->slots[slot];
        obj->slots[slot] = v;
        fpy_rc_decref(old.tag, old.data.i);
        return;
    }
    /* Dynamic attr fallback — lazily allocate the side table on first use. */
    FpyObjAttrs *a = obj->dynamic_attrs;
    if (a != NULL) {
        for (int i = 0; i < a->count; i++) {
            if (a->names[i] == name
                    || strcmp(a->names[i], name) == 0) {
                FpyValue old = a->values[i];
                a->values[i] = v;
                fpy_rc_decref(old.tag, old.data.i);
                return;
            }
        }
        if (a->count >= a->capacity) {
            fpy_attrs_grow(a);
        }
    } else {
        a = fpy_attrs_new(4);
        obj->dynamic_attrs = a;
    }
    a->names[a->count] = name;
    a->values[a->count] = v;
    a->count++;
    /* New dynamic slot — no old value to decref. */
}

/* Get an attribute as FpyValue, writing tag+data to output params.
 * Using two output pointers instead of struct return sidesteps the MSVC x64
 * ABI (which passes 16-byte structs via hidden pointer). */
void fastpy_obj_get_fv(FpyObj *obj, const char *name, int32_t *out_tag, int64_t *out_data) {
    /* Check static slots first */
    int slot = fpy_find_slot(obj->class_id, name);
    if (slot >= 0) {
        *out_tag = obj->slots[slot].tag;
        *out_data = obj->slots[slot].data.i;
        return;
    }
    /* Dynamic attr fallback */
    FpyObjAttrs *a = obj->dynamic_attrs;
    if (a != NULL) {
        for (int i = 0; i < a->count; i++) {
            if (a->names[i] == name
                    || strcmp(a->names[i], name) == 0) {
                *out_tag = a->values[i].tag;
                *out_data = a->values[i].data.i;
                return;
            }
        }
    }
    snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no attribute '%s'",
             fpy_classes[obj->class_id].name, name);
    fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
    *out_tag = FPY_TAG_NONE; *out_data = 0; return;
}

/* Get attribute as string representation (works for any type).
 * Still used by the f-string path for `{self.attr}` expansion. */
/* Call a method on an object — returns i64 */
int64_t fastpy_obj_call_method0(FpyObj *obj, const char *name) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0;
    }
    return ((FpyMethodFunc)m->func)(obj);
}

int64_t fastpy_obj_call_method1(FpyObj *obj, const char *name, int64_t a) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0;
    }
    return ((FpyMethod1Func)m->func)(obj, a);
}

int64_t fastpy_obj_call_method2(FpyObj *obj, const char *name, int64_t a, int64_t b) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0;
    }
    return ((FpyMethod2Func)m->func)(obj, a, b);
}

int64_t fastpy_obj_call_method3(FpyObj *obj, const char *name, int64_t a, int64_t b, int64_t c) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0;
    }
    return ((FpyMethod3Func)m->func)(obj, a, b, c);
}

int64_t fastpy_obj_call_method4(FpyObj *obj, const char *name, int64_t a, int64_t b, int64_t c, int64_t d) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0;
    }
    return ((FpyMethod4Func)m->func)(obj, a, b, c, d);
}

/* Call method returning double */
typedef double (*FpyMethodDoubleFunc)(FpyObj *self);
typedef double (*FpyMethodDouble1Func)(FpyObj *self, int64_t a);

double fastpy_obj_call_method0_double(FpyObj *obj, const char *name) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0.0;
    }
    return ((FpyMethodDoubleFunc)m->func)(obj);
}

double fastpy_obj_call_method1_double(FpyObj *obj, const char *name, int64_t a) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0.0;
    }
    return ((FpyMethodDouble1Func)m->func)(obj, a);
}

/* Call __init__ (void return) */
void fastpy_obj_call_init0(FpyObj *obj) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (m) ((FpyMethodFunc)m->func)(obj);
}

void fastpy_obj_call_init1(FpyObj *obj, int64_t a) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (m) ((FpyMethod1Func)m->func)(obj, a);
}

void fastpy_obj_call_init2(FpyObj *obj, int64_t a, int64_t b) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (m) ((FpyMethod2Func)m->func)(obj, a, b);
}

void fastpy_obj_call_init3(FpyObj *obj, int64_t a, int64_t b, int64_t c) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (m) ((FpyMethod3Func)m->func)(obj, a, b, c);
}

void fastpy_obj_call_init4(FpyObj *obj, int64_t a, int64_t b, int64_t c, int64_t d) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (m) ((FpyMethod4Func)m->func)(obj, a, b, c, d);
}

/* isinstance check — walks class hierarchy */
int fastpy_isinstance(FpyObj *obj, int class_id) {
    int cid = obj->class_id;
    while (cid >= 0) {
        if (cid == class_id) return 1;
        cid = fpy_classes[cid].parent_id;
    }
    return 0;
}

/* Get class name for an object */
const char* fastpy_obj_classname(FpyObj *obj) {
    return fpy_classes[obj->class_id].name;
}

/* Call __str__ if it exists, otherwise return default repr */
const char* fastpy_obj_to_str(FpyObj *obj) {
    /* Try __str__ first, then __repr__ */
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__str__");
    if (!m) m = fastpy_find_method(obj->class_id, "__repr__");
    if (m) {
        int64_t result = ((FpyMethodFunc)m->func)(obj);
        return (const char*)result;
    }
    /* Default: <ClassName object> */
    char *buf = (char*)malloc(256);
    snprintf(buf, 256, "<%s object>", fpy_classes[obj->class_id].name);
    return buf;
}

/* Call __repr__ if it exists, otherwise __str__, otherwise default */
const char* fastpy_obj_to_repr(FpyObj *obj) {
    /* Try __repr__ first, then __str__ */
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__repr__");
    if (!m) m = fastpy_find_method(obj->class_id, "__str__");
    if (m) {
        int64_t result = ((FpyMethodFunc)m->func)(obj);
        return (const char*)result;
    }
    /* Default: <ClassName object> */
    char *buf = (char*)malloc(256);
    snprintf(buf, 256, "<%s object>", fpy_classes[obj->class_id].name);
    return buf;
}

/* Defined in cpython_bridge.c — prints a PyObject* via CPython's str() */
extern void fpy_cpython_print_obj(void *pyobj);

void fastpy_obj_write(FpyObj *obj) {
    if (obj == NULL) { printf("None"); return; }
    /* Check the magic number to distinguish native FpyObj from CPython
     * PyObject* (e.g. numpy arrays returned via the bridge). Without this,
     * accessing class_id on a PyObject* would read ob_refcnt and crash. */
    if (obj->magic != FPY_OBJ_MAGIC) {
        fpy_cpython_print_obj((void*)obj);
        return;
    }
    const char *s = fastpy_obj_to_str(obj);
    printf("%s", s);
}

/* ── Complex number operations ──────────────────────────────────── */

FpyComplex* fpy_complex_new(double real, double imag) {
    FpyComplex *c = (FpyComplex*)malloc(sizeof(FpyComplex));
    c->real = real;
    c->imag = imag;
    return c;
}

FpyComplex* fpy_complex_add(FpyComplex *a, FpyComplex *b) {
    return fpy_complex_new(a->real + b->real, a->imag + b->imag);
}

FpyComplex* fpy_complex_sub(FpyComplex *a, FpyComplex *b) {
    return fpy_complex_new(a->real - b->real, a->imag - b->imag);
}

FpyComplex* fpy_complex_mul(FpyComplex *a, FpyComplex *b) {
    return fpy_complex_new(
        a->real * b->real - a->imag * b->imag,
        a->real * b->imag + a->imag * b->real);
}

FpyComplex* fpy_complex_div(FpyComplex *a, FpyComplex *b) {
    double denom = b->real * b->real + b->imag * b->imag;
    if (denom == 0.0) {
        fastpy_raise(FPY_EXC_ZERODIVISION, "complex division by zero");
        return NULL;
    }
    return fpy_complex_new(
        (a->real * b->real + a->imag * b->imag) / denom,
        (a->imag * b->real - a->real * b->imag) / denom);
}

FpyComplex* fpy_complex_neg(FpyComplex *a) {
    return fpy_complex_new(-a->real, -a->imag);
}

double fpy_complex_abs(FpyComplex *a) {
    return sqrt(a->real * a->real + a->imag * a->imag);
}

void fpy_complex_print(FpyComplex *c) {
    if (c->real == 0.0 && !signbit(c->real)) {
        printf("%gj", c->imag);
    } else if (c->imag >= 0.0 || c->imag != c->imag) {
        printf("(%g+%gj)", c->real, c->imag);
    } else {
        printf("(%g%gj)", c->real, c->imag);
    }
}

char* fpy_complex_to_str(FpyComplex *c) {
    char *buf = (char*)malloc(128);
    if (c->real == 0.0 && !signbit(c->real)) {
        snprintf(buf, 128, "%gj", c->imag);
    } else if (c->imag >= 0.0 || c->imag != c->imag) {
        snprintf(buf, 128, "(%g+%gj)", c->real, c->imag);
    } else {
        snprintf(buf, 128, "(%g%gj)", c->real, c->imag);
    }
    return buf;
}

/* ── Native Decimal arithmetic ─────────────────────────────────── */

FpyDecimal* fpy_decimal_new(int64_t coeff, int32_t exp, int8_t sign) {
    FpyDecimal *d = (FpyDecimal*)malloc(sizeof(FpyDecimal));
    d->coefficient = coeff < 0 ? -coeff : coeff;
    d->exponent = exp;
    d->sign = sign;
    if (coeff == 0) d->sign = 0;
    return d;
}

FpyDecimal* fpy_decimal_from_int(int64_t val) {
    if (val == 0) return fpy_decimal_new(0, 0, 0);
    if (val < 0) return fpy_decimal_new(-val, 0, -1);
    return fpy_decimal_new(val, 0, 1);
}

FpyDecimal* fpy_decimal_from_str(const char *s) {
    if (!s || !*s) return fpy_decimal_new(0, 0, 0);
    int8_t sign = 1;
    const char *p = s;
    if (*p == '-') { sign = -1; p++; }
    else if (*p == '+') { p++; }

    int64_t coeff = 0;
    int32_t exp = 0;
    int saw_dot = 0, frac_digits = 0;

    while (*p) {
        if (*p == '.') { saw_dot = 1; p++; continue; }
        if (*p >= '0' && *p <= '9') {
            coeff = coeff * 10 + (*p - '0');
            if (saw_dot) frac_digits++;
        } else if (*p == 'e' || *p == 'E') {
            /* Scientific notation */
            p++;
            int esign = 1;
            if (*p == '-') { esign = -1; p++; }
            else if (*p == '+') { p++; }
            int eval = 0;
            while (*p >= '0' && *p <= '9') eval = eval * 10 + (*p++ - '0');
            exp = esign * eval - frac_digits;
            goto done;
        } else break;
        p++;
    }
    exp = -frac_digits;
done:
    if (coeff == 0) sign = 0;
    return fpy_decimal_new(coeff, exp, sign);
}

/* Normalize exponents: align a and b to the same exponent (smaller one) */
static void fpy_decimal_align(FpyDecimal *a, FpyDecimal *b,
                               int64_t *a_coeff, int64_t *b_coeff, int32_t *common_exp) {
    if (a->exponent == b->exponent) {
        *a_coeff = a->coefficient;
        *b_coeff = b->coefficient;
        *common_exp = a->exponent;
    } else if (a->exponent < b->exponent) {
        *common_exp = a->exponent;
        *a_coeff = a->coefficient;
        int32_t diff = b->exponent - a->exponent;
        int64_t scale = 1;
        for (int32_t i = 0; i < diff && i < 18; i++) scale *= 10;
        *b_coeff = b->coefficient * scale;
    } else {
        *common_exp = b->exponent;
        *b_coeff = b->coefficient;
        int32_t diff = a->exponent - b->exponent;
        int64_t scale = 1;
        for (int32_t i = 0; i < diff && i < 18; i++) scale *= 10;
        *a_coeff = a->coefficient * scale;
    }
}

FpyDecimal* fpy_decimal_add(FpyDecimal *a, FpyDecimal *b) {
    int64_t ac, bc; int32_t exp;
    fpy_decimal_align(a, b, &ac, &bc, &exp);
    int64_t a_signed = a->sign >= 0 ? ac : -ac;
    int64_t b_signed = b->sign >= 0 ? bc : -bc;
    int64_t result = a_signed + b_signed;
    int8_t sign = result > 0 ? 1 : (result < 0 ? -1 : 0);
    return fpy_decimal_new(result < 0 ? -result : result, exp, sign);
}

FpyDecimal* fpy_decimal_sub(FpyDecimal *a, FpyDecimal *b) {
    int64_t ac, bc; int32_t exp;
    fpy_decimal_align(a, b, &ac, &bc, &exp);
    int64_t a_signed = a->sign >= 0 ? ac : -ac;
    int64_t b_signed = b->sign >= 0 ? bc : -bc;
    int64_t result = a_signed - b_signed;
    int8_t sign = result > 0 ? 1 : (result < 0 ? -1 : 0);
    return fpy_decimal_new(result < 0 ? -result : result, exp, sign);
}

FpyDecimal* fpy_decimal_mul(FpyDecimal *a, FpyDecimal *b) {
    int64_t coeff = a->coefficient * b->coefficient;
    int32_t exp = a->exponent + b->exponent;
    int8_t sign = (int8_t)(a->sign * b->sign);
    return fpy_decimal_new(coeff, exp, sign);
}

FpyDecimal* fpy_decimal_div(FpyDecimal *a, FpyDecimal *b) {
    if (b->coefficient == 0) {
        fastpy_raise(FPY_EXC_ZERODIVISION, "division by zero");
        return NULL;
    }
    /* Scale numerator for precision (18 digits) */
    int64_t scale = 1000000000LL;  /* 9 extra digits of precision */
    int64_t num = a->coefficient * scale;
    int64_t coeff = num / b->coefficient;
    int32_t exp = a->exponent - b->exponent - 9;
    int8_t sign = (int8_t)(a->sign * b->sign);
    /* Remove trailing zeros */
    while (coeff != 0 && coeff % 10 == 0) { coeff /= 10; exp++; }
    return fpy_decimal_new(coeff, exp, sign);
}

int fpy_decimal_compare(FpyDecimal *a, FpyDecimal *b) {
    int64_t ac, bc; int32_t exp;
    fpy_decimal_align(a, b, &ac, &bc, &exp);
    int64_t av = a->sign >= 0 ? ac : -ac;
    int64_t bv = b->sign >= 0 ? bc : -bc;
    if (av < bv) return -1;
    if (av > bv) return 1;
    return 0;
}

FpyDecimal* fpy_decimal_neg(FpyDecimal *a) {
    return fpy_decimal_new(a->coefficient, a->exponent, (int8_t)(-a->sign));
}

FpyDecimal* fpy_decimal_abs(FpyDecimal *a) {
    return fpy_decimal_new(a->coefficient, a->exponent,
                            a->sign < 0 ? 1 : a->sign);
}

char* fpy_decimal_to_str(FpyDecimal *d) {
    if (d->sign == 0) return fpy_strdup("0");

    char coeff_buf[32];
    sprintf(coeff_buf, "%lld", (long long)d->coefficient);
    int clen = (int)strlen(coeff_buf);

    char *buf = (char*)malloc(clen + 32);
    char *out = buf;
    if (d->sign < 0) *out++ = '-';

    if (d->exponent >= 0) {
        /* No decimal point needed, just append zeros */
        memcpy(out, coeff_buf, clen); out += clen;
        for (int32_t i = 0; i < d->exponent; i++) *out++ = '0';
    } else {
        int frac_digits = -d->exponent;
        if (frac_digits >= clen) {
            /* 0.00...digits */
            *out++ = '0'; *out++ = '.';
            for (int i = 0; i < frac_digits - clen; i++) *out++ = '0';
            memcpy(out, coeff_buf, clen); out += clen;
        } else {
            /* digits with dot inserted */
            int int_digits = clen - frac_digits;
            memcpy(out, coeff_buf, int_digits); out += int_digits;
            *out++ = '.';
            memcpy(out, coeff_buf + int_digits, frac_digits); out += frac_digits;
        }
    }
    *out = '\0';
    return buf;
}

/* ── Native JSON support ────────────────────────────────────────── */

static void json_append(char **buf, int *len, int *cap, const char *s, int slen) {
    while (*len + slen >= *cap) { *cap *= 2; *buf = (char*)realloc(*buf, *cap); }
    memcpy(*buf + *len, s, slen);
    *len += slen;
}
static void json_append_str(char **buf, int *len, int *cap, const char *s) {
    json_append(buf, len, cap, s, (int)strlen(s));
}

static void json_serialize(FpyValue val, char **buf, int *len, int *cap) {
    switch (val.tag) {
        case FPY_TAG_INT: {
            char tmp[32]; snprintf(tmp, sizeof(tmp), "%lld", (long long)val.data.i);
            json_append_str(buf, len, cap, tmp); break;
        }
        case FPY_TAG_FLOAT: {
            char tmp[64]; snprintf(tmp, sizeof(tmp), "%.17g", val.data.f);
            json_append_str(buf, len, cap, tmp); break;
        }
        case FPY_TAG_STR: {
            const char *s = val.data.s;
            json_append(buf, len, cap, "\"", 1);
            for (const char *p = s; *p; p++) {
                switch (*p) {
                    case '"':  json_append(buf, len, cap, "\\\"", 2); break;
                    case '\\': json_append(buf, len, cap, "\\\\", 2); break;
                    case '\n': json_append(buf, len, cap, "\\n", 2); break;
                    case '\r': json_append(buf, len, cap, "\\r", 2); break;
                    case '\t': json_append(buf, len, cap, "\\t", 2); break;
                    default:   json_append(buf, len, cap, p, 1); break;
                }
            }
            json_append(buf, len, cap, "\"", 1); break;
        }
        case FPY_TAG_BOOL:
            json_append_str(buf, len, cap, val.data.i ? "true" : "false"); break;
        case FPY_TAG_NONE:
            json_append_str(buf, len, cap, "null"); break;
        case FPY_TAG_LIST: {
            FpyList *lst = (FpyList*)(intptr_t)val.data.i;
            json_append(buf, len, cap, "[", 1);
            for (int64_t i = 0; i < lst->length; i++) {
                if (i > 0) json_append(buf, len, cap, ", ", 2);
                json_serialize(lst->items[i], buf, len, cap);
            }
            json_append(buf, len, cap, "]", 1); break;
        }
        case FPY_TAG_DICT: {
            FpyDict *d = (FpyDict*)(intptr_t)val.data.i;
            json_append(buf, len, cap, "{", 1);
            for (int64_t i = 0; i < d->length; i++) {
                if (i > 0) json_append(buf, len, cap, ", ", 2);
                json_serialize(d->keys[i], buf, len, cap);
                json_append(buf, len, cap, ": ", 2);
                json_serialize(d->values[i], buf, len, cap);
            }
            json_append(buf, len, cap, "}", 1); break;
        }
        default: json_append_str(buf, len, cap, "null"); break;
    }
}

const char* fastpy_json_dumps_fv(int32_t tag, int64_t data) {
    int cap = 256, len = 0;
    char *buf = (char*)malloc(cap);
    FpyValue val; val.tag = tag; val.data.i = data;
    json_serialize(val, &buf, &len, &cap);
    buf[len] = '\0';
    return buf;
}

/* json.loads */
static const char *json_skip_ws(const char *p) {
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    return p;
}
static const char *json_parse_value(const char *p, int32_t *out_tag, int64_t *out_data);

static const char *json_parse_string(const char *p, const char **out) {
    if (*p != '"') return NULL;
    p++;
    int cap = 64, len = 0;
    char *buf = (char*)malloc(cap);
    while (*p && *p != '"') {
        if (*p == '\\') {
            p++;
            switch (*p) {
                case '"': buf[len++] = '"'; break;
                case '\\': buf[len++] = '\\'; break;
                case 'n': buf[len++] = '\n'; break;
                case 'r': buf[len++] = '\r'; break;
                case 't': buf[len++] = '\t'; break;
                case '/': buf[len++] = '/'; break;
                default: buf[len++] = *p; break;
            }
        } else { buf[len++] = *p; }
        if (len >= cap - 1) { cap *= 2; buf = (char*)realloc(buf, cap); }
        p++;
    }
    buf[len] = '\0';
    if (*p == '"') p++;
    *out = buf;
    return p;
}

static const char *json_parse_number(const char *p, int32_t *tag, int64_t *data) {
    const char *start = p;
    int is_float = 0;
    if (*p == '-') p++;
    while (*p >= '0' && *p <= '9') p++;
    if (*p == '.') { is_float = 1; p++; while (*p >= '0' && *p <= '9') p++; }
    if (*p == 'e' || *p == 'E') { is_float = 1; p++; if (*p == '+' || *p == '-') p++; while (*p >= '0' && *p <= '9') p++; }
    if (is_float) { *tag = FPY_TAG_FLOAT; double d = strtod(start, NULL); memcpy(data, &d, sizeof(double)); }
    else { *tag = FPY_TAG_INT; *data = strtoll(start, NULL, 10); }
    return p;
}

static const char *json_parse_array(const char *p, int32_t *tag, int64_t *data) {
    p++;
    FpyList *lst = fpy_list_new(4);
    p = json_skip_ws(p);
    if (*p != ']') {
        while (1) {
            FpyValue elem;
            p = json_parse_value(json_skip_ws(p), &elem.tag, &elem.data.i);
            if (!p) break;
            fpy_list_append(lst, elem);
            p = json_skip_ws(p);
            if (*p == ',') { p++; continue; }
            break;
        }
    }
    if (*p == ']') p++;
    *tag = FPY_TAG_LIST; *data = (int64_t)(intptr_t)lst;
    return p;
}

static const char *json_parse_object(const char *p, int32_t *tag, int64_t *data) {
    p++;
    FpyDict *dict = fpy_dict_new(4);
    p = json_skip_ws(p);
    if (*p != '}') {
        while (1) {
            const char *key_str;
            p = json_parse_string(json_skip_ws(p), &key_str);
            if (!p) break;
            p = json_skip_ws(p);
            if (*p == ':') p++;
            FpyValue val;
            p = json_parse_value(json_skip_ws(p), &val.tag, &val.data.i);
            if (!p) break;
            FpyValue key; key.tag = FPY_TAG_STR; key.data.s = key_str;
            fpy_dict_set(dict, key, val);
            p = json_skip_ws(p);
            if (*p == ',') { p++; continue; }
            break;
        }
    }
    if (*p == '}') p++;
    *tag = FPY_TAG_DICT; *data = (int64_t)(intptr_t)dict;
    return p;
}

static const char *json_parse_value(const char *p, int32_t *tag, int64_t *data) {
    p = json_skip_ws(p);
    if (*p == '"') { const char *s; p = json_parse_string(p, &s); *tag = FPY_TAG_STR; *data = (int64_t)(intptr_t)s; return p; }
    if (*p == '{') return json_parse_object(p, tag, data);
    if (*p == '[') return json_parse_array(p, tag, data);
    if (*p == 't' && strncmp(p, "true", 4) == 0) { *tag = FPY_TAG_BOOL; *data = 1; return p + 4; }
    if (*p == 'f' && strncmp(p, "false", 5) == 0) { *tag = FPY_TAG_BOOL; *data = 0; return p + 5; }
    if (*p == 'n' && strncmp(p, "null", 4) == 0) { *tag = FPY_TAG_NONE; *data = 0; return p + 4; }
    if (*p == '-' || (*p >= '0' && *p <= '9')) return json_parse_number(p, tag, data);
    *tag = FPY_TAG_NONE; *data = 0; return p;
}

void fastpy_json_loads(const char *json_str, int32_t *out_tag, int64_t *out_data) {
    json_parse_value(json_str, out_tag, out_data);
}

/* ── Native OS module functions ─────────────────────────────────── */

#ifdef _WIN32
#include <direct.h>
#include <io.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>
#endif

const char* fastpy_os_getcwd(void) {
    char *buf = (char*)malloc(4096);
#ifdef _WIN32
    _getcwd(buf, 4096);
#else
    getcwd(buf, 4096);
#endif
    return buf;
}

int64_t fastpy_os_path_exists(const char *path) {
#ifdef _WIN32
    DWORD attrs = GetFileAttributesA(path);
    return (attrs != INVALID_FILE_ATTRIBUTES) ? 1 : 0;
#else
    struct stat st;
    return (stat(path, &st) == 0) ? 1 : 0;
#endif
}

int64_t fastpy_os_path_isfile(const char *path) {
#ifdef _WIN32
    DWORD attrs = GetFileAttributesA(path);
    if (attrs == INVALID_FILE_ATTRIBUTES) return 0;
    return (attrs & FILE_ATTRIBUTE_DIRECTORY) ? 0 : 1;
#else
    struct stat st;
    if (stat(path, &st) != 0) return 0;
    return S_ISREG(st.st_mode) ? 1 : 0;
#endif
}

int64_t fastpy_os_path_isdir(const char *path) {
#ifdef _WIN32
    DWORD attrs = GetFileAttributesA(path);
    if (attrs == INVALID_FILE_ATTRIBUTES) return 0;
    return (attrs & FILE_ATTRIBUTE_DIRECTORY) ? 1 : 0;
#else
    struct stat st;
    if (stat(path, &st) != 0) return 0;
    return S_ISDIR(st.st_mode) ? 1 : 0;
#endif
}

const char* fastpy_os_path_join(const char *a, const char *b) {
    int alen = (int)strlen(a), blen = (int)strlen(b);
    char *buf = (char*)malloc(alen + blen + 2);
    memcpy(buf, a, alen);
#ifdef _WIN32
    if (alen > 0 && a[alen-1] != '\\' && a[alen-1] != '/') buf[alen++] = '\\';
#else
    if (alen > 0 && a[alen-1] != '/') buf[alen++] = '/';
#endif
    memcpy(buf + alen, b, blen + 1);
    return buf;
}

const char* fastpy_os_path_basename(const char *path) {
    const char *last = path;
    for (const char *p = path; *p; p++) {
        if (*p == '/' || *p == '\\') last = p + 1;
    }
    return fpy_strdup(last);
}

const char* fastpy_os_path_dirname(const char *path) {
    const char *last_sep = NULL;
    for (const char *p = path; *p; p++) {
        if (*p == '/' || *p == '\\') last_sep = p;
    }
    if (!last_sep) return fpy_strdup("");
    int len = (int)(last_sep - path);
    char *buf = (char*)malloc(len + 1);
    memcpy(buf, path, len);
    buf[len] = '\0';
    return buf;
}

FpyList* fastpy_os_listdir(const char *path) {
    FpyList *lst = fpy_list_new(16);
#ifdef _WIN32
    char pattern[4096];
    snprintf(pattern, sizeof(pattern), "%s\\*", path);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (strcmp(fd.cFileName, ".") == 0 || strcmp(fd.cFileName, "..") == 0) continue;
            FpyValue v;
            v.tag = FPY_TAG_STR;
            v.data.s = fpy_strdup(fd.cFileName);
            fpy_list_append(lst, v);
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
#else
    DIR *d = opendir(path);
    if (d) {
        struct dirent *ent;
        while ((ent = readdir(d))) {
            if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0) continue;
            FpyValue v;
            v.tag = FPY_TAG_STR;
            v.data.s = strdup(ent->d_name);
            fpy_list_append(lst, v);
        }
        closedir(d);
    }
#endif
    return lst;
}

const char* fastpy_os_getenv(const char *name) {
    const char *val = getenv(name);
    return val ? fpy_strdup(val) : NULL;
}

/* ============================================================
 * Native collections module
 * ============================================================ */

/* --- Counter ---
 * A Counter is just an FpyDict where values are always ints.
 * counter_new() → empty Counter (dict)
 * counter_from_list(list) → count occurrences of each element
 * counter_increment(counter, key_tag, key_data) → increment count by 1
 * counter_most_common(counter, n) → list of (key, count) tuples, sorted desc
 */

FpyDict* fastpy_counter_new(void) {
    return fpy_dict_new(4);
}

FpyDict* fastpy_counter_from_string(const char *str) {
    if (!str) return fpy_dict_new(4);
    int64_t len = (int64_t)strlen(str);
    FpyDict *counter = fpy_dict_new(len > 4 ? (int32_t)len : 4);
    for (int64_t i = 0; i < len; i++) {
        char buf[2] = {str[i], '\0'};
        FpyValue key;
        key.tag = FPY_TAG_STR;
        key.data.s = fpy_strdup(buf);
        uint64_t h = fpy_hash_value(key);
        int64_t mask = counter->table_size - 1;
        int64_t slot = (int64_t)(h & (uint64_t)mask);
        int found = 0;
        while (1) {
            int64_t idx = counter->indices[slot];
            if (idx == FPY_DICT_EMPTY) break;
            if (idx != FPY_DICT_DELETED && fpy_key_equal(counter->keys[idx], key)) {
                counter->values[idx].data.i++;
                found = 1;
                free(key.data.s);
                break;
            }
            slot = (slot + 1) & mask;
        }
        if (!found) {
            fpy_dict_set(counter, key, fpy_int(1));
        }
    }
    return counter;
}

FpyDict* fastpy_counter_from_list(FpyList *list) {
    FpyDict *counter = fpy_dict_new(list->length > 4 ? list->length : 4);
    for (int64_t i = 0; i < list->length; i++) {
        FpyValue key = list->items[i];
        uint64_t h = fpy_hash_value(key);
        int64_t mask = counter->table_size - 1;
        int64_t slot = (int64_t)(h & (uint64_t)mask);
        int found = 0;
        while (1) {
            int64_t idx = counter->indices[slot];
            if (idx == FPY_DICT_EMPTY) break;
            if (idx != FPY_DICT_DELETED && fpy_key_equal(counter->keys[idx], key)) {
                counter->values[idx].data.i++;
                found = 1;
                break;
            }
            slot = (slot + 1) & mask;
        }
        if (!found) {
            fpy_dict_set(counter, key, fpy_int(1));
        }
    }
    return counter;
}

void fastpy_counter_increment(FpyDict *counter, int32_t key_tag, int64_t key_data) {
    FpyValue key; key.tag = key_tag; key.data.i = key_data;
    uint64_t h = fpy_hash_value(key);
    int64_t mask = counter->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = counter->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(counter->keys[idx], key)) {
            counter->values[idx].data.i++;
            return;
        }
        slot = (slot + 1) & mask;
    }
    fpy_dict_set(counter, key, fpy_int(1));
}

void fastpy_counter_update_list(FpyDict *counter, FpyList *list) {
    for (int64_t i = 0; i < list->length; i++) {
        FpyValue key = list->items[i];
        uint64_t h = fpy_hash_value(key);
        int64_t mask = counter->table_size - 1;
        int64_t slot = (int64_t)(h & (uint64_t)mask);
        int found = 0;
        while (1) {
            int64_t idx = counter->indices[slot];
            if (idx == FPY_DICT_EMPTY) break;
            if (idx != FPY_DICT_DELETED && fpy_key_equal(counter->keys[idx], key)) {
                counter->values[idx].data.i++;
                found = 1;
                break;
            }
            slot = (slot + 1) & mask;
        }
        if (!found) {
            fpy_dict_set(counter, key, fpy_int(1));
        }
    }
}

/* counter.most_common(n) → list of (key, count) tuples sorted by count desc.
 * If n <= 0, return all. */
FpyList* fastpy_counter_most_common(FpyDict *counter, int64_t n) {
    int64_t total = counter->length;
    if (n <= 0 || n > total) n = total;

    /* Build sorted index array (selection sort — sufficient for typical Counter sizes) */
    int64_t *order = (int64_t*)malloc(sizeof(int64_t) * total);
    for (int64_t i = 0; i < total; i++) order[i] = i;

    /* Sort descending by count */
    for (int64_t i = 0; i < n && i < total; i++) {
        int64_t max_idx = i;
        for (int64_t j = i + 1; j < total; j++) {
            if (counter->values[order[j]].data.i > counter->values[order[max_idx]].data.i)
                max_idx = j;
        }
        if (max_idx != i) {
            int64_t tmp = order[i];
            order[i] = order[max_idx];
            order[max_idx] = tmp;
        }
    }

    /* Build result list of (key, count) tuples */
    FpyList *result = fpy_list_new(n);
    for (int64_t i = 0; i < n; i++) {
        int64_t idx = order[i];
        FpyList *tuple = fpy_list_new(2);
        tuple->is_tuple = 1;
        fpy_list_append(tuple, counter->keys[idx]);
        fpy_list_append(tuple, counter->values[idx]);
        FpyValue tval; tval.tag = FPY_TAG_LIST; tval.data.list = tuple;
        fpy_list_append(result, tval);
    }
    free(order);
    return result;
}

/* counter.elements() → list with each element repeated by its count */
FpyList* fastpy_counter_elements(FpyDict *counter) {
    /* First pass: compute total size */
    int64_t total = 0;
    for (int64_t i = 0; i < counter->length; i++) {
        int64_t count = counter->values[i].data.i;
        if (count > 0) total += count;
    }
    FpyList *result = fpy_list_new(total > 4 ? total : 4);
    for (int64_t i = 0; i < counter->length; i++) {
        int64_t count = counter->values[i].data.i;
        for (int64_t j = 0; j < count; j++) {
            fpy_list_append(result, counter->keys[i]);
        }
    }
    return result;
}

/* --- defaultdict ---
 * A defaultdict is an FpyDict + a factory tag.
 * Factory tags: 0=list, 1=int(0), 2=str(""), 3=float(0.0), 4=dict
 * When a key is missing, we insert a default value and return it.
 *
 * We store the factory tag in a global (per-defaultdict) since our FpyDict
 * struct doesn't have room for extra fields. We use a simple registry.
 */

#define FPY_DEFAULTDICT_MAX 64
static struct {
    FpyDict *dict;
    int factory;  /* 0=list, 1=int, 2=str, 3=float, 4=dict */
} fpy_defaultdict_registry[FPY_DEFAULTDICT_MAX];
static int fpy_defaultdict_count = 0;

FpyDict* fastpy_defaultdict_new(int32_t factory_tag) {
    FpyDict *dict = fpy_dict_new(4);
    if (fpy_defaultdict_count < FPY_DEFAULTDICT_MAX) {
        fpy_defaultdict_registry[fpy_defaultdict_count].dict = dict;
        fpy_defaultdict_registry[fpy_defaultdict_count].factory = factory_tag;
        fpy_defaultdict_count++;
    }
    return dict;
}

static int fpy_defaultdict_get_factory(FpyDict *dict) {
    for (int i = 0; i < fpy_defaultdict_count; i++) {
        if (fpy_defaultdict_registry[i].dict == dict)
            return fpy_defaultdict_registry[i].factory;
    }
    return 1;  /* default to int if not found */
}

static FpyValue fpy_defaultdict_make_default(int factory) {
    switch (factory) {
        case 0: {  /* list */
            FpyList *lst = fpy_list_new(4);
            FpyValue v; v.tag = FPY_TAG_LIST; v.data.list = lst;
            return v;
        }
        case 1: return fpy_int(0);     /* int */
        case 2: return fpy_str("");    /* str */
        case 3: return fpy_float(0.0); /* float */
        case 4: {  /* dict */
            FpyDict *d = fpy_dict_new(4);
            FpyValue v; v.tag = FPY_TAG_DICT; v.data.i = (int64_t)(intptr_t)d;
            return v;
        }
        default: return fpy_int(0);
    }
}

/* Get value or insert default. Returns the value via out_tag/out_data. */
void fastpy_defaultdict_get(FpyDict *dict, const char *key,
                            int32_t *out_tag, int64_t *out_data) {
    FpyValue k = fpy_str(key);
    uint64_t h = fpy_hash_value(k);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k)) {
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return;
        }
        slot = (slot + 1) & mask;
    }
    /* Key not found — insert default */
    int factory = fpy_defaultdict_get_factory(dict);
    FpyValue def = fpy_defaultdict_make_default(factory);
    fpy_dict_set(dict, k, def);
    *out_tag = def.tag;
    *out_data = def.data.i;
}

/* Get value by FpyValue key (for non-string keys) */
void fastpy_defaultdict_get_fv(FpyDict *dict, int32_t key_tag, int64_t key_data,
                               int32_t *out_tag, int64_t *out_data) {
    FpyValue key; key.tag = key_tag; key.data.i = key_data;
    uint64_t h = fpy_hash_value(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], key)) {
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return;
        }
        slot = (slot + 1) & mask;
    }
    /* Key not found — insert default */
    int factory = fpy_defaultdict_get_factory(dict);
    FpyValue def = fpy_defaultdict_make_default(factory);
    fpy_dict_set(dict, key, def);
    *out_tag = def.tag;
    *out_data = def.data.i;
}

/* --- deque (double-ended queue) ---
 * Implemented as a circular buffer of FpyValues.
 * Supports O(1) append/appendleft/pop/popleft.
 */

typedef struct {
    int32_t refcount;
    FpyGCNode gc_node;
    FpyValue *items;
    int64_t head;       /* index of first element */
    int64_t length;     /* number of elements */
    int64_t capacity;   /* allocated size of items array */
    int64_t maxlen;     /* max length (-1 = unlimited) */
    fpy_mutex_t lock;
} FpyDeque;

FpyDeque* fastpy_deque_new(int64_t maxlen) {
    FpyDeque *dq = (FpyDeque*)malloc(sizeof(FpyDeque));
    dq->refcount = 1;
    memset(&dq->gc_node, 0, sizeof(FpyGCNode));
    dq->capacity = 8;
    dq->items = (FpyValue*)malloc(sizeof(FpyValue) * dq->capacity);
    dq->head = 0;
    dq->length = 0;
    dq->maxlen = maxlen;
    if (fpy_threading_mode == FPY_THREADING_FREE) fpy_mutex_init(&dq->lock);
    return dq;
}

FpyDeque* fastpy_deque_from_list(FpyList *list, int64_t maxlen) {
    int64_t cap = list->length > 8 ? list->length * 2 : 8;
    FpyDeque *dq = (FpyDeque*)malloc(sizeof(FpyDeque));
    dq->refcount = 1;
    memset(&dq->gc_node, 0, sizeof(FpyGCNode));
    dq->capacity = cap;
    dq->items = (FpyValue*)malloc(sizeof(FpyValue) * cap);
    dq->head = 0;
    dq->maxlen = maxlen;

    int64_t start = 0;
    if (maxlen > 0 && list->length > maxlen) {
        start = list->length - maxlen;
    }
    dq->length = list->length - start;
    for (int64_t i = 0; i < dq->length; i++) {
        dq->items[i] = list->items[start + i];
    }
    if (fpy_threading_mode == FPY_THREADING_FREE) fpy_mutex_init(&dq->lock);
    return dq;
}

static void fpy_deque_grow(FpyDeque *dq) {
    int64_t new_cap = dq->capacity * 2;
    FpyValue *new_items = (FpyValue*)malloc(sizeof(FpyValue) * new_cap);
    /* Linearize the circular buffer */
    for (int64_t i = 0; i < dq->length; i++) {
        new_items[i] = dq->items[(dq->head + i) % dq->capacity];
    }
    free(dq->items);
    dq->items = new_items;
    dq->head = 0;
    dq->capacity = new_cap;
}

void fastpy_deque_append(FpyDeque *dq, int32_t tag, int64_t data) {
    FpyValue val; val.tag = tag; val.data.i = data;
    if (dq->maxlen > 0 && dq->length >= dq->maxlen) {
        /* Evict from the left */
        dq->head = (dq->head + 1) % dq->capacity;
        dq->length--;
    }
    if (dq->length >= dq->capacity) fpy_deque_grow(dq);
    int64_t tail = (dq->head + dq->length) % dq->capacity;
    dq->items[tail] = val;
    dq->length++;
}

void fastpy_deque_appendleft(FpyDeque *dq, int32_t tag, int64_t data) {
    FpyValue val; val.tag = tag; val.data.i = data;
    if (dq->maxlen > 0 && dq->length >= dq->maxlen) {
        /* Evict from the right */
        dq->length--;
    }
    if (dq->length >= dq->capacity) fpy_deque_grow(dq);
    dq->head = (dq->head - 1 + dq->capacity) % dq->capacity;
    dq->items[dq->head] = val;
    dq->length++;
}

void fastpy_deque_pop(FpyDeque *dq, int32_t *out_tag, int64_t *out_data) {
    if (dq->length == 0) {
        fastpy_raise(FPY_EXC_INDEXERROR, "pop from an empty deque");
        *out_tag = FPY_TAG_NONE; *out_data = 0; return;
    }
    dq->length--;
    int64_t tail = (dq->head + dq->length) % dq->capacity;
    *out_tag = dq->items[tail].tag;
    *out_data = dq->items[tail].data.i;
}

void fastpy_deque_popleft(FpyDeque *dq, int32_t *out_tag, int64_t *out_data) {
    if (dq->length == 0) {
        fastpy_raise(FPY_EXC_INDEXERROR, "pop from an empty deque");
        *out_tag = FPY_TAG_NONE; *out_data = 0; return;
    }
    *out_tag = dq->items[dq->head].tag;
    *out_data = dq->items[dq->head].data.i;
    dq->head = (dq->head + 1) % dq->capacity;
    dq->length--;
}

int64_t fastpy_deque_length(FpyDeque *dq) {
    return dq->length;
}

void fastpy_deque_get(FpyDeque *dq, int64_t index, int32_t *out_tag, int64_t *out_data) {
    if (index < 0) index += dq->length;
    if (index < 0 || index >= dq->length) {
        fastpy_raise(FPY_EXC_INDEXERROR, "deque index out of range");
        *out_tag = FPY_TAG_NONE; *out_data = 0; return;
    }
    int64_t actual = (dq->head + index) % dq->capacity;
    *out_tag = dq->items[actual].tag;
    *out_data = dq->items[actual].data.i;
}

void fastpy_deque_rotate(FpyDeque *dq, int64_t n) {
    if (dq->length <= 1) return;
    n = n % dq->length;
    if (n < 0) n += dq->length;
    /* Rotate right by n: move n elements from right to left */
    for (int64_t i = 0; i < n; i++) {
        dq->length--;
        int64_t tail = (dq->head + dq->length) % dq->capacity;
        FpyValue val = dq->items[tail];
        dq->head = (dq->head - 1 + dq->capacity) % dq->capacity;
        dq->items[dq->head] = val;
        dq->length++;
    }
}

void fastpy_deque_clear(FpyDeque *dq) {
    dq->head = 0;
    dq->length = 0;
}

/* Convert deque to list (for iteration/printing) */
FpyList* fastpy_deque_to_list(FpyDeque *dq) {
    FpyList *lst = fpy_list_new(dq->length > 4 ? dq->length : 4);
    for (int64_t i = 0; i < dq->length; i++) {
        int64_t actual = (dq->head + i) % dq->capacity;
        fpy_list_append(lst, dq->items[actual]);
    }
    return lst;
}

void fastpy_deque_extend(FpyDeque *dq, FpyList *list) {
    for (int64_t i = 0; i < list->length; i++) {
        fastpy_deque_append(dq, list->items[i].tag, list->items[i].data.i);
    }
}

void fastpy_deque_extendleft(FpyDeque *dq, FpyList *list) {
    for (int64_t i = 0; i < list->length; i++) {
        fastpy_deque_appendleft(dq, list->items[i].tag, list->items[i].data.i);
    }
}

/* --- namedtuple ---
 * A namedtuple is represented as a tuple (FpyList with is_tuple=1)
 * plus a field name registry for __repr__ and field access.
 * Since we compile statically, field access is by index. The registry
 * is only for display and debugging.
 */

#define FPY_NAMEDTUPLE_MAX 64
static struct {
    const char *type_name;
    const char **field_names;
    int n_fields;
} fpy_namedtuple_registry[FPY_NAMEDTUPLE_MAX];
static int fpy_namedtuple_count = 0;

int32_t fastpy_namedtuple_register(const char *type_name,
                                    const char **field_names, int32_t n_fields) {
    int id = fpy_namedtuple_count;
    if (id >= FPY_NAMEDTUPLE_MAX) return -1;
    fpy_namedtuple_registry[id].type_name = type_name;
    fpy_namedtuple_registry[id].field_names = field_names;
    fpy_namedtuple_registry[id].n_fields = n_fields;
    fpy_namedtuple_count++;
    return id;
}

FpyList* fastpy_namedtuple_new(int32_t type_id, int32_t n_fields) {
    (void)type_id;  /* type_id used for repr, not allocation */
    FpyList *t = fpy_list_new(n_fields);
    t->is_tuple = 1;
    return t;
}

/* Print a namedtuple: TypeName(field1=val1, field2=val2) */
void fastpy_namedtuple_print(FpyList *tuple, int32_t type_id) {
    if (type_id < 0 || type_id >= fpy_namedtuple_count) {
        /* Fallback to regular tuple print */
        fastpy_tuple_write(tuple);
        printf("\n");
        return;
    }
    printf("%s(", fpy_namedtuple_registry[type_id].type_name);
    for (int64_t i = 0; i < tuple->length; i++) {
        if (i > 0) printf(", ");
        printf("%s=", fpy_namedtuple_registry[type_id].field_names[i]);
        char buf[256];
        fpy_value_repr(tuple->items[i], buf, sizeof(buf));
        printf("%s", buf);
    }
    printf(")\n");
}

/* --- ChainMap ---
 * A ChainMap is a list of dicts. Lookup goes through the list in order,
 * returning the first hit. Writes go to the first dict only.
 */

typedef struct {
    int32_t refcount;
    FpyDict **maps;     /* array of dict pointers */
    int32_t n_maps;
    int32_t capacity;
} FpyChainMap;

FpyChainMap* fastpy_chainmap_new(void) {
    FpyChainMap *cm = (FpyChainMap*)malloc(sizeof(FpyChainMap));
    cm->refcount = 1;
    cm->capacity = 4;
    cm->maps = (FpyDict**)malloc(sizeof(FpyDict*) * cm->capacity);
    cm->n_maps = 1;
    cm->maps[0] = fpy_dict_new(4);  /* default first dict */
    return cm;
}

FpyChainMap* fastpy_chainmap_from_dicts(FpyDict **dicts, int32_t n) {
    FpyChainMap *cm = (FpyChainMap*)malloc(sizeof(FpyChainMap));
    cm->refcount = 1;
    cm->capacity = n > 4 ? n * 2 : 4;
    cm->maps = (FpyDict**)malloc(sizeof(FpyDict*) * cm->capacity);
    cm->n_maps = n;
    for (int32_t i = 0; i < n; i++) {
        cm->maps[i] = dicts[i];
    }
    return cm;
}

void fastpy_chainmap_get(FpyChainMap *cm, const char *key,
                         int32_t *out_tag, int64_t *out_data) {
    FpyValue k = fpy_str(key);
    for (int32_t m = 0; m < cm->n_maps; m++) {
        FpyDict *dict = cm->maps[m];
        uint64_t h = fpy_hash_value(k);
        int64_t mask = dict->table_size - 1;
        int64_t slot = (int64_t)(h & (uint64_t)mask);
        while (1) {
            int64_t idx = dict->indices[slot];
            if (idx == FPY_DICT_EMPTY) break;
            if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k)) {
                *out_tag = dict->values[idx].tag;
                *out_data = dict->values[idx].data.i;
                return;
            }
            slot = (slot + 1) & mask;
        }
    }
    fastpy_raise(FPY_EXC_KEYERROR, key);
    *out_tag = FPY_TAG_NONE; *out_data = 0; return;
}

void fastpy_chainmap_set(FpyChainMap *cm, const char *key,
                         int32_t tag, int64_t data) {
    /* Writes always go to the first map */
    FpyValue k = fpy_str(key);
    FpyValue v; v.tag = tag; v.data.i = data;
    fpy_dict_set(cm->maps[0], k, v);
}

FpyChainMap* fastpy_chainmap_new_child(FpyChainMap *cm) {
    FpyChainMap *child = (FpyChainMap*)malloc(sizeof(FpyChainMap));
    child->refcount = 1;
    child->capacity = cm->n_maps + 2;
    child->maps = (FpyDict**)malloc(sizeof(FpyDict*) * child->capacity);
    child->maps[0] = fpy_dict_new(4);  /* new empty dict at front */
    for (int32_t i = 0; i < cm->n_maps; i++) {
        child->maps[i + 1] = cm->maps[i];
    }
    child->n_maps = cm->n_maps + 1;
    return child;
}

int32_t fastpy_chainmap_contains(FpyChainMap *cm, const char *key) {
    FpyValue k = fpy_str(key);
    for (int32_t m = 0; m < cm->n_maps; m++) {
        FpyDict *dict = cm->maps[m];
        uint64_t h = fpy_hash_value(k);
        int64_t mask = dict->table_size - 1;
        int64_t slot = (int64_t)(h & (uint64_t)mask);
        while (1) {
            int64_t idx = dict->indices[slot];
            if (idx == FPY_DICT_EMPTY) break;
            if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], k))
                return 1;
            slot = (slot + 1) & mask;
        }
    }
    return 0;
}

/* OrderedDict is just an alias for our regular dict (which preserves insertion order) */
FpyDict* fastpy_ordereddict_new(void) {
    return fpy_dict_new(4);
}

/* ============================================================
 * copy module — shallow/deep copy of native objects
 * ============================================================ */

/* copy.copy(obj) — shallow copy based on runtime tag */
void fastpy_copy_copy(int32_t tag, int64_t data,
                       int32_t *out_tag, int64_t *out_data) {
    switch (tag) {
        case FPY_TAG_LIST: {
            FpyList *src = (FpyList*)(intptr_t)data;
            FpyList *dst = fpy_list_new(src->length);
            for (int64_t i = 0; i < src->length; i++)
                fpy_list_append(dst, src->items[i]);
            dst->is_tuple = src->is_tuple;
            *out_tag = FPY_TAG_LIST;
            *out_data = (int64_t)(intptr_t)dst;
            break;
        }
        case FPY_TAG_DICT: {
            FpyDict *src = (FpyDict*)(intptr_t)data;
            FpyDict *dst = fpy_dict_new(src->length > 4 ? src->length : 4);
            for (int64_t i = 0; i < src->length; i++)
                fpy_dict_set(dst, src->keys[i], src->values[i]);
            *out_tag = FPY_TAG_DICT;
            *out_data = (int64_t)(intptr_t)dst;
            break;
        }
        case FPY_TAG_SET: {
            FpyDict *src = (FpyDict*)(intptr_t)data;
            FpyDict *dst = fpy_dict_new(src->length > 4 ? src->length : 4);
            FpyValue none_val = fpy_none();
            for (int64_t i = 0; i < src->length; i++)
                fpy_dict_set(dst, src->keys[i], none_val);
            *out_tag = FPY_TAG_SET;
            *out_data = (int64_t)(intptr_t)dst;
            break;
        }
        default:
            /* Scalars (int, float, str, bool, None) are immutable — just pass through */
            *out_tag = tag;
            *out_data = data;
            break;
    }
}

/* copy.deepcopy(obj) — recursive deep copy */
void fastpy_copy_deepcopy(int32_t tag, int64_t data,
                           int32_t *out_tag, int64_t *out_data) {
    switch (tag) {
        case FPY_TAG_LIST: {
            FpyList *src = (FpyList*)(intptr_t)data;
            FpyList *dst = fpy_list_new(src->length);
            dst->is_tuple = src->is_tuple;
            for (int64_t i = 0; i < src->length; i++) {
                int32_t et; int64_t ed;
                fastpy_copy_deepcopy(src->items[i].tag, src->items[i].data.i, &et, &ed);
                FpyValue v; v.tag = et; v.data.i = ed;
                fpy_list_append(dst, v);
            }
            *out_tag = FPY_TAG_LIST;
            *out_data = (int64_t)(intptr_t)dst;
            break;
        }
        case FPY_TAG_DICT: {
            FpyDict *src = (FpyDict*)(intptr_t)data;
            FpyDict *dst = fpy_dict_new(src->length > 4 ? src->length : 4);
            for (int64_t i = 0; i < src->length; i++) {
                int32_t vt; int64_t vd;
                fastpy_copy_deepcopy(src->values[i].tag, src->values[i].data.i, &vt, &vd);
                FpyValue v; v.tag = vt; v.data.i = vd;
                fpy_dict_set(dst, src->keys[i], v);
            }
            *out_tag = FPY_TAG_DICT;
            *out_data = (int64_t)(intptr_t)dst;
            break;
        }
        default:
            *out_tag = tag;
            *out_data = data;
            break;
    }
}

/* ============================================================
 * operator module — function equivalents of operators
 * ============================================================ */

int64_t fastpy_operator_add(int64_t a, int64_t b) { return a + b; }
int64_t fastpy_operator_sub(int64_t a, int64_t b) { return a - b; }
int64_t fastpy_operator_mul(int64_t a, int64_t b) { return a * b; }
int64_t fastpy_operator_floordiv(int64_t a, int64_t b) { return b ? a / b : 0; }
int64_t fastpy_operator_mod(int64_t a, int64_t b) { return b ? a % b : 0; }
int64_t fastpy_operator_neg(int64_t a) { return -a; }
int64_t fastpy_operator_abs(int64_t a) { return a < 0 ? -a : a; }
int64_t fastpy_operator_eq(int64_t a, int64_t b) { return a == b; }
int64_t fastpy_operator_ne(int64_t a, int64_t b) { return a != b; }
int64_t fastpy_operator_lt(int64_t a, int64_t b) { return a < b; }
int64_t fastpy_operator_le(int64_t a, int64_t b) { return a <= b; }
int64_t fastpy_operator_gt(int64_t a, int64_t b) { return a > b; }
int64_t fastpy_operator_ge(int64_t a, int64_t b) { return a >= b; }
int64_t fastpy_operator_not_(int64_t a) { return !a; }
int64_t fastpy_operator_and_(int64_t a, int64_t b) { return a & b; }
int64_t fastpy_operator_or_(int64_t a, int64_t b) { return a | b; }
int64_t fastpy_operator_xor(int64_t a, int64_t b) { return a ^ b; }
int64_t fastpy_operator_lshift(int64_t a, int64_t b) { return a << b; }
int64_t fastpy_operator_rshift(int64_t a, int64_t b) { return a >> b; }

/* itemgetter(key) — returns the key itself for use as a function.
 * In Python, itemgetter returns a callable that extracts items.
 * For AOT, we store the key and implement it via call_ptr. */
int64_t fastpy_operator_itemgetter_int(int64_t item, int64_t key) {
    /* This is called as: getter(item) where getter was created with key.
     * For the simple case of sorting by index, we just return item[key].
     * The caller handles the dispatch. */
    return item;  /* placeholder — real dispatch via compiler */
}

/* ============================================================
 * functools.lru_cache support
 * ============================================================
 * Each cached function gets a slot in a global cache registry.
 * The cache is a dict mapping argument-key (int or string) to result (int64).
 */

#define FPY_LRU_MAX_CACHES 64
static struct {
    FpyDict *cache;
    int64_t maxsize;    /* -1 = unlimited, 0 = no cache (passthrough) */
    int64_t hits;
    int64_t misses;
} fpy_lru_caches[FPY_LRU_MAX_CACHES];
static int fpy_lru_cache_count = 0;

/* Register a new lru_cache slot. Returns cache_id. */
int32_t fastpy_lru_cache_new(int64_t maxsize) {
    int id = fpy_lru_cache_count++;
    if (id >= FPY_LRU_MAX_CACHES) return -1;
    fpy_lru_caches[id].cache = fpy_dict_new(maxsize > 0 ? maxsize : 16);
    fpy_lru_caches[id].maxsize = maxsize;
    fpy_lru_caches[id].hits = 0;
    fpy_lru_caches[id].misses = 0;
    return id;
}

/* Check if a single-int-arg result is cached. Returns 1 if hit. */
int32_t fastpy_lru_cache_get(int32_t cache_id, int64_t key,
                              int64_t *out_result) {
    if (cache_id < 0 || cache_id >= fpy_lru_cache_count) return 0;
    FpyDict *cache = fpy_lru_caches[cache_id].cache;
    FpyValue k; k.tag = FPY_TAG_INT; k.data.i = key;
    uint64_t h = fpy_hash_value(k);
    int64_t mask = cache->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = cache->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(cache->keys[idx], k)) {
            *out_result = cache->values[idx].data.i;
            fpy_lru_caches[cache_id].hits++;
            return 1;
        }
        slot = (slot + 1) & mask;
    }
    fpy_lru_caches[cache_id].misses++;
    return 0;
}

/* Store a result in the cache. Evicts oldest if at maxsize. */
void fastpy_lru_cache_put(int32_t cache_id, int64_t key, int64_t result) {
    if (cache_id < 0 || cache_id >= fpy_lru_cache_count) return;
    FpyDict *cache = fpy_lru_caches[cache_id].cache;
    int64_t maxsize = fpy_lru_caches[cache_id].maxsize;

    /* Simple eviction: if at capacity, clear the entire cache.
     * (A proper LRU would track access order, but for AOT compilation
     * the simple approach is sufficient for most memoization patterns.) */
    if (maxsize > 0 && cache->length >= maxsize) {
        /* Reset the cache */
        free(cache->keys);
        free(cache->values);
        free(cache->indices);
        cache->length = 0;
        cache->capacity = maxsize > 4 ? maxsize : 4;
        cache->keys = (FpyValue*)malloc(sizeof(FpyValue) * cache->capacity);
        cache->values = (FpyValue*)malloc(sizeof(FpyValue) * cache->capacity);
        cache->table_size = 8;
        while (cache->table_size < cache->capacity * 3 / 2)
            cache->table_size *= 2;
        cache->indices = (int64_t*)malloc(sizeof(int64_t) * cache->table_size);
        fpy_dict_init_indices(cache);
    }

    FpyValue k; k.tag = FPY_TAG_INT; k.data.i = key;
    FpyValue v; v.tag = FPY_TAG_INT; v.data.i = result;
    fpy_dict_set(cache, k, v);
}

/* ============================================================
 * Native itertools module
 * ============================================================ */

/* itertools.chain(*iterables) → concatenate lists into one */
FpyList* fastpy_itertools_chain(FpyList *lists_of_lists) {
    /* lists_of_lists is a list of lists */
    int64_t total = 0;
    for (int64_t i = 0; i < lists_of_lists->length; i++) {
        FpyList *sub = (FpyList*)(intptr_t)lists_of_lists->items[i].data.i;
        if (sub) total += sub->length;
    }
    FpyList *result = fpy_list_new(total > 4 ? total : 4);
    for (int64_t i = 0; i < lists_of_lists->length; i++) {
        FpyList *sub = (FpyList*)(intptr_t)lists_of_lists->items[i].data.i;
        if (!sub) continue;
        for (int64_t j = 0; j < sub->length; j++) {
            fpy_list_append(result, sub->items[j]);
        }
    }
    return result;
}

/* itertools.repeat(value, n) → list of value repeated n times */
FpyList* fastpy_itertools_repeat(int32_t tag, int64_t data, int64_t n) {
    FpyList *result = fpy_list_new(n > 4 ? n : 4);
    FpyValue v; v.tag = tag; v.data.i = data;
    for (int64_t i = 0; i < n; i++) {
        fpy_list_append(result, v);
    }
    return result;
}

/* itertools.product(list_a, list_b) → list of (a, b) tuples */
FpyList* fastpy_itertools_product2(FpyList *a, FpyList *b) {
    int64_t n = a->length * b->length;
    FpyList *result = fpy_list_new(n > 4 ? n : 4);
    for (int64_t i = 0; i < a->length; i++) {
        for (int64_t j = 0; j < b->length; j++) {
            FpyList *tuple = fpy_list_new(2);
            tuple->is_tuple = 1;
            fpy_list_append(tuple, a->items[i]);
            fpy_list_append(tuple, b->items[j]);
            FpyValue tv; tv.tag = FPY_TAG_LIST; tv.data.list = tuple;
            fpy_list_append(result, tv);
        }
    }
    return result;
}

/* itertools.zip_longest(a, b, fillvalue=None) → list of (a_i, b_i) tuples */
FpyList* fastpy_itertools_zip_longest(FpyList *a, FpyList *b,
                                       int32_t fill_tag, int64_t fill_data) {
    int64_t n = a->length > b->length ? a->length : b->length;
    FpyList *result = fpy_list_new(n > 4 ? n : 4);
    FpyValue fill; fill.tag = fill_tag; fill.data.i = fill_data;
    for (int64_t i = 0; i < n; i++) {
        FpyList *tuple = fpy_list_new(2);
        tuple->is_tuple = 1;
        fpy_list_append(tuple, i < a->length ? a->items[i] : fill);
        fpy_list_append(tuple, i < b->length ? b->items[i] : fill);
        FpyValue tv; tv.tag = FPY_TAG_LIST; tv.data.list = tuple;
        fpy_list_append(result, tv);
    }
    return result;
}

/* itertools.islice(iterable, stop) → first `stop` elements */
FpyList* fastpy_itertools_islice(FpyList *lst, int64_t start, int64_t stop) {
    if (start < 0) start = 0;
    if (stop > lst->length) stop = lst->length;
    int64_t n = stop - start;
    if (n <= 0) return fpy_list_new(4);
    FpyList *result = fpy_list_new(n);
    for (int64_t i = start; i < stop; i++) {
        fpy_list_append(result, lst->items[i]);
    }
    return result;
}

/* itertools.accumulate(list, func_tag)
 * func_tag: 0=add, 1=mul, 2=max, 3=min
 * Returns running totals. */
FpyList* fastpy_itertools_accumulate(FpyList *lst, int32_t func_tag) {
    if (lst->length == 0) return fpy_list_new(4);
    FpyList *result = fpy_list_new(lst->length);
    fpy_list_append(result, lst->items[0]);
    int64_t acc = lst->items[0].data.i;
    for (int64_t i = 1; i < lst->length; i++) {
        int64_t val = lst->items[i].data.i;
        switch (func_tag) {
            case 0: acc += val; break;  /* add (default) */
            case 1: acc *= val; break;  /* mul */
            case 2: if (val > acc) acc = val; break;  /* max */
            case 3: if (val < acc) acc = val; break;  /* min */
            default: acc += val; break;
        }
        FpyValue v; v.tag = FPY_TAG_INT; v.data.i = acc;
        fpy_list_append(result, v);
    }
    return result;
}

/* itertools.combinations(list, r) → list of r-length tuples */
FpyList* fastpy_itertools_combinations(FpyList *pool, int32_t r) {
    int64_t n = pool->length;
    if (r > n || r < 0) return fpy_list_new(4);
    FpyList *result = fpy_list_new(16);

    /* Simple iterative generation using indices array */
    int32_t *indices = (int32_t*)malloc(sizeof(int32_t) * r);
    for (int32_t i = 0; i < r; i++) indices[i] = i;

    while (1) {
        /* Emit current combination */
        FpyList *combo = fpy_list_new(r);
        combo->is_tuple = 1;
        for (int32_t i = 0; i < r; i++) {
            fpy_list_append(combo, pool->items[indices[i]]);
        }
        FpyValue tv; tv.tag = FPY_TAG_LIST; tv.data.list = combo;
        fpy_list_append(result, tv);

        /* Advance to next combination */
        int32_t i = r - 1;
        while (i >= 0 && indices[i] == (int32_t)(n - r + i)) i--;
        if (i < 0) break;
        indices[i]++;
        for (int32_t j = i + 1; j < r; j++)
            indices[j] = indices[j-1] + 1;
    }
    free(indices);
    return result;
}

/* itertools.permutations(list, r) → list of r-length tuples */
FpyList* fastpy_itertools_permutations(FpyList *pool, int32_t r) {
    int64_t n = pool->length;
    if (r > n || r < 0) return fpy_list_new(4);
    if (r == 0) {
        FpyList *result = fpy_list_new(1);
        FpyList *empty = fpy_list_new(0);
        empty->is_tuple = 1;
        FpyValue tv; tv.tag = FPY_TAG_LIST; tv.data.list = empty;
        fpy_list_append(result, tv);
        return result;
    }

    FpyList *result = fpy_list_new(16);
    /* Generate permutations via recursive backtracking (simple for small r) */
    int32_t *indices = (int32_t*)malloc(sizeof(int32_t) * r);
    int32_t *used = (int32_t*)calloc(n, sizeof(int32_t));

    /* Iterative permutation generation using Heap's concept simplified */
    /* For simplicity, use the combinations+permute approach for small inputs */
    /* Stack-based DFS */
    int32_t depth = 0;
    indices[0] = -1;

    while (depth >= 0) {
        indices[depth]++;
        if (indices[depth] >= (int32_t)n) {
            if (depth > 0) used[indices[depth-1]] = 0;
            depth--;
            if (depth >= 0) used[indices[depth]] = 0;
            continue;
        }
        if (used[indices[depth]]) continue;
        used[indices[depth]] = 1;
        if (depth == r - 1) {
            /* Emit permutation */
            FpyList *perm = fpy_list_new(r);
            perm->is_tuple = 1;
            for (int32_t i = 0; i < r; i++)
                fpy_list_append(perm, pool->items[indices[i]]);
            FpyValue tv; tv.tag = FPY_TAG_LIST; tv.data.list = perm;
            fpy_list_append(result, tv);
            used[indices[depth]] = 0;
        } else {
            depth++;
            indices[depth] = -1;
        }
    }
    free(indices);
    free(used);
    return result;
}

/* ============================================================
 * Native logging module
 * ============================================================
 *
 * Implements a simplified but functional logging system:
 * - Global root logger with configurable level and format
 * - Named loggers (inherit root level)
 * - Levels: DEBUG=10, INFO=20, WARNING=30, ERROR=40, CRITICAL=50
 * - Format strings with %(levelname)s, %(message)s, %(name)s
 * - Output to stderr (default) or file
 */

#define FPY_LOG_DEBUG    10
#define FPY_LOG_INFO     20
#define FPY_LOG_WARNING  30
#define FPY_LOG_ERROR    40
#define FPY_LOG_CRITICAL 50

/* Global logging state */
static int32_t fpy_log_root_level = FPY_LOG_WARNING;  /* default: WARNING */
static const char *fpy_log_format = "%(levelname)s:%(name)s:%(message)s";
static FILE *fpy_log_stream = NULL;  /* NULL = stderr */
static const char *fpy_log_filename = NULL;

/* Named loggers: up to 32 */
#define FPY_LOG_MAX_LOGGERS 32
static struct {
    const char *name;
    int32_t level;      /* -1 = inherit from root */
} fpy_loggers[FPY_LOG_MAX_LOGGERS];
static int fpy_logger_count = 0;

static const char* fpy_level_name(int32_t level) {
    if (level >= FPY_LOG_CRITICAL) return "CRITICAL";
    if (level >= FPY_LOG_ERROR)    return "ERROR";
    if (level >= FPY_LOG_WARNING)  return "WARNING";
    if (level >= FPY_LOG_INFO)     return "INFO";
    return "DEBUG";
}

static FILE* fpy_log_get_stream(void) {
    if (fpy_log_stream) return fpy_log_stream;
    return stderr;
}

/* Format a log message using the configured format string.
 * Supports: %(levelname)s, %(message)s, %(name)s, %(levelno)d */
static const char* fpy_log_format_record(int32_t level, const char *name,
                                          const char *message) {
    const char *fmt = fpy_log_format;
    /* Calculate output size (generous estimate) */
    int64_t msg_len = (int64_t)strlen(message);
    int64_t name_len = (int64_t)strlen(name);
    int64_t fmt_len = (int64_t)strlen(fmt);
    int64_t buf_size = fmt_len + msg_len + name_len + 64;
    char *buf = (char*)malloc(buf_size);
    char *out = buf;
    const char *p = fmt;

    while (*p) {
        if (p[0] == '%' && p[1] == '(') {
            /* Named field: %(fieldname)s or %(fieldname)d */
            const char *field_start = p + 2;
            const char *field_end = strchr(field_start, ')');
            if (field_end && (field_end[1] == 's' || field_end[1] == 'd')) {
                int field_len = (int)(field_end - field_start);
                if (field_len == 9 && strncmp(field_start, "levelname", 9) == 0) {
                    const char *ln = fpy_level_name(level);
                    int64_t ln_len = (int64_t)strlen(ln);
                    memcpy(out, ln, ln_len);
                    out += ln_len;
                } else if (field_len == 7 && strncmp(field_start, "message", 7) == 0) {
                    memcpy(out, message, msg_len);
                    out += msg_len;
                } else if (field_len == 4 && strncmp(field_start, "name", 4) == 0) {
                    memcpy(out, name, name_len);
                    out += name_len;
                } else if (field_len == 7 && strncmp(field_start, "levelno", 7) == 0) {
                    out += sprintf(out, "%d", level);
                } else if (field_len == 8 && strncmp(field_start, "filename", 8) == 0) {
                    const char *fn = "<compiled>";
                    memcpy(out, fn, 10);
                    out += 10;
                } else if (field_len == 6 && strncmp(field_start, "lineno", 6) == 0) {
                    out += sprintf(out, "0");
                } else {
                    /* Unknown field — output as-is */
                    *out++ = '%';
                    *out++ = '(';
                    memcpy(out, field_start, field_len);
                    out += field_len;
                    *out++ = ')';
                    *out++ = field_end[1];
                }
                p = field_end + 2;  /* skip past ')s' or ')d' */
                continue;
            }
        }
        *out++ = *p++;
    }
    *out = '\0';
    return buf;
}

/* logging.basicConfig(level=X, format=fmt, filename=fn) */
void fastpy_logging_basicConfig(int32_t level, const char *fmt,
                                 const char *filename) {
    if (level >= 0) fpy_log_root_level = level;
    if (fmt && fmt[0] != '\0') fpy_log_format = fmt;
    if (filename && filename[0] != '\0') {
        fpy_log_filename = filename;
        fpy_log_stream = fopen(filename, "a");
    }
}

/* Core log function */
void fastpy_logging_log(int32_t level, const char *name, const char *message) {
    /* Check if this level passes the filter */
    int32_t effective_level = fpy_log_root_level;

    /* Check for named logger with custom level */
    for (int i = 0; i < fpy_logger_count; i++) {
        if (strcmp(fpy_loggers[i].name, name) == 0) {
            if (fpy_loggers[i].level >= 0)
                effective_level = fpy_loggers[i].level;
            break;
        }
    }

    if (level < effective_level) return;

    /* Format and output */
    const char *formatted = fpy_log_format_record(level, name, message);
    FILE *stream = fpy_log_get_stream();
    fprintf(stream, "%s\n", formatted);
    fflush(stream);
    free((void*)formatted);
}

/* Convenience functions for root logger */
void fastpy_logging_debug(const char *msg) {
    fastpy_logging_log(FPY_LOG_DEBUG, "root", msg);
}

void fastpy_logging_info(const char *msg) {
    fastpy_logging_log(FPY_LOG_INFO, "root", msg);
}

void fastpy_logging_warning(const char *msg) {
    fastpy_logging_log(FPY_LOG_WARNING, "root", msg);
}

void fastpy_logging_error(const char *msg) {
    fastpy_logging_log(FPY_LOG_ERROR, "root", msg);
}

void fastpy_logging_critical(const char *msg) {
    fastpy_logging_log(FPY_LOG_CRITICAL, "root", msg);
}

/* logging.getLogger(name) → logger_id (index into registry) */
int32_t fastpy_logging_getLogger(const char *name) {
    /* Check if logger already exists */
    for (int i = 0; i < fpy_logger_count; i++) {
        if (strcmp(fpy_loggers[i].name, name) == 0)
            return i;
    }
    /* Create new logger */
    if (fpy_logger_count >= FPY_LOG_MAX_LOGGERS) return 0;
    int id = fpy_logger_count++;
    fpy_loggers[id].name = name;
    fpy_loggers[id].level = -1;  /* inherit from root */
    return id;
}

/* logger.setLevel(level) */
void fastpy_logging_setLevel(int32_t logger_id, int32_t level) {
    if (logger_id >= 0 && logger_id < fpy_logger_count)
        fpy_loggers[logger_id].level = level;
}

/* logger.debug/info/warning/error/critical(msg) */
void fastpy_logging_logger_log(int32_t logger_id, int32_t level, const char *msg) {
    const char *name = "root";
    if (logger_id >= 0 && logger_id < fpy_logger_count)
        name = fpy_loggers[logger_id].name;
    fastpy_logging_log(level, name, msg);
}

/* Format a message with args: logging.info("Hello %s, age %d", name, age) */
const char* fastpy_logging_format_msg(const char *fmt, FpyList *args) {
    if (!args || args->length == 0) return fmt;
    /* Simple % formatting with positional args */
    int64_t buf_size = (int64_t)strlen(fmt) + 256;
    for (int64_t i = 0; i < args->length; i++) {
        if (args->items[i].tag == FPY_TAG_STR)
            buf_size += (int64_t)strlen(args->items[i].data.s);
        else
            buf_size += 32;
    }
    char *buf = (char*)malloc(buf_size);
    char *out = buf;
    const char *p = fmt;
    int arg_idx = 0;

    while (*p) {
        if (*p == '%' && p[1] != '\0' && p[1] != '(' && arg_idx < args->length) {
            char spec = p[1];
            FpyValue val = args->items[arg_idx++];
            if (spec == 's') {
                if (val.tag == FPY_TAG_STR) {
                    int64_t len = (int64_t)strlen(val.data.s);
                    memcpy(out, val.data.s, len);
                    out += len;
                } else if (val.tag == FPY_TAG_INT) {
                    out += sprintf(out, "%lld", (long long)val.data.i);
                } else {
                    memcpy(out, "?", 1);
                    out += 1;
                }
            } else if (spec == 'd' || spec == 'i') {
                out += sprintf(out, "%lld", (long long)val.data.i);
            } else if (spec == 'f') {
                out += sprintf(out, "%f", val.data.f);
            } else {
                *out++ = *p;
                *out++ = p[1];
                arg_idx--;  /* didn't consume an arg */
            }
            p += 2;
        } else {
            *out++ = *p++;
        }
    }
    *out = '\0';
    return buf;
}

/* ═══════════════════════════════════════════════════════════════════════
 * Weak references
 *
 * A weak reference points to an FpyObj without preventing its collection.
 * When the target is destroyed, all its weakrefs are invalidated (target
 * set to NULL). Deref on a dead weakref returns None.
 *
 * The FpyWeakRef is itself refcounted and heap-allocated. It participates
 * in the target's weakref_list (singly-linked). Creating a weakref
 * inserts it at the head of the list; destruction removes it.
 * ═══════════════════════════════════════════════════════════════════════ */

/* Create a weak reference to target. The target must be an FpyObj*.
 * Returns the weakref as an i64 (pointer cast). The caller stores it
 * as an FPY_TAG_OBJ value. */
FpyWeakRef* fpy_weakref_new(FpyObj *target) {
    FpyWeakRef *wr = (FpyWeakRef*)malloc(sizeof(FpyWeakRef));
    wr->refcount = 1;
    wr->magic = FPY_WEAKREF_MAGIC;
    wr->target = target;
    wr->callback = 0;
    wr->callback_tag = 0;
    /* Insert at head of target's weakref list */
    wr->next = target->weakref_list;
    target->weakref_list = wr;
    return wr;
}

/* Dereference a weak reference. Returns the target as an FpyObj*, or
 * NULL if the target has been collected. The caller checks NULL and
 * produces None. */
FpyObj* fpy_weakref_deref(FpyWeakRef *wr) {
    if (!wr || wr->magic != FPY_WEAKREF_MAGIC) return NULL;
    return wr->target;  /* NULL if invalidated */
}

/* Check if a weakref is alive (target not yet collected). */
int32_t fpy_weakref_alive(FpyWeakRef *wr) {
    if (!wr || wr->magic != FPY_WEAKREF_MAGIC) return 0;
    return (wr->target != NULL) ? 1 : 0;
}

/* Free a weakref. Unlinks it from the target's list (if target is alive). */
void fpy_weakref_destroy(FpyWeakRef *wr) {
    if (!wr) return;
    /* Unlink from target's list if target is still alive */
    if (wr->target) {
        FpyObj *obj = wr->target;
        FpyWeakRef **pp = &obj->weakref_list;
        while (*pp) {
            if (*pp == wr) { *pp = wr->next; break; }
            pp = &(*pp)->next;
        }
    }
    free(wr);
}
