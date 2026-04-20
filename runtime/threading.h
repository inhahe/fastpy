/*
 * fastpy threading support.
 *
 * Provides platform-abstracted primitives for:
 * - Thread-local storage (FPY_THREAD_LOCAL)
 * - Mutexes (fpy_mutex_t)
 * - Condition variables (fpy_cond_t)
 * - Atomic operations
 * - GIL (Global Interpreter Lock)
 *
 * Threading modes:
 *   0 = single-threaded (no locks, no TLS overhead)
 *   1 = GIL mode (one thread runs compiled code at a time)
 *   2 = free-threaded (per-object locking, true parallelism)
 */

#ifndef FASTPY_THREADING_H
#define FASTPY_THREADING_H

#include <stdint.h>

/* ── Platform detection ──────────────────────────────────────────── */

#ifdef _WIN32
#define FPY_WINDOWS 1
#define FPY_THREAD_LOCAL __declspec(thread)
#include <windows.h>
#else
#define FPY_POSIX 1
#define FPY_THREAD_LOCAL __thread
#include <pthread.h>
#endif

/* ── Threading mode ──────────────────────────────────────────────── */

#define FPY_THREADING_NONE          0
#define FPY_THREADING_GIL           1
#define FPY_THREADING_FREE          2

extern int fpy_threading_mode;

/* ── Mutex ───────────────────────────────────────────────────────── */

#ifdef FPY_WINDOWS

typedef CRITICAL_SECTION fpy_mutex_t;

static inline void fpy_mutex_init(fpy_mutex_t *m) {
    InitializeCriticalSection(m);
}
static inline void fpy_mutex_lock(fpy_mutex_t *m) {
    EnterCriticalSection(m);
}
static inline void fpy_mutex_unlock(fpy_mutex_t *m) {
    LeaveCriticalSection(m);
}
static inline void fpy_mutex_destroy(fpy_mutex_t *m) {
    DeleteCriticalSection(m);
}

#else /* POSIX */

typedef pthread_mutex_t fpy_mutex_t;

static inline void fpy_mutex_init(fpy_mutex_t *m) {
    pthread_mutex_init(m, NULL);
}
static inline void fpy_mutex_lock(fpy_mutex_t *m) {
    pthread_mutex_lock(m);
}
static inline void fpy_mutex_unlock(fpy_mutex_t *m) {
    pthread_mutex_unlock(m);
}
static inline void fpy_mutex_destroy(fpy_mutex_t *m) {
    pthread_mutex_destroy(m);
}

#endif

/* ── Condition variable ──────────────────────────────────────────── */

#ifdef FPY_WINDOWS

typedef CONDITION_VARIABLE fpy_cond_t;

static inline void fpy_cond_init(fpy_cond_t *c) {
    InitializeConditionVariable(c);
}
static inline void fpy_cond_wait(fpy_cond_t *c, fpy_mutex_t *m) {
    SleepConditionVariableCS(c, m, INFINITE);
}
static inline void fpy_cond_signal(fpy_cond_t *c) {
    WakeConditionVariable(c);
}
static inline void fpy_cond_broadcast(fpy_cond_t *c) {
    WakeAllConditionVariable(c);
}

#else /* POSIX */

typedef pthread_cond_t fpy_cond_t;

static inline void fpy_cond_init(fpy_cond_t *c) {
    pthread_cond_init(c, NULL);
}
static inline void fpy_cond_wait(fpy_cond_t *c, fpy_mutex_t *m) {
    pthread_cond_wait(c, m);
}
static inline void fpy_cond_signal(fpy_cond_t *c) {
    pthread_cond_signal(c);
}
static inline void fpy_cond_broadcast(fpy_cond_t *c) {
    pthread_cond_broadcast(c);
}

#endif

/* ── Thread ID ───────────────────────────────────────────────────── */

static inline uint64_t fpy_thread_id(void) {
#ifdef FPY_WINDOWS
    return (uint64_t)GetCurrentThreadId();
#else
    return (uint64_t)pthread_self();
#endif
}

/* ── Atomics ─────────────────────────────────────────────────────── */

#ifdef FPY_WINDOWS
#include <intrin.h>

static inline int32_t fpy_atomic_load_i32(volatile int32_t *p) {
    return _InterlockedOr((volatile long *)p, 0);
}
static inline void fpy_atomic_store_i32(volatile int32_t *p, int32_t v) {
    _InterlockedExchange((volatile long *)p, v);
}
static inline int32_t fpy_atomic_cas_i32(volatile int32_t *p, int32_t expected, int32_t desired) {
    return _InterlockedCompareExchange((volatile long *)p, desired, expected);
}

#else /* GCC/Clang */

static inline int32_t fpy_atomic_load_i32(volatile int32_t *p) {
    return __atomic_load_n(p, __ATOMIC_SEQ_CST);
}
static inline void fpy_atomic_store_i32(volatile int32_t *p, int32_t v) {
    __atomic_store_n(p, v, __ATOMIC_SEQ_CST);
}
static inline int32_t fpy_atomic_cas_i32(volatile int32_t *p, int32_t expected, int32_t desired) {
    __atomic_compare_exchange_n(p, &expected, desired, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST);
    return expected;
}

#endif

/* ── GIL ─────────────────────────────────────────────────────────── */

void fpy_gil_init(void);
void fpy_gil_acquire(void);
void fpy_gil_release(void);
int  fpy_gil_held(void);

/* ── Lock macros for container operations ────────────────────────── */

/* These are no-ops unless free-threaded mode is active. The branch on
 * fpy_threading_mode is well-predicted (constant after startup). */
#define FPY_LOCK(obj)   do { if (fpy_threading_mode == FPY_THREADING_FREE) fpy_mutex_lock(&(obj)->lock); } while(0)
#define FPY_UNLOCK(obj) do { if (fpy_threading_mode == FPY_THREADING_FREE) fpy_mutex_unlock(&(obj)->lock); } while(0)

/* Print mutex — serializes print() calls across threads */
extern fpy_mutex_t fpy_print_mutex;
extern int fpy_print_mutex_initialized;

static inline void fpy_print_lock(void) {
    if (fpy_threading_mode >= FPY_THREADING_GIL && fpy_print_mutex_initialized)
        fpy_mutex_lock(&fpy_print_mutex);
}
static inline void fpy_print_unlock(void) {
    if (fpy_threading_mode >= FPY_THREADING_GIL && fpy_print_mutex_initialized)
        fpy_mutex_unlock(&fpy_print_mutex);
}

#endif /* FASTPY_THREADING_H */
