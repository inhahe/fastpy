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

FpyBigInt* fpy_bigint_from_str(const char *s) {
    if (!s || *s == '\0') return fpy_bigint_from_i64(0);
    int sign = 1;
    if (*s == '-') { sign = -1; s++; }
    else if (*s == '+') { s++; }

    FpyBigInt *result = fpy_bigint_from_i64(0);
    FpyBigInt *ten = fpy_bigint_from_i64(10);

    while (*s >= '0' && *s <= '9') {
        FpyBigInt *tmp = fpy_bigint_mul(result, ten);
        fpy_bigint_free(result);
        FpyBigInt *digit = fpy_bigint_from_i64(*s - '0');
        result = fpy_bigint_add(tmp, digit);
        fpy_bigint_free(tmp);
        fpy_bigint_free(digit);
        s++;
    }
    fpy_bigint_free(ten);
    result->sign = sign;
    bigint_normalize(result);
    return result;
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

/* Unsigned single-limb division: q = |a| / d, returns remainder.
 * a's limbs are divided in-place into q's limbs. */
static uint64_t mag_divmod_single(FpyBigInt *a, uint64_t d,
                                   FpyBigInt *q) {
    uint64_t rem = 0;
    q->length = a->length;
    bigint_ensure_capacity(q, a->length);
    for (int32_t i = a->length - 1; i >= 0; i--) {
#ifdef _MSC_VER
        uint64_t quot;
        rem = div128_by_u64(rem, a->limbs[i], d, &quot);
        q->limbs[i] = quot;
#else
        __uint128_t cur = ((__uint128_t)rem << 64) | a->limbs[i];
        q->limbs[i] = (uint64_t)(cur / d);
        rem = (uint64_t)(cur % d);
#endif
    }
    bigint_normalize(q);
    return rem;
}

/* Unsigned multi-limb division: compute |a| / |b| using schoolbook
 * algorithm (Knuth Algorithm D, simplified).  Returns quotient;
 * remainder is written to *rem_out if non-NULL. */
static FpyBigInt* mag_divmod(FpyBigInt *a, FpyBigInt *b,
                              FpyBigInt **rem_out) {
    int cmp = mag_cmp(a, b);
    if (cmp < 0) {
        /* |a| < |b| → quotient=0, remainder=a */
        if (rem_out) {
            FpyBigInt *r = bigint_alloc(a->length);
            memcpy(r->limbs, a->limbs, a->length * sizeof(uint64_t));
            r->length = a->length;
            bigint_normalize(r);
            *rem_out = r;
        }
        return fpy_bigint_from_i64(0);
    }
    if (cmp == 0) {
        /* |a| == |b| → quotient=1, remainder=0 */
        if (rem_out) *rem_out = fpy_bigint_from_i64(0);
        return fpy_bigint_from_i64(1);
    }
    /* Single-limb divisor: fast path */
    if (b->length == 1) {
        FpyBigInt *q = bigint_alloc(a->length);
        uint64_t r = mag_divmod_single(a, b->limbs[0], q);
        if (rem_out) *rem_out = fpy_bigint_from_i64((int64_t)r);
        return q;
    }
    /* Multi-limb divisor: binary long division on full BigInt.
     * Uses repeated doubling of divisor and subtraction.
     * Not the fastest, but correct for any size. */
    FpyBigInt *remainder = bigint_alloc(a->length);
    memcpy(remainder->limbs, a->limbs, a->length * sizeof(uint64_t));
    remainder->length = a->length;
    remainder->sign = 1;

    FpyBigInt *quotient = fpy_bigint_from_i64(0);

    /* Find highest bit of remainder */
    int total_bits = (int)(a->length) * 64;
    while (total_bits > 0) {
        int top_limb_idx = (total_bits - 1) / 64;
        int top_bit = (total_bits - 1) % 64;
        if (top_limb_idx < remainder->length &&
            (remainder->limbs[top_limb_idx] >> top_bit) & 1) break;
        total_bits--;
    }

    /* Process each bit from high to low */
    for (int bit = total_bits - 1; bit >= 0; bit--) {
        /* Left-shift quotient by 1 */
        uint64_t carry = 0;
        for (int32_t i = 0; i < quotient->length; i++) {
            uint64_t new_carry = quotient->limbs[i] >> 63;
            quotient->limbs[i] = (quotient->limbs[i] << 1) | carry;
            carry = new_carry;
        }
        if (carry) {
            bigint_ensure_capacity(quotient, quotient->length + 1);
            quotient->limbs[quotient->length] = carry;
            quotient->length++;
        }

        /* Check if b << bit_pos <= remainder.
         * Instead of shifting b, compare b with remainder >> bit_pos
         * by extracting the right window. */
        /* Simpler: subtract b*2^bit from remainder if remainder >= b*2^bit */
        /* Even simpler for correctness: use the trial-subtract approach */

        /* Extract bit `bit` of remainder to build quotient, then subtract */
        /* Actually, use standard binary long division:
         * Compare (remainder >> bit) with b; if >=, set quotient bit and subtract */
    }

    /* Fallback: just use repeated subtraction for now (slow but correct) */
    fpy_bigint_free(quotient);
    quotient = fpy_bigint_from_i64(0);

    /* Better approach: shift-and-subtract */
    /* First, find the bit length of b */
    int b_bits = 0;
    for (int32_t i = b->length - 1; i >= 0; i--) {
        if (b->limbs[i] != 0) {
            b_bits = i * 64;
            uint64_t v = b->limbs[i];
            while (v) { b_bits++; v >>= 1; }
            break;
        }
    }
    /* Find bit length of remainder (= a) */
    int a_bits = 0;
    for (int32_t i = remainder->length - 1; i >= 0; i--) {
        if (remainder->limbs[i] != 0) {
            a_bits = i * 64;
            uint64_t v = remainder->limbs[i];
            while (v) { a_bits++; v >>= 1; }
            break;
        }
    }
    int shift = a_bits - b_bits;
    if (shift < 0) shift = 0;

    /* Build shifted_b = b << shift */
    /* Then iterate: if remainder >= shifted_b, subtract and set quotient bit */
    for (int s = shift; s >= 0; s--) {
        /* Compare remainder with b << s */
        /* Build b_shifted temporarily */
        int limb_shift = s / 64;
        int bit_shift = s % 64;
        int32_t bslen = b->length + limb_shift + 1;
        /* Stack-allocate for small, heap for large */
        uint64_t *bs_limbs = (uint64_t*)calloc(bslen, sizeof(uint64_t));
        for (int32_t i = 0; i < b->length; i++) {
            uint64_t v = b->limbs[i];
            bs_limbs[i + limb_shift] |= (bit_shift == 0) ? v : (v << bit_shift);
            if (bit_shift > 0 && i + limb_shift + 1 < bslen)
                bs_limbs[i + limb_shift + 1] |= v >> (64 - bit_shift);
        }
        /* Find actual length */
        int32_t bs_actual = bslen;
        while (bs_actual > 0 && bs_limbs[bs_actual - 1] == 0) bs_actual--;

        /* Compare remainder with shifted b */
        int ge = 0;
        if (remainder->length > bs_actual) ge = 1;
        else if (remainder->length == bs_actual) {
            ge = 1;
            for (int32_t i = bs_actual - 1; i >= 0; i--) {
                uint64_t rl = (i < remainder->length) ? remainder->limbs[i] : 0;
                if (rl < bs_limbs[i]) { ge = 0; break; }
                if (rl > bs_limbs[i]) break;
            }
        }

        if (ge) {
            /* Subtract b<<s from remainder */
            uint64_t borrow = 0;
            for (int32_t i = 0; i < remainder->length || i < bs_actual; i++) {
                uint64_t rl = (i < remainder->length) ? remainder->limbs[i] : 0;
                uint64_t bl = (i < bs_actual) ? bs_limbs[i] : 0;
                uint64_t diff = rl - bl - borrow;
                borrow = (rl < bl + borrow || (borrow && bl == UINT64_MAX)) ? 1 : 0;
                if (i < remainder->length) remainder->limbs[i] = diff;
            }
            bigint_normalize(remainder);

            /* Set bit s in quotient */
            int qlimb = s / 64;
            int qbit = s % 64;
            bigint_ensure_capacity(quotient, qlimb + 1);
            while (quotient->length <= qlimb) {
                quotient->limbs[quotient->length] = 0;
                quotient->length++;
            }
            quotient->limbs[qlimb] |= ((uint64_t)1 << qbit);
        }
        free(bs_limbs);
    }
    bigint_normalize(quotient);

    if (rem_out) *rem_out = remainder;
    else fpy_bigint_free(remainder);
    return quotient;
}

/* Floor division and modulo — simple long division */
FpyBigInt* fpy_bigint_floordiv(FpyBigInt *a, FpyBigInt *b) {
    if (fpy_bigint_is_zero(b)) {
        fprintf(stderr, "ZeroDivisionError: integer division or modulo by zero\n");
        exit(1);
    }
    /* Simple case: single limb each */
    if (a->length <= 1 && b->length <= 1) {
        int64_t va = a->sign * (int64_t)a->limbs[0];
        int64_t vb = b->sign * (int64_t)b->limbs[0];
        /* Python floor division */
        int64_t q = va / vb;
        if ((va % vb != 0) && ((va ^ vb) < 0)) q--;
        return fpy_bigint_from_i64(q);
    }
    /* For values that both fit in i64: fast path */
    int ov1, ov2;
    int64_t va = fpy_bigint_to_i64(a, &ov1);
    int64_t vb = fpy_bigint_to_i64(b, &ov2);
    if (!ov1 && !ov2) {
        int64_t q = va / vb;
        if ((va % vb != 0) && ((va ^ vb) < 0)) q--;
        return fpy_bigint_from_i64(q);
    }
    /* Full multi-limb unsigned division, then fix sign for Python floor */
    FpyBigInt *q = mag_divmod(a, b, NULL);
    q->sign = (a->sign == b->sign) ? 1 : -1;
    /* Python floor division: if signs differ and there's a remainder,
     * subtract 1 from quotient. Check via q*b != a. */
    if (a->sign != b->sign) {
        FpyBigInt *check = fpy_bigint_mul(q, b);
        check->sign = a->sign;  /* match a's sign for comparison */
        if (fpy_bigint_cmp(check, a) != 0) {
            FpyBigInt *one = fpy_bigint_from_i64(1);
            FpyBigInt *q2 = fpy_bigint_sub(q, one);
            fpy_bigint_free(one);
            fpy_bigint_free(q);
            q = q2;
        }
        fpy_bigint_free(check);
    }
    bigint_normalize(q);
    if (q->length == 0) q->sign = 1;
    return q;
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

/* Negate: if the value is a BigInt pointer, negate the BigInt.
 * Otherwise negate as i64 with overflow check. */
int64_t fpy_checked_neg(int64_t a, FpyBigInt **big) {
    *big = NULL;
    if (a == INT64_MIN) {
        /* -INT64_MIN overflows i64 */
        *big = fpy_bigint_from_i64(a);
        *big = fpy_bigint_neg(*big);
        return 0;
    }
    return -a;
}

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

    /* Try i64 with overflow checks.
     * Classic binary exponentiation: shift e first, then square b
     * only if more iterations remain.  This avoids a false overflow
     * from an unnecessary final b*b squaring. */
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
        e >>= 1;
        if (e == 0) break;  /* Don't square base when we're done */
        FpyBigInt *tmp = NULL;
        b = fpy_checked_mul(b, b, &tmp);
        if (tmp) {
            /* Base squared overflowed — finish in BigInt */
            FpyBigInt *bb = tmp;
            FpyBigInt *br = fpy_bigint_from_i64(result);
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
    }
    return result;
}
