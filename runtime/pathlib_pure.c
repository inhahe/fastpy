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
 * A Path is an `FpyPurePath` header block (see the long comment above the
 * struct): magic at offset 0, a zero guard word at offset 32, and the
 * NUL-terminated path text at offset 40. The pointer handed to the codegen is
 * the header base, NOT the text — the offsets exist specifically so the
 * OBJ refcount dispatcher's blind magic probes can never mistake path text for
 * an object. Use `_p()` internally, or the exported `fastpy_path_as_cstr()`
 * from another translation unit; never cast a Path straight to `char *`.
 *
 * Path-returning functions hand back a fresh header block; property getters
 * (name/suffix/stem/str) hand back a fresh `fpy_str_alloc`-headed string. Both
 * are treated as borrowed by the codegen, mirroring the host bridge's
 * ownership convention, so there is no new lifetime hazard versus host mode.
 *
 * Filesystem predicates (exists/is_file/is_dir) delegate to the native
 * os.path.* helpers in objects.c (fastpy_os_path_exists/isfile/isdir), which
 * are already compiled into the pure build and proven on-target — so this file
 * introduces no new struct-stat ABI dependency of its own.
 *
 * The whole pathlib.Path surface the codegen emits is implemented here; there
 * is full parity with the bridge.
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>

/* The real object-system header, for FpyValue / FpyList / fpy_str_alloc. This
 * TU used to hand-copy those declarations to avoid objects.h's threading.h and
 * gc.h includes, but objects.c itself is compiled into every pure build with
 * the same flags, so the header is known to build here — and a hand-copied
 * struct layout is an ABI duplicate waiting to drift. */
#include "objects.h"

/* Native os.path.* predicates (objects.c) — struct-stat-backed, proven on-target. */
extern int64_t fastpy_os_path_exists(const char *path);
extern int64_t fastpy_os_path_isfile(const char *path);
extern int64_t fastpy_os_path_isdir(const char *path);

/* Raise machinery (runtime.c). RuntimeError == 6 (matches bridge_stub.c). */
extern void fastpy_raise(int exc_type, const char *msg);
#define FPY_PURE_EXC_RUNTIMEERROR 6

/*
 * String results and the refcounted-string ABI (FpyString / fpy_str_alloc,
 * from objects.h).
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

/* Copy `n` bytes of `src` into a fresh, properly-headed refcounted fastpy
 * string and return its `data` pointer (what the codegen treats as the STR). */
static const char *_str_n(const char *src, size_t n) {
    FpyString *s = fpy_str_alloc((int64_t)n);
    if (s) {
        if (n) memcpy(s->data, src, n);
        /* fpy_str_alloc already wrote the terminating NUL at data[n]. */
        return s->data;
    }
    /* OOM: fall back to an empty headed string so the caller still hands back
     * an RC-safe STR (never a bare literal that would break fpy_str_header). */
    FpyString *e = fpy_str_alloc(0);
    return e ? e->data : "";
}
static const char *_str_dup(const char *src) { return _str_n(src, strlen(src)); }

/* --- Pure-mode Path object layout -------------------------------------- *
 *
 * The codegen tags a pathlib.Path as FPY_TAG_OBJ (tag 6) and wraps every use in
 * fpy_rc_incref/decref. For an OBJ, that dispatcher (objects.c) has no type
 * information, so it *probes* the pointer: it reads a would-be FpyObj magic at
 * BYTE OFFSET 32 and a would-be FpyClosure magic at OFFSET 0, and only when
 * neither matches does it fall through to the pure-mode bridge no-ops
 * (bridge_stub.c) that correctly leave a Path alone.
 *
 * Storing the path text at offset 0 (the obvious "a Path is just a char*"
 * representation) makes both probes read path *text*:
 *   - offset 32 is out of bounds for any path shorter than 36 bytes, so the
 *     dispatcher reads adjacent heap bytes; when those spuriously equal
 *     FPY_OBJ_MAGIC the decref treats the Path as a real object and FREES it.
 *   - even with zero padding to keep that read in bounds, a path of >= 36 bytes
 *     puts real text under the probe, so a path whose bytes 32..35 happen to
 *     spell "SJBO" (FPY_OBJ_MAGIC == 0x4F424A53) still misfires.
 *
 * Fix: give a Path a real header and put the text at offset 40, past BOTH
 * probe sites. Every byte the dispatcher inspects is then one we control:
 * offset 0 holds FPY_PURE_PATH_MAGIC (never FPY_CLOSURE_MAGIC) and offset 32
 * holds a zero guard (never FPY_OBJ_MAGIC). The OBJ incref/decref therefore
 * take the bridge no-op path deterministically, for every possible path string.
 *
 * The pointer handed to the codegen is the header base, so anything that wants
 * the text must go through _p() / fastpy_path_as_cstr(). */
#define FPY_PURE_PATH_MAGIC 0x48544150  /* "PATH" */

typedef struct {
    int32_t magic;         /* offset 0  — FPY_PURE_PATH_MAGIC, != CLOSURE magic */
    int32_t _pad0;
    char    _reserved[24];
    int32_t guard;         /* offset 32 — always 0, != FPY_OBJ_MAGIC */
    int32_t _pad1;
    char    data[];        /* offset 40 — NUL-terminated path text */
} FpyPurePath;

/* A NULL/empty path behaves like CPython's Path('') / Path('.') == '.'. */
static const char *_p(void *self) {
    if (!self) return ".";
    const FpyPurePath *h = (const FpyPurePath *)self;
    /* Every Path reaching here was built by _path_alloc_n below, so the header
     * is always present; the magic check is a cheap assertion that also keeps
     * the accessor honest if a non-Path ever reaches a Path entry point. */
    if (h->magic != FPY_PURE_PATH_MAGIC) return ".";
    return *h->data ? h->data : ".";
}

/* Public accessor: lets Path consumers compiled into OTHER translation units
 * (runtime.c's fastpy_path_with_suffix) reach the text without duplicating the
 * layout. Host builds don't compile this TU and keep their own representation. */
const char *fastpy_path_as_cstr(const void *self) {
    return _p((void *)(uintptr_t)self);
}

/* Identify an arbitrary OBJ-tagged pointer as a Path, or report that it isn't.
 *
 * This is what the header bought us beyond collision-safety. Codegen tags a
 * Path OBJ, so every generic OBJ consumer in objects.c (print / str / repr /
 * write) reaches a pointer it cannot type, and its fallback is the CPython
 * bridge — which in a pure build is a stub that RAISES. Before the header there
 * was no way to tell a Path from a PyObject*, so `print(p)` had to fail; now the
 * magic at offset 0 answers exactly that question, and the generic paths can
 * dispatch a Path natively instead of bridging.
 *
 * Returns the path text, or NULL if `p` is not an FpyPurePath. Unlike
 * fastpy_path_as_cstr() this never substitutes "." — callers need to
 * distinguish "not a Path" from "a Path whose text is empty". */
const char *fpy_pure_path_text(const void *p) {
    if (!p) return NULL;
    const FpyPurePath *h = (const FpyPurePath *)p;
    if (h->magic != FPY_PURE_PATH_MAGIC) return NULL;
    return *h->data ? h->data : ".";
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

/* --- Path allocation ----------------------------------------------------- *
 * Builds the headed layout documented at FpyPurePath above: caller-visible
 * pointer is the header base, path text lives at offset 40. (STR results —
 * name/suffix/stem/str/read_text — are NOT Paths; they go through
 * fpy_str_alloc and carry the FpyString refcount header instead.) */
static void *_path_alloc_n(const char *s, size_t n) {
    FpyPurePath *h = (FpyPurePath *)malloc(sizeof(FpyPurePath) + n + 1);
    if (!h) return NULL;
    /* Zero the whole header so `guard` (offset 32) and the reserved bytes can
     * never coincide with FPY_OBJ_MAGIC, then stamp the identifying magic. */
    memset(h, 0, sizeof(FpyPurePath));
    h->magic = FPY_PURE_PATH_MAGIC;
    if (n) memcpy(h->data, s, n);
    h->data[n] = '\0';
    return (void *)h;
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

/* path.with_suffix(suffix) -> Path with the basename's extension replaced.
 *
 * Pure-mode override of the runtime.c implementation (which is compiled only
 * for non-pure builds). Both differences matter here: `self` is a headed Path,
 * not bare text, and the codegen tags the RESULT as a Path too — so this must
 * hand back a headed Path rather than the plain string buffer runtime.c
 * returns, or every subsequent operation on it would fail the header check. */
void *fastpy_path_with_suffix(void *self, const char *suffix) {
    const char *p = _p(self);
    if (!suffix) suffix = "";
    size_t bl;
    const char *b = _basename(p, &bl);
    /* Last dot that is neither first nor last char of the basename (PurePath). */
    long d = -1;
    for (long i = 0; i < (long)bl; i++)
        if (b[i] == '.') d = i;
    size_t keep = (d > 0 && d < (long)bl - 1) ? (size_t)d : bl;
    size_t prefix_len = (size_t)(b - p) + keep;   /* dirname + stem */
    size_t sl = strlen(suffix);

    char *tmp = (char *)malloc(prefix_len + sl + 1);
    if (!tmp) return _path_alloc(p);
    memcpy(tmp, p, prefix_len);
    memcpy(tmp + prefix_len, suffix, sl + 1);
    void *out = _path_alloc_n(tmp, prefix_len + sl);
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

/* --- Directory listing --------------------------------------------------- *
 *
 * The codegen types `p.iterdir()` as list[Path] (see _infer_type_tag in
 * compiler/codegen.py), so BOTH runtimes materialize the listing eagerly and
 * return an FpyList* whose elements are OBJ-tagged Path pointers. The bridge
 * has always been eager too (PySequence_List over the generator), so this is
 * not a behavioural change versus host mode — CPython's laziness is the thing
 * neither runtime ever had.
 *
 * Entries are yielded in readdir() order, exactly like CPython's iterdir();
 * '.' and '..' are skipped, again matching CPython.
 *
 * Element ownership: fpy_list_append increfs each element, which for an OBJ
 * routes through fpy_rc_incref. Thanks to the FpyPurePath header that probe
 * deterministically misses and lands on the pure-mode bridge no-op, so a Path
 * is neither freed nor double-counted by list bookkeeping — the same
 * allocate-and-leak lifetime every other pure-mode Path already has. */

void *fastpy_path_iterdir(void *self) {
    const char *p = _p(self);
    FpyList *out = fpy_list_new(8);
    DIR *d = opendir(p);
    if (!d) {
        /* Unlike read_text (which degrades to "" on a missing file), a failed
         * listing gets an exception: an empty list is indistinguishable from a
         * genuinely empty directory, so a caller would silently skip work.
         *
         * But still return a valid empty list, never NULL. fastpy_raise only
         * SETS a pending-exception flag — it does not unwind — and codegen
         * only tests that flag at statement boundaries, so the caller consumes
         * this return value first. `for x in p.iterdir()` immediately calls
         * fastpy_list_length on it, which faults on NULL. */
        fastpy_raise(FPY_PURE_EXC_RUNTIMEERROR,
                     "Path.iterdir(): cannot open directory");
        return (void *)out;
    }

    /* Precompute the parent prefix so each entry is one join, not a strlen
     * per iteration. Path('/') already ends in '/', so don't double it. */
    size_t plen = strlen(p);
    int need_slash = (plen > 0 && p[plen - 1] != '/');

    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        const char *nm = ent->d_name;
        if (nm[0] == '.' && (nm[1] == '\0' || (nm[1] == '.' && nm[2] == '\0')))
            continue;
        size_t nlen = strlen(nm);
        size_t total = plen + (size_t)need_slash + nlen;
        char *joined = (char *)malloc(total + 1);
        if (!joined) continue;   /* skip this entry rather than abort the walk */
        memcpy(joined, p, plen);
        if (need_slash) joined[plen] = '/';
        memcpy(joined + plen + (size_t)need_slash, nm, nlen);
        joined[total] = '\0';
        void *child = _path_alloc_n(joined, total);
        free(joined);
        if (!child) continue;
        FpyValue v;
        v.tag = FPY_TAG_OBJ;
        v.data.obj = (FpyObj *)child;
        fpy_list_append(out, v);
    }
    closedir(d);
    return (void *)out;
}
