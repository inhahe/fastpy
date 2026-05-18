# Auto-adapted from CPython Lib/test/test_textwrap.py
# Tests fastpy's ability to compile and run the textwrap module
# Stdlib source inlined from: C:\Users\inhah\AppData\Local\Python\pythoncore-3.13-64\Lib\textwrap.py

# ======================================================================
# Inlined stdlib module: textwrap
# ======================================================================

"""Text wrapping and filling.
"""

# Copyright (C) 1999-2001 Gregory P. Ward.
# Copyright (C) 2002, 2003 Python Software Foundation.
# Written by Greg Ward <gward@python.net>

import re

__all__ = ['TextWrapper', 'wrap', 'fill', 'dedent', 'indent', 'shorten']

# Hardcode the recognized whitespace characters to the US-ASCII
# whitespace characters.  The main reason for doing this is that
# some Unicode spaces (like \u00a0) are non-breaking whitespaces.
_whitespace = '\t\n\x0b\x0c\r '

class TextWrapper:
    """
    Object for wrapping/filling text.  The public interface consists of
    the wrap() and fill() methods; the other methods are just there for
    subclasses to override in order to tweak the default behaviour.
    If you want to completely replace the main wrapping algorithm,
    you'll probably have to override _wrap_chunks().

    Several instance attributes control various aspects of wrapping:
      width (default: 70)
        the maximum width of wrapped lines (unless break_long_words
        is false)
      initial_indent (default: "")
        string that will be prepended to the first line of wrapped
        output.  Counts towards the line's width.
      subsequent_indent (default: "")
        string that will be prepended to all lines save the first
        of wrapped output; also counts towards each line's width.
      expand_tabs (default: true)
        Expand tabs in input text to spaces before further processing.
        Each tab will become 0 .. 'tabsize' spaces, depending on its position
        in its line.  If false, each tab is treated as a single character.
      tabsize (default: 8)
        Expand tabs in input text to 0 .. 'tabsize' spaces, unless
        'expand_tabs' is false.
      replace_whitespace (default: true)
        Replace all whitespace characters in the input text by spaces
        after tab expansion.  Note that if expand_tabs is false and
        replace_whitespace is true, every tab will be converted to a
        single space!
      fix_sentence_endings (default: false)
        Ensure that sentence-ending punctuation is always followed
        by two spaces.  Off by default because the algorithm is
        (unavoidably) imperfect.
      break_long_words (default: true)
        Break words longer than 'width'.  If false, those words will not
        be broken, and some lines might be longer than 'width'.
      break_on_hyphens (default: true)
        Allow breaking hyphenated words. If true, wrapping will occur
        preferably on whitespaces and right after hyphens part of
        compound words.
      drop_whitespace (default: true)
        Drop leading and trailing whitespace from lines.
      max_lines (default: None)
        Truncate wrapped lines.
      placeholder (default: ' [...]')
        Append to the last line of truncated text.
    """

    unicode_whitespace_trans = dict.fromkeys(map(ord, _whitespace), ord(' '))

    # This funky little regex is just the trick for splitting
    # text up into word-wrappable chunks.  E.g.
    #   "Hello there -- you goof-ball, use the -b option!"
    # splits into
    #   Hello/ /there/ /--/ /you/ /goof-/ball,/ /use/ /the/ /-b/ /option!
    # (after stripping out empty strings).
    word_punct = r'[\w!"\'&.,?]'
    letter = r'[^\d\W]'
    whitespace = r'[%s]' % re.escape(_whitespace)
    nowhitespace = '[^' + whitespace[1:]
    wordsep_re = re.compile(r'''
        ( # any whitespace
          %(ws)s+
        | # em-dash between words
          (?<=%(wp)s) -{2,} (?=\w)
        | # word, possibly hyphenated
          %(nws)s+? (?:
            # hyphenated word
              -(?: (?<=%(lt)s{2}-) | (?<=%(lt)s-%(lt)s-))
              (?= %(lt)s -? %(lt)s)
            | # end of word
              (?=%(ws)s|\Z)
            | # em-dash
              (?<=%(wp)s) (?=-{2,}\w)
            )
        )''' % {'wp': word_punct, 'lt': letter,
                'ws': whitespace, 'nws': nowhitespace},
        re.VERBOSE)
    del word_punct, letter, nowhitespace

    # This less funky little regex just split on recognized spaces. E.g.
    #   "Hello there -- you goof-ball, use the -b option!"
    # splits into
    #   Hello/ /there/ /--/ /you/ /goof-ball,/ /use/ /the/ /-b/ /option!/
    wordsep_simple_re = re.compile(r'(%s+)' % whitespace)
    del whitespace

    # XXX this is not locale- or charset-aware -- string.lowercase
    # is US-ASCII only (and therefore English-only)
    sentence_end_re = re.compile(r'[a-z]'             # lowercase letter
                                 r'[\.\!\?]'          # sentence-ending punct.
                                 r'[\"\']?'           # optional end-of-quote
                                 r'\Z')               # end of chunk

    def __init__(self,
                 width=70,
                 initial_indent="",
                 subsequent_indent="",
                 expand_tabs=True,
                 replace_whitespace=True,
                 fix_sentence_endings=False,
                 break_long_words=True,
                 drop_whitespace=True,
                 break_on_hyphens=True,
                 tabsize=8,
                 *,
                 max_lines=None,
                 placeholder=' [...]'):
        self.width = width
        self.initial_indent = initial_indent
        self.subsequent_indent = subsequent_indent
        self.expand_tabs = expand_tabs
        self.replace_whitespace = replace_whitespace
        self.fix_sentence_endings = fix_sentence_endings
        self.break_long_words = break_long_words
        self.drop_whitespace = drop_whitespace
        self.break_on_hyphens = break_on_hyphens
        self.tabsize = tabsize
        self.max_lines = max_lines
        self.placeholder = placeholder


    # -- Private methods -----------------------------------------------
    # (possibly useful for subclasses to override)

    def _munge_whitespace(self, text):
        """_munge_whitespace(text : string) -> string

        Munge whitespace in text: expand tabs and convert all other
        whitespace characters to spaces.  Eg. " foo\\tbar\\n\\nbaz"
        becomes " foo    bar  baz".
        """
        if self.expand_tabs:
            text = text.expandtabs(self.tabsize)
        if self.replace_whitespace:
            text = text.translate(self.unicode_whitespace_trans)
        return text


    def _split(self, text):
        """_split(text : string) -> [string]

        Split the text to wrap into indivisible chunks.  Chunks are
        not quite the same as words; see _wrap_chunks() for full
        details.  As an example, the text
          Look, goof-ball -- use the -b option!
        breaks into the following chunks:
          'Look,', ' ', 'goof-', 'ball', ' ', '--', ' ',
          'use', ' ', 'the', ' ', '-b', ' ', 'option!'
        if break_on_hyphens is True, or in:
          'Look,', ' ', 'goof-ball', ' ', '--', ' ',
          'use', ' ', 'the', ' ', '-b', ' ', option!'
        otherwise.
        """
        if self.break_on_hyphens is True:
            chunks = self.wordsep_re.split(text)
        else:
            chunks = self.wordsep_simple_re.split(text)
        chunks = [c for c in chunks if c]
        return chunks

    def _fix_sentence_endings(self, chunks):
        """_fix_sentence_endings(chunks : [string])

        Correct for sentence endings buried in 'chunks'.  Eg. when the
        original text contains "... foo.\\nBar ...", munge_whitespace()
        and split() will convert that to [..., "foo.", " ", "Bar", ...]
        which has one too few spaces; this method simply changes the one
        space to two.
        """
        i = 0
        patsearch = self.sentence_end_re.search
        while i < len(chunks)-1:
            if chunks[i+1] == " " and patsearch(chunks[i]):
                chunks[i+1] = "  "
                i += 2
            else:
                i += 1

    def _handle_long_word(self, reversed_chunks, cur_line, cur_len, width):
        """_handle_long_word(chunks : [string],
                             cur_line : [string],
                             cur_len : int, width : int)

        Handle a chunk of text (most likely a word, not whitespace) that
        is too long to fit in any line.
        """
        # Figure out when indent is larger than the specified width, and make
        # sure at least one character is stripped off on every pass
        if width < 1:
            space_left = 1
        else:
            space_left = width - cur_len

        # If we're allowed to break long words, then do so: put as much
        # of the next chunk onto the current line as will fit.
        if self.break_long_words and space_left > 0:
            end = space_left
            chunk = reversed_chunks[-1]
            if self.break_on_hyphens and len(chunk) > space_left:
                # break after last hyphen, but only if there are
                # non-hyphens before it
                hyphen = chunk.rfind('-', 0, space_left)
                if hyphen > 0 and any(c != '-' for c in chunk[:hyphen]):
                    end = hyphen + 1
            cur_line.append(chunk[:end])
            reversed_chunks[-1] = chunk[end:]

        # Otherwise, we have to preserve the long word intact.  Only add
        # it to the current line if there's nothing already there --
        # that minimizes how much we violate the width constraint.
        elif not cur_line:
            cur_line.append(reversed_chunks.pop())

        # If we're not allowed to break long words, and there's already
        # text on the current line, do nothing.  Next time through the
        # main loop of _wrap_chunks(), we'll wind up here again, but
        # cur_len will be zero, so the next line will be entirely
        # devoted to the long word that we can't handle right now.

    def _wrap_chunks(self, chunks):
        """_wrap_chunks(chunks : [string]) -> [string]

        Wrap a sequence of text chunks and return a list of lines of
        length 'self.width' or less.  (If 'break_long_words' is false,
        some lines may be longer than this.)  Chunks correspond roughly
        to words and the whitespace between them: each chunk is
        indivisible (modulo 'break_long_words'), but a line break can
        come between any two chunks.  Chunks should not have internal
        whitespace; ie. a chunk is either all whitespace or a "word".
        Whitespace chunks will be removed from the beginning and end of
        lines, but apart from that whitespace is preserved.
        """
        lines = []
        if self.width <= 0:
            raise ValueError("invalid width %r (must be > 0)" % self.width)
        if self.max_lines is not None:
            if self.max_lines > 1:
                indent = self.subsequent_indent
            else:
                indent = self.initial_indent
            if len(indent) + len(self.placeholder.lstrip()) > self.width:
                raise ValueError("placeholder too large for max width")

        # Arrange in reverse order so items can be efficiently popped
        # from a stack of chucks.
        chunks.reverse()

        while chunks:

            # Start the list of chunks that will make up the current line.
            # cur_len is just the length of all the chunks in cur_line.
            cur_line = []
            cur_len = 0

            # Figure out which static string will prefix this line.
            if lines:
                indent = self.subsequent_indent
            else:
                indent = self.initial_indent

            # Maximum width for this line.
            width = self.width - len(indent)

            # First chunk on line is whitespace -- drop it, unless this
            # is the very beginning of the text (ie. no lines started yet).
            if self.drop_whitespace and chunks[-1].strip() == '' and lines:
                del chunks[-1]

            while chunks:
                l = len(chunks[-1])

                # Can at least squeeze this chunk onto the current line.
                if cur_len + l <= width:
                    cur_line.append(chunks.pop())
                    cur_len += l

                # Nope, this line is full.
                else:
                    break

            # The current line is full, and the next chunk is too big to
            # fit on *any* line (not just this one).
            if chunks and len(chunks[-1]) > width:
                self._handle_long_word(chunks, cur_line, cur_len, width)
                cur_len = sum(map(len, cur_line))

            # If the last chunk on this line is all whitespace, drop it.
            if self.drop_whitespace and cur_line and cur_line[-1].strip() == '':
                cur_len -= len(cur_line[-1])
                del cur_line[-1]

            if cur_line:
                if (self.max_lines is None or
                    len(lines) + 1 < self.max_lines or
                    (not chunks or
                     self.drop_whitespace and
                     len(chunks) == 1 and
                     not chunks[0].strip()) and cur_len <= width):
                    # Convert current line back to a string and store it in
                    # list of all lines (return value).
                    lines.append(indent + ''.join(cur_line))
                else:
                    while cur_line:
                        if (cur_line[-1].strip() and
                            cur_len + len(self.placeholder) <= width):
                            cur_line.append(self.placeholder)
                            lines.append(indent + ''.join(cur_line))
                            break
                        cur_len -= len(cur_line[-1])
                        del cur_line[-1]
                    else:
                        if lines:
                            prev_line = lines[-1].rstrip()
                            if (len(prev_line) + len(self.placeholder) <=
                                    self.width):
                                lines[-1] = prev_line + self.placeholder
                                break
                        lines.append(indent + self.placeholder.lstrip())
                    break

        return lines

    def _split_chunks(self, text):
        text = self._munge_whitespace(text)
        return self._split(text)

    # -- Public interface ----------------------------------------------

    def wrap(self, text):
        """wrap(text : string) -> [string]

        Reformat the single paragraph in 'text' so it fits in lines of
        no more than 'self.width' columns, and return a list of wrapped
        lines.  Tabs in 'text' are expanded with string.expandtabs(),
        and all other whitespace characters (including newline) are
        converted to space.
        """
        chunks = self._split_chunks(text)
        if self.fix_sentence_endings:
            self._fix_sentence_endings(chunks)
        return self._wrap_chunks(chunks)

    def fill(self, text):
        """fill(text : string) -> string

        Reformat the single paragraph in 'text' to fit in lines of no
        more than 'self.width' columns, and return a new string
        containing the entire wrapped paragraph.
        """
        return "\n".join(self.wrap(text))


# -- Convenience interface ---------------------------------------------

def wrap(text, width=70, **kwargs):
    """Wrap a single paragraph of text, returning a list of wrapped lines.

    Reformat the single paragraph in 'text' so it fits in lines of no
    more than 'width' columns, and return a list of wrapped lines.  By
    default, tabs in 'text' are expanded with string.expandtabs(), and
    all other whitespace characters (including newline) are converted to
    space.  See TextWrapper class for available keyword args to customize
    wrapping behaviour.
    """
    w = TextWrapper(width=width, **kwargs)
    return w.wrap(text)

def fill(text, width=70, **kwargs):
    """Fill a single paragraph of text, returning a new string.

    Reformat the single paragraph in 'text' to fit in lines of no more
    than 'width' columns, and return a new string containing the entire
    wrapped paragraph.  As with wrap(), tabs are expanded and other
    whitespace characters converted to space.  See TextWrapper class for
    available keyword args to customize wrapping behaviour.
    """
    w = TextWrapper(width=width, **kwargs)
    return w.fill(text)

def shorten(text, width, **kwargs):
    """Collapse and truncate the given text to fit in the given width.

    The text first has its whitespace collapsed.  If it then fits in
    the *width*, it is returned as is.  Otherwise, as many words
    as possible are joined and then the placeholder is appended::

        >>> textwrap.shorten("Hello  world!", width=12)
        'Hello world!'
        >>> textwrap.shorten("Hello  world!", width=11)
        'Hello [...]'
    """
    w = TextWrapper(width=width, max_lines=1, **kwargs)
    return w.fill(' '.join(text.strip().split()))


# -- Loosely related functionality -------------------------------------

_whitespace_only_re = re.compile('^[ \t]+$', re.MULTILINE)
_leading_whitespace_re = re.compile('(^[ \t]*)(?:[^ \t\n])', re.MULTILINE)

def dedent(text):
    """Remove any common leading whitespace from every line in `text`.

    This can be used to make triple-quoted strings line up with the left
    edge of the display, while still presenting them in the source code
    in indented form.

    Note that tabs and spaces are both treated as whitespace, but they
    are not equal: the lines "  hello" and "\\thello" are
    considered to have no common leading whitespace.

    Entirely blank lines are normalized to a newline character.
    """
    # Look for the longest leading string of spaces and tabs common to
    # all lines.
    margin = None
    text = _whitespace_only_re.sub('', text)
    indents = _leading_whitespace_re.findall(text)
    for indent in indents:
        if margin is None:
            margin = indent

        # Current line more deeply indented than previous winner:
        # no change (previous winner is still on top).
        elif indent.startswith(margin):
            pass

        # Current line consistent with and no deeper than previous winner:
        # it's the new winner.
        elif margin.startswith(indent):
            margin = indent

        # Find the largest common whitespace between current line and previous
        # winner.
        else:
            for i, (x, y) in enumerate(zip(margin, indent)):
                if x != y:
                    margin = margin[:i]
                    break

    # sanity check (testing/debugging only)
    if 0 and margin:
        for line in text.split("\n"):
            assert not line or line.startswith(margin), \
                   "line = %r, margin = %r" % (line, margin)

    if margin:
        text = re.sub(r'(?m)^' + margin, '', text)
    return text


def indent(text, prefix, predicate=None):
    """Adds 'prefix' to the beginning of selected lines in 'text'.

    If 'predicate' is provided, 'prefix' will only be added to the lines
    where 'predicate(line)' is True. If 'predicate' is not provided,
    it will default to adding 'prefix' to all non-empty lines that do not
    consist solely of whitespace characters.
    """
    if predicate is None:
        # str.splitlines(True) doesn't produce empty string.
        #  ''.splitlines(True) => []
        #  'foo\n'.splitlines(True) => ['foo\n']
        # So we can use just `not s.isspace()` here.
        predicate = lambda s: not s.isspace()

    prefixed_lines = []
    for line in text.splitlines(True):
        if predicate(line):
            prefixed_lines.append(prefix)
        prefixed_lines.append(line)

    return ''.join(prefixed_lines)



# ======================================================================
# Assertion helpers
# ======================================================================

# Assertion helpers (replacing unittest.TestCase methods)
def assertEqual(a, b, msg=None):
    if a != b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " != " + str(b))

def assertNotEqual(a, b, msg=None):
    if a == b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " == " + str(b))

def assertAlmostEqual(a, b, places=7, msg=None):
    if abs(a - b) > 0.5 * 10.0 ** (-places):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " != " + str(b) + " within " + str(places) + " places")

def assertNotAlmostEqual(a, b, places=7, msg=None):
    if abs(a - b) <= 0.5 * 10.0 ** (-places):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " == " + str(b) + " within " + str(places) + " places")

def assertTrue(x, msg=None):
    if not x:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("expected True, got " + str(x))

def assertFalse(x, msg=None):
    if x:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("expected False, got " + str(x))

def assertIs(a, b, msg=None):
    if a is not b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is not " + str(b))

def assertIsNot(a, b, msg=None):
    if a is b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is " + str(b))

def assertIsNone(x, msg=None):
    if x is not None:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(x) + " is not None")

def assertIsNotNone(x, msg=None):
    if x is None:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("unexpected None")

def assertIn(a, b, msg=None):
    if a not in b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not in " + str(b))

def assertNotIn(a, b, msg=None):
    if a in b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " in " + str(b))

def assertIsInstance(a, b, msg=None):
    if not isinstance(a, b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is not instance of " + str(b))

def assertGreater(a, b, msg=None):
    if not (a > b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not greater than " + str(b))

def assertGreaterEqual(a, b, msg=None):
    if not (a >= b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not >= " + str(b))

def assertLess(a, b, msg=None):
    if not (a < b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not less than " + str(b))

def assertLessEqual(a, b, msg=None):
    if not (a <= b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not <= " + str(b))

def assertSequenceEqual(a, b, msg=None):
    if len(a) != len(b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError("sequences differ in length: " + str(len(a)) + " vs " + str(len(b)))
    for i in range(len(a)):
        if a[i] != b[i]:
            if msg:
                raise AssertionError(msg)
            raise AssertionError("sequences differ at index " + str(i) + ": " + str(a[i]) + " != " + str(b[i]))

def assertListEqual(a, b, msg=None):
    assertSequenceEqual(a, b, msg)

def assertTupleEqual(a, b, msg=None):
    assertSequenceEqual(a, b, msg)


# ======================================================================
# Test functions (extracted from CPython test suite)
# ======================================================================

# Helper methods from WrapTestCase
def show(textin):
    if isinstance(textin, list):
        result = []
        for i in range(len(textin)):
            result.append('  %d: %r' % (i, textin[i]))
        result = '\n'.join(result) if result else '  no lines'
    elif isinstance(textin, str):
        result = '  %s\n' % repr(textin)
    return result

def check(result, expect):
    assertEqual(result, expect, 'expected:\n%s\nbut got:\n%s' % (show(expect), show(result)))

def check_wrap(text, width, expect, **kwargs):
    result = wrap(text, width, **kwargs)
    check(result, expect)

def check_split(text, expect):
    result = wrapper._split(text)
    assertEqual(result, expect, '\nexpected %r\nbut got  %r' % (expect, result))

# Test functions from WrapTestCase
def WrapTestCase__test_simple():
    wrapper = TextWrapper(width=45)
    text = "Hello there, how are you this fine day?  I'm glad to hear it!"
    check_wrap(text, 12, ['Hello there,', 'how are you', 'this fine', "day?  I'm", 'glad to hear', 'it!'])
    check_wrap(text, 42, ['Hello there, how are you this fine day?', "I'm glad to hear it!"])
    check_wrap(text, 80, [text])

def WrapTestCase__test_empty_string():
    wrapper = TextWrapper(width=45)
    check_wrap('', 6, [])
    check_wrap('', 6, [], drop_whitespace=False)

def WrapTestCase__test_empty_string_with_initial_indent():
    wrapper = TextWrapper(width=45)
    check_wrap('', 6, [], initial_indent='++')
    check_wrap('', 6, [], initial_indent='++', drop_whitespace=False)

def WrapTestCase__test_whitespace():
    wrapper = TextWrapper(width=45)
    text = 'This is a paragraph that already has\nline breaks.  But some of its lines are much longer than the others,\nso it needs to be wrapped.\nSome lines are \ttabbed too.\nWhat a mess!\n'
    expect = ['This is a paragraph that already has line', 'breaks.  But some of its lines are much', 'longer than the others, so it needs to be', 'wrapped.  Some lines are  tabbed too.  What a', 'mess!']
    wrapper = TextWrapper(45, fix_sentence_endings=True)
    result = wrapper.wrap(text)
    check(result, expect)
    result = wrapper.fill(text)
    check(result, '\n'.join(expect))
    text = '\tTest\tdefault\t\ttabsize.'
    expect = ['        Test    default         tabsize.']
    check_wrap(text, 80, expect)
    text = '\tTest\tcustom\t\ttabsize.'
    expect = ['    Test    custom      tabsize.']
    check_wrap(text, 80, expect, tabsize=4)

def WrapTestCase__test_fix_sentence_endings():
    wrapper = TextWrapper(width=45)
    wrapper = TextWrapper(60, fix_sentence_endings=True)
    text = 'A short line. Note the single space.'
    expect = ['A short line.  Note the single space.']
    check(wrapper.wrap(text), expect)
    text = 'Well, Doctor? What do you think?'
    expect = ['Well, Doctor?  What do you think?']
    check(wrapper.wrap(text), expect)
    text = 'Well, Doctor?\nWhat do you think?'
    check(wrapper.wrap(text), expect)
    text = 'I say, chaps! Anyone for "tennis?"\nHmmph!'
    expect = ['I say, chaps!  Anyone for "tennis?"  Hmmph!']
    check(wrapper.wrap(text), expect)
    wrapper.width = 20
    expect = ['I say, chaps!', 'Anyone for "tennis?"', 'Hmmph!']
    check(wrapper.wrap(text), expect)
    text = 'And she said, "Go to hell!"\nCan you believe that?'
    expect = ['And she said, "Go to', 'hell!"  Can you', 'believe that?']
    check(wrapper.wrap(text), expect)
    wrapper.width = 60
    expect = ['And she said, "Go to hell!"  Can you believe that?']
    check(wrapper.wrap(text), expect)
    text = 'File stdio.h is nice.'
    expect = ['File stdio.h is nice.']
    check(wrapper.wrap(text), expect)

def WrapTestCase__test_wrap_short():
    wrapper = TextWrapper(width=45)
    text = 'This is a\nshort paragraph.'
    check_wrap(text, 20, ['This is a short', 'paragraph.'])
    check_wrap(text, 40, ['This is a short paragraph.'])

def WrapTestCase__test_wrap_short_1line():
    wrapper = TextWrapper(width=45)
    text = 'This is a short line.'
    check_wrap(text, 30, ['This is a short line.'])
    check_wrap(text, 30, ['(1) This is a short line.'], initial_indent='(1) ')

def WrapTestCase__test_hyphenated():
    wrapper = TextWrapper(width=45)
    text = "this-is-a-useful-feature-for-reformatting-posts-from-tim-peters'ly"
    check_wrap(text, 40, ['this-is-a-useful-feature-for-', "reformatting-posts-from-tim-peters'ly"])
    check_wrap(text, 41, ['this-is-a-useful-feature-for-', "reformatting-posts-from-tim-peters'ly"])
    check_wrap(text, 42, ['this-is-a-useful-feature-for-reformatting-', "posts-from-tim-peters'ly"])
    expect = "this-|is-|a-|useful-|feature-|for-|reformatting-|posts-|from-|tim-|peters'ly".split('|')
    check_wrap(text, 1, expect, break_long_words=False)
    check_split(text, expect)
    check_split('e-mail', ['e-mail'])
    check_split('Jelly-O', ['Jelly-O'])
    check_split('half-a-crown', 'half-|a-|crown'.split('|'))

def WrapTestCase__test_hyphenated_numbers():
    wrapper = TextWrapper(width=45)
    text = 'Python 1.0.0 was released on 1994-01-26.  Python 1.0.1 was\nreleased on 1994-02-15.'
    check_wrap(text, 30, ['Python 1.0.0 was released on', '1994-01-26.  Python 1.0.1 was', 'released on 1994-02-15.'])
    check_wrap(text, 40, ['Python 1.0.0 was released on 1994-01-26.', 'Python 1.0.1 was released on 1994-02-15.'])
    check_wrap(text, 1, text.split(), break_long_words=False)
    text = 'I do all my shopping at 7-11.'
    check_wrap(text, 25, ['I do all my shopping at', '7-11.'])
    check_wrap(text, 27, ['I do all my shopping at', '7-11.'])
    check_wrap(text, 29, ['I do all my shopping at 7-11.'])
    check_wrap(text, 1, text.split(), break_long_words=False)

def WrapTestCase__test_em_dash():
    wrapper = TextWrapper(width=45)
    text = 'Em-dashes should be written -- thus.'
    check_wrap(text, 25, ['Em-dashes should be', 'written -- thus.'])
    check_wrap(text, 29, ['Em-dashes should be written', '-- thus.'])
    expect = ['Em-dashes should be written --', 'thus.']
    check_wrap(text, 30, expect)
    check_wrap(text, 35, expect)
    check_wrap(text, 36, ['Em-dashes should be written -- thus.'])
    text = 'You can also do--this or even---this.'
    expect = ['You can also do', '--this or even', '---this.']
    check_wrap(text, 15, expect)
    check_wrap(text, 16, expect)
    expect = ['You can also do--', 'this or even---', 'this.']
    check_wrap(text, 17, expect)
    check_wrap(text, 19, expect)
    expect = ['You can also do--this or even', '---this.']
    check_wrap(text, 29, expect)
    check_wrap(text, 31, expect)
    expect = ['You can also do--this or even---', 'this.']
    check_wrap(text, 32, expect)
    check_wrap(text, 35, expect)
    text = "Here's an -- em-dash and--here's another---and another!"
    expect = ["Here's", ' ', 'an', ' ', '--', ' ', 'em-', 'dash', ' ', 'and', '--', "here's", ' ', 'another', '---', 'and', ' ', 'another!']
    check_split(text, expect)
    text = 'and then--bam!--he was gone'
    expect = ['and', ' ', 'then', '--', 'bam!', '--', 'he', ' ', 'was', ' ', 'gone']
    check_split(text, expect)

def WrapTestCase__test_unix_options():
    wrapper = TextWrapper(width=45)
    text = 'You should use the -n option, or --dry-run in its long form.'
    check_wrap(text, 20, ['You should use the', '-n option, or --dry-', 'run in its long', 'form.'])
    check_wrap(text, 21, ['You should use the -n', 'option, or --dry-run', 'in its long form.'])
    expect = ['You should use the -n option, or', '--dry-run in its long form.']
    check_wrap(text, 32, expect)
    check_wrap(text, 34, expect)
    check_wrap(text, 35, expect)
    check_wrap(text, 38, expect)
    expect = ['You should use the -n option, or --dry-', 'run in its long form.']
    check_wrap(text, 39, expect)
    check_wrap(text, 41, expect)
    expect = ['You should use the -n option, or --dry-run', 'in its long form.']
    check_wrap(text, 42, expect)
    text = 'the -n option, or --dry-run or --dryrun'
    expect = ['the', ' ', '-n', ' ', 'option,', ' ', 'or', ' ', '--dry-', 'run', ' ', 'or', ' ', '--dryrun']
    check_split(text, expect)

def WrapTestCase__test_funky_hyphens():
    wrapper = TextWrapper(width=45)
    check_split('what the--hey!', ['what', ' ', 'the', '--', 'hey!'])
    check_split('what the--', ['what', ' ', 'the--'])
    check_split('what the--.', ['what', ' ', 'the--.'])
    check_split('--text--.', ['--text--.'])
    check_split('--option', ['--option'])
    check_split('--option-opt', ['--option-', 'opt'])
    check_split('foo --option-opt bar', ['foo', ' ', '--option-', 'opt', ' ', 'bar'])

def WrapTestCase__test_punct_hyphens():
    wrapper = TextWrapper(width=45)
    check_split("the 'wibble-wobble' widget", ['the', ' ', "'wibble-", "wobble'", ' ', 'widget'])
    check_split('the "wibble-wobble" widget', ['the', ' ', '"wibble-', 'wobble"', ' ', 'widget'])
    check_split('the (wibble-wobble) widget', ['the', ' ', '(wibble-', 'wobble)', ' ', 'widget'])
    check_split("the ['wibble-wobble'] widget", ['the', ' ', "['wibble-", "wobble']", ' ', 'widget'])
    check_split("what-d'you-call-it.", "what-d'you-|call-|it.".split('|'))

def WrapTestCase__test_funky_parens():
    wrapper = TextWrapper(width=45)
    check_split('foo (--option) bar', ['foo', ' ', '(--option)', ' ', 'bar'])
    check_split('foo (bar) baz', ['foo', ' ', '(bar)', ' ', 'baz'])
    check_split('blah (ding dong), wubba', ['blah', ' ', '(ding', ' ', 'dong),', ' ', 'wubba'])

def WrapTestCase__test_drop_whitespace_false():
    wrapper = TextWrapper(width=45)
    text = ' This is a    sentence with     much whitespace.'
    check_wrap(text, 10, [' This is a', '    ', 'sentence ', 'with     ', 'much white', 'space.'], drop_whitespace=False)

def WrapTestCase__test_drop_whitespace_false_whitespace_only():
    wrapper = TextWrapper(width=45)
    check_wrap('   ', 6, ['   '], drop_whitespace=False)

def WrapTestCase__test_drop_whitespace_false_whitespace_only_with_indent():
    wrapper = TextWrapper(width=45)
    check_wrap('   ', 6, ['     '], drop_whitespace=False, initial_indent='  ')

def WrapTestCase__test_drop_whitespace_whitespace_only():
    wrapper = TextWrapper(width=45)
    check_wrap('  ', 6, [])

def WrapTestCase__test_drop_whitespace_leading_whitespace():
    wrapper = TextWrapper(width=45)
    text = ' This is a sentence with leading whitespace.'
    check_wrap(text, 50, [' This is a sentence with leading whitespace.'])
    check_wrap(text, 30, [' This is a sentence with', 'leading whitespace.'])

def WrapTestCase__test_drop_whitespace_whitespace_line():
    wrapper = TextWrapper(width=45)
    text = 'abcd    efgh'
    check_wrap(text, 6, ['abcd', '    ', 'efgh'], drop_whitespace=False)
    check_wrap(text, 6, ['abcd', 'efgh'])

def WrapTestCase__test_drop_whitespace_whitespace_only_with_indent():
    wrapper = TextWrapper(width=45)
    check_wrap('  ', 6, [], initial_indent='++')

def WrapTestCase__test_drop_whitespace_whitespace_indent():
    wrapper = TextWrapper(width=45)
    check_wrap('abcd efgh', 6, ['  abcd', '  efgh'], initial_indent='  ', subsequent_indent='  ')

def WrapTestCase__test_split():
    wrapper = TextWrapper(width=45)
    text = 'Hello there -- you goof-ball, use the -b option!'
    result = wrapper._split(text)
    check(result, ['Hello', ' ', 'there', ' ', '--', ' ', 'you', ' ', 'goof-', 'ball,', ' ', 'use', ' ', 'the', ' ', '-b', ' ', 'option!'])

def WrapTestCase__test_break_on_hyphens():
    wrapper = TextWrapper(width=45)
    text = 'yaba daba-doo'
    check_wrap(text, 10, ['yaba daba-', 'doo'], break_on_hyphens=True)
    check_wrap(text, 10, ['yaba', 'daba-doo'], break_on_hyphens=False)

def WrapTestCase__test_no_split_at_umlaut():
    wrapper = TextWrapper(width=45)
    text = 'Die Empfänger-Auswahl'
    check_wrap(text, 13, ['Die', 'Empfänger-', 'Auswahl'])

def WrapTestCase__test_umlaut_followed_by_dash():
    wrapper = TextWrapper(width=45)
    text = 'aa ää-ää'
    check_wrap(text, 7, ['aa ää-', 'ää'])

def WrapTestCase__test_non_breaking_space():
    wrapper = TextWrapper(width=45)
    text = 'This is a sentence with non-breaking\xa0space.'
    check_wrap(text, 20, ['This is a sentence', 'with non-', 'breaking\xa0space.'], break_on_hyphens=True)
    check_wrap(text, 20, ['This is a sentence', 'with', 'non-breaking\xa0space.'], break_on_hyphens=False)

def WrapTestCase__test_narrow_non_breaking_space():
    wrapper = TextWrapper(width=45)
    text = 'This is a sentence with non-breaking\u202fspace.'
    check_wrap(text, 20, ['This is a sentence', 'with non-', 'breaking\u202fspace.'], break_on_hyphens=True)
    check_wrap(text, 20, ['This is a sentence', 'with', 'non-breaking\u202fspace.'], break_on_hyphens=False)


# Helper methods from MaxLinesTestCase
def show(textin):
    if isinstance(textin, list):
        result = []
        for i in range(len(textin)):
            result.append('  %d: %r' % (i, textin[i]))
        result = '\n'.join(result) if result else '  no lines'
    elif isinstance(textin, str):
        result = '  %s\n' % repr(textin)
    return result

def check(result, expect):
    assertEqual(result, expect, 'expected:\n%s\nbut got:\n%s' % (show(expect), show(result)))

def check_wrap(text, width, expect, **kwargs):
    result = wrap(text, width, **kwargs)
    check(result, expect)

def check_split(text, expect):
    result = wrapper._split(text)
    assertEqual(result, expect, '\nexpected %r\nbut got  %r' % (expect, result))

# Test functions from MaxLinesTestCase
def MaxLinesTestCase__test_simple():
    check_wrap(text, 12, ['Hello [...]'], max_lines=0)
    check_wrap(text, 12, ['Hello [...]'], max_lines=1)
    check_wrap(text, 12, ['Hello there,', 'how [...]'], max_lines=2)
    check_wrap(text, 13, ['Hello there,', 'how are [...]'], max_lines=2)
    check_wrap(text, 80, [text], max_lines=1)
    check_wrap(text, 12, ['Hello there,', 'how are you', 'this fine', "day?  I'm", 'glad to hear', 'it!'], max_lines=6)

def MaxLinesTestCase__test_spaces():
    check_wrap(text, 12, ['Hello there,', 'how are you', 'this fine', 'day? [...]'], max_lines=4)
    check_wrap(text, 6, ['Hello', '[...]'], max_lines=2)
    check_wrap(text + ' ' * 10, 12, ['Hello there,', 'how are you', 'this fine', "day?  I'm", 'glad to hear', 'it!'], max_lines=6)

def MaxLinesTestCase__test_placeholder_backtrack():
    text = 'Good grief Python features are advancing quickly!'
    check_wrap(text, 12, ['Good grief', 'Python*****'], max_lines=3, placeholder='*****')


# Helper methods from LongWordTestCase
def show(textin):
    if isinstance(textin, list):
        result = []
        for i in range(len(textin)):
            result.append('  %d: %r' % (i, textin[i]))
        result = '\n'.join(result) if result else '  no lines'
    elif isinstance(textin, str):
        result = '  %s\n' % repr(textin)
    return result

def check(result, expect):
    assertEqual(result, expect, 'expected:\n%s\nbut got:\n%s' % (show(expect), show(result)))

def check_wrap(text, width, expect, **kwargs):
    result = wrap(text, width, **kwargs)
    check(result, expect)

def check_split(text, expect):
    result = wrapper._split(text)
    assertEqual(result, expect, '\nexpected %r\nbut got  %r' % (expect, result))

# Test functions from LongWordTestCase
def LongWordTestCase__test_break_long():
    wrapper = TextWrapper()
    text = 'Did you say "supercalifragilisticexpialidocious?"\nHow *do* you spell that odd word, anyways?\n'
    check_wrap(text, 30, ['Did you say "supercalifragilis', 'ticexpialidocious?" How *do*', 'you spell that odd word,', 'anyways?'])
    check_wrap(text, 50, ['Did you say "supercalifragilisticexpialidocious?"', 'How *do* you spell that odd word, anyways?'])
    check_wrap('-' * 10 + 'hello', 10, ['----------', '               h', '               e', '               l', '               l', '               o'], subsequent_indent=' ' * 15)
    check_wrap(text, 12, ['Did you say ', '"supercalifr', 'agilisticexp', 'ialidocious?', '" How *do*', 'you spell', 'that odd', 'word,', 'anyways?'])

def LongWordTestCase__test_nobreak_long():
    wrapper = TextWrapper()
    text = 'Did you say "supercalifragilisticexpialidocious?"\nHow *do* you spell that odd word, anyways?\n'
    wrapper.break_long_words = 0
    wrapper.width = 30
    expect = ['Did you say', '"supercalifragilisticexpialidocious?"', 'How *do* you spell that odd', 'word, anyways?']
    result = wrapper.wrap(text)
    check(result, expect)
    result = wrap(text, width=30, break_long_words=0)
    check(result, expect)

def LongWordTestCase__test_max_lines_long():
    wrapper = TextWrapper()
    text = 'Did you say "supercalifragilisticexpialidocious?"\nHow *do* you spell that odd word, anyways?\n'
    check_wrap(text, 12, ['Did you say ', '"supercalifr', 'agilisticexp', '[...]'], max_lines=4)


# Helper methods from LongWordWithHyphensTestCase
def show(textin):
    if isinstance(textin, list):
        result = []
        for i in range(len(textin)):
            result.append('  %d: %r' % (i, textin[i]))
        result = '\n'.join(result) if result else '  no lines'
    elif isinstance(textin, str):
        result = '  %s\n' % repr(textin)
    return result

def check(result, expect):
    assertEqual(result, expect, 'expected:\n%s\nbut got:\n%s' % (show(expect), show(result)))

def check_wrap(text, width, expect, **kwargs):
    result = wrap(text, width, **kwargs)
    check(result, expect)

def check_split(text, expect):
    result = wrapper._split(text)
    assertEqual(result, expect, '\nexpected %r\nbut got  %r' % (expect, result))

# Test functions from LongWordWithHyphensTestCase
def LongWordWithHyphensTestCase__test_break_long_words_on_hyphen():
    wrapper = TextWrapper()
    text1 = 'We used enyzme 2-succinyl-6-hydroxy-2,4-cyclohexadiene-1-carboxylate synthase.\n'
    text2 = '1234567890-1234567890--this_is_a_very_long_option_indeed-good-bye"\n'
    expected = ['We used enyzme 2-succinyl-6-hydroxy-2,4-', 'cyclohexadiene-1-carboxylate synthase.']
    check_wrap(text1, 50, expected)
    expected = ['We used', 'enyzme 2-', 'succinyl-', '6-hydroxy-', '2,4-', 'cyclohexad', 'iene-1-', 'carboxylat', 'e', 'synthase.']
    check_wrap(text1, 10, expected)
    expected = ['1234567890', '-123456789', '0--this_is', '_a_very_lo', 'ng_option_', 'indeed-', 'good-bye"']
    check_wrap(text2, 10, expected)

def LongWordWithHyphensTestCase__test_break_long_words_not_on_hyphen():
    wrapper = TextWrapper()
    text1 = 'We used enyzme 2-succinyl-6-hydroxy-2,4-cyclohexadiene-1-carboxylate synthase.\n'
    text2 = '1234567890-1234567890--this_is_a_very_long_option_indeed-good-bye"\n'
    expected = ['We used enyzme 2-succinyl-6-hydroxy-2,4-cyclohexad', 'iene-1-carboxylate synthase.']
    check_wrap(text1, 50, expected, break_on_hyphens=False)
    expected = ['We used', 'enyzme 2-s', 'uccinyl-6-', 'hydroxy-2,', '4-cyclohex', 'adiene-1-c', 'arboxylate', 'synthase.']
    check_wrap(text1, 10, expected, break_on_hyphens=False)
    expected = ['1234567890', '-123456789', '0--this_is', '_a_very_lo', 'ng_option_', 'indeed-', 'good-bye"']
    check_wrap(text2, 10, expected)

def LongWordWithHyphensTestCase__test_break_on_hyphen_but_not_long_words():
    wrapper = TextWrapper()
    text1 = 'We used enyzme 2-succinyl-6-hydroxy-2,4-cyclohexadiene-1-carboxylate synthase.\n'
    text2 = '1234567890-1234567890--this_is_a_very_long_option_indeed-good-bye"\n'
    expected = ['We used enyzme', '2-succinyl-6-hydroxy-2,4-cyclohexadiene-1-carboxylate', 'synthase.']
    check_wrap(text1, 50, expected, break_long_words=False)
    expected = ['We used', 'enyzme', '2-succinyl-6-hydroxy-2,4-cyclohexadiene-1-carboxylate', 'synthase.']
    check_wrap(text1, 10, expected, break_long_words=False)
    expected = ['1234567890', '-123456789', '0--this_is', '_a_very_lo', 'ng_option_', 'indeed-', 'good-bye"']
    check_wrap(text2, 10, expected)

def LongWordWithHyphensTestCase__test_do_not_break_long_words_or_on_hyphens():
    wrapper = TextWrapper()
    text1 = 'We used enyzme 2-succinyl-6-hydroxy-2,4-cyclohexadiene-1-carboxylate synthase.\n'
    text2 = '1234567890-1234567890--this_is_a_very_long_option_indeed-good-bye"\n'
    expected = ['We used enyzme', '2-succinyl-6-hydroxy-2,4-cyclohexadiene-1-carboxylate', 'synthase.']
    check_wrap(text1, 50, expected, break_long_words=False, break_on_hyphens=False)
    expected = ['We used', 'enyzme', '2-succinyl-6-hydroxy-2,4-cyclohexadiene-1-carboxylate', 'synthase.']
    check_wrap(text1, 10, expected, break_long_words=False, break_on_hyphens=False)
    expected = ['1234567890', '-123456789', '0--this_is', '_a_very_lo', 'ng_option_', 'indeed-', 'good-bye"']
    check_wrap(text2, 10, expected)


# Helper methods from IndentTestCases
def show(textin):
    if isinstance(textin, list):
        result = []
        for i in range(len(textin)):
            result.append('  %d: %r' % (i, textin[i]))
        result = '\n'.join(result) if result else '  no lines'
    elif isinstance(textin, str):
        result = '  %s\n' % repr(textin)
    return result

def check(result, expect):
    assertEqual(result, expect, 'expected:\n%s\nbut got:\n%s' % (show(expect), show(result)))

def check_wrap(text, width, expect, **kwargs):
    result = wrap(text, width, **kwargs)
    check(result, expect)

def check_split(text, expect):
    result = wrapper._split(text)
    assertEqual(result, expect, '\nexpected %r\nbut got  %r' % (expect, result))

# Test functions from IndentTestCases
def IndentTestCases__test_fill():
    text = 'This paragraph will be filled, first without any indentation,\nand then with some (including a hanging indent).'
    expect = 'This paragraph will be filled, first\nwithout any indentation, and then with\nsome (including a hanging indent).'
    result = fill(text, 40)
    check(result, expect)

def IndentTestCases__test_initial_indent():
    text = 'This paragraph will be filled, first without any indentation,\nand then with some (including a hanging indent).'
    expect = ['     This paragraph will be filled,', 'first without any indentation, and then', 'with some (including a hanging indent).']
    result = wrap(text, 40, initial_indent='     ')
    check(result, expect)
    expect = '\n'.join(expect)
    result = fill(text, 40, initial_indent='     ')
    check(result, expect)

def IndentTestCases__test_subsequent_indent():
    text = 'This paragraph will be filled, first without any indentation,\nand then with some (including a hanging indent).'
    expect = '  * This paragraph will be filled, first\n    without any indentation, and then\n    with some (including a hanging\n    indent).'
    result = fill(text, 40, initial_indent='  * ', subsequent_indent='    ')
    check(result, expect)


# Helper methods from DedentTestCase
def assertUnchanged(text):
    """assert that dedent() has no effect on 'text'"""
    assertEqual(text, dedent(text))

# Test functions from DedentTestCase
def DedentTestCase__test_dedent_nomargin():
    text = "Hello there.\nHow are you?\nOh good, I'm glad."
    assertUnchanged(text)
    text = 'Hello there.\n\nBoo!'
    assertUnchanged(text)
    text = 'Hello there.\n  This is indented.'
    assertUnchanged(text)
    text = 'Hello there.\n\n  Boo!\n'
    assertUnchanged(text)

def DedentTestCase__test_dedent_even():
    text = '  Hello there.\n  How are ya?\n  Oh good.'
    expect = 'Hello there.\nHow are ya?\nOh good.'
    assertEqual(expect, dedent(text))
    text = '  Hello there.\n\n  How are ya?\n  Oh good.\n'
    expect = 'Hello there.\n\nHow are ya?\nOh good.\n'
    assertEqual(expect, dedent(text))
    text = '  Hello there.\n  \n  How are ya?\n  Oh good.\n'
    expect = 'Hello there.\n\nHow are ya?\nOh good.\n'
    assertEqual(expect, dedent(text))

def DedentTestCase__test_dedent_uneven():
    text = '        def foo():\n            while 1:\n                return foo\n        '
    expect = 'def foo():\n    while 1:\n        return foo\n'
    assertEqual(expect, dedent(text))
    text = '  Foo\n    Bar\n\n   Baz\n'
    expect = 'Foo\n  Bar\n\n Baz\n'
    assertEqual(expect, dedent(text))
    text = '  Foo\n    Bar\n \n   Baz\n'
    expect = 'Foo\n  Bar\n\n Baz\n'
    assertEqual(expect, dedent(text))

def DedentTestCase__test_dedent_declining():
    text = '     Foo\n    Bar\n'
    expect = ' Foo\nBar\n'
    assertEqual(expect, dedent(text))
    text = '     Foo\n\n    Bar\n'
    expect = ' Foo\n\nBar\n'
    assertEqual(expect, dedent(text))
    text = '     Foo\n    \n    Bar\n'
    expect = ' Foo\n\nBar\n'
    assertEqual(expect, dedent(text))

def DedentTestCase__test_dedent_preserve_internal_tabs():
    text = '  hello\tthere\n  how are\tyou?'
    expect = 'hello\tthere\nhow are\tyou?'
    assertEqual(expect, dedent(text))
    assertEqual(expect, dedent(expect))

def DedentTestCase__test_dedent_preserve_margin_tabs():
    text = '  hello there\n\thow are you?'
    assertUnchanged(text)
    text = '        hello there\n\thow are you?'
    assertUnchanged(text)
    text = '\thello there\n\thow are you?'
    expect = 'hello there\nhow are you?'
    assertEqual(expect, dedent(text))
    text = '  \thello there\n  \thow are you?'
    assertEqual(expect, dedent(text))
    text = '  \t  hello there\n  \t  how are you?'
    assertEqual(expect, dedent(text))
    text = '  \thello there\n  \t  how are you?'
    expect = 'hello there\n  how are you?'
    assertEqual(expect, dedent(text))
    text = "  \thello there\n   \thow are you?\n \tI'm fine, thanks"
    expect = " \thello there\n  \thow are you?\n\tI'm fine, thanks"
    assertEqual(expect, dedent(text))


# Test functions from IndentTestCase
def IndentTestCase__test_indent_nomargin_default():
    for text in CASES:
        assertEqual(indent(text, ''), text)

def IndentTestCase__test_indent_nomargin_explicit_default():
    for text in CASES:
        assertEqual(indent(text, '', None), text)

def IndentTestCase__test_indent_nomargin_all_lines():
    predicate = lambda line: True
    for text in CASES:
        assertEqual(indent(text, '', predicate), text)

def IndentTestCase__test_indent_no_lines():
    predicate = lambda line: False
    for text in CASES:
        assertEqual(indent(text, '    ', predicate), text)

def IndentTestCase__test_roundtrip_spaces():
    for text in ROUNDTRIP_CASES:
        assertEqual(dedent(indent(text, '    ')), text)

def IndentTestCase__test_roundtrip_tabs():
    for text in ROUNDTRIP_CASES:
        assertEqual(dedent(indent(text, '\t\t')), text)

def IndentTestCase__test_roundtrip_mixed():
    for text in ROUNDTRIP_CASES:
        assertEqual(dedent(indent(text, ' \t  \t ')), text)

def IndentTestCase__test_indent_default():
    prefix = '  '
    expected = ('  Hi.\n  This is a test.\n  Testing.', '  Hi.\n  This is a test.\n\n  Testing.', '\n  Hi.\n  This is a test.\n  Testing.\n', '  Hi.\r\n  This is a test.\r\n  Testing.\r\n', '\n  Hi.\r\n  This is a test.\n\r\n  Testing.\r\n\n')
    for text, expect in zip(CASES, expected):
        assertEqual(indent(text, prefix), expect)

def IndentTestCase__test_indent_explicit_default():
    prefix = '  '
    expected = ('  Hi.\n  This is a test.\n  Testing.', '  Hi.\n  This is a test.\n\n  Testing.', '\n  Hi.\n  This is a test.\n  Testing.\n', '  Hi.\r\n  This is a test.\r\n  Testing.\r\n', '\n  Hi.\r\n  This is a test.\n\r\n  Testing.\r\n\n')
    for text, expect in zip(CASES, expected):
        assertEqual(indent(text, prefix, None), expect)

def IndentTestCase__test_indent_all_lines():
    prefix = '  '
    expected = ('  Hi.\n  This is a test.\n  Testing.', '  Hi.\n  This is a test.\n  \n  Testing.', '  \n  Hi.\n  This is a test.\n  Testing.\n', '  Hi.\r\n  This is a test.\r\n  Testing.\r\n', '  \n  Hi.\r\n  This is a test.\n  \r\n  Testing.\r\n  \n')
    predicate = lambda line: True
    for text, expect in zip(CASES, expected):
        assertEqual(indent(text, prefix, predicate), expect)

def IndentTestCase__test_indent_empty_lines():
    prefix = '  '
    expected = ('Hi.\nThis is a test.\nTesting.', 'Hi.\nThis is a test.\n  \nTesting.', '  \nHi.\nThis is a test.\nTesting.\n', 'Hi.\r\nThis is a test.\r\nTesting.\r\n', '  \nHi.\r\nThis is a test.\n  \r\nTesting.\r\n  \n')
    predicate = lambda line: not line.strip()
    for text, expect in zip(CASES, expected):
        assertEqual(indent(text, prefix, predicate), expect)


# Helper methods from ShortenTestCase
def show(textin):
    if isinstance(textin, list):
        result = []
        for i in range(len(textin)):
            result.append('  %d: %r' % (i, textin[i]))
        result = '\n'.join(result) if result else '  no lines'
    elif isinstance(textin, str):
        result = '  %s\n' % repr(textin)
    return result

def check(result, expect):
    assertEqual(result, expect, 'expected:\n%s\nbut got:\n%s' % (show(expect), show(result)))

def check_wrap(text, width, expect, **kwargs):
    result = wrap(text, width, **kwargs)
    check(result, expect)

def check_split(text, expect):
    result = wrapper._split(text)
    assertEqual(result, expect, '\nexpected %r\nbut got  %r' % (expect, result))

def check_shorten(text, width, expect, **kwargs):
    result = shorten(text, width, **kwargs)
    check(result, expect)

# Test functions from ShortenTestCase
def ShortenTestCase__test_simple():
    text = "Hello there, how are you this fine day? I'm glad to hear it!"
    check_shorten(text, 18, 'Hello there, [...]')
    check_shorten(text, len(text), text)
    check_shorten(text, len(text) - 1, "Hello there, how are you this fine day? I'm glad to [...]")

def ShortenTestCase__test_placeholder():
    text = "Hello there, how are you this fine day? I'm glad to hear it!"
    check_shorten(text, 17, 'Hello there,$$', placeholder='$$')
    check_shorten(text, 18, 'Hello there, how$$', placeholder='$$')
    check_shorten(text, 18, 'Hello there, $$', placeholder=' $$')
    check_shorten(text, len(text), text, placeholder='$$')
    check_shorten(text, len(text) - 1, "Hello there, how are you this fine day? I'm glad to hear$$", placeholder='$$')

def ShortenTestCase__test_empty_string():
    check_shorten('', 6, '')

def ShortenTestCase__test_whitespace():
    text = '\n            This is a  paragraph that  already has\n            line breaks and \t tabs too.'
    check_shorten(text, 62, 'This is a paragraph that already has line breaks and tabs too.')
    check_shorten(text, 61, 'This is a paragraph that already has line breaks and [...]')
    check_shorten('hello      world!  ', 12, 'hello world!')
    check_shorten('hello      world!  ', 11, 'hello [...]')
    check_shorten('hello      world!  ', 10, '[...]')

def ShortenTestCase__test_first_word_too_long_but_placeholder_fits():
    check_shorten('Helloo', 5, '[...]')


# ======================================================================
# Direct invocation
# ======================================================================

try:
    WrapTestCase__test_simple()
    print("WrapTestCase.test_simple: PASS")
except Exception as _e:
    print("WrapTestCase.test_simple: FAIL -", _e)
try:
    WrapTestCase__test_empty_string()
    print("WrapTestCase.test_empty_string: PASS")
except Exception as _e:
    print("WrapTestCase.test_empty_string: FAIL -", _e)
try:
    WrapTestCase__test_empty_string_with_initial_indent()
    print("WrapTestCase.test_empty_string_with_initial_indent: PASS")
except Exception as _e:
    print("WrapTestCase.test_empty_string_with_initial_indent: FAIL -", _e)
try:
    WrapTestCase__test_whitespace()
    print("WrapTestCase.test_whitespace: PASS")
except Exception as _e:
    print("WrapTestCase.test_whitespace: FAIL -", _e)
try:
    WrapTestCase__test_fix_sentence_endings()
    print("WrapTestCase.test_fix_sentence_endings: PASS")
except Exception as _e:
    print("WrapTestCase.test_fix_sentence_endings: FAIL -", _e)
try:
    WrapTestCase__test_wrap_short()
    print("WrapTestCase.test_wrap_short: PASS")
except Exception as _e:
    print("WrapTestCase.test_wrap_short: FAIL -", _e)
try:
    WrapTestCase__test_wrap_short_1line()
    print("WrapTestCase.test_wrap_short_1line: PASS")
except Exception as _e:
    print("WrapTestCase.test_wrap_short_1line: FAIL -", _e)
try:
    WrapTestCase__test_hyphenated()
    print("WrapTestCase.test_hyphenated: PASS")
except Exception as _e:
    print("WrapTestCase.test_hyphenated: FAIL -", _e)
try:
    WrapTestCase__test_hyphenated_numbers()
    print("WrapTestCase.test_hyphenated_numbers: PASS")
except Exception as _e:
    print("WrapTestCase.test_hyphenated_numbers: FAIL -", _e)
try:
    WrapTestCase__test_em_dash()
    print("WrapTestCase.test_em_dash: PASS")
except Exception as _e:
    print("WrapTestCase.test_em_dash: FAIL -", _e)
try:
    WrapTestCase__test_unix_options()
    print("WrapTestCase.test_unix_options: PASS")
except Exception as _e:
    print("WrapTestCase.test_unix_options: FAIL -", _e)
try:
    WrapTestCase__test_funky_hyphens()
    print("WrapTestCase.test_funky_hyphens: PASS")
except Exception as _e:
    print("WrapTestCase.test_funky_hyphens: FAIL -", _e)
try:
    WrapTestCase__test_punct_hyphens()
    print("WrapTestCase.test_punct_hyphens: PASS")
except Exception as _e:
    print("WrapTestCase.test_punct_hyphens: FAIL -", _e)
try:
    WrapTestCase__test_funky_parens()
    print("WrapTestCase.test_funky_parens: PASS")
except Exception as _e:
    print("WrapTestCase.test_funky_parens: FAIL -", _e)
try:
    WrapTestCase__test_drop_whitespace_false()
    print("WrapTestCase.test_drop_whitespace_false: PASS")
except Exception as _e:
    print("WrapTestCase.test_drop_whitespace_false: FAIL -", _e)
try:
    WrapTestCase__test_drop_whitespace_false_whitespace_only()
    print("WrapTestCase.test_drop_whitespace_false_whitespace_only: PASS")
except Exception as _e:
    print("WrapTestCase.test_drop_whitespace_false_whitespace_only: FAIL -", _e)
try:
    WrapTestCase__test_drop_whitespace_false_whitespace_only_with_indent()
    print("WrapTestCase.test_drop_whitespace_false_whitespace_only_with_indent: PASS")
except Exception as _e:
    print("WrapTestCase.test_drop_whitespace_false_whitespace_only_with_indent: FAIL -", _e)
try:
    WrapTestCase__test_drop_whitespace_whitespace_only()
    print("WrapTestCase.test_drop_whitespace_whitespace_only: PASS")
except Exception as _e:
    print("WrapTestCase.test_drop_whitespace_whitespace_only: FAIL -", _e)
try:
    WrapTestCase__test_drop_whitespace_leading_whitespace()
    print("WrapTestCase.test_drop_whitespace_leading_whitespace: PASS")
except Exception as _e:
    print("WrapTestCase.test_drop_whitespace_leading_whitespace: FAIL -", _e)
try:
    WrapTestCase__test_drop_whitespace_whitespace_line()
    print("WrapTestCase.test_drop_whitespace_whitespace_line: PASS")
except Exception as _e:
    print("WrapTestCase.test_drop_whitespace_whitespace_line: FAIL -", _e)
try:
    WrapTestCase__test_drop_whitespace_whitespace_only_with_indent()
    print("WrapTestCase.test_drop_whitespace_whitespace_only_with_indent: PASS")
except Exception as _e:
    print("WrapTestCase.test_drop_whitespace_whitespace_only_with_indent: FAIL -", _e)
try:
    WrapTestCase__test_drop_whitespace_whitespace_indent()
    print("WrapTestCase.test_drop_whitespace_whitespace_indent: PASS")
except Exception as _e:
    print("WrapTestCase.test_drop_whitespace_whitespace_indent: FAIL -", _e)
try:
    WrapTestCase__test_split()
    print("WrapTestCase.test_split: PASS")
except Exception as _e:
    print("WrapTestCase.test_split: FAIL -", _e)
try:
    WrapTestCase__test_break_on_hyphens()
    print("WrapTestCase.test_break_on_hyphens: PASS")
except Exception as _e:
    print("WrapTestCase.test_break_on_hyphens: FAIL -", _e)
try:
    WrapTestCase__test_no_split_at_umlaut()
    print("WrapTestCase.test_no_split_at_umlaut: PASS")
except Exception as _e:
    print("WrapTestCase.test_no_split_at_umlaut: FAIL -", _e)
try:
    WrapTestCase__test_umlaut_followed_by_dash()
    print("WrapTestCase.test_umlaut_followed_by_dash: PASS")
except Exception as _e:
    print("WrapTestCase.test_umlaut_followed_by_dash: FAIL -", _e)
try:
    WrapTestCase__test_non_breaking_space()
    print("WrapTestCase.test_non_breaking_space: PASS")
except Exception as _e:
    print("WrapTestCase.test_non_breaking_space: FAIL -", _e)
try:
    WrapTestCase__test_narrow_non_breaking_space()
    print("WrapTestCase.test_narrow_non_breaking_space: PASS")
except Exception as _e:
    print("WrapTestCase.test_narrow_non_breaking_space: FAIL -", _e)
try:
    MaxLinesTestCase__test_simple()
    print("MaxLinesTestCase.test_simple: PASS")
except Exception as _e:
    print("MaxLinesTestCase.test_simple: FAIL -", _e)
try:
    MaxLinesTestCase__test_spaces()
    print("MaxLinesTestCase.test_spaces: PASS")
except Exception as _e:
    print("MaxLinesTestCase.test_spaces: FAIL -", _e)
try:
    MaxLinesTestCase__test_placeholder_backtrack()
    print("MaxLinesTestCase.test_placeholder_backtrack: PASS")
except Exception as _e:
    print("MaxLinesTestCase.test_placeholder_backtrack: FAIL -", _e)
try:
    LongWordTestCase__test_break_long()
    print("LongWordTestCase.test_break_long: PASS")
except Exception as _e:
    print("LongWordTestCase.test_break_long: FAIL -", _e)
try:
    LongWordTestCase__test_nobreak_long()
    print("LongWordTestCase.test_nobreak_long: PASS")
except Exception as _e:
    print("LongWordTestCase.test_nobreak_long: FAIL -", _e)
try:
    LongWordTestCase__test_max_lines_long()
    print("LongWordTestCase.test_max_lines_long: PASS")
except Exception as _e:
    print("LongWordTestCase.test_max_lines_long: FAIL -", _e)
try:
    LongWordWithHyphensTestCase__test_break_long_words_on_hyphen()
    print("LongWordWithHyphensTestCase.test_break_long_words_on_hyphen: PASS")
except Exception as _e:
    print("LongWordWithHyphensTestCase.test_break_long_words_on_hyphen: FAIL -", _e)
try:
    LongWordWithHyphensTestCase__test_break_long_words_not_on_hyphen()
    print("LongWordWithHyphensTestCase.test_break_long_words_not_on_hyphen: PASS")
except Exception as _e:
    print("LongWordWithHyphensTestCase.test_break_long_words_not_on_hyphen: FAIL -", _e)
try:
    LongWordWithHyphensTestCase__test_break_on_hyphen_but_not_long_words()
    print("LongWordWithHyphensTestCase.test_break_on_hyphen_but_not_long_words: PASS")
except Exception as _e:
    print("LongWordWithHyphensTestCase.test_break_on_hyphen_but_not_long_words: FAIL -", _e)
try:
    LongWordWithHyphensTestCase__test_do_not_break_long_words_or_on_hyphens()
    print("LongWordWithHyphensTestCase.test_do_not_break_long_words_or_on_hyphens: PASS")
except Exception as _e:
    print("LongWordWithHyphensTestCase.test_do_not_break_long_words_or_on_hyphens: FAIL -", _e)
try:
    IndentTestCases__test_fill()
    print("IndentTestCases.test_fill: PASS")
except Exception as _e:
    print("IndentTestCases.test_fill: FAIL -", _e)
try:
    IndentTestCases__test_initial_indent()
    print("IndentTestCases.test_initial_indent: PASS")
except Exception as _e:
    print("IndentTestCases.test_initial_indent: FAIL -", _e)
try:
    IndentTestCases__test_subsequent_indent()
    print("IndentTestCases.test_subsequent_indent: PASS")
except Exception as _e:
    print("IndentTestCases.test_subsequent_indent: FAIL -", _e)
try:
    DedentTestCase__test_dedent_nomargin()
    print("DedentTestCase.test_dedent_nomargin: PASS")
except Exception as _e:
    print("DedentTestCase.test_dedent_nomargin: FAIL -", _e)
try:
    DedentTestCase__test_dedent_even()
    print("DedentTestCase.test_dedent_even: PASS")
except Exception as _e:
    print("DedentTestCase.test_dedent_even: FAIL -", _e)
try:
    DedentTestCase__test_dedent_uneven()
    print("DedentTestCase.test_dedent_uneven: PASS")
except Exception as _e:
    print("DedentTestCase.test_dedent_uneven: FAIL -", _e)
try:
    DedentTestCase__test_dedent_declining()
    print("DedentTestCase.test_dedent_declining: PASS")
except Exception as _e:
    print("DedentTestCase.test_dedent_declining: FAIL -", _e)
try:
    DedentTestCase__test_dedent_preserve_internal_tabs()
    print("DedentTestCase.test_dedent_preserve_internal_tabs: PASS")
except Exception as _e:
    print("DedentTestCase.test_dedent_preserve_internal_tabs: FAIL -", _e)
try:
    DedentTestCase__test_dedent_preserve_margin_tabs()
    print("DedentTestCase.test_dedent_preserve_margin_tabs: PASS")
except Exception as _e:
    print("DedentTestCase.test_dedent_preserve_margin_tabs: FAIL -", _e)
try:
    IndentTestCase__test_indent_nomargin_default()
    print("IndentTestCase.test_indent_nomargin_default: PASS")
except Exception as _e:
    print("IndentTestCase.test_indent_nomargin_default: FAIL -", _e)
try:
    IndentTestCase__test_indent_nomargin_explicit_default()
    print("IndentTestCase.test_indent_nomargin_explicit_default: PASS")
except Exception as _e:
    print("IndentTestCase.test_indent_nomargin_explicit_default: FAIL -", _e)
try:
    IndentTestCase__test_indent_nomargin_all_lines()
    print("IndentTestCase.test_indent_nomargin_all_lines: PASS")
except Exception as _e:
    print("IndentTestCase.test_indent_nomargin_all_lines: FAIL -", _e)
try:
    IndentTestCase__test_indent_no_lines()
    print("IndentTestCase.test_indent_no_lines: PASS")
except Exception as _e:
    print("IndentTestCase.test_indent_no_lines: FAIL -", _e)
try:
    IndentTestCase__test_roundtrip_spaces()
    print("IndentTestCase.test_roundtrip_spaces: PASS")
except Exception as _e:
    print("IndentTestCase.test_roundtrip_spaces: FAIL -", _e)
try:
    IndentTestCase__test_roundtrip_tabs()
    print("IndentTestCase.test_roundtrip_tabs: PASS")
except Exception as _e:
    print("IndentTestCase.test_roundtrip_tabs: FAIL -", _e)
try:
    IndentTestCase__test_roundtrip_mixed()
    print("IndentTestCase.test_roundtrip_mixed: PASS")
except Exception as _e:
    print("IndentTestCase.test_roundtrip_mixed: FAIL -", _e)
try:
    IndentTestCase__test_indent_default()
    print("IndentTestCase.test_indent_default: PASS")
except Exception as _e:
    print("IndentTestCase.test_indent_default: FAIL -", _e)
try:
    IndentTestCase__test_indent_explicit_default()
    print("IndentTestCase.test_indent_explicit_default: PASS")
except Exception as _e:
    print("IndentTestCase.test_indent_explicit_default: FAIL -", _e)
try:
    IndentTestCase__test_indent_all_lines()
    print("IndentTestCase.test_indent_all_lines: PASS")
except Exception as _e:
    print("IndentTestCase.test_indent_all_lines: FAIL -", _e)
try:
    IndentTestCase__test_indent_empty_lines()
    print("IndentTestCase.test_indent_empty_lines: PASS")
except Exception as _e:
    print("IndentTestCase.test_indent_empty_lines: FAIL -", _e)
try:
    ShortenTestCase__test_simple()
    print("ShortenTestCase.test_simple: PASS")
except Exception as _e:
    print("ShortenTestCase.test_simple: FAIL -", _e)
try:
    ShortenTestCase__test_placeholder()
    print("ShortenTestCase.test_placeholder: PASS")
except Exception as _e:
    print("ShortenTestCase.test_placeholder: FAIL -", _e)
try:
    ShortenTestCase__test_empty_string()
    print("ShortenTestCase.test_empty_string: PASS")
except Exception as _e:
    print("ShortenTestCase.test_empty_string: FAIL -", _e)
try:
    ShortenTestCase__test_whitespace()
    print("ShortenTestCase.test_whitespace: PASS")
except Exception as _e:
    print("ShortenTestCase.test_whitespace: FAIL -", _e)
try:
    ShortenTestCase__test_first_word_too_long_but_placeholder_fits()
    print("ShortenTestCase.test_first_word_too_long_but_placeholder_fits: PASS")
except Exception as _e:
    print("ShortenTestCase.test_first_word_too_long_but_placeholder_fits: FAIL -", _e)