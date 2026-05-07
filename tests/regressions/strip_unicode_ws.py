# Regression: str.strip() missing non-ASCII whitespace characters.
# Before fix: strip/lstrip/rstrip/isspace only checked space/tab/newline/cr.
# Fix: added \x0b \x0c \x1c-\x1f and UTF-8 sequences for U+0085 U+00A0.

# 1. Basic strip with \xa0 (NBSP)
print('\xa0 hello \xa0'.strip() == 'hello')

# 2. Strip with \x0b (vertical tab)
print('\x0b hello \x0b'.strip() == 'hello')

# 3. Strip with \x0c (form feed)
print('\x0c hello \x0c'.strip() == 'hello')

# 4. Mixed whitespace strip
print(' \t\n\r\x0b\x0c\xa0hello\xa0\x0c\x0b\r\n\t '.strip() == 'hello')

# 5. isspace for various chars
print('\xa0'.isspace())
print('\x0b'.isspace())
print('\x0c'.isspace())
print(' \t\n\xa0'.isspace())
print('a'.isspace())

# 6. lstrip/rstrip with NBSP
print('\xa0hello\xa0'.lstrip() == 'hello\xa0')
print('\xa0hello\xa0'.rstrip() == '\xa0hello')

# 7. Empty result from strip
print('\xa0'.strip() == '')
print('\xa0\xa0\xa0'.strip() == '')

# 8. No whitespace to strip
print('hello'.strip() == 'hello')

# 9. Regular strip still works
print('  hello  '.strip() == 'hello')
print('\thello\t'.strip() == 'hello')
print('\nhello\n'.strip() == 'hello')
