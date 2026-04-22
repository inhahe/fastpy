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
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif
#ifndef _WIN32
#include <dirent.h>
#include <unistd.h>
#endif
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

/* str.encode() — returns a copy of the string tagged as bytes.
 * For UTF-8 strings (the default encoding), the byte content is identical
 * to the string content, so we just strdup and let the caller tag as BYTES. */
const char* fastpy_str_encode(const char *s) {
    if (!s) return "";
    size_t len = strlen(s);
    FpyString *result = fpy_str_alloc(len);
    memcpy(result->data, s, len + 1);
    return result->data;
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
#define FPY_EXC_NAMEERROR      9
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
    if (strcmp(name, "NameError") == 0) return FPY_EXC_NAMEERROR;
    return FPY_EXC_GENERIC;
}

/* Print unhandled exception and exit */
void fastpy_exc_unhandled(void) {
    if (fpy_exc_type == FPY_EXC_NONE) return;
    const char *names[] = {
        "Exception", "ZeroDivisionError", "ValueError", "TypeError",
        "IndexError", "KeyError", "RuntimeError", "StopIteration",
        "ExceptionGroup", "NameError"
    };
    const char *name = (fpy_exc_type >= 1 && fpy_exc_type <= 9)
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
/* ── JIT symbol table ──────────────────────────────────────────────
 * Returns pairs of (name, address) for all runtime functions so the
 * in-process MCJIT can resolve them. Called from compiler/jit.py. */

typedef struct { const char *name; void *addr; } FpySymEntry;

/* Forward declarations for runtime functions used in symbol table.
 * Most are declared in objects.h or defined earlier in this file.
 * Only need to declare those not visible from the includes. */
#define SYM(fn) { #fn, (void*)(intptr_t)fn }

extern void fastpy_print_newline(void);
extern void fastpy_fv_print(int32_t, int64_t);
extern void fastpy_fv_write(int32_t, int64_t);
extern const char* fastpy_fv_repr(int32_t, int64_t);
extern const char* fastpy_fv_str(int32_t, int64_t);
extern int32_t fastpy_fv_truthy(int32_t, int64_t);
extern void fastpy_fv_binop(int32_t, int64_t, int32_t, int64_t, int32_t, int32_t*, int64_t*);
extern void fastpy_raise(int, const char*);
extern int32_t fastpy_exc_pending(void);
extern void fastpy_exc_clear(void);
extern int32_t fastpy_exc_get_type(void);
extern const char* fastpy_exc_get_msg(void);
extern int32_t fastpy_exc_name_to_id(const char*);
extern FpyList* fastpy_list_new(void);
extern void fastpy_list_append_fv(FpyList*, int32_t, int64_t);
extern void fastpy_list_get_fv(FpyList*, int64_t, int32_t*, int64_t*);
extern void fastpy_list_set_fv(FpyList*, int64_t, int32_t, int64_t);
extern int64_t fastpy_list_length(FpyList*);
extern FpyList* fastpy_list_sorted(FpyList*);
extern FpyList* fastpy_list_reversed(FpyList*);
extern FpyList* fastpy_list_copy(FpyList*);
extern void fastpy_list_clear(FpyList*);
extern void fastpy_list_extend(FpyList*, FpyList*);
extern void fastpy_list_sort(FpyList*);
extern FpyList* fastpy_list_concat(FpyList*, FpyList*);
extern FpyDict* fastpy_dict_new(void);
extern void fastpy_dict_set_fv(FpyDict*, const char*, int32_t, int64_t);
extern void fastpy_dict_get_fv(FpyDict*, const char*, int32_t*, int64_t*);
extern int64_t fastpy_dict_length(FpyDict*);
extern FpyList* fastpy_dict_keys(FpyDict*);
extern FpyList* fastpy_dict_values(FpyDict*);
extern FpyList* fastpy_dict_items(FpyDict*);
extern int32_t fastpy_dict_has_key(FpyDict*, const char*);
extern void fastpy_dict_update(FpyDict*, FpyDict*);
extern FpyList* fastpy_tuple_new(void);
extern void* fastpy_obj_new(int32_t);
extern int32_t fastpy_register_class(const char*, int32_t);
extern void fastpy_register_method(int32_t, const char*, void*, int32_t, int32_t);
extern void fastpy_obj_set_fv(void*, const char*, int32_t, int64_t);
extern void fastpy_obj_get_fv(void*, const char*, int32_t*, int64_t*);
extern const char* fastpy_str_concat(const char*, const char*);
extern int64_t fastpy_str_len(const char*);
extern const char* fastpy_str_lower(const char*);
extern const char* fastpy_str_upper(const char*);
extern const char* fastpy_str_strip(const char*);
extern const char* fastpy_str_replace(const char*, const char*, const char*);
extern FpyList* fastpy_str_split(const char*);
extern const char* fastpy_str_join(const char*, FpyList*);
extern int64_t fastpy_str_compare(const char*, const char*);
extern int64_t fastpy_str_find(const char*, const char*);
extern const char* fastpy_int_to_str(int64_t);
extern const char* fastpy_float_to_str(double);
extern int64_t fastpy_pow_int(int64_t, int64_t);
extern double fastpy_pow_float(double, double);
extern int64_t fastpy_round(double);
extern const char* fastpy_chr(int64_t);
extern int64_t fastpy_ord(const char*);
extern const char* fastpy_hex(int64_t);
extern FpyList* fastpy_enumerate(FpyList*, int64_t);
extern FpyList* fastpy_zip(FpyList*, FpyList*);
extern FpyList* fastpy_range(int64_t, int64_t, int64_t);
extern void* fastpy_closure_new(void*, int32_t, int32_t);
extern void fastpy_closure_set_capture(void*, int32_t, int64_t);
extern int64_t fastpy_closure_call0(void*);
extern int64_t fastpy_closure_call1(void*, int64_t);
extern int64_t fastpy_closure_call2(void*, int64_t, int64_t);
extern void* fastpy_cell_new(int64_t);
extern void fastpy_cell_set(void*, int64_t);
extern int64_t fastpy_cell_get(void*);
extern void* fpy_cpython_import(const char*);
extern void* fpy_cpython_getattr(void*, const char*);
extern void fpy_cpython_call0(void*, int32_t*, int64_t*);
extern void fpy_cpython_call1(void*, int32_t, int64_t, int32_t*, int64_t*);
extern void fpy_cpython_call2(void*, int32_t, int64_t, int32_t, int64_t, int32_t*, int64_t*);
extern void fpy_cpython_call3(void*, int32_t, int64_t, int32_t, int64_t, int32_t, int64_t, int32_t*, int64_t*);
extern void fpy_cpython_call_kw(void*, int32_t, int32_t*, int64_t*, int32_t, const char**, int32_t*, int64_t*, int32_t*, int64_t*);
extern void fpy_cpython_to_fv(void*, int32_t*, int64_t*);
extern int64_t fpy_cpython_len(void*);
extern int64_t fpy_cpython_bool(void*);
extern void fpy_cpython_flush(void);
extern void* fpy_cpython_iter(void*);
extern int32_t fpy_cpython_iter_next(void*, int32_t*, int64_t*);
extern void fpy_jit_exec(const char*);
extern void* fpy_jit_import(const char*);
extern void fpy_rc_incref(int32_t, int64_t);
extern void fpy_rc_decref(int32_t, int64_t);
extern void fpy_cpython_binop(void*, int32_t, int64_t, int32_t, int32_t*, int64_t*);
extern void fpy_cpython_rbinop(int32_t, int64_t, void*, int32_t, int32_t*, int64_t*);
extern int32_t fpy_cpython_compare(void*, void*, int32_t);
extern void fpy_cpython_concat(void*, void*, int32_t*, int64_t*);

static FpySymEntry fpy_jit_symbols[] = {
    SYM(fastpy_print_newline),
    SYM(fastpy_fv_print), SYM(fastpy_fv_write),
    SYM(fastpy_fv_repr), SYM(fastpy_fv_str), SYM(fastpy_fv_truthy),
    SYM(fastpy_fv_binop),
    SYM(fastpy_raise), SYM(fastpy_exc_pending), SYM(fastpy_exc_clear),
    SYM(fastpy_exc_get_type), SYM(fastpy_exc_get_msg), SYM(fastpy_exc_name_to_id),
    SYM(fastpy_list_new), SYM(fastpy_list_append_fv),
    SYM(fastpy_list_get_fv), SYM(fastpy_list_set_fv),
    SYM(fastpy_list_length), SYM(fastpy_list_sorted), SYM(fastpy_list_reversed),
    SYM(fastpy_list_copy), SYM(fastpy_list_clear),
    SYM(fastpy_list_extend), SYM(fastpy_list_sort), SYM(fastpy_list_concat),
    SYM(fastpy_dict_new), SYM(fastpy_dict_set_fv), SYM(fastpy_dict_get_fv),
    SYM(fastpy_dict_length), SYM(fastpy_dict_keys), SYM(fastpy_dict_values),
    SYM(fastpy_dict_items), SYM(fastpy_dict_has_key), SYM(fastpy_dict_update),
    SYM(fastpy_dict_equal), SYM(fastpy_set_equal),
    SYM(fastpy_tuple_new), SYM(fastpy_obj_new),
    SYM(fastpy_register_class), SYM(fastpy_register_method),
    SYM(fastpy_obj_set_fv), SYM(fastpy_obj_get_fv),
    SYM(fastpy_str_concat), SYM(fastpy_str_len), SYM(fastpy_str_lower),
    SYM(fastpy_str_upper), SYM(fastpy_str_strip), SYM(fastpy_str_replace),
    SYM(fastpy_str_split), SYM(fastpy_str_join),
    SYM(fastpy_str_compare), SYM(fastpy_str_find),
    SYM(fastpy_int_to_str), SYM(fastpy_float_to_str),
    SYM(fastpy_pow_int), SYM(fastpy_pow_float), SYM(fastpy_round),
    SYM(fastpy_chr), SYM(fastpy_ord), SYM(fastpy_hex),
    SYM(fastpy_enumerate), SYM(fastpy_zip), SYM(fastpy_range),
    SYM(fastpy_closure_new), SYM(fastpy_closure_set_capture),
    SYM(fastpy_closure_call0), SYM(fastpy_closure_call1), SYM(fastpy_closure_call2),
    SYM(fastpy_cell_new), SYM(fastpy_cell_set), SYM(fastpy_cell_get),
    SYM(fpy_cpython_import), SYM(fpy_cpython_getattr),
    SYM(fpy_cpython_call0), SYM(fpy_cpython_call1), SYM(fpy_cpython_call2),
    SYM(fpy_cpython_call3), SYM(fpy_cpython_call_kw),
    SYM(fpy_cpython_to_fv), SYM(fpy_cpython_len), SYM(fpy_cpython_bool),
    SYM(fpy_cpython_flush), SYM(fpy_cpython_iter), SYM(fpy_cpython_iter_next),
    SYM(fpy_jit_exec), SYM(fpy_jit_import),
    SYM(fpy_rc_incref), SYM(fpy_rc_decref),
    SYM(fpy_cpython_binop), SYM(fpy_cpython_rbinop),
    SYM(fpy_cpython_compare), SYM(fpy_cpython_concat),
    {NULL, NULL}
};

/* Returns the symbol table. Called from Python via ctypes. */
#ifdef _WIN32
__declspec(dllexport)
#endif
FpySymEntry* fastpy_get_jit_symbols(void) {
    return fpy_jit_symbols;
}

/* Returns the number of symbols (excluding terminator). */
#ifdef _WIN32
__declspec(dllexport)
#endif
int fastpy_get_jit_symbol_count(void) {
    int n = 0;
    while (fpy_jit_symbols[n].name) n++;
    return n;
}

int main(void) {
#ifdef _WIN32
    /* Ensure stdout/stderr are in text mode so \n → \r\n conversion
     * matches CPython's behavior. C runtime may default to binary
     * mode when stdout is a pipe (e.g. subprocess capture). */
    _setmode(_fileno(stdout), _O_TEXT);
    _setmode(_fileno(stderr), _O_TEXT);
#endif
    /* Initialize threading if enabled (mode set by codegen global) */
    if (fpy_threading_mode >= FPY_THREADING_GIL) {
        fpy_gil_init();
        fpy_print_mutex_init();
        fpy_gil_acquire();  /* main thread holds GIL initially */
    }
    fastpy_main();
    /* Run final GC sweep to trigger destructors on all remaining
     * objects (e.g., generators with pending finally blocks). This
     * matches CPython's behavior of running __del__/close() at exit.
     * Only objects with destructors are called — others are left for
     * the OS to reclaim with process memory. */
    extern void fpy_gc_finalize(void);
    fpy_gc_finalize();
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
            case FPY_EXC_NAMEERROR:    name = "NameError"; break;
            default: break;
        }
        fprintf(stderr, "%s: %s\n", name, fpy_exc_msg ? fpy_exc_msg : "");
        return 1;
    }
    return 0;
}

/* ============================================================
 * Native sys module
 * ============================================================ */

/* sys.exit(code) */
void fastpy_sys_exit(int64_t code) {
    exit((int)code);
}

/* sys.argv — returns an empty list (AOT-compiled programs don't
 * receive Python argv by default; future: link to main(argc, argv)) */
FpyList* fastpy_sys_argv(void) {
    return fpy_list_new(4);
}

/* sys.platform */
const char* fastpy_sys_platform(void) {
#ifdef _WIN32
    return "win32";
#elif __APPLE__
    return "darwin";
#else
    return "linux";
#endif
}

/* sys.maxsize (2^63 - 1) */
int64_t fastpy_sys_maxsize(void) {
    return 9223372036854775807LL;
}

/* sys.version_info — returns a tuple (major, minor, micro, ...) */
FpyList* fastpy_sys_version_info(void) {
    FpyList *t = fpy_list_new(5);
    t->is_tuple = 1;
    FpyValue v;
    v.tag = FPY_TAG_INT; v.data.i = 3; fpy_list_append(t, v);  /* major */
    v.tag = FPY_TAG_INT; v.data.i = 14; fpy_list_append(t, v); /* minor */
    v.tag = FPY_TAG_INT; v.data.i = 0; fpy_list_append(t, v);  /* micro */
    v.tag = FPY_TAG_STR; v.data.s = "final"; fpy_list_append(t, v);
    v.tag = FPY_TAG_INT; v.data.i = 0; fpy_list_append(t, v);
    return t;
}

/* ============================================================
 * Native time module
 * ============================================================ */

#ifdef _WIN32
#include <windows.h>
#else
#include <sys/time.h>
#include <unistd.h>
#endif

/* time.time() → float seconds since epoch */
double fastpy_time_time(void) {
#ifdef _WIN32
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    uint64_t t = ((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
    /* Convert from 100ns intervals since 1601 to seconds since 1970 */
    return (double)(t - 116444736000000000ULL) / 10000000.0;
#else
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (double)tv.tv_sec + (double)tv.tv_usec / 1000000.0;
#endif
}

/* time.time_ns() → int nanoseconds since epoch */
int64_t fastpy_time_time_ns(void) {
#ifdef _WIN32
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    uint64_t t = ((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
    return (int64_t)((t - 116444736000000000ULL) * 100);
#else
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (int64_t)tv.tv_sec * 1000000000LL + (int64_t)tv.tv_usec * 1000LL;
#endif
}

/* time.perf_counter() → float high-resolution timer */
double fastpy_time_perf_counter(void) {
#ifdef _WIN32
    LARGE_INTEGER freq, count;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&count);
    return (double)count.QuadPart / (double)freq.QuadPart;
#else
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (double)tv.tv_sec + (double)tv.tv_usec / 1000000.0;
#endif
}

/* time.sleep(seconds) */
void fastpy_time_sleep(double seconds) {
#ifdef _WIN32
    Sleep((DWORD)(seconds * 1000));
#else
    usleep((useconds_t)(seconds * 1000000));
#endif
}

/* time.monotonic() → float monotonic clock */
double fastpy_time_monotonic(void) {
#ifdef _WIN32
    return fastpy_time_perf_counter();
#else
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (double)tv.tv_sec + (double)tv.tv_usec / 1000000.0;
#endif
}

/* ============================================================
 * Native random module — xoshiro256** PRNG
 * ============================================================
 * Fast, high-quality 64-bit PRNG. Seeded from system time on first use.
 */

static uint64_t fpy_rng_state[4] = {0, 0, 0, 0};
static int fpy_rng_initialized = 0;

static inline uint64_t fpy_rotl(uint64_t x, int k) {
    return (x << k) | (x >> (64 - k));
}

static void fpy_rng_seed(uint64_t seed) {
    /* SplitMix64 to expand a single seed into 4 state words */
    for (int i = 0; i < 4; i++) {
        seed += 0x9e3779b97f4a7c15ULL;
        uint64_t z = seed;
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        fpy_rng_state[i] = z ^ (z >> 31);
    }
    fpy_rng_initialized = 1;
}

static void fpy_rng_ensure_init(void) {
    if (!fpy_rng_initialized) {
        /* Seed from system time */
#ifdef _WIN32
        LARGE_INTEGER pc;
        QueryPerformanceCounter(&pc);
        fpy_rng_seed((uint64_t)pc.QuadPart ^ (uint64_t)GetTickCount64());
#else
        struct timeval tv;
        gettimeofday(&tv, NULL);
        fpy_rng_seed((uint64_t)tv.tv_sec * 1000000ULL + (uint64_t)tv.tv_usec);
#endif
    }
}

static uint64_t fpy_rng_next(void) {
    fpy_rng_ensure_init();
    uint64_t *s = fpy_rng_state;
    uint64_t result = fpy_rotl(s[1] * 5, 7) * 9;
    uint64_t t = s[1] << 17;
    s[2] ^= s[0]; s[3] ^= s[1]; s[1] ^= s[2]; s[0] ^= s[3];
    s[2] ^= t;
    s[3] = fpy_rotl(s[3], 45);
    return result;
}

/* random.seed(n) */
void fastpy_random_seed(int64_t seed) {
    fpy_rng_seed((uint64_t)seed);
}

/* random.random() → float in [0.0, 1.0) */
double fastpy_random_random(void) {
    return (double)(fpy_rng_next() >> 11) * (1.0 / 9007199254740992.0);
}

/* random.randint(a, b) → int in [a, b] inclusive */
int64_t fastpy_random_randint(int64_t a, int64_t b) {
    if (a > b) { int64_t t = a; a = b; b = t; }
    uint64_t range = (uint64_t)(b - a) + 1;
    uint64_t r = fpy_rng_next();
    return a + (int64_t)(r % range);
}

/* random.randrange(start, stop) → int in [start, stop) */
int64_t fastpy_random_randrange(int64_t start, int64_t stop) {
    if (start >= stop) return start;
    uint64_t range = (uint64_t)(stop - start);
    return start + (int64_t)(fpy_rng_next() % range);
}

/* random.choice(list) → random element */
void fastpy_random_choice(FpyList *lst, int32_t *out_tag, int64_t *out_data) {
    if (lst->length == 0) {
        fprintf(stderr, "IndexError: Cannot choose from an empty sequence\n");
        exit(1);
    }
    int64_t idx = (int64_t)(fpy_rng_next() % (uint64_t)lst->length);
    *out_tag = lst->items[idx].tag;
    *out_data = lst->items[idx].data.i;
}

/* random.shuffle(list) — in-place Fisher-Yates shuffle */
void fastpy_random_shuffle(FpyList *lst) {
    for (int64_t i = lst->length - 1; i > 0; i--) {
        int64_t j = (int64_t)(fpy_rng_next() % (uint64_t)(i + 1));
        FpyValue tmp = lst->items[i];
        lst->items[i] = lst->items[j];
        lst->items[j] = tmp;
    }
}

/* random.sample(list, k) → new list with k unique random elements */
FpyList* fastpy_random_sample(FpyList *lst, int64_t k) {
    if (k > lst->length) k = lst->length;
    if (k <= 0) return fpy_list_new(4);
    /* Reservoir sampling for k elements */
    FpyList *result = fpy_list_new(k);
    for (int64_t i = 0; i < k; i++) {
        fpy_list_append(result, lst->items[i]);
    }
    for (int64_t i = k; i < lst->length; i++) {
        int64_t j = (int64_t)(fpy_rng_next() % (uint64_t)(i + 1));
        if (j < k) {
            result->items[j] = lst->items[i];
        }
    }
    return result;
}

/* random.uniform(a, b) → float in [a, b] */
double fastpy_random_uniform(double a, double b) {
    return a + (b - a) * fastpy_random_random();
}

/* random.gauss(mu, sigma) → float, Gaussian distribution (Box-Muller) */
double fastpy_random_gauss(double mu, double sigma) {
    double u1 = fastpy_random_random();
    double u2 = fastpy_random_random();
    if (u1 < 1e-15) u1 = 1e-15;  /* avoid log(0) */
    double z = sqrt(-2.0 * log(u1)) * cos(2.0 * 3.14159265358979323846 * u2);
    return mu + sigma * z;
}

/* ============================================================
 * Native base64 module
 * ============================================================ */

static const char b64_table[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static const int8_t b64_decode_table[256] = {
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,62,-1,-1,-1,63,
    52,53,54,55,56,57,58,59,60,61,-1,-1,-1,-1,-1,-1,
    -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,
    15,16,17,18,19,20,21,22,23,24,25,-1,-1,-1,-1,-1,
    -1,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,
    41,42,43,44,45,46,47,48,49,50,51,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
};

/* base64.b64encode(data_str) → encoded string */
const char* fastpy_base64_b64encode(const char *data) {
    int64_t len = (int64_t)strlen(data);
    int64_t out_len = ((len + 2) / 3) * 4;
    char *out = (char*)malloc(out_len + 1);
    int64_t i = 0, j = 0;
    while (i < len) {
        int64_t remaining = len - i;
        uint32_t a = (uint8_t)data[i++];
        uint32_t b = (remaining > 1) ? (uint8_t)data[i++] : 0;
        uint32_t c = (remaining > 2) ? (uint8_t)data[i++] : 0;
        uint32_t triple = (a << 16) | (b << 8) | c;
        out[j++] = b64_table[(triple >> 18) & 0x3F];
        out[j++] = b64_table[(triple >> 12) & 0x3F];
        out[j++] = (remaining > 1) ? b64_table[(triple >> 6) & 0x3F] : '=';
        out[j++] = (remaining > 2) ? b64_table[triple & 0x3F] : '=';
    }
    out[j] = '\0';
    return out;
}

/* base64.b64decode(encoded_str) → decoded string */
const char* fastpy_base64_b64decode(const char *data) {
    int64_t len = (int64_t)strlen(data);
    /* Remove padding for size calculation */
    int64_t padding = 0;
    if (len > 0 && data[len-1] == '=') padding++;
    if (len > 1 && data[len-2] == '=') padding++;
    int64_t out_len = (len / 4) * 3 - padding;
    if (out_len < 0) out_len = 0;
    char *out = (char*)malloc(out_len + 1);
    int64_t i = 0, j = 0;
    while (i < len) {
        int8_t a = b64_decode_table[(uint8_t)data[i++]];
        int8_t b = i < len ? b64_decode_table[(uint8_t)data[i++]] : 0;
        int8_t c = i < len ? b64_decode_table[(uint8_t)data[i++]] : 0;
        int8_t d = i < len ? b64_decode_table[(uint8_t)data[i++]] : 0;
        if (a < 0) a = 0; if (b < 0) b = 0;
        if (c < 0) c = 0; if (d < 0) d = 0;
        uint32_t triple = ((uint32_t)a << 18) | ((uint32_t)b << 12)
                         | ((uint32_t)c << 6) | (uint32_t)d;
        if (j < out_len) out[j++] = (triple >> 16) & 0xFF;
        if (j < out_len) out[j++] = (triple >> 8) & 0xFF;
        if (j < out_len) out[j++] = triple & 0xFF;
    }
    out[out_len] = '\0';
    return out;
}

/* ============================================================
 * Native uuid module
 * ============================================================ */

/* uuid.uuid4() → random UUID string "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx" */
const char* fastpy_uuid_uuid4(void) {
    fpy_rng_ensure_init();
    char *buf = (char*)malloc(37);
    uint64_t r1 = fpy_rng_next();
    uint64_t r2 = fpy_rng_next();
    /* Set version (4) and variant (10xx) bits */
    r1 = (r1 & 0xFFFFFFFFFFFF0FFFULL) | 0x0000000000004000ULL;  /* version 4 */
    r2 = (r2 & 0x3FFFFFFFFFFFFFFFULL) | 0x8000000000000000ULL;  /* variant 10 */
    sprintf(buf, "%08x-%04x-%04x-%04x-%012llx",
            (uint32_t)(r1 >> 32),
            (uint16_t)(r1 >> 16),
            (uint16_t)(r1),
            (uint16_t)(r2 >> 48),
            (unsigned long long)(r2 & 0x0000FFFFFFFFFFFFULL));
    return buf;
}

/* ============================================================
 * Native struct module — binary packing/unpacking
 * ============================================================
 * Supports format chars: b/B (int8), h/H (int16), i/I (int32),
 * q/Q (int64), f (float32), d (float64), x (pad byte), s (bytes).
 * Byte order: @ = native, < = little-endian, > = big-endian, ! = network (big).
 */

static int fpy_struct_item_size(char c) {
    switch (c) {
        case 'b': case 'B': case 'x': return 1;
        case 'h': case 'H': return 2;
        case 'i': case 'I': case 'l': case 'L': case 'f': return 4;
        case 'q': case 'Q': case 'd': return 8;
        default: return 0;
    }
}

/* struct.calcsize(fmt) → int */
int64_t fastpy_struct_calcsize(const char *fmt) {
    int64_t size = 0;
    const char *p = fmt;
    /* Skip byte order char */
    if (*p == '@' || *p == '<' || *p == '>' || *p == '!' || *p == '=') p++;
    int count = 0;
    while (*p) {
        if (*p >= '0' && *p <= '9') {
            count = count * 10 + (*p - '0');
        } else {
            if (count == 0) count = 1;
            if (*p == 's') {
                size += count;  /* 's' means count bytes */
            } else {
                size += count * fpy_struct_item_size(*p);
            }
            count = 0;
        }
        p++;
    }
    return size;
}

/* struct.pack(fmt, *values) → bytes (returned as char* with length prefix)
 * We return a FpyList of ints (byte values) for simplicity, or a char* buffer.
 * Using char* buffer (caller knows length via calcsize). */
const char* fastpy_struct_pack(const char *fmt, FpyList *values) {
    int64_t size = fastpy_struct_calcsize(fmt);
    char *buf = (char*)calloc(size, 1);
    const char *p = fmt;
    int big_endian = 0;

    /* Parse byte order */
    if (*p == '>' || *p == '!') { big_endian = 1; p++; }
    else if (*p == '<') { big_endian = 0; p++; }
    else if (*p == '@' || *p == '=') { p++; }

    int offset = 0, val_idx = 0, count = 0;
    while (*p) {
        if (*p >= '0' && *p <= '9') {
            count = count * 10 + (*p - '0');
            p++;
            continue;
        }
        if (count == 0) count = 1;
        char spec = *p++;

        for (int r = 0; r < count; r++) {
            if (spec == 'x') {
                offset += 1;
                continue;
            }
            int64_t val = 0;
            double fval = 0;
            if (val_idx < values->length) {
                if (values->items[val_idx].tag == FPY_TAG_FLOAT)
                    fval = values->items[val_idx].data.f;
                else
                    val = values->items[val_idx].data.i;
                val_idx++;
            }
            int item_size = fpy_struct_item_size(spec);
            if (spec == 'f') {
                float f32 = (float)fval;
                memcpy(buf + offset, &f32, 4);
            } else if (spec == 'd') {
                memcpy(buf + offset, &fval, 8);
            } else {
                /* Integer — write in appropriate endianness */
                if (big_endian) {
                    for (int i = item_size - 1; i >= 0; i--)
                        buf[offset + (item_size - 1 - i)] = (char)((val >> (i * 8)) & 0xFF);
                } else {
                    for (int i = 0; i < item_size; i++)
                        buf[offset + i] = (char)((val >> (i * 8)) & 0xFF);
                }
            }
            offset += item_size;
        }
        count = 0;
    }
    return buf;
}

/* struct.unpack(fmt, buffer) → list of values */
FpyList* fastpy_struct_unpack(const char *fmt, const char *buf) {
    FpyList *result = fpy_list_new(8);
    const char *p = fmt;
    int big_endian = 0;

    if (*p == '>' || *p == '!') { big_endian = 1; p++; }
    else if (*p == '<') { big_endian = 0; p++; }
    else if (*p == '@' || *p == '=') { p++; }

    int offset = 0, count = 0;
    while (*p) {
        if (*p >= '0' && *p <= '9') {
            count = count * 10 + (*p - '0');
            p++;
            continue;
        }
        if (count == 0) count = 1;
        char spec = *p++;

        for (int r = 0; r < count; r++) {
            if (spec == 'x') {
                offset += 1;
                continue;
            }
            int item_size = fpy_struct_item_size(spec);
            FpyValue v;

            if (spec == 'f') {
                float f32;
                memcpy(&f32, buf + offset, 4);
                v.tag = FPY_TAG_FLOAT; v.data.f = (double)f32;
            } else if (spec == 'd') {
                double f64;
                memcpy(&f64, buf + offset, 8);
                v.tag = FPY_TAG_FLOAT; v.data.f = f64;
            } else {
                /* Integer — read in appropriate endianness */
                uint64_t uval = 0;
                if (big_endian) {
                    for (int i = 0; i < item_size; i++)
                        uval = (uval << 8) | (uint8_t)buf[offset + i];
                } else {
                    for (int i = item_size - 1; i >= 0; i--)
                        uval = (uval << 8) | (uint8_t)buf[offset + i];
                }
                /* Sign extension for signed types */
                int64_t ival = (int64_t)uval;
                if (spec == 'b' && (uval & 0x80)) ival = (int64_t)(int8_t)uval;
                if (spec == 'h' && (uval & 0x8000)) ival = (int64_t)(int16_t)uval;
                if (spec == 'i' && (uval & 0x80000000ULL)) ival = (int64_t)(int32_t)uval;
                v.tag = FPY_TAG_INT; v.data.i = ival;
            }
            fpy_list_append(result, v);
            offset += item_size;
        }
        count = 0;
    }
    return result;
}

/* struct.pack_into — not yet needed, most code uses pack() */

/* ============================================================
 * Native pathlib module
 * ============================================================
 * Path is represented as a plain string (const char*).
 * All methods are thin wrappers over the existing os.path functions.
 */

/* Forward declarations for os.path functions (defined in objects.c) */
extern int64_t fastpy_os_path_exists(const char *path);
extern int64_t fastpy_os_path_isfile(const char *path);
extern int64_t fastpy_os_path_isdir(const char *path);
extern const char* fastpy_os_path_join(const char *a, const char *b);
extern const char* fastpy_os_path_basename(const char *path);
extern const char* fastpy_os_path_dirname(const char *path);
extern const char* fastpy_os_getcwd(void);
extern FpyList* fastpy_os_listdir(const char *path);

/* Path(str) → just returns the string (Path IS a string internally) */
const char* fastpy_path_new(const char *s) {
    return s ? fpy_strdup(s) : fpy_strdup(".");
}

/* Path.cwd() → current working directory */
const char* fastpy_path_cwd(void) {
    return fastpy_os_getcwd();
}

/* path / other → join paths (operator /) */
const char* fastpy_path_join(const char *self, const char *other) {
    return fastpy_os_path_join(self, other);
}

/* path.exists() → bool */
int64_t fastpy_path_exists(const char *self) {
    return fastpy_os_path_exists(self);
}

/* path.is_file() → bool */
int64_t fastpy_path_is_file(const char *self) {
    return fastpy_os_path_isfile(self);
}

/* path.is_dir() → bool */
int64_t fastpy_path_is_dir(const char *self) {
    return fastpy_os_path_isdir(self);
}

/* path.name → basename */
const char* fastpy_path_name(const char *self) {
    return fastpy_os_path_basename(self);
}

/* path.parent → dirname */
const char* fastpy_path_parent(const char *self) {
    return fastpy_os_path_dirname(self);
}

/* path.suffix → extension (e.g. ".py") */
const char* fastpy_path_suffix(const char *self) {
    const char *base = fastpy_os_path_basename(self);
    const char *dot = NULL;
    for (const char *p = base; *p; p++) {
        if (*p == '.') dot = p;
    }
    if (dot && dot != base) return fpy_strdup(dot);
    return fpy_strdup("");
}

/* path.stem → filename without extension */
const char* fastpy_path_stem(const char *self) {
    const char *base = fastpy_os_path_basename(self);
    const char *dot = NULL;
    for (const char *p = base; *p; p++) {
        if (*p == '.') dot = p;
    }
    if (dot && dot != base) {
        int len = (int)(dot - base);
        char *buf = (char*)malloc(len + 1);
        memcpy(buf, base, len);
        buf[len] = '\0';
        return buf;
    }
    return fpy_strdup(base);
}

/* path.resolve() → absolute path */
const char* fastpy_path_resolve(const char *self) {
#ifdef _WIN32
    char buf[4096];
    DWORD n = GetFullPathNameA(self, sizeof(buf), buf, NULL);
    if (n > 0 && n < sizeof(buf)) return fpy_strdup(buf);
    return fpy_strdup(self);
#else
    char *resolved = realpath(self, NULL);
    if (resolved) return resolved;  /* realpath mallocs */
    return fpy_strdup(self);
#endif
}

/* path.iterdir() → list of Path strings in directory */
FpyList* fastpy_path_iterdir(const char *self) {
    return fastpy_os_listdir(self);
}

/* path.read_text() → file contents as string */
const char* fastpy_path_read_text(const char *self) {
    FILE *f = fopen(self, "rb");
    if (!f) return fpy_strdup("");
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = (char*)malloc(size + 1);
    fread(buf, 1, size, f);
    buf[size] = '\0';
    fclose(f);
    return buf;
}

/* path.write_text(content) → writes string to file */
void fastpy_path_write_text(const char *self, const char *content) {
    FILE *f = fopen(self, "w");
    if (!f) return;
    fputs(content, f);
    fclose(f);
}

/* str(path) / repr(path) — just returns the path string */
const char* fastpy_path_str(const char *self) {
    return self;
}

/* path.with_suffix(suffix) → new path with different extension */
const char* fastpy_path_with_suffix(const char *self, const char *suffix) {
    /* Find the last dot in basename */
    const char *base_start = self;
    for (const char *p = self; *p; p++) {
        if (*p == '/' || *p == '\\') base_start = p + 1;
    }
    const char *dot = NULL;
    for (const char *p = base_start; *p; p++) {
        if (*p == '.') dot = p;
    }
    int prefix_len = dot ? (int)(dot - self) : (int)strlen(self);
    int suffix_len = (int)strlen(suffix);
    char *buf = (char*)malloc(prefix_len + suffix_len + 1);
    memcpy(buf, self, prefix_len);
    memcpy(buf + prefix_len, suffix, suffix_len + 1);
    return buf;
}

/* ============================================================
 * textwrap module
 * ============================================================ */

/* textwrap.dedent(text) → remove common leading whitespace */
const char* fastpy_textwrap_dedent(const char *text) {
    /* Find minimum indentation (ignoring blank lines) */
    int min_indent = 9999;
    const char *p = text;
    while (*p) {
        /* Skip blank lines */
        if (*p == '\n') { p++; continue; }
        int indent = 0;
        while (*p == ' ') { indent++; p++; }
        if (*p && *p != '\n' && indent < min_indent) min_indent = indent;
        while (*p && *p != '\n') p++;
        if (*p == '\n') p++;
    }
    if (min_indent == 9999 || min_indent == 0) return fpy_strdup(text);

    /* Build dedented result */
    int64_t len = (int64_t)strlen(text);
    char *out = (char*)malloc(len + 1);
    char *o = out;
    p = text;
    while (*p) {
        /* Remove min_indent spaces from start of each non-blank line */
        int skipped = 0;
        while (*p == ' ' && skipped < min_indent) { p++; skipped++; }
        /* Copy rest of line */
        while (*p && *p != '\n') *o++ = *p++;
        if (*p == '\n') *o++ = *p++;
    }
    *o = '\0';
    return out;
}

/* textwrap.indent(text, prefix) → add prefix to each line */
const char* fastpy_textwrap_indent(const char *text, const char *prefix) {
    int64_t tlen = (int64_t)strlen(text);
    int64_t plen = (int64_t)strlen(prefix);
    /* Count lines */
    int64_t lines = 1;
    for (const char *p = text; *p; p++) if (*p == '\n') lines++;
    char *out = (char*)malloc(tlen + lines * plen + 1);
    char *o = out;
    const char *p = text;
    int at_line_start = 1;
    while (*p) {
        if (at_line_start && *p != '\n') {
            memcpy(o, prefix, plen); o += plen;
            at_line_start = 0;
        }
        if (*p == '\n') at_line_start = 1;
        *o++ = *p++;
    }
    *o = '\0';
    return out;
}

/* ============================================================
 * shutil module
 * ============================================================ */

/* shutil.copy(src, dst) — copy file */
void fastpy_shutil_copy(const char *src, const char *dst) {
    FILE *in = fopen(src, "rb");
    if (!in) return;
    FILE *out = fopen(dst, "wb");
    if (!out) { fclose(in); return; }
    char buf[8192];
    size_t n;
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0)
        fwrite(buf, 1, n, out);
    fclose(in);
    fclose(out);
}

/* shutil.rmtree — remove directory recursively (simplified: single file or empty dir) */
void fastpy_shutil_rmtree(const char *path) {
#ifdef _WIN32
    /* On Windows, use system command for simplicity */
    char cmd[4096];
    snprintf(cmd, sizeof(cmd), "rmdir /s /q \"%s\" 2>NUL", path);
    system(cmd);
#else
    char cmd[4096];
    snprintf(cmd, sizeof(cmd), "rm -rf '%s'", path);
    system(cmd);
#endif
}

/* ============================================================
 * glob module
 * ============================================================ */

/* glob.glob(pattern) → list of matching paths (simplified: only *.ext in cwd) */
FpyList* fastpy_glob_glob(const char *pattern) {
    FpyList *result = fpy_list_new(16);
    /* Extract directory and file pattern */
    const char *last_sep = NULL;
    for (const char *p = pattern; *p; p++)
        if (*p == '/' || *p == '\\') last_sep = p;

    char dir[4096] = ".";
    const char *file_pattern = pattern;
    if (last_sep) {
        int dlen = (int)(last_sep - pattern);
        memcpy(dir, pattern, dlen);
        dir[dlen] = '\0';
        file_pattern = last_sep + 1;
    }

    /* Simple wildcard matching: *.ext */
    const char *star = strchr(file_pattern, '*');
    const char *suffix = star ? star + 1 : "";

#ifdef _WIN32
    char search[4096];
    snprintf(search, sizeof(search), "%s\\%s", dir, file_pattern);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(search, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (fd.cFileName[0] == '.') continue;
            char full[4096];
            if (last_sep)
                snprintf(full, sizeof(full), "%s\\%s", dir, fd.cFileName);
            else
                snprintf(full, sizeof(full), "%s", fd.cFileName);
            FpyValue v; v.tag = FPY_TAG_STR; v.data.s = fpy_strdup(full);
            fpy_list_append(result, v);
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
#else
    DIR *d = opendir(dir);
    if (d) {
        struct dirent *ent;
        while ((ent = readdir(d))) {
            if (ent->d_name[0] == '.') continue;
            /* Check if name matches the suffix pattern */
            if (suffix[0]) {
                int nlen = strlen(ent->d_name);
                int slen = strlen(suffix);
                if (nlen < slen) continue;
                if (strcmp(ent->d_name + nlen - slen, suffix) != 0) continue;
            }
            char full[4096];
            if (last_sep)
                snprintf(full, sizeof(full), "%s/%s", dir, ent->d_name);
            else
                snprintf(full, sizeof(full), "%s", ent->d_name);
            FpyValue v; v.tag = FPY_TAG_STR; v.data.s = fpy_strdup(full);
            fpy_list_append(result, v);
        }
        closedir(d);
    }
#endif
    return result;
}

/* ============================================================
 * tempfile module
 * ============================================================ */

/* tempfile.gettempdir() → temp directory path */
const char* fastpy_tempfile_gettempdir(void) {
#ifdef _WIN32
    char buf[4096];
    DWORD n = GetTempPathA(sizeof(buf), buf);
    if (n > 0) {
        /* Remove trailing backslash */
        if (n > 0 && buf[n-1] == '\\') buf[n-1] = '\0';
        return fpy_strdup(buf);
    }
    return fpy_strdup("C:\\Temp");
#else
    const char *tmp = getenv("TMPDIR");
    if (tmp) return fpy_strdup(tmp);
    return fpy_strdup("/tmp");
#endif
}

/* tempfile.mkdtemp() → create and return path to temp directory */
const char* fastpy_tempfile_mkdtemp(void) {
#ifdef _WIN32
    char tmp[4096], path[4096];
    GetTempPathA(sizeof(tmp), tmp);
    snprintf(path, sizeof(path), "%sfpy_%08x", tmp, (uint32_t)fpy_rng_next());
    CreateDirectoryA(path, NULL);
    return fpy_strdup(path);
#else
    char tmpl[] = "/tmp/fpy_XXXXXX";
    char *result = mkdtemp(tmpl);
    return result ? fpy_strdup(result) : fpy_strdup("/tmp/fpy_fallback");
#endif
}

/* ============================================================
 * heapq module — binary min-heap operations on lists
 * ============================================================ */

static void fpy_sift_down(FpyList *lst, int64_t start, int64_t end) {
    int64_t root = start;
    while (root * 2 + 1 <= end) {
        int64_t child = root * 2 + 1;
        int64_t swap = root;
        if (lst->items[child].data.i < lst->items[swap].data.i)
            swap = child;
        if (child + 1 <= end && lst->items[child+1].data.i < lst->items[swap].data.i)
            swap = child + 1;
        if (swap == root) return;
        FpyValue tmp = lst->items[root];
        lst->items[root] = lst->items[swap];
        lst->items[swap] = tmp;
        root = swap;
    }
}

static void fpy_sift_up(FpyList *lst, int64_t pos) {
    while (pos > 0) {
        int64_t parent = (pos - 1) / 2;
        if (lst->items[pos].data.i < lst->items[parent].data.i) {
            FpyValue tmp = lst->items[pos];
            lst->items[pos] = lst->items[parent];
            lst->items[parent] = tmp;
            pos = parent;
        } else break;
    }
}

/* heapq.heapify(list) — transform list into a heap in-place */
void fastpy_heapq_heapify(FpyList *lst) {
    for (int64_t i = lst->length / 2 - 1; i >= 0; i--)
        fpy_sift_down(lst, i, lst->length - 1);
}

/* heapq.heappush(heap, item) — push item onto heap */
void fastpy_heapq_heappush(FpyList *lst, int32_t tag, int64_t data) {
    FpyValue v; v.tag = tag; v.data.i = data;
    fpy_list_append(lst, v);
    fpy_sift_up(lst, lst->length - 1);
}

/* heapq.heappop(heap) → smallest item */
int64_t fastpy_heapq_heappop(FpyList *lst) {
    if (lst->length == 0) return 0;
    int64_t result = lst->items[0].data.i;
    lst->items[0] = lst->items[lst->length - 1];
    lst->length--;
    if (lst->length > 0)
        fpy_sift_down(lst, 0, lst->length - 1);
    return result;
}

/* heapq.nsmallest(n, list) → list of n smallest */
FpyList* fastpy_heapq_nsmallest(int64_t n, FpyList *lst) {
    /* Simple: sort a copy and take first n */
    FpyList *copy = fpy_list_new(lst->length);
    for (int64_t i = 0; i < lst->length; i++)
        fpy_list_append(copy, lst->items[i]);
    /* Selection sort for n elements */
    for (int64_t i = 0; i < n && i < copy->length; i++) {
        int64_t min_idx = i;
        for (int64_t j = i + 1; j < copy->length; j++)
            if (copy->items[j].data.i < copy->items[min_idx].data.i)
                min_idx = j;
        if (min_idx != i) {
            FpyValue tmp = copy->items[i];
            copy->items[i] = copy->items[min_idx];
            copy->items[min_idx] = tmp;
        }
    }
    FpyList *result = fpy_list_new(n);
    for (int64_t i = 0; i < n && i < copy->length; i++)
        fpy_list_append(result, copy->items[i]);
    free(copy->items); free(copy);
    return result;
}

/* ============================================================
 * bisect module — binary search on sorted lists
 * ============================================================ */

/* bisect.bisect_left(list, x) → insertion index */
int64_t fastpy_bisect_left(FpyList *lst, int64_t x) {
    int64_t lo = 0, hi = lst->length;
    while (lo < hi) {
        int64_t mid = (lo + hi) / 2;
        if (lst->items[mid].data.i < x)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo;
}

/* bisect.bisect_right(list, x) → insertion index */
int64_t fastpy_bisect_right(FpyList *lst, int64_t x) {
    int64_t lo = 0, hi = lst->length;
    while (lo < hi) {
        int64_t mid = (lo + hi) / 2;
        if (lst->items[mid].data.i <= x)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo;
}

/* bisect.insort(list, x) — insert x in sorted position */
void fastpy_bisect_insort(FpyList *lst, int64_t x) {
    int64_t pos = fastpy_bisect_right(lst, x);
    /* Grow and shift elements */
    FpyValue v; v.tag = FPY_TAG_INT; v.data.i = x;
    fpy_list_append(lst, v);  /* make room */
    for (int64_t i = lst->length - 1; i > pos; i--)
        lst->items[i] = lst->items[i - 1];
    lst->items[pos] = v;
}
