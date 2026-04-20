/*
 * fastpy runtime object system implementation.
 */

#include "objects.h"
#include "threading.h"
#include "gc.h"
#include <math.h>

/* Forward declarations */
void fastpy_tuple_write(FpyList *tuple);
void fastpy_dict_write(FpyDict *dict);
void fastpy_obj_write(FpyObj *obj);

/* External exception-raising API (defined in runtime.c) */
extern void fastpy_raise(int exc_type, const char *msg);

/* Exception type constants (mirror runtime.c) */
#define FPY_EXC_VALUEERROR     2
#define FPY_EXC_TYPEERROR      3
#define FPY_EXC_INDEXERROR     4
#define FPY_EXC_KEYERROR       5

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
    int64_t captures[8];
} FpyClosure;

/* Forward declarations for recursive destroy and class registry */
static void fpy_list_destroy(FpyList *list);
static void fpy_dict_destroy(FpyDict *dict);
void fpy_rc_decref(int32_t tag, int64_t data);
extern FpyClassDef fpy_classes[];  /* defined later in this file */

/* --- Destructors for refcounted objects --- */

static void fpy_list_destroy(FpyList *list) {
    fpy_gc_untrack(&list->gc_node);
    for (int64_t i = 0; i < list->length; i++) {
        fpy_rc_decref(list->items[i].tag, list->items[i].data.i);
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
             * FpyObj has its magic (0x4F424A53) deep in the struct.
             * Check closure magic first (most common in OBJ-tagged values). */
            void *ptr = (void*)(intptr_t)data;
            if (*(int32_t*)ptr == FPY_CLOSURE_MAGIC) {
                fpy_incref(&((FpyClosure*)ptr)->refcount);
            } else {
                FpyObj *obj = (FpyObj*)ptr;
                if (obj->magic == FPY_OBJ_MAGIC)
                    fpy_incref(&obj->refcount);
                /* else: CPython PyObject* — don't touch */
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
            /* Check if this is a closure (not an FpyObj) */
            if (*(int32_t*)ptr == FPY_CLOSURE_MAGIC) {
                FpyClosure *c = (FpyClosure*)ptr;
                if (fpy_decref(&c->refcount)) {
                    /* Decref captured values, then free closure */
                    for (int i = 0; i < c->n_captures; i++)
                        fpy_rc_decref(FPY_TAG_INT, c->captures[i]);
                    free(c);
                }
                break;
            }
            FpyObj *obj = (FpyObj*)ptr;
            if (obj->magic != FPY_OBJ_MAGIC) break;  /* CPython PyObject*, don't touch */
            if (fpy_decref(&obj->refcount)) {
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
        fprintf(stderr, "IndexError: list index out of range\n");
        exit(1);
    }
    return list->items[index];
}

void fpy_list_set(FpyList *list, int64_t index, FpyValue value) {
    FPY_LOCK(list);
    if (index < 0) index += list->length;
    if (index < 0 || index >= list->length) {
        FPY_UNLOCK(list);
        fprintf(stderr, "IndexError: list assignment index out of range\n");
        exit(1);
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
        case FPY_TAG_STR:
            snprintf(buf, bufsize, "'%s'", val.data.s);
            break;
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
            extern const char* fastpy_obj_to_str(FpyObj*);
            const char *s = fastpy_obj_to_str(val.data.obj);
            snprintf(buf, bufsize, "%s", s);
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

/* Return the str string (allocated) for an FpyValue — strings pass
 * through without quotes; other types use repr. */
const char* fastpy_fv_str(int32_t tag, int64_t data) {
    if (tag == FPY_TAG_STR) return (const char*)data;
    char *buf = (char*)malloc(4096);
    fpy_value_repr(_pack_fv(tag, data), buf, 4096);
    return buf;
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
        case FPY_TAG_OBJ: return data != 0;
        case FPY_TAG_SET: {
            FpyDict *s = (FpyDict*)data;
            return s && s->length != 0;
        }
    }
    return 0;
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
    if (start >= stop) return fpy_list_new(0);
    int64_t rlen = stop - start;
    FpyList *result = fpy_list_new(rlen);
    for (int64_t i = start; i < stop; i++) {
        fpy_list_append(result, list->items[i]);
    }
    return result;
}

/* Slice with step (e.g. x[::2] or x[::-1]) */
FpyList* fastpy_list_slice_step(FpyList *list, int64_t start, int64_t stop,
                                int64_t step, int64_t has_start, int64_t has_stop) {
    int64_t len = list->length;
    if (step == 0) { fprintf(stderr, "ValueError: slice step cannot be zero\n"); exit(1); }

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
    fprintf(stderr, "KeyError\n");
    exit(1);
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
    fprintf(stderr, "KeyError: '%s'\n", key);
    exit(1);
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
    fprintf(stderr, "KeyError\n");
    exit(1);
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
    fprintf(stderr, "KeyError\n");
    exit(1);
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
    return c;
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
int64_t fastpy_closure_call_list(FpyClosure *c, FpyList *args) {
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

/* --- Mutable closure cells --- */

/* A cell holds a mutable int64 value on the heap */
typedef struct {
    int32_t refcount;
    int64_t value;
} FpyCell;

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
        fprintf(stderr, "IndexError: pop from empty list\n");
        exit(1);
    }
    list->length--;
    int64_t result = list->items[list->length].data.i;
    FPY_UNLOCK(list);
    return result;
}

void fastpy_list_delete_at(FpyList *list, int64_t index) {
    FPY_LOCK(list);
    if (index < 0) index += list->length;
    if (index < 0 || index >= list->length) {
        FPY_UNLOCK(list);
        fprintf(stderr, "IndexError: list index out of range\n");
        exit(1);
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
    fprintf(stderr, "KeyError: '%s'\n", key);
    exit(1);
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
    fprintf(stderr, "ValueError: list.remove(x): x not in list\n");
    exit(1);
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
    fprintf(stderr, "ValueError: list.remove(x): x not in list\n");
    exit(1);
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
    fprintf(stderr, "KeyError: '%s'\n", key);
    exit(1);
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
    fprintf(stderr, "KeyError: '%s'\n", key);
    exit(1);
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
    if ((int64_t)slen >= width) return _strdup(s);
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
    if ((int64_t)slen >= width) return _strdup(s);
    char *result = (char*)malloc(width + 1);
    memcpy(result, s, slen);
    for (int64_t i = slen; i < width; i++) result[i] = ' ';
    result[width] = '\0';
    return result;
}

const char* fastpy_str_rjust(const char *s, int64_t width) {
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return _strdup(s);
    char *result = (char*)malloc(width + 1);
    int64_t pad = width - (int64_t)slen;
    for (int64_t i = 0; i < pad; i++) result[i] = ' ';
    memcpy(result + pad, s, slen);
    result[width] = '\0';
    return result;
}

const char* fastpy_str_zfill(const char *s, int64_t width) {
    size_t slen = strlen(s);
    if ((int64_t)slen >= width) return _strdup(s);
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

FpyList* fastpy_str_split_max(const char *s, const char *sep, int64_t max_split) {
    FpyList *result = fpy_list_new(0);
    size_t sep_len = strlen(sep);
    size_t s_len = strlen(s);
    if (sep_len == 0) {
        char *copy = _strdup(s);
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
    return _strdup(start);
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

/* List copy — shallow copy of the list */
FpyList* fastpy_list_copy(FpyList *list) {
    FpyList *result = fpy_list_new(list->length);
    for (int64_t i = 0; i < list->length; i++)
        fpy_list_append(result, list->items[i]);
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
                        || va.tag == FPY_TAG_FLOAT;
            int num_b = vb.tag == FPY_TAG_INT || vb.tag == FPY_TAG_BOOL
                        || vb.tag == FPY_TAG_FLOAT;
            if (num_a && num_b) {
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
static int fpy_class_count = 0;

int fastpy_register_class(const char *name, int parent_id) {
    int id = fpy_class_count++;
    fpy_classes[id].class_id = id;
    fpy_classes[id].name = name;
    fpy_classes[id].parent_id = parent_id;
    fpy_classes[id].methods = NULL;
    fpy_classes[id].method_count = 0;
    fpy_classes[id].slot_count = 0;
    fpy_classes[id].slot_names = NULL;
    return id;
}

/* Set the number of pre-declared attribute slots for a class.
 * Called after register_class with the slot count determined at compile time. */
void fastpy_set_class_slot_count(int class_id, int slot_count) {
    fpy_classes[class_id].slot_count = slot_count;
    fpy_classes[class_id].slot_names = (const char**)calloc(
        slot_count, sizeof(const char*));
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
    memset(&obj->gc_node, 0, sizeof(FpyGCNode));
    obj->gc_node.gc_type = FPY_GC_TYPE_OBJ;
    fpy_gc_track(&obj->gc_node);
    fpy_gc_maybe_collect();
    obj->magic = FPY_OBJ_MAGIC;
    obj->class_id = class_id;
    if (fpy_threading_mode == FPY_THREADING_FREE) fpy_mutex_init(&obj->lock);
    obj->dynamic_attrs = NULL;
    if (sc > 0) {
        obj->slots = (FpyValue*)(obj + 1);
        for (int i = 0; i < sc; i++) {
            obj->slots[i].tag = FPY_TAG_NONE;
            obj->slots[i].data.i = 0;
        }
    } else {
        obj->slots = NULL;
    }
    return obj;
}

/* Fast-path static slot access. Slot index is known at compile time. */
void fastpy_obj_set_slot(FpyObj *obj, int slot, int32_t tag, int64_t data) {
    obj->slots[slot].tag = tag;
    obj->slots[slot].data.i = data;
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
    /* Check static slots first (covers all compiler-known attrs) */
    int slot = fpy_find_slot(obj->class_id, name);
    if (slot >= 0) {
        obj->slots[slot] = v;
        return;
    }
    /* Dynamic attr fallback — lazily allocate the side table on first use. */
    FpyObjAttrs *a = obj->dynamic_attrs;
    if (a != NULL) {
        for (int i = 0; i < a->count; i++) {
            if (a->names[i] == name
                    || strcmp(a->names[i], name) == 0) {
                a->values[i] = v;
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
    fprintf(stderr, "AttributeError: '%s' object has no attribute '%s'\n",
            fpy_classes[obj->class_id].name, name);
    exit(1);
}

/* Get attribute as string representation (works for any type).
 * Still used by the f-string path for `{self.attr}` expansion. */
/* Call a method on an object — returns i64 */
int64_t fastpy_obj_call_method0(FpyObj *obj, const char *name) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        fprintf(stderr, "AttributeError: '%s' object has no method '%s'\n",
                fpy_classes[obj->class_id].name, name);
        exit(1);
    }
    return ((FpyMethodFunc)m->func)(obj);
}

int64_t fastpy_obj_call_method1(FpyObj *obj, const char *name, int64_t a) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        fprintf(stderr, "AttributeError: '%s' object has no method '%s'\n",
                fpy_classes[obj->class_id].name, name);
        exit(1);
    }
    return ((FpyMethod1Func)m->func)(obj, a);
}

int64_t fastpy_obj_call_method2(FpyObj *obj, const char *name, int64_t a, int64_t b) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        fprintf(stderr, "AttributeError: '%s' object has no method '%s'\n",
                fpy_classes[obj->class_id].name, name);
        exit(1);
    }
    return ((FpyMethod2Func)m->func)(obj, a, b);
}

int64_t fastpy_obj_call_method3(FpyObj *obj, const char *name, int64_t a, int64_t b, int64_t c) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        fprintf(stderr, "AttributeError: '%s' object has no method '%s'\n",
                fpy_classes[obj->class_id].name, name);
        exit(1);
    }
    return ((FpyMethod3Func)m->func)(obj, a, b, c);
}

int64_t fastpy_obj_call_method4(FpyObj *obj, const char *name, int64_t a, int64_t b, int64_t c, int64_t d) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        fprintf(stderr, "AttributeError: '%s' object has no method '%s'\n",
                fpy_classes[obj->class_id].name, name);
        exit(1);
    }
    return ((FpyMethod4Func)m->func)(obj, a, b, c, d);
}

/* Call method returning double */
typedef double (*FpyMethodDoubleFunc)(FpyObj *self);
typedef double (*FpyMethodDouble1Func)(FpyObj *self, int64_t a);

double fastpy_obj_call_method0_double(FpyObj *obj, const char *name) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) { fprintf(stderr, "AttributeError: no method '%s'\n", name); exit(1); }
    return ((FpyMethodDoubleFunc)m->func)(obj);
}

double fastpy_obj_call_method1_double(FpyObj *obj, const char *name, int64_t a) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) { fprintf(stderr, "AttributeError: no method '%s'\n", name); exit(1); }
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
