/*
 * fastpy cycle collector — detects and frees circular references.
 *
 * Uses CPython's algorithm: subtract internal references, then BFS
 * from roots to find unreachable objects.
 */

#include "gc.h"
#include "objects.h"
#include "threading.h"
#include <stdio.h>
#include <stdlib.h>

/* ── Tracked object list ─────────────────────────────────────────── */

/* Sentinel node — head of the doubly-linked tracked list */
static FpyGCNode gc_sentinel = { &gc_sentinel, &gc_sentinel, 0, 0 };
static int64_t gc_tracked = 0;
static int64_t gc_alloc_count = 0;
static int64_t gc_threshold = 700;

void fpy_gc_track(FpyGCNode *node) {
    node->gc_flags |= FPY_GC_TRACKED;
    /* Insert at the tail of the list (before sentinel) */
    node->gc_prev = gc_sentinel.gc_prev;
    node->gc_next = &gc_sentinel;
    gc_sentinel.gc_prev->gc_next = node;
    gc_sentinel.gc_prev = node;
    gc_tracked++;
}

void fpy_gc_untrack(FpyGCNode *node) {
    if (!(node->gc_flags & FPY_GC_TRACKED)) return;
    node->gc_prev->gc_next = node->gc_next;
    node->gc_next->gc_prev = node->gc_prev;
    node->gc_prev = NULL;
    node->gc_next = NULL;
    node->gc_flags &= ~FPY_GC_TRACKED;
    gc_tracked--;
}

int64_t fpy_gc_tracked_count(void) {
    return gc_tracked;
}

/* ── Container ↔ GC node conversion ──────────────────────────────── */

/* Get the container pointer from a GC node, based on gc_type */
static void* gc_node_to_container(FpyGCNode *node) {
    switch (node->gc_type) {
        case FPY_GC_TYPE_LIST:
            return (char*)node - offsetof(FpyList, gc_node);
        case FPY_GC_TYPE_DICT:
            return (char*)node - offsetof(FpyDict, gc_node);
        case FPY_GC_TYPE_OBJ:
            return (char*)node - offsetof(FpyObj, gc_node);
        default: return NULL;
    }
}

/* Get refcount from a GC node */
static int32_t gc_get_refcount(FpyGCNode *node) {
    switch (node->gc_type) {
        case FPY_GC_TYPE_LIST: {
            FpyList *l = (FpyList*)gc_node_to_container(node);
            return l->refcount;
        }
        case FPY_GC_TYPE_DICT: {
            FpyDict *d = (FpyDict*)gc_node_to_container(node);
            return d->refcount;
        }
        case FPY_GC_TYPE_OBJ: {
            FpyObj *o = (FpyObj*)gc_node_to_container(node);
            return o->refcount;
        }
        default: return FPY_RC_IMMORTAL;
    }
}

/* Get a GC node from an FpyValue (if the value is a tracked container) */
static FpyGCNode* gc_node_from_value(FpyValue val) {
    switch (val.tag) {
        case FPY_TAG_LIST: case FPY_TAG_SET:
            if (val.data.list) return &val.data.list->gc_node;
            break;
        case FPY_TAG_DICT:
            if (val.data.list) return &((FpyDict*)(val.data.list))->gc_node;
            break;
        case FPY_TAG_OBJ:
            if (val.data.obj && val.data.obj->magic == FPY_OBJ_MAGIC)
                return &val.data.obj->gc_node;
            break;
        default: break;
    }
    return NULL;
}

/* ── Visit outgoing references ───────────────────────────────────── */

/* For each outgoing reference in a container that points to a tracked
 * object, call the visitor function. Used for both subtract and mark. */
typedef void (*gc_visitor_fn)(FpyGCNode *referent);

static void gc_visit_refs(FpyGCNode *node, gc_visitor_fn visitor) {
    void *container = gc_node_to_container(node);
    if (!container) return;

    switch (node->gc_type) {
        case FPY_GC_TYPE_LIST: {
            FpyList *list = (FpyList*)container;
            for (int64_t i = 0; i < list->length; i++) {
                FpyGCNode *ref = gc_node_from_value(list->items[i]);
                if (ref && (ref->gc_flags & FPY_GC_TRACKED))
                    visitor(ref);
            }
            break;
        }
        case FPY_GC_TYPE_DICT: {
            FpyDict *dict = (FpyDict*)container;
            for (int64_t i = 0; i < dict->length; i++) {
                FpyGCNode *ref;
                ref = gc_node_from_value(dict->keys[i]);
                if (ref && (ref->gc_flags & FPY_GC_TRACKED))
                    visitor(ref);
                ref = gc_node_from_value(dict->values[i]);
                if (ref && (ref->gc_flags & FPY_GC_TRACKED))
                    visitor(ref);
            }
            break;
        }
        case FPY_GC_TYPE_OBJ: {
            FpyObj *obj = (FpyObj*)container;
            if (obj->slots) {
                extern FpyClassDef fpy_classes[];
                int sc = fpy_classes[obj->class_id].slot_count;
                for (int i = 0; i < sc; i++) {
                    FpyGCNode *ref = gc_node_from_value(obj->slots[i]);
                    if (ref && (ref->gc_flags & FPY_GC_TRACKED))
                        visitor(ref);
                }
            }
            break;
        }
    }
}

/* ── Visitor callbacks ───────────────────────────────────────────── */

static void gc_subtract_one(FpyGCNode *ref) {
    ref->gc_refs--;
}

static void gc_mark_reachable(FpyGCNode *ref) {
    if (ref->gc_flags & FPY_GC_REACHABLE) return;  /* already visited */
    ref->gc_flags |= FPY_GC_REACHABLE;
    /* Recursively mark all objects reachable from this one */
    gc_visit_refs(ref, gc_mark_reachable);
}

/* ── Collection ──────────────────────────────────────────────────── */

int64_t fpy_gc_collect(void) {
    if (gc_tracked == 0) return 0;

    FpyGCNode *node, *next;

    /* Phase 1: Copy refcounts to gc_refs, clear reachable flag */
    for (node = gc_sentinel.gc_next; node != &gc_sentinel; node = node->gc_next) {
        int32_t rc = gc_get_refcount(node);
        if (rc == FPY_RC_IMMORTAL) {
            node->gc_refs = FPY_RC_IMMORTAL;
            node->gc_flags |= FPY_GC_REACHABLE;  /* immortals are always roots */
        } else {
            node->gc_refs = rc;
            node->gc_flags &= ~FPY_GC_REACHABLE;
        }
    }

    /* Phase 2: Subtract internal references.
     * For each tracked object, for each outgoing reference to another
     * tracked object, decrement the referent's gc_refs. After this,
     * gc_refs reflects only EXTERNAL references. */
    for (node = gc_sentinel.gc_next; node != &gc_sentinel; node = node->gc_next) {
        gc_visit_refs(node, gc_subtract_one);
    }

    /* Phase 3: Find roots — objects with gc_refs > 0 are reachable
     * from outside the tracked set. Mark them and their transitive
     * references as reachable. */
    for (node = gc_sentinel.gc_next; node != &gc_sentinel; node = node->gc_next) {
        if (node->gc_refs > 0 && !(node->gc_flags & FPY_GC_REACHABLE)) {
            node->gc_flags |= FPY_GC_REACHABLE;
            gc_visit_refs(node, gc_mark_reachable);
        }
    }

    /* Phase 4: Sweep — destroy unreachable objects.
     * We must be careful: destroying an object may untrack it (modifying
     * the list), so we collect pointers first, then destroy. */
    int64_t freed = 0;

    /* Count unreachable objects */
    int64_t unreachable_count = 0;
    for (node = gc_sentinel.gc_next; node != &gc_sentinel; node = node->gc_next) {
        if (!(node->gc_flags & FPY_GC_REACHABLE))
            unreachable_count++;
    }

    if (unreachable_count == 0) return 0;

    /* Collect unreachable nodes into an array */
    FpyGCNode **to_free = (FpyGCNode**)malloc(sizeof(FpyGCNode*) * unreachable_count);
    int64_t idx = 0;
    for (node = gc_sentinel.gc_next; node != &gc_sentinel; node = node->gc_next) {
        if (!(node->gc_flags & FPY_GC_REACHABLE))
            to_free[idx++] = node;
    }

    /* Destroy each unreachable object */
    for (int64_t i = 0; i < idx; i++) {
        node = to_free[i];
        /* Set refcount to 0 so fpy_rc_decref triggers destruction */
        void *container = gc_node_to_container(node);
        if (!container) continue;
        switch (node->gc_type) {
            case FPY_GC_TYPE_LIST:
                ((FpyList*)container)->refcount = 1;
                fpy_rc_decref(FPY_TAG_LIST, (int64_t)(intptr_t)container);
                break;
            case FPY_GC_TYPE_DICT:
                ((FpyDict*)container)->refcount = 1;
                fpy_rc_decref(FPY_TAG_DICT, (int64_t)(intptr_t)container);
                break;
            case FPY_GC_TYPE_OBJ:
                ((FpyObj*)container)->refcount = 1;
                fpy_rc_decref(FPY_TAG_OBJ, (int64_t)(intptr_t)container);
                break;
        }
        freed++;
    }

    free(to_free);
    return freed;
}

/* Final sweep: destroy ALL tracked objects regardless of refcount.
 * Called at program exit to ensure destructors run (e.g., generator
 * finally blocks). Only objects with destructors are actually called —
 * others are left for the OS to reclaim with process memory. */
void fpy_gc_finalize(void) {
    extern FpyClassDef fpy_classes[];
    extern int fpy_class_count;
    FpyGCNode *node = gc_sentinel.gc_next;
    while (node != &gc_sentinel) {
        FpyGCNode *next = node->gc_next;
        if (node->gc_type == FPY_GC_TYPE_OBJ) {
            /* Recover the FpyObj and check for destructor */
            FpyObj *obj = (FpyObj*)((char*)node - offsetof(FpyObj, gc_node));
            if (obj->magic == FPY_OBJ_MAGIC &&
                obj->class_id >= 0 && obj->class_id < fpy_class_count) {
                void (*dtor)(FpyObj*) = fpy_classes[obj->class_id].destructor;
                if (dtor) {
                    dtor(obj);
                }
            }
        }
        node = next;
    }
}

/* ── Atomic refcount operations (free-threaded mode) ────────────── */

void fpy_incref_atomic(int32_t *rc) {
    if (*rc == FPY_RC_IMMORTAL) return;
#ifdef FPY_WINDOWS
    _InterlockedIncrement((volatile long *)rc);
#else
    __atomic_add_fetch(rc, 1, __ATOMIC_SEQ_CST);
#endif
}

int fpy_decref_atomic(int32_t *rc) {
    if (*rc == FPY_RC_IMMORTAL) return 0;
#ifdef FPY_WINDOWS
    return (_InterlockedDecrement((volatile long *)rc) == 0);
#else
    return (__atomic_sub_fetch(rc, 1, __ATOMIC_SEQ_CST) == 0);
#endif
}

void fpy_gc_maybe_collect(void) {
    gc_alloc_count++;
    if (gc_alloc_count >= gc_threshold) {
        gc_alloc_count = 0;
        int64_t freed = fpy_gc_collect();
        /* Adaptive threshold: if the GC scan found nothing to free,
         * double the threshold so we don't keep re-scanning a stable
         * working set.  This prevents O(n²) when many long-lived objects
         * exist (e.g. 100K Point objects).  Cap at 50K to ensure cycles
         * are eventually detected.  When objects ARE freed, shrink back
         * toward the base threshold to stay responsive. */
        if (freed == 0 && gc_threshold < 50000) {
            gc_threshold *= 2;
        } else if (freed > 0 && gc_threshold > 700) {
            gc_threshold = (gc_threshold > 1400) ? gc_threshold / 2 : 700;
        }
    }
}
