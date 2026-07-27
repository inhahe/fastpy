/*
 * fastpy — exception type codes, shared by every runtime translation unit.
 *
 * These numbers are a wire format: codegen emits them as immediates into the
 * `fastpy_raise` calls it generates, `fastpy_raise` maps them back to class
 * names for `type(e).__name__`, and each runtime .c raises with them directly.
 * They had been re-#defined per file ("mirror runtime.c", said objects.c),
 * which is fine right up until one copy gains a code the others don't and a
 * raise starts reporting the wrong class. One definition removes that whole
 * category of drift; the compiler-side copy still has to agree by hand, and is
 * marked as such in codegen.py.
 */
#ifndef FPY_EXCEPTIONS_H
#define FPY_EXCEPTIONS_H

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
#define FPY_EXC_OVERFLOWERROR  10
#define FPY_EXC_ATTRIBUTEERROR 11
/* Raised by a user-defined exception class; the class name is supplied
 * separately via fastpy_exc_set_class_name, so don't overwrite it. */
#define FPY_EXC_GENERIC        99

/* Defined in runtime.c. Declared here so a raising translation unit doesn't
 * have to re-declare it alongside a private copy of the codes above. */
void fastpy_raise(int exc_type, const char *msg);
int  fastpy_exc_pending(void);

#endif /* FPY_EXCEPTIONS_H */
