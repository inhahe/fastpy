/*
 * fastpy pure-mode pathlib.Path runtime.
 *
 * In "pure mode" (SlateOS / Q29 option A: AOT-compile to native without
 * embedding CPython) the runtime is linked WITHOUT cpython_bridge.c, so the
 * PyObject*-backed pathlib.Path functions defined there
 * (fastpy_path_new / _read_text / _write_text / _name / ...) are absent. A
 * pure-mode program that uses `pathlib.Path` would therefore fail to link.
 *
 * This translation unit provides a native, CPython-free implementation of the
 * whole pathlib.Path surface the codegen emits. It is compiled ONLY for the
 * SlateOS pure-mode/cross target (added to `_SLATEOS_RUNTIME_NAMES` in
 * compiler/toolchain.py, alongside bridge_stub.c); the host build keeps using
 * cpython_bridge.c, so these definitions never collide with the bridge ones.
 *
 * ## Pure-mode Path representation
 *
 * A Path is simply a heap-allocated NUL-terminated C string holding the path
 * text (an `i8*` at the IR level — exactly what `fastpy_path_new` already
 * returns to the codegen, and what the already-native `fastpy_path_with_suffix`
 * in runtime.c already assumes). Every function here therefore treats its
 * `void *self` argument as `const char *`. Path-returning functions hand back a
 * fresh heap string; property getters (name/suffix/stem/str) do the same. This
 * mirrors the host bridge's strdup-based ownership convention (the returned
 * pointers are treated as borrowed C strings by the codegen, exactly as the
 * bridge's were), so there is no new lifetime hazard versus host mode.
 *
 * Filesystem predicates (exists/is_file/is_dir) delegate to the native
 * os.path.* helpers in objects.c (fastpy_os_path_exists/isfile/isdir), which
 * are already compiled into the pure build and proven on-target — so this file
 * introduces no new struct-stat ABI dependency of its own.
 *
 * ## Deferred
 *
 * `Path.iterdir()` (a directory listing yielding Path objects) needs the
 * runtime list-builder API and is not yet wired here; in pure mode it raises a
 * catchable RuntimeError rather than silently returning wrong data. Everything
 * else has full parity with the bridge.
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Native os.path.* predicates (objects.c) — struct-stat-backed, proven on-target. */
extern int64_t fastpy_os_path_exists(const char *path);
extern int64_t fastpy_os_path_isfile(const char *path);
extern int64_t fastpy_os_path_isdir(const char *path);

/* Raise machinery (runtime.c). RuntimeError == 6 (matches bridge_stub.c). */
extern void fastpy_raise(int exc_type, const char *msg);
#define FPY_PURE_EXC_RUNTIMEERROR 6

/*
 * fastpy refcounted-string ABI (mirrors runtime/objects.h — kept as a local
 * forward-declaration so this TU doesn't have to pull in objects.h's
 * threading.h/gc.h dependencies; the layout is stable ABI).
 *
 * CRITICAL: every value the codegen tags FPY_TAG_STR (str) — which is what it
 * assigns to the results of Path.name/.suffix/.stem/str(Path)/read_text — MUST
 * be an `FpyString`-headed buffer, NOT a bare strdup/malloc. The runtime's
 * refcount machinery (fpy_str_header / fpy_str_incref / fpy_str_decref in
 * objects.h) locates an 8-byte {magic, refcount} header at `data - 8` and, on
 * the temporary's decref, frees `header` when the count hits zero. A bare
 * `strdup` has no such header: `fpy_str_header` reads whatever 8 bytes precede
 * the allocation, and on the SlateOS heap allocator that word can collide with
 * FPY_STR_MAGIC, causing `free(data - 8)` to release a wild pointer and corrupt
 * the heap — which manifested as every Path check AFTER the first read_text
 * silently returning the wrong result. (The host build survives the same bare
 * strdup only because its libc malloc metadata never collides with the magic.)
 * Allocating through `fpy_str_alloc` gives the header a well-defined magic +
 * refcount so incref/decref manage and free the string correctly.
 */
typedef struct {
    int32_t magic;
    int32_t refcount;
    char data[];   /* flexible array member — NUL-terminated UTF-8 */
} FpyPureString;
extern FpyPureString *fpy_str_alloc(int64_t len);

/* Copy `n` bytes of `src` into a fresh, properly-headed refcounted fastpy
 * string and return its `data` pointer (what the codegen treats as the STR). */
static const char *_str_n(const char *src, size_t n) {
    FpyPureString *s = fpy_str_alloc((int64_t)n);
    if (s) {
        if (n) memcpy(s->data, src, n);
        /* fpy_str_alloc already wrote the terminating NUL at data[n]. */
        return s->data;
    }
    /* OOM: fall back to an empty headed string so the caller still hands back
     * an RC-safe STR (never a bare literal that would break fpy_str_header). */
    FpyPureString *e = fpy_str_alloc(0);
    return e ? e->data : "";
}
static const char *_str_dup(const char *src) { return _str_n(src, strlen(src)); }

/* A NULL/empty path behaves like CPython's Path('') / Path('.') == '.'. */
static const char *_p(void *self) {
    const char *s = (const char *)self;
    return (s && *s) ? s : ".";
}

/* Locate the basename within `p`, honoring trailing-slash stripping the way
 * PurePath does (Path('/a/b/') == Path('/a/b')). Writes the basename length
 * into *blen and returns a pointer into `p` at the basename start. */
static const char *_basename(const char *p, size_t *blen) {
    size_t n = strlen(p);
    while (n > 1 && p[n - 1] == '/') n--;   /* strip trailing '/', keep root */
    size_t i = n;
    while (i > 0 && p[i - 1] != '/') i--;   /* back up to just past last '/' */
    *blen = n - i;
    return p + i;
}

/* --- Path (OBJ-tagged) allocation --------------------------------------- *
 *
 * CRITICAL: the codegen tags a pathlib.Path as FPY_TAG_OBJ (tag 6) and wraps
 * every use in fpy_rc_incref/decref. For an OBJ, that dispatcher (objects.c)
 * inspects a would-be `FpyObj` magic at BYTE OFFSET 32 and a would-be
 * `FpyClosure` magic at offset 0; only if neither matches does it fall through
 * to the pure-mode bridge no-ops (bridge_stub.c) that correctly leave the Path
 * alone. A bare `strdup`'d path (e.g. "/tmp/fpy-pathlib.txt", 21 bytes) is
 * SHORTER than 36 bytes, so that offset-32 read is OUT OF BOUNDS: it reads
 * whatever adjacent heap bytes happen to sit there, and when those spuriously
 * equal FPY_OBJ_MAGIC the decref treats the Path as a real object and FREES it
 * — corrupting every subsequent Path operation. Because the colliding bytes
 * depend on heap layout, the failure is order-dependent: a program that reads
 * the file first then checks exists()/name() saw the Path freed after the first
 * statement (only the first check passed), while the same checks reordered
 * ahead of read_text() all passed.
 *
 * Fix: allocate every Path buffer with enough ZEROED padding that offset 32 is
 * always in-bounds and reads as 0 (never FPY_OBJ_MAGIC), while offset 0 holds
 * the path text (never FPY_CLOSURE_MAGIC == "SOLC" for a real path). The OBJ
 * incref/decref then deterministically take the pure-mode bridge no-op path, so
 * a Path is never freed out from under the program. (STR results — name/suffix/
 * stem/str/read_text — go through fpy_str_alloc instead and are unaffected.) */
#define FPY_PURE_PATH_MIN 40  /* > offset 32 + sizeof(int32_t), with slack */

static void *_path_alloc_n(const char *s, size_t n) {
    size_t cap = n + 1;
    if (cap < FPY_PURE_PATH_MIN) cap = FPY_PURE_PATH_MIN;
    char *out = (char *)malloc(cap);
    if (!out) return NULL;
    memset(out, 0, cap);       /* zero the padding so offset 32 reads as 0 */
    if (n) memcpy(out, s, n);  /* terminating NUL already present from memset */
    return (void *)out;
}

static void *_path_alloc(const char *s) {
    if (!s || !*s) s = ".";    /* Path('') / NULL behaves like Path('.') */
    return _path_alloc_n(s, strlen(s));
}

/* --- Construction ------------------------------------------------------- */

void *fastpy_path_new(const char *s) {
    return _path_alloc(s);
}

void *fastpy_path_cwd(void) {
    char buf[4096];
    if (getcwd(buf, sizeof buf)) return _path_alloc(buf);
    return _path_alloc(".");
}

/* self / other. POSIX join: an absolute `other` replaces `self` entirely. */
void *fastpy_path_join(void *self, void *other) {
    const char *a = _p(self);
    const char *b = other ? (const char *)other : "";
    if (b[0] == '/') return _path_alloc(b);      /* absolute other wins */
    if (b[0] == '\0') return _path_alloc(a);
    size_t la = strlen(a);
    int need_sep = (la > 0 && a[la - 1] != '/');
    size_t lb = strlen(b);
    size_t total = la + (size_t)(need_sep ? 1 : 0) + lb;
    /* Build the joined text in a scratch buffer, then hand it to _path_alloc so
     * the result carries the same RC-safe zero padding as every other Path. */
    char *tmp = (char *)malloc(total + 1);
    if (!tmp) return _path_alloc(a);
    memcpy(tmp, a, la);
    size_t pos = la;
    if (need_sep) tmp[pos++] = '/';
    memcpy(tmp + pos, b, lb + 1);
    void *out = _path_alloc_n(tmp, total);
    free(tmp);
    return out;
}

/* --- Filesystem predicates (delegate to native os.path.*) --------------- */

int64_t fastpy_path_exists(void *self)  { return fastpy_os_path_exists(_p(self)); }
int64_t fastpy_path_is_file(void *self) { return fastpy_os_path_isfile(_p(self)); }
int64_t fastpy_path_is_dir(void *self)  { return fastpy_os_path_isdir(_p(self)); }

/* --- Name components ---------------------------------------------------- */

const char *fastpy_path_name(void *self) {
    size_t bl;
    const char *b = _basename(_p(self), &bl);
    return _str_n(b, bl);
}

void *fastpy_path_parent(void *self) {
    const char *p = _p(self);
    size_t n = strlen(p);
    while (n > 1 && p[n - 1] == '/') n--;   /* strip trailing '/' */
    size_t i = n;
    while (i > 0 && p[i - 1] != '/') i--;   /* i = just past last '/' (or 0) */
    if (i == 0) return _path_alloc(".");            /* no slash -> '.' */
    size_t plen = i - 1;                            /* drop the slash */
    if (plen == 0) return _path_alloc("/");         /* '/a' -> '/' */
    while (plen > 1 && p[plen - 1] == '/') plen--;  /* collapse extra '/' */
    return _path_alloc_n(p, plen);
}

/* CPython PurePath rule: the last '.' with 0 < idx < len-1 (dot neither the
 * first nor the last char of the basename) delimits the suffix. */
const char *fastpy_path_suffix(void *self) {
    size_t bl;
    const char *b = _basename(_p(self), &bl);
    long d = -1;
    for (long i = 0; i < (long)bl; i++)
        if (b[i] == '.') d = i;
    if (d > 0 && d < (long)bl - 1) {
        size_t sl = bl - (size_t)d;
        return _str_n(b + d, sl);
    }
    return _str_n("", 0);
}

const char *fastpy_path_stem(void *self) {
    size_t bl;
    const char *b = _basename(_p(self), &bl);
    long d = -1;
    for (long i = 0; i < (long)bl; i++)
        if (b[i] == '.') d = i;
    size_t keep = (d > 0 && d < (long)bl - 1) ? (size_t)d : bl;
    return _str_n(b, keep);
}

void *fastpy_path_resolve(void *self) {
    const char *p = _p(self);
    char buf[4096];
    char *r = realpath(p, buf);
    if (r) return _path_alloc(r);
    /* realpath failed (e.g. path does not exist): absolutize against cwd. */
    if (p[0] == '/') return _path_alloc(p);
    char cwd[4096];
    if (getcwd(cwd, sizeof cwd)) {
        size_t lc = strlen(cwd), lp = strlen(p);
        char *tmp = (char *)malloc(lc + 1 + lp + 1);
        if (!tmp) return _path_alloc(p);
        memcpy(tmp, cwd, lc);
        tmp[lc] = '/';
        memcpy(tmp + lc + 1, p, lp + 1);
        void *out = _path_alloc_n(tmp, lc + 1 + lp);
        free(tmp);
        return out;
    }
    return _path_alloc(p);
}

const char *fastpy_path_str(void *self) {
    return _str_dup(_p(self));
}

/* --- Text I/O (fopen/fread/fwrite — no bridge needed) ------------------- */

const char *fastpy_path_read_text(void *self) {
    const char *cpath = _p(self);
    FILE *f = fopen(cpath, "rb");
    if (!f) return _str_n("", 0);
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size < 0) size = 0;
    /* Read into a scratch buffer first, then hand back a properly-headed
     * fastpy string sized to the true byte count (short reads shrink it). */
    char *buf = (char *)malloc((size_t)size + 1);
    if (!buf) { fclose(f); return _str_n("", 0); }
    size_t got = fread(buf, 1, (size_t)size, f);
    fclose(f);
    const char *out = _str_n(buf, got);
    free(buf);
    return out;
}

void fastpy_path_write_text(void *self, const char *content) {
    const char *cpath = _p(self);
    FILE *f = fopen(cpath, "w");
    if (!f) return;
    if (content) fputs(content, f);
    fclose(f);
}

/* --- Deferred ----------------------------------------------------------- */

void *fastpy_path_iterdir(void *self) {
    (void)self;
    fastpy_raise(FPY_PURE_EXC_RUNTIMEERROR,
        "Path.iterdir() is not yet supported in pure-mode (no-CPython) builds");
    return (void *)0;
}
