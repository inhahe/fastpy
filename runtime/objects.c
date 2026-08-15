/*
 * fastpy runtime object system implementation.
 */

#include "objects.h"
#include "threading.h"
#include "gc.h"
#include "bigint.h"
#include <math.h>
#include <assert.h>  /* static_assert macro (C11); MSVC provides it implicitly */

/* The codegen computes inline slot addresses as (FpyValue*)(obj + 1) + idx,
 * relying on sizeof(FpyObj) == 56 on x64 (lock field removed).
 * If the struct layout changes, this will fire at compile time rather than
 * silently corrupting memory. */
static_assert(sizeof(FpyObj) == 56,
    "FpyObj size changed -- update fpy_obj_type in codegen.py to match");
static_assert(sizeof(FpyValue) == 16,
    "FpyValue size changed -- update fpy_val_type in codegen.py to match");

/* Forward declarations */
void fastpy_tuple_write(FpyList *tuple);
void fastpy_dict_write(FpyDict *dict);
void fastpy_obj_write(FpyObj *obj);
FpyMethodDef* fastpy_find_method(int class_id, const char *name);
/* Defined later in this file; declared here so callers earlier in the TU
 * don't rely on an implicit declaration (rejected by strict C99+/clang). */
int fastpy_dict_has_key(FpyDict *dict, const char *key);
int32_t fastpy_dict_has_int_key(FpyDict *dict, int64_t key);
static int _fpy_ws_fwd(const unsigned char *p);

/* External APIs (defined in runtime.c) */
extern int64_t fastpy_str_len(const char *);

/* fastpy_raise / fastpy_exc_pending and the FPY_EXC_* codes. */
#include "exceptions.h"

/* External: return-tag side channel (defined in runtime.c) */
extern void fastpy_set_ret_tag(int32_t tag);

/* Thread-local buffer for formatted error messages. Only one exception
 * can be pending per thread, so a single buffer is safe. */
static FPY_THREAD_LOCAL char _err_buf[256];

/* --- Object free-list allocator ---
 * Maintain per-class free lists so freed objects can be reused without
 * calling malloc.  Each free-list entry repurposes the `dynamic_attrs`
 * pointer as the "next" link.
 * This eliminates malloc/free overhead in tight loops that create
 * and destroy many objects of the same class.
 *
 * Keyed by class_id (not slot_count) because the native-slot optimization
 * means classes with the same slot_count can have different allocation
 * sizes — per-class keying is always safe. */
#define FPY_OBJ_FREELIST_MAX    64   /* max cached objects per class */
static FpyObj* fpy_obj_freelist[FPY_MAX_CLASSES];
static int     fpy_obj_freelist_count[FPY_MAX_CLASSES];

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
    uint8_t has_vararg;        /* 1 if function uses *args — args must be packed into list */
    uint8_t has_kwarg;         /* 1 if function uses **kwargs — first param is dict */
    int n_defaults;            /* number of default parameter values */
    int64_t defaults[8];       /* default values for last n_defaults params */
    int64_t captures[8];
    const char **param_names;  /* parameter names (n_params entries), for **kwargs dispatch */
} FpyClosure;
/* Declared here (right after the type) so early callers in this TU use the
 * real signature instead of an implicit/void* declaration. */
int64_t fastpy_closure_call1(FpyClosure *c, int64_t a);

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
        case FPY_TAG_LIST:
            fpy_incref(&((FpyList*)(intptr_t)data)->refcount); break;
        case FPY_TAG_SET:
            fpy_incref(&((FpyDict*)(intptr_t)data)->refcount); break;
        case FPY_TAG_DICT:
            fpy_incref(&((FpyDict*)(intptr_t)data)->refcount); break;
        case FPY_TAG_OBJ: {
            /* Could be FpyObj, FpyClosure, or CPython PyObject*.
             * FpyObj is the overwhelmingly common case, so check its
             * magic first (at offset 32) to avoid the multi-step
             * closure/plausibility dispatch.  Reading at offset 32 is
             * safe — the current code already does this for FpyObj, and
             * closures + PyObject* are always ≥ 32 bytes. */
            FpyObj *obj = (FpyObj*)(intptr_t)data;
            if (obj->magic == FPY_OBJ_MAGIC) {
                fpy_incref(&obj->refcount);
            } else if (*(int32_t*)(intptr_t)data == FPY_CLOSURE_MAGIC) {
                fpy_incref(&((FpyClosure*)(intptr_t)data)->refcount);
            } else {
                fpy_bridge_pyobj_incref((void*)(intptr_t)data);
            }
            break;
        }
        case FPY_TAG_STR:
            fpy_str_incref((const char*)(intptr_t)data); break;
        case FPY_TAG_BYTES:
            fpy_bytes_incref((const char*)(intptr_t)data); break;
        case FPY_TAG_BIGINT:
            /* Must mirror the FPY_TAG_BIGINT arm of fpy_rc_decref below.
             * Omitting it made every BigInt incref a silent no-op while
             * the matching decref still decremented, so a BigInt with two
             * owners (e.g. a list element also bound to a loop variable)
             * was freed by the first release and the second one read
             * freed memory.  See BUG-BIGINT-INCREF-MISSING. */
            fpy_incref(&((FpyBigInt*)(intptr_t)data)->refcount); break;
        default: break;  /* INT, FLOAT, BOOL, NONE — not heap-allocated.
                          * COMPLEX and DECIMAL are heap-allocated but are
                          * refcounted by neither incref nor decref, so they
                          * leak rather than dangle — DEBT-COMPLEX-DECIMAL-
                          * NOT-REFCOUNTED. */
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
        case FPY_TAG_BYTES:
            if (fpy_bytes_decref((const char*)(intptr_t)data)) {
                FpyBytes *h = fpy_bytes_header((const char*)(intptr_t)data);
                if (h) free(h);
            }
            break;
        case FPY_TAG_LIST:
            if (fpy_decref(&((FpyList*)(intptr_t)data)->refcount))
                fpy_list_destroy((FpyList*)(intptr_t)data);
            break;
        case FPY_TAG_SET:
            if (fpy_decref(&((FpyDict*)(intptr_t)data)->refcount))
                fpy_dict_destroy((FpyDict*)(intptr_t)data);
            break;
        case FPY_TAG_DICT:
            if (fpy_decref(&((FpyDict*)(intptr_t)data)->refcount))
                fpy_dict_destroy((FpyDict*)(intptr_t)data);
            break;
        case FPY_TAG_OBJ: {
            /* Could be FpyObj, FpyClosure, or CPython PyObject*.
             * FpyObj is the overwhelmingly common case, so check its
             * magic first (at offset 32) — this is a single comparison
             * on the hot path instead of the multi-step dispatch.
             * Reading at offset 32 is safe: closures and PyObject*
             * are always ≥ 32 bytes, and the previous code already
             * read obj->magic for the same pointer types. */
            FpyObj *obj = (FpyObj*)(intptr_t)data;
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
                        /* Invoke callback if set.  The callback is stored
                         * as an FpyValue (tag + data).  Tag 0 (NONE) means
                         * no callback.  Otherwise it should be a closure
                         * pointer we can call with the weakref as argument. */
                        if (wr->callback_tag != 0 && wr->callback != 0) {
                            /* callback(weakref) — call with the weakref
                             * itself as the single argument, per CPython
                             * weakref semantics. (Declared at file scope.) */
                            fastpy_closure_call1(
                                (FpyClosure*)(intptr_t)wr->callback,
                                (int64_t)(intptr_t)wr);
                        }
                        wr = next;
                    }
                    /* Free slots: only decref BOXED slots (native slots
                     * hold scalars — no heap references to release). */
                    {
                        int _cid = obj->class_id;
                        int nn = fpy_classes[_cid].n_native_slots;
                        int nb = fpy_classes[_cid].slot_count - nn;
                        if (nb > 0) {
                            FpyValue *boxed = FPY_OBJ_BOXED_SLOTS(obj, nn);
                            for (int i = 0; i < nb; i++)
                                FPY_VAL_DECREF(boxed[i]);
                        }
                        /* slots are contiguous with obj (malloc'd together), don't free separately */
                    }
                    if (obj->dynamic_attrs) {
                        for (int i = 0; i < obj->dynamic_attrs->count; i++)
                            FPY_VAL_DECREF(obj->dynamic_attrs->values[i]);
                        free(obj->dynamic_attrs->names);
                        free(obj->dynamic_attrs->values);
                        free(obj->dynamic_attrs);
                        obj->dynamic_attrs = NULL;
                    }
                    /* Push to per-class free-list if possible, else free */
                    int _cid2 = obj->class_id;
                    if (_cid2 < FPY_MAX_CLASSES
                            && fpy_obj_freelist_count[_cid2] < FPY_OBJ_FREELIST_MAX) {
                        obj->dynamic_attrs = (FpyObjAttrs*)fpy_obj_freelist[_cid2];
                        fpy_obj_freelist[_cid2] = obj;
                        fpy_obj_freelist_count[_cid2]++;
                    } else {
                        free(obj);
                    }
                }
                break;
            }
            /* Not FpyObj — check closure magic at offset 0 */
            if (*(int32_t*)(intptr_t)data == FPY_CLOSURE_MAGIC) {
                FpyClosure *c = (FpyClosure*)(intptr_t)data;
                if (fpy_decref(&c->refcount)) {
                    /* Free captured values: cells get freed, others decrefd */
                    for (int i = 0; i < c->n_captures; i++) {
                        if (c->capture_is_cell & (1 << i)) {
                            /* Cell pointer — decref (may be shared between closures) */
                            FpyCell *cell = (FpyCell*)(intptr_t)c->captures[i];
                            if (cell && --cell->refcount <= 0) free(cell);
                        }
                        /* Regular captures: the value was borrowed from the
                         * outer scope; don't decref (the scope owns it) */
                    }
                    free(c);
                }
                break;
            }
            /* Not a closure, not an FpyObj — treat as CPython PyObject* */
            fpy_bridge_pyobj_decref((void*)(intptr_t)data);
            break;
        }
        case FPY_TAG_BIGINT: {
            FpyBigInt *bi = (FpyBigInt*)(intptr_t)data;
            if (bi && fpy_decref(&bi->refcount))
                fpy_bigint_free(bi);
            break;
        }
        default: break;  /* Must stay arm-for-arm with fpy_rc_incref above:
                          * a tag handled here but not there turns every
                          * balanced incref/decref pair in the program into a
                          * use-after-free.  INT, FLOAT, BOOL and NONE fall
                          * through on purpose (unboxed); COMPLEX and DECIMAL
                          * fall through by omission and leak — DEBT-COMPLEX-
                          * DECIMAL-NOT-REFCOUNTED. */
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

/* Mark an existing FpyList as a list (clear tuple flag).
   Used by star unpack: first, *rest = tuple → rest must be a list. */
void fastpy_list_mark_list(FpyList *list) {
    if (list) list->is_tuple = 0;
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

/* Is this OBJ-tagged pointer actually a pure-mode pathlib.Path?
 *
 * Codegen tags a Path OBJ, so every generic OBJ consumer below (print / write /
 * str / repr) receives a pointer it cannot type. Its fallback is the CPython
 * bridge, which in a pure build is a stub that RAISES — so without this check
 * `print(Path(...))` fails even though the value is perfectly printable.
 * runtime/pathlib_pure.c (compiled only into pure builds) can answer the
 * question from the Path header's magic word; in bridged builds a Path really
 * IS a PyObject*, so the bridge fallback is correct and this returns NULL.
 *
 * Returns the path text, or NULL if it is not a Path. */
#ifdef FPY_PURE_MODE
extern const char *fpy_pure_path_text(const void *p);
static inline const char *_fpy_obj_as_path_text(const void *p) {
    return fpy_pure_path_text(p);
}
#else
static inline const char *_fpy_obj_as_path_text(const void *p) {
    (void)p;
    return NULL;
}
#endif

/* --- Shared string-repr quoting. BUG-REPR-ALWAYS-SINGLE-QUOTES.
 *
 * CPython *picks* the quote character instead of always escaping: a string
 * that contains ' but no " is repr'd in double quotes, so repr("it's") is
 * "it's" and not 'it\'s'. Only when both quote characters appear does the
 * single quote get a backslash. fastpy had two independent repr routines
 * (fpy_value_repr's STR case and fastpy_str_repr) that both hardcoded a
 * single quote, and that also disagreed with each other about control
 * characters — one emitted \xNN, the other passed the raw byte through into
 * the output. Both now share the two routines below, so there is one answer
 * to "what does a string look like when repr'd". */

/* Which quote CPython would wrap this string in. */
static char fpy_repr_quote(const char *s, size_t len) {
    int has_sq = 0, has_dq = 0;
    for (size_t i = 0; i < len; i++) {
        if (s[i] == '\'') has_sq = 1;
        else if (s[i] == '"') has_dq = 1;
    }
    return (has_sq && !has_dq) ? '"' : '\'';
}

/* Write the escaped *body* of a repr (no surrounding quotes) into buf and
 * return the count written. Stops early rather than overrunning, always
 * leaving the caller room for the closing quote and the terminator. Only the
 * chosen quote is escaped — the other one is literal, which is the whole
 * point of choosing. Bytes >= 128 pass through: they are UTF-8 continuation
 * bytes of a character CPython would print as itself. */
static int fpy_repr_escape_body(const char *s, size_t len, char quote,
                                char *buf, int bufsize) {
    int pos = 0;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        if (pos > bufsize - 6) break;  /* worst case is \xNN + quote + NUL */
        if (c == '\\')                      { buf[pos++] = '\\'; buf[pos++] = '\\'; }
        else if (c == (unsigned char)quote) { buf[pos++] = '\\'; buf[pos++] = (char)c; }
        else if (c == '\n')                 { buf[pos++] = '\\'; buf[pos++] = 'n'; }
        else if (c == '\r')                 { buf[pos++] = '\\'; buf[pos++] = 'r'; }
        else if (c == '\t')                 { buf[pos++] = '\\'; buf[pos++] = 't'; }
        else if (c < 32 || c == 127)
            pos += snprintf(buf + pos, (size_t)(bufsize - pos), "\\x%02x", c);
        else buf[pos++] = (char)c;
    }
    return pos;
}

void fpy_value_repr(FpyValue val, char *buf, int bufsize) {
    switch (val.tag) {
        case FPY_TAG_INT:
            snprintf(buf, bufsize, "%lld", (long long)val.data.i);
            break;
        case FPY_TAG_FLOAT:
            format_float(val.data.f, buf, bufsize);
            break;
        case FPY_TAG_STR: {
            const char *s = val.data.s ? val.data.s : "";
            size_t slen = strlen(s);
            if (bufsize < 4) { if (bufsize > 0) buf[0] = '\0'; break; }
            char q = fpy_repr_quote(s, slen);
            int pos = 0;
            buf[pos++] = q;
            pos += fpy_repr_escape_body(s, slen, q, buf + pos, bufsize - pos);
            buf[pos++] = q;
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
            /* Pure-mode pathlib.Path: check first, since its magic is neither
             * the closure magic nor in the small-int range the FpyObj probe
             * uses, so it would otherwise fall through to the bridge (which
             * raises in a pure build). CPython reprs a Path as PosixPath('…'). */
            const char *_pt = _fpy_obj_as_path_text(ptr);
            if (_pt) {
                snprintf(buf, bufsize, "PosixPath('%s')", _pt);
                break;
            }
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
            /* NOT free(): unlike its siblings above, fpy_complex_to_str
             * returns fpy_str_buf's *header-backed* buffer, whose char*
             * points 8 bytes into the malloc block.  Handing that to free()
             * aborted the process with STATUS_HEAP_CORRUPTION (0xc0000374) —
             * `print([1 + 2j])` died before printing anything, while
             * `print(c[0])` was fine because it never reached this repr.
             * BUG-COMPLEX-REPR-FREES-HEADERED-STRING. */
            fpy_rc_decref(FPY_TAG_STR, (int64_t)(intptr_t)s);
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
            /* bytes repr: b'...'. Same quote-choosing rule as str — CPython
             * reprs b"it's" with double quotes — but the escaping differs:
             * a byte >= 127 has no character to print, so it stays \xNN. */
            const char *data = val.data.s;
            size_t len = data ? (size_t)fpy_bytes_len(data) : 0;  /* embedded-null safe */
            if (bufsize < 5) { if (bufsize > 0) buf[0] = '\0'; break; }
            char q = data ? fpy_repr_quote(data, len) : '\'';
            int pos = 0;
            buf[pos++] = 'b';
            buf[pos++] = q;
            for (size_t i = 0; i < len && pos < bufsize - 6; i++) {
                unsigned char c = (unsigned char)data[i];
                if (c == '\\')                      { buf[pos++] = '\\'; buf[pos++] = '\\'; }
                else if (c == (unsigned char)q)     { buf[pos++] = '\\'; buf[pos++] = (char)c; }
                else if (c == '\n')                 { buf[pos++] = '\\'; buf[pos++] = 'n'; }
                else if (c == '\r')                 { buf[pos++] = '\\'; buf[pos++] = 'r'; }
                else if (c == '\t')                 { buf[pos++] = '\\'; buf[pos++] = 't'; }
                else if (c >= 32 && c < 127)        { buf[pos++] = (char)c; }
                else pos += snprintf(buf + pos, (size_t)(bufsize - pos), "\\x%02x", c);
            }
            buf[pos++] = q;
            buf[pos] = '\0';
            break;
        }
    }
}

/* Raise KeyError for a missing key. BUG-KEYERROR-STR-NOT-REPR.
 *
 * KeyError is the one built-in whose __str__ is not the message but
 * `repr(args[0])` — CPython prints `KeyError: 'a'` for a string key and
 * `KeyError: 5` for an int one. fastpy has no `args`, only the message that
 * *is* str(e), so the repr has to be applied at the raise site. Doing it in
 * one helper is what keeps the rule from being reapplied inconsistently: the
 * dozen dict/set miss paths had drifted into passing the raw key text, a bare
 * "KeyError", or a snprintf'd integer, three different answers to one
 * question.
 *
 * This also covers the message-shaped ones — `set().pop()` raises
 * KeyError('pop from an empty set'), and CPython quotes that string like any
 * other argument, so those sites pass a string value through here too rather
 * than special-casing themselves.
 *
 * A stack buffer suffices because fastpy_raise copies the message into
 * header-backed storage before returning.
 *
 * FPY_NOINLINE because that buffer must stay out of the callers' frames: the
 * dict lookups that call this are hot, and inlining put 256 bytes on their
 * stack, which is what made MSVC give them /GS cookie code on the path where
 * the key *is* found.  See the macro's comment in objects.h. */
FPY_NOINLINE static void fpy_raise_key_error(FpyValue key) {
    char buf[256];
    fpy_value_repr(key, buf, sizeof(buf));
    fastpy_raise(FPY_EXC_KEYERROR, buf);
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
    char *buf = fpy_str_buf(4096);
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
        /* Pure-mode pathlib.Path: printable natively, and the bridge below
         * would raise. Copy the text so the caller owns a normal FpyString
         * rather than a pointer into the Path's own header block. */
        const char *pt = _fpy_obj_as_path_text(ptr);
        if (pt) return fpy_str_from_cstr(pt);
        /* CPython PyObject* — use PyObject_Str */
        extern const char* fpy_bridge_pyobj_str(void*);
        return fpy_bridge_pyobj_str(ptr);
    }
    char *buf = fpy_str_buf(4096);
    fpy_value_repr(_pack_fv(tag, data), buf, 4096);
    return buf;
}

/* FpyValue comparison — op: 0=eq, 1=ne, 2=lt, 3=le, 4=gt, 5=ge.
 * Returns 1 if the comparison is true, 0 otherwise. */
static const char *_fpy_tag_typename(int32_t tag) {
    switch (tag) {
        case FPY_TAG_INT:   return "int";
        case FPY_TAG_FLOAT: return "float";
        case FPY_TAG_STR:   return "str";
        case FPY_TAG_BOOL:  return "bool";
        case FPY_TAG_NONE:  return "NoneType";
        case FPY_TAG_LIST:  return "list";
        case FPY_TAG_OBJ:   return "object";
        case FPY_TAG_DICT:  return "dict";
        case FPY_TAG_BYTES: return "bytes";
        case FPY_TAG_SET:   return "set";
        case FPY_TAG_BIGINT: return "int";
        case FPY_TAG_COMPLEX: return "complex";
        case FPY_TAG_DECIMAL: return "Decimal";
        default: return "object";
    }
}

/* Check if two tags are compatible for ordering comparisons.
 * Compatible pairs: INT/BOOL (integer subtypes), and any + FLOAT
 * (promoted to float comparison). Everything else is incompatible. */
static int _fpy_tags_order_compatible(int32_t tag1, int32_t tag2) {
    if (tag1 == tag2) return 1;
    /* INT and BOOL are interchangeable for ordering */
    if ((tag1 == FPY_TAG_INT || tag1 == FPY_TAG_BOOL) &&
        (tag2 == FPY_TAG_INT || tag2 == FPY_TAG_BOOL)) return 1;
    /* FLOAT compares with INT/BOOL */
    if (tag1 == FPY_TAG_FLOAT &&
        (tag2 == FPY_TAG_INT || tag2 == FPY_TAG_BOOL)) return 1;
    if (tag2 == FPY_TAG_FLOAT &&
        (tag1 == FPY_TAG_INT || tag1 == FPY_TAG_BOOL)) return 1;
    /* BIGINT with INT/BOOL/FLOAT — all four are numbers, and CPython orders
     * any pair of them.  FLOAT was missing here, so `2 ** 80 < 1.5` raised
     * TypeError instead of answering. */
    if (tag1 == FPY_TAG_BIGINT &&
        (tag2 == FPY_TAG_INT || tag2 == FPY_TAG_BOOL
         || tag2 == FPY_TAG_FLOAT)) return 1;
    if (tag2 == FPY_TAG_BIGINT &&
        (tag1 == FPY_TAG_INT || tag1 == FPY_TAG_BOOL
         || tag1 == FPY_TAG_FLOAT)) return 1;
    /* DECIMAL with INT/BOOL/FLOAT — CPython orders a Decimal against any of
     * them.  COMPLEX with them too, but only for *equality*: `(1+0j) == 1` is
     * True while `(1+0j) < 1` is a TypeError.  This predicate cannot express
     * "equality only", and answering 0 here would make the equality silently
     * False instead, so the ordering rejection lives in the COMPLEX arm of
     * fastpy_fv_compare (which also has to reject complex-vs-complex ordering,
     * something the tag1 == tag2 shortcut above lets through).
     * BUG-FV-COMPARE-NO-DECIMAL-COMPLEX. */
    if (tag1 == FPY_TAG_DECIMAL &&
        (tag2 == FPY_TAG_INT || tag2 == FPY_TAG_BOOL
         || tag2 == FPY_TAG_FLOAT)) return 1;
    if (tag2 == FPY_TAG_DECIMAL &&
        (tag1 == FPY_TAG_INT || tag1 == FPY_TAG_BOOL
         || tag1 == FPY_TAG_FLOAT)) return 1;
    if (tag1 == FPY_TAG_COMPLEX &&
        (tag2 == FPY_TAG_INT || tag2 == FPY_TAG_BOOL
         || tag2 == FPY_TAG_FLOAT)) return 1;
    if (tag2 == FPY_TAG_COMPLEX &&
        (tag1 == FPY_TAG_INT || tag1 == FPY_TAG_BOOL
         || tag1 == FPY_TAG_FLOAT)) return 1;
    return 0;
}

/* A Decimal as a double, for comparison against a FLOAT operand.
 *
 * Inexact in the same way `float(Decimal(...))` is, and CPython's own
 * Decimal-vs-float comparison is *exact* — it converts the float to a Decimal
 * rather than the other way round.  The difference only shows up past 2^53 or
 * for a decimal fraction no double represents, and doing it exactly needs a
 * float→Decimal constructor the runtime does not have yet.
 * Logged as BUG-DECIMAL-FLOAT-COMPARE-INEXACT. */
static double _fpy_decimal_to_double(const FpyDecimal *d) {
    double v = (double)d->coefficient * pow(10.0, (double)d->exponent);
    return d->sign < 0 ? -v : v;
}

/* A finite double whose magnitude is at least 2^63, as an exact BigInt.
 *
 * Such a double is always an integer, and always exactly `mantissa * 2^k`:
 * `frexp` splits it into m * 2^e with 0.5 <= |m| < 1, `ldexp(m, 53)` is then
 * an integer of at most 53 bits (so it fits an i64 exactly), and the leftover
 * exponent is a shift.  No rounding happens anywhere. */
static FpyBigInt *_fpy_bigint_from_large_double(double d) {
    int e;
    double m = frexp(d, &e);
    int64_t mant = (int64_t)ldexp(m, 53);
    FpyBigInt *b = fpy_bigint_from_i64(mant);
    e -= 53;                       /* |d| >= 2^63 means e >= 64, so e > 0 */
    if (e > 0) {
        FpyBigInt *sh = fpy_bigint_from_i64(e);
        FpyBigInt *r = fpy_bigint_lshift(b, sh);
        fpy_bigint_free(b);
        fpy_bigint_free(sh);
        return r;
    }
    return b;
}

/* Compare a BigInt against a double: -1 / 0 / 1 for a < d, a == d, a > d,
 * and 2 for "unordered" (NaN), which every comparison must answer False to.
 *
 * Converting the BigInt to a double and comparing would be wrong in exactly
 * the cases that matter: every integer past 2^53 rounds, so `2**80 + 1` and
 * `2.0**80` would compare equal.  Converting the *double* to an integer is
 * lossless in both directions — below 2^63 through an i64 with the fraction
 * breaking the tie, and above it through the mantissa/exponent split. */
static int _fpy_bigint_cmp_double(FpyBigInt *a, double d) {
    if (isnan(d)) return 2;
    if (isinf(d)) return d > 0 ? -1 : 1;
    double t = trunc(d);
    if (t >= -9223372036854775808.0 && t < 9223372036854775808.0) {
        FpyBigInt *bt = fpy_bigint_from_i64((int64_t)t);
        int c = fpy_bigint_cmp(a, bt);
        fpy_bigint_free(bt);
        if (c != 0) return c;
        double frac = d - t;          /* a == trunc(d), so the fraction decides */
        if (frac > 0.0) return -1;
        if (frac < 0.0) return 1;
        return 0;
    }
    FpyBigInt *bd = _fpy_bigint_from_large_double(d);
    int c = fpy_bigint_cmp(a, bd);
    fpy_bigint_free(bd);
    return c;
}

int32_t fastpy_fv_compare(int32_t tag1, int64_t data1,
                           int32_t tag2, int64_t data2, int32_t op) {
    /* Cross-type check: for ordering ops (< <= > >=), incompatible
     * types must raise TypeError just like CPython.  Equality (== !=)
     * between different types always returns False/True. */
    if (tag1 != tag2) {
        int is_ordering = (op >= 2);  /* 2=Lt 3=LtE 4=Gt 5=GtE */
        if (is_ordering && !_fpy_tags_order_compatible(tag1, tag2)) {
            static char _cmp_err[256];
            const char *ops[] = {"==","!=","<","<=",">",">="};
            snprintf(_cmp_err, sizeof(_cmp_err),
                     "'%s' not supported between instances of '%s' and '%s'",
                     ops[op], _fpy_tag_typename(tag1), _fpy_tag_typename(tag2));
            fastpy_raise(FPY_EXC_TYPEERROR, _cmp_err);
            return 0;
        }
        /* Equality between incompatible types → always unequal */
        if (!is_ordering && !_fpy_tags_order_compatible(tag1, tag2)) {
            return (op == 1);  /* NotEq → 1, Eq → 0 */
        }
    }

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
    /* BigInt comparison: at least one is BIGINT.  This has to come before the
     * FLOAT and default-integer branches, both of which would read the BigInt
     * *pointer* as a number — the default one compared the two pointers, so
     * `-b == -c` on equal BigInts was False, and the float one bitcast a
     * pointer to a double.  BUG-BIGINT-FV-RESULT-NOT-CONSUMED. */
    if (tag1 == FPY_TAG_BIGINT || tag2 == FPY_TAG_BIGINT) {
        int cmp;
        if (tag1 == FPY_TAG_BIGINT && tag2 == FPY_TAG_BIGINT) {
            cmp = fpy_bigint_cmp((FpyBigInt*)(intptr_t)data1,
                                 (FpyBigInt*)(intptr_t)data2);
        } else if (tag1 == FPY_TAG_FLOAT || tag2 == FPY_TAG_FLOAT) {
            double d;
            int64_t fdata = (tag1 == FPY_TAG_FLOAT) ? data1 : data2;
            memcpy(&d, &fdata, sizeof(d));
            FpyBigInt *big = (FpyBigInt*)(intptr_t)
                ((tag1 == FPY_TAG_BIGINT) ? data1 : data2);
            cmp = _fpy_bigint_cmp_double(big, d);
            if (cmp == 2) return (op == 1);   /* NaN: only != is true */
            if (tag2 == FPY_TAG_BIGINT) cmp = -cmp;
        } else {
            /* The other side is INT or BOOL — promote it and compare.
             * Not named `small`: Windows' rpcndr.h has `#define small char`. */
            int64_t narrow = (tag1 == FPY_TAG_BIGINT) ? data2 : data1;
            if ((tag1 == FPY_TAG_BIGINT ? tag2 : tag1) == FPY_TAG_BOOL)
                narrow = (narrow != 0);
            FpyBigInt *tmp = fpy_bigint_from_i64(narrow);
            FpyBigInt *big = (FpyBigInt*)(intptr_t)
                ((tag1 == FPY_TAG_BIGINT) ? data1 : data2);
            cmp = (tag1 == FPY_TAG_BIGINT) ? fpy_bigint_cmp(big, tmp)
                                           : fpy_bigint_cmp(tmp, big);
            fpy_bigint_free(tmp);
        }
        switch (op) {
            case 0: return cmp == 0;
            case 1: return cmp != 0;
            case 2: return cmp < 0;
            case 3: return cmp <= 0;
            case 4: return cmp > 0;
            case 5: return cmp >= 0;
        }
        return 0;
    }
    /* Decimal comparison: at least one is DECIMAL.  Like the BigInt block
     * above, this has to precede the FLOAT and default-integer branches, both
     * of which read the Decimal *pointer* as a number — the default one
     * compared the two addresses, so `[Decimal("1.5"), 1][0] == Decimal("1.5")`
     * was False and `w[0] < w[1]` answered on allocation order.
     * BUG-FV-COMPARE-NO-DECIMAL-COMPLEX. */
    if (tag1 == FPY_TAG_DECIMAL || tag2 == FPY_TAG_DECIMAL) {
        int cmp;
        if (tag1 == FPY_TAG_FLOAT || tag2 == FPY_TAG_FLOAT) {
            double dv;
            int64_t fdata = (tag1 == FPY_TAG_FLOAT) ? data1 : data2;
            memcpy(&dv, &fdata, sizeof(dv));
            double dd = _fpy_decimal_to_double((FpyDecimal*)(intptr_t)
                ((tag1 == FPY_TAG_DECIMAL) ? data1 : data2));
            if (isnan(dv)) return (op == 1);   /* NaN: only != is true */
            double lhs = (tag1 == FPY_TAG_DECIMAL) ? dd : dv;
            double rhs = (tag1 == FPY_TAG_DECIMAL) ? dv : dd;
            cmp = (lhs < rhs) ? -1 : (lhs > rhs) ? 1 : 0;
        } else {
            /* The other side is DECIMAL, INT or BOOL.  Only the promoted one
             * is owned here; the caller's Decimal is not ours to free. */
            FpyDecimal *la = (tag1 == FPY_TAG_DECIMAL)
                ? (FpyDecimal*)(intptr_t)data1 : fpy_decimal_from_int(data1);
            FpyDecimal *ra = (tag2 == FPY_TAG_DECIMAL)
                ? (FpyDecimal*)(intptr_t)data2 : fpy_decimal_from_int(data2);
            cmp = fpy_decimal_compare(la, ra);
            if (tag1 != FPY_TAG_DECIMAL) free(la);
            if (tag2 != FPY_TAG_DECIMAL) free(ra);
        }
        switch (op) {
            case 0: return cmp == 0;
            case 1: return cmp != 0;
            case 2: return cmp < 0;
            case 3: return cmp <= 0;
            case 4: return cmp > 0;
            case 5: return cmp >= 0;
        }
        return 0;
    }
    /* Complex comparison: equality only, exactly as CPython.  Ordering is a
     * TypeError even between two complexes — which the tag1 == tag2 shortcut
     * in the cross-type check above lets through, so it has to be rejected
     * here.  BUG-FV-COMPARE-NO-DECIMAL-COMPLEX. */
    if (tag1 == FPY_TAG_COMPLEX || tag2 == FPY_TAG_COMPLEX) {
        if (op >= 2) {
            static char _cx_err[256];
            const char *ops[] = {"==","!=","<","<=",">",">="};
            snprintf(_cx_err, sizeof(_cx_err),
                     "'%s' not supported between instances of '%s' and '%s'",
                     ops[op], _fpy_tag_typename(tag1), _fpy_tag_typename(tag2));
            fastpy_raise(FPY_EXC_TYPEERROR, _cx_err);
            return 0;
        }
        double r1, i1, r2, i2;
        if (tag1 == FPY_TAG_COMPLEX) {
            FpyComplex *c = (FpyComplex*)(intptr_t)data1;
            r1 = c->real; i1 = c->imag;
        } else if (tag1 == FPY_TAG_FLOAT) {
            memcpy(&r1, &data1, sizeof(r1)); i1 = 0.0;
        } else {
            r1 = (double)data1; i1 = 0.0;
        }
        if (tag2 == FPY_TAG_COMPLEX) {
            FpyComplex *c = (FpyComplex*)(intptr_t)data2;
            r2 = c->real; i2 = c->imag;
        } else if (tag2 == FPY_TAG_FLOAT) {
            memcpy(&r2, &data2, sizeof(r2)); i2 = 0.0;
        } else {
            r2 = (double)data2; i2 = 0.0;
        }
        int eq = (r1 == r2 && i1 == i2);
        return (op == 0) ? eq : !eq;
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
            /* Native FpyObj — call __bool__ if defined, then __len__, else true */
            {
                typedef int64_t (*FpyMethodFunc)(FpyObj*);
                FpyMethodDef *m = fastpy_find_method(obj->class_id, "__bool__");
                if (m) {
                    int64_t r = ((FpyMethodFunc)m->func)(obj);
                    return (int32_t)(r & 0xFFFFFFFF) != 0;
                }
                m = fastpy_find_method(obj->class_id, "__len__");
                if (m) {
                    int64_t r = ((FpyMethodFunc)m->func)(obj);
                    return r != 0;
                }
            }
            return 1;
        }
        case FPY_TAG_SET: {
            FpyDict *s = (FpyDict*)data;
            return s && s->length != 0;
        }
        case FPY_TAG_BIGINT: {
            FpyBigInt *bi = (FpyBigInt*)(intptr_t)data;
            return bi && !fpy_bigint_is_zero(bi);
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
            return s ? fastpy_str_len(s) : 0;
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

/* FpyValue iteration element — runtime dispatch for for-loops on
 * runtime-typed values (FVALUE/MIXED).  Given a container (tag+data)
 * and a positional index, returns the iteration element.
 *   LIST/TUPLE: list->items[idx]  (same as list_get_fv)
 *   DICT/SET:   dict->keys[idx]   (same as dict_key_fv)
 *   STR:        str[idx] as single-char string
 * This avoids duplicating the tag-dispatch logic in the compiler. */
extern const char* fastpy_str_index(const char*, int64_t);
void fastpy_fv_iter_get(int32_t tag, int64_t data, int64_t index,
                         int32_t *out_tag, int64_t *out_data) {
    switch (tag) {
        case FPY_TAG_LIST: {
            FpyList *lst = (FpyList*)(intptr_t)data;
            if (!lst || index < 0 || index >= lst->length) {
                *out_tag = FPY_TAG_NONE;
                *out_data = 0;
                return;
            }
            *out_tag = lst->items[index].tag;
            *out_data = lst->items[index].data.i;
            return;
        }
        case FPY_TAG_DICT:
        case FPY_TAG_SET: {
            FpyDict *d = (FpyDict*)(intptr_t)data;
            if (!d || index < 0 || index >= d->length) {
                *out_tag = FPY_TAG_NONE;
                *out_data = 0;
                return;
            }
            *out_tag = d->keys[index].tag;
            *out_data = d->keys[index].data.i;
            return;
        }
        case FPY_TAG_STR: {
            const char *s = (const char*)(intptr_t)data;
            const char *ch = fastpy_str_index(s, index);
            *out_tag = FPY_TAG_STR;
            *out_data = (int64_t)(intptr_t)ch;
            return;
        }
        case FPY_TAG_BYTES: {
            const char *b = (const char*)(intptr_t)data;
            int64_t len = b ? (int64_t)strlen(b) : 0;
            if (index < 0) index += len;
            if (index < 0 || index >= len) {
                *out_tag = FPY_TAG_NONE;
                *out_data = 0;
                return;
            }
            *out_tag = FPY_TAG_INT;
            *out_data = (int64_t)(unsigned char)b[index];
            return;
        }
    }
    *out_tag = FPY_TAG_NONE;
    *out_data = 0;
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

/* FpyValue slice — runtime dispatch for `c[a:b:s]` where the container's kind
 * is only known at runtime (an untyped parameter, a json.loads result, ...).
 * The static paths pick fastpy_str_slice or fastpy_list_slice by the compiler's
 * guess, which silently produced an empty string when a list arrived on the
 * str path.  Slicing preserves the container's kind, so the tag is echoed back
 * rather than derived from the elements. */
FpyList* fastpy_list_slice(FpyList*, int64_t, int64_t, int64_t, int64_t);
FpyList* fastpy_list_slice_step(FpyList*, int64_t, int64_t, int64_t,
                                int64_t, int64_t);
extern const char* fastpy_str_slice(const char*, int64_t, int64_t,
                                    int64_t, int64_t);
extern const char* fastpy_str_slice_step(const char*, int64_t, int64_t,
                                         int64_t, int64_t, int64_t);
extern const char* fastpy_bytes_slice(const char*, int64_t, int64_t,
                                      int64_t, int64_t);
extern const char* fastpy_bytes_slice_step(const char*, int64_t, int64_t,
                                           int64_t, int64_t, int64_t);

void fastpy_fv_slice(int32_t c_tag, int64_t c_data,
                     int64_t start, int64_t stop, int64_t step,
                     int64_t has_start, int64_t has_stop, int64_t has_step,
                     int32_t *out_tag, int64_t *out_data) {
    switch (c_tag) {
        case FPY_TAG_LIST: {
            /* Tuples carry FPY_TAG_LIST at runtime, so this arm covers both. */
            FpyList *lst = (FpyList*)(intptr_t)c_data;
            FpyList *res;
            if (has_step) {
                res = fastpy_list_slice_step(lst, start, stop, step,
                                             has_start, has_stop);
            } else {
                res = fastpy_list_slice(lst, start, stop,
                                        has_start, has_stop);
            }
            *out_tag = c_tag;
            *out_data = (int64_t)(intptr_t)res;
            return;
        }
        case FPY_TAG_STR: {
            const char *s = (const char*)(intptr_t)c_data;
            const char *res;
            if (has_step) {
                res = fastpy_str_slice_step(s, start, stop, step,
                                            has_start, has_stop);
            } else {
                res = fastpy_str_slice(s, start, stop, has_start, has_stop);
            }
            *out_tag = c_tag;
            *out_data = (int64_t)(intptr_t)res;
            return;
        }
        case FPY_TAG_BYTES: {
            /* Byte-indexed and FpyBytes-backed: the str path is code-point
             * indexed and hands back an FpyString, which a BYTES tag then
             * makes every fpy_bytes_len probe out of bounds.
             * BUG-BYTES-SLICE-VIA-STR. */
            const char *b = (const char*)(intptr_t)c_data;
            const char *res;
            if (has_step) {
                res = fastpy_bytes_slice_step(b, start, stop, step,
                                              has_start, has_stop);
            } else {
                res = fastpy_bytes_slice(b, start, stop, has_start, has_stop);
            }
            *out_tag = c_tag;
            *out_data = (int64_t)(intptr_t)res;
            return;
        }
    }
    fastpy_raise(FPY_EXC_TYPEERROR, "object is not subscriptable");
    *out_tag = FPY_TAG_NONE;
    *out_data = 0;
}

/* FpyValue containment check — runtime dispatch for `x in container`.
 * Returns 1 if found, 0 if not found. */
int32_t fastpy_fv_contains(int32_t c_tag, int64_t c_data,
                             int32_t v_tag, int64_t v_data) {
    switch (c_tag) {
        case FPY_TAG_LIST: {
            FpyList *lst = (FpyList*)(intptr_t)c_data;
            if (!lst) return 0;
            for (int64_t i = 0; i < lst->length; i++) {
                FpyValue elem = lst->items[i];
                if (elem.tag != v_tag) continue;
                if (v_tag == FPY_TAG_STR) {
                    if (strcmp(elem.data.s, (const char*)(intptr_t)v_data) == 0)
                        return 1;
                } else if (v_tag == FPY_TAG_INT || v_tag == FPY_TAG_BOOL) {
                    if (elem.data.i == v_data) return 1;
                } else if (v_tag == FPY_TAG_FLOAT) {
                    double a, b;
                    memcpy(&a, &elem.data.i, sizeof(double));
                    memcpy(&b, &v_data, sizeof(double));
                    if (a == b) return 1;
                }
            }
            return 0;
        }
        case FPY_TAG_DICT:
        case FPY_TAG_SET: {
            FpyDict *d = (FpyDict*)(intptr_t)c_data;
            if (!d) return 0;
            if (v_tag == FPY_TAG_STR) {
                return fastpy_dict_has_key(d, (const char*)(intptr_t)v_data);
            } else {
                return fastpy_dict_has_int_key(d, v_data);
            }
        }
        case FPY_TAG_STR: {
            const char *haystack = (const char*)(intptr_t)c_data;
            if (!haystack || v_tag != FPY_TAG_STR) return 0;
            const char *needle = (const char*)(intptr_t)v_data;
            return strstr(haystack, needle) != NULL ? 1 : 0;
        }
    }
    return 0;
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
    /* String * Int/Bool or Int/Bool * String → repeat */
    if (lt == FPY_TAG_STR && (rt == FPY_TAG_INT || rt == FPY_TAG_BOOL) && op == 2) {
        const char *result = fastpy_str_repeat((const char*)ld, rd);
        *out_tag = FPY_TAG_STR;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    if ((lt == FPY_TAG_INT || lt == FPY_TAG_BOOL) && rt == FPY_TAG_STR && op == 2) {
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
    /* Bytes + Bytes → concat.  Header-backed (fpy_bytes_alloc) and
     * length-aware (fpy_bytes_len) so embedded null bytes survive and the
     * result carries an FpyBytes header (refcount=1) for correct free. */
    if (lt == FPY_TAG_BYTES && rt == FPY_TAG_BYTES && op == 0) {
        const char *a = (const char*)(intptr_t)ld;
        const char *b = (const char*)(intptr_t)rd;
        int64_t la = a ? fpy_bytes_len(a) : 0;
        int64_t lb = b ? fpy_bytes_len(b) : 0;
        char *result = fpy_bytes_alloc(la + lb);
        if (la > 0) memcpy(result, a, (size_t)la);
        if (lb > 0) memcpy(result + la, b, (size_t)lb);
        *out_tag = FPY_TAG_BYTES;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    /* Bytes * Int/Bool or Int/Bool * Bytes → repeat */
    if (lt == FPY_TAG_BYTES && (rt == FPY_TAG_INT || rt == FPY_TAG_BOOL) && op == 2) {
        const char *a = (const char*)(intptr_t)ld;
        int64_t la = a ? fpy_bytes_len(a) : 0;
        int64_t n = rd > 0 ? rd : 0;
        int64_t total = la * n;
        char *result = fpy_bytes_alloc(total);
        for (int64_t i = 0; i < n; i++)
            if (la > 0) memcpy(result + i * la, a, (size_t)la);
        *out_tag = FPY_TAG_BYTES;
        *out_data = (int64_t)(intptr_t)result;
        return;
    }
    if ((lt == FPY_TAG_INT || lt == FPY_TAG_BOOL) && rt == FPY_TAG_BYTES && op == 2) {
        const char *a = (const char*)(intptr_t)rd;
        int64_t la = a ? fpy_bytes_len(a) : 0;
        int64_t n = ld > 0 ? ld : 0;
        int64_t total = la * n;
        char *result = fpy_bytes_alloc(total);
        for (int64_t i = 0; i < n; i++)
            if (la > 0) memcpy(result + i * la, a, (size_t)la);
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
    /* Bitwise / shift ops (op: 6=and, 7=or, 8=xor, 9=lshift, 10=rshift)
     * on integer-like operands.  Promote everything to BigInt so Python's
     * infinite-width two's-complement / floor-shift semantics are honored
     * uniformly (the bigint helpers implement them), then demote the
     * result back to a native INT when it fits.  This is the dynamic
     * fallback path (statically-typed int&int uses the inline i64 path in
     * codegen); correctness matters more than the bigint alloc overhead. */
    if (op >= 6 && op <= 10
        && (lt == FPY_TAG_INT || lt == FPY_TAG_BOOL || lt == FPY_TAG_BIGINT)
        && (rt == FPY_TAG_INT || rt == FPY_TAG_BOOL || rt == FPY_TAG_BIGINT)) {
        extern FpyBigInt* fpy_bigint_from_i64(int64_t);
        extern FpyBigInt* fpy_bigint_and(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_or(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_xor(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_lshift(FpyBigInt*, FpyBigInt*);
        extern FpyBigInt* fpy_bigint_rshift(FpyBigInt*, FpyBigInt*);
        extern int fpy_bigint_fits_i64(FpyBigInt*);
        extern int64_t fpy_bigint_to_i64(FpyBigInt*, int*);
        extern void fpy_bigint_free(FpyBigInt*);
        /* Only the operands we promote via from_i64 are owned here and must
         * be freed; a caller-provided BigInt (tag==BIGINT) is not. */
        int l_own = (lt != FPY_TAG_BIGINT);
        int r_own = (rt != FPY_TAG_BIGINT);
        FpyBigInt *la = (lt == FPY_TAG_BIGINT) ? (FpyBigInt*)(intptr_t)ld
            : fpy_bigint_from_i64((lt == FPY_TAG_BOOL) ? (ld != 0) : ld);
        FpyBigInt *ra = (rt == FPY_TAG_BIGINT) ? (FpyBigInt*)(intptr_t)rd
            : fpy_bigint_from_i64((rt == FPY_TAG_BOOL) ? (rd != 0) : rd);
        FpyBigInt *result = NULL;
        switch (op) {
            case 6:  result = fpy_bigint_and(la, ra);    break;
            case 7:  result = fpy_bigint_or(la, ra);     break;
            case 8:  result = fpy_bigint_xor(la, ra);    break;
            case 9:  result = fpy_bigint_lshift(la, ra); break;
            case 10: result = fpy_bigint_rshift(la, ra); break;
            default: break;
        }
        if (l_own) fpy_bigint_free(la);
        if (r_own) fpy_bigint_free(ra);
        if (result) {
            if (fpy_bigint_fits_i64(result)) {
                int ov = 0;
                int64_t iv = fpy_bigint_to_i64(result, &ov);
                fpy_bigint_free(result);
                /* `&`, `|` and `^` of two bools stay a bool in CPython --
                 * `True & False` is `False`, not `0` -- while the shifts
                 * widen to int (`True << 1` is `2`), and so does a mixed
                 * bool/int pair (`True | 3` is `3`).  Tagging every result
                 * INT printed `0` and `1` where CPython prints `False` and
                 * `True`.  BUG-BOOL-PLUS-INT-YIELDS-FLOAT. */
                *out_tag = (op <= 8 && lt == FPY_TAG_BOOL && rt == FPY_TAG_BOOL)
                    ? FPY_TAG_BOOL : FPY_TAG_INT;
                *out_data = iv;
            } else {
                *out_tag = FPY_TAG_BIGINT;
                *out_data = (int64_t)(intptr_t)result;
            }
            return;
        }
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
        extern int fpy_bigint_truediv(FpyBigInt*, FpyBigInt*, double*);
        extern int fpy_bigint_to_double(FpyBigInt*, double*);
        extern int fpy_bigint_fits_i64(FpyBigInt*);
        extern int64_t fpy_bigint_to_i64(FpyBigInt*, int*);
        extern void fpy_bigint_free(FpyBigInt*);

        /* A float on the other side makes this float arithmetic — (2 ** 80) +
         * 1.5 is a float in Python.  It has to be split off *before* the
         * promotion below, which would otherwise hand fpy_bigint_from_i64 the
         * float's bit pattern and call it an integer.  Converting the BigInt to
         * a double and re-entering lets the float arm below do the work once. */
        if (lt == FPY_TAG_FLOAT || rt == FPY_TAG_FLOAT) {
            FpyBigInt *b = (FpyBigInt*)(intptr_t)(lt == FPY_TAG_BIGINT ? ld : rd);
            double bd = 0.0;
            if (fpy_bigint_to_double(b, &bd) != 0) {
                fastpy_raise(FPY_EXC_OVERFLOWERROR, "int too large to convert to float");
                *out_tag = FPY_TAG_NONE; *out_data = 0;
                return;
            }
            int64_t bits; memcpy(&bits, &bd, sizeof(double));
            if (lt == FPY_TAG_BIGINT)
                fastpy_fv_binop(FPY_TAG_FLOAT, bits, rt, rd, op, out_tag, out_data);
            else
                fastpy_fv_binop(lt, ld, FPY_TAG_FLOAT, bits, op, out_tag, out_data);
            return;
        }
        /* Anything else that is not integer-like has no BigInt handler; leave it
         * to the TypeError guard below rather than promoting its payload. */
        if ((lt == FPY_TAG_BIGINT || lt == FPY_TAG_INT || lt == FPY_TAG_BOOL)
            && (rt == FPY_TAG_BIGINT || rt == FPY_TAG_INT || rt == FPY_TAG_BOOL)) {
            /* Only the operands promoted here are owned and must be freed; a
             * caller-provided BigInt still belongs to whoever holds the value. */
            int l_own = (lt != FPY_TAG_BIGINT);
            int r_own = (rt != FPY_TAG_BIGINT);
            FpyBigInt *la = (lt == FPY_TAG_BIGINT) ? (FpyBigInt*)(intptr_t)ld
                : fpy_bigint_from_i64((lt == FPY_TAG_BOOL) ? (ld != 0) : ld);
            FpyBigInt *ra = (rt == FPY_TAG_BIGINT) ? (FpyBigInt*)(intptr_t)rd
                : fpy_bigint_from_i64((rt == FPY_TAG_BOOL) ? (rd != 0) : rd);
            if (op == 3) {
                /* True division is the one BigInt op whose result is not a
                 * BigInt, so it returns here rather than through the
                 * demote-to-INT tail below.
                 * BUG-BIGINT-TRUEDIV-UNIMPLEMENTED: this used to be left
                 * unimplemented and fall out of the arm entirely, reaching the
                 * CPython bridge, which took the BigInt pointer for a
                 * PyObject* and crashed. */
                double q = 0.0;
                int rc = fpy_bigint_truediv(la, ra, &q);
                if (l_own) fpy_bigint_free(la);
                if (r_own) fpy_bigint_free(ra);
                if (rc != 0) {
                    fastpy_raise(rc == 1 ? FPY_EXC_ZERODIVISION : FPY_EXC_OVERFLOWERROR,
                                 rc == 1 ? "division by zero"
                                         : "integer division result too large for a float");
                    *out_tag = FPY_TAG_NONE; *out_data = 0;
                    return;
                }
                *out_tag = FPY_TAG_FLOAT;
                memcpy(out_data, &q, sizeof(double));
                return;
            }
            FpyBigInt *result = NULL;
            switch (op) {
                case 0: result = fpy_bigint_add(la, ra); break;
                case 1: result = fpy_bigint_sub(la, ra); break;
                case 2: result = fpy_bigint_mul(la, ra); break;
                case 4: result = fpy_bigint_floordiv(la, ra); break;
                case 5: result = fpy_bigint_mod(la, ra); break;
                default: break;
            }
            if (l_own) fpy_bigint_free(la);
            if (r_own) fpy_bigint_free(ra);
            if (result) {
                /* Demote to INT if the result fits in i64 — this avoids
                 * leaving a BigInt pointer in the data field when
                 * downstream code (range, print, icmp) extracts it as
                 * a bare i64 integer. */
                if (fpy_bigint_fits_i64(result)) {
                    int ov = 0;
                    int64_t iv = fpy_bigint_to_i64(result, &ov);
                    fpy_bigint_free(result);
                    *out_tag = FPY_TAG_INT;
                    *out_data = iv;
                } else {
                    *out_tag = FPY_TAG_BIGINT;
                    *out_data = (int64_t)(intptr_t)result;
                }
                return;
            }
        }
    }
    /* Decimal arithmetic — promote INT/BOOL to Decimal.
     *
     * Without this a DECIMAL-tagged operand fell all the way through to the
     * int/bool arithmetic at the bottom of this function, which added the
     * Decimal's *pointer*: `[Decimal("1.5"), 1][0] + 1` printed a heap
     * address, and `* 2` printed twice that address.
     * BUG-FV-BINOP-NO-DECIMAL-COMPLEX.
     *
     * Only +, -, * and / are covered, matching the helpers that exist (and
     * the statically-typed Decimal path in codegen, which maps the same four).
     * Anything else — Decimal + float, which CPython rejects, and //, % and
     * the bitwise ops, which it accepts but no helper implements — falls
     * through to the TypeError guard below.  That is loud rather than silently
     * wrong, which is the right failure while the helpers are missing. */
    if (lt == FPY_TAG_DECIMAL || rt == FPY_TAG_DECIMAL) {
        if ((lt == FPY_TAG_DECIMAL || lt == FPY_TAG_INT || lt == FPY_TAG_BOOL)
            && (rt == FPY_TAG_DECIMAL || rt == FPY_TAG_INT || rt == FPY_TAG_BOOL)
            && op >= 0 && op <= 3) {
            FpyDecimal *la = (lt == FPY_TAG_DECIMAL)
                ? (FpyDecimal*)(intptr_t)ld : fpy_decimal_from_int(ld);
            FpyDecimal *ra = (rt == FPY_TAG_DECIMAL)
                ? (FpyDecimal*)(intptr_t)rd : fpy_decimal_from_int(rd);
            FpyDecimal *dres = NULL;
            switch (op) {
                case 0: dres = fpy_decimal_add(la, ra); break;
                case 1: dres = fpy_decimal_sub(la, ra); break;
                case 2: dres = fpy_decimal_mul(la, ra); break;
                case 3: dres = fpy_decimal_div(la, ra); break;
                default: break;
            }
            /* Only the operands promoted here are owned; a caller-provided
             * Decimal still belongs to whoever holds the tagged value. */
            if (lt != FPY_TAG_DECIMAL) free(la);
            if (rt != FPY_TAG_DECIMAL) free(ra);
            if (dres) {
                *out_tag = FPY_TAG_DECIMAL;
                *out_data = (int64_t)(intptr_t)dres;
                return;
            }
        }
    }
    /* Complex arithmetic — promote INT/BOOL/FLOAT to complex.  Same hole and
     * same fix as Decimal above: `[1 + 2j][0] + [1 + 2j][0]` added two
     * pointers.  BUG-FV-BINOP-NO-DECIMAL-COMPLEX. */
    if (lt == FPY_TAG_COMPLEX || rt == FPY_TAG_COMPLEX) {
        int _lc_ok = (lt == FPY_TAG_COMPLEX || lt == FPY_TAG_INT
                      || lt == FPY_TAG_BOOL || lt == FPY_TAG_FLOAT);
        int _rc_ok = (rt == FPY_TAG_COMPLEX || rt == FPY_TAG_INT
                      || rt == FPY_TAG_BOOL || rt == FPY_TAG_FLOAT);
        if (_lc_ok && _rc_ok && op >= 0 && op <= 3) {
            FpyComplex *lc, *rc;
            if (lt == FPY_TAG_COMPLEX) lc = (FpyComplex*)(intptr_t)ld;
            else if (lt == FPY_TAG_FLOAT) {
                double _lv; memcpy(&_lv, &ld, sizeof(double));
                lc = fpy_complex_new(_lv, 0.0);
            } else lc = fpy_complex_new((double)ld, 0.0);
            if (rt == FPY_TAG_COMPLEX) rc = (FpyComplex*)(intptr_t)rd;
            else if (rt == FPY_TAG_FLOAT) {
                double _rv; memcpy(&_rv, &rd, sizeof(double));
                rc = fpy_complex_new(_rv, 0.0);
            } else rc = fpy_complex_new((double)rd, 0.0);
            FpyComplex *cres = NULL;
            switch (op) {
                case 0: cres = fpy_complex_add(lc, rc); break;
                case 1: cres = fpy_complex_sub(lc, rc); break;
                case 2: cres = fpy_complex_mul(lc, rc); break;
                case 3: cres = fpy_complex_div(lc, rc); break;
                default: break;
            }
            if (lt != FPY_TAG_COMPLEX) free(lc);
            if (rt != FPY_TAG_COMPLEX) free(rc);
            if (cres) {
                *out_tag = FPY_TAG_COMPLEX;
                *out_data = (int64_t)(intptr_t)cres;
                return;
            }
        }
    }
    /* Promote to float if either operand is float AND the other is numeric.
     * Guard: float + container (str, list, dict, set, etc.) is TypeError,
     * not float promotion.
     *
     * The op range matters as much as the tags: a float has no bitwise
     * operators, so `1 & 1.5` is a TypeError in Python.  Without the bound the
     * switch below fell to its `default` and answered 0.0. */
    if ((lt == FPY_TAG_FLOAT || rt == FPY_TAG_FLOAT)
        && (lt == FPY_TAG_FLOAT || lt == FPY_TAG_INT || lt == FPY_TAG_BOOL)
        && (rt == FPY_TAG_FLOAT || rt == FPY_TAG_INT || rt == FPY_TAG_BOOL)
        && op >= 0 && op <= 5) {
        double lf, rf;
        if (lt == FPY_TAG_FLOAT) { memcpy(&lf, &ld, sizeof(double)); }
        else if (lt == FPY_TAG_INT) { lf = (double)ld; }
        else if (lt == FPY_TAG_BOOL) { lf = (double)ld; }
        else { lf = 0.0; }
        if (rt == FPY_TAG_FLOAT) { memcpy(&rf, &rd, sizeof(double)); }
        else if (rt == FPY_TAG_INT) { rf = (double)rd; }
        else if (rt == FPY_TAG_BOOL) { rf = (double)rd; }
        else { rf = 0.0; }
        /* A zero divisor raises, as it does everywhere else in the language.
         * These three cases used to substitute 0.0 silently, which turned an
         * error into a plausible-looking answer. */
        if (rf == 0.0 && op >= 3 && op <= 5) {
            fastpy_raise(FPY_EXC_ZERODIVISION, "division by zero");
            *out_tag = FPY_TAG_NONE; *out_data = 0;
            return;
        }
        double result;
        switch (op) {
            case 0: result = lf + rf; break;
            case 1: result = lf - rf; break;
            case 2: result = lf * rf; break;
            case 3: result = lf / rf; break;
            case 4: result = floor(lf / rf); break;
            case 5: {
                /* Python's % takes the sign of the divisor, C's fmod takes the
                 * sign of the dividend: -7.0 % 3.0 is 2.0, not -1.0. */
                double m = fmod(lf, rf);
                if (m != 0.0 && ((m < 0.0) != (rf < 0.0))) m += rf;
                result = m;
                break;
            }
            default: result = 0.0; break;
        }
        *out_tag = FPY_TAG_FLOAT;
        memcpy(out_data, &result, sizeof(double));
        return;
    }
    /* Guard: everything past this point is plain int/bool arithmetic, so
     * anything that is not two integer-like operands has no handler and is a
     * TypeError.
     *
     * This is written as a *positive* check on purpose.  It used to enumerate
     * the tags that must stop here (list, dict, set, str, bytes, and later
     * Decimal and complex — BUG-FV-BINOP-NO-DECIMAL-COMPLEX), which meant every
     * tag anyone forgot to add fell into the i64 arithmetic below and had its
     * *pointer* added: that is how BIGINT (which was never on the list) turned
     * `(2 ** 80) / 2` into a crash, and how NONE + NONE quietly answered 0.
     * Listing what is allowed instead of what is forbidden makes a new tag, or
     * a newly unhandled combination, fail loudly rather than silently wrong. */
    if (!((lt == FPY_TAG_INT || lt == FPY_TAG_BOOL)
          && (rt == FPY_TAG_INT || rt == FPY_TAG_BOOL))) {
        /* If we reach here, no valid handler matched (e.g. list+int, dict-int,
         * str+list, etc.) — raise TypeError like CPython does. */
        static const char *_op_syms[] = {"+", "-", "*", "/", "//", "%",
                                         "&", "|", "^", "<<", ">>"};
        static const char *_tnames[] = {
            "int", "float", "str", "bool", "NoneType",
            "list", "object", "dict", "bytes", "set",
            "bigint", "complex", "Decimal"};
        const char *ln = (lt >= 0 && lt <= 12) ? _tnames[lt] : "object";
        const char *rn = (rt >= 0 && rt <= 12) ? _tnames[rt] : "object";
        const char *on = (op >= 0 && op <= 10) ? _op_syms[op] : "?";
        snprintf(_err_buf, sizeof(_err_buf),
                 "unsupported operand type(s) for %s: '%.40s' and '%.40s'",
                 on, ln, rn);
        fastpy_raise(FPY_EXC_TYPEERROR, _err_buf);
        *out_tag = FPY_TAG_NONE; *out_data = 0;
        return;
    }
    /* Int/Bool arithmetic — use overflow-checked add/sub/mul so that
     * results that don't fit in i64 promote to BigInt instead of
     * silently wrapping.  This matters when fv_binop is called on
     * values that started as INT but could produce large results
     * (e.g. LCG multipliers: v * 6364136223846793005). */
    extern int64_t fpy_checked_add(int64_t, int64_t, FpyBigInt**);
    extern int64_t fpy_checked_sub(int64_t, int64_t, FpyBigInt**);
    extern int64_t fpy_checked_mul(int64_t, int64_t, FpyBigInt**);
    int64_t li = (lt == FPY_TAG_BOOL) ? (int64_t)(ld != 0) : ld;
    int64_t ri = (rt == FPY_TAG_BOOL) ? (int64_t)(rd != 0) : rd;
    int64_t result;
    FpyBigInt *big = NULL;
    /* A zero divisor raises rather than quietly answering 0, which is what the
     * three ternaries this replaced used to do. */
    if (ri == 0 && op >= 3 && op <= 5) {
        fastpy_raise(FPY_EXC_ZERODIVISION, "division by zero");
        *out_tag = FPY_TAG_NONE; *out_data = 0;
        return;
    }
    switch (op) {
        case 0: result = fpy_checked_add(li, ri, &big); break;
        case 1: result = fpy_checked_sub(li, ri, &big); break;
        case 2: result = fpy_checked_mul(li, ri, &big); break;
        case 3: /* truediv returns float */ {
            double d = (double)li / (double)ri;
            *out_tag = FPY_TAG_FLOAT;
            memcpy(out_data, &d, sizeof(double));
            return;
        }
        /* Python's // floors and its % takes the divisor's sign; C truncates
         * toward zero and takes the dividend's.  -7 // 2 is -4, not -3, and
         * -7 % 2 is 1, not -1. */
        case 4: {
            if (li == INT64_MIN && ri == -1) {
                /* The one i64 division that overflows: -2**63 // -1 is 2**63,
                 * which is a BigInt in Python and UB in C. */
                extern FpyBigInt* fpy_bigint_from_i64(int64_t);
                extern FpyBigInt* fpy_bigint_neg(FpyBigInt*);
                extern void fpy_bigint_free(FpyBigInt*);
                FpyBigInt *m = fpy_bigint_from_i64(INT64_MIN);
                big = fpy_bigint_neg(m);
                fpy_bigint_free(m);
                result = 0;
                break;
            }
            int64_t q = li / ri;
            if ((li % ri != 0) && ((li ^ ri) < 0)) q--;
            result = q;
            break;
        }
        case 5: {
            if (li == INT64_MIN && ri == -1) { result = 0; break; }
            int64_t m = li % ri;
            if (m != 0 && ((m < 0) != (ri < 0))) m += ri;
            result = m;
            break;
        }
        default: result = 0; break;
    }
    if (big) {
        *out_tag = FPY_TAG_BIGINT;
        *out_data = (int64_t)(intptr_t)big;
    } else {
        *out_tag = FPY_TAG_INT;
        *out_data = result;
    }
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
            size_t len = (size_t)fpy_bytes_len(data);  /* embedded-null safe */
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
            /* Native FpyObj — use __lt__ if defined, else pointer identity */
            FpyMethodDef *lt_m = fastpy_find_method(oa->class_id, "__lt__");
            if (lt_m) {
                int64_t r = ((int64_t(*)(void*,int64_t))lt_m->func)(pa, (int64_t)(intptr_t)pb);
                if (r) return -1;
                /* Check reverse: b < a */
                FpyObj *ob = (FpyObj*)pb;
                FpyMethodDef *lt_b = fastpy_find_method(ob->class_id, "__lt__");
                if (lt_b) {
                    int64_t r2 = ((int64_t(*)(void*,int64_t))lt_b->func)(pb, (int64_t)(intptr_t)pa);
                    if (r2) return 1;
                }
                return 0;
            }
            return (pa > pb) - (pa < pb);
        }
        default:
            return 0;
    }
}

/* Return min element's data (as i64) using fpy_value_compare.
 * Returns the raw data field — caller knows the element type. */
int64_t fastpy_list_min_fv(FpyList *list) {
    FpyValue best = list->items[0];
    for (int64_t i = 1; i < list->length; i++) {
        if (fpy_value_compare(&list->items[i], &best) < 0)
            best = list->items[i];
    }
    return best.data.i;
}

/* Return max element's data (as i64) using fpy_value_compare. */
int64_t fastpy_list_max_fv(FpyList *list) {
    FpyValue best = list->items[0];
    for (int64_t i = 1; i < list->length; i++) {
        if (fpy_value_compare(&list->items[i], &best) > 0)
            best = list->items[i];
    }
    return best.data.i;
}

/* Return a new sorted copy of a list */
/* list(obj) where obj implements __iter__/__next__: build a list by
 * calling __iter__() then __next__() until StopIteration is raised. */
extern int64_t fastpy_obj_call_method0(FpyObj*, const char*);
extern void fastpy_exc_clear(void);
extern int32_t fastpy_get_ret_tag(void);
FpyList* fastpy_list_from_obj_iter(FpyObj *obj) {
    FpyList *result = fpy_list_new(8);
    /* Call __iter__() to get the iterator */
    int64_t iter_raw = fastpy_obj_call_method0(obj, "__iter__");
    if (fastpy_exc_pending()) {
        fastpy_exc_clear();
        return result;  /* empty list on error */
    }
    FpyObj *iter = (FpyObj*)(intptr_t)iter_raw;
    /* Repeatedly call __next__() */
    for (;;) {
        int64_t val = fastpy_obj_call_method0(iter, "__next__");
        if (fastpy_exc_pending()) {
            fastpy_exc_clear();  /* StopIteration */
            break;
        }
        /* Get the return tag to build the correct FpyValue */
        int32_t tag = fastpy_get_ret_tag();
        FpyValue fv;
        fv.tag = tag;
        fv.data.i = val;
        fpy_list_append(result, fv);
    }
    return result;
}

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

/* Return a reversed list of single-character strings from a string.
 * reversed("abc") → ['c', 'b', 'a'] (each element is a 1-char str). */
FpyList* fastpy_str_reversed(const char *s) {
    /* Count code points */
    const unsigned char *p = (const unsigned char *)s;
    int64_t n = 0;
    while (*p) { p += fpy_utf8_cplen(p); n++; }

    FpyList *result = fpy_list_new(n);
    result->length = n;

    /* Walk forward, store chars in reverse order */
    p = (const unsigned char *)s;
    for (int64_t i = 0; i < n; i++) {
        int cplen = fpy_utf8_cplen(p);
        FpyString *ch = fpy_str_alloc(cplen);
        memcpy(ch->data, p, cplen);
        ch->data[cplen] = '\0';
        result->items[n - 1 - i] = fpy_str(ch->data);
        p += cplen;
    }
    return result;
}

/* --- String methods that return lists / take lists --- */

/* Split a string by whitespace, return list of strings */
FpyList* fastpy_str_split(const char *s) {
    FpyList *result = fpy_list_new(8);
    const unsigned char *p = (const unsigned char *)s;
    int n;
    while (*p) {
        /* Skip whitespace (UTF-8 aware) */
        while (*p && (n = _fpy_ws_fwd(p)) > 0) p += n;
        if (!*p) break;
        /* Find end of word */
        const unsigned char *start = p;
        while (*p && _fpy_ws_fwd(p) == 0) p++;
        /* Copy word into a headered (refcounted) string — see fpy_str_copy /
         * BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC. A bare malloc here would leave
         * the STR value without an FpyString header, leaking it and making
         * fpy_str_header read out of bounds. */
        int64_t len = p - start;
        fpy_list_append(result, fpy_str(fpy_str_copy((const char*)start, len)));
    }
    return result;
}

/* bytes.split() — same as str_split but tags results as BYTES */
FpyList* fastpy_bytes_split(const char *s) {
    FpyList *result = fpy_list_new(8);
    const char *p = s;
    while (*p) {
        while (*p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) p++;
        if (!*p) break;
        const char *start = p;
        while (*p && *p != ' ' && *p != '\t' && *p != '\n' && *p != '\r') p++;
        int64_t len = p - start;
        char *word = fpy_bytes_alloc(len);  /* header-backed FpyBytes */
        memcpy(word, start, len);
        fpy_list_append(result, fpy_bytes_val(word));
    }
    return result;
}

/* Join a list of strings with a separator */
const char* fastpy_str_join(const char *sep, FpyList *list) {
    if (list->length == 0) {
        return fpy_str_buf(0);
    }
    size_t sep_len = strlen(sep);
    size_t total = 0;
    for (int64_t i = 0; i < list->length; i++) {
        total += strlen(list->items[i].data.s);
        if (i > 0) total += sep_len;
    }
    char *result = fpy_str_buf((int64_t)total);
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
    char *buf = fpy_str_buf(4096);
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
    char *buf = fpy_str_buf(4096);
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

static uint64_t fpy_hash_int(int64_t key);  /* forward declaration */

static uint64_t fpy_hash_value(FpyValue v) {
    if (v.tag == FPY_TAG_STR) return fpy_hash_string(v.data.s);
    if (v.tag == FPY_TAG_INT) {
        /* Mix integer bits (splitmix64-style) */
        uint64_t x = (uint64_t)v.data.i;
        x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
        x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
        return x ^ (x >> 31);
    }
    if (v.tag == FPY_TAG_BOOL) {
        return fpy_hash_int((int64_t)v.data.b);
    }
    if (v.tag == FPY_TAG_NONE) {
        return 0x345678ULL;  /* stable sentinel */
    }
    if (v.tag == FPY_TAG_FLOAT) {
        /* Hash doubles: if it's an exact integer, hash like the int.
         * Otherwise use raw bits. This matches Python semantics where
         * hash(1) == hash(1.0).
         *
         * The bound is the int64 range, not 2^53.  A narrower bound would
         * hash 1e18 by its bits while hashing the int 1000000000000000000
         * as an int, so two keys that fpy_key_equal() calls equal would land
         * in different buckets and both survive in the table.  Converting an
         * integral in-range double to int64 is exact, so there is no
         * precision argument for stopping at 2^53 — only the conversion's
         * own UB above 2^63, which is what this guard is for. */
        double d = v.data.f;
        if (d >= -9223372036854775808.0 && d < 9223372036854775808.0
                && d == (double)(int64_t)d) {
            return fpy_hash_int((int64_t)d);
        }
        uint64_t bits;
        memcpy(&bits, &d, sizeof(bits));
        bits = (bits ^ (bits >> 30)) * 0xbf58476d1ce4e5b9ULL;
        bits = (bits ^ (bits >> 27)) * 0x94d049bb133111ebULL;
        return bits ^ (bits >> 31);
    }
    if (v.tag == FPY_TAG_LIST) {
        /* Tuple hash (Python's tuple hash algorithm — tuplehash).
         * Lists use the same tag; we hash element-wise for tuples used as
         * dict keys. */
        FpyList *list = v.data.list;
        if (!list) return 0;
        uint64_t h = 0x345678ULL;
        uint64_t mult = 1000003ULL;
        for (int64_t i = 0; i < list->length; i++) {
            uint64_t elem_h = fpy_hash_value(list->items[i]);
            h = (h ^ elem_h) * mult;
            mult += 82520ULL + (uint64_t)(list->length - i - 1) * 2ULL;
        }
        h += 97531ULL;
        return h;
    }
    return (uint64_t)v.data.i;  /* fallback for other types */
}

/* True when a tag takes part in Python's numeric tower for key identity.
 * bool is a subclass of int, and int/float compare across types, so all
 * three name the same key when they are numerically equal: `{1: 'a'}[1.0]`
 * is 'a' and `{1: 'a', True: 'b'}` has one entry. */
static int fpy_key_tag_is_numeric(int32_t tag) {
    return tag == FPY_TAG_INT || tag == FPY_TAG_BOOL || tag == FPY_TAG_FLOAT;
}

static int fpy_key_numeric_equal(FpyValue a, FpyValue b) {
    /* Exact comparison, the way CPython does it — never by widening the
     * integer to a double, which would make 2**60 and 2**60 + 1 the same
     * key.  An integral double in int64 range converts back exactly, so
     * comparing in int64 is the exact answer; a non-integral or
     * out-of-range double cannot equal any int. */
    double d;
    int64_t i;
    int a_is_float = (a.tag == FPY_TAG_FLOAT);
    int b_is_float = (b.tag == FPY_TAG_FLOAT);
    if (a_is_float && b_is_float) return a.data.f == b.data.f;
    if (!a_is_float && !b_is_float) {
        int64_t ai = (a.tag == FPY_TAG_BOOL) ? (int64_t)a.data.b : a.data.i;
        int64_t bi = (b.tag == FPY_TAG_BOOL) ? (int64_t)b.data.b : b.data.i;
        return ai == bi;
    }
    if (a_is_float) {
        d = a.data.f;
        i = (b.tag == FPY_TAG_BOOL) ? (int64_t)b.data.b : b.data.i;
    } else {
        d = b.data.f;
        i = (a.tag == FPY_TAG_BOOL) ? (int64_t)a.data.b : a.data.i;
    }
    if (!(d >= -9223372036854775808.0 && d < 9223372036854775808.0))
        return 0;
    if (d != (double)(int64_t)d) return 0;   /* has a fractional part */
    return (int64_t)d == i;
}

static int fpy_key_equal(FpyValue a, FpyValue b) {
    /* Across the numeric tags this has to agree with fpy_hash_value(), which
     * already hashes True as 1 and an integral 1.0 as 1.  It used to reject
     * any tag mismatch outright, so `1` and `1.0` hashed into the same bucket
     * and then compared unequal — the dict kept both, and `{1: 'a'}[1.0]`
     * raised a KeyError on a key Python says is present. */
    if (fpy_key_tag_is_numeric(a.tag) && fpy_key_tag_is_numeric(b.tag))
        return fpy_key_numeric_equal(a, b);
    if (a.tag != b.tag) return 0;
    if (a.tag == FPY_TAG_INT) return a.data.i == b.data.i;
    if (a.tag == FPY_TAG_STR) {
        return a.data.s == b.data.s || strcmp(a.data.s, b.data.s) == 0;
    }
    if (a.tag == FPY_TAG_LIST) {
        /* Tuple equality: element-wise comparison */
        FpyList *la = a.data.list, *lb = b.data.list;
        if (la == lb) return 1;
        if (!la || !lb) return 0;
        if (la->length != lb->length) return 0;
        for (int64_t i = 0; i < la->length; i++) {
            if (!fpy_key_equal(la->items[i], lb->items[i])) return 0;
        }
        return 1;
    }
    return a.data.i == b.data.i;  /* fallback */
}

/* The int-specialized dict paths (`_int_fv`, `_int_val`, `has_int_key`, the
 * int delete) each inlined `tag == FPY_TAG_INT && data.i == key`.  That is a
 * *narrower* rule than fpy_key_equal(): it cannot see a float or bool key
 * naming the same slot, so `{2.0: 'two'}[2]` raised a KeyError while
 * `{2: 'two'}[2.0]` — which goes through the general path — worked.  They all
 * defer here now, so there is one rule for what makes two keys the same.
 * BUG-FLOAT-KEY-DICT-LITERAL-SEGFAULTS.
 *
 * Split in two, and taking the stored key by pointer, because the shape
 * matters at this call frequency.  As one by-value function the probe loop
 * had to materialise the whole 16-byte FpyValue — MSVC loaded it with
 * `movups` into an XMM register and dug the tag and payload back out with
 * `movd`/`psrldq`/`movq`, then produced the answer through `sete` instead of
 * branching on the compare.  By pointer, the int/int case is the two scalar
 * loads and two compares it always was, and the numeric-tower cases cost the
 * hit path nothing because they live in their own frame. */
FPY_NOINLINE static int fpy_key_equal_int_slow(FpyValue stored, int64_t key) {
    if (!fpy_key_tag_is_numeric(stored.tag)) return 0;
    FpyValue k;
    k.tag = FPY_TAG_INT;
    k.data.i = key;
    return fpy_key_numeric_equal(stored, k);
}

static int fpy_key_equal_int(const FpyValue *stored, int64_t key) {
    if (stored->tag == FPY_TAG_INT) return stored->data.i == key;
    return fpy_key_equal_int_slow(*stored, key);
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
    fpy_raise_key_error(key);
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
    /* Retain the stored value+key (Model-2 borrowed-at-boundary model):
     * every retaining container store increfs so a producer's owned temp
     * survives the statement-boundary flush. Matches the internal
     * fpy_dict_set and fpy_dict_destroy (which decrefs both). */
    FPY_VAL_INCREF(k);
    FPY_VAL_INCREF(v);
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
            /* Overwrite: release old value's dict-ref; the key is unchanged
             * so undo the key incref we took above. */
            FPY_VAL_DECREF(dict->values[idx]);
            dict->values[idx] = v;
            FPY_VAL_DECREF(k);
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
    fpy_raise_key_error(fpy_str(key));
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

/* Exported hash function for the compiler's hash() builtin.
 * Takes (tag, data) to match the FpyValue ABI. */
int64_t fastpy_hash_fv(int32_t tag, int64_t data) {
    FpyValue v;
    v.tag = tag;
    v.data.i = data;
    return (int64_t)fpy_hash_value(v);
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
        } else if (fpy_key_equal_int(&dict->keys[idx], key)) {
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
    /* Retain the stored value (int key is not refcounted). See
     * fastpy_dict_set_fv for the rationale. */
    FPY_VAL_INCREF(v);
    uint64_t h = fpy_hash_int(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    int64_t first_deleted = -1;
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx == FPY_DICT_DELETED) {
            if (first_deleted < 0) first_deleted = slot;
        } else if (fpy_key_equal_int(&dict->keys[idx], key)) {
            FPY_VAL_DECREF(dict->values[idx]);
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
                && fpy_key_equal_int(&dict->keys[idx], key)) {
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return;
        }
        slot = (slot + 1) & mask;
    }
    fpy_raise_key_error(fpy_int(key));
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
                && fpy_key_equal_int(&dict->keys[idx], key)) {
            return dict->values[idx].data.i;
        }
        slot = (slot + 1) & mask;
    }
    fpy_raise_key_error(fpy_int(key));
    return 0;
}

/* ---- Generic FpyValue-keyed dict operations ----
 * These use fpy_hash_value + fpy_key_equal so they handle any key type
 * (string, int, tuple, etc.) passed as (tag, data). */
void fastpy_dict_set_kv_fv(FpyDict *dict,
                            int32_t key_tag, int64_t key_data,
                            int32_t val_tag, int64_t val_data) {
    FpyValue k; k.tag = key_tag; k.data.i = key_data;
    FpyValue v; v.tag = val_tag; v.data.i = val_data;
    /* Retain the stored value+key. See fastpy_dict_set_fv for rationale. */
    FPY_VAL_INCREF(k);
    FPY_VAL_INCREF(v);
    uint64_t h = fpy_hash_value(k);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    int64_t first_deleted = -1;
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx == FPY_DICT_DELETED) {
            if (first_deleted < 0) first_deleted = slot;
        } else if (fpy_key_equal(dict->keys[idx], k)) {
            FPY_VAL_DECREF(dict->values[idx]);
            dict->values[idx] = v;
            FPY_VAL_DECREF(k);
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

void fastpy_dict_get_kv_fv(FpyDict *dict,
                            int32_t key_tag, int64_t key_data,
                            int32_t *out_tag, int64_t *out_data) {
    FpyValue k; k.tag = key_tag; k.data.i = key_data;
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
    fpy_raise_key_error(k);
    *out_tag = FPY_TAG_NONE; *out_data = 0; return;
}

int32_t fastpy_dict_has_kv_key(FpyDict *dict, int32_t key_tag, int64_t key_data) {
    FpyValue k; k.tag = key_tag; k.data.i = key_data;
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

int32_t fastpy_dict_has_int_key(FpyDict *dict, int64_t key) {
    uint64_t h = fpy_hash_int(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) return 0;
        if (idx != FPY_DICT_DELETED
                && fpy_key_equal_int(&dict->keys[idx], key))
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

/* Build a dict from a list of (key, value) pairs.
 * Each element of `pairs` must be a 2-element tuple/list.
 * dict([(1, "a"), (2, "b")])  →  {1: "a", 2: "b"} */
FpyDict* fastpy_dict_from_pairs(FpyList *pairs) {
    FpyDict *result = fpy_dict_new(pairs->length > 4 ? pairs->length : 4);
    for (int64_t i = 0; i < pairs->length; i++) {
        FpyValue item = pairs->items[i];
        if (item.tag == FPY_TAG_LIST) {
            FpyList *pair = item.data.list;
            if (pair && pair->length >= 2) {
                fpy_dict_set(result, pair->items[0], pair->items[1]);
            }
        }
    }
    return result;
}

void fastpy_dict_clear(FpyDict *dict) {
    FPY_LOCK(dict);
    /* Release the dict's owned refs on every entry before dropping them
     * (retain model — see fastpy_dict_set_fv). Without this, clearing a
     * dict/set that holds heap keys/values leaks them. */
    for (int64_t i = 0; i < dict->length; i++) {
        FPY_VAL_DECREF(dict->keys[i]);
        FPY_VAL_DECREF(dict->values[i]);
    }
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

/* Zero-copy element access for dict/set iteration.
 * Read key/value at compact-array index without materializing a list. */
void fastpy_dict_key_fv(FpyDict *dict, int64_t index,
                        int32_t *out_tag, int64_t *out_data) {
    FpyValue v = dict->keys[index];
    *out_tag = v.tag;
    *out_data = v.data.i;
}

void fastpy_dict_value_fv(FpyDict *dict, int64_t index,
                          int32_t *out_tag, int64_t *out_data) {
    FpyValue v = dict->values[index];
    *out_tag = v.tag;
    *out_data = v.data.i;
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
        fpy_raise_key_error(fpy_str("pop from an empty set"));
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

/* set.intersection_update(other) — keep only elements found in other */
void fastpy_set_intersection_update(FpyDict *a, FpyDict *b) {
    /* Build list of keys to remove (can't mutate while iterating). */
    int64_t n = 0;
    FpyValue *to_remove = (FpyValue*)malloc(a->length * sizeof(FpyValue));
    for (int64_t i = 0; i < a->length; i++) {
        if (!fastpy_set_contains(b, a->keys[i]))
            to_remove[n++] = a->keys[i];
    }
    for (int64_t i = 0; i < n; i++)
        fastpy_set_discard_fv(a, to_remove[i].tag, to_remove[i].data.i);
    free(to_remove);
}

/* set.difference_update(other) — remove elements found in other */
void fastpy_set_difference_update(FpyDict *a, FpyDict *b) {
    for (int64_t i = 0; i < b->length; i++) {
        if (fastpy_set_contains(a, b->keys[i]))
            fastpy_set_discard_fv(a, b->keys[i].tag, b->keys[i].data.i);
    }
}

/* set.symmetric_difference_update(other) — keep elements in either but not both */
void fastpy_set_symmetric_difference_update(FpyDict *a, FpyDict *b) {
    for (int64_t i = 0; i < b->length; i++) {
        if (fastpy_set_contains(a, b->keys[i]))
            fastpy_set_discard_fv(a, b->keys[i].tag, b->keys[i].data.i);
        else
            fpy_dict_set(a, b->keys[i], fpy_none());
    }
}

/* --- Any iterable, as a set the set algorithms can consume ---
 *
 * Every set method above that takes an "other" is written against an FpyDict
 * and reads `b->keys[i]`, but CPython accepts *any* iterable for all eleven of
 * them.  Handing one an FpyList reinterprets that list's `items`/`length`/
 * `capacity` as a dict's `keys`/`values`/`length`, so `b->keys[i]` comes back
 * as an FpyValue assembled from a pointer and a capacity, and the runtime
 * dereferences it.  That is BUG-SET-UPDATE-NON-SET-ITERABLE-SEGFAULTS: not a
 * null pointer but a live object of one type read as another, the same shape
 * as BUG-EMPTY-KWARGS-CALL-SEGFAULTS.
 *
 * The kind is a runtime fact, not a static one -- the argument is a parameter
 * as often as not -- so the answer has to come from the tag, exactly as it
 * does for BUG-FOR-DICT-KEY-KIND-GUESSED.  Giving each of the eleven its own
 * tag switch would be eleven chances for them to disagree about what
 * `s.update("ab")` means, so the coercion happens once, here, and the eleven
 * algorithms stay untouched.
 *
 * A value that is already a set is returned as itself, so the overwhelmingly
 * common case costs one comparison and no allocation.  Anything else is
 * materialised into a temporary and `*owned` is set, meaning the caller must
 * release it.  A non-iterable raises TypeError and returns NULL -- loud,
 * rather than corrupting memory, which was the whole failure here.
 *
 * The elements themselves come from `fastpy_fv_to_list`, which already had to
 * answer "what does iterating this value yield?" for `list()`/`tuple()`.
 * Writing a second tag switch here would have been a second, quietly
 * divergent answer -- and a worse one: it would have rejected the OBJ tag,
 * losing every CPython-backed iterable that the bridge makes work.  The
 * intermediate list costs one allocation on a path that is cold by
 * construction, since the hot argument is a set and never reaches it.
 */
extern FpyList* fastpy_fv_to_list(int32_t tag, int64_t data);
static const char *_fpy_tag_name(int32_t tag);   /* defined further down */

/* Iterating one of these is a TypeError, so they must not reach
 * fastpy_fv_to_list -- its `default` arm wraps a scalar into a one-element
 * list, which is the right answer for its own callers and the wrong one here
 * (`s.update(5)` would quietly add 5 rather than raising). */
static int fpy_tag_is_iterable(int32_t tag) {
    switch (tag) {
    case FPY_TAG_STR: case FPY_TAG_LIST: case FPY_TAG_OBJ:
    case FPY_TAG_DICT: case FPY_TAG_BYTES: case FPY_TAG_SET:
        return 1;
    default:
        return 0;
    }
}

static FpyDict *fpy_iterable_as_set(int32_t tag, int64_t data, int *owned) {
    *owned = 0;
    if (data != 0 && tag == FPY_TAG_SET)
        return (FpyDict*)(intptr_t)data;
    if (data == 0 || !fpy_tag_is_iterable(tag)) {
        char buf[128];
        snprintf(buf, sizeof(buf), "'%.40s' object is not iterable",
                 data == 0 ? "NoneType" : _fpy_tag_name(tag));
        fastpy_raise(FPY_EXC_TYPEERROR, buf);
        return NULL;
    }
    *owned = 1;
    /* A list is already the element sequence, so take it directly.  Going
     * through fastpy_fv_to_list would be correct but would copy it first
     * (`list()` owes its caller a new list; this does not), doubling the
     * allocation for `set(xs)` and `s.update(xs)` on the commonest argument
     * there is.  Tuples are FpyLists too, so this covers them. */
    if (tag == FPY_TAG_LIST)
        return fastpy_set_from_list((FpyList*)(intptr_t)data);
    FpyList *elems = fastpy_fv_to_list(tag, data);
    if (!elems) { *owned = 0; return NULL; }
    FpyDict *out = fastpy_set_from_list(elems);
    fpy_rc_decref(FPY_TAG_LIST, (int64_t)(intptr_t)elems);
    return out;
}

static void fpy_release_iterable_set(FpyDict *b, int owned) {
    if (owned) fpy_rc_decref(FPY_TAG_SET, (int64_t)(intptr_t)b);
}

/* `set(x)` / `frozenset(x)`: the same coercion, but the result is the
 * program's own set, so it is always fresh -- `set(s)` must not alias `s`. */
FpyDict* fastpy_set_from_iterable_fv(int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return fpy_dict_new(4);
    return owned ? b : fastpy_set_copy(b);
}

/* The eleven entry points codegen actually calls.  They take the argument as
 * (tag, data) so the kind survives to run time, coerce once, and delegate.
 *
 * fastpy_raise only sets a pending-exception flag, so an error path still has
 * to return something the caller can hold until it checks: an empty set for
 * the set-returning ones (never NULL, which the next call would dereference)
 * and 0 for the predicates. */
void fastpy_set_update_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return;
    fastpy_set_update(a, b);
    fpy_release_iterable_set(b, owned);
}

void fastpy_set_intersection_update_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return;
    fastpy_set_intersection_update(a, b);
    fpy_release_iterable_set(b, owned);
}

void fastpy_set_difference_update_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return;
    fastpy_set_difference_update(a, b);
    fpy_release_iterable_set(b, owned);
}

void fastpy_set_symmetric_difference_update_fv(FpyDict *a, int32_t tag,
                                               int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return;
    fastpy_set_symmetric_difference_update(a, b);
    fpy_release_iterable_set(b, owned);
}

FpyDict* fastpy_set_union_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return fpy_dict_new(4);
    FpyDict *r = fastpy_set_union(a, b);
    fpy_release_iterable_set(b, owned);
    return r;
}

FpyDict* fastpy_set_intersection_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return fpy_dict_new(4);
    FpyDict *r = fastpy_set_intersection(a, b);
    fpy_release_iterable_set(b, owned);
    return r;
}

FpyDict* fastpy_set_difference_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return fpy_dict_new(4);
    FpyDict *r = fastpy_set_difference(a, b);
    fpy_release_iterable_set(b, owned);
    return r;
}

FpyDict* fastpy_set_symmetric_diff_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return fpy_dict_new(4);
    FpyDict *r = fastpy_set_symmetric_diff(a, b);
    fpy_release_iterable_set(b, owned);
    return r;
}

int32_t fastpy_set_issubset_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return 0;
    int32_t r = fastpy_set_issubset(a, b);
    fpy_release_iterable_set(b, owned);
    return r;
}

int32_t fastpy_set_issuperset_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return 0;
    int32_t r = fastpy_set_issuperset(a, b);
    fpy_release_iterable_set(b, owned);
    return r;
}

int32_t fastpy_set_isdisjoint_fv(FpyDict *a, int32_t tag, int64_t data) {
    int owned; FpyDict *b = fpy_iterable_as_set(tag, data, &owned);
    if (!b) return 0;
    int32_t r = fastpy_set_isdisjoint(a, b);
    fpy_release_iterable_set(b, owned);
    return r;
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
    c->has_vararg = 0;       /* caller sets to 1 if function uses *args */
    c->has_kwarg = 0;        /* caller sets to 1 if function uses **kwargs */
    c->n_defaults = 0;
    c->param_names = NULL;
    return c;
}

/* Set default parameter values for the closure. defaults are stored
 * for the LAST n_defaults parameters (like Python convention). */
void fastpy_closure_set_defaults(FpyClosure *c, int n_defaults) {
    c->n_defaults = n_defaults;
}

void fastpy_closure_set_default(FpyClosure *c, int index, int64_t value) {
    if (index < 8) c->defaults[index] = value;
}

/* Mark a capture as a cell pointer (for proper cleanup) */
void fastpy_closure_mark_cell(FpyClosure *c, int index) {
    c->capture_is_cell |= (1 << index);
}

/* Mark a closure as using *args (args must be packed into a list) */
void fastpy_closure_set_vararg(FpyClosure *c) {
    c->has_vararg = 1;
}

void fastpy_closure_set_kwarg(FpyClosure *c) {
    c->has_kwarg = 1;
}

void fastpy_closure_set_param_names(FpyClosure *c, const char **names) {
    c->param_names = names;
}

void fastpy_closure_set_param_name(FpyClosure *c, int index, const char *name) {
    if (!c->param_names) {
        c->param_names = (const char**)malloc(sizeof(const char*) * c->n_params);
        for (int i = 0; i < c->n_params; i++) c->param_names[i] = NULL;
    }
    if (index >= 0 && index < c->n_params) {
        c->param_names[index] = name;
    }
}

void fastpy_closure_set_capture(FpyClosure *c, int index, int64_t value) {
    c->captures[index] = value;
}

/* Forward declarations for default dispatch */
int64_t fastpy_closure_call1(FpyClosure *c, int64_t a);
int64_t fastpy_closure_call2(FpyClosure *c, int64_t a, int64_t b);

/* Helper: pack N i64 args into an FpyList for *args closures.
 * Uses the arg tag side-channel (fpy_arg_tags) to preserve the
 * runtime type of each argument, so forwarding patterns like
 * func(*args) in decorators don't lose type information. */
static FpyList* _pack_args0(void) {
    FpyList *lst = fpy_list_new(0);
    lst->is_tuple = 1;
    return lst;
}
extern int32_t fastpy_get_arg_tag(int32_t);
static FpyList* _pack_args1(int64_t a) {
    FpyList *lst = fpy_list_new(1);
    lst->is_tuple = 1;
    FpyValue fv = {.tag = fastpy_get_arg_tag(0), .data = {.i = a}};
    fpy_list_append(lst, fv);
    return lst;
}
static FpyList* _pack_args2(int64_t a, int64_t b) {
    FpyList *lst = fpy_list_new(2);
    lst->is_tuple = 1;
    FpyValue fva = {.tag = fastpy_get_arg_tag(0), .data = {.i = a}};
    FpyValue fvb = {.tag = fastpy_get_arg_tag(1), .data = {.i = b}};
    fpy_list_append(lst, fva);
    fpy_list_append(lst, fvb);
    return lst;
}

/* Call closure with 0 explicit args + captures.
 * If the closure has default parameter values, fill them in. */
int64_t fastpy_closure_call0(FpyClosure *c) {
    /* *args closure: pack 0 args into empty list, pass as first param */
    if (c->has_vararg) {
        int64_t args_list = (int64_t)(intptr_t)_pack_args0();
        typedef int64_t (*fn1_t)(int64_t);
        typedef int64_t (*fn2c_t)(int64_t, int64_t);
        typedef int64_t (*fn3c_t)(int64_t, int64_t, int64_t);
        switch (c->n_captures) {
            case 0: return ((fn1_t)c->func)(args_list);
            case 1: return ((fn2c_t)c->func)(args_list, c->captures[0]);
            case 2: return ((fn3c_t)c->func)(args_list, c->captures[0], c->captures[1]);
            case 3: {
                typedef int64_t (*fn4c_t)(int64_t, int64_t, int64_t, int64_t);
                return ((fn4c_t)c->func)(args_list, c->captures[0], c->captures[1], c->captures[2]);
            }
            default: return 0;
        }
    }
    /* If closure expects explicit params and has defaults for all of them,
     * supply the default values as arguments. */
    if (c->n_params > 0 && c->n_defaults >= c->n_params) {
        /* All params have defaults — call with defaults + captures */
        int n = c->n_params;
        if (n == 1) return fastpy_closure_call1(c, c->defaults[0]);
        if (n == 2) return fastpy_closure_call2(c, c->defaults[0], c->defaults[1]);
    }
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

/* Call closure with 1 explicit arg + captures.
 * If the closure expects more params and has defaults, fill them in. */
int64_t fastpy_closure_call1(FpyClosure *c, int64_t a) {
    /* *args closure: pack 1 arg into list, pass as first param */
    if (c->has_vararg) {
        int64_t args_list = (int64_t)(intptr_t)_pack_args1(a);
        typedef int64_t (*fn1_t)(int64_t);
        typedef int64_t (*fn2c_t)(int64_t, int64_t);
        typedef int64_t (*fn3c_t)(int64_t, int64_t, int64_t);
        switch (c->n_captures) {
            case 0: return ((fn1_t)c->func)(args_list);
            case 1: return ((fn2c_t)c->func)(args_list, c->captures[0]);
            case 2: return ((fn3c_t)c->func)(args_list, c->captures[0], c->captures[1]);
            case 3: {
                typedef int64_t (*fn4c_t)(int64_t, int64_t, int64_t, int64_t);
                return ((fn4c_t)c->func)(args_list, c->captures[0], c->captures[1], c->captures[2]);
            }
            default: return 0;
        }
    }
    /* If closure expects 2 params but only 1 provided, and the 2nd has a default */
    if (c->n_params == 2 && c->n_defaults >= 1) {
        /* defaults[n_defaults-1] is the last param's default */
        return fastpy_closure_call2(c, a, c->defaults[c->n_defaults - 1]);
    }
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
    /* *args closure: pack 2 args into list, pass as first param */
    if (c->has_vararg) {
        int64_t args_list = (int64_t)(intptr_t)_pack_args2(a, b);
        typedef int64_t (*fn1_t)(int64_t);
        typedef int64_t (*fn2c_t)(int64_t, int64_t);
        typedef int64_t (*fn3c_t)(int64_t, int64_t, int64_t);
        switch (c->n_captures) {
            case 0: return ((fn1_t)c->func)(args_list);
            case 1: return ((fn2c_t)c->func)(args_list, c->captures[0]);
            case 2: return ((fn3c_t)c->func)(args_list, c->captures[0], c->captures[1]);
            case 3: {
                typedef int64_t (*fn4c_t)(int64_t, int64_t, int64_t, int64_t);
                return ((fn4c_t)c->func)(args_list, c->captures[0], c->captures[1], c->captures[2]);
            }
            default: return 0;
        }
    }
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
    FpyList *args = (FpyList *)args_list;

    /* Raw function pointer (not a closure): unpack args and call directly.
     * This happens when func(*args) is called where func is a captured
     * raw function pointer (e.g. the original function in a decorator). */
    if (!fpy_is_closure(closure)) {
        int64_t n = args ? args->length : 0;
        int64_t a[8] = {0};
        /* Store arg tags in the side-channel so i64 wrappers (for FV-ABI
         * functions) can reconstruct FpyValues with correct runtime tags. */
        extern void fastpy_set_arg_tag(int32_t, int32_t);
        for (int64_t i = 0; i < n && i < 8; i++) {
            a[i] = args->items[i].data.i;
            fastpy_set_arg_tag((int32_t)i, args->items[i].tag);
        }
        typedef int64_t (*fn0_t)(void);
        typedef int64_t (*fn1_t)(int64_t);
        typedef int64_t (*fn2_t)(int64_t, int64_t);
        typedef int64_t (*fn3_t)(int64_t, int64_t, int64_t);
        typedef int64_t (*fn4_t)(int64_t, int64_t, int64_t, int64_t);
        switch (n) {
            case 0: return ((fn0_t)closure)();
            case 1: return ((fn1_t)closure)(a[0]);
            case 2: return ((fn2_t)closure)(a[0], a[1]);
            case 3: return ((fn3_t)closure)(a[0], a[1], a[2]);
            case 4: return ((fn4_t)closure)(a[0], a[1], a[2], a[3]);
            default: return 0;
        }
    }

    FpyClosure *c = (FpyClosure *)closure;

    /* *args closure: pass the list directly as the first parameter */
    if (c->has_vararg) {
        int64_t list_val = (int64_t)(intptr_t)(args ? args : _pack_args0());
        typedef int64_t (*fn1_t)(int64_t);
        typedef int64_t (*fn2c_t)(int64_t, int64_t);
        typedef int64_t (*fn3c_t)(int64_t, int64_t, int64_t);
        typedef int64_t (*fn4c_t)(int64_t, int64_t, int64_t, int64_t);
        switch (c->n_captures) {
            case 0: return ((fn1_t)c->func)(list_val);
            case 1: return ((fn2c_t)c->func)(list_val, c->captures[0]);
            case 2: return ((fn3c_t)c->func)(list_val, c->captures[0], c->captures[1]);
            case 3: return ((fn4c_t)c->func)(list_val, c->captures[0], c->captures[1], c->captures[2]);
            default: return 0;
        }
    }

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

/* Try to find a string key in dict without raising KeyError.
 * Returns 1 and sets out_tag/out_data if found, 0 if not found. */
static int fpy_dict_try_get(FpyDict *dict, const char *key,
                            int32_t *out_tag, int64_t *out_data) {
    if (!dict || !key) return 0;
    uint64_t h = fpy_hash_string(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) return 0;
        if (idx != FPY_DICT_DELETED
                && dict->keys[idx].tag == FPY_TAG_STR
                && (dict->keys[idx].data.s == key
                    || strcmp(dict->keys[idx].data.s, key) == 0)) {
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return 1;
        }
        slot = (slot + 1) & mask;
    }
}

/* Call closure with keyword args passed as a dict.
 * Maps dict keys to positional params using the closure's param_names,
 * fills defaults for missing params, then dispatches. */
int64_t fastpy_closure_call_dict(void *closure, void *dict_ptr) {
    /* Raw function pointer: extract dict values in insertion order and
     * dispatch positionally.  This relies on Python 3.7+ dict ordering:
     * kwargs passed in the same order as the function's params work. */
    if (!fpy_is_closure(closure)) {
        FpyDict *d = (FpyDict *)dict_ptr;
        int64_t n = d ? d->length : 0;
        int64_t a[8] = {0};
        extern void fastpy_set_arg_tag(int32_t, int32_t);
        for (int64_t i = 0; i < n && i < 8; i++) {
            a[i] = d->values[i].data.i;
            fastpy_set_arg_tag((int32_t)i, d->values[i].tag);
        }
        typedef int64_t (*fn0_t)(void);
        typedef int64_t (*fn1_t)(int64_t);
        typedef int64_t (*fn2_t)(int64_t, int64_t);
        typedef int64_t (*fn3_t)(int64_t, int64_t, int64_t);
        typedef int64_t (*fn4_t)(int64_t, int64_t, int64_t, int64_t);
        switch (n) {
            case 0: return ((fn0_t)closure)();
            case 1: return ((fn1_t)closure)(a[0]);
            case 2: return ((fn2_t)closure)(a[0], a[1]);
            case 3: return ((fn3_t)closure)(a[0], a[1], a[2]);
            case 4: return ((fn4_t)closure)(a[0], a[1], a[2], a[3]);
            default: return 0;
        }
    }

    FpyClosure *c = (FpyClosure *)closure;
    FpyDict *d = (FpyDict *)dict_ptr;

    /* If target is itself a **kwargs function, forward the dict directly */
    if (c->has_kwarg) {
        int64_t dict_val = (int64_t)(intptr_t)dict_ptr;
        typedef int64_t (*fn1_t)(int64_t);
        typedef int64_t (*fn2c_t)(int64_t, int64_t);
        typedef int64_t (*fn3c_t)(int64_t, int64_t, int64_t);
        typedef int64_t (*fn4c_t)(int64_t, int64_t, int64_t, int64_t);
        switch (c->n_captures) {
            case 0: return ((fn1_t)c->func)(dict_val);
            case 1: return ((fn2c_t)c->func)(dict_val, c->captures[0]);
            case 2: return ((fn3c_t)c->func)(dict_val, c->captures[0], c->captures[1]);
            case 3: return ((fn4c_t)c->func)(dict_val, c->captures[0], c->captures[1], c->captures[2]);
            default: return 0;
        }
    }

    /* Map dict keys to positional args using param_names */
    extern void fastpy_set_arg_tag(int32_t, int32_t);
    int n = c->n_params;
    int64_t args[8] = {0};

    for (int i = 0; i < n && i < 8; i++) {
        int32_t tag = FPY_TAG_NONE;
        int64_t data = 0;
        int found = 0;

        if (c->param_names && c->param_names[i]) {
            found = fpy_dict_try_get(d, c->param_names[i], &tag, &data);
        }

        if (found) {
            args[i] = data;
            fastpy_set_arg_tag(i, tag);
        } else if (c->n_defaults > 0 && i >= n - c->n_defaults) {
            /* Use default value */
            int def_idx = c->n_defaults - (n - i);
            if (def_idx >= 0 && def_idx < c->n_defaults) {
                args[i] = c->defaults[def_idx];
            }
        }
    }

    /* Dispatch with positional args + captures */
    int64_t n_caps = c->n_captures;
    int64_t total = n + n_caps;

    int64_t all[8];
    for (int i = 0; i < n && i < 8; i++) all[i] = args[i];
    for (int64_t i = 0; i < n_caps && (n + i) < 8; i++)
        all[n + i] = c->captures[i];

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

/* enumerate(string) -> list of [index, char] pairs (UTF-8 aware) */
FpyList* fastpy_enumerate_str(const char *s, int64_t start) {
    int64_t len = fastpy_str_len(s);  /* code point count */
    FpyList *result = fpy_list_new(len);
    const unsigned char *p = (const unsigned char *)s;
    int64_t idx = 0;
    while (*p) {
        FpyList *pair = fpy_list_new(2);
        pair->is_tuple = 1;
        fpy_list_append(pair, fpy_int(start + idx));
        int clen = fpy_utf8_cplen(p);
        FpyString *ch = fpy_str_alloc(clen);
        memcpy(ch->data, p, clen);
        ch->data[clen] = '\0';
        fpy_list_append(pair, fpy_str(ch->data));
        fpy_list_append(result, fpy_list(pair));
        p += clen;
        idx++;
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

/* zip(a) — single iterable: wraps each element in a 1-tuple */
FpyList* fastpy_zip1(FpyList *a) {
    FpyList *result = fpy_list_new(a->length);
    for (int64_t i = 0; i < a->length; i++) {
        FpyList *t = fpy_list_new(1);
        t->is_tuple = 1;
        fpy_list_append(t, a->items[i]);
        fpy_list_append(result, fpy_list(t));
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

void fastpy_cell_incref(FpyCell *cell) {
    if (cell) cell->refcount++;
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

/* list.pop() — returns FpyValue via out params, preserving element type */
void fastpy_list_pop_fv(FpyList *list, int32_t *out_tag, int64_t *out_data) {
    FPY_LOCK(list);
    if (list->length == 0) {
        FPY_UNLOCK(list);
        fastpy_raise(FPY_EXC_INDEXERROR, "pop from empty list");
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    list->length--;
    FpyValue v = list->items[list->length];
    *out_tag = v.tag;
    *out_data = v.data.i;
    FPY_UNLOCK(list);
}

/* list.pop(index) — returns FpyValue via out params, preserving element type */
void fastpy_list_pop_at_fv(FpyList *list, int64_t index,
                            int32_t *out_tag, int64_t *out_data) {
    FPY_LOCK(list);
    if (index < 0) index += list->length;
    if (index < 0 || index >= list->length) {
        FPY_UNLOCK(list);
        fastpy_raise(FPY_EXC_INDEXERROR, "pop index out of range");
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    FpyValue v = list->items[index];
    *out_tag = v.tag;
    *out_data = v.data.i;
    for (int64_t i = index; i < list->length - 1; i++) {
        list->items[i] = list->items[i + 1];
    }
    list->length--;
    FPY_UNLOCK(list);
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
    fpy_raise_key_error(k);
    return;
}

void fastpy_dict_delete_int(FpyDict *dict, int64_t key) {
    FPY_LOCK(dict);
    uint64_t h = fpy_hash_int(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);

    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED
            && fpy_key_equal_int(&dict->keys[idx], key)) {
            FPY_VAL_DECREF(dict->keys[idx]);
            FPY_VAL_DECREF(dict->values[idx]);
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
    fpy_raise_key_error(fpy_int(key));
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
    fpy_raise_key_error(k);
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
    fpy_raise_key_error(k);
    return 0;
}

/* dict.pop(key) — 1-arg version, returns FpyValue via out params.
 * Raises KeyError if key is not found. */
void fastpy_dict_pop_nodefault_fv(FpyDict *dict, const char *key,
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
    fpy_raise_key_error(k);
    *out_tag = FPY_TAG_NONE;
    *out_data = 0;
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

/* dict.pop(key) with generic key type — no default, raises KeyError on miss */
void fastpy_dict_pop_nodefault_generic(FpyDict *dict,
                                        int32_t key_tag, int64_t key_data,
                                        int32_t *out_tag, int64_t *out_data) {
    FPY_LOCK(dict);
    FpyValue k; k.tag = key_tag; k.data.i = key_data;
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
    fpy_raise_key_error(k);
    *out_tag = FPY_TAG_NONE;
    *out_data = 0;
}

/* dict.pop(key, default) with generic key type */
void fastpy_dict_pop_generic(FpyDict *dict,
                              int32_t key_tag, int64_t key_data,
                              int32_t def_tag, int64_t def_data,
                              int32_t *out_tag, int64_t *out_data) {
    FPY_LOCK(dict);
    FpyValue k; k.tag = key_tag; k.data.i = key_data;
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
    *out_tag = def_tag;
    *out_data = def_data;
}

void fastpy_dict_setdefault_list(FpyDict *dict, const char *key, FpyList *default_val) {
    if (fastpy_dict_has_key(dict, key)) return;
    fpy_dict_set(dict, fpy_str(key), fpy_list(default_val));
}

void fastpy_dict_setdefault_int(FpyDict *dict, const char *key, int64_t default_val) {
    if (fastpy_dict_has_key(dict, key)) return;
    fpy_dict_set(dict, fpy_str(key), fpy_int(default_val));
}

/* dict.setdefault(key, default) → value. Returns the existing value if key
 * is present, otherwise inserts default and returns it. Uses FpyValue ABI
 * for both the default and the return value. */
void fastpy_dict_setdefault_fv(FpyDict *dict, const char *key,
                                int32_t def_tag, int64_t def_data,
                                int32_t *out_tag, int64_t *out_data) {
    /* Look up the key first */
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
            /* Key found — return existing value */
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return;
        }
        slot = (slot + 1) & mask;
    }
    /* Key not found — insert default and return it */
    FpyValue v; v.tag = def_tag; v.data.i = def_data;
    fpy_dict_set(dict, fpy_str(key), v);
    *out_tag = def_tag;
    *out_data = def_data;
}

/* dict.setdefault(key, default) → value with generic key type.
 * Accepts tag+data for the key so it handles int, str, bool, tuple, etc. */
void fastpy_dict_setdefault_generic(FpyDict *dict,
                                     int32_t key_tag, int64_t key_data,
                                     int32_t def_tag, int64_t def_data,
                                     int32_t *out_tag, int64_t *out_data) {
    FpyValue key; key.tag = key_tag; key.data.i = key_data;
    uint64_t h = fpy_hash_value(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) break;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], key)) {
            /* Key found — return existing value */
            *out_tag = dict->values[idx].tag;
            *out_data = dict->values[idx].data.i;
            return;
        }
        slot = (slot + 1) & mask;
    }
    /* Key not found — insert default and return it */
    FpyValue v; v.tag = def_tag; v.data.i = def_data;
    fpy_dict_set(dict, key, v);
    *out_tag = def_tag;
    *out_data = def_data;
}

/* dict.popitem() — remove and return the last inserted key-value pair */
void fastpy_dict_popitem(FpyDict *dict, int32_t *key_tag, int64_t *key_data,
                          int32_t *val_tag, int64_t *val_data) {
    if (dict->length == 0) {
        fpy_raise_key_error(fpy_str("popitem(): dictionary is empty"));
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
    char *result = fpy_str_buf((int64_t)len);
    for (size_t i = 0; i <= len; i++) {
        result[i] = (s[i] >= 'a' && s[i] <= 'z') ? s[i] - 32 : s[i];
    }
    return result;
}

const char* fastpy_str_capitalize(const char *s) {
    size_t len = strlen(s);
    char *result = fpy_str_buf((int64_t)len);
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
    char *result = fpy_str_buf((int64_t)len);
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
    char *result = fpy_str_buf((int64_t)len);
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
    size_t byte_len = strlen(s);
    int64_t cp_len = fastpy_str_len(s);
    if (cp_len >= width) return fpy_str_from_cstr(s);
    int64_t total_pad = width - cp_len;
    int64_t left = total_pad / 2;
    int64_t right = total_pad - left;
    size_t rsize = byte_len + total_pad;  /* pad chars are ASCII ' ' */
    char *result = fpy_str_buf((int64_t)rsize);
    for (int64_t i = 0; i < left; i++) result[i] = ' ';
    memcpy(result + left, s, byte_len);
    for (int64_t i = 0; i < right; i++) result[left + byte_len + i] = ' ';
    result[rsize] = '\0';
    return result;
}

const char* fastpy_str_ljust(const char *s, int64_t width) {
    size_t byte_len = strlen(s);
    int64_t cp_len = fastpy_str_len(s);
    if (cp_len >= width) return fpy_str_from_cstr(s);
    int64_t pad = width - cp_len;
    size_t rsize = byte_len + pad;
    char *result = fpy_str_buf((int64_t)rsize);
    memcpy(result, s, byte_len);
    for (int64_t i = 0; i < pad; i++) result[byte_len + i] = ' ';
    result[rsize] = '\0';
    return result;
}

const char* fastpy_str_rjust(const char *s, int64_t width) {
    size_t byte_len = strlen(s);
    int64_t cp_len = fastpy_str_len(s);
    if (cp_len >= width) return fpy_str_from_cstr(s);
    int64_t pad = width - cp_len;
    size_t rsize = byte_len + pad;
    char *result = fpy_str_buf((int64_t)rsize);
    for (int64_t i = 0; i < pad; i++) result[i] = ' ';
    memcpy(result + pad, s, byte_len);
    result[rsize] = '\0';
    return result;
}

const char* fastpy_str_zfill(const char *s, int64_t width) {
    size_t byte_len = strlen(s);
    int64_t cp_len = fastpy_str_len(s);
    if (cp_len >= width) return fpy_str_from_cstr(s);
    int64_t pad = width - cp_len;
    size_t rsize = byte_len + pad;
    char *result = fpy_str_buf((int64_t)rsize);
    int src_idx = 0;
    int dst_idx = 0;
    /* Preserve leading sign */
    if (s[0] == '-' || s[0] == '+') {
        result[dst_idx++] = s[0];
        src_idx = 1;
    }
    for (int64_t i = 0; i < pad; i++) result[dst_idx++] = '0';
    for (size_t i = src_idx; i < byte_len; i++) result[dst_idx++] = s[i];
    result[dst_idx] = '\0';
    return result;
}

/* center/ljust/rjust with custom fill character (Python 3.x) */
const char* fastpy_str_center_fill(const char *s, int64_t width, const char *fill) {
    int fc_len = fpy_utf8_cplen((const unsigned char *)fill);
    size_t byte_len = strlen(s);
    int64_t cp_len = fastpy_str_len(s);
    if (cp_len >= width) return fpy_str_from_cstr(s);
    int64_t total_pad = width - cp_len;
    int64_t left = total_pad / 2;
    int64_t right = total_pad - left;
    size_t rsize = byte_len + total_pad * fc_len;
    char *result = fpy_str_buf((int64_t)rsize);
    int64_t off = 0;
    for (int64_t i = 0; i < left; i++) { memcpy(result + off, fill, fc_len); off += fc_len; }
    memcpy(result + off, s, byte_len); off += byte_len;
    for (int64_t i = 0; i < right; i++) { memcpy(result + off, fill, fc_len); off += fc_len; }
    result[off] = '\0';
    return result;
}

const char* fastpy_str_ljust_fill(const char *s, int64_t width, const char *fill) {
    int fc_len = fpy_utf8_cplen((const unsigned char *)fill);
    size_t byte_len = strlen(s);
    int64_t cp_len = fastpy_str_len(s);
    if (cp_len >= width) return fpy_str_from_cstr(s);
    int64_t pad = width - cp_len;
    size_t rsize = byte_len + pad * fc_len;
    char *result = fpy_str_buf((int64_t)rsize);
    memcpy(result, s, byte_len);
    int64_t off = byte_len;
    for (int64_t i = 0; i < pad; i++) { memcpy(result + off, fill, fc_len); off += fc_len; }
    result[off] = '\0';
    return result;
}

const char* fastpy_str_rjust_fill(const char *s, int64_t width, const char *fill) {
    int fc_len = fpy_utf8_cplen((const unsigned char *)fill);
    size_t byte_len = strlen(s);
    int64_t cp_len = fastpy_str_len(s);
    if (cp_len >= width) return fpy_str_from_cstr(s);
    int64_t pad = width - cp_len;
    size_t rsize = byte_len + pad * fc_len;
    char *result = fpy_str_buf((int64_t)rsize);
    int64_t off = 0;
    for (int64_t i = 0; i < pad; i++) { memcpy(result + off, fill, fc_len); off += fc_len; }
    memcpy(result + off, s, byte_len);
    result[rsize] = '\0';
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
    if (!s) return fpy_str_from_cstr("");
    size_t len = strlen(s);
    char *result = fpy_str_buf((int64_t)len);
    for (size_t i = 0; i <= len; i++) {
        char c = s[i];
        if (c >= 'A' && c <= 'Z') c = c + ('a' - 'A');
        result[i] = c;
    }
    return result;
}

/* str.expandtabs(tabsize) — column counter uses code points, not bytes */
const char* fastpy_str_expandtabs(const char *s, int64_t tabsize) {
    if (!s) return fpy_str_from_cstr("");
    const unsigned char *p;
    /* First pass: count output byte length */
    size_t out_len = 0;
    size_t col = 0;
    for (p = (const unsigned char *)s; *p; ) {
        if (*p == '\t') {
            int64_t spaces = tabsize - (int64_t)(col % (size_t)tabsize);
            if (tabsize <= 0) spaces = 0;
            out_len += (size_t)spaces;
            col += (size_t)spaces;
            p++;
        } else if (*p == '\n' || *p == '\r') {
            out_len++;
            col = 0;
            p++;
        } else {
            int cplen = fpy_utf8_cplen(p);
            out_len += cplen;   /* copy all bytes of the code point */
            col++;              /* but only advance column by 1 */
            p += cplen;
        }
    }
    char *result = fpy_str_buf((int64_t)out_len);
    size_t i = 0;
    col = 0;
    for (p = (const unsigned char *)s; *p; ) {
        if (*p == '\t') {
            int64_t spaces = tabsize - (int64_t)(col % (size_t)tabsize);
            if (tabsize <= 0) spaces = 0;
            for (int64_t j = 0; j < spaces; j++) result[i++] = ' ';
            col += (size_t)spaces;
            p++;
        } else if (*p == '\n' || *p == '\r') {
            result[i++] = (char)*p;
            col = 0;
            p++;
        } else {
            int cplen = fpy_utf8_cplen(p);
            for (int k = 0; k < cplen; k++) result[i++] = (char)p[k];
            col++;
            p += cplen;
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
        const char *after = found + sep_len;
        /* Header-backed copies so each tuple element is a valid STR value. */
        fpy_list_append(result, fpy_str(fpy_str_copy(s, (int64_t)before_len)));
        fpy_list_append(result, fpy_str(fpy_str_from_cstr(sep)));
        fpy_list_append(result, fpy_str(fpy_str_from_cstr(after)));
    } else {
        fpy_list_append(result, fpy_str(fpy_str_from_cstr(s)));
        fpy_list_append(result, fpy_str(fpy_str_from_cstr("")));
        fpy_list_append(result, fpy_str(fpy_str_from_cstr("")));
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
        const char *after = last + seplen;
        fpy_list_append(result, fpy_str(fpy_str_copy(s, (int64_t)before_len)));
        fpy_list_append(result, fpy_str(fpy_str_from_cstr(sep)));
        fpy_list_append(result, fpy_str(fpy_str_from_cstr(after)));
    } else {
        fpy_list_append(result, fpy_str(fpy_str_from_cstr("")));
        fpy_list_append(result, fpy_str(fpy_str_from_cstr("")));
        fpy_list_append(result, fpy_str(fpy_str_from_cstr(s)));
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
            fpy_list_append(result, fpy_str(fpy_str_copy(s + start, (int64_t)line_len)));
            if (s[i] == '\r' && i + 1 < len && s[i + 1] == '\n') i += 2;
            else i++;
            start = i;
        } else {
            i++;
        }
    }
    if (start < len) {
        size_t line_len = len - start;
        fpy_list_append(result, fpy_str(fpy_str_copy(s + start, (int64_t)line_len)));
    }
    return result;
}

/* str.rsplit() — split on whitespace (no args). Result is identical to
   str.split() since without maxsplit, order is the same. */
FpyList* fastpy_str_rsplit_ws(const char *s) {
    return fastpy_str_split(s);
}

/* str.rsplit(sep, maxsplit) — split from the right.
 * sep == NULL means split on whitespace (Python: s.rsplit(None, n)). */
FpyList* fastpy_str_rsplit(const char *s, const char *sep, int64_t max_split) {
    if (sep == NULL) {
        if (max_split < 0)
            return fastpy_str_split(s);
        /* Whitespace rsplit: split from the right up to max_split times.
         * Strategy: collect all words left-to-right, then only split the
         * last max_split ones (join the rest as the first element). */
        size_t len = strlen(s);
        /* Collect word boundaries (start, end) */
        size_t starts[256], ends[256];
        int n_words = 0;
        size_t i = 0;
        while (i < len) {
            while (i < len && (s[i]==' '||s[i]=='\t'||s[i]=='\n'||
                               s[i]=='\r'||s[i]=='\f'||s[i]=='\v')) i++;
            if (i >= len) break;
            size_t ws = i;
            while (i < len && s[i]!=' '&&s[i]!='\t'&&s[i]!='\n'&&
                   s[i]!='\r'&&s[i]!='\f'&&s[i]!='\v') i++;
            if (n_words < 256) {
                starts[n_words] = ws;
                ends[n_words] = i;
                n_words++;
            }
        }
        FpyList *result = fpy_list_new(0);
        if (n_words == 0) return result;
        int split_from = n_words - max_split;
        if (split_from < 0) split_from = 0;
        if (split_from > 0) {
            /* Join words 0..split_from-1 plus intervening whitespace
             * as the first element (everything from start of first word
             * to end of word split_from-1). */
            size_t seg_start = starts[0];
            size_t seg_end = ends[split_from - 1];
            size_t seg_len = seg_end - seg_start;
            fpy_list_append(result, fpy_str(fpy_str_copy(s + seg_start, (int64_t)seg_len)));
        }
        for (int w = (split_from > 0 ? split_from : 0); w < n_words; w++) {
            size_t seg_len = ends[w] - starts[w];
            fpy_list_append(result, fpy_str(fpy_str_copy(s + starts[w], (int64_t)seg_len)));
        }
        return result;
    }
    size_t s_len = strlen(s);
    size_t sep_len = strlen(sep);
    if (sep_len == 0) {
        FpyList *result = fpy_list_new(1);
        fpy_list_append(result, fpy_str(fpy_str_from_cstr(s)));
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
        fpy_list_append(parts, fpy_str(fpy_str_from_cstr(s)));
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
        fpy_list_append(parts, fpy_str(fpy_str_copy(s, (int64_t)len)));
        seg_start = positions[start_idx] + sep_len;
    }
    for (int64_t i = start_idx; i < n_pos; i++) {
        if (i == start_idx && start_idx == 0) {
            size_t len = positions[i];
            fpy_list_append(parts, fpy_str(fpy_str_copy(s, (int64_t)len)));
            seg_start = positions[i] + sep_len;
        } else if (i > start_idx) {
            size_t len = positions[i] - seg_start;
            fpy_list_append(parts, fpy_str(fpy_str_copy(s + seg_start, (int64_t)len)));
            seg_start = positions[i] + sep_len;
        }
    }
    /* Remainder after last separator */
    size_t rem_len = s_len - seg_start;
    fpy_list_append(parts, fpy_str(fpy_str_copy(s + seg_start, (int64_t)rem_len)));
    free(positions);
    return parts;
}

FpyList* fastpy_str_split_max(const char *s, const char *sep, int64_t max_split) {
    /* sep == NULL means split on whitespace (Python: s.split(None, n)) */
    if (sep == NULL) {
        if (max_split < 0)
            return fastpy_str_split(s);
        /* Whitespace split with maxsplit limit */
        FpyList *result = fpy_list_new(0);
        size_t len = strlen(s);
        size_t i = 0;
        int64_t splits = 0;
        while (i < len && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n'
                           || s[i] == '\r' || s[i] == '\f' || s[i] == '\v'))
            i++;
        while (i < len) {
            if (splits >= max_split) {
                /* Remainder of string (including leading whitespace already skipped) */
                size_t rest_len = len - i;
                fpy_list_append(result, fpy_str(fpy_str_copy(s + i, (int64_t)rest_len)));
                break;
            }
            size_t start = i;
            while (i < len && s[i] != ' ' && s[i] != '\t' && s[i] != '\n'
                   && s[i] != '\r' && s[i] != '\f' && s[i] != '\v')
                i++;
            size_t seg_len = i - start;
            fpy_list_append(result, fpy_str(fpy_str_copy(s + start, (int64_t)seg_len)));
            splits++;
            while (i < len && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n'
                               || s[i] == '\r' || s[i] == '\f' || s[i] == '\v'))
                i++;
        }
        return result;
    }
    FpyList *result = fpy_list_new(0);
    size_t sep_len = strlen(sep);
    size_t s_len = strlen(s);
    if (sep_len == 0) {
        fpy_list_append(result, fpy_str(fpy_str_from_cstr(s)));
        return result;
    }
    const char *p = s;
    const char *end = s + s_len;
    int64_t splits = 0;
    while (p <= end) {
        if (max_split >= 0 && splits >= max_split) {
            size_t rest_len = end - p;
            /* Use fpy_str_copy so the result carries a proper FpyString header
               (magic + refcount); a bare malloc would be headerless and cause
               an OOB read in fpy_str_header on incref/decref.
               See BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC. */
            fpy_list_append(result, fpy_str(fpy_str_copy(p, (int64_t)rest_len)));
            break;
        }
        const char *q = (p <= end) ? strstr(p, sep) : NULL;
        if (!q) {
            /* No more separators — add the rest of the string (may be empty
               if the string ended with the separator, which is correct:
               "a ".split(" ") → ["a", ""]). */
            size_t rest_len = end - p;
            fpy_list_append(result, fpy_str(fpy_str_copy(p, (int64_t)rest_len)));
            break;
        }
        size_t seg_len = q - p;
        fpy_list_append(result, fpy_str(fpy_str_copy(p, (int64_t)seg_len)));
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
    if (old_len == 0) {
        /* Python: "abc".replace("", "x") → "xaxbxcx"
         * Insert new_str at every position (n+1 positions for n chars). */
        size_t n_inserts = s_len + 1;
        size_t result_len = s_len + n_inserts * new_len;
        char *result = fpy_str_buf((int64_t)result_len);
        char *dst = result;
        for (size_t i = 0; i <= s_len; i++) {
            memcpy(dst, new_str, new_len);
            dst += new_len;
            if (i < s_len) *dst++ = s[i];
        }
        *dst = '\0';
        return result;
    }

    /* Count occurrences */
    int count = 0;
    const char *p = s;
    while ((p = strstr(p, old)) != NULL) { count++; p += old_len; }

    size_t result_len = s_len + count * (new_len - old_len);
    char *result = fpy_str_buf((int64_t)result_len);
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
        char *copy = fpy_str_buf((int64_t)s_len);
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
    char *result = fpy_str_buf((int64_t)result_len);
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
        char *result = fpy_str_buf((int64_t)rlen);
        memcpy(result, s + plen, rlen);
        result[rlen] = '\0';
        return result;
    }
    /* No match — return a copy of the original string */
    size_t slen = strlen(s);
    char *copy = fpy_str_buf((int64_t)slen);
    memcpy(copy, s, slen + 1);
    return copy;
}

/* String removesuffix (Python 3.9+) */
const char* fastpy_str_removesuffix(const char *s, const char *suffix) {
    size_t slen = strlen(s);
    size_t suflen = strlen(suffix);
    if (suflen <= slen && strcmp(s + slen - suflen, suffix) == 0) {
        size_t rlen = slen - suflen;
        char *result = fpy_str_buf((int64_t)rlen);
        memcpy(result, s, rlen);
        result[rlen] = '\0';
        return result;
    }
    /* No match — return a copy of the original string */
    char *copy = fpy_str_buf((int64_t)slen);
    memcpy(copy, s, slen + 1);
    return copy;
}

/* String contains (for 'in' operator) */
int fastpy_str_contains(const char *haystack, const char *needle) {
    return strstr(haystack, needle) != NULL;
}

/* `x in b"..."` — dispatches on the tag of the left operand, because Python
 * gives the two forms different meanings: an int asks whether that byte value
 * occurs, a bytes/str asks whether it occurs as a contiguous subsequence
 * (and the empty one always does).  Length-aware throughout, so an embedded
 * null byte is matched rather than ending the search.  `in` on a bytes had no
 * arm at all in the emitter and fell through to the CPython `__contains__`
 * bridge, which faults on Windows and returns NULL in pure mode.
 * BUG-BYTES-CONTAINS-NO-ARM. */
int fastpy_bytes_contains(const char *hay, int32_t tag, int64_t data) {
    if (hay == NULL) return 0;
    int64_t n = fpy_bytes_len(hay);
    if (tag == FPY_TAG_INT || tag == FPY_TAG_BOOL) {
        /* CPython rejects an out-of-range int rather than answering False. */
        if (data < 0 || data > 255) {
            fastpy_raise(FPY_EXC_VALUEERROR, "byte must be in range(0, 256)");
            return 0;
        }
        for (int64_t i = 0; i < n; i++)
            if ((unsigned char)hay[i] == (unsigned char)data) return 1;
        return 0;
    }
    if (tag == FPY_TAG_BYTES || tag == FPY_TAG_STR) {
        const char *needle = (const char *)(intptr_t)data;
        if (needle == NULL) return 0;
        int64_t m = (tag == FPY_TAG_BYTES) ? fpy_bytes_len(needle)
                                           : (int64_t)strlen(needle);
        if (m == 0) return 1;
        if (m > n) return 0;
        for (int64_t i = 0; i + m <= n; i++)
            if (memcmp(hay + i, needle, (size_t)m) == 0) return 1;
        return 0;
    }
    fastpy_raise(FPY_EXC_TYPEERROR,
                 "a bytes-like object is required for 'in'");
    return 0;
}

/* `bytes(x)` / `bytearray(x)` — the builtin had no native lowering at all and
 * went through the CPython bridge, so in pure mode (SlateOS) it answered NULL
 * and the next `fpy_bytes_len` walked off a null pointer.  Dispatches on the
 * runtime tag because the argument's kind is often only known then; the shape
 * mirrors `fastpy_fv_to_list`, and anything iterable is routed through that
 * so sets, dicts, ranges and generators need no separate arm here.
 * BUG-BYTES-CTOR-BRIDGE-ONLY. */
extern FpyList* fastpy_fv_to_list(int32_t tag, int64_t data);

const char* fastpy_fv_to_bytes(int32_t tag, int64_t data) {
    if (tag == FPY_TAG_INT || tag == FPY_TAG_BOOL) {
        /* bytes(n) → n zero bytes. */
        int64_t n = data;
        if (n < 0) {
            fastpy_raise(FPY_EXC_VALUEERROR, "negative count");
            n = 0;
        }
        char *out = fpy_bytes_alloc(n);
        if (n > 0) memset(out, 0, (size_t)n);
        return out;
    }
    if (tag == FPY_TAG_BYTES) {
        const char *src = (const char *)(intptr_t)data;
        if (src == NULL) return fpy_bytes_alloc(0);
        int64_t n = fpy_bytes_len(src);
        char *out = fpy_bytes_alloc(n);
        if (n > 0) memcpy(out, src, (size_t)n);
        return out;
    }
    if (tag == FPY_TAG_STR) {
        fastpy_raise(FPY_EXC_TYPEERROR,
                     "string argument without an encoding");
        return fpy_bytes_alloc(0);
    }
    if (tag == FPY_TAG_NONE) {
        fastpy_raise(FPY_EXC_TYPEERROR,
                     "cannot convert 'NoneType' object to bytes");
        return fpy_bytes_alloc(0);
    }
    FpyList *items = fastpy_fv_to_list(tag, data);
    if (items == NULL) return fpy_bytes_alloc(0);
    int64_t n = items->length;
    char *out = fpy_bytes_alloc(n);
    for (int64_t i = 0; i < n; i++) {
        FpyValue v = items->items[i];
        if (v.tag != FPY_TAG_INT && v.tag != FPY_TAG_BOOL) {
            fastpy_raise(FPY_EXC_TYPEERROR,
                         "bytes must be an iterable of integers");
            return out;
        }
        if (v.data.i < 0 || v.data.i > 255) {
            fastpy_raise(FPY_EXC_VALUEERROR, "bytes must be in range(0, 256)");
            return out;
        }
        out[i] = (char)(unsigned char)v.data.i;
    }
    return out;
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

/* List count — count occurrences.
   Python semantics: True == 1 and False == 0, so list.count(True)
   counts both True and 1, and list.count(1) counts both 1 and True. */
int64_t fastpy_list_count(FpyList *list, int64_t value) {
    int64_t count = 0;
    for (int64_t i = 0; i < list->length; i++) {
        int32_t t = list->items[i].tag;
        if ((t == FPY_TAG_INT || t == FPY_TAG_BOOL)
            && list->items[i].data.i == value) {
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

/* Python whitespace helpers (UTF-8 aware).
 * Python's definition of whitespace for str.strip/isspace:
 *   ASCII: \t(09) \n(0A) \x0b(0B) \x0c(0C) \r(0D) \x1c(1C) \x1d(1D) \x1e(1E) \x1f(1F) space(20)
 *   Non-ASCII (2-byte UTF-8): U+0085 NEL (C2 85), U+00A0 NBSP (C2 A0)
 */
static int _fpy_ws_fwd(const unsigned char *p) {
    unsigned char c = *p;
    if (c == ' ' || c == '\t' || c == '\n' || c == '\r' ||
        c == 0x0b || c == 0x0c ||
        c == 0x1c || c == 0x1d || c == 0x1e || c == 0x1f)
        return 1;
    if (c == 0xc2 && (p[1] == 0x85 || p[1] == 0xa0))
        return 2;
    return 0;
}

/* Check for whitespace ending at position (end points one past last byte). */
static int _fpy_ws_back(const unsigned char *start, const unsigned char *end) {
    if (end <= start) return 0;
    unsigned char last = end[-1];
    if (last == ' ' || last == '\t' || last == '\n' || last == '\r' ||
        last == 0x0b || last == 0x0c ||
        last == 0x1c || last == 0x1d || last == 0x1e || last == 0x1f)
        return 1;
    if (end - start >= 2 && end[-2] == 0xc2 && (last == 0x85 || last == 0xa0))
        return 2;
    return 0;
}

/* String strip */
const char* fastpy_str_strip(const char *s) {
    const unsigned char *start = (const unsigned char *)s;
    int n;
    while ((n = _fpy_ws_fwd(start)) > 0) start += n;
    const unsigned char *end = (const unsigned char *)s + strlen(s);
    while ((n = _fpy_ws_back(start, end)) > 0) end -= n;
    size_t len = end - start;
    char *result = fpy_str_buf((int64_t)len);
    memcpy(result, start, len);
    result[len] = '\0';
    return result;
}

const char* fastpy_str_lstrip(const char *s) {
    const unsigned char *start = (const unsigned char *)s;
    int n;
    while ((n = _fpy_ws_fwd(start)) > 0) start += n;
    return fpy_str_from_cstr((const char *)start);
}

const char* fastpy_str_rstrip(const char *s) {
    size_t slen = strlen(s);
    const unsigned char *start = (const unsigned char *)s;
    const unsigned char *end = start + slen;
    int n;
    while ((n = _fpy_ws_back(start, end)) > 0) end -= n;
    size_t len = end - start;
    char *result = fpy_str_buf((int64_t)len);
    memcpy(result, start, len);
    result[len] = '\0';
    return result;
}

const char* fastpy_str_strip_chars(const char *s, const char *chars) {
    const char *start = s;
    while (*start && strchr(chars, *start)) start++;
    const char *end = s + strlen(s) - 1;
    while (end >= start && strchr(chars, *end)) end--;
    size_t len = end - start + 1;
    char *result = fpy_str_buf((int64_t)len);
    memcpy(result, start, len);
    result[len] = '\0';
    return result;
}

const char* fastpy_str_lstrip_chars(const char *s, const char *chars) {
    const char *start = s;
    while (*start && strchr(chars, *start)) start++;
    return fpy_str_from_cstr(start);
}

const char* fastpy_str_rstrip_chars(const char *s, const char *chars) {
    size_t slen = strlen(s);
    if (slen == 0) return fpy_str_from_cstr(s);
    const char *end = s + slen - 1;
    while (end >= s && strchr(chars, *end)) end--;
    size_t len = end - s + 1;
    char *result = fpy_str_buf((int64_t)len);
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
    const unsigned char *p = (const unsigned char *)s;
    while (*p) {
        int n = _fpy_ws_fwd(p);
        if (n == 0) return 0;
        p += n;
    }
    return 1;
}

const char* fastpy_chr(int64_t code) {
    /* Only ASCII — no Unicode support yet */
    char *result = fpy_str_buf(2);
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
        /* The message goes in the shared buffer, not a fresh malloc: since
         * `fastpy_raise` copies it into the exception slot's own refcounted
         * string, a malloc here would be a straight leak — one per failed
         * conversion. The literal is truncated at 160 chars, which no
         * *parseable* number ever reaches. */
        snprintf(_err_buf, sizeof(_err_buf),
                 "invalid literal for int() with base 10: '%.160s'", s);
        fastpy_raise(FPY_EXC_VALUEERROR, _err_buf);
        return 0;
    }
    char *end;
    int64_t result = (int64_t)strtoll(start, &end, 10);
    /* Check for trailing garbage (other than whitespace) */
    while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r') end++;
    if (*end != '\0') {
        snprintf(_err_buf, sizeof(_err_buf),
                 "invalid literal for int() with base 10: '%.160s'", s);
        fastpy_raise(FPY_EXC_VALUEERROR, _err_buf);
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
        snprintf(_err_buf, sizeof(_err_buf),
                 "invalid literal for int() with base %lld: '%.160s'",
                 (long long)base, s);
        fastpy_raise(FPY_EXC_VALUEERROR, _err_buf);
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
        snprintf(_err_buf, sizeof(_err_buf),
                 "could not convert string to float: '%.160s'", s);
        fastpy_raise(FPY_EXC_VALUEERROR, _err_buf);
        return 0.0;
    }
    char *end;
    double result = strtod(p, &end);
    while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r') end++;
    if (*end != '\0' || end == p) {
        snprintf(_err_buf, sizeof(_err_buf),
                 "could not convert string to float: '%.160s'", s);
        fastpy_raise(FPY_EXC_VALUEERROR, _err_buf);
        return 0.0;
    }
    return result;
}

const char* fastpy_hex(int64_t value) {
    char *buf = fpy_str_buf(32);
    if (value < 0) {
        snprintf(buf, 32, "-0x%llx", (long long)(-value));
    } else {
        snprintf(buf, 32, "0x%llx", (long long)value);
    }
    return buf;
}

const char* fastpy_oct(int64_t value) {
    char *buf = fpy_str_buf(32);
    if (value < 0) {
        snprintf(buf, 32, "-0o%llo", (long long)(-value));
    } else {
        snprintf(buf, 32, "0o%llo", (long long)value);
    }
    return buf;
}

const char* fastpy_bin(int64_t value) {
    char *buf = fpy_str_buf(80);
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
    /* buf grows via realloc, which is incompatible with a header-backed
       allocation; copy the finished result into a headered string so the
       returned STR value is valid. See BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC. */
    const char *result = fpy_str_copy(buf, (int64_t)out);
    free(buf);
    return result;
}

const char* fastpy_str_repr(const char *s) {
    if (!s) s = "";
    size_t len = strlen(s);
    /* Worst case is four output chars per input char (\xNN), plus the two
     * quotes; fpy_str_buf adds the terminator. The old sizing was len*2+2,
     * which fit the escapes this routine used to emit but leaves no room for
     * the \xNN form it now shares with fpy_value_repr. */
    int cap = (int)(len * 4 + 2);
    char *buf = fpy_str_buf((int64_t)cap);
    char q = fpy_repr_quote(s, len);
    int out = 0;
    buf[out++] = q;
    out += fpy_repr_escape_body(s, len, q, buf + out, cap + 1 - out);
    buf[out++] = q;
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
    return fpy_byte_to_cp(s, (int64_t)(p - s));
}

int64_t fastpy_str_rfind(const char *s, const char *sub) {
    size_t sub_len = strlen(sub);
    size_t s_len = strlen(s);
    if (sub_len == 0) return fastpy_str_len(s);  /* code point count */
    if (sub_len > s_len) return -1;
    for (int64_t i = (int64_t)(s_len - sub_len); i >= 0; i--) {
        if (memcmp(s + i, sub, sub_len) == 0) {
            return fpy_byte_to_cp(s, i);
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
    if (sub_len == 0) return fastpy_str_len(s) + 1;  /* code point count + 1 */
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
    int64_t cp_len = fastpy_str_len(s);
    /* Clamp start/end (code-point positions) like Python */
    if (start < 0) { start += cp_len; if (start < 0) start = 0; }
    if (end < 0) { end += cp_len; if (end < 0) end = 0; }
    if (end > cp_len) end = cp_len;
    if (start > end) return -1;
    size_t sub_len = strlen(sub);
    if (sub_len == 0) return start;
    /* Convert code-point positions to byte offsets for the search window */
    int64_t byte_start = fpy_cp_to_byte(s, start);
    int64_t byte_end = fpy_cp_to_byte(s, end);
    if ((int64_t)sub_len > byte_end - byte_start) return -1;
    for (int64_t i = byte_start; i <= byte_end - (int64_t)sub_len; i++) {
        if (memcmp(s + i, sub, sub_len) == 0)
            return fpy_byte_to_cp(s, i);
    }
    return -1;
}

/* str.rfind(sub, start, end) — reverse search within slice */
int64_t fastpy_str_rfind_range(const char *s, const char *sub,
                                int64_t start, int64_t end) {
    int64_t cp_len = fastpy_str_len(s);
    if (start < 0) { start += cp_len; if (start < 0) start = 0; }
    if (end < 0) { end += cp_len; if (end < 0) end = 0; }
    if (end > cp_len) end = cp_len;
    if (start > end) return -1;
    size_t sub_len = strlen(sub);
    int64_t byte_start = fpy_cp_to_byte(s, start);
    int64_t byte_end = fpy_cp_to_byte(s, end);
    if (sub_len == 0) return end;
    if ((int64_t)sub_len > byte_end - byte_start) return -1;
    for (int64_t i = byte_end - (int64_t)sub_len; i >= byte_start; i--) {
        if (memcmp(s + i, sub, sub_len) == 0)
            return fpy_byte_to_cp(s, i);
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
    int64_t cp_len = fastpy_str_len(s);
    if (start < 0) { start += cp_len; if (start < 0) start = 0; }
    if (end < 0) { end += cp_len; if (end < 0) end = 0; }
    if (end > cp_len) end = cp_len;
    if (start > end) return 0;
    size_t sub_len = strlen(sub);
    if (sub_len == 0) return end - start + 1;
    int64_t byte_start = fpy_cp_to_byte(s, start);
    int64_t byte_end = fpy_cp_to_byte(s, end);
    int64_t count = 0;
    for (int64_t i = byte_start; i <= byte_end - (int64_t)sub_len; i++) {
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
    int64_t cp_len = fastpy_str_len(s);
    if (start < 0) { start += cp_len; if (start < 0) start = 0; }
    if (end < 0) { end += cp_len; if (end < 0) end = 0; }
    if (end > cp_len) end = cp_len;
    if (start > end) return 0;
    size_t plen = strlen(prefix);
    int64_t byte_start = fpy_cp_to_byte(s, start);
    int64_t byte_end = fpy_cp_to_byte(s, end);
    if ((int64_t)plen > byte_end - byte_start) return 0;
    return memcmp(s + byte_start, prefix, plen) == 0;
}

/* str.endswith(suffix, start, end) — check suffix within slice */
int32_t fastpy_str_endswith_range(const char *s, const char *suffix,
                                   int64_t start, int64_t end) {
    int64_t cp_len = fastpy_str_len(s);
    if (start < 0) { start += cp_len; if (start < 0) start = 0; }
    if (end < 0) { end += cp_len; if (end < 0) end = 0; }
    if (end > cp_len) end = cp_len;
    if (start > end) return 0;
    size_t slen = strlen(suffix);
    int64_t byte_end = fpy_cp_to_byte(s, end);
    int64_t byte_start = fpy_cp_to_byte(s, start);
    if ((int64_t)slen > byte_end - byte_start) return 0;
    return memcmp(s + byte_end - slen, suffix, slen) == 0;
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
    char *result = fpy_str_buf((int64_t)len);
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
        char *copy = fpy_str_buf((int64_t)slen);
        memcpy(copy, s, slen + 1);
        return copy;
    }
    char *result = fpy_str_buf((int64_t)slen);
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

/* Extended-slice assignment: list[start:stop:step] = new_values.
 * CPython requires len(new_values) == len(selected_indices), raises
 * ValueError otherwise.  Unlike contiguous slice assignment, extended
 * slices cannot change the list length. */
void fastpy_list_slice_step_assign(FpyList *list, int64_t start, int64_t stop,
                                    int64_t step, int64_t has_start,
                                    int64_t has_stop, FpyList *new_values) {
    FPY_LOCK(list);
    int64_t len = list->length;

    if (step == 0) {
        FPY_UNLOCK(list);
        fastpy_raise(FPY_EXC_VALUEERROR, "slice step cannot be zero");
        return;
    }

    /* Normalize start/stop like CPython */
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

    /* Count how many indices the slice selects */
    int64_t slice_len = 0;
    if (step > 0) {
        for (int64_t i = start; i < stop; i += step) slice_len++;
    } else {
        for (int64_t i = start; i > stop; i += step)
            if (i >= 0 && i < len) slice_len++;
    }

    /* CPython: extended slice assignment requires exact size match */
    if (new_values->length != slice_len) {
        FPY_UNLOCK(list);
        snprintf(_err_buf, sizeof(_err_buf),
                 "attempt to assign sequence of size %lld "
                 "to extended slice of size %lld",
                 (long long)new_values->length, (long long)slice_len);
        fastpy_raise(FPY_EXC_VALUEERROR, _err_buf);
        return;
    }

    /* Assign values to the selected indices */
    int64_t vi = 0;
    if (step > 0) {
        for (int64_t i = start; i < stop && vi < new_values->length; i += step) {
            FPY_VAL_DECREF(list->items[i]);
            FPY_VAL_INCREF(new_values->items[vi]);
            list->items[i] = new_values->items[vi];
            vi++;
        }
    } else {
        for (int64_t i = start; i > stop && vi < new_values->length; i += step) {
            if (i >= 0 && i < len) {
                FPY_VAL_DECREF(list->items[i]);
                FPY_VAL_INCREF(new_values->items[vi]);
                list->items[i] = new_values->items[vi];
                vi++;
            }
        }
    }
    FPY_UNLOCK(list);
}

/* Step-slice deletion: del lst[start:stop:step]
 * Removes elements at positions selected by the extended slice.
 * For positive step: collects indices, removes from highest to lowest. */
void fastpy_list_slice_step_delete(FpyList *list, int64_t start, int64_t stop,
                                    int64_t step, int64_t has_start,
                                    int64_t has_stop) {
    FPY_LOCK(list);
    int64_t len = list->length;

    if (step == 0) {
        FPY_UNLOCK(list);
        fastpy_raise(FPY_EXC_VALUEERROR, "slice step cannot be zero");
        return;
    }

    /* Normalize start/stop like CPython */
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

    /* Collect indices to delete */
    int64_t *indices = (int64_t*)malloc(len * sizeof(int64_t));
    int64_t n = 0;
    if (step > 0) {
        for (int64_t i = start; i < stop; i += step)
            if (i >= 0 && i < len) indices[n++] = i;
    } else {
        for (int64_t i = start; i > stop; i += step)
            if (i >= 0 && i < len) indices[n++] = i;
    }

    if (n == 0) {
        free(indices);
        FPY_UNLOCK(list);
        return;
    }

    /* Sort indices ascending (for negative step they're reversed) */
    for (int64_t i = 0; i < n - 1; i++)
        for (int64_t j = i + 1; j < n; j++)
            if (indices[i] > indices[j]) {
                int64_t tmp = indices[i];
                indices[i] = indices[j];
                indices[j] = tmp;
            }

    /* Decref removed elements */
    for (int64_t i = 0; i < n; i++)
        FPY_VAL_DECREF(list->items[indices[i]]);

    /* Compact: shift elements to fill gaps.
     * Walk two pointers: src reads all items, dst writes kept items. */
    int64_t dst = indices[0];
    int64_t di = 0;  /* index into indices[] */
    for (int64_t src = indices[0]; src < len; src++) {
        if (di < n && src == indices[di]) {
            di++;
            continue;  /* skip deleted element */
        }
        list->items[dst++] = list->items[src];
    }
    list->length = len - n;
    free(indices);
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

/* List concatenation.  Preserves tuple flag when both inputs are tuples. */
FpyList* fastpy_list_concat(FpyList *a, FpyList *b) {
    FpyList *result = fpy_list_new(a->length + b->length);
    for (int64_t i = 0; i < a->length; i++) fpy_list_append(result, a->items[i]);
    for (int64_t i = 0; i < b->length; i++) fpy_list_append(result, b->items[i]);
    if (a->is_tuple && b->is_tuple) result->is_tuple = 1;
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
    char *buf = fpy_str_buf((width > tlen ? width : tlen) + 1);
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
    /* Parse Python format spec:
     *   [[fill]align][sign][#][0][width][,|_][type]
     * Supported types: b d o x X c n (default 'd'). */
    int i = 0;
    char fill = ' ';
    char align = '>';  /* default right-align for numbers */

    /* [fill]align — fill is any char if followed by <, >, ^, = */
    if (spec[i] != '\0' && (spec[i+1] == '<' || spec[i+1] == '>'
                             || spec[i+1] == '^' || spec[i+1] == '=')) {
        fill = spec[i];
        align = spec[i+1];
        i += 2;
    } else if (spec[i] == '<' || spec[i] == '>' || spec[i] == '^' || spec[i] == '=') {
        align = spec[i];
        i++;
    }

    /* sign */
    char sign = '\0';
    if (spec[i] == '+' || spec[i] == '-' || spec[i] == ' ') {
        sign = spec[i]; i++;
    }

    /* alternate form */
    int alt = 0;
    if (spec[i] == '#') { alt = 1; i++; }

    /* zero-pad shorthand: '0' means fill='0', align='=' */
    if (spec[i] == '0') {
        if (fill == ' ') fill = '0';
        if (align == '>') align = '=';
        i++;
    }

    /* width */
    int width = 0;
    while (spec[i] >= '0' && spec[i] <= '9') {
        width = width * 10 + (spec[i] - '0'); i++;
    }

    /* grouping */
    char grouping = '\0';
    if (spec[i] == ',' || spec[i] == '_') { grouping = spec[i]; i++; }

    /* type */
    char type = spec[i] ? spec[i] : 'd';

    /* Decompose value into sign_char + unsigned magnitude */
    int is_neg = 0;
    uint64_t abs_val;
    if (value < 0 && type != 'c') {
        is_neg = 1;
        abs_val = (uint64_t)(-(value + 1)) + 1; /* avoid UB on INT64_MIN */
    } else {
        abs_val = (uint64_t)value;
    }

    char sign_char = '\0';
    if (is_neg) sign_char = '-';
    else if (sign == '+') sign_char = '+';
    else if (sign == ' ') sign_char = ' ';

    /* Format digits based on type */
    char digits[128];
    int dlen = 0;
    char prefix[4] = "";
    int plen = 0;

    switch (type) {
    case 'b': {
        if (abs_val == 0) {
            digits[0] = '0'; dlen = 1;
        } else {
            char rev[65]; int ri = 0;
            uint64_t v = abs_val;
            while (v > 0) { rev[ri++] = '0' + (v & 1); v >>= 1; }
            for (int j = ri - 1; j >= 0; j--) digits[dlen++] = rev[j];
        }
        if (alt) { prefix[0] = '0'; prefix[1] = 'b'; plen = 2; }
        break;
    }
    case 'o': {
        snprintf(digits, sizeof(digits), "%llo", (unsigned long long)abs_val);
        dlen = (int)strlen(digits);
        if (alt) { prefix[0] = '0'; prefix[1] = 'o'; plen = 2; }
        break;
    }
    case 'x': {
        snprintf(digits, sizeof(digits), "%llx", (unsigned long long)abs_val);
        dlen = (int)strlen(digits);
        if (alt) { prefix[0] = '0'; prefix[1] = 'x'; plen = 2; }
        break;
    }
    case 'X': {
        snprintf(digits, sizeof(digits), "%llX", (unsigned long long)abs_val);
        dlen = (int)strlen(digits);
        if (alt) { prefix[0] = '0'; prefix[1] = 'X'; plen = 2; }
        break;
    }
    case 'c': {
        digits[0] = (char)(value & 0xFF);
        dlen = 1;
        break;
    }
    default: /* 'd', 'n' */ {
        snprintf(digits, sizeof(digits), "%llu", (unsigned long long)abs_val);
        dlen = (int)strlen(digits);
        break;
    }
    }
    digits[dlen] = '\0';

    /* Apply grouping (comma or underscore) */
    char grouped[256];
    int glen = 0;
    if (grouping && type != 'c') {
        int grp_size = (type == 'b' || type == 'o' || type == 'x' || type == 'X') ? 4 : 3;
        int groups = (dlen > 0) ? (dlen - 1) / grp_size : 0;
        int first = dlen - groups * grp_size;
        memcpy(grouped, digits, first);
        glen = first;
        for (int g = 0; g < groups; g++) {
            grouped[glen++] = grouping;
            memcpy(grouped + glen, digits + first + g * grp_size, grp_size);
            glen += grp_size;
        }
    } else {
        memcpy(grouped, digits, dlen);
        glen = dlen;
    }
    grouped[glen] = '\0';

    /* Total content length: sign + prefix + grouped digits */
    int sign_len = sign_char ? 1 : 0;
    int tlen = sign_len + plen + glen;

    int outsize = (width > tlen ? width : tlen) + 1;
    char *buf = fpy_str_buf(outsize);

    /* No padding needed */
    if (tlen >= width) {
        int out = 0;
        if (sign_char) buf[out++] = sign_char;
        memcpy(buf + out, prefix, plen); out += plen;
        memcpy(buf + out, grouped, glen); out += glen;
        buf[out] = '\0';
        return buf;
    }

    /* Pad to width according to alignment */
    int pad = width - tlen;
    int out = 0;

    if (align == '<') {
        if (sign_char) buf[out++] = sign_char;
        memcpy(buf + out, prefix, plen); out += plen;
        memcpy(buf + out, grouped, glen); out += glen;
        for (int k = 0; k < pad; k++) buf[out++] = fill == '0' ? ' ' : fill;
    } else if (align == '^') {
        int left = pad / 2, right = pad - left;
        for (int k = 0; k < left; k++) buf[out++] = fill;
        if (sign_char) buf[out++] = sign_char;
        memcpy(buf + out, prefix, plen); out += plen;
        memcpy(buf + out, grouped, glen); out += glen;
        for (int k = 0; k < right; k++) buf[out++] = fill;
    } else if (align == '=') {
        /* Pad between sign/prefix and digits */
        if (sign_char) buf[out++] = sign_char;
        memcpy(buf + out, prefix, plen); out += plen;
        for (int k = 0; k < pad; k++) buf[out++] = fill;
        memcpy(buf + out, grouped, glen); out += glen;
    } else {
        /* '>' right-align (default) */
        for (int k = 0; k < pad; k++) buf[out++] = fill;
        if (sign_char) buf[out++] = sign_char;
        memcpy(buf + out, prefix, plen); out += plen;
        memcpy(buf + out, grouped, glen); out += glen;
    }
    buf[out] = '\0';
    return buf;
}

const char* fastpy_format_spec_str(const char *value, const char *spec) {
    /* Parse Python format spec: [[fill]align][width][.precision][type]
     * Strings default to left-align (<). */
    int i = 0;
    char fill = ' ';
    char align = '<';  /* default left-align for strings */

    /* [fill]align */
    if (spec[i] != '\0' && (spec[i+1] == '<' || spec[i+1] == '>'
                             || spec[i+1] == '^')) {
        fill = spec[i];
        align = spec[i+1];
        i += 2;
    } else if (spec[i] == '<' || spec[i] == '>' || spec[i] == '^') {
        align = spec[i];
        i++;
    }

    /* width */
    int width = 0;
    while (spec[i] >= '0' && spec[i] <= '9') {
        width = width * 10 + (spec[i] - '0');
        i++;
    }

    /* .precision (truncate string) */
    int precision = -1;
    if (spec[i] == '.') {
        i++;
        precision = 0;
        while (spec[i] >= '0' && spec[i] <= '9') {
            precision = precision * 10 + (spec[i] - '0');
            i++;
        }
    }

    int len = (int)strlen(value);
    if (precision >= 0 && precision < len) len = precision;

    int outsize = (width > len ? width : len) + 1;
    char *buf = fpy_str_buf(outsize);

    if (width <= len) {
        memcpy(buf, value, len);
        buf[len] = '\0';
        return buf;
    }

    int pad = width - len;
    int out = 0;

    if (align == '<') {
        memcpy(buf + out, value, len); out += len;
        for (int k = 0; k < pad; k++) buf[out++] = fill;
    } else if (align == '^') {
        int left = pad / 2, right = pad - left;
        for (int k = 0; k < left; k++) buf[out++] = fill;
        memcpy(buf + out, value, len); out += len;
        for (int k = 0; k < right; k++) buf[out++] = fill;
    } else {
        /* '>' right-align */
        for (int k = 0; k < pad; k++) buf[out++] = fill;
        memcpy(buf + out, value, len); out += len;
    }
    buf[out] = '\0';
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

/* In-place sort by key function: key_fn is int64_t(int64_t).
   reverse=0 for ascending, reverse=1 for descending (stable). */
void fastpy_list_sort_by_key_int(FpyList *lst, void *key_fn, int reverse) {
    typedef int64_t (*keyfn_t)(int64_t);
    keyfn_t fn = (keyfn_t)key_fn;
    int64_t n = lst->length;
    if (n <= 1) return;
    FPY_LOCK(lst);
    int64_t *keys = (int64_t*)malloc(sizeof(int64_t) * n);
    int64_t *order = (int64_t*)malloc(sizeof(int64_t) * n);
    for (int64_t i = 0; i < n; i++) {
        order[i] = i;
        keys[i] = fn(lst->items[i].data.i);
    }
    /* Stable insertion sort on order by keys */
    for (int64_t i = 1; i < n; i++) {
        int64_t cur = order[i];
        int64_t cur_key = keys[cur];
        int64_t j = i - 1;
        if (reverse) {
            while (j >= 0 && keys[order[j]] < cur_key) {
                order[j + 1] = order[j];
                j--;
            }
        } else {
            while (j >= 0 && keys[order[j]] > cur_key) {
                order[j + 1] = order[j];
                j--;
            }
        }
        order[j + 1] = cur;
    }
    /* Rearrange items in-place using temporary copy */
    FpyValue *tmp = (FpyValue*)malloc(sizeof(FpyValue) * n);
    for (int64_t i = 0; i < n; i++) {
        tmp[i] = lst->items[order[i]];
    }
    memcpy(lst->items, tmp, sizeof(FpyValue) * n);
    free(tmp);
    free(keys);
    free(order);
    FPY_UNLOCK(lst);
}

/* In-place sort by key function returning string: key values compared
   with strcmp. The key_fn returns a char* (as int64_t). */
void fastpy_list_sort_by_key_str(FpyList *lst, void *key_fn, int reverse) {
    typedef int64_t (*keyfn_t)(int64_t);
    keyfn_t fn = (keyfn_t)key_fn;
    int64_t n = lst->length;
    if (n <= 1) return;
    FPY_LOCK(lst);
    const char **keys = (const char**)malloc(sizeof(const char*) * n);
    int64_t *order = (int64_t*)malloc(sizeof(int64_t) * n);
    for (int64_t i = 0; i < n; i++) {
        order[i] = i;
        keys[i] = (const char*)(intptr_t)fn(lst->items[i].data.i);
    }
    /* Stable insertion sort on order by strcmp */
    for (int64_t i = 1; i < n; i++) {
        int64_t cur = order[i];
        const char *cur_key = keys[cur];
        int64_t j = i - 1;
        if (reverse) {
            while (j >= 0 && strcmp(keys[order[j]], cur_key) < 0) {
                order[j + 1] = order[j];
                j--;
            }
        } else {
            while (j >= 0 && strcmp(keys[order[j]], cur_key) > 0) {
                order[j + 1] = order[j];
                j--;
            }
        }
        order[j + 1] = cur;
    }
    /* Rearrange items in-place using temporary copy */
    FpyValue *tmp = (FpyValue*)malloc(sizeof(FpyValue) * n);
    for (int64_t i = 0; i < n; i++) {
        tmp[i] = lst->items[order[i]];
    }
    memcpy(lst->items, tmp, sizeof(FpyValue) * n);
    free(tmp);
    free(keys);
    free(order);
    FPY_UNLOCK(lst);
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
    extern void fastpy_set_arg_tag(int32_t, int32_t);
    for (int64_t i = 0; i < n; i++) {
        order[i] = i;
        /* Set the arg tag side-channel so FV-ABI shims can reconstruct
         * the correct FpyValue type (e.g., LIST tag for tuple elements). */
        fastpy_set_arg_tag(0, lst->items[i].tag);
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
    extern void fastpy_set_arg_tag(int32_t, int32_t);
    for (int64_t i = 0; i < n; i++) {
        order[i] = i;
        fastpy_set_arg_tag(0, lst->items[i].tag);
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

/* List sorted by key function returning tuple/list: key values are
   compared lexicographically via fastpy_list_compare. The key_fn
   returns a FpyList* (as int64_t). */
FpyList* fastpy_list_sorted_by_key_tuple(FpyList *lst, void *key_fn) {
    typedef int64_t (*keyfn_t)(int64_t);
    keyfn_t fn = (keyfn_t)key_fn;
    int64_t n = lst->length;
    FpyList *result = fpy_list_new(n);
    FpyList **keys = (FpyList**)malloc(sizeof(FpyList*) * n);
    int64_t *order = (int64_t*)malloc(sizeof(int64_t) * n);
    extern void fastpy_set_arg_tag(int32_t, int32_t);
    for (int64_t i = 0; i < n; i++) {
        order[i] = i;
        fastpy_set_arg_tag(0, lst->items[i].tag);
        keys[i] = (FpyList*)(intptr_t)fn(lst->items[i].data.i);
    }
    /* Stable insertion sort by lexicographic comparison */
    extern int64_t fastpy_list_compare(FpyList*, FpyList*);
    for (int64_t i = 1; i < n; i++) {
        int64_t cur = order[i];
        FpyList *cur_key = keys[cur];
        int64_t j = i - 1;
        while (j >= 0 && fastpy_list_compare(keys[order[j]], cur_key) > 0) {
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

/* List repetition: [1, 2] * 3 = [1, 2, 1, 2, 1, 2].
   Preserves tuple flag from the source list. */
FpyList* fastpy_list_repeat(FpyList *lst, int64_t n) {
    if (n <= 0) {
        FpyList *empty = fpy_list_new(0);
        empty->is_tuple = lst->is_tuple;
        return empty;
    }
    FpyList *result = fpy_list_new(lst->length * n);
    for (int64_t r = 0; r < n; r++) {
        for (int64_t i = 0; i < lst->length; i++) {
            fpy_list_append(result, lst->items[i]);
        }
    }
    result->is_tuple = lst->is_tuple;
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
    char *buf = fpy_str_buf(4096);
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
    fpy_classes[id].n_native_slots = 0;
    fpy_classes[id].slot_names = NULL;
    fpy_classes[id].destructor = NULL;
    fpy_classes[id].vtable = NULL;
    fpy_classes[id].vtable_size = 0;
    fpy_classes[id].acyclic = 0;
    fpy_classes[id].mro = NULL;
    fpy_classes[id].mro_len = 0;
    fpy_classes[id].class_var_names = NULL;
    fpy_classes[id].class_var_values = NULL;
    fpy_classes[id].class_var_count = 0;
    return id;
}

/* Mark a class as acyclic — its slots can only hold scalar values
 * (INT, FLOAT, BOOL, NONE), so instances can never participate in
 * reference cycles.  Instances skip GC tracking entirely. */
void fastpy_set_class_acyclic(int class_id) {
    fpy_classes[class_id].acyclic = 1;
}

/* Store a class-level variable (e.g. `kind = "parent"` from the class body).
 * Called during class registration. obj_get_fv falls back to these when
 * the instance has no matching attribute. */
void fastpy_set_class_var(int class_id, const char *name,
                          int32_t tag, int64_t data) {
    FpyClassDef *cls = &fpy_classes[class_id];
    int n = cls->class_var_count;
    cls->class_var_names = realloc(cls->class_var_names,
                                    (n + 1) * sizeof(const char *));
    cls->class_var_values = realloc(cls->class_var_values,
                                     (n + 1) * sizeof(FpyValue));
    cls->class_var_names[n] = name;
    cls->class_var_values[n].tag = tag;
    cls->class_var_values[n].data.i = data;
    cls->class_var_count = n + 1;
}

/* Set the MRO (Method Resolution Order) for a class.
 * mro_ids is a heap-allocated array of class IDs in C3-linearized order:
 *   mro[0] = self, mro[1..n-1] = ancestors in MRO order.
 * The class takes ownership of the array (no copy). */
void fastpy_set_class_mro(int class_id, int *mro_ids, int mro_len) {
    fpy_classes[class_id].mro = mro_ids;
    fpy_classes[class_id].mro_len = mro_len;
}

/* Resolve a super() method call using MRO.
 * Finds the next class in self's MRO after calling_class_id that
 * implements method_name, and returns its function pointer.
 * Returns NULL if no such method exists. */
void* fastpy_super_resolve(FpyObj *self, int calling_class_id,
                            const char *method_name) {
    int actual_class = self->class_id;
    int *mro = fpy_classes[actual_class].mro;
    int mro_len = fpy_classes[actual_class].mro_len;

    /* If no MRO registered, fall back to single-parent lookup */
    if (!mro || mro_len == 0) {
        int pid = fpy_classes[calling_class_id].parent_id;
        if (pid < 0) return NULL;
        FpyClassDef *pcls = &fpy_classes[pid];
        for (int i = 0; i < pcls->method_count; i++) {
            if (strcmp(pcls->methods[i].name, method_name) == 0)
                return pcls->methods[i].func;
        }
        return NULL;
    }

    /* Find calling_class_id in the MRO, then search subsequent entries */
    int found = 0;
    for (int i = 0; i < mro_len; i++) {
        if (!found) {
            if (mro[i] == calling_class_id) found = 1;
            continue;
        }
        /* Search this class's methods */
        FpyClassDef *cls = &fpy_classes[mro[i]];
        for (int j = 0; j < cls->method_count; j++) {
            if (strcmp(cls->methods[j].name, method_name) == 0)
                return cls->methods[j].func;
        }
    }
    return NULL;
}

/* Set the number of pre-declared attribute slots for a class.
 * Called after register_class with the slot count determined at compile time. */
void fastpy_set_class_slot_count(int class_id, int slot_count) {
    fpy_classes[class_id].slot_count = slot_count;
    fpy_classes[class_id].slot_names = (const char**)calloc(
        slot_count, sizeof(const char*));
}

/* Set the number of native (untagged, 8-byte) slots for a class.
 * Must be called AFTER set_class_slot_count.  The first n_native slots
 * are stored as raw i64 (8 bytes each) — no tag field.  Remaining slots
 * are boxed FpyValue (16 bytes each).  This saves 8 bytes per native slot.
 * Slots 0..n_native-1 must be statically-typed scalars (int/float/bool). */
void fastpy_set_class_native_slot_count(int class_id, int n_native) {
    fpy_classes[class_id].n_native_slots = n_native;
}

void fastpy_set_class_native_slot_tag(int class_id, int slot_idx, int tag) {
    if (slot_idx >= 0 && slot_idx < 16)
        fpy_classes[class_id].native_slot_tags[slot_idx] = (int8_t)tag;
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
    m->return_tag = -1;  /* unknown until set */
    m->is_vararg = 0;
    m->n_positional = arg_count;
}

/* Mark a method as accepting *args.  n_positional is the number of regular
 * positional parameters (excluding self) before the *args parameter.
 * The method's LLVM function receives those positionals as i64, followed
 * by a single i8* (FpyList*) containing the collected *args. */
void fastpy_set_method_vararg(int class_id, const char *name,
                              int n_positional) {
    FpyClassDef *cls = &fpy_classes[class_id];
    for (int i = 0; i < cls->method_count; i++) {
        if (cls->methods[i].name == name
                || strcmp(cls->methods[i].name, name) == 0) {
            cls->methods[i].is_vararg = 1;
            cls->methods[i].n_positional = n_positional;
            return;
        }
    }
}

/* Set the return type tag for a method (called after register_method) */
void fastpy_set_method_ret_tag(int class_id, const char *name, int return_tag) {
    FpyClassDef *cls = &fpy_classes[class_id];
    for (int i = 0; i < cls->method_count; i++) {
        if (cls->methods[i].name == name
                || strcmp(cls->methods[i].name, name) == 0) {
            cls->methods[i].return_tag = return_tag;
            return;
        }
    }
}

/* Call a method on an object, returning FpyValue (tag + data).
 * Uses the method's registered return_tag to produce the correct tag.
 * Falls back to INT if return_tag is unknown. */
void fastpy_obj_call_method1_fv(FpyObj *obj, const char *name, int64_t a,
                                 int32_t *out_tag, int64_t *out_data) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        /* __ne__ fallback */
        if (strcmp(name, "__ne__") == 0) {
            m = fastpy_find_method(obj->class_id, "__eq__");
            if (m) {
                int64_t eq_result = ((FpyMethod1Func)m->func)(obj, a);
                *out_tag = FPY_TAG_INT;
                *out_data = !eq_result;
                return;
            }
        }
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    if (m->return_tag == FPY_TAG_FLOAT) {
        typedef double (*FpyM1DoubleFunc)(FpyObj*, int64_t);
        double d = ((FpyM1DoubleFunc)m->func)(obj, a);
        *out_tag = FPY_TAG_FLOAT;
        memcpy(out_data, &d, sizeof(double));
    } else if (!m->returns_value) {
        /* No `return <expr>` anywhere in the method: it is a void function and
         * its Python value is None.  Reading the return register would produce
         * a garbage INT.  See FpyMethod1VoidFunc in objects.h. */
        ((FpyMethod1VoidFunc)m->func)(obj, a);
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
    } else {
        int64_t result = ((FpyMethod1Func)m->func)(obj, a);
        if (m->return_tag >= 0) {
            *out_tag = m->return_tag;
        } else {
            *out_tag = FPY_TAG_INT;  /* fallback: raw i64 as int */
        }
        *out_data = result;
    }
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

/* Copy parent's vtable entries into child class.  Must be called AFTER
 * all of the child's own methods have been registered via set_vtable_entry
 * so that overrides are already in place.  Parent entries fill only NULL
 * slots, so child overrides are preserved.
 *
 * Requires classes to be registered in dependency order (parent before
 * child).  Multi-level inheritance works because the parent's vtable
 * already contains its ancestors' entries by the time we copy. */
void fastpy_inherit_parent_vtable(int class_id) {
    FpyClassDef *cls = &fpy_classes[class_id];
    int pid = cls->parent_id;
    if (pid < 0) return;
    FpyClassDef *parent = &fpy_classes[pid];
    if (!parent->vtable || parent->vtable_size == 0) return;

    /* Ensure child vtable is at least as large as parent's. */
    if (!cls->vtable) {
        cls->vtable_size = parent->vtable_size;
        cls->vtable = (void**)calloc(cls->vtable_size, sizeof(void*));
    } else if (cls->vtable_size < parent->vtable_size) {
        int old_size = cls->vtable_size;
        cls->vtable_size = parent->vtable_size;
        cls->vtable = (void**)realloc(cls->vtable,
                                       cls->vtable_size * sizeof(void*));
        for (int i = old_size; i < cls->vtable_size; i++)
            cls->vtable[i] = NULL;
    }

    /* Fill NULL slots with parent's entries (child overrides stay). */
    for (int i = 0; i < parent->vtable_size; i++) {
        if (!cls->vtable[i] && parent->vtable[i])
            cls->vtable[i] = parent->vtable[i];
    }
}

/* O(1) vtable dispatch — returns the function pointer for the given slot
 * on the object's class.  After fastpy_inherit_parent_vtable() has been
 * called for every class, all inherited methods are already in the child's
 * vtable, so no parent-chain walk is needed. */
void* fastpy_vtable_lookup(FpyObj *obj, int slot) {
    FpyClassDef *cls = &fpy_classes[obj->class_id];
    if (cls->vtable && slot < cls->vtable_size)
        return cls->vtable[slot];
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
 * Uses a per-class free-list: if a previously freed object of the same
 * class is available, reuse it (pointer pop — no malloc).
 * Otherwise falls back to malloc with contiguous header+slots layout.
 *
 * Two-region layout: native slots (i64, 8 bytes each) come first,
 * then boxed slots (FpyValue, 16 bytes each). */
FpyObj* fastpy_obj_new(int class_id) {
    int sc = fpy_classes[class_id].slot_count;
    int nn = fpy_classes[class_id].n_native_slots;
    int nb = sc - nn;  /* number of boxed slots */
    size_t total = sizeof(FpyObj) + (size_t)nn * sizeof(int64_t)
                   + (size_t)nb * sizeof(FpyValue);
    FpyObj *obj;
    int from_freelist = 0;

    /* Try per-class free-list first */
    if (class_id < FPY_MAX_CLASSES && fpy_obj_freelist[class_id]) {
        obj = fpy_obj_freelist[class_id];
        fpy_obj_freelist[class_id] = (FpyObj*)obj->dynamic_attrs;
        fpy_obj_freelist_count[class_id]--;
        from_freelist = 1;
    } else {
        obj = (FpyObj*)malloc(total);
    }
    obj->refcount = 1;
    obj->magic = FPY_OBJ_MAGIC;
    obj->class_id = class_id;
    obj->dynamic_attrs = NULL;
    obj->weakref_list = NULL;
    /* Initialize native slots to 0 (raw i64) */
    if (nn > 0) {
        int64_t *native = FPY_OBJ_NATIVE_SLOTS(obj);
        for (int i = 0; i < nn; i++)
            native[i] = 0;
    }
    /* Initialize boxed slots to {NONE, 0} */
    if (nb > 0) {
        FpyValue *boxed = FPY_OBJ_BOXED_SLOTS(obj, nn);
        for (int i = 0; i < nb; i++) {
            boxed[i].tag = FPY_TAG_NONE;
            boxed[i].data.i = 0;
        }
    }
    /* Acyclic classes (scalar-only slots) skip GC tracking entirely —
     * they can never form reference cycles, so the cycle collector
     * never needs to see them.  This eliminates the GC doubly-linked
     * list insert/remove and all GC scan overhead for these objects. */
    memset(&obj->gc_node, 0, sizeof(FpyGCNode));
    obj->gc_node.gc_type = FPY_GC_TYPE_OBJ;
    if (!fpy_classes[class_id].acyclic) {
        fpy_gc_track(&obj->gc_node);
        /* Skip gc_maybe_collect for free-list reuse — no new memory was
         * allocated, so there's nothing for the GC to reclaim. */
        if (!from_freelist)
            fpy_gc_maybe_collect();
    }
    return obj;
}

/* Fast-path static slot access. Slot index is known at compile time.
 * Manages refcounts: increfs the new value, decrefs the old.
 * Handles two-region layout: native slots (< n_native) are raw i64,
 * boxed slots (>= n_native) are FpyValue. */
void fastpy_obj_set_slot(FpyObj *obj, int slot, int32_t tag, int64_t data) {
    int nn = fpy_classes[obj->class_id].n_native_slots;
    if (slot < nn) {
        /* Native slot: raw i64, no tag, no refcounting */
        FPY_OBJ_NATIVE_SLOTS(obj)[slot] = data;
    } else {
        /* Boxed slot: full FpyValue with refcounting */
        FpyValue *boxed = FPY_OBJ_BOXED_SLOTS(obj, nn);
        int bi = slot - nn;
        FpyValue old = boxed[bi];
        fpy_rc_incref(tag, data);
        boxed[bi].tag = tag;
        boxed[bi].data.i = data;
        fpy_rc_decref(old.tag, old.data.i);
    }
}

void fastpy_obj_get_slot(FpyObj *obj, int slot,
                          int32_t *out_tag, int64_t *out_data) {
    int nn = fpy_classes[obj->class_id].n_native_slots;
    if (slot < nn) {
        /* Native slot: look up the compile-time tag from the class def */
        *out_tag = (int32_t)fpy_classes[obj->class_id].native_slot_tags[slot];
        *out_data = FPY_OBJ_NATIVE_SLOTS(obj)[slot];
    } else {
        FpyValue *boxed = FPY_OBJ_BOXED_SLOTS(obj, nn);
        int bi = slot - nn;
        *out_tag = boxed[bi].tag;
        *out_data = boxed[bi].data.i;
    }
}

/* Set an attribute on an object */
/* Tagged-value attribute access (post-refactor) — stores with the exact tag
 * provided. Replaced the old typed variants (obj_set_int with its pointer
 * heuristic, obj_set_float, obj_set_str) and their obj_get_* counterparts. */
void fastpy_obj_set_fv(FpyObj *obj, const char *name, int32_t tag, int64_t data) {
    /* Incref the new value up-front (before any slot/dyn store). */
    fpy_rc_incref(tag, data);
    /* Check static slots first (covers all compiler-known attrs) */
    int slot = fpy_find_slot(obj->class_id, name);
    if (slot >= 0) {
        int nn = fpy_classes[obj->class_id].n_native_slots;
        if (slot < nn) {
            /* Native slot: raw i64, no tag, no old-value decref */
            FPY_OBJ_NATIVE_SLOTS(obj)[slot] = data;
            /* Undo the incref — native slots don't hold references */
            fpy_rc_decref(tag, data);
        } else {
            FpyValue *boxed = FPY_OBJ_BOXED_SLOTS(obj, nn);
            int bi = slot - nn;
            FpyValue old = boxed[bi];
            FpyValue v;
            v.tag = tag;
            v.data.i = data;
            boxed[bi] = v;
            fpy_rc_decref(old.tag, old.data.i);
        }
        return;
    }
    /* Dynamic attr fallback — lazily allocate the side table on first use. */
    FpyValue v;
    v.tag = tag;
    v.data.i = data;
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
        int nn = fpy_classes[obj->class_id].n_native_slots;
        if (slot < nn) {
            *out_tag = (int32_t)fpy_classes[obj->class_id].native_slot_tags[slot];
            *out_data = FPY_OBJ_NATIVE_SLOTS(obj)[slot];
        } else {
            FpyValue *boxed = FPY_OBJ_BOXED_SLOTS(obj, nn);
            int bi = slot - nn;
            *out_tag = boxed[bi].tag;
            *out_data = boxed[bi].data.i;
        }
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
    /* Fall back to class-level variables (walk MRO / parent chain).
     * This handles `self.kind` where `kind = "parent"` is defined on
     * the class body, and also inherits class vars from parent classes. */
    {
        int cid = obj->class_id;
        while (cid >= 0) {
            FpyClassDef *cls = &fpy_classes[cid];
            for (int i = 0; i < cls->class_var_count; i++) {
                if (cls->class_var_names[i] == name
                        || strcmp(cls->class_var_names[i], name) == 0) {
                    *out_tag = cls->class_var_values[i].tag;
                    *out_data = cls->class_var_values[i].data.i;
                    return;
                }
            }
            cid = cls->parent_id;
        }
    }
    snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no attribute '%s'",
             fpy_classes[obj->class_id].name, name);
    fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
    *out_tag = FPY_TAG_NONE; *out_data = 0; return;
}

/* hasattr(obj, name) — returns 1 if the attribute exists, 0 otherwise.
 * Does NOT raise; simply checks slot table and dynamic attrs. */
int32_t fastpy_obj_has_attr(FpyObj *obj, const char *name) {
    int slot = fpy_find_slot(obj->class_id, name);
    if (slot >= 0) {
        return 1;
    }
    FpyObjAttrs *a = obj->dynamic_attrs;
    if (a != NULL) {
        for (int i = 0; i < a->count; i++) {
            if (a->names[i] == name
                    || strcmp(a->names[i], name) == 0) {
                return 1;
            }
        }
    }
    /* Check class-level variables (walk parent chain) */
    {
        int cid = obj->class_id;
        while (cid >= 0) {
            FpyClassDef *cls = &fpy_classes[cid];
            for (int i = 0; i < cls->class_var_count; i++) {
                if (cls->class_var_names[i] == name
                        || strcmp(cls->class_var_names[i], name) == 0) {
                    return 1;
                }
            }
            cid = cls->parent_id;
        }
    }
    return 0;
}

/* getattr(obj, name, default) — returns attribute value, or default if
 * the attribute doesn't exist. Sets out_tag/out_data. Returns 1 if found,
 * 0 if default was used. */
int32_t fastpy_obj_getattr_default(FpyObj *obj, const char *name,
                                    int32_t def_tag, int64_t def_data,
                                    int32_t *out_tag, int64_t *out_data) {
    int slot = fpy_find_slot(obj->class_id, name);
    if (slot >= 0) {
        int nn = fpy_classes[obj->class_id].n_native_slots;
        if (slot < nn) {
            *out_tag = (int32_t)fpy_classes[obj->class_id].native_slot_tags[slot];
            *out_data = FPY_OBJ_NATIVE_SLOTS(obj)[slot];
        } else {
            FpyValue *boxed = FPY_OBJ_BOXED_SLOTS(obj, nn);
            int bi = slot - nn;
            *out_tag = boxed[bi].tag;
            *out_data = boxed[bi].data.i;
        }
        return 1;
    }
    FpyObjAttrs *a = obj->dynamic_attrs;
    if (a != NULL) {
        for (int i = 0; i < a->count; i++) {
            if (a->names[i] == name
                    || strcmp(a->names[i], name) == 0) {
                *out_tag = a->values[i].tag;
                *out_data = a->values[i].data.i;
                return 1;
            }
        }
    }
    /* Check class-level variables (walk parent chain) */
    {
        int cid = obj->class_id;
        while (cid >= 0) {
            FpyClassDef *cls = &fpy_classes[cid];
            for (int i = 0; i < cls->class_var_count; i++) {
                if (cls->class_var_names[i] == name
                        || strcmp(cls->class_var_names[i], name) == 0) {
                    *out_tag = cls->class_var_values[i].tag;
                    *out_data = cls->class_var_values[i].data.i;
                    return 1;
                }
            }
            cid = cls->parent_id;
        }
    }
    /* Not found — use default */
    *out_tag = def_tag;
    *out_data = def_data;
    return 0;
}

/* Get attribute as string representation (works for any type).
 * Still used by the f-string path for `{self.attr}` expansion. */
/* ---- Vararg method helpers ----
 * When a method is registered as vararg, obj_call_methodN packs the
 * extra arguments (those beyond the positional count) into a FpyList
 * and passes the list pointer as the final parameter.
 *
 * Signature of a vararg method with P positional params:
 *   int64_t method(FpyObj *self, i64 p0, ..., i64 p_{P-1}, FpyList *args)
 *
 * When P == 0:  int64_t method(FpyObj *self, FpyList *args)
 */
extern int32_t fastpy_get_arg_tag(int32_t index);

static int64_t _call_vararg_method(FpyMethodDef *m, FpyObj *obj,
                                   int n_call_args, int64_t *args) {
    int n_pos = m->n_positional;  /* positional params before *args */
    /* Build the *args list from extra arguments */
    FpyList *varlist = fastpy_list_new();
    for (int i = n_pos; i < n_call_args; i++) {
        int32_t tag = fastpy_get_arg_tag(i);
        fastpy_list_append_fv(varlist, tag, args[i]);
    }
    int64_t list_as_i64 = (int64_t)(intptr_t)varlist;
    /* A method with no `return <expr>` is compiled to a void function; calling
     * it through an int64_t-returning pointer type yields whatever is left in
     * the return register.  See the FpyMethod*VoidFunc typedefs in objects.h. */
    if (!m->returns_value) {
        switch (n_pos) {
        case 0: {
            typedef void (*VA0V)(FpyObj*, int64_t);
            ((VA0V)m->func)(obj, list_as_i64);
            break;
        }
        case 1: {
            typedef void (*VA1V)(FpyObj*, int64_t, int64_t);
            ((VA1V)m->func)(obj, args[0], list_as_i64);
            break;
        }
        case 2: {
            typedef void (*VA2V)(FpyObj*, int64_t, int64_t, int64_t);
            ((VA2V)m->func)(obj, args[0], args[1], list_as_i64);
            break;
        }
        case 3: {
            typedef void (*VA3V)(FpyObj*, int64_t, int64_t, int64_t, int64_t);
            ((VA3V)m->func)(obj, args[0], args[1], args[2], list_as_i64);
            break;
        }
        default: {
            typedef void (*VA4V)(FpyObj*, int64_t, int64_t, int64_t, int64_t,
                                 int64_t);
            ((VA4V)m->func)(obj, args[0], args[1], args[2], args[3],
                            list_as_i64);
            break;
        }
        }
        return 0;
    }
    /* Dispatch based on positional count */
    switch (n_pos) {
    case 0: {
        typedef int64_t (*VA0)(FpyObj*, int64_t);
        return ((VA0)m->func)(obj, list_as_i64);
    }
    case 1: {
        typedef int64_t (*VA1)(FpyObj*, int64_t, int64_t);
        return ((VA1)m->func)(obj, args[0], list_as_i64);
    }
    case 2: {
        typedef int64_t (*VA2)(FpyObj*, int64_t, int64_t, int64_t);
        return ((VA2)m->func)(obj, args[0], args[1], list_as_i64);
    }
    case 3: {
        typedef int64_t (*VA3)(FpyObj*, int64_t, int64_t, int64_t, int64_t);
        return ((VA3)m->func)(obj, args[0], args[1], args[2], list_as_i64);
    }
    default: {
        /* Fallback: 4+ positional not expected but handle it */
        typedef int64_t (*VA4)(FpyObj*, int64_t, int64_t, int64_t, int64_t, int64_t);
        return ((VA4)m->func)(obj, args[0], args[1], args[2], args[3], list_as_i64);
    }
    }
}

/* Call a method on an object — returns i64.
 * If the method returns double (return_tag == FPY_TAG_FLOAT), uses the
 * correct calling convention (reads XMM0) and bitcasts to i64. */
int64_t fastpy_obj_call_method0(FpyObj *obj, const char *name) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0;
    }
    if (m->is_vararg) {
        return _call_vararg_method(m, obj, 0, NULL);
    }
    if (m->return_tag == FPY_TAG_FLOAT) {
        typedef double (*FpyM0DoubleFunc)(FpyObj*);
        double d = ((FpyM0DoubleFunc)m->func)(obj);
        int64_t r;
        memcpy(&r, &d, sizeof(double));
        return r;
    }
    /* void-returning method (no `return <expr>` in the Python source): call it
     * through a matching pointer type and report None-as-0 rather than reading
     * a stale return register.  See FpyMethodVoidFunc in objects.h. */
    if (!m->returns_value) {
        ((FpyMethodVoidFunc)m->func)(obj);
        return 0;
    }
    return ((FpyMethodFunc)m->func)(obj);
}

int64_t fastpy_obj_call_method1(FpyObj *obj, const char *name, int64_t a) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, name);
    if (!m) {
        /* Python auto-derives __ne__ from __eq__: return not self.__eq__(other) */
        if (strcmp(name, "__ne__") == 0) {
            m = fastpy_find_method(obj->class_id, "__eq__");
            if (m) {
                int64_t eq_result = ((FpyMethod1Func)m->func)(obj, a);
                return !eq_result;
            }
        }
        snprintf(_err_buf, sizeof(_err_buf), "'%s' object has no method '%s'",
                 fpy_classes[obj->class_id].name, name);
        fastpy_raise(FPY_EXC_ATTRIBUTEERROR, _err_buf);
        return 0;
    }
    if (m->is_vararg) {
        int64_t args_arr[1] = {a};
        return _call_vararg_method(m, obj, 1, args_arr);
    }
    if (m->return_tag == FPY_TAG_FLOAT) {
        typedef double (*FpyM1DoubleFunc)(FpyObj*, int64_t);
        double d = ((FpyM1DoubleFunc)m->func)(obj, a);
        int64_t r;
        memcpy(&r, &d, sizeof(double));
        return r;
    }
    if (!m->returns_value) {
        ((FpyMethod1VoidFunc)m->func)(obj, a);
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
    if (m->is_vararg) {
        int64_t args_arr[2] = {a, b};
        return _call_vararg_method(m, obj, 2, args_arr);
    }
    if (!m->returns_value) {
        ((FpyMethod2VoidFunc)m->func)(obj, a, b);
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
    if (m->is_vararg) {
        int64_t args_arr[3] = {a, b, c};
        return _call_vararg_method(m, obj, 3, args_arr);
    }
    /* This is the `with` statement's __exit__ call.  A None-returning __exit__
     * must read as falsy: a truthy answer means "suppress the exception". */
    if (!m->returns_value) {
        ((FpyMethod3VoidFunc)m->func)(obj, a, b, c);
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
    if (m->is_vararg) {
        int64_t args_arr[4] = {a, b, c, d};
        return _call_vararg_method(m, obj, 4, args_arr);
    }
    if (!m->returns_value) {
        ((FpyMethod4VoidFunc)m->func)(obj, a, b, c, d);
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

/* ================================================================
 * Built-in list/tuple iterator
 *
 * iter() on a list or tuple creates a lightweight FpyObj wrapping the
 * list pointer and a current-index counter.  The __next__ method reads
 * list->items[idx], increments idx, and raises StopIteration when done.
 * The class is lazily registered on first use.
 *
 * Slot layout:
 *   slot 0 = list pointer (FPY_TAG_LIST)
 *   slot 1 = current index (FPY_TAG_INT)
 * ================================================================ */
static int fpy_listiter_class_id = -1;

/* Forward declare — full definition below. */
static int64_t fpy_listiter_next(FpyObj *self);
static int64_t fpy_listiter_iter(FpyObj *self);

static void fpy_listiter_ensure_class(void) {
    if (fpy_listiter_class_id >= 0) return;
    fpy_listiter_class_id = fastpy_register_class("list_iterator", -1);
    fastpy_set_class_slot_count(fpy_listiter_class_id, 2);
    fastpy_register_slot_name(fpy_listiter_class_id, 0, "_list");
    fastpy_register_slot_name(fpy_listiter_class_id, 1, "_index");
    /* __next__: 0 extra args (self only), returns value, dynamic tag */
    fastpy_register_method(fpy_listiter_class_id, "__next__",
                           (void*)fpy_listiter_next, 0, 1);
    fastpy_set_method_ret_tag(fpy_listiter_class_id, "__next__", -1);
    /* __iter__: returns self (OBJ tag) */
    fastpy_register_method(fpy_listiter_class_id, "__iter__",
                           (void*)fpy_listiter_iter, 0, 1);
    fastpy_set_method_ret_tag(fpy_listiter_class_id, "__iter__", FPY_TAG_OBJ);
}

static int64_t fpy_listiter_next(FpyObj *self) {
    FpyValue *slots = FPY_OBJ_SLOTS(self);
    FpyList *list = slots[0].data.list;
    int64_t idx = slots[1].data.i;
    if (!list || idx >= list->length) {
        fastpy_raise(FPY_EXC_STOPITERATION, "");
        fastpy_set_ret_tag(FPY_TAG_NONE);
        return 0;
    }
    FpyValue elem = list->items[idx];
    slots[1].data.i = idx + 1;
    fastpy_set_ret_tag(elem.tag);
    return elem.data.i;
}

static int64_t fpy_listiter_iter(FpyObj *self) {
    fpy_incref(&self->refcount);
    fastpy_set_ret_tag(FPY_TAG_OBJ);
    return (int64_t)(intptr_t)self;
}

/* Public: create a list iterator wrapping `list`.  Increfs the list. */
FpyObj* fastpy_list_iter_new(FpyList *list) {
    fpy_listiter_ensure_class();
    FpyObj *obj = fastpy_obj_new(fpy_listiter_class_id);
    FpyValue *slots = FPY_OBJ_SLOTS(obj);
    slots[0].tag = FPY_TAG_LIST;
    slots[0].data.list = list;
    fpy_rc_incref(FPY_TAG_LIST, (int64_t)(intptr_t)list);
    slots[1].tag = FPY_TAG_INT;
    slots[1].data.i = 0;
    return obj;
}

/* ================================================================
 * Built-in file object — open()/read/write/readline/readlines/close,
 * context-manager (__enter__/__exit__) and line iteration.
 *
 * Backed entirely by C stdio (fopen/fread/fwrite/fgetc/fclose), so it
 * works in *pure mode* with no CPython bridge: the SlateOS posix libc
 * implements the stdio surface over the SYS_FS_* VFS syscalls.  The
 * file object is a normal FpyObj of a lazily-registered built-in class,
 * so it plugs into the existing object refcounting/GC, dynamic method
 * dispatch (fastpy_obj_call_methodN), and `with` handling for free.
 *
 * Slot layout:
 *   slot 0 = FILE*  (stored raw in an FPY_TAG_INT slot — non-owning for GC)
 *   slot 1 = flags  (FPY_TAG_INT): bit0 = closed
 *
 * Slice-1 limitations (see design.md): text mode only (read() returns a
 * str; binary 'rb'/bytes not yet wired); read() reads the whole remaining
 * file (no size argument yet); FileNotFoundError is raised by name but is
 * not yet part of a registered OSError hierarchy.
 * ================================================================ */
#define FPY_EXC_GENERIC 99
extern void fastpy_exc_set_class_name(const char *name);

static int fpy_file_class_id = -1;

/* Return the FILE* for an open file, or NULL (raising ValueError) if closed. */
static FILE *fpy_file_fp(FpyObj *self) {
    FpyValue *slots = FPY_OBJ_SLOTS(self);
    if (slots[1].data.i & 1) {
        fastpy_raise(FPY_EXC_VALUEERROR, "I/O operation on closed file");
        return NULL;
    }
    return (FILE*)(intptr_t)slots[0].data.i;
}

/* Read a single line (through and including '\n', or to EOF) into a fresh
 * FpyString.  A zero-length result means EOF (matches Python readline). */
static FpyString *fpy_file_readline_raw(FILE *fp) {
    size_t cap = 128, len = 0;
    char *buf = (char*)malloc(cap);
    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (len + 1 > cap) { cap *= 2; buf = (char*)realloc(buf, cap); }
        buf[len++] = (char)c;
        if (c == '\n') break;
    }
    FpyString *s = fpy_str_alloc((int64_t)len);
    if (len) memcpy(s->data, buf, len);
    free(buf);
    return s;
}

static int64_t fpy_file_read(FpyObj *self) {
    FILE *fp = fpy_file_fp(self);
    if (!fp) { fastpy_set_ret_tag(FPY_TAG_NONE); return 0; }
    size_t cap = 4096, len = 0;
    char *buf = (char*)malloc(cap);
    for (;;) {
        if (len + 4096 > cap) { cap *= 2; buf = (char*)realloc(buf, cap); }
        size_t n = fread(buf + len, 1, 4096, fp);
        len += n;
        if (n < 4096) break;  /* short read = EOF or error */
    }
    FpyString *s = fpy_str_alloc((int64_t)len);
    if (len) memcpy(s->data, buf, len);
    free(buf);
    fastpy_set_ret_tag(FPY_TAG_STR);
    return (int64_t)(intptr_t)s->data;
}

static int64_t fpy_file_readline(FpyObj *self) {
    FILE *fp = fpy_file_fp(self);
    if (!fp) { fastpy_set_ret_tag(FPY_TAG_NONE); return 0; }
    FpyString *s = fpy_file_readline_raw(fp);
    fastpy_set_ret_tag(FPY_TAG_STR);
    return (int64_t)(intptr_t)s->data;
}

static int64_t fpy_file_readlines(FpyObj *self) {
    FILE *fp = fpy_file_fp(self);
    if (!fp) { fastpy_set_ret_tag(FPY_TAG_NONE); return 0; }
    FpyList *lst = fpy_list_new(8);
    for (;;) {
        FpyString *s = fpy_file_readline_raw(fp);
        if (fastpy_str_len(s->data) == 0) { free(s); break; }  /* EOF */
        FpyValue v; v.tag = FPY_TAG_STR; v.data.s = s->data;
        fpy_list_append(lst, v);  /* increfs → drop our builder ref below */
        fpy_rc_decref(FPY_TAG_STR, (int64_t)(intptr_t)s->data);
    }
    fastpy_set_ret_tag(FPY_TAG_LIST);
    return (int64_t)(intptr_t)lst;
}

/* write(self, s) → number of characters written. `a` is the str data ptr. */
static int64_t fpy_file_write(FpyObj *self, int64_t a) {
    FILE *fp = fpy_file_fp(self);
    if (!fp) { fastpy_set_ret_tag(FPY_TAG_NONE); return 0; }
    const char *str = (const char*)(intptr_t)a;
    int64_t n = str ? fastpy_str_len(str) : 0;
    if (n > 0) fwrite(str, 1, (size_t)n, fp);
    fastpy_set_ret_tag(FPY_TAG_INT);
    return n;
}

static int64_t fpy_file_close(FpyObj *self) {
    FpyValue *slots = FPY_OBJ_SLOTS(self);
    if (!(slots[1].data.i & 1)) {
        FILE *fp = (FILE*)(intptr_t)slots[0].data.i;
        if (fp) fclose(fp);
        slots[1].data.i |= 1;
        slots[0].data.i = 0;
    }
    fastpy_set_ret_tag(FPY_TAG_NONE);
    return 0;
}

static int64_t fpy_file_enter(FpyObj *self) {
    fpy_incref(&self->refcount);
    fastpy_set_ret_tag(FPY_TAG_OBJ);
    return (int64_t)(intptr_t)self;
}

/* __exit__(self, exc_type, exc_val, tb) → None (closes the file). */
static int64_t fpy_file_exit(FpyObj *self, int64_t a, int64_t b, int64_t c) {
    (void)a; (void)b; (void)c;
    return fpy_file_close(self);
}

static int64_t fpy_file_iter(FpyObj *self) {
    fpy_incref(&self->refcount);
    fastpy_set_ret_tag(FPY_TAG_OBJ);
    return (int64_t)(intptr_t)self;
}

static int64_t fpy_file_next(FpyObj *self) {
    FILE *fp = fpy_file_fp(self);
    if (!fp) { fastpy_set_ret_tag(FPY_TAG_NONE); return 0; }
    FpyString *s = fpy_file_readline_raw(fp);
    if (fastpy_str_len(s->data) == 0) {
        free(s);
        fastpy_raise(FPY_EXC_STOPITERATION, "");
        fastpy_set_ret_tag(FPY_TAG_NONE);
        return 0;
    }
    fastpy_set_ret_tag(FPY_TAG_STR);
    return (int64_t)(intptr_t)s->data;
}

/* Destructor: close the underlying FILE* if the program dropped the file
 * object without calling close() (matches CPython's finalizer flush/close). */
static void fpy_file_dtor(FpyObj *self) {
    FpyValue *slots = FPY_OBJ_SLOTS(self);
    if (!(slots[1].data.i & 1)) {
        FILE *fp = (FILE*)(intptr_t)slots[0].data.i;
        if (fp) fclose(fp);
        slots[1].data.i |= 1;
    }
}

static void fpy_file_ensure_class(void) {
    if (fpy_file_class_id >= 0) return;
    fpy_file_class_id = fastpy_register_class("file", -1);
    fastpy_set_class_slot_count(fpy_file_class_id, 2);
    fastpy_register_slot_name(fpy_file_class_id, 0, "_fp");
    fastpy_register_slot_name(fpy_file_class_id, 1, "_flags");
    fastpy_set_class_destructor(fpy_file_class_id, fpy_file_dtor);
    fastpy_register_method(fpy_file_class_id, "read", (void*)fpy_file_read, 0, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "read", FPY_TAG_STR);
    fastpy_register_method(fpy_file_class_id, "readline", (void*)fpy_file_readline, 0, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "readline", FPY_TAG_STR);
    fastpy_register_method(fpy_file_class_id, "readlines", (void*)fpy_file_readlines, 0, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "readlines", FPY_TAG_LIST);
    fastpy_register_method(fpy_file_class_id, "write", (void*)fpy_file_write, 1, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "write", FPY_TAG_INT);
    fastpy_register_method(fpy_file_class_id, "close", (void*)fpy_file_close, 0, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "close", FPY_TAG_NONE);
    fastpy_register_method(fpy_file_class_id, "__enter__", (void*)fpy_file_enter, 0, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "__enter__", FPY_TAG_OBJ);
    fastpy_register_method(fpy_file_class_id, "__exit__", (void*)fpy_file_exit, 3, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "__exit__", FPY_TAG_NONE);
    fastpy_register_method(fpy_file_class_id, "__iter__", (void*)fpy_file_iter, 0, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "__iter__", FPY_TAG_OBJ);
    fastpy_register_method(fpy_file_class_id, "__next__", (void*)fpy_file_next, 0, 1);
    fastpy_set_method_ret_tag(fpy_file_class_id, "__next__", -1);
}

/* Public: open(path, mode) → file object.  `mode` may be NULL ("r" default). */
FpyObj* fastpy_io_open(const char *path, const char *mode) {
    fpy_file_ensure_class();
    if (!mode || !mode[0]) mode = "r";
    FILE *fp = fopen(path ? path : "", mode);
    if (!fp) {
        snprintf(_err_buf, sizeof(_err_buf),
                 "[Errno 2] No such file or directory: '%s'", path ? path : "");
        fastpy_exc_set_class_name("FileNotFoundError");
        fastpy_raise(FPY_EXC_GENERIC, _err_buf);
        return NULL;
    }
    FpyObj *obj = fastpy_obj_new(fpy_file_class_id);
    FpyValue *slots = FPY_OBJ_SLOTS(obj);
    slots[0].tag = FPY_TAG_INT; slots[0].data.i = (int64_t)(intptr_t)fp;
    slots[1].tag = FPY_TAG_INT; slots[1].data.i = 0;
    return obj;
}

/* Call __init__ (its Python return value, if any, is discarded).
 * __init__ is normally compiled to a void function, so dispatch on
 * returns_value: calling a void function through an int64_t-returning pointer
 * type is a signature mismatch even when the result is thrown away, and
 * -fsanitize=function flags it. */
void fastpy_obj_call_init0(FpyObj *obj) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (!m) return;
    if (!m->returns_value) ((FpyMethodVoidFunc)m->func)(obj);
    else ((FpyMethodFunc)m->func)(obj);
}

void fastpy_obj_call_init1(FpyObj *obj, int64_t a) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (!m) return;
    if (!m->returns_value) ((FpyMethod1VoidFunc)m->func)(obj, a);
    else ((FpyMethod1Func)m->func)(obj, a);
}

void fastpy_obj_call_init2(FpyObj *obj, int64_t a, int64_t b) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (!m) return;
    if (!m->returns_value) ((FpyMethod2VoidFunc)m->func)(obj, a, b);
    else ((FpyMethod2Func)m->func)(obj, a, b);
}

void fastpy_obj_call_init3(FpyObj *obj, int64_t a, int64_t b, int64_t c) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (!m) return;
    if (!m->returns_value) ((FpyMethod3VoidFunc)m->func)(obj, a, b, c);
    else ((FpyMethod3Func)m->func)(obj, a, b, c);
}

void fastpy_obj_call_init4(FpyObj *obj, int64_t a, int64_t b, int64_t c, int64_t d) {
    FpyMethodDef *m = fastpy_find_method(obj->class_id, "__init__");
    if (!m) return;
    if (!m->returns_value) ((FpyMethod4VoidFunc)m->func)(obj, a, b, c, d);
    else ((FpyMethod4Func)m->func)(obj, a, b, c, d);
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

/* Safe class name: works for both native FpyObj and opaque PyObject*.
 * OBJ-tagged FpyValues may hold either an FpyObj* (native user class)
 * or a raw PyObject* (opaque bridge value like uuid.UUID).  Check the
 * magic header to distinguish.  Falls back to cpython_typeof for
 * non-native pointers. */
extern const char* fpy_cpython_typeof(void *obj);
const char* fastpy_obj_classname_safe(void *ptr) {
    if (!ptr) return "NoneType";
    FpyObj *obj = (FpyObj*)ptr;
    if (obj->magic == FPY_OBJ_MAGIC &&
        obj->class_id >= 0 && obj->class_id < fpy_class_count) {
        return fpy_classes[obj->class_id].name;
    }
    /* Not a native FpyObj — treat as PyObject* */
    return fpy_cpython_typeof(ptr);
}

/* Get "<class '__main__.ClassName'>" for an object (type(obj) display) */
const char* fastpy_obj_type_repr(FpyObj *obj) {
    const char *name = fpy_classes[obj->class_id].name;
    size_t len = strlen(name);
    /* Match Python's output: "<class '__main__.ClassName'>" */
    size_t buflen = len + 22; /* "<class '__main__.'>" + name + NUL */
    char *buf = fpy_str_buf((int64_t)buflen);
    snprintf(buf, buflen, "<class '__main__.%s'>", name);
    return buf;
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
    /* Exception objects: check for __exc_msg__ stored by raise_with_obj.
     * This gives str(e) the same behavior as Python's Exception.__str__. */
    if (obj->dynamic_attrs) {
        FpyObjAttrs *a = obj->dynamic_attrs;
        for (int i = 0; i < a->count; i++) {
            if (strcmp(a->names[i], "__exc_msg__") == 0
                    && a->values[i].tag == FPY_TAG_STR
                    && a->values[i].data.i != 0) {
                return (const char*)a->values[i].data.i;
            }
        }
    }
    /* Default: <ClassName object> */
    char *buf = fpy_str_buf(256);
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
    char *buf = fpy_str_buf(256);
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
        const char *pt = _fpy_obj_as_path_text((void*)obj);
        if (pt) { printf("%s", pt); return; }
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
        /* CPython says plainly "division by zero" here too — the operand type
         * never appears in the message. */
        fastpy_raise(FPY_EXC_ZERODIVISION, "division by zero");
        return NULL;
    }
    return fpy_complex_new(
        (a->real * b->real + a->imag * b->imag) / denom,
        (a->imag * b->real - a->real * b->imag) / denom);
}

FpyComplex* fpy_complex_pow(FpyComplex *a, FpyComplex *b) {
    /* Handle 0^b */
    if (a->real == 0.0 && a->imag == 0.0) {
        if (b->real == 0.0 && b->imag == 0.0)
            return fpy_complex_new(1.0, 0.0);
        if (b->real > 0.0)
            return fpy_complex_new(0.0, 0.0);
        fastpy_raise(FPY_EXC_ZERODIVISION,
                     "zero to a negative or complex power");
        return NULL;
    }
    /* Integer real exponent with no imaginary part: use repeated
       multiplication for exact results (matches CPython). */
    if (b->imag == 0.0 && b->real == (double)(int64_t)b->real
            && b->real >= -100 && b->real <= 100) {
        int64_t n = (int64_t)b->real;
        FpyComplex base = *a;
        if (n < 0) {
            /* a^(-n) = 1 / a^n */
            double denom = a->real * a->real + a->imag * a->imag;
            base.real = a->real / denom;
            base.imag = -a->imag / denom;
            n = -n;
        }
        double rr = 1.0, ri = 0.0;
        while (n > 0) {
            if (n & 1) {
                double tmp = rr * base.real - ri * base.imag;
                ri = rr * base.imag + ri * base.real;
                rr = tmp;
            }
            double tmp = base.real * base.real - base.imag * base.imag;
            base.imag = 2.0 * base.real * base.imag;
            base.real = tmp;
            n >>= 1;
        }
        return fpy_complex_new(rr, ri);
    }
    /* General case: a^b = exp(b * ln(a)) using polar form. */
    double abs_a = sqrt(a->real * a->real + a->imag * a->imag);
    double arg_a = atan2(a->imag, a->real);
    double ln_abs = log(abs_a);
    double re = b->real * ln_abs - b->imag * arg_a;
    double im = b->imag * ln_abs + b->real * arg_a;
    double r = exp(re);
    return fpy_complex_new(r * cos(im), r * sin(im));
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
    char *buf = fpy_str_buf(128);
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

/* abs() of a runtime-tagged value.
 *
 * `_emit_builtin_abs` in codegen only ever knew two LLVM types, i64 and
 * double.  An argument that arrives as a tagged FpyValue — a heterogeneous
 * list element, a "mixed"-returning call — matched neither and fell through
 * to the silent bridge fallback, which yields 0 in native mode, so
 * `abs(v[0])` on `[1, -2.5]` printed `0 0`.  BUG-ABS-OF-TAGGED-VALUE.
 *
 * This lives in the runtime rather than being open-coded in codegen because
 * six tags are numeric, not two: inlining an i64/double select would have
 * left bigint, Decimal and complex silently wrong instead of visibly wrong. */
void fastpy_abs_fv(int32_t tag, int64_t data,
                   int32_t *out_tag, int64_t *out_data) {
    switch (tag) {
    case FPY_TAG_BOOL:
        *out_tag = FPY_TAG_INT;
        *out_data = (data != 0) ? 1 : 0;
        return;
    case FPY_TAG_INT:
        if (data == INT64_MIN) {
            /* abs(-2**63) does not fit an i64.  CPython has no such limit,
             * so widen rather than wrap — negating in place would be UB. */
            FpyBigInt *b = fpy_bigint_from_i64(data);
            FpyBigInt *r = fpy_bigint_abs(b);
            fpy_bigint_free(b);
            *out_tag = FPY_TAG_BIGINT;
            *out_data = (int64_t)(intptr_t)r;
            return;
        }
        *out_tag = FPY_TAG_INT;
        *out_data = (data < 0) ? -data : data;
        return;
    case FPY_TAG_FLOAT: {
        double d;
        memcpy(&d, &data, sizeof(double));
        d = fabs(d);
        *out_tag = FPY_TAG_FLOAT;
        memcpy(out_data, &d, sizeof(double));
        return;
    }
    case FPY_TAG_BIGINT:
        *out_tag = FPY_TAG_BIGINT;
        *out_data = (int64_t)(intptr_t)
            fpy_bigint_abs((FpyBigInt*)(intptr_t)data);
        return;
    case FPY_TAG_DECIMAL:
        *out_tag = FPY_TAG_DECIMAL;
        *out_data = (int64_t)(intptr_t)
            fpy_decimal_abs((FpyDecimal*)(intptr_t)data);
        return;
    case FPY_TAG_COMPLEX: {
        /* abs(a+bj) is a real magnitude, so the result is a float. */
        double m = fpy_complex_abs((FpyComplex*)(intptr_t)data);
        *out_tag = FPY_TAG_FLOAT;
        memcpy(out_data, &m, sizeof(double));
        return;
    }
    default: {
        static const char *_tnames[] = {
            "int", "float", "str", "bool", "NoneType",
            "list", "object", "dict", "bytes", "set",
            "bigint", "complex", "Decimal"};
        const char *tn = (tag >= 0 && tag <= 12) ? _tnames[tag] : "object";
        snprintf(_err_buf, sizeof(_err_buf),
                 "bad operand type for abs(): '%.40s'", tn);
        fastpy_raise(FPY_EXC_TYPEERROR, _err_buf);
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    }
}

/* Unary minus on a runtime-tagged value.
 *
 * Codegen open-coded this as `select(tag == FLOAT, fneg, 0 - data)`, which is
 * the same two-way-dispatch-over-six-numeric-tags mistake as
 * BUG-ABS-OF-TAGGED-VALUE.  A BIGINT operand kept its tag but had its
 * *pointer* negated, so `-(-b)` handed a garbage pointer to the printer and
 * took an access violation.  BUG-BIGINT-FV-RESULT-NOT-CONSUMED. */
void fastpy_neg_fv(int32_t tag, int64_t data,
                   int32_t *out_tag, int64_t *out_data) {
    switch (tag) {
    case FPY_TAG_BOOL:
        /* CPython: -True is -1, an int. */
        *out_tag = FPY_TAG_INT;
        *out_data = (data != 0) ? -1 : 0;
        return;
    case FPY_TAG_INT:
        if (data == INT64_MIN) {
            /* -(-2**63) does not fit an i64; negating in place is UB. */
            FpyBigInt *b = fpy_bigint_from_i64(data);
            FpyBigInt *r = fpy_bigint_neg(b);
            fpy_bigint_free(b);
            *out_tag = FPY_TAG_BIGINT;
            *out_data = (int64_t)(intptr_t)r;
            return;
        }
        *out_tag = FPY_TAG_INT;
        *out_data = -data;
        return;
    case FPY_TAG_FLOAT: {
        double d;
        memcpy(&d, &data, sizeof(double));
        d = -d;
        *out_tag = FPY_TAG_FLOAT;
        memcpy(out_data, &d, sizeof(double));
        return;
    }
    case FPY_TAG_BIGINT:
        *out_tag = FPY_TAG_BIGINT;
        *out_data = (int64_t)(intptr_t)
            fpy_bigint_neg((FpyBigInt*)(intptr_t)data);
        return;
    case FPY_TAG_DECIMAL:
        *out_tag = FPY_TAG_DECIMAL;
        *out_data = (int64_t)(intptr_t)
            fpy_decimal_neg((FpyDecimal*)(intptr_t)data);
        return;
    case FPY_TAG_COMPLEX:
        *out_tag = FPY_TAG_COMPLEX;
        *out_data = (int64_t)(intptr_t)
            fpy_complex_neg((FpyComplex*)(intptr_t)data);
        return;
    default: {
        static const char *_tnames[] = {
            "int", "float", "str", "bool", "NoneType",
            "list", "object", "dict", "bytes", "set",
            "int", "complex", "Decimal"};
        const char *tn = (tag >= 0 && tag <= 12) ? _tnames[tag] : "object";
        snprintf(_err_buf, sizeof(_err_buf),
                 "bad operand type for unary -: '%.40s'", tn);
        fastpy_raise(FPY_EXC_TYPEERROR, _err_buf);
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    }
}

/* The type name a conversion error should print for a tag. BIGINT is "int",
 * because a big integer is not a separate Python type. */
static const char *_fpy_tag_name(int32_t tag) {
    static const char *_tnames[] = {
        "int", "float", "str", "bool", "NoneType",
        "list", "object", "dict", "bytes", "set",
        "int", "complex", "Decimal"};
    return (tag >= 0 && tag <= 12) ? _tnames[tag] : "object";
}

/* Copy a bytes object's data into `buf` as a C string, or return 0 if it does
 * not fit. `int(b"...")`/`float(b"...")` accept only a numeric literal, which
 * is far shorter than any sane buffer, so refusing to grow is not a limit that
 * bites — a rejected long input was never going to parse. */
static int _fpy_bytes_cstr(int64_t data, char *buf, size_t cap) {
    FpyBytes *b = (FpyBytes*)(intptr_t)data;
    if (!b || (size_t)b->length + 1 > cap) return 0;
    memcpy(buf, b->data, (size_t)b->length);
    buf[b->length] = '\0';
    return 1;
}

/* int() of a runtime-tagged value.
 *
 * `_emit_builtin_int` knew two shapes: naked scalars, and an inlined three-way
 * branch (float / str / everything-else) over an FV-backed *variable*. A tagged
 * value arriving any other way — a heterogeneous list element, a "mixed"
 * return — matched neither and was returned unchanged, so `int(v[1])` on
 * `[1, -2.5]` printed `-2.5`. The inlined branch was wrong in its own way: its
 * else arm handed back `data` verbatim, which for a BIGINT or Decimal is the
 * *pointer*, and for None or a list is a nonsense integer instead of a
 * TypeError.  BUG-INT-FLOAT-OF-TAGGED-VALUE.
 *
 * Both now come here, for the reason `fastpy_abs_fv` exists: the numeric tags
 * outnumber the arms anyone inlines, so dispatch belongs in one place that
 * handles all of them and raises for the rest. */
void fastpy_int_fv(int32_t tag, int64_t data,
                   int32_t *out_tag, int64_t *out_data) {
    switch (tag) {
    case FPY_TAG_BOOL:
        *out_tag = FPY_TAG_INT;
        *out_data = (data != 0) ? 1 : 0;
        return;
    case FPY_TAG_INT:
        *out_tag = FPY_TAG_INT;
        *out_data = data;
        return;
    case FPY_TAG_FLOAT: {
        double d;
        memcpy(&d, &data, sizeof(double));
        if (isnan(d)) {
            fastpy_raise(FPY_EXC_VALUEERROR,
                         "cannot convert float NaN to integer");
            *out_tag = FPY_TAG_NONE; *out_data = 0;
            return;
        }
        if (isinf(d)) {
            fastpy_raise(FPY_EXC_OVERFLOWERROR,
                         "cannot convert float infinity to integer");
            *out_tag = FPY_TAG_NONE; *out_data = 0;
            return;
        }
        d = trunc(d);                       /* Python truncates toward zero */
        /* 2^63 exactly, so the comparison is exact in double arithmetic. */
        if (d >= 9223372036854775808.0 || d < -9223372036854775808.0) {
            /* CPython's int(1e30) is exact, so widen rather than saturate. */
            *out_tag = FPY_TAG_BIGINT;
            *out_data = (int64_t)(intptr_t)_fpy_bigint_from_large_double(d);
            return;
        }
        *out_tag = FPY_TAG_INT;
        *out_data = (int64_t)d;
        return;
    }
    case FPY_TAG_STR:
        *out_tag = FPY_TAG_INT;
        *out_data = fastpy_str_to_int((const char*)(intptr_t)data);
        return;
    case FPY_TAG_BYTES: {
        char buf[128];
        if (!_fpy_bytes_cstr(data, buf, sizeof(buf))) {
            fastpy_raise(FPY_EXC_VALUEERROR,
                         "invalid literal for int() with base 10");
            *out_tag = FPY_TAG_NONE; *out_data = 0;
            return;
        }
        *out_tag = FPY_TAG_INT;
        *out_data = fastpy_str_to_int(buf);
        return;
    }
    case FPY_TAG_BIGINT:
        /* A fresh copy, not the argument: every tagged result this file hands
         * back is owned by the caller, and returning the input would give the
         * value two owners with one refcount. */
        *out_tag = FPY_TAG_BIGINT;
        *out_data = (int64_t)(intptr_t)
            fpy_bigint_copy((FpyBigInt*)(intptr_t)data);
        return;
    case FPY_TAG_DECIMAL: {
        /* Truncate toward zero exactly. Going through a double would round —
         * `int(Decimal("0.9999999999999999999"))` must be 0, not 1. */
        FpyDecimal *dc = (FpyDecimal*)(intptr_t)data;
        int64_t coeff = dc->coefficient;
        int32_t e = dc->exponent;
        if (dc->sign == 0) { *out_tag = FPY_TAG_INT; *out_data = 0; return; }
        if (e < 0) {
            /* The coefficient is at most 10^18, so 19 divisions clear it. */
            for (int32_t i = 0; i < -e && coeff != 0; i++) coeff /= 10;
            *out_tag = FPY_TAG_INT;
            *out_data = dc->sign < 0 ? -coeff : coeff;
            return;
        }
        if (e > 0) {
            /* coeff * 10^e can outgrow an i64; build it as text and let the
             * BigInt parser decide, then narrow back if it fits. */
            char buf[64];
            int n = snprintf(buf, sizeof(buf), "%s%lld",
                             dc->sign < 0 ? "-" : "", (long long)coeff);
            if (n > 0 && (size_t)n + (size_t)e < sizeof(buf)) {
                memset(buf + n, '0', (size_t)e);
                buf[n + e] = '\0';
                FpyBigInt *b = fpy_bigint_from_str(buf);
                int ovf = 0;
                int64_t v = fpy_bigint_to_i64(b, &ovf);
                if (!ovf) {
                    fpy_bigint_free(b);
                    *out_tag = FPY_TAG_INT;
                    *out_data = v;
                    return;
                }
                *out_tag = FPY_TAG_BIGINT;
                *out_data = (int64_t)(intptr_t)b;
                return;
            }
        }
        *out_tag = FPY_TAG_INT;
        *out_data = dc->sign < 0 ? -coeff : coeff;
        return;
    }
    default:
        snprintf(_err_buf, sizeof(_err_buf),
                 "int() argument must be a string, a bytes-like object or a "
                 "real number, not '%.40s'", _fpy_tag_name(tag));
        fastpy_raise(FPY_EXC_TYPEERROR, _err_buf);
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
}

/* float() of a runtime-tagged value — the sibling of fastpy_int_fv, and broken
 * the same two ways: `float(v[0])` on `[1, -2.5]` returned the int unchanged,
 * and the inlined variable path's else arm ran `sitofp` on whatever was in
 * `data`, which for a BigInt or Decimal is a pointer converted to a double.
 * BUG-INT-FLOAT-OF-TAGGED-VALUE. */
void fastpy_float_fv(int32_t tag, int64_t data,
                     int32_t *out_tag, int64_t *out_data) {
    double d;
    switch (tag) {
    case FPY_TAG_BOOL:
        d = (data != 0) ? 1.0 : 0.0;
        break;
    case FPY_TAG_INT:
        d = (double)data;
        break;
    case FPY_TAG_FLOAT:
        *out_tag = FPY_TAG_FLOAT;
        *out_data = data;
        return;
    case FPY_TAG_STR:
        d = fastpy_str_to_float((const char*)(intptr_t)data);
        break;
    case FPY_TAG_BYTES: {
        char buf[128];
        if (!_fpy_bytes_cstr(data, buf, sizeof(buf))) {
            fastpy_raise(FPY_EXC_VALUEERROR,
                         "could not convert string to float");
            *out_tag = FPY_TAG_NONE; *out_data = 0;
            return;
        }
        d = fastpy_str_to_float(buf);
        break;
    }
    case FPY_TAG_BIGINT:
        if (fpy_bigint_to_double((FpyBigInt*)(intptr_t)data, &d) != 0) {
            fastpy_raise(FPY_EXC_OVERFLOWERROR,
                         "int too large to convert to float");
            *out_tag = FPY_TAG_NONE; *out_data = 0;
            return;
        }
        break;
    case FPY_TAG_DECIMAL:
        d = _fpy_decimal_to_double((FpyDecimal*)(intptr_t)data);
        break;
    default:
        snprintf(_err_buf, sizeof(_err_buf),
                 "float() argument must be a string or a real number, "
                 "not '%.40s'", _fpy_tag_name(tag));
        fastpy_raise(FPY_EXC_TYPEERROR, _err_buf);
        *out_tag = FPY_TAG_NONE;
        *out_data = 0;
        return;
    }
    *out_tag = FPY_TAG_FLOAT;
    memcpy(out_data, &d, sizeof(double));
}

char* fpy_decimal_to_str(FpyDecimal *d) {
    if (d->sign == 0) return fpy_strdup("0");

    char coeff_buf[32];
    snprintf(coeff_buf, sizeof(coeff_buf), "%lld", (long long)d->coefficient);
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
    /* json_serialize realloc-grows buf, so it can't carry the FpyString
     * header; copy into a header-backed string (refcount 1) and free the
     * scratch buffer. See BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC. */
    const char *result = fpy_str_copy(buf, len);
    free(buf);
    return result;
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
    /* Return a header-backed FpyString (refcount 1) so the parsed STR value
     * has a valid FpyString header for fpy_str_header/decref — the growth
     * buffer above is realloc'd, so it can't itself carry the header; copy
     * into a fresh headered string and free the scratch buffer.
     * See BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC. */
    *out = fpy_str_copy(buf, len);
    free(buf);
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
#include <process.h>
#include <sys/stat.h>   /* MSVC: struct _stat64 / _stat64() for os.path.getsize/getmtime */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <fcntl.h>
#endif

const char* fastpy_os_getcwd(void) {
    char *buf = fpy_str_buf(4096);
#ifdef _WIN32
    _getcwd(buf, 4096);
#else
    getcwd(buf, 4096);
#endif
    return buf;
}

/* os.getpid() -> the calling process's PID. On SlateOS posix getpid() is a
 * real SYS_PROCESS_ID syscall; on the host it is the OS pid. Returned as a
 * bare i64 (PIDs comfortably fit). */
int64_t fastpy_os_getpid(void) {
#ifdef _WIN32
    return (int64_t)_getpid();
#else
    return (int64_t)getpid();
#endif
}

/* os.getppid() -> the parent process's PID. On SlateOS posix getppid() is a
 * real SYS_PROCESS_PARENT_ID syscall (a kernel-spawned orphan is reparented to
 * init, so it returns 1). Windows has no getppid(); host builds of fastpy
 * tools don't run on SlateOS, so a fixed 1 placeholder is fine there. */
int64_t fastpy_os_getppid(void) {
#ifdef _WIN32
    return (int64_t)1;
#else
    return (int64_t)getppid();
#endif
}

/* os.gettid() -> the calling thread's kernel task ID. On SlateOS posix
 * gettid() is a real SYS_TASK_ID syscall — the scheduler's task table, a
 * distinct kernel path from the process table hit by getpid()/getppid(). musl's
 * headers only declare gettid() under _GNU_SOURCE, and at link time the symbol
 * resolves to the SlateOS posix crate's extern "C" gettid (PidT == i32), so we
 * forward-declare it ourselves rather than depend on a feature-test macro.
 * Windows host builds don't run on SlateOS, so a fixed 1 placeholder is fine. */
#ifndef _WIN32
extern int gettid(void);
#endif
int64_t fastpy_os_gettid(void) {
#ifdef _WIN32
    return (int64_t)1;
#else
    return (int64_t)gettid();
#endif
}

/* os.getuid()/os.getgid() -> the calling process's real uid/gid. On SlateOS
 * posix getuid()/getgid() issue the real SYS_PROCESS_GET_CREDENTIALS syscall,
 * reading the process credentials the kernel set at spawn (from
 * SpawnOptions.uid_gid) — a distinct kernel path (the process-credentials
 * table) from the pid/tid identity syscalls. getuid()/getgid() are declared by
 * musl's <unistd.h> and resolve at link time to the SlateOS posix crate's
 * extern "C" symbols. Windows host builds don't run on SlateOS, so root (0) is
 * a fine placeholder there. */
int64_t fastpy_os_getuid(void) {
#ifdef _WIN32
    return (int64_t)0;
#else
    return (int64_t)getuid();
#endif
}

int64_t fastpy_os_getgid(void) {
#ifdef _WIN32
    return (int64_t)0;
#else
    return (int64_t)getgid();
#endif
}

/* os.setuid(uid)/os.setgid(gid) -> status (0 ok, -1 on EPERM). On SlateOS
 * posix setuid()/setgid() perform the userspace CAP_SETUID/CAP_SETGID +
 * identity check and, if allowed, issue the real SYS_PROCESS_SET_CREDENTIALS
 * syscall that *mutates* the process's kernel credentials (previously these
 * silently succeeded without changing anything). A distinct kernel path (the
 * process-credentials table) from the read-only getuid/getgid. setuid()/
 * setgid() are declared by musl's <unistd.h> and resolve at link time to the
 * SlateOS posix crate's extern "C" symbols. CPython os.setuid returns None;
 * like os.remove/chmod, fastpy models the outcome as an int status. Windows
 * host builds don't run on SlateOS, so report success (0) there. */
int64_t fastpy_os_setuid(int64_t uid) {
#ifdef _WIN32
    (void)uid;
    return (int64_t)0;
#else
    return (int64_t)setuid((uid_t)uid);
#endif
}

int64_t fastpy_os_setgid(int64_t gid) {
#ifdef _WIN32
    (void)gid;
    return (int64_t)0;
#else
    return (int64_t)setgid((gid_t)gid);
#endif
}

/* os.nice(inc) -> the new nice value. On SlateOS posix nice() reads the
 * process's current kernel nice (SYS_PROCESS_GET_NICE), adds the increment,
 * and — after the userspace CAP_SYS_NICE check for a priority-raise — installs
 * it via SYS_PROCESS_SET_NICE, which ALSO maps nice to a scheduler priority
 * level and re-prioritises the process's tasks. Nice is thus a real scheduling
 * attribute (previously the value was stored in a userspace static that did
 * not affect scheduling). A distinct kernel path (the scheduler's per-task
 * priority) from every filesystem/credential syscall. nice() is declared by
 * musl's <unistd.h> and resolves at link time to the SlateOS posix crate's
 * extern "C" symbol. Windows has no nice(); host builds don't run on SlateOS,
 * so 0 is a fine placeholder. */
int64_t fastpy_os_nice(int64_t inc) {
#ifdef _WIN32
    (void)inc;
    return (int64_t)0;
#else
    return (int64_t)nice((int)inc);
#endif
}

/* os.getpriority(which, who) -> the target's nice value. On SlateOS posix
 * getpriority() reads the caller's real kernel nice via SYS_PROCESS_GET_NICE.
 * getpriority() is declared by musl's <sys/resource.h>. Windows host builds
 * don't run on SlateOS, so 0 (the default nice) is a fine placeholder. */
int64_t fastpy_os_getpriority(int64_t which, int64_t who) {
#ifdef _WIN32
    (void)which; (void)who;
    return (int64_t)0;
#else
    return (int64_t)getpriority((int)which, (id_t)who);
#endif
}

/* os.setpriority(which, who, prio) -> status (0 ok, -1 error). On SlateOS
 * posix setpriority() installs the nice value via SYS_PROCESS_SET_NICE (which
 * re-prioritises the process's tasks) after the userspace CAP_SYS_NICE check.
 * setpriority() is declared by musl's <sys/resource.h>. Windows host builds
 * don't run on SlateOS, so report success (0). */
int64_t fastpy_os_setpriority(int64_t which, int64_t who, int64_t prio) {
#ifdef _WIN32
    (void)which; (void)who; (void)prio;
    return (int64_t)0;
#else
    return (int64_t)setpriority((int)which, (id_t)who, (int)prio);
#endif
}

/* os.pipe() -> (read_fd, write_fd). On SlateOS posix pipe() issues the real
 * SYS_PIPE_CREATE syscall — a genuinely distinct kernel path (the pipe
 * subsystem) not touched by any file/process syscall. Python's os.pipe()
 * returns a 2-tuple; fastpy pure mode unpacks a 2-element list identically, so
 * we return a fastpy list [read_fd, write_fd]. On error both entries are -1.
 * Windows host builds don't run on SlateOS but _pipe() fills the fds too. */
FpyList* fastpy_os_pipe(void) {
    FpyList *lst = fpy_list_new(2);
    int r = -1, w = -1;
    int fds[2];
#ifdef _WIN32
    if (_pipe(fds, 65536, 0) == 0) { r = fds[0]; w = fds[1]; }
#else
    if (pipe(fds) == 0) { r = fds[0]; w = fds[1]; }
#endif
    FpyValue vr; vr.tag = FPY_TAG_INT; vr.data.i = (int64_t)r; fpy_list_append(lst, vr);
    FpyValue vw; vw.tag = FPY_TAG_INT; vw.data.i = (int64_t)w; fpy_list_append(lst, vw);
    return lst;
}

/* os.write(fd, data) -> bytes written (or -1). `fd` is a raw integer fd (e.g. a
 * pipe end from os.pipe()); `data` is a fastpy str (NUL-terminated char*). On
 * SlateOS posix write() dispatches by fd kind — for a pipe fd it routes to the
 * pipe's kernel buffer via SYS_PIPE_WRITE (a regular file fd would use
 * SYS_FS_WRITE). We use strlen() — the pipe self-test uses NUL-free ASCII; a
 * NUL-safe bytes overload can be added later if a caller needs embedded NULs. */
int64_t fastpy_os_write(int64_t fd, const char *data) {
    if (!data) return -1;
    size_t n = strlen(data);
#ifdef _WIN32
    return (int64_t)_write((int)fd, data, (unsigned)n);
#else
    return (int64_t)write((int)fd, data, n);
#endif
}

/* os.read(fd, n) -> str of up to `n` bytes read (empty on EOF/error). `fd` is a
 * raw integer fd. On SlateOS posix read() dispatches by fd kind — for a pipe fd
 * it pulls from the pipe's kernel buffer via SYS_PIPE_READ (a regular file fd
 * would use SYS_FS_READ). Returns a fastpy owned string; NUL-terminated, so it
 * is safe for the NUL-free ASCII the pipe self-test round-trips. */
const char* fastpy_os_read(int64_t fd, int64_t n) {
    if (n < 0) n = 0;
    FpyString *s = fpy_str_alloc(n);
    long got;
#ifdef _WIN32
    got = (long)_read((int)fd, s->data, (unsigned)n);
#else
    got = (long)read((int)fd, s->data, (size_t)n);
#endif
    if (got < 0) got = 0;
    s->data[got] = '\0';
    return s->data;
}

/* os.close(fd) -> 0 on success, -1 on error. Closes a raw integer fd (e.g. a
 * pipe end); posix close() releases the fd-table entry and its kernel handle
 * (SYS_PIPE_CLOSE for a pipe end). */
int64_t fastpy_os_close(int64_t fd) {
#ifdef _WIN32
    return (int64_t)(_close((int)fd) == 0 ? 0 : -1);
#else
    return (int64_t)(close((int)fd) == 0 ? 0 : -1);
#endif
}

/* os.dup(fd) -> a new raw integer fd referring to the same open file /
 * pipe end / socket as `fd` (or -1 on error). On SlateOS posix dup()
 * shares the underlying kernel handle at the fd-table level — for a pipe
 * end the duplicate aliases the same kernel pipe buffer, so bytes written
 * through the dup are readable from the original pipe's read end. */
int64_t fastpy_os_dup(int64_t fd) {
#ifdef _WIN32
    return (int64_t)_dup((int)fd);
#else
    return (int64_t)dup((int)fd);
#endif
}

/* os.dup2(oldfd, newfd) -> newfd on success (or -1). Unlike dup(), which picks
 * the lowest free fd, dup2() installs a copy of `oldfd` at the *caller-chosen*
 * `newfd` (silently closing whatever was open there first), sharing the same
 * underlying kernel handle — for a pipe end the target aliases the same kernel
 * pipe buffer. On SlateOS this is posix dup2() at the fd-table level; the
 * close-then-alias-at-a-specific-fd semantics are a distinct path from dup(). */
int64_t fastpy_os_dup2(int64_t oldfd, int64_t newfd) {
#ifdef _WIN32
    return (_dup2((int)oldfd, (int)newfd) == 0) ? newfd : (int64_t)-1;
#else
    return (int64_t)dup2((int)oldfd, (int)newfd);
#endif
}

/* os.lseek(fd, offset, whence) -> the new absolute file offset (or -1 on
 * error). `whence` is SEEK_SET (0), SEEK_CUR (1) or SEEK_END (2). On SlateOS
 * posix lseek() repositions a regular file fd's kernel offset via SYS_FS_SEEK
 * — a genuinely distinct kernel path from read/write. Not meaningful for a
 * pipe (which is not seekable); intended for regular file fds. */
int64_t fastpy_os_lseek(int64_t fd, int64_t offset, int64_t whence) {
#ifdef _WIN32
    return (int64_t)_lseeki64((int)fd, (long long)offset, (int)whence);
#else
    return (int64_t)lseek((int)fd, (off_t)offset, (int)whence);
#endif
}

/* os.open(path, flags, mode) -> a new raw integer fd for a regular file (or -1
 * on error). `flags` are the standard POSIX open() bits (O_RDONLY=0,
 * O_WRONLY=1, O_RDWR=2, O_CREAT=0100, O_TRUNC=01000, ...) and `mode` the
 * creation permission bits (e.g. 0644). On SlateOS this is posix open() ->
 * SYS_FS_OPEN, yielding a raw file fd that native os.read/os.write/os.lseek/
 * os.close then drive — the raw-fd counterpart to the high-level open() every
 * other fastpy tool uses. (On the Windows host build the flag/mode bit values
 * differ; this helper targets the SlateOS/posix ABI.) */
int64_t fastpy_os_open(const char *path, int64_t flags, int64_t mode) {
    if (!path) return -1;
#ifdef _WIN32
    return (int64_t)_open(path, (int)flags, (int)mode);
#else
    return (int64_t)open(path, (int)flags, (mode_t)mode);
#endif
}

/* os.umask(mask) -> the *previous* process file-mode creation mask. Sets the
 * new mask (low 9 rwxrwxrwx bits) and returns the old one, matching POSIX
 * umask(). On SlateOS this is posix umask(), which stores the mask in the
 * userspace POSIX layer; subsequent file/dir creation (os.open O_CREAT,
 * os.mkdir) masks its mode with it before handing the final permission bits
 * to the kernel create primitive (SYS_FS_OPEN / SYS_FS_MKDIR). A genuine
 * observable mutation: after os.umask(022), creating a 0777 file yields 0755
 * on disk. */
int64_t fastpy_os_umask(int64_t mask) {
#ifdef _WIN32
    /* Windows _umask only models the read-only bit; still returns the prior
     * mask so chained get/set semantics work on the host build. */
    return (int64_t)_umask((int)(mask & 0777));
#else
    return (int64_t)umask((mode_t)(mask & 0777));
#endif
}

/* os.ftruncate(fd, length) -> 0 on success, -1 on error. Sets the size of the
 * regular file open on `fd` to exactly `length` bytes (extending with zeros or
 * discarding the tail). On SlateOS this is posix ftruncate() -> SYS_FS_FTRUNCATE
 * — a genuinely distinct kernel path from lseek/write, and from the path-based
 * os.truncate() (SYS_FS_TRUNCATE). Not meaningful for a pipe. */
int64_t fastpy_os_ftruncate(int64_t fd, int64_t length) {
#ifdef _WIN32
    return (int64_t)(_chsize_s((int)fd, (long long)length) == 0 ? 0 : -1);
#else
    return (int64_t)(ftruncate((int)fd, (off_t)length) == 0 ? 0 : -1);
#endif
}

/* os.pwrite(fd, data, offset) -> bytes written (or -1). Positioned write: the
 * bytes go to absolute file `offset` WITHOUT changing the fd's current file
 * offset. On SlateOS this is posix pwrite() (atomic seek+write on SYS_FS_SEEK/
 * SYS_FS_WRITE, restoring the offset) — distinct from write+lseek because the
 * fd position is untouched. `data` is a fastpy str (NUL-terminated); we use
 * strlen (NUL-free ASCII, matching the raw-fd I/O convention here). */
int64_t fastpy_os_pwrite(int64_t fd, const char *data, int64_t offset) {
    if (!data) return -1;
    size_t n = strlen(data);
#ifdef _WIN32
    long long saved = _lseeki64((int)fd, 0, SEEK_CUR);
    if (saved < 0) return -1;
    if (_lseeki64((int)fd, (long long)offset, SEEK_SET) < 0) return -1;
    int w = _write((int)fd, data, (unsigned)n);
    (void)_lseeki64((int)fd, saved, SEEK_SET);
    return (int64_t)w;
#else
    return (int64_t)pwrite((int)fd, data, n, (off_t)offset);
#endif
}

/* os.pread(fd, n, offset) -> str of up to `n` bytes read from absolute file
 * `offset` WITHOUT changing the fd's current file offset. On SlateOS this is
 * posix pread() — distinct from lseek+read because the fd position is
 * untouched. Returns a fastpy owned NUL-terminated string. */
const char* fastpy_os_pread(int64_t fd, int64_t n, int64_t offset) {
    if (n < 0) n = 0;
    FpyString *s = fpy_str_alloc(n);
    long got;
#ifdef _WIN32
    long long saved = _lseeki64((int)fd, 0, SEEK_CUR);
    if (saved >= 0 && _lseeki64((int)fd, (long long)offset, SEEK_SET) >= 0) {
        got = (long)_read((int)fd, s->data, (unsigned)n);
        (void)_lseeki64((int)fd, saved, SEEK_SET);
    } else {
        got = -1;
    }
#else
    got = (long)pread((int)fd, s->data, (size_t)n, (off_t)offset);
#endif
    if (got < 0) got = 0;
    s->data[got] = '\0';
    return s->data;
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

/* os.path.getsize(path) -> file size in bytes.  Python raises OSError when the
 * path doesn't exist; pure/AOT mode surfaces that as -1 (mirroring the int
 * error convention of os.remove/mkdir), so callers can branch on rc < 0. */
int64_t fastpy_os_path_getsize(const char *path) {
#ifdef _WIN32
    struct _stat64 st;
    if (_stat64(path, &st) != 0) return -1;
    return (int64_t)st.st_size;
#else
    struct stat st;
    if (stat(path, &st) != 0) return -1;
    return (int64_t)st.st_size;
#endif
}

/* os.path.getmtime(path) -> modification time in seconds since the epoch as a
 * CPython-faithful float.  Reads the mtime field of the stat struct (a distinct
 * metadata field from getsize's st_size); returns -1.0 on error.  On posix we
 * combine whole seconds with the nanosecond sub-second field (st_mtim.tv_nsec)
 * so sub-second precision survives the round-trip. */
double fastpy_os_path_getmtime(const char *path) {
#ifdef _WIN32
    struct _stat64 st;
    if (_stat64(path, &st) != 0) return -1.0;
    return (double)st.st_mtime;
#else
    struct stat st;
    if (stat(path, &st) != 0) return -1.0;
    return (double)st.st_mtim.tv_sec + (double)st.st_mtim.tv_nsec / 1e9;
#endif
}

/* os.path.getatime: last-access time (st_atim) as epoch seconds (double).
 * Distinct stat field from getmtime's st_mtim — reads the *atime* the
 * kernel/utime stamped.  CPython returns a float; -1.0 on stat error. */
double fastpy_os_path_getatime(const char *path) {
#ifdef _WIN32
    struct _stat64 st;
    if (_stat64(path, &st) != 0) return -1.0;
    return (double)st.st_atime;
#else
    struct stat st;
    if (stat(path, &st) != 0) return -1.0;
    return (double)st.st_atim.tv_sec + (double)st.st_atim.tv_nsec / 1e9;
#endif
}

/* os.path.getctime: metadata-change time (st_ctim) as epoch seconds (double).
 * On POSIX this is the inode change time (ctime) — a *distinct* stat field
 * from atime/mtime, and (unlike them) not settable via os.utime; it reflects
 * when the file's metadata last changed (e.g. creation).  CPython returns a
 * float (on Windows it's the creation time); -1.0 on stat error. */
double fastpy_os_path_getctime(const char *path) {
#ifdef _WIN32
    struct _stat64 st;
    if (_stat64(path, &st) != 0) return -1.0;
    return (double)st.st_ctime;
#else
    struct stat st;
    if (stat(path, &st) != 0) return -1.0;
    return (double)st.st_ctim.tv_sec + (double)st.st_ctim.tv_nsec / 1e9;
#endif
}

/* os.access(path, mode) -> 1 if accessible (True), 0 otherwise (False).
 * Mirrors CPython os.access, which returns a bool.  `mode` is the POSIX
 * accessibility mask: F_OK=0, R_OK=4, W_OK=2, X_OK=1.  Unlike the get*time
 * probes this exercises the libc access() entry point, and the mode argument
 * is genuinely honored: POSIX access() rejects mode bits outside R|W|X with
 * EINVAL, so os.access(path, 8) returns False even for an existing file.
 * (SlateOS has no per-user permission enforcement yet, so a *valid* mode
 * succeeds iff the path exists — but the mode is still validated.) */
int64_t fastpy_os_access(const char *path, int64_t mode) {
    if (path == NULL) return 0;
#ifdef _WIN32
    /* Windows _access has no X_OK; map any valid *nix mode to an existence
     * check (mode 0) and reject out-of-range mode bits like POSIX does. */
    if (mode & ~(int64_t)6) {
        /* Only F_OK/R_OK/W_OK are representable on Windows; treat X_OK(1) and
         * out-of-range bits as invalid so host builds match the SlateOS EINVAL
         * behavior for the self-test's invalid-mode case. */
        if (mode & ~(int64_t)7) return 0;   /* out of R|W|X range -> False */
    }
    return (_access(path, 0) == 0) ? 1 : 0;
#else
    return (access(path, (int)mode) == 0) ? 1 : 0;
#endif
}

/* os.path.samefile(a, b) -> 1 if both paths refer to the same file (True),
 * 0 otherwise (False).  Mirrors CPython os.path.samefile, which compares the
 * (st_dev, st_ino) identity of two stat() results.  This is the first fastpy
 * lowering to exercise the *st_ino* field: both stat() calls follow symlinks
 * (POSIX stat semantics), so a file and a symlink pointing at it compare equal
 * (same inode), while two distinct files have distinct synthetic inodes and
 * compare unequal.  CPython raises if a path is missing; the AOT-simplified
 * form returns False on any stat error. */
int64_t fastpy_os_path_samefile(const char *a, const char *b) {
    if (a == NULL || b == NULL) return 0;
#ifdef _WIN32
    struct _stat64 sa, sb;
    if (_stat64(a, &sa) != 0) return 0;
    if (_stat64(b, &sb) != 0) return 0;
#else
    struct stat sa, sb;
    if (stat(a, &sa) != 0) return 0;
    if (stat(b, &sb) != 0) return 0;
#endif
    return (sa.st_dev == sb.st_dev && sa.st_ino == sb.st_ino) ? 1 : 0;
}

/* os.path.islink(path) -> 1 if path is a symbolic link (True), 0 otherwise.
 * Mirrors CPython os.path.islink, which lstat()s the path (crucially NOT
 * following the final symlink) and tests S_ISLNK on st_mode.  This is the
 * first fastpy lowering to use *lstat* (no-follow) semantics — distinct from
 * exists/isfile/isdir, which all follow symlinks via stat().  Because it does
 * not follow the link, a symlink returns True even when its target is missing
 * (the link entry itself exists), while a regular file — or the target a
 * symlink resolves to — returns False.  CPython returns False on any OSError;
 * the AOT-simplified form returns 0 on any lstat error. */
int64_t fastpy_os_path_islink(const char *path) {
    if (path == NULL) return 0;
#ifdef _WIN32
    /* Windows _stat cannot distinguish reparse points; the host self-test does
     * not exercise this branch, so report non-link. */
    return 0;
#else
    struct stat st;
    if (lstat(path, &st) != 0) return 0;
    return S_ISLNK(st.st_mode) ? 1 : 0;
#endif
}

/* os.stat(path) -> a 10-int list mirroring CPython's os.stat_result *sequence*
 * form: (st_mode, st_ino, st_dev, st_nlink, st_uid, st_gid, st_size,
 *        st_atime, st_mtime, st_ctime).  The timestamps are integer seconds —
 * the index/tuple form (CPython exposes sub-second floats only via the named
 * .st_*time attributes, not the sequence).  A single stat() call (SYS_FS_STAT,
 * follows symlinks) fills the whole struct, so this is the capstone that
 * exercises many stat fields at once — st_mode/st_ino/st_dev/st_nlink/st_size
 * plus the three timestamps — rather than one field per lowering.  CPython
 * raises OSError on failure; the AOT-simplified form returns an empty list on
 * any stat error (an indexing self-test uses a known-good path). */
FpyList* fastpy_os_stat(const char *path) {
    FpyList *lst = fpy_list_new(10);
    if (path == NULL) return lst;
#ifdef _WIN32
    struct _stat64 st;
    if (_stat64(path, &st) != 0) return lst;
#else
    struct stat st;
    if (stat(path, &st) != 0) return lst;
#endif
    /* musl/glibc/Win32 all provide st_atime/st_mtime/st_ctime (as macros for
     * the .tv_sec of the timespec on POSIX), so this order is portable. */
    fpy_list_append(lst, fpy_int((int64_t)st.st_mode));
    fpy_list_append(lst, fpy_int((int64_t)st.st_ino));
    fpy_list_append(lst, fpy_int((int64_t)st.st_dev));
    fpy_list_append(lst, fpy_int((int64_t)st.st_nlink));
    fpy_list_append(lst, fpy_int((int64_t)st.st_uid));
    fpy_list_append(lst, fpy_int((int64_t)st.st_gid));
    fpy_list_append(lst, fpy_int((int64_t)st.st_size));
    fpy_list_append(lst, fpy_int((int64_t)st.st_atime));
    fpy_list_append(lst, fpy_int((int64_t)st.st_mtime));
    fpy_list_append(lst, fpy_int((int64_t)st.st_ctime));
    return lst;
}

/* os.statvfs(path): filesystem capacity/limits via a single statvfs() call.
 * Returns CPython's os.statvfs_result sequence form as a 10-int list in the
 * documented field order:
 *   (f_bsize, f_frsize, f_blocks, f_bfree, f_bavail,
 *    f_files, f_ffree, f_favail, f_flag, f_namemax)
 * Distinct from os.stat (per-file metadata): this reports the *whole
 * filesystem* the path lives on (block sizes, block/inode totals & free
 * counts, mount flags, and the max filename length). */
FpyList* fastpy_os_statvfs(const char *path) {
    FpyList *lst = fpy_list_new(10);
    if (path == NULL) return lst;
#ifdef _WIN32
    /* Win32 has no statvfs; the SlateOS target never takes this branch. */
    (void)path;
    return lst;
#else
    struct statvfs vfs;
    if (statvfs(path, &vfs) != 0) return lst;
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_bsize));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_frsize));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_blocks));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_bfree));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_bavail));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_files));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_ffree));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_favail));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_flag));
    fpy_list_append(lst, fpy_int((int64_t)vfs.f_namemax));
    return lst;
#endif
}

const char* fastpy_os_path_join(const char *a, const char *b) {
    int alen = (int)strlen(a), blen = (int)strlen(b);
    char *buf = fpy_str_buf(alen + blen + 1);
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
    return fpy_str_from_cstr(last);
}

const char* fastpy_os_path_dirname(const char *path) {
    const char *last_sep = NULL;
    for (const char *p = path; *p; p++) {
        if (*p == '/' || *p == '\\') last_sep = p;
    }
    if (!last_sep) return fpy_str_from_cstr("");
    int len = (int)(last_sep - path);
    char *buf = fpy_str_buf(len);
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
            v.data.s = fpy_str_from_cstr(fd.cFileName);
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
            v.data.s = fpy_str_from_cstr(ent->d_name);
            fpy_list_append(lst, v);
        }
        closedir(d);
    }
#endif
    return lst;
}

const char* fastpy_os_getenv(const char *name) {
    const char *val = getenv(name);
    return val ? fpy_str_from_cstr(val) : NULL;
}

/* os.remove(path) / os.unlink(path): delete a directory entry.
 * Returns 0 on success, -1 on failure.  Python's os.remove returns None and
 * raises OSError on failure; in pure/AOT mode (no exception unwinding wired
 * for this path) we surface success/failure as an int status instead, so a
 * caller can branch on it (mirrors os.path.exists returning a bool).  Backed
 * by C stdio remove(), which the SlateOS posix libc implements over
 * SYS_FS_DELETE. */
int64_t fastpy_os_remove(const char *path) {
    return (int64_t)(remove(path) == 0 ? 0 : -1);
}

/* os.mkdir(path) -> 0 ok / -1 error.  Python's os.mkdir defaults mode 0o777
 * (further masked by umask); we pass 0777 on POSIX/SlateOS.  On Windows the
 * CRT _mkdir takes no mode. */
int64_t fastpy_os_mkdir(const char *path) {
#ifdef _WIN32
    return (int64_t)(_mkdir(path) == 0 ? 0 : -1);
#else
    return (int64_t)(mkdir(path, 0777) == 0 ? 0 : -1);
#endif
}

/* os.rmdir(path) -> 0 ok / -1 error. */
int64_t fastpy_os_rmdir(const char *path) {
#ifdef _WIN32
    return (int64_t)(_rmdir(path) == 0 ? 0 : -1);
#else
    return (int64_t)(rmdir(path) == 0 ? 0 : -1);
#endif
}

/* os.rename(src, dst) -> 0 ok / -1 error.  C rename() handles both files and
 * directories; on SlateOS it maps to SYS_FS_RENAME. */
int64_t fastpy_os_rename(const char *src, const char *dst) {
    return (int64_t)(rename(src, dst) == 0 ? 0 : -1);
}

/* os.execv(path, argv) -> only returns on FAILURE (-1); on success the calling
 * process image is REPLACED by the program at `path` (execv never returns).
 * `argv` is an FpyList* of str whose elements become the NULL-terminated C
 * argv[].  On SlateOS posix execv() lowers to SYS_EXECVE, so a fastpy program
 * can resolve an installed /bin command by name and hand off to it — the core
 * primitive a shell/`init` uses.  Python raises OSError on failure; in pure/AOT
 * mode (no exception unwinding on this path) we surface the failure as -1 so a
 * caller can branch on it, mirroring os.remove/os.rename. */
int64_t fastpy_os_execv(const char *path, FpyList *argv) {
#ifdef _WIN32
    (void)path; (void)argv;
    return -1;
#else
    if (path == NULL) return -1;
    int64_t n = argv ? fpy_list_len(argv) : 0;
    if (n < 0) n = 0;
    /* +1 for the NULL terminator execv() requires. */
    char **cargv = (char **)malloc((size_t)(n + 1) * sizeof(char *));
    if (cargv == NULL) return -1;
    for (int64_t i = 0; i < n; i++) {
        FpyValue v = fpy_list_get(argv, i);
        /* execv takes char *const argv[]; it does not modify the strings, so
         * casting away const on the list-owned str is safe.  Non-str elements
         * (shouldn't happen for a list[str]) degrade to an empty argument. */
        cargv[i] = (v.tag == FPY_TAG_STR && v.data.s)
                       ? (char *)v.data.s
                       : (char *)"";
    }
    cargv[n] = NULL;
    execv(path, cargv);
    /* Only reached if execv failed (e.g. ENOENT). Free our scratch and report
     * failure; the list-owned strings are not ours to free. */
    free(cargv);
    return -1;
#endif
}

/* os.fork() -> child PID in the parent, 0 in the child, -1 on failure.  On
 * SlateOS posix fork() lowers to SYS_PROCESS_FORK: the kernel clones the
 * caller's address space copy-on-write, duplicates its handle table
 * (refcount-shared), and resumes the child at the same point with RAX forced to
 * 0.  A single call site therefore yields both views — the classic fork/exec
 * pattern (fork, then os.execv in the child, os.waitpid in the parent) that a
 * shell/`init` uses to spawn a child without replacing itself.  Windows host
 * builds have no fork(); they return -1. */
int64_t fastpy_os_fork(void) {
#ifdef _WIN32
    return -1;
#else
    return (int64_t)fork();
#endif
}

/* os.waitpid(pid, options) -> 2-element list [pid, status].  CPython returns a
 * (pid, status) tuple; fastpy pure mode unpacks a 2-element list identically, so
 * `p, st` = os.waitpid(child, 0) works.  On SlateOS posix waitpid() reaps a
 * child and returns its raw wait status; we hand back both the reaped pid and
 * the encoded status so a caller can decode it with os.WIFEXITED/os.WEXITSTATUS
 * (or the raw value).  On error the returned pid is -1.  Windows: -1/0. */
FpyList* fastpy_os_waitpid(int64_t pid, int64_t options) {
    FpyList *lst = fpy_list_new(2);
    int64_t rpid = -1, rstatus = 0;
#ifndef _WIN32
    int status = 0;
    pid_t r = waitpid((pid_t)pid, &status, (int)options);
    rpid = (int64_t)r;
    rstatus = (int64_t)status;
#else
    (void)pid; (void)options;
#endif
    FpyValue vp; vp.tag = FPY_TAG_INT; vp.data.i = rpid; fpy_list_append(lst, vp);
    FpyValue vs; vs.tag = FPY_TAG_INT; vs.data.i = rstatus; fpy_list_append(lst, vs);
    return lst;
}

/* os.WIFEXITED(status) -> 1 if the child exited normally, else 0.  Decodes the
 * raw wait status from os.waitpid.  Windows builds: the status is already a
 * plain exit code (no encoding), so treat any status as "exited". */
int64_t fastpy_os_wifexited(int64_t status) {
#ifdef _WIN32
    (void)status; return 1;
#else
    int s = (int)status;
    return (int64_t)(WIFEXITED(s) ? 1 : 0);
#endif
}

/* os.WEXITSTATUS(status) -> the child's exit code (low 8 bits) from a status
 * that WIFEXITED reports as a normal exit.  On Windows the status is already the
 * exit code. */
int64_t fastpy_os_wexitstatus(int64_t status) {
#ifdef _WIN32
    return status & 0xff;
#else
    int s = (int)status;
    return (int64_t)WEXITSTATUS(s);
#endif
}

/* os.symlink(target, linkpath) -> 0 ok / -1 error.  Note the CPython argument
 * order: symlink(src, dst) creates dst as a link *pointing at* src.  On
 * SlateOS the posix libc symlink() maps to SYS_FS_SYMLINK (Rights::CREATE).
 * Windows has no POSIX symlink()/readlink(), so those builds return -1. */
int64_t fastpy_os_symlink(const char *target, const char *linkpath) {
#ifdef _WIN32
    (void)target; (void)linkpath;
    return -1;
#else
    return (int64_t)(symlink(target, linkpath) == 0 ? 0 : -1);
#endif
}

/* os.link(src, dst) -> 0 ok / -1 error.  Creates a hard link `dst` referring
 * to the same inode as `src` (POSIX order: link(oldpath, newpath)).  On
 * SlateOS the posix libc link() maps to SYS_FS_LINK (Rights::CREATE).  Windows
 * has no POSIX link(), so those builds return -1. */
int64_t fastpy_os_link(const char *src, const char *dst) {
#ifdef _WIN32
    (void)src; (void)dst;
    return -1;
#else
    return (int64_t)(link(src, dst) == 0 ? 0 : -1);
#endif
}

/* os.chmod(path, mode) -> int status (0 ok, -1 error).  Python's os.chmod
 * returns None and raises on error, but pure/AOT mode surfaces the result as
 * a bare int (mirroring os.remove/os.mkdir).  Only the low permission bits of
 * `mode` apply; the kernel ignores the file-type bits. */
int64_t fastpy_os_chmod(const char *path, int64_t mode) {
#ifdef _WIN32
    (void)path; (void)mode;
    return -1;
#else
    return (int64_t)(chmod(path, (mode_t)mode) == 0 ? 0 : -1);
#endif
}

/* os.truncate(path, length) -> int status (0 ok, -1 error).  Resizes the file
 * to exactly `length` bytes (shrinking discards the tail; growing zero-fills).
 * Pure/AOT mode surfaces the result as a bare int, mirroring os.chmod. */
int64_t fastpy_os_truncate(const char *path, int64_t length) {
#ifdef _WIN32
    (void)path; (void)length;
    return -1;
#else
    return (int64_t)(truncate(path, (off_t)length) == 0 ? 0 : -1);
#endif
}

/* os.utime(path, atime_ns, mtime_ns) -> int status (0 ok, -1 error).  AOT-
 * simplified 3-positional form of os.utime: both times are nanoseconds since
 * the Unix epoch (bare i64), applied via utimensat().  A time of 0 still sets
 * the field to epoch (not "unchanged") — callers pass concrete stamps. */
int64_t fastpy_os_utime(const char *path, int64_t atime_ns, int64_t mtime_ns) {
#ifdef _WIN32
    (void)path; (void)atime_ns; (void)mtime_ns;
    return -1;
#else
    struct timespec times[2];
    times[0].tv_sec = (time_t)(atime_ns / 1000000000);
    times[0].tv_nsec = (long)(atime_ns % 1000000000);
    times[1].tv_sec = (time_t)(mtime_ns / 1000000000);
    times[1].tv_nsec = (long)(mtime_ns % 1000000000);
    return (int64_t)(utimensat(AT_FDCWD, path, times, 0) == 0 ? 0 : -1);
#endif
}

/* os.chown(path, uid, gid) -> int status (0 ok, -1 error).  AOT-simplified
 * 3-positional form: uid/gid as bare ints (Python's os.chown returns None +
 * raises; pure/AOT mode surfaces the result as an int, like os.utime). */
int64_t fastpy_os_chown(const char *path, int64_t uid, int64_t gid) {
#ifdef _WIN32
    (void)path; (void)uid; (void)gid;
    return -1;
#else
    return (int64_t)(chown(path, (uid_t)uid, (gid_t)gid) == 0 ? 0 : -1);
#endif
}

/* os.readlink(path) -> str (the link's target).  Returns a valid FpyString
 * `.data` pointer (FPY_TAG_STR); an empty string signals an error, mirroring
 * how callers already branch on os.getcwd/os.path.* string results.  POSIX
 * readlink() does NOT null-terminate and returns the byte count, so we bound
 * the copy by its return value and let fpy_str_alloc add the terminator. */
const char* fastpy_os_readlink(const char *path) {
#ifdef _WIN32
    (void)path;
    FpyString *empty = fpy_str_alloc(0);
    return empty->data;
#else
    char buf[4096];
    ssize_t n = readlink(path, buf, sizeof(buf));
    if (n < 0) n = 0;
    FpyString *s = fpy_str_alloc((int64_t)n);
    if (n > 0) memcpy(s->data, buf, (size_t)n);
    return s->data;
#endif
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
        /* Headered temp key (refcount 1). fpy_dict_set takes its own reference
           (increfs), so we release our creation reference on every path below.
           See BUG-RUNTIME-STR-PRODUCERS-BARE-MALLOC. */
        key.data.s = fpy_str_from_cstr(buf);
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
                FPY_VAL_DECREF(key);
                break;
            }
            slot = (slot + 1) & mask;
        }
        if (!found) {
            fpy_dict_set(counter, key, fpy_int(1));
            FPY_VAL_DECREF(key);
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

/* Helper: find the index (in keys[]/values[]) of a key, or -1 if absent. */
static int64_t fpy_dict_find_index(FpyDict *dict, FpyValue key) {
    uint64_t h = fpy_hash_value(key);
    int64_t mask = dict->table_size - 1;
    int64_t slot = (int64_t)(h & (uint64_t)mask);
    while (1) {
        int64_t idx = dict->indices[slot];
        if (idx == FPY_DICT_EMPTY) return -1;
        if (idx != FPY_DICT_DELETED && fpy_key_equal(dict->keys[idx], key))
            return idx;
        slot = (slot + 1) & mask;
    }
}

/* --- Counter arithmetic ---
 * Counter + Counter: adds counts, keeps only positive counts
 * Counter - Counter: subtracts counts, keeps only positive counts
 */
FpyDict* fastpy_counter_add(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length + b->length);
    /* Copy all entries from a */
    for (int64_t i = 0; i < a->length; i++) {
        fpy_dict_set(result, a->keys[i], a->values[i]);
    }
    /* Add entries from b */
    for (int64_t i = 0; i < b->length; i++) {
        FpyValue key = b->keys[i];
        int64_t b_count = b->values[i].data.i;
        /* Look up existing count in result */
        int64_t idx = fpy_dict_find_index(result, key);
        if (idx >= 0) {
            result->values[idx].data.i += b_count;
        } else {
            FpyValue val = {.tag = FPY_TAG_INT, .data.i = b_count};
            fpy_dict_set(result, key, val);
        }
    }
    /* Remove non-positive counts (Python Counter keeps only positive) */
    FpyDict *filtered = fpy_dict_new(result->length);
    for (int64_t i = 0; i < result->length; i++) {
        if (result->values[i].data.i > 0) {
            fpy_dict_set(filtered, result->keys[i], result->values[i]);
        }
    }
    return filtered;
}

FpyDict* fastpy_counter_sub(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length);
    /* Copy all entries from a */
    for (int64_t i = 0; i < a->length; i++) {
        fpy_dict_set(result, a->keys[i], a->values[i]);
    }
    /* Subtract entries from b */
    for (int64_t i = 0; i < b->length; i++) {
        FpyValue key = b->keys[i];
        int64_t b_count = b->values[i].data.i;
        int64_t idx = fpy_dict_find_index(result, key);
        if (idx >= 0) {
            result->values[idx].data.i -= b_count;
        } else {
            FpyValue val = {.tag = FPY_TAG_INT, .data.i = -b_count};
            fpy_dict_set(result, key, val);
        }
    }
    /* Remove non-positive counts */
    FpyDict *filtered = fpy_dict_new(result->length);
    for (int64_t i = 0; i < result->length; i++) {
        if (result->values[i].data.i > 0) {
            fpy_dict_set(filtered, result->keys[i], result->values[i]);
        }
    }
    return filtered;
}

/* Counter | Counter: union (max counts) */
FpyDict* fastpy_counter_union(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length + b->length);
    /* Copy all entries from a */
    for (int64_t i = 0; i < a->length; i++) {
        fpy_dict_set(result, a->keys[i], a->values[i]);
    }
    /* Union: take max of each key */
    for (int64_t i = 0; i < b->length; i++) {
        FpyValue key = b->keys[i];
        int64_t b_count = b->values[i].data.i;
        int64_t idx = fpy_dict_find_index(result, key);
        if (idx >= 0) {
            if (b_count > result->values[idx].data.i)
                result->values[idx].data.i = b_count;
        } else {
            FpyValue val = {.tag = FPY_TAG_INT, .data.i = b_count};
            fpy_dict_set(result, key, val);
        }
    }
    return result;
}

/* Counter & Counter: intersection (min counts) */
FpyDict* fastpy_counter_intersection(FpyDict *a, FpyDict *b) {
    FpyDict *result = fpy_dict_new(a->length < b->length ? a->length : b->length);
    for (int64_t i = 0; i < a->length; i++) {
        FpyValue key = a->keys[i];
        int64_t a_count = a->values[i].data.i;
        int64_t idx = fpy_dict_find_index(b, key);
        if (idx >= 0) {
            int64_t b_count = b->values[idx].data.i;
            int64_t min_count = a_count < b_count ? a_count : b_count;
            if (min_count > 0) {
                FpyValue val = {.tag = FPY_TAG_INT, .data.i = min_count};
                fpy_dict_set(result, key, val);
            }
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
    fpy_raise_key_error(k);
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
        else if (args->items[i].tag == FPY_TAG_FLOAT)
            buf_size += 350;  /* %f on extreme doubles can be 300+ chars */
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
