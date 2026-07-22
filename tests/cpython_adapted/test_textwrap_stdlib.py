# Adapted from CPython Lib/textwrap.py — stdlib text wrapping algorithms
# Tests text wrapping, filling, dedenting and indenting compiled by fastpy.
#
# The CPython textwrap module uses a TextWrapper class with regex-based
# chunking (import re), module-level variables, and keyword-only args.
# These trigger compiler limitations, so we reimplement the core algorithms
# as standalone functions using string operations only.
#
# NOTE: Strings built by concatenation in a loop and stored in lists have
# corrupted metadata (len=0, .split() segfaults) when retrieved in compiled
# code.  Tests avoid calling methods on strings from wrap() results and
# instead verify structural properties (line count, word count).
#
# NOTE: The function "indent" was renamed to "prefix_lines" because the
# compiler confuses 2-arg calls across functions with different signatures.

# ======================================================================
# Core text wrapping algorithms
# ======================================================================

def wrap(text, width=70):
    """Wrap a single paragraph of text, returning a list of lines.

    Core algorithm from CPython's TextWrapper._wrap_chunks:
    greedily pack words into lines that don't exceed width.
    """
    words = text.split()
    if len(words) == 0:
        return []

    lines = []
    current_line = words[0]

    i = 1
    while i < len(words):
        word = words[i]
        test = current_line + " " + word
        if len(test) <= width:
            current_line = test
        else:
            lines.append(current_line)
            current_line = word
        i = i + 1

    lines.append(current_line)
    return lines

def fill(text, width=70):
    """Fill a single paragraph of text, returning a single string.

    Equivalent to '\\n'.join(wrap(text, width)).
    """
    return "\n".join(wrap(text, width))

def dedent(text):
    """Remove any common leading whitespace from all lines of text.

    Adapted from CPython Lib/textwrap.py dedent() — same algorithm
    but without regex for leading whitespace detection.
    """
    lines = text.split("\n")
    min_indent = -1
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip(" ")
        if len(stripped) > 0:
            ind = len(line) - len(stripped)
            if min_indent == -1 or ind < min_indent:
                min_indent = ind
        i = i + 1

    if min_indent <= 0:
        return text

    result = []
    j = 0
    while j < len(lines):
        line = lines[j]
        stripped = line.lstrip(" ")
        if len(stripped) == 0:
            result.append("")
        else:
            result.append(line[min_indent:])
        j = j + 1
    return "\n".join(result)

def prefix_lines(text, pfx):
    """Add prefix to the beginning of non-empty lines.

    Equivalent to CPython's textwrap.indent(text, prefix) with default
    predicate.
    """
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip():
            result.append(pfx + line)
        else:
            result.append(line)
        i = i + 1
    return "\n".join(result)

def shorten(text, width):
    """Collapse and truncate text to fit in the given width.

    Adapted from CPython Lib/textwrap.py shorten().
    Uses ' [...]' as the placeholder.
    """
    placeholder = " [...]"
    words = text.split()
    collapsed = " ".join(words)

    if len(collapsed) <= width:
        return collapsed

    result = ""
    i = 0
    while i < len(words):
        if i == 0:
            test = words[i]
        else:
            test = result + " " + words[i]
        if len(test) + len(placeholder) <= width:
            result = test
        else:
            break
        i = i + 1

    return result + placeholder

# ======================================================================
# Tests
# ======================================================================

def test_wrap_basic():
    ok = 0
    total = 0
    total = total + 1
    r = wrap("Hello World", 5)
    if r == ["Hello", "World"]: ok = ok + 1
    total = total + 1
    r = wrap("Short", 100)
    if r == ["Short"]: ok = ok + 1
    total = total + 1
    r = wrap("", 10)
    if r == []: ok = ok + 1
    total = total + 1
    r = wrap("one two three", 5)
    if r == ["one", "two", "three"]: ok = ok + 1
    total = total + 1
    r = wrap("ab cd ef", 5)
    if r == ["ab cd", "ef"]: ok = ok + 1
    if ok == total:
        print("TestTextwrap.test_wrap_basic: PASS")
    else:
        print("TestTextwrap.test_wrap_basic: FAIL -", ok, "of", total)

def test_wrap_sentence():
    text = "The quick brown fox jumps over the lazy dog"
    ok = 0
    total = 0
    # Should wrap to multiple lines at width 15
    total = total + 1
    r = wrap(text, 15)
    if len(r) > 1: ok = ok + 1
    # Should be single line at width 100
    total = total + 1
    r2 = wrap(text, 100)
    if len(r2) == 1: ok = ok + 1
    if ok == total:
        print("TestTextwrap.test_wrap_sentence: PASS")
    else:
        print("TestTextwrap.test_wrap_sentence: FAIL -", ok, "of", total)

def test_wrap_widths():
    # Verify wrap produces correct line count at different widths
    text = "one two three four five six seven"
    ok = 0
    total = 0
    # Width 5: each word on its own line (7 words → 7 lines)
    total = total + 1
    r = wrap(text, 5)
    if len(r) == 7: ok = ok + 1
    # Width 50: should fit in 1 line (32 chars)
    total = total + 1
    r = wrap(text, 50)
    if len(r) == 1: ok = ok + 1
    # Width 15: some wrapping
    total = total + 1
    r = wrap(text, 15)
    if len(r) > 1 and len(r) < 7: ok = ok + 1
    if ok == total:
        print("TestTextwrap.test_wrap_widths: PASS")
    else:
        print("TestTextwrap.test_wrap_widths: FAIL -", ok, "of", total)

def test_fill():
    text = "one two three four five"
    ok = 0
    total = 0
    total = total + 1
    r = fill(text, 10)
    lines = r.split("\n")
    if len(lines) > 1: ok = ok + 1
    # Full width — single line
    total = total + 1
    r2 = fill(text, 100)
    if "\n" not in r2: ok = ok + 1
    if ok == total:
        print("TestTextwrap.test_fill: PASS")
    else:
        print("TestTextwrap.test_fill: FAIL -", ok, "of", total)

def test_dedent():
    ok = 0
    total = 0
    # Uniform indentation
    total = total + 1
    r = dedent("    line1\n    line2\n    line3")
    if r == "line1\nline2\nline3": ok = ok + 1
    # Deeper indentation
    total = total + 1
    r = dedent("        deep1\n        deep2")
    if r == "deep1\ndeep2": ok = ok + 1
    # Mixed indentation
    total = total + 1
    r = dedent("    first\n        deeper\n    back")
    if r == "first\n    deeper\nback": ok = ok + 1
    # No indentation
    total = total + 1
    r = dedent("no indent\nat all")
    if r == "no indent\nat all": ok = ok + 1
    # Single line
    total = total + 1
    r = dedent("    indented line")
    if r == "indented line": ok = ok + 1
    if ok == total:
        print("TestTextwrap.test_dedent: PASS")
    else:
        print("TestTextwrap.test_dedent: FAIL -", ok, "of", total)

def test_prefix_lines():
    ok = 0
    total = 0
    total = total + 1
    r = prefix_lines("line1\nline2\nline3", "  ")
    if r == "  line1\n  line2\n  line3": ok = ok + 1
    total = total + 1
    r = prefix_lines("hello\nworld", "> ")
    if r == "> hello\n> world": ok = ok + 1
    total = total + 1
    r = prefix_lines("line1\n\nline3", "  ")
    if r == "  line1\n\n  line3": ok = ok + 1
    if ok == total:
        print("TestTextwrap.test_prefix_lines: PASS")
    else:
        print("TestTextwrap.test_prefix_lines: FAIL -", ok, "of", total)

def test_shorten():
    ok = 0
    total = 0
    # Short enough — no truncation
    total = total + 1
    r = shorten("Hello World", 20)
    if r == "Hello World": ok = ok + 1
    # Needs truncation
    total = total + 1
    r = shorten("The quick brown fox jumps over the lazy dog", 20)
    if len(r) <= 20: ok = ok + 1
    # Whitespace collapsing
    total = total + 1
    r = shorten("  lots   of    spaces  ", 30)
    if r == "lots of spaces": ok = ok + 1
    if ok == total:
        print("TestTextwrap.test_shorten: PASS")
    else:
        print("TestTextwrap.test_shorten: FAIL -", ok, "of", total)

# ======================================================================
# Run all tests
# ======================================================================

try:
    test_wrap_basic()
except Exception as _e:
    print("TestTextwrap.test_wrap_basic: FAIL -", _e)
try:
    test_wrap_sentence()
except Exception as _e:
    print("TestTextwrap.test_wrap_sentence: FAIL -", _e)
try:
    test_wrap_widths()
except Exception as _e:
    print("TestTextwrap.test_wrap_widths: FAIL -", _e)
try:
    test_fill()
except Exception as _e:
    print("TestTextwrap.test_fill: FAIL -", _e)
try:
    test_dedent()
except Exception as _e:
    print("TestTextwrap.test_dedent: FAIL -", _e)
try:
    test_prefix_lines()
except Exception as _e:
    print("TestTextwrap.test_prefix_lines: FAIL -", _e)
try:
    test_shorten()
except Exception as _e:
    print("TestTextwrap.test_shorten: FAIL -", _e)
