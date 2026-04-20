/*
 * fastpy cycle collector.
 *
 * Detects and frees reference cycles that refcounting alone can't handle.
 * Only containers (FpyList, FpyDict, FpyObj) are tracked — scalars and
 * strings can never form cycles.
 *
 * Algorithm (CPython-style):
 * 1. For each tracked object, set gc_refs = refcount
 * 2. For each tracked object, subtract internal references (references
 *    from other tracked objects) from gc_refs
 * 3. Objects with gc_refs > 0 are reachable from outside → roots
 * 4. BFS from roots marks all transitively reachable objects
 * 5. Unmarked objects are unreachable garbage → destroy them
 */

#ifndef FASTPY_GC_H
#define FASTPY_GC_H

#include <stdint.h>

/* GC tracking header — prepended to every tracked object.
 * The object's own struct follows immediately after this header.
 * Uses a doubly-linked list for O(1) insert/remove. */
typedef struct FpyGCNode {
    struct FpyGCNode *gc_prev;
    struct FpyGCNode *gc_next;
    int32_t gc_refs;      /* temporary refcount during collection */
    uint32_t gc_flags;    /* GC state flags */
} FpyGCNode;

#define FPY_GC_TRACKED    0x01
#define FPY_GC_REACHABLE  0x02

/* Track an object for cycle collection. Called by container constructors. */
void fpy_gc_track(FpyGCNode *node);

/* Untrack an object (called before destruction). */
void fpy_gc_untrack(FpyGCNode *node);

/* Run the cycle collector. Returns number of objects freed. */
int64_t fpy_gc_collect(void);

/* Get the number of tracked objects. */
int64_t fpy_gc_tracked_count(void);

/* Auto-collection: call this after allocations. Triggers collection
 * when the allocation count exceeds the threshold. */
void fpy_gc_maybe_collect(void);

#endif /* FASTPY_GC_H */
