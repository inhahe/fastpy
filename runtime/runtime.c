/*
 * fastpy minimal runtime — Milestone 1
 *
 * Provides basic I/O functions that compiled Python code calls into.
 * For now, just print functions for int, float, string, None, and bool.
 * The compiled module provides a fastpy_main() function that this
 * runtime's main() calls.
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <setjmp.h>
#include <stdlib.h>
#include "threading.h"
#include "objects.h"

/* Forward declaration: the compiled Python module provides this */
extern void fastpy_main(void);

/* --- Float formatting and newline/space writers ---
 * The typed print/write helpers (print_int/float/str/bool/none,
 * write_int/float/bool/none) were eliminated when the compiler moved
 * to dispatching print/write through fv_print/fv_write. Only the
 * formatting helper and the sep/end writers remain. */

void fastpy_format_float(double value, char *buf, int bufsize) {
    /*
     * Match CPython's float repr: shortest round-trip representation.
     * CPython uses David Gay's dtoa.c. We approximate with %g at
     * increasing precision, then fix up the format to match CPython's
     * conventions (prefer 180.0 over 1.8e+02 for moderate numbers).
     */
    int prec;
    char trial[64];

    for (prec = 1; prec <= 17; prec++) {
        snprintf(trial, sizeof(trial), "%.*g", prec, value);
        double roundtrip;
        if (sscanf(trial, "%lf", &roundtrip) == 1 && roundtrip == value) {
            break;
        }
    }

    /* Now format with the found precision using 'r' style:
     * use %f-style for numbers in [1e-4, 1e16), %e-style otherwise.
     * This matches CPython's behavior of preferring 180.0 over 1.8e+02. */
    double absval = value < 0 ? -value : value;

    if (absval == 0.0 || (absval >= 1e-4 && absval < 1e16)) {
        /* Use fixed-point notation. Convert %g precision (significant digits)
         * to %f precision (decimal places): decimal_places = sig_digits - floor(log10(absval)) - 1 */
        int int_digits = 1;
        if (absval >= 1.0) {
            double tmp = absval;
            int_digits = 0;
            while (tmp >= 1.0) { tmp /= 10.0; int_digits++; }
        }
        int decimal_places = prec - int_digits;
        if (decimal_places < 1) decimal_places = 1;

        snprintf(buf, bufsize, "%.*f", decimal_places, value);
        /* Strip trailing zeros but keep at least one after the dot */
        char *dot = strchr(buf, '.');
        if (dot) {
            char *end = buf + strlen(buf) - 1;
            while (end > dot + 1 && *end == '0') {
                *end = '\0';
                end--;
            }
        }
        /* Verify round-trip; if it fails, try with more precision */
        double roundtrip;
        if (sscanf(buf, "%lf", &roundtrip) == 1 && roundtrip == value) {
            return;
        }
        /* Try one more decimal place */
        snprintf(buf, bufsize, "%.*f", decimal_places + 1, value);
        dot = strchr(buf, '.');
        if (dot) {
            char *end = buf + strlen(buf) - 1;
            while (end > dot + 1 && *end == '0') { *end = '\0'; end--; }
        }
        if (sscanf(buf, "%lf", &roundtrip) == 1 && roundtrip == value) {
            return;
        }
    }

    /* Fall back to %g (scientific notation for very large/small numbers) */
    snprintf(buf, bufsize, "%.*g", prec, value);

    /* Ensure there's a dot or 'e' so it looks like a float */
    if (!strchr(buf, '.') && !strchr(buf, 'e') && !strchr(buf, 'E')
        && !strchr(buf, 'n') && !strchr(buf, 'i')) {
        strcat(buf, ".0");
    }
}

/* --- Remaining writers used by print(sep=, end=) handling --- */

void fastpy_write_str(const char *value) {
    printf("%s", value);
}

void fastpy_write_space(void) {
    printf(" ");
}

/* Newline-only print (for print() with no args) */
void fastpy_print_newline(void) {
    printf("\n");
    fflush(stdout);
}

/* --- String operations --- */

#include <stdlib.h>

const char* fastpy_str_concat(const char *a, const char *b) {
    size_t la = strlen(a), lb = strlen(b);
    FpyString *s = fpy_str_alloc(la + lb);
    memcpy(s->data, a, la);
    memcpy(s->data + la, b, lb + 1);
    return s->data;
}

int64_t fastpy_str_len(const char *s) {
    return (int64_t)strlen(s);
}

const char* fastpy_str_index(const char *s, int64_t index) {
    int64_t len = (int64_t)strlen(s);
    if (index < 0) index += len;
    if (index < 0 || index >= len) {
        fprintf(stderr, "IndexError: string index out of range\n");
        exit(1);
    }
    FpyString *r = fpy_str_alloc(1);
    r->data[0] = s[index];
    r->data[1] = '\0';
    return r->data;
}

const char* fastpy_str_slice(const char *s, int64_t start, int64_t stop, int64_t has_start, int64_t has_stop) {
    int64_t len = (int64_t)strlen(s);
    if (!has_start) start = 0;
    if (!has_stop) stop = len;
    if (start < 0) start += len;
    if (stop < 0) stop += len;
    if (start < 0) start = 0;
    if (stop > len) stop = len;
    if (start >= stop) {
        char *result = (char*)malloc(1);
        result[0] = '\0';
        return result;
    }
    int64_t rlen = stop - start;
    char *result = (char*)malloc(rlen + 1);
    memcpy(result, s + start, rlen);
    result[rlen] = '\0';
    return result;
}

const char* fastpy_str_slice_step(const char *s, int64_t start, int64_t stop,
                                   int64_t step, int64_t has_start, int64_t has_stop) {
    int64_t len = (int64_t)strlen(s);
    if (step == 0) step = 1;
    if (step > 0) {
        if (!has_start) start = 0;
        if (!has_stop) stop = len;
        if (start < 0) start += len;
        if (stop < 0) stop += len;
        if (start < 0) start = 0;
        if (stop > len) stop = len;
    } else {
        if (!has_start) start = len - 1;
        if (has_stop && stop < 0) stop += len;
        if (!has_stop) stop = -1;  /* sentinel past beginning */
        if (start < 0) start += len;
        if (start >= len) start = len - 1;
    }
    int64_t rlen = 0;
    if (step > 0) {
        for (int64_t i = start; i < stop; i += step) rlen++;
    } else {
        for (int64_t i = start; i > stop; i += step) rlen++;
    }
    char *result = (char*)malloc(rlen + 1);
    int64_t out = 0;
    if (step > 0) {
        for (int64_t i = start; i < stop; i += step) result[out++] = s[i];
    } else {
        for (int64_t i = start; i > stop; i += step) result[out++] = s[i];
    }
    result[out] = '\0';
    return result;
}

const char* fastpy_str_repeat(const char *s, int64_t n) {
    if (n <= 0) {
        char *result = (char*)malloc(1);
        result[0] = '\0';
        return result;
    }
    size_t slen = strlen(s);
    size_t rlen = slen * n;
    char *result = (char*)malloc(rlen + 1);
    for (int64_t i = 0; i < n; i++) {
        memcpy(result + i * slen, s, slen);
    }
    result[rlen] = '\0';
    return result;
}

const char* fastpy_str_lower(const char *s) {
    size_t len = strlen(s);
    char *result = (char*)malloc(len + 1);
    for (size_t i = 0; i <= len; i++) {
        result[i] = (s[i] >= 'A' && s[i] <= 'Z') ? s[i] + 32 : s[i];
    }
    return result;
}

/* Convert int to string (for f-string formatting) */
const char* fastpy_int_to_str(int64_t value) {
    FpyString *s = fpy_str_alloc(32);
    snprintf(s->data, 32, "%lld", (long long)value);
    return s->data;
}

/* Convert float to string (for f-string formatting) */
const char* fastpy_float_to_str(double value) {
    char buf[64];
    fastpy_format_float(value, buf, sizeof(buf));
    size_t len = strlen(buf);
    FpyString *s = fpy_str_alloc(len);
    memcpy(s->data, buf, len + 1);
    return s->data;
}

/* --- Arithmetic helpers --- */

int64_t fastpy_pow_int(int64_t base, int64_t exp) {
    /* Integer power. Negative exponents return 0 (integer division of 1/x). */
    if (exp < 0) return 0;
    int64_t result = 1;
    while (exp > 0) {
        if (exp & 1) result *= base;
        base *= base;
        exp >>= 1;
    }
    return result;
}

int64_t fastpy_pow_mod(int64_t base, int64_t exp, int64_t mod) {
    if (mod == 0) return 0;  /* would be ZeroDivisionError */
    if (exp < 0) return 0;
    int64_t result = 1;
    base = base % mod;
    if (base < 0) base += mod;
    while (exp > 0) {
        if (exp & 1) result = (result * base) % mod;
        base = (base * base) % mod;
        exp >>= 1;
    }
    return result;
}

double fastpy_pow_float(double base, double exp) {
    return pow(base, exp);
}

/* --- Exception system (flag-based) --- */

#define FPY_EXC_NONE           0
#define FPY_EXC_ZERODIVISION   1
#define FPY_EXC_VALUEERROR     2
#define FPY_EXC_TYPEERROR      3
#define FPY_EXC_INDEXERROR     4
#define FPY_EXC_KEYERROR       5
#define FPY_EXC_RUNTIMEERROR   6
#define FPY_EXC_STOPITERATION  7
#define FPY_EXC_EXCEPTIONGROUP 8
#define FPY_EXC_GENERIC        99

/* Per-thread exception state. Each thread has its own exception,
 * so raising in one thread doesn't corrupt another's state. */
FPY_THREAD_LOCAL int fpy_exc_type = FPY_EXC_NONE;
FPY_THREAD_LOCAL const char *fpy_exc_msg = "";
FPY_THREAD_LOCAL int fpy_exc_group_inner = FPY_EXC_NONE;

/* Per-thread return tag for closure calls. The closure body stores
 * the value's runtime tag here before returning the i64 data. The
 * caller reads it after the call to reconstruct the full FpyValue.
 * Default INT so non-closure paths produce correct results. */
FPY_THREAD_LOCAL int32_t fpy_ret_tag = 0;  /* FPY_TAG_INT */

void fastpy_set_ret_tag(int32_t tag) { fpy_ret_tag = tag; }
int32_t fastpy_get_ret_tag(void) { return fpy_ret_tag; }

/* Raise an exception — sets the flag. Caller must check and propagate. */
void fastpy_raise(int exc_type, const char *msg) {
    fpy_exc_type = exc_type;
    fpy_exc_msg = msg;
}

/* Check if an exception is pending */
int fastpy_exc_pending(void) {
    return fpy_exc_type != FPY_EXC_NONE;
}

/* Get current exception type. */
int fastpy_exc_get_type(void) {
    return fpy_exc_type;
}

/* Get current exception message. */
const char* fastpy_exc_get_msg(void) {
    return fpy_exc_msg;
}

/* Clear current exception. */
void fastpy_exc_clear(void) {
    fpy_exc_type = FPY_EXC_NONE;
    fpy_exc_msg = "";
    fpy_exc_group_inner = FPY_EXC_NONE;
}

/* Set the inner exception type for ExceptionGroup */
void fastpy_exc_set_group_inner(int inner_type) {
    fpy_exc_group_inner = inner_type;
}

/* Get the inner exception type for ExceptionGroup */
int fastpy_exc_get_group_inner(void) {
    return fpy_exc_group_inner;
}

/* Map exception name to type id */
int fastpy_exc_name_to_id(const char *name) {
    if (strcmp(name, "ZeroDivisionError") == 0) return FPY_EXC_ZERODIVISION;
    if (strcmp(name, "ValueError") == 0) return FPY_EXC_VALUEERROR;
    if (strcmp(name, "TypeError") == 0) return FPY_EXC_TYPEERROR;
    if (strcmp(name, "IndexError") == 0) return FPY_EXC_INDEXERROR;
    if (strcmp(name, "KeyError") == 0) return FPY_EXC_KEYERROR;
    if (strcmp(name, "RuntimeError") == 0) return FPY_EXC_RUNTIMEERROR;
    if (strcmp(name, "StopIteration") == 0) return FPY_EXC_STOPITERATION;
    if (strcmp(name, "ExceptionGroup") == 0) return FPY_EXC_EXCEPTIONGROUP;
    return FPY_EXC_GENERIC;
}

/* Print unhandled exception and exit */
void fastpy_exc_unhandled(void) {
    if (fpy_exc_type == FPY_EXC_NONE) return;
    const char *names[] = {
        "Exception", "ZeroDivisionError", "ValueError", "TypeError",
        "IndexError", "KeyError", "RuntimeError", "StopIteration",
        "ExceptionGroup"
    };
    const char *name = (fpy_exc_type >= 1 && fpy_exc_type <= 8)
        ? names[fpy_exc_type] : "Exception";
    fprintf(stderr, "Traceback (most recent call last):\n  %s: %s\n", name, fpy_exc_msg);
    exit(1);
}

/* Safe integer division — raises ZeroDivisionError if divisor is 0 */
int64_t fastpy_safe_div(int64_t a, int64_t b) {
    if (b == 0) {
        fastpy_raise(FPY_EXC_ZERODIVISION, "division by zero");
        return 0;
    }
    return a / b;
}

double fastpy_safe_fdiv(double a, double b) {
    if (b == 0.0) {
        /* CPython 3.14+ uses "division by zero" for all cases (int/int,
         * float/float, and mixed). Older CPython said "float division by
         * zero" for float operands — we match current behavior. */
        fastpy_raise(FPY_EXC_ZERODIVISION, "division by zero");
        return 0.0;
    }
    return a / b;
}

/* int/int "true division" that returns float but preserves CPython's
 * "division by zero" error message (CPython only says "float division
 * by zero" when one of the operands is actually a float). */
double fastpy_safe_int_fdiv(int64_t a, int64_t b) {
    if (b == 0) {
        fastpy_raise(FPY_EXC_ZERODIVISION, "division by zero");
        return 0.0;
    }
    return (double)a / (double)b;
}

/* Entry point. If fastpy_main sets an unhandled exception (via
 * fastpy_raise), print a traceback-style message to stderr and exit
 * non-zero to match CPython's behavior. */
int main(void) {
    /* Initialize threading if enabled (mode set by codegen global) */
    if (fpy_threading_mode >= FPY_THREADING_GIL) {
        fpy_gil_init();
        fpy_print_mutex_init();
        fpy_gil_acquire();  /* main thread holds GIL initially */
    }
    fastpy_main();
    /* Flush Python's stdout in case CPython bridge functions called print() */
    extern void fpy_cpython_flush(void);
    fpy_cpython_flush();
    fflush(stdout);
    if (fastpy_exc_pending()) {
        const char *name = "Exception";
        switch (fpy_exc_type) {
            case FPY_EXC_ZERODIVISION: name = "ZeroDivisionError"; break;
            case FPY_EXC_VALUEERROR:   name = "ValueError"; break;
            case FPY_EXC_TYPEERROR:    name = "TypeError"; break;
            case FPY_EXC_KEYERROR:     name = "KeyError"; break;
            case FPY_EXC_INDEXERROR:   name = "IndexError"; break;
            case FPY_EXC_RUNTIMEERROR: name = "RuntimeError"; break;
            case FPY_EXC_STOPITERATION: name = "StopIteration"; break;
            default: break;
        }
        fprintf(stderr, "%s: %s\n", name, fpy_exc_msg ? fpy_exc_msg : "");
        return 1;
    }
    return 0;
}
