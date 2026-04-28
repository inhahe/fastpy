"""
Standalone Django template test suite adapted from Django's template_tests.

Exercises core template engine functionality:
- Variable substitution
- For loops, if/else, ifequal
- Filters (escape, upper, lower, length, default, etc.)
- Context operations
- Template rendering with various data types
- Table generation (pyperformance benchmark)

No unittest dependency — uses simple assert + print for verification.
"""

import time
import django.conf
from django.template import Context, Template


def assert_equal(actual, expected, msg=""):
    if actual != expected:
        print("FAIL: " + msg)
        print("  expected: " + repr(expected))
        print("  actual:   " + repr(actual))
        return False
    return True


def test_basic_syntax():
    """Plain text, variable substitution, multiple variables."""
    passed = 0
    total = 0

    # Plain text passthrough
    total += 1
    t = Template("something cool")
    out = t.render(Context({}))
    if assert_equal(out, "something cool", "plain text"):
        passed += 1

    # Single variable
    total += 1
    t = Template("{{ headline }}")
    out = t.render(Context({"headline": "Success"}))
    if assert_equal(out, "Success", "single variable"):
        passed += 1

    # Multiple variables
    total += 1
    t = Template("{{ first }} --- {{ second }}")
    out = t.render(Context({"first": 1, "second": 2}))
    if assert_equal(out, "1 --- 2", "multiple variables"):
        passed += 1

    # Missing variable (silent fail)
    total += 1
    t = Template("as{{ missing }}df")
    out = t.render(Context({}))
    if assert_equal(out, "asdf", "missing variable"):
        passed += 1

    # Literal string in variable
    total += 1
    t = Template('{{ "fred" }}')
    out = t.render(Context({}))
    if assert_equal(out, "fred", "literal string"):
        passed += 1

    # Integer literal
    total += 1
    t = Template("{{ 1 }}")
    out = t.render(Context({"1": "abc"}))
    if assert_equal(out, "1", "integer literal"):
        passed += 1

    # Float literal
    total += 1
    t = Template("{{ 1.2 }}")
    out = t.render(Context({"1": "abc"}))
    if assert_equal(out, "1.2", "float literal"):
        passed += 1

    print("  basic_syntax: " + str(passed) + "/" + str(total))
    return passed, total


def test_for_loop():
    """For loop tag: iteration, forloop counter, empty."""
    passed = 0
    total = 0

    # Basic for loop
    total += 1
    t = Template("{% for item in items %}{{ item }},{% endfor %}")
    out = t.render(Context({"items": ["a", "b", "c"]}))
    if assert_equal(out, "a,b,c,", "basic for"):
        passed += 1

    # forloop.counter
    total += 1
    t = Template("{% for item in items %}{{ forloop.counter }}{% endfor %}")
    out = t.render(Context({"items": ["a", "b", "c"]}))
    if assert_equal(out, "123", "forloop.counter"):
        passed += 1

    # forloop.counter0
    total += 1
    t = Template("{% for item in items %}{{ forloop.counter0 }}{% endfor %}")
    out = t.render(Context({"items": ["a", "b", "c"]}))
    if assert_equal(out, "012", "forloop.counter0"):
        passed += 1

    # forloop.first / forloop.last
    total += 1
    t = Template("{% for item in items %}{% if forloop.first %}FIRST{% endif %}{% if forloop.last %}LAST{% endif %}{% endfor %}")
    out = t.render(Context({"items": [1, 2, 3]}))
    if assert_equal(out, "FIRSTLAST", "forloop.first/last"):
        passed += 1

    # Nested for loops
    total += 1
    t = Template("{% for row in table %}{% for col in row %}{{ col }}{% endfor %};{% endfor %}")
    out = t.render(Context({"table": [[1, 2], [3, 4]]}))
    if assert_equal(out, "12;34;", "nested for"):
        passed += 1

    # for...empty
    total += 1
    t = Template("{% for item in items %}{{ item }}{% empty %}EMPTY{% endfor %}")
    out = t.render(Context({"items": []}))
    if assert_equal(out, "EMPTY", "for...empty"):
        passed += 1

    # for loop with range
    total += 1
    t = Template("{% for i in nums %}{{ i }}{% endfor %}")
    out = t.render(Context({"nums": range(5)}))
    if assert_equal(out, "01234", "for with range"):
        passed += 1

    print("  for_loop: " + str(passed) + "/" + str(total))
    return passed, total


def test_if_tag():
    """If/elif/else tag."""
    passed = 0
    total = 0

    # Basic if true
    total += 1
    t = Template("{% if x %}YES{% endif %}")
    out = t.render(Context({"x": True}))
    if assert_equal(out, "YES", "if true"):
        passed += 1

    # Basic if false
    total += 1
    t = Template("{% if x %}YES{% endif %}")
    out = t.render(Context({"x": False}))
    if assert_equal(out, "", "if false"):
        passed += 1

    # if...else
    total += 1
    t = Template("{% if x %}YES{% else %}NO{% endif %}")
    out = t.render(Context({"x": False}))
    if assert_equal(out, "NO", "if...else"):
        passed += 1

    # if...elif...else
    total += 1
    t = Template("{% if x == 1 %}ONE{% elif x == 2 %}TWO{% else %}OTHER{% endif %}")
    out = t.render(Context({"x": 2}))
    if assert_equal(out, "TWO", "if...elif"):
        passed += 1

    # if with and
    total += 1
    t = Template("{% if x and y %}BOTH{% endif %}")
    out = t.render(Context({"x": True, "y": True}))
    if assert_equal(out, "BOTH", "if and"):
        passed += 1

    # if with or
    total += 1
    t = Template("{% if x or y %}EITHER{% endif %}")
    out = t.render(Context({"x": False, "y": True}))
    if assert_equal(out, "EITHER", "if or"):
        passed += 1

    # if with not
    total += 1
    t = Template("{% if not x %}NEGATED{% endif %}")
    out = t.render(Context({"x": False}))
    if assert_equal(out, "NEGATED", "if not"):
        passed += 1

    # if with comparison
    total += 1
    t = Template("{% if x > 5 %}BIG{% else %}SMALL{% endif %}")
    out = t.render(Context({"x": 10}))
    if assert_equal(out, "BIG", "if comparison"):
        passed += 1

    # if with in operator
    total += 1
    t = Template("{% if 'a' in items %}FOUND{% endif %}")
    out = t.render(Context({"items": ["a", "b", "c"]}))
    if assert_equal(out, "FOUND", "if in"):
        passed += 1

    print("  if_tag: " + str(passed) + "/" + str(total))
    return passed, total


def test_filters():
    """Built-in template filters."""
    passed = 0
    total = 0

    # escape filter
    total += 1
    t = Template("{{ text|escape }}")
    out = t.render(Context({"text": "<b>bold</b>"}))
    if assert_equal(out, "&lt;b&gt;bold&lt;/b&gt;", "escape"):
        passed += 1

    # upper filter
    total += 1
    t = Template("{{ text|upper }}")
    out = t.render(Context({"text": "hello"}))
    if assert_equal(out, "HELLO", "upper"):
        passed += 1

    # lower filter
    total += 1
    t = Template("{{ text|lower }}")
    out = t.render(Context({"text": "HELLO"}))
    if assert_equal(out, "hello", "lower"):
        passed += 1

    # length filter
    total += 1
    t = Template("{{ items|length }}")
    out = t.render(Context({"items": [1, 2, 3, 4, 5]}))
    if assert_equal(out, "5", "length"):
        passed += 1

    # default filter
    total += 1
    t = Template("{{ val|default:'nothing' }}")
    out = t.render(Context({"val": ""}))
    if assert_equal(out, "nothing", "default empty"):
        passed += 1

    total += 1
    t = Template("{{ val|default:'nothing' }}")
    out = t.render(Context({"val": "something"}))
    if assert_equal(out, "something", "default with value"):
        passed += 1

    # default_if_none filter
    total += 1
    t = Template("{{ val|default_if_none:'was none' }}")
    out = t.render(Context({"val": None}))
    if assert_equal(out, "was none", "default_if_none"):
        passed += 1

    # join filter
    total += 1
    t = Template('{{ items|join:", " }}')
    out = t.render(Context({"items": ["a", "b", "c"]}))
    if assert_equal(out, "a, b, c", "join"):
        passed += 1

    # first / last
    total += 1
    t = Template("{{ items|first }}")
    out = t.render(Context({"items": ["a", "b", "c"]}))
    if assert_equal(out, "a", "first"):
        passed += 1

    total += 1
    t = Template("{{ items|last }}")
    out = t.render(Context({"items": ["a", "b", "c"]}))
    if assert_equal(out, "c", "last"):
        passed += 1

    # capfirst
    total += 1
    t = Template("{{ text|capfirst }}")
    out = t.render(Context({"text": "hello world"}))
    if assert_equal(out, "Hello world", "capfirst"):
        passed += 1

    # title
    total += 1
    t = Template("{{ text|title }}")
    out = t.render(Context({"text": "hello world"}))
    if assert_equal(out, "Hello World", "title"):
        passed += 1

    # truncatechars
    total += 1
    t = Template("{{ text|truncatechars:10 }}")
    out = t.render(Context({"text": "Hello World, this is a test"}))
    if assert_equal(out, "Hello Wor\u2026", "truncatechars"):
        passed += 1

    # add filter (numeric)
    total += 1
    t = Template("{{ val|add:5 }}")
    out = t.render(Context({"val": 10}))
    if assert_equal(out, "15", "add numeric"):
        passed += 1

    # yesno filter
    total += 1
    t = Template("{{ val|yesno:'yes,no,maybe' }}")
    out = t.render(Context({"val": True}))
    if assert_equal(out, "yes", "yesno true"):
        passed += 1

    total += 1
    t = Template("{{ val|yesno:'yes,no,maybe' }}")
    out = t.render(Context({"val": False}))
    if assert_equal(out, "no", "yesno false"):
        passed += 1

    total += 1
    t = Template("{{ val|yesno:'yes,no,maybe' }}")
    out = t.render(Context({"val": None}))
    if assert_equal(out, "maybe", "yesno none"):
        passed += 1

    # safe filter (mark as safe, no auto-escape)
    total += 1
    t = Template("{% autoescape on %}{{ text|safe }}{% endautoescape %}")
    out = t.render(Context({"text": "<b>bold</b>"}))
    if assert_equal(out, "<b>bold</b>", "safe"):
        passed += 1

    # cut filter
    total += 1
    t = Template("{{ text|cut:' ' }}")
    out = t.render(Context({"text": "hello world"}))
    if assert_equal(out, "helloworld", "cut"):
        passed += 1

    # linebreaksbr
    total += 1
    t = Template("{{ text|linebreaksbr }}")
    out = t.render(Context({"text": "line1\nline2"}))
    if assert_equal(out, "line1<br>line2", "linebreaksbr"):
        passed += 1

    print("  filters: " + str(passed) + "/" + str(total))
    return passed, total


def test_autoescape():
    """Autoescape behavior."""
    passed = 0
    total = 0

    # Default autoescape on
    total += 1
    t = Template("{{ text }}")
    out = t.render(Context({"text": "<script>alert('xss')</script>"}))
    if assert_equal(out, "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", "autoescape default"):
        passed += 1

    # Autoescape off
    total += 1
    t = Template("{% autoescape off %}{{ text }}{% endautoescape %}")
    out = t.render(Context({"text": "<b>bold</b>"}))
    if assert_equal(out, "<b>bold</b>", "autoescape off"):
        passed += 1

    print("  autoescape: " + str(passed) + "/" + str(total))
    return passed, total


def test_comment():
    """Comment tag."""
    passed = 0
    total = 0

    total += 1
    t = Template("before{# this is a comment #}after")
    out = t.render(Context({}))
    if assert_equal(out, "beforeafter", "inline comment"):
        passed += 1

    total += 1
    t = Template("before{% comment %}this is hidden{% endcomment %}after")
    out = t.render(Context({}))
    if assert_equal(out, "beforeafter", "block comment"):
        passed += 1

    print("  comment: " + str(passed) + "/" + str(total))
    return passed, total


def test_spaceless():
    """Spaceless tag."""
    passed = 0
    total = 0

    total += 1
    t = Template("{% spaceless %}<p> <a> test </a> </p>{% endspaceless %}")
    out = t.render(Context({}))
    if assert_equal(out, "<p><a> test </a></p>", "spaceless"):
        passed += 1

    print("  spaceless: " + str(passed) + "/" + str(total))
    return passed, total


def test_with():
    """With tag for variable aliasing."""
    passed = 0
    total = 0

    total += 1
    t = Template("{% with x=42 %}{{ x }}{% endwith %}")
    out = t.render(Context({}))
    if assert_equal(out, "42", "with assign"):
        passed += 1

    total += 1
    t = Template("{% with total=items|length %}count={{ total }}{% endwith %}")
    out = t.render(Context({"items": [1, 2, 3]}))
    if assert_equal(out, "count=3", "with filter"):
        passed += 1

    print("  with: " + str(passed) + "/" + str(total))
    return passed, total


def test_cycle():
    """Cycle tag."""
    passed = 0
    total = 0

    total += 1
    t = Template("{% for i in items %}{% cycle 'odd' 'even' %}{% endfor %}")
    out = t.render(Context({"items": [1, 2, 3, 4]}))
    if assert_equal(out, "oddevenoddeven", "cycle"):
        passed += 1

    print("  cycle: " + str(passed) + "/" + str(total))
    return passed, total


def test_firstof():
    """Firstof tag."""
    passed = 0
    total = 0

    total += 1
    t = Template("{% firstof a b c %}")
    out = t.render(Context({"a": 0, "b": "", "c": "third"}))
    if assert_equal(out, "third", "firstof"):
        passed += 1

    total += 1
    t = Template("{% firstof a b c 'fallback' %}")
    out = t.render(Context({"a": 0, "b": "", "c": ""}))
    if assert_equal(out, "fallback", "firstof fallback"):
        passed += 1

    print("  firstof: " + str(passed) + "/" + str(total))
    return passed, total


def test_now():
    """Now tag (just verify it doesn't crash)."""
    passed = 0
    total = 0

    total += 1
    t = Template("{% now 'Y' %}")
    out = t.render(Context({}))
    # Just check it produced a 4-digit year
    if len(out) == 4 and out.isdigit():
        passed += 1
    else:
        print("FAIL: now tag, got: " + repr(out))

    print("  now: " + str(passed) + "/" + str(total))
    return passed, total


def test_widthratio():
    """Widthratio tag."""
    passed = 0
    total = 0

    total += 1
    t = Template("{% widthratio 50 100 200 %}")
    out = t.render(Context({}))
    if assert_equal(out, "100", "widthratio"):
        passed += 1

    print("  widthratio: " + str(passed) + "/" + str(total))
    return passed, total


def test_table_generation():
    """Performance test: generate an HTML table (from pyperformance)."""
    passed = 0
    total = 0

    total += 1
    template = Template("""<table>
{% for row in table %}
<tr>{% for col in row %}<td>{{ col|escape }}</td>{% endfor %}</tr>
{% endfor %}
</table>
    """)
    table = [range(10) for _ in range(10)]
    context = Context({"table": table})

    # Warm up
    template.render(context)

    # Timed run
    ITERATIONS = 3
    t0 = time.perf_counter()
    for _ in range(ITERATIONS):
        result = template.render(context)
    elapsed = time.perf_counter() - t0

    # Verify output contains expected content
    has0 = "<td>0</td>" in result
    has9 = "<td>9</td>" in result
    hastable = "<table>" in result
    if has0 and has9 and hastable:
        passed += 1
    else:
        print("FAIL: table generation output incorrect")

    ms = elapsed / ITERATIONS * 1000
    print("  table_generation: " + str(passed) + "/" + str(total) + " (%.1f ms/iter)" % ms)
    return passed, total


def run_all_tests():
    total_passed = 0
    total_tests = 0

    results = []
    results.append(test_basic_syntax())
    results.append(test_for_loop())
    results.append(test_if_tag())
    results.append(test_filters())
    results.append(test_autoescape())
    results.append(test_comment())
    results.append(test_spaceless())
    results.append(test_with())
    results.append(test_cycle())
    results.append(test_firstof())
    results.append(test_now())
    results.append(test_widthratio())
    results.append(test_table_generation())

    for p, t in results:
        total_passed += p
        total_tests += t

    print("")
    if total_passed == total_tests:
        print("ALL TESTS PASSED: " + str(total_passed) + "/" + str(total_tests))
    else:
        print("SOME TESTS FAILED: " + str(total_passed) + "/" + str(total_tests))


if __name__ == "__main__":
    django.conf.settings.configure(TEMPLATES=[{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
    }])
    django.setup()

    run_all_tests()
