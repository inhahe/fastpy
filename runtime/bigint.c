/*
 * fastpy minimal BigInt implementation.
 * Arbitrary-precision integers using base-2^64 limbs.
 */

#include "bigint.h"
#include <stdio.h>
#include <string.h>
#include <limits.h>

#ifdef _MSC_VER
#include <intrin.h>
/* MSVC doesn't have __uint128_t. Use _umul128 for 64x64→128 multiply. */
static void mul128(uint64_t a, uint64_t b, uint64_t *lo, uint64_t *hi) {
    *lo = _umul128(a, b, hi);
}
/* 128-bit division by a small divisor (single uint64_t) */
static uint64_t div128_by_u64(uint64_t hi, uint64_t lo, uint64_t divisor, uint64_t *quotient) {
    /* Use MSVC's _udiv128 if available (VS 2019+), else manual */
#if _MSC_VER >= 1920
    uint64_t rem;
    *quotient = _udiv128(hi, lo, divisor, &rem);
    return rem;
#else
    /* Fallback: iterate bits */
    uint64_t q = 0, r = 0;
    for (int i = 127; i >= 0; i--) {
        r <<= 1;
        if (i >= 64) { r |= (hi >> (i - 64)) & 1; }
        else { r |= (lo >> i) & 1; }
        if (r >= divisor) { r -= divisor; q |= ((uint64_t)1 << i); }
    }
    *quotient = q;
    return r;
#endif
}
#endif

/* ── Internal helpers ────────────────────────────────────────────── */

static FpyBigInt* bigint_alloc(int32_t capacity) {
    FpyBigInt *b = (FpyBigInt*)malloc(sizeof(FpyBigInt));
    b->refcount = 1;
    b->sign = 1;
    b->length = 0;
    b->capacity = capacity < 2 ? 2 : capacity;
    b->limbs = (uint64_t*)calloc(b->capacity, sizeof(uint64_t));
    return b;
}

static void bigint_normalize(FpyBigInt *b) {
    while (b->length > 0 && b->limbs[b->length - 1] == 0)
        b->length--;
    if (b->length == 0) b->sign = 1;  /* zero is positive */
}

static void bigint_ensure_capacity(FpyBigInt *b, int32_t need) {
    if (need > b->capacity) {
        b->capacity = need * 2;
        b->limbs = (uint64_t*)realloc(b->limbs, sizeof(uint64_t) * b->capacity);
        memset(b->limbs + b->length, 0,
               sizeof(uint64_t) * (b->capacity - b->length));
    }
}

/* Unsigned magnitude comparison: returns -1, 0, 1 */
static int mag_cmp(FpyBigInt *a, FpyBigInt *b) {
    if (a->length != b->length)
        return a->length > b->length ? 1 : -1;
    for (int32_t i = a->length - 1; i >= 0; i--) {
        if (a->limbs[i] != b->limbs[i])
            return a->limbs[i] > b->limbs[i] ? 1 : -1;
    }
    return 0;
}

/* Unsigned addition: result = a + b (magnitudes only) */
static FpyBigInt* mag_add(FpyBigInt *a, FpyBigInt *b) {
    int32_t maxlen = a->length > b->length ? a->length : b->length;
    FpyBigInt *r = bigint_alloc(maxlen + 1);
    uint64_t carry = 0;
    for (int32_t i = 0; i < maxlen || carry; i++) {
        uint64_t va = (i < a->length) ? a->limbs[i] : 0;
        uint64_t vb = (i < b->length) ? b->limbs[i] : 0;
        uint64_t sum = va + vb + carry;
        carry = (sum < va || (carry && sum == va)) ? 1 : 0;
        bigint_ensure_capacity(r, i + 1);
        r->limbs[i] = sum;
        r->length = i + 1;
    }
    bigint_normalize(r);
    return r;
}

/* Unsigned subtraction: result = a - b where |a| >= |b| */
static FpyBigInt* mag_sub(FpyBigInt *a, FpyBigInt *b) {
    FpyBigInt *r = bigint_alloc(a->length);
    uint64_t borrow = 0;
    for (int32_t i = 0; i < a->length; i++) {
        uint64_t va = a->limbs[i];
        uint64_t vb = (i < b->length) ? b->limbs[i] : 0;
        uint64_t diff = va - vb - borrow;
        borrow = (va < vb + borrow) ? 1 : 0;
        r->limbs[i] = diff;
        r->length = i + 1;
    }
    bigint_normalize(r);
    return r;
}

/* ── Construction ────────────────────────────────────────────────── */

FpyBigInt* fpy_bigint_from_i64(int64_t value) {
    FpyBigInt *b = bigint_alloc(1);
    if (value < 0) {
        b->sign = -1;
        /* Handle INT64_MIN carefully */
        if (value == INT64_MIN) {
            b->limbs[0] = (uint64_t)INT64_MAX + 1;
        } else {
            b->limbs[0] = (uint64_t)(-value);
        }
    } else {
        b->sign = 1;
        b->limbs[0] = (uint64_t)value;
    }
    b->length = (b->limbs[0] != 0) ? 1 : 0;
    return b;
}

FpyBigInt* fpy_bigint_copy(FpyBigInt *a) {
    FpyBigInt *r = bigint_alloc(a->length);
    r->sign = a->sign;
    r->length = a->length;
    memcpy(r->limbs, a->limbs, sizeof(uint64_t) * a->length);
    return r;
}

/* ── Conversion ──────────────────────────────────────────────────── */

int64_t fpy_bigint_to_i64(FpyBigInt *a, int *overflow) {
    *overflow = 0;
    if (a->length == 0) return 0;
    if (a->length > 1) { *overflow = 1; return 0; }
    uint64_t v = a->limbs[0];
    if (a->sign > 0) {
        if (v > (uint64_t)INT64_MAX) { *overflow = 1; return 0; }
        return (int64_t)v;
    } else {
        if (v > (uint64_t)INT64_MAX + 1) { *overflow = 1; return 0; }
        return -(int64_t)v;
    }
}

int fpy_bigint_fits_i64(FpyBigInt *a) {
    int overflow;
    fpy_bigint_to_i64(a, &overflow);
    return !overflow;
}

const char* fpy_bigint_to_str(FpyBigInt *a) {
    if (a->length == 0) {
        char *s = (char*)malloc(2);
        s[0] = '0'; s[1] = '\0';
        return s;
    }
    /* Simple approach: repeated division by 10 */
    /* Work on a copy */
    FpyBigInt *tmp = fpy_bigint_copy(a);
    tmp->sign = 1;
    char buf[256];  /* enough for ~77 digits per limb */
    int pos = 255;
    buf[pos] = '\0';

    while (tmp->length > 0) {
        /* Divide by 10, get remainder */
        uint64_t rem = 0;
        for (int32_t i = tmp->length - 1; i >= 0; i--) {
#ifdef _MSC_VER
            uint64_t q;
            rem = div128_by_u64(rem, tmp->limbs[i], 10, &q);
            tmp->limbs[i] = q;
#else
            __uint128_t cur = ((__uint128_t)rem << 64) | tmp->limbs[i];
            tmp->limbs[i] = (uint64_t)(cur / 10);
            rem = (uint64_t)(cur % 10);
#endif
        }
        bigint_normalize(tmp);
        buf[--pos] = '0' + (char)rem;
    }

    if (pos == 255) buf[--pos] = '0';
    if (a->sign < 0) buf[--pos] = '-';

    int len = 255 - pos;
    char *result = (char*)malloc(len + 1);
    memcpy(result, buf + pos, len + 1);
    fpy_bigint_free(tmp);
    return result;
}

/* ── Arithmetic ──────────────────────────────────────────────────── */

FpyBigInt* fpy_bigint_add(FpyBigInt *a, FpyBigInt *b) {
    if (a->sign == b->sign) {
        FpyBigInt *r = mag_add(a, b);
        r->sign = a->sign;
        return r;
    }
    /* Different signs: subtract smaller magnitude from larger */
    int cmp = mag_cmp(a, b);
    if (cmp == 0) return fpy_bigint_from_i64(0);
    if (cmp > 0) {
        FpyBigInt *r = mag_sub(a, b);
        r->sign = a->sign;
        return r;
    } else {
        FpyBigInt *r = mag_sub(b, a);
        r->sign = b->sign;
        return r;
    }
}

FpyBigInt* fpy_bigint_sub(FpyBigInt *a, FpyBigInt *b) {
    FpyBigInt nb = *b;
    nb.sign = -b->sign;
    return fpy_bigint_add(a, &nb);
}

FpyBigInt* fpy_bigint_mul(FpyBigInt *a, FpyBigInt *b) {
    int32_t rlen = a->length + b->length;
    FpyBigInt *r = bigint_alloc(rlen);
    r->length = rlen;
    for (int32_t i = 0; i < a->length; i++) {
        uint64_t carry = 0;
        for (int32_t j = 0; j < b->length || carry; j++) {
#ifdef _MSC_VER
            uint64_t lo, hi;
            if (j < b->length) {
                mul128(a->limbs[i], b->limbs[j], &lo, &hi);
                /* Add existing value + carry */
                uint64_t sum = r->limbs[i + j] + lo;
                uint64_t c1 = (sum < lo) ? 1 : 0;
                sum += carry;
                c1 += (sum < carry) ? 1 : 0;
                r->limbs[i + j] = sum;
                carry = hi + c1;
            } else {
                uint64_t sum = r->limbs[i + j] + carry;
                uint64_t c1 = (sum < carry) ? 1 : 0;
                r->limbs[i + j] = sum;
                carry = c1;
            }
#else
            __uint128_t cur = (__uint128_t)r->limbs[i + j] + carry;
            if (j < b->length)
                cur += (__uint128_t)a->limbs[i] * b->limbs[j];
            r->limbs[i + j] = (uint64_t)cur;
            carry = (uint64_t)(cur >> 64);
#endif
        }
    }
    r->sign = a->sign * b->sign;
    bigint_normalize(r);
    return r;
}

FpyBigInt* fpy_bigint_neg(FpyBigInt *a) {
    FpyBigInt *r = fpy_bigint_copy(a);
    if (r->length > 0) r->sign = -r->sign;
    return r;
}

FpyBigInt* fpy_bigint_abs(FpyBigInt *a) {
    FpyBigInt *r = fpy_bigint_copy(a);
    r->sign = 1;
    return r;
}

/* Simple power by repeated squaring */
FpyBigInt* fpy_bigint_pow(FpyBigInt *base, FpyBigInt *exp) {
    if (exp->sign < 0) {
        /* Negative exponent → 0 for integers (would be fraction) */
        return fpy_bigint_from_i64(0);
    }
    FpyBigInt *result = fpy_bigint_from_i64(1);
    FpyBigInt *b = fpy_bigint_copy(base);
    FpyBigInt *e = fpy_bigint_copy(exp);

    while (!fpy_bigint_is_zero(e)) {
        /* Check if e is odd (lowest bit of lowest limb) */
        if (e->length > 0 && (e->limbs[0] & 1)) {
            FpyBigInt *tmp = fpy_bigint_mul(result, b);
            fpy_bigint_free(result);
            result = tmp;
        }
        /* b = b * b */
        FpyBigInt *tmp = fpy_bigint_mul(b, b);
        fpy_bigint_free(b);
        b = tmp;
        /* e = e >> 1 (shift right by 1) */
        uint64_t carry = 0;
        for (int32_t i = e->length - 1; i >= 0; i--) {
            uint64_t new_carry = e->limbs[i] & 1;
            e->limbs[i] = (e->limbs[i] >> 1) | (carry << 63);
            carry = new_carry;
        }
        bigint_normalize(e);
    }
    /* Fix sign: negative base with odd exponent → negative */
    if (base->sign < 0) {
        int overflow;
        int64_t exp_val = fpy_bigint_to_i64(exp, &overflow);
        if (!overflow && (exp_val & 1))
            result->sign = -1;
    }
    fpy_bigint_free(b);
    fpy_bigint_free(e);
    return result;
}

/* Floor division and modulo — simple long division */
FpyBigInt* fpy_bigint_floordiv(FpyBigInt *a, FpyBigInt *b) {
    if (fpy_bigint_is_zero(b)) {
        fprintf(stderr, "ZeroDivisionError: integer division or modulo by zero\n");
        exit(1);
    }
    /* Simple case: single limb */
    if (a->length <= 1 && b->length <= 1) {
        int64_t va = a->sign * (int64_t)a->limbs[0];
        int64_t vb = b->sign * (int64_t)b->limbs[0];
        /* Python floor division */
        int64_t q = va / vb;
        if ((va % vb != 0) && ((va ^ vb) < 0)) q--;
        return fpy_bigint_from_i64(q);
    }
    /* For larger values, use the i64 path if possible */
    int ov1, ov2;
    int64_t va = fpy_bigint_to_i64(a, &ov1);
    int64_t vb = fpy_bigint_to_i64(b, &ov2);
    if (!ov1 && !ov2) {
        int64_t q = va / vb;
        if ((va % vb != 0) && ((va ^ vb) < 0)) q--;
        return fpy_bigint_from_i64(q);
    }
    /* TODO: full multi-limb division for very large numbers */
    return fpy_bigint_from_i64(0);
}

FpyBigInt* fpy_bigint_mod(FpyBigInt *a, FpyBigInt *b) {
    FpyBigInt *q = fpy_bigint_floordiv(a, b);
    FpyBigInt *qb = fpy_bigint_mul(q, b);
    FpyBigInt *r = fpy_bigint_sub(a, qb);
    fpy_bigint_free(q);
    fpy_bigint_free(qb);
    return r;
}

/* ── Comparison ──────────────────────────────────────────────────── */

int fpy_bigint_cmp(FpyBigInt *a, FpyBigInt *b) {
    if (a->sign != b->sign)
        return a->sign > b->sign ? 1 : -1;
    int mc = mag_cmp(a, b);
    return a->sign > 0 ? mc : -mc;
}

int fpy_bigint_is_zero(FpyBigInt *a) {
    return a->length == 0;
}

/* ── Cleanup ─────────────────────────────────────────────────────── */

void fpy_bigint_free(FpyBigInt *a) {
    if (!a) return;
    free(a->limbs);
    free(a);
}

/* ── Overflow-checked i64 arithmetic ─────────────────────────────── */

int64_t fpy_checked_add(int64_t a, int64_t b, FpyBigInt **big) {
    *big = NULL;
    int64_t result = a + b;
    /* Overflow: signs are same but result sign differs */
    if (((a ^ result) & (b ^ result)) < 0) {
        FpyBigInt *ba = fpy_bigint_from_i64(a);
        FpyBigInt *bb = fpy_bigint_from_i64(b);
        *big = fpy_bigint_add(ba, bb);
        fpy_bigint_free(ba);
        fpy_bigint_free(bb);
        return 0;
    }
    return result;
}

int64_t fpy_checked_sub(int64_t a, int64_t b, FpyBigInt **big) {
    *big = NULL;
    int64_t result = a - b;
    if (((a ^ b) & (a ^ result)) < 0) {
        FpyBigInt *ba = fpy_bigint_from_i64(a);
        FpyBigInt *bb = fpy_bigint_from_i64(b);
        *big = fpy_bigint_sub(ba, bb);
        fpy_bigint_free(ba);
        fpy_bigint_free(bb);
        return 0;
    }
    return result;
}

int64_t fpy_checked_mul(int64_t a, int64_t b, FpyBigInt **big) {
    *big = NULL;
    /* Detect overflow using 128-bit multiply */
#ifdef _MSC_VER
    int64_t hi;
    int64_t lo = _mul128(a, b, &hi);
    /* Overflow if hi is not the sign extension of lo */
    int overflow = (hi != (lo >> 63));
    if (overflow) {
#else
    __int128 result128 = (__int128)a * b;
    int overflow = (result128 > INT64_MAX || result128 < INT64_MIN);
    int64_t lo = (int64_t)result128;
    if (overflow) {
#endif
        FpyBigInt *ba = fpy_bigint_from_i64(a);
        FpyBigInt *bb = fpy_bigint_from_i64(b);
        *big = fpy_bigint_mul(ba, bb);
        fpy_bigint_free(ba);
        fpy_bigint_free(bb);
        return 0;
    }
    return lo;
}

int64_t fpy_checked_pow(int64_t base, int64_t exp, FpyBigInt **big) {
    *big = NULL;
    if (exp < 0) return 0;  /* integer negative power → 0 */
    if (exp == 0) return 1;
    if (base == 0) return 0;
    if (base == 1) return 1;
    if (base == -1) return (exp & 1) ? -1 : 1;

    /* For large exponents, go straight to BigInt */
    if (exp > 62 || (exp > 40 && (base > 2 || base < -2))) {
        FpyBigInt *bb = fpy_bigint_from_i64(base);
        FpyBigInt *be = fpy_bigint_from_i64(exp);
        *big = fpy_bigint_pow(bb, be);
        fpy_bigint_free(bb);
        fpy_bigint_free(be);
        return 0;
    }

    /* Try i64 with overflow checks */
    int64_t result = 1;
    int64_t b = base;
    int64_t e = exp;
    while (e > 0) {
        if (e & 1) {
            FpyBigInt *tmp = NULL;
            result = fpy_checked_mul(result, b, &tmp);
            if (tmp) {
                /* Overflow — finish in BigInt */
                FpyBigInt *br = tmp;
                FpyBigInt *bb = fpy_bigint_from_i64(b);
                e >>= 1;
                while (e > 0) {
                    FpyBigInt *sq = fpy_bigint_mul(bb, bb);
                    fpy_bigint_free(bb);
                    bb = sq;
                    if (e & 1) {
                        FpyBigInt *t = fpy_bigint_mul(br, bb);
                        fpy_bigint_free(br);
                        br = t;
                    }
                    e >>= 1;
                }
                fpy_bigint_free(bb);
                *big = br;
                return 0;
            }
        }
        FpyBigInt *tmp = NULL;
        b = fpy_checked_mul(b, b, &tmp);
        if (tmp) {
            /* Base squared overflowed — finish in BigInt */
            FpyBigInt *bb = tmp;
            FpyBigInt *br = fpy_bigint_from_i64(result);
            e >>= 1;
            while (e > 0) {
                if (e & 1) {
                    FpyBigInt *t = fpy_bigint_mul(br, bb);
                    fpy_bigint_free(br);
                    br = t;
                }
                FpyBigInt *sq = fpy_bigint_mul(bb, bb);
                fpy_bigint_free(bb);
                bb = sq;
                e >>= 1;
            }
            fpy_bigint_free(bb);
            *big = br;
            return 0;
        }
        e >>= 1;
    }
    return result;
}
