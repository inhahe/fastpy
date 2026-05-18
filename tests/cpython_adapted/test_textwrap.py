# Adapted from CPython Lib/test/test_textwrap.py
# Tests text wrapping algorithms (pure Python)

def wrap(text, width=70):
    """Simple word-wrap implementation."""
    words = text.split()
    if not words:
        return []
    lines = []
    current_line = words[0]
    for word in words[1:]:
        if len(current_line) + 1 + len(word) <= width:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines

def fill(text, width=70):
    """Fill text to width."""
    return "\n".join(wrap(text, width))

def dedent(text):
    """Remove common leading whitespace."""
    lines = text.split("\n")
    # Find minimum indentation (ignoring empty lines)
    min_indent = -1
    for line in lines:
        if line.strip():
            indent = 0
            for ch in line:
                if ch == " ":
                    indent += 1
                else:
                    break
            if min_indent == -1 or indent < min_indent:
                min_indent = indent
    if min_indent <= 0:
        return text
    result = []
    for line in lines:
        if line.strip():
            result.append(line[min_indent:])
        else:
            result.append("")
    return "\n".join(result)

def indent(text, prefix):
    """Add prefix to beginning of each non-empty line."""
    lines = text.split("\n")
    result = []
    for line in lines:
        if line.strip():
            result.append(prefix + line)
        else:
            result.append(line)
    return "\n".join(result)

# Test wrap
print(wrap("Hello World", 5))
print(wrap("The quick brown fox jumps over the lazy dog", 15))
print(wrap("Short", 100))
print(wrap("", 10))
print(wrap("OneVeryLongWordThatDoesNotFit", 10))

# Test fill
text = "The quick brown fox jumps over the lazy dog and continues running through the field"
print(fill(text, 20))
print("---")
print(fill(text, 40))
print("---")

# Test wrap with various widths
sentence = "Python is a great programming language for beginners and experts alike"
for w in [10, 20, 30, 50]:
    lines = wrap(sentence, w)
    print(w, len(lines), lines)

# Test dedent
indented = "    line1\n    line2\n    line3"
print(dedent(indented))
print("---")
indented2 = "        deep1\n        deep2\n        deep3"
print(dedent(indented2))
print("---")

# Mixed indentation
mixed = "    first\n        deeper\n    back"
print(dedent(mixed))
print("---")

# Test indent
text2 = "line1\nline2\nline3"
print(indent(text2, ">>> "))
print("---")
print(indent(text2, "  "))
print("---")

# Empty lines preserved
text3 = "first\n\nsecond\n\nthird"
print(indent(text3, "# "))
print("---")

# Single word per line at narrow width
narrow = wrap("one two three four five six seven", 5)
print(narrow)

# Exact fit
exact = wrap("ab cd ef", 5)
print(exact)

# Already single word
print(wrap("hello", 3))
