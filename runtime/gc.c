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
static int64_t gc_threshold = 700;  /* collect after this many allocations */

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

/* ── Internal reference subtraction ──────────────────────────────── */

/* Subtract 1 from the gc_refs of a referenced tracked object.
 * Called for each outgoing reference from a tracked container. */
static void gc_subtract_ref(FpyValue val) {
    void *ptr = NULL;
    switch (val.tag) {
        case FPY_TAG_LIST: case FPY_TAG_SET:
            ptr = val.data.list; break;
        case FPY_TAG_DICT:
            ptr = val.data.list; break;  /* dict stored in list union member */
        case FPY_TAG_OBJ:
            if (val.data.obj && val.data.obj->magic == FPY_OBJ_MAGIC)
                ptr = val.data.obj;
            break;
        default: return;  /* scalars/strings don't participate in cycles */
    }
    if (!ptr) return;
    /* The GC node is stored in the gc_node field — but we don't have
     * that field yet. For now, we skip cycle collection on objects
     * that don't have GC nodes. This will be connected in a future pass
     * when GC nodes are added to FpyList/FpyDict/FpyObj structs. */
}

/* ── Collection ──────────────────────────────────────────────────── */

int64_t fpy_gc_collect(void) {
    /* Phase 1: Copy refcounts to gc_refs */
    FpyGCNode *node;
    for (node = gc_sentinel.gc_next; node != &gc_sentinel; node = node->gc_next) {
        node->gc_refs = 0;  /* will be set from the object's refcount */
        node->gc_flags &= ~FPY_GC_REACHABLE;
    }

    /* TODO: Phase 2-5 — subtract internal refs, find roots, mark, sweep.
     * For now this is a skeleton that tracks objects but doesn't collect.
     * The full algorithm requires adding FpyGCNode to FpyList/FpyDict/FpyObj
     * and connecting the subtract/mark/sweep logic. */

    return 0;  /* nothing collected yet */
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
        fpy_gc_collect();
    }
}
