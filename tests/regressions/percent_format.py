# Regression: % string formatting with precision/width specifiers.
# Before fix: the runtime only handled bare %s/%d/%f — any prefix like
# %.2f or %5d caused the entire spec to be emitted literally and the arg
# to be silently dropped.

print("pi is %.2f" % 3.14159)
print("integer %d" % 42)
print("string %s" % "hello")
print("two %s and %d" % ("abc", 99))
print("wide %5d" % 7)
print("padded %05d" % 42)
print("left %-5d|" % 42)
print("precision %.4f" % 0.123456789)
print("sci %.2e" % 1234.5)
print("hex %x" % 255)
print("upper hex %X" % 255)
print("octal %o" % 8)

# Edge: no args, no specs
print("plain text")
# Edge: literal %
print("50%% done")
