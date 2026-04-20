/*
 * fastpy minimal BigInt implementation.
 *
 * Arbitrary-precision integers stored as sign + array of 64-bit limbs
 * (least-significant first). Supports add, sub, mul, divmod, pow,
 * comparison, and string conversion.
 *
 * Used when i64 arithmetic overflows. The compiler's default mode uses
 * speculative unboxing: fast i64 path, overflow check, BigInt fallback.
 */

#ifndef FASTPY_BIGINT_H
#define FASTPY_BIGINT_H

#include <stdint.h>
#include <stdlib.h>

typedef struct {
    int32_t refcount;     /* for GC */
    int32_t sign;         /* 1 = positive/zero, -1 = negative */
    int32_t length;       /* number of limbs in use */
    int32_t capacity;     /* allocated limbs */
    uint64_t *limbs;      /* least-significant first */
} FpyBigInt;

/* Construction */
FpyBigInt* fpy_bigint_from_i64(int64_t value);
FpyBigInt* fpy_bigint_from_str(const char *s);
FpyBigInt* fpy_bigint_copy(FpyBigInt *a);

/* Conversion */
int64_t fpy_bigint_to_i64(FpyBigInt *a, int *overflow);
const char* fpy_bigint_to_str(FpyBigInt *a);

/* Arithmetic (returns new BigInt) */
FpyBigInt* fpy_bigint_add(FpyBigInt *a, FpyBigInt *b);
FpyBigInt* fpy_bigint_sub(FpyBigInt *a, FpyBigInt *b);
FpyBigInt* fpy_bigint_mul(FpyBigInt *a, FpyBigInt *b);
FpyBigInt* fpy_bigint_floordiv(FpyBigInt *a, FpyBigInt *b);
FpyBigInt* fpy_bigint_mod(FpyBigInt *a, FpyBigInt *b);
FpyBigInt* fpy_bigint_pow(FpyBigInt *base, FpyBigInt *exp);
FpyBigInt* fpy_bigint_neg(FpyBigInt *a);
FpyBigInt* fpy_bigint_abs(FpyBigInt *a);

/* Comparison: returns -1, 0, or 1 */
int fpy_bigint_cmp(FpyBigInt *a, FpyBigInt *b);

/* Predicates */
int fpy_bigint_is_zero(FpyBigInt *a);
int fpy_bigint_fits_i64(FpyBigInt *a);

/* Cleanup */
void fpy_bigint_free(FpyBigInt *a);

/* --- Overflow-checked i64 arithmetic ---
 * These perform i64 arithmetic and return the result. If overflow
 * occurs, they promote to BigInt and return via the BigInt output
 * pointer. The caller checks *big != NULL to detect promotion. */
int64_t fpy_checked_add(int64_t a, int64_t b, FpyBigInt **big);
int64_t fpy_checked_sub(int64_t a, int64_t b, FpyBigInt **big);
int64_t fpy_checked_mul(int64_t a, int64_t b, FpyBigInt **big);
int64_t fpy_checked_pow(int64_t base, int64_t exp, FpyBigInt **big);

#endif /* FASTPY_BIGINT_H */
