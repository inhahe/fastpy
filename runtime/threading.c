/*
 * fastpy threading runtime — GIL and synchronization primitives.
 */

#include "threading.h"
#include <stdio.h>

/* ── Global threading mode ───────────────────────────────────────── */

/* Threading mode is defined by the LLVM codegen (in the compiled output.obj).
 * The C runtime only has the extern declaration (in threading.h). */

/* ── GIL state ───────────────────────────────────────────────────── */

static fpy_mutex_t fpy_gil_mutex;
static fpy_cond_t fpy_gil_cond;
static volatile int32_t fpy_gil_locked = 0;
static volatile uint64_t fpy_gil_owner = 0;

void fpy_gil_init(void) {
    fpy_mutex_init(&fpy_gil_mutex);
    fpy_cond_init(&fpy_gil_cond);
    fpy_gil_locked = 0;
    fpy_gil_owner = 0;
}

void fpy_gil_acquire(void) {
    if (fpy_threading_mode == FPY_THREADING_NONE) return;
    uint64_t me = fpy_thread_id();
    /* Re-entrant: if we already hold it, just return. */
    if (fpy_gil_locked && fpy_gil_owner == me) return;
    fpy_mutex_lock(&fpy_gil_mutex);
    while (fpy_gil_locked) {
        fpy_cond_wait(&fpy_gil_cond, &fpy_gil_mutex);
    }
    fpy_gil_locked = 1;
    fpy_gil_owner = me;
    fpy_mutex_unlock(&fpy_gil_mutex);
}

void fpy_gil_release(void) {
    if (fpy_threading_mode == FPY_THREADING_NONE) return;
    fpy_mutex_lock(&fpy_gil_mutex);
    fpy_gil_locked = 0;
    fpy_gil_owner = 0;
    fpy_cond_signal(&fpy_gil_cond);
    fpy_mutex_unlock(&fpy_gil_mutex);
}

int fpy_gil_held(void) {
    return fpy_gil_locked && fpy_gil_owner == fpy_thread_id();
}

/* ── Print mutex ─────────────────────────────────────────────────── */

fpy_mutex_t fpy_print_mutex;
int fpy_print_mutex_initialized = 0;

void fpy_print_mutex_init(void) {
    fpy_mutex_init(&fpy_print_mutex);
    fpy_print_mutex_initialized = 1;
}
