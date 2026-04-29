"""
Core differential tests — inline Python snippets tested against CPython.

These test the harness itself and provide basic coverage for language
features as the compiler grows. Each test is a small Python program
that prints a deterministic result.

Tests use the `assert_compiles` fixture which:
    - Runs the source under CPython
    - Compiles with fastpy and runs the binary
    - Compares stdout, stderr, and exit code
    - SKIPs if the compiler can't handle it yet
    - FAILs if output differs
"""

from __future__ import annotations


class TestHarnessBasics:
    """Verify the test harness itself works correctly."""

    def test_cpython_runs_simple_program(self):
        """Sanity check: CPython can run a program and we capture output."""
        from tests.harness import run_cpython
        result = run_cpython("print('hello')")
        assert result.stdout.strip() == "hello"
        assert result.exit_code == 0

    def test_cpython_captures_exit_code(self):
        from tests.harness import run_cpython
        result = run_cpython("import sys; sys.exit(42)")
        assert result.exit_code == 42

    def test_cpython_captures_stderr(self):
        from tests.harness import run_cpython
        result = run_cpython("import sys; print('err', file=sys.stderr)")
        assert "err" in result.stderr

    def test_cpython_handles_timeout(self):
        from tests.harness import run_cpython
        result = run_cpython("import time; time.sleep(999)", timeout=0.5)
        assert result.timed_out

    def test_diff_test_passes_for_simple_print(self):
        """The compiler can handle print(literal) and output matches CPython."""
        from tests.harness import diff_test
        result = diff_test("print('hello')")
        assert result.passed
        assert result.cpython is not None
        assert result.cpython.stdout.strip() == "hello"


class TestArithmetic:
    """Basic integer and float arithmetic."""

    def test_int_add(self, assert_compiles):
        assert_compiles("print(1 + 2)")

    def test_int_sub(self, assert_compiles):
        assert_compiles("print(10 - 3)")

    def test_int_mul(self, assert_compiles):
        assert_compiles("print(6 * 7)")

    def test_int_floordiv(self, assert_compiles):
        assert_compiles("print(17 // 3)")

    def test_int_mod(self, assert_compiles):
        assert_compiles("print(17 % 3)")

    def test_int_pow(self, assert_compiles):
        assert_compiles("print(2 ** 10)")

    def test_int_neg(self, assert_compiles):
        assert_compiles("print(-42)")

    def test_float_add(self, assert_compiles):
        assert_compiles("print(1.5 + 2.5)")

    def test_float_mul(self, assert_compiles):
        assert_compiles("print(3.0 * 2.5)")

    def test_float_div(self, assert_compiles):
        assert_compiles("print(10.0 / 3.0)")

    def test_mixed_arith(self, assert_compiles):
        assert_compiles("print(1 + 2.5)")

    def test_big_int(self, assert_compiles):
        assert_compiles("print(2 ** 100)")

    def test_negative_floordiv(self, assert_compiles):
        assert_compiles("print(-7 // 2)")

    def test_chained_ops(self, assert_compiles):
        assert_compiles("print(1 + 2 * 3 - 4)")

    def test_bitwise_and(self, assert_compiles):
        assert_compiles("print(5 & 3)")

    def test_bitwise_or(self, assert_compiles):
        assert_compiles("print(5 | 3)")

    def test_bitwise_xor(self, assert_compiles):
        assert_compiles("print(5 ^ 3)")

    def test_shift_left(self, assert_compiles):
        assert_compiles("print(1 << 10)")

    def test_shift_right(self, assert_compiles):
        assert_compiles("print(1024 >> 3)")

    def test_bitwise_not(self, assert_compiles):
        assert_compiles("print(~5)")

    def test_pow_builtin(self, assert_compiles):
        assert_compiles("print(pow(2, 10))")

    def test_pow_mod(self, assert_compiles):
        assert_compiles("print(pow(2, 10, 1000))")


class TestStrings:
    """String operations."""

    def test_string_concat(self, assert_compiles):
        assert_compiles("print('hello' + ' ' + 'world')")

    def test_string_repeat(self, assert_compiles):
        assert_compiles("print('ab' * 3)")

    def test_string_len(self, assert_compiles):
        assert_compiles("print(len('hello'))")

    def test_string_index(self, assert_compiles):
        assert_compiles("print('hello'[1])")

    def test_string_slice(self, assert_compiles):
        assert_compiles("print('hello'[1:4])")

    def test_string_slice_step(self, assert_compiles):
        assert_compiles("print('abcdef'[::2])")

    def test_string_slice_reverse(self, assert_compiles):
        assert_compiles("print('abcdef'[::-1])")

    def test_fstring(self, assert_compiles):
        assert_compiles("x = 42; print(f'value is {x}')")

    def test_fstring_format_spec(self, assert_compiles):
        assert_compiles('x = 3.14\nprint(f"{x:.1f}")')

    def test_fstring_int_spec(self, assert_compiles):
        assert_compiles('n = 42\nprint(f"{n:5d}")')

    def test_string_methods(self, assert_compiles):
        assert_compiles("print('Hello World'.lower())")

    def test_string_split_join(self, assert_compiles):
        assert_compiles("print('-'.join('hello world'.split()))")

    def test_str_format_basic(self, assert_compiles):
        assert_compiles('print("{} is {}".format("age", 25))')

    def test_str_format_positional(self, assert_compiles):
        assert_compiles('print("{0} and {1} and {0}".format("a", "b"))')

    def test_str_format_named(self, assert_compiles):
        assert_compiles('print("{name} is {age}".format(name="Alice", age=30))')

    def test_str_format_escaped(self, assert_compiles):
        assert_compiles('print("{{hello}}".format())')

    def test_format_spec_float(self, assert_compiles):
        assert_compiles('print("{:.2f}".format(3.14159))')

    def test_format_spec_int(self, assert_compiles):
        assert_compiles('print("{:5d}".format(42))')

    def test_format_spec_pad_left(self, assert_compiles):
        assert_compiles('print("{:<10}".format("hi"))')

    def test_format_spec_zero_pad(self, assert_compiles):
        assert_compiles('print("{:05d}".format(42))')

    def test_str_strip_chars(self, assert_compiles):
        assert_compiles('print("xxxabcxxx".strip("x"))')

    def test_str_rstrip(self, assert_compiles):
        assert_compiles('print("abc   ".rstrip())')

    def test_str_lstrip(self, assert_compiles):
        assert_compiles('print("   abc".lstrip())')

    def test_str_isdigit(self, assert_compiles):
        assert_compiles('print("123".isdigit())\nprint("12a".isdigit())')

    def test_str_isalpha(self, assert_compiles):
        assert_compiles('print("abc".isalpha())\nprint("abc1".isalpha())')

    def test_str_isalnum(self, assert_compiles):
        assert_compiles('print("abc123".isalnum())')

    def test_str_isspace(self, assert_compiles):
        assert_compiles('print("   ".isspace())')

    def test_chr_ord(self, assert_compiles):
        assert_compiles('print(chr(65))\nprint(ord("A"))')

    def test_hex(self, assert_compiles):
        assert_compiles("print(hex(255))")

    def test_oct(self, assert_compiles):
        assert_compiles("print(oct(8))")

    def test_bin(self, assert_compiles):
        assert_compiles("print(bin(5))")

    def test_round(self, assert_compiles):
        assert_compiles("print(round(3.7))\nprint(round(3.2))")

    def test_repr_str(self, assert_compiles):
        assert_compiles('print(repr("hi"))')

    def test_sum_with_start(self, assert_compiles):
        assert_compiles("print(sum([1, 2, 3], 10))")

    def test_dict_update(self, assert_compiles):
        assert_compiles('d = {"a": 1}\nd.update({"b": 2})\nprint(len(d))')

    def test_print_sep(self, assert_compiles):
        assert_compiles('print("a", "b", "c", sep="-")')

    def test_print_end(self, assert_compiles):
        assert_compiles('print("hi", end="!")\nprint("bye")')

    def test_str_rfind(self, assert_compiles):
        assert_compiles('print("hello".rfind("l"))')

    def test_str_capitalize(self, assert_compiles):
        assert_compiles('print("hello".capitalize())')

    def test_str_title(self, assert_compiles):
        assert_compiles('print("hello world".title())')

    def test_str_swapcase(self, assert_compiles):
        assert_compiles('print("HeLLo".swapcase())')

    def test_str_center(self, assert_compiles):
        assert_compiles('print("x".center(5) + "|")')

    def test_str_ljust(self, assert_compiles):
        assert_compiles('print("hi".ljust(5) + "|")')

    def test_str_rjust(self, assert_compiles):
        assert_compiles('print("hi".rjust(5) + "|")')

    def test_str_zfill(self, assert_compiles):
        assert_compiles('print("42".zfill(5))')

    def test_split_maxsplit(self, assert_compiles):
        assert_compiles('print("a,b,c,d".split(",", 2))')

    def test_percent_formatting(self, assert_compiles):
        assert_compiles('print("hello %s" % "world")\nprint("x = %d" % 5)')

    def test_percent_tuple(self, assert_compiles):
        assert_compiles('print("%s is %d" % ("Alice", 30))')

    def test_percent_float(self, assert_compiles):
        assert_compiles('print("%d" % 42)')


class TestControlFlow:
    """if/else, for, while, break, continue."""

    def test_if_true(self, assert_compiles):
        assert_compiles("x = 5\nif x > 3:\n    print('yes')")

    def test_if_else(self, assert_compiles):
        assert_compiles("x = 2\nif x > 3:\n    print('big')\nelse:\n    print('small')")

    def test_if_elif_else(self, assert_compiles):
        assert_compiles(
            "x = 5\n"
            "if x > 10:\n    print('big')\n"
            "elif x > 3:\n    print('medium')\n"
            "else:\n    print('small')"
        )

    def test_for_range(self, assert_compiles):
        assert_compiles("for i in range(5):\n    print(i)")

    def test_for_list(self, assert_compiles):
        assert_compiles("for x in [1, 2, 3]:\n    print(x)")

    def test_while_loop(self, assert_compiles):
        assert_compiles("x = 0\nwhile x < 5:\n    print(x)\n    x += 1")

    def test_break(self, assert_compiles):
        assert_compiles("for i in range(10):\n    if i == 3:\n        break\n    print(i)")

    def test_continue(self, assert_compiles):
        assert_compiles("for i in range(5):\n    if i == 2:\n        continue\n    print(i)")

    def test_nested_loops(self, assert_compiles):
        assert_compiles(
            "for i in range(3):\n"
            "    for j in range(3):\n"
            "        print(i * 3 + j)"
        )

    def test_for_else(self, assert_compiles):
        assert_compiles("for i in range(3):\n    pass\nelse:\n    print('done')")


class TestFunctions:
    """Function definition and calling."""

    def test_simple_function(self, assert_compiles):
        assert_compiles("def f(x):\n    return x + 1\nprint(f(5))")

    def test_multiple_args(self, assert_compiles):
        assert_compiles("def add(a, b):\n    return a + b\nprint(add(3, 4))")

    def test_starred_call(self, assert_compiles):
        assert_compiles("def f(a, b, c): return a+b+c\nargs=[1,2,3]\nprint(f(*args))")

    def test_string_concat_func(self, assert_compiles):
        assert_compiles('def greet(name): return "Hello, " + name + "!"\nprint(greet("World"))')

    def test_sum_generator(self, assert_compiles):
        assert_compiles("print(sum(x*x for x in range(5)))")

    def test_any_generator(self, assert_compiles):
        assert_compiles("print(any(x > 3 for x in range(5)))")

    def test_all_generator(self, assert_compiles):
        assert_compiles("print(all(x > 0 for x in [1, 2, 3]))")

    def test_try_finally_return(self, assert_compiles):
        assert_compiles(
            "def f():\n"
            "    try:\n        return 1\n"
            "    finally:\n        print('finally')\n"
            "print(f())"
        )

    def test_try_except_finally_return(self, assert_compiles):
        assert_compiles(
            "def f():\n"
            "    try:\n        raise ValueError('oops')\n"
            "    except ValueError:\n        return 2\n"
            "    finally:\n        print('finally')\n"
            "print(f())"
        )

    def test_nested_try_finally(self, assert_compiles):
        assert_compiles(
            "def f():\n"
            "    try:\n"
            "        try:\n            return 10\n"
            "        finally:\n            print('inner')\n"
            "    finally:\n        print('outer')\n"
            "print(f())"
        )

    def test_conditional_string_chain(self, assert_compiles):
        assert_compiles(
            "def rank(score):\n"
            "    return 'A' if score >= 90 else 'B' if score >= 80 else 'C'\n"
            "print(rank(95))\nprint(rank(85))\nprint(rank(75))"
        )

    def test_attr_tuple_unpack(self, assert_compiles):
        assert_compiles(
            "class Point:\n"
            "    def __init__(self, x, y):\n        self.x, self.y = x, y\n"
            "p = Point(1, 2)\n"
            "print(p.x, p.y)"
        )

    def test_nested_list_comprehension_cond(self, assert_compiles):
        assert_compiles(
            "matrix = [[i+j for j in range(3) if j > 0] for i in range(2)]\n"
            "for row in matrix:\n    print(row)"
        )

    def test_sorted_dict_items(self, assert_compiles):
        assert_compiles('d = {"b": 2, "a": 1}\nfor k, v in sorted(d.items()):\n    print(k, v)')

    def test_dict_with_list_values(self, assert_compiles):
        assert_compiles('data = {"items": [1, 2, 3]}\nprint(data["items"][2])')

    def test_dict_list_values_iter(self, assert_compiles):
        assert_compiles('data = {"items": [10, 20, 30]}\nfor x in data["items"]:\n    print(x)')

    def test_default_args(self, assert_compiles):
        assert_compiles("def f(x, y=10):\n    return x + y\nprint(f(5))\nprint(f(5, 20))")

    def test_recursive(self, assert_compiles):
        assert_compiles(
            "def fib(n):\n"
            "    if n <= 1:\n        return n\n"
            "    return fib(n-1) + fib(n-2)\n"
            "print(fib(10))"
        )

    def test_closure(self, assert_compiles):
        assert_compiles(
            "def make_adder(n):\n"
            "    def add(x):\n        return x + n\n"
            "    return add\n"
            "f = make_adder(10)\n"
            "print(f(5))"
        )

    def test_lambda(self, assert_compiles):
        assert_compiles("f = lambda x, y: x + y\nprint(f(3, 4))")

    def test_star_args(self, assert_compiles):
        assert_compiles(
            "def f(*args):\n    return sum(args)\n"
            "print(f(1, 2, 3))"
        )

    def test_kwargs(self, assert_compiles):
        assert_compiles(
            "def f(**kwargs):\n    return kwargs\n"
            "print(f(a=1, b=2))"
        )


class TestContainers:
    """Lists, dicts, tuples, sets."""

    def test_list_create(self, assert_compiles):
        assert_compiles("print([1, 2, 3])")

    def test_list_append(self, assert_compiles):
        assert_compiles("a = [1, 2]\na.append(3)\nprint(a)")

    def test_list_comprehension(self, assert_compiles):
        assert_compiles("print([x * x for x in range(5)])")

    def test_dict_create(self, assert_compiles):
        assert_compiles("print({'a': 1, 'b': 2})")

    def test_dict_access(self, assert_compiles):
        assert_compiles("d = {'a': 1, 'b': 2}\nprint(d['a'])")

    def test_dict_comprehension(self, assert_compiles):
        assert_compiles("print({x: x*x for x in range(4)})")

    def test_tuple_create(self, assert_compiles):
        assert_compiles("print((1, 2, 3))")

    def test_tuple_unpack(self, assert_compiles):
        assert_compiles("a, b, c = 1, 2, 3\nprint(a, b, c)")

    def test_set_create(self, assert_compiles):
        assert_compiles("print(sorted({3, 1, 2}))")

    def test_nested_containers(self, assert_compiles):
        assert_compiles("print([[i*j for j in range(3)] for i in range(3)])")

    def test_nested_list_subscript(self, assert_compiles):
        assert_compiles("a = [[1, 2, 3], [4, 5, 6]]\nprint(a[0][0])\nprint(a[1][2])")

    def test_nested_list_len(self, assert_compiles):
        assert_compiles("a = [[1, 2, 3], [4, 5, 6]]\nprint(len(a))\nprint(len(a[0]))")

    def test_nested_list_iteration(self, assert_compiles):
        assert_compiles("m = [[1, 2], [3, 4]]\nfor row in m:\n    print(row)")

    def test_nested_list_dynamic_build(self, assert_compiles):
        assert_compiles("""
result = []
for i in range(3):
    row = []
    for j in range(3):
        row.append(i * 3 + j)
    result.append(row)
print(result[0])
print(result[1])
print(result[2])
""")

    def test_matrix_multiply(self, assert_compiles):
        assert_compiles("""
def matrix_multiply(a, b):
    rows_a = len(a)
    cols_a = len(a[0])
    cols_b = len(b[0])
    result = []
    i = 0
    while i < rows_a:
        row = []
        j = 0
        while j < cols_b:
            total = 0
            k = 0
            while k < cols_a:
                total = total + a[i][k] * b[k][j]
                k = k + 1
            row.append(total)
            j = j + 1
        result.append(row)
        i = i + 1
    return result

a = [[1, 2], [3, 4]]
b = [[5, 6], [7, 8]]
c = matrix_multiply(a, b)
print(c[0][0])
print(c[0][1])
print(c[1][0])
print(c[1][1])
""")

    def test_list_repeat(self, assert_compiles):
        assert_compiles("print([0] * 5)")

    def test_list_repeat_multi(self, assert_compiles):
        assert_compiles("print([1, 2] * 3)")

    def test_int_times_list(self, assert_compiles):
        assert_compiles("print(3 * [1, 2])")

    def test_dict_get_default(self, assert_compiles):
        assert_compiles('d = {"a": 1}\nprint(d.get("b", 0))')

    def test_dict_get_found(self, assert_compiles):
        assert_compiles('d = {"a": 1}\nprint(d.get("a", 0))')

    def test_dict_iteration(self, assert_compiles):
        assert_compiles('d = {"a": 1, "b": 2}\nfor k in sorted(d):\n    print(k, d[k])')

    def test_range_list(self, assert_compiles):
        assert_compiles("print(list(range(5)))")

    def test_range_step(self, assert_compiles):
        assert_compiles("print(list(range(0, 10, 2)))")

    def test_range_negative_step(self, assert_compiles):
        assert_compiles("print(list(range(10, 0, -1)))")

    def test_for_range_neg_step(self, assert_compiles):
        assert_compiles("for i in range(5, 0, -1):\n    print(i)")

    def test_sorted_reverse(self, assert_compiles):
        assert_compiles("print(sorted([3, 1, 2], reverse=True))")

    def test_isinstance_int(self, assert_compiles):
        assert_compiles("print(isinstance(1, int))")

    def test_isinstance_str(self, assert_compiles):
        assert_compiles('print(isinstance("a", str))')

    def test_isinstance_list(self, assert_compiles):
        assert_compiles("print(isinstance([1], list))")

    def test_isinstance_negative(self, assert_compiles):
        assert_compiles("print(isinstance(1, str))")

    def test_augmented_list_concat(self, assert_compiles):
        assert_compiles("a = [1, 2]\na += [3, 4]\nprint(a)")

    def test_augmented_list_repeat(self, assert_compiles):
        assert_compiles("a = [1, 2]\na *= 3\nprint(a)")

    def test_augmented_str_concat(self, assert_compiles):
        assert_compiles('s = "ab"\ns += "cd"\nprint(s)')

    def test_tuple_unpack_from_list_iter(self, assert_compiles):
        assert_compiles("for t in [(1, 2), (3, 4)]:\n    a, b = t\n    print(a, b)")

    def test_tuple_direct_unpack_iter(self, assert_compiles):
        assert_compiles("for a, b in [(1, 2), (3, 4)]:\n    print(a + b)")

    def test_list_remove(self, assert_compiles):
        assert_compiles("a = [1, 2, 3]\na.remove(2)\nprint(a)")

    def test_list_insert(self, assert_compiles):
        assert_compiles("a = [1, 3]\na.insert(1, 2)\nprint(a)")

    def test_dict_pop(self, assert_compiles):
        assert_compiles('d = {"a": 1, "b": 2}\nprint(d.pop("a"))\nprint(len(d))')

    def test_dict_setdefault(self, assert_compiles):
        assert_compiles('d = {}\nd.setdefault("a", 5)\nprint(d["a"])')

    def test_dict_constructor(self, assert_compiles):
        assert_compiles('d = dict([("a", 1), ("b", 2)])\nprint(d["a"])')

    def test_divmod(self, assert_compiles):
        assert_compiles("print(divmod(17, 5))")

    def test_empty_list(self, assert_compiles):
        assert_compiles("print(list())")

    def test_empty_dict(self, assert_compiles):
        assert_compiles("print(dict())")

    def test_list_equality(self, assert_compiles):
        assert_compiles("print([1, 2, 3] == [1, 2, 3])\nprint([1, 2] != [1, 3])")

    def test_nested_list_equality(self, assert_compiles):
        assert_compiles("print([[1, 2], [3, 4]] == [[1, 2], [3, 4]])\nprint([[1, 2]] == [[1, 2, 3]])")

    def test_nested_tuple_equality(self, assert_compiles):
        assert_compiles("print([(1, 2), (3, 4)] == [(1, 2), (3, 4)])")

    def test_bool_empty_list(self, assert_compiles):
        assert_compiles("print(bool([]))\nprint(bool([1]))")

    def test_bool_empty_str(self, assert_compiles):
        assert_compiles('print(bool(""))\nprint(bool("a"))')

    def test_bool_empty_dict(self, assert_compiles):
        assert_compiles('print(bool({}))\nprint(bool({"a": 1}))')

    def test_if_empty_list(self, assert_compiles):
        assert_compiles('a = []\nif a:\n    print("t")\nelse:\n    print("f")')

    def test_list_of_dicts_iter(self, assert_compiles):
        assert_compiles('people = [{"name": "a"}, {"name": "b"}]\nfor p in people:\n    print(p["name"])')

    def test_type_builtin(self, assert_compiles):
        assert_compiles('print(type(1))\nprint(type("a"))\nprint(type([1]))')

    def test_del_list(self, assert_compiles):
        assert_compiles("a = [1, 2, 3]\ndel a[1]\nprint(a)")

    def test_del_dict(self, assert_compiles):
        assert_compiles('d = {"a": 1, "b": 2}\ndel d["a"]\nprint(len(d))')

    def test_del_list_neg_idx(self, assert_compiles):
        assert_compiles("a = [1, 2, 3]\ndel a[-1]\nprint(a)")

    def test_list_in_str_elems(self, assert_compiles):
        assert_compiles('print("b" in ["a", "b", "c"])\nprint("z" in ["a", "b", "c"])')

    def test_min_max_strings(self, assert_compiles):
        assert_compiles('print(min(["apple", "banana", "cherry"]))\nprint(max(["apple", "banana", "cherry"]))')

    def test_sorted_with_key(self, assert_compiles):
        assert_compiles("def neg(x): return -x\nprint(sorted([1, 2, 3], key=neg))")

    def test_sorted_with_key_reverse(self, assert_compiles):
        assert_compiles("def neg(x): return -x\nprint(sorted([1, 2, 3], key=neg, reverse=True))")

    def test_map_named_func(self, assert_compiles):
        assert_compiles("def dbl(x): return x * 2\nprint(list(map(dbl, [1, 2, 3])))")

    def test_filter_named_func(self, assert_compiles):
        assert_compiles("def pos(x): return x > 0\nprint(list(filter(pos, [-1, 2, -3, 4])))")

    def test_inline_lambda_sorted(self, assert_compiles):
        assert_compiles("print(sorted([3, 1, 2], key=lambda x: -x))")

    def test_inline_lambda_filter(self, assert_compiles):
        assert_compiles("print(list(filter(lambda x: x > 2, [1, 2, 3, 4])))")

    def test_inline_lambda_map(self, assert_compiles):
        assert_compiles("print(list(map(lambda x: x * 2, [1, 2, 3])))")

    def test_enumerate_print(self, assert_compiles):
        assert_compiles('print(list(enumerate(["a", "b", "c"])))')

    def test_zip_print(self, assert_compiles):
        assert_compiles("print(list(zip([1, 2], [3, 4])))")

    def test_tuple_in_list_print(self, assert_compiles):
        assert_compiles("print([(1, 2), (3, 4)])")

    def test_sorted_tuples_print(self, assert_compiles):
        assert_compiles('print(sorted([(2, "b"), (1, "a")]))')

    def test_single_element_tuple(self, assert_compiles):
        assert_compiles("print((1,))")

    def test_fstring_repr(self, assert_compiles):
        assert_compiles('x = "hi"\nprint(f"{x!r}")')


class TestClasses:
    """Class definitions and usage."""

    def test_simple_class(self, assert_compiles):
        assert_compiles(
            "class Point:\n"
            "    def __init__(self, x, y):\n"
            "        self.x = x\n"
            "        self.y = y\n"
            "p = Point(3, 4)\n"
            "print(p.x, p.y)"
        )

    def test_method(self, assert_compiles):
        assert_compiles(
            "class Counter:\n"
            "    def __init__(self):\n"
            "        self.n = 0\n"
            "    def inc(self):\n"
            "        self.n += 1\n"
            "c = Counter()\n"
            "c.inc()\nc.inc()\n"
            "print(c.n)"
        )

    def test_inheritance(self, assert_compiles):
        assert_compiles(
            "class Animal:\n"
            "    def speak(self):\n        return 'unknown'\n"
            "class Dog(Animal):\n"
            "    def speak(self):\n        return 'woof'\n"
            "print(Dog().speak())"
        )

    def test_str_repr(self, assert_compiles):
        assert_compiles(
            "class Num:\n"
            "    def __init__(self, v):\n        self.v = v\n"
            "    def __str__(self):\n        return f'Num({self.v})'\n"
            "print(Num(42))"
        )

    def test_super_init(self, assert_compiles):
        assert_compiles(
            "class A:\n"
            "    def __init__(self):\n        self.x = 1\n"
            "class B(A):\n"
            "    def __init__(self):\n"
            "        super().__init__()\n"
            "        self.y = 2\n"
            "b = B()\n"
            "print(b.x, b.y)"
        )

    def test_super_method(self, assert_compiles):
        assert_compiles(
            "class A:\n"
            "    def greet(self):\n        return 'A'\n"
            "class B(A):\n"
            "    def greet(self):\n        return super().greet() + 'B'\n"
            "print(B().greet())"
        )

    def test_init_with_default(self, assert_compiles):
        assert_compiles(
            "class A:\n"
            "    def __init__(self, x=10):\n        self.x = x\n"
            "print(A().x)\nprint(A(20).x)"
        )

    def test_method_returns_list(self, assert_compiles):
        assert_compiles(
            "class A:\n"
            "    def get_list(self):\n        return [1, 2, 3]\n"
            "a = A()\n"
            "lst = a.get_list()\n"
            "print(len(lst))\nprint(lst[0])"
        )

    def test_class_level_constant(self, assert_compiles):
        assert_compiles(
            "class Config:\n"
            "    MAX = 100\n"
            "print(Config.MAX)"
        )

    def test_class_level_multiple_consts(self, assert_compiles):
        assert_compiles(
            "class Config:\n"
            "    X = 1\n"
            "    NAME = \"cfg\"\n"
            "print(Config.X)\nprint(Config.NAME)"
        )

    def test_method_returns_tuple(self, assert_compiles):
        assert_compiles(
            "class Point:\n"
            "    def __init__(self, x, y):\n        self.x = x\n        self.y = y\n"
            "    def as_tuple(self):\n        return self.x, self.y\n"
            "p = Point(3, 4)\n"
            "print(p.as_tuple())"
        )

    def test_method_returns_dict(self, assert_compiles):
        assert_compiles(
            "class A:\n"
            "    def get_data(self):\n        return {\"x\": 1, \"y\": 2}\n"
            "a = A()\n"
            "d = a.get_data()\n"
            "print(d[\"x\"])"
        )

    def test_classmethod_basic(self, assert_compiles):
        assert_compiles(
            "class A:\n"
            "    @classmethod\n    def name(cls):\n        return 'A'\n"
            "print(A.name())"
        )

    def test_classmethod_factory(self, assert_compiles):
        assert_compiles(
            "class A:\n"
            "    def __init__(self, n):\n        self.n = n\n"
            "    @classmethod\n    def from_int(cls, n):\n        return cls(n)\n"
            "print(A.from_int(42).n)"
        )

    def test_fluent_chain(self, assert_compiles):
        assert_compiles(
            "class F:\n"
            "    def __init__(self):\n        self.v = 0\n"
            "    def add(self, n):\n        self.v = self.v + n\n        return self\n"
            "print(F().add(5).add(10).add(20).v)"
        )


class TestExceptions:
    """try/except/finally."""

    def test_try_except(self, assert_compiles):
        assert_compiles(
            "try:\n    x = 1/0\n"
            "except ZeroDivisionError:\n    print('caught')"
        )

    def test_try_finally(self, assert_compiles):
        assert_compiles(
            "try:\n    print('try')\n"
            "finally:\n    print('finally')"
        )

    def test_raise(self, assert_compiles):
        assert_compiles(
            "try:\n    raise ValueError('oops')\n"
            "except ValueError as e:\n    print(e)"
        )


class TestVariables:
    """Variable assignment and usage."""

    def test_simple_assign(self, assert_compiles):
        assert_compiles("x = 42\nprint(x)")

    def test_multiple_vars(self, assert_compiles):
        assert_compiles("x = 5\ny = 10\nprint(x + y)")

    def test_reassign(self, assert_compiles):
        assert_compiles("x = 1\nx = 2\nprint(x)")

    def test_assign_from_expr(self, assert_compiles):
        assert_compiles("x = 3 * 4 + 1\nprint(x)")

    def test_augmented_assign(self, assert_compiles):
        assert_compiles("x = 10\nx += 5\nprint(x)")

    def test_augmented_sub(self, assert_compiles):
        assert_compiles("x = 10\nx -= 3\nprint(x)")

    def test_augmented_mul(self, assert_compiles):
        assert_compiles("x = 5\nx *= 4\nprint(x)")

    def test_chain_assignments(self, assert_compiles):
        assert_compiles("x = 1\ny = x + 1\nz = y + 1\nprint(z)")

    def test_float_var(self, assert_compiles):
        assert_compiles("x = 3.14\nprint(x)")

    def test_mixed_arithmetic_vars(self, assert_compiles):
        assert_compiles("x = 10\ny = 3.0\nprint(x + y)")

    def test_multi_statement_program(self, assert_compiles):
        assert_compiles(
            "a = 100\n"
            "b = 200\n"
            "c = a + b\n"
            "d = c * 2\n"
            "print(d)"
        )

    def test_negative_variable(self, assert_compiles):
        assert_compiles("x = 5\nprint(-x)")

    def test_multiple_prints(self, assert_compiles):
        assert_compiles("x = 1\nprint(x)\nx = 2\nprint(x)\nx = 3\nprint(x)")


class TestMisc:
    """Miscellaneous language features."""

    def test_none(self, assert_compiles):
        assert_compiles("print(None)")

    def test_bool_ops(self, assert_compiles):
        assert_compiles("print(True and False)\nprint(True or False)\nprint(not True)")

    def test_and_returns_operand(self, assert_compiles):
        assert_compiles("print(True and 5)\nprint(5 and 10)")

    def test_or_returns_operand(self, assert_compiles):
        assert_compiles("print(0 or 5)\nprint(5 or 10)")

    def test_or_with_strings(self, assert_compiles):
        assert_compiles('print("" or "hi")\nprint("a" or "b")')

    def test_or_default_value(self, assert_compiles):
        assert_compiles("x = 0\nprint(x or 100)")

    def test_chained_or(self, assert_compiles):
        assert_compiles("print(0 or 0 or 5)")

    def test_comparison_chain(self, assert_compiles):
        assert_compiles("print(1 < 2 < 3)\nprint(1 < 2 > 3)")

    def test_in_operator(self, assert_compiles):
        assert_compiles("print(2 in [1, 2, 3])\nprint(4 in [1, 2, 3])")

    def test_is_operator(self, assert_compiles):
        assert_compiles("print(None is None)\nprint(None is not None)")

    def test_var_is_none(self, assert_compiles):
        assert_compiles('x = None\nif x is None:\n    print("is none")')

    def test_var_is_not_none(self, assert_compiles):
        assert_compiles('x = 5\nif x is not None:\n    print("not none")')

    def test_assert_passing(self, assert_compiles):
        assert_compiles('assert 1 == 1\nprint("pass")')

    def test_assert_in_try(self, assert_compiles):
        assert_compiles('try:\n    assert False\nexcept:\n    print("caught")')

    def test_walrus(self, assert_compiles):
        assert_compiles(
            "nums = [1, 2, 3, 4, 5]\n"
            "big = [y for x in nums if (y := x * 2) > 5]\n"
            "print(big)"
        )

    def test_multiline_program(self, assert_compiles):
        assert_compiles(
            "def factorial(n):\n"
            "    result = 1\n"
            "    for i in range(2, n + 1):\n"
            "        result *= i\n"
            "    return result\n"
            "\n"
            "for n in range(10):\n"
            "    print(f'{n}! = {factorial(n)}')"
        )


    def test_min_inline(self, assert_compiles):
        assert_compiles("print(min(3, 1, 2))\nprint(min(5, 2))")

    def test_max_inline(self, assert_compiles):
        assert_compiles("print(max(3, 1, 2))\nprint(max(5, 2))")


class TestAdvanced:
    """Advanced features: closures, operator overloading, higher-order functions."""

    def test_closure_read_only(self, assert_compiles):
        assert_compiles(
            "def make_adder(n):\n"
            "    def add(x):\n        return x + n\n"
            "    return add\n"
            "f = make_adder(10)\n"
            "print(f(5))\nprint(f(100))"
        )

    def test_closure_mutable(self, assert_compiles):
        assert_compiles(
            "def counter(start=0):\n"
            "    count = start\n"
            "    def inc():\n"
            "        nonlocal count\n"
            "        count += 1\n"
            "        return count\n"
            "    return inc\n"
            "c = counter(10)\n"
            "print(c())\nprint(c())\nprint(c())"
        )

    def test_higher_order(self, assert_compiles):
        assert_compiles(
            "def apply(f, x):\n    return f(f(x))\n"
            "print(apply(lambda x: x * 2, 3))"
        )

    def test_operator_overload(self, assert_compiles):
        assert_compiles(
            "class Vec:\n"
            "    def __init__(self, x, y):\n"
            "        self.x = x\n        self.y = y\n"
            "    def __add__(self, other):\n"
            "        return Vec(self.x + other.x, self.y + other.y)\n"
            "    def __repr__(self):\n"
            "        return f'Vec({self.x}, {self.y})'\n"
            "v = Vec(1, 2) + Vec(3, 4)\nprint(v)"
        )

    def test_static_method(self, assert_compiles):
        assert_compiles(
            "class Math:\n"
            "    @staticmethod\n"
            "    def add(a, b):\n        return a + b\n"
            "print(Math.add(3, 4))"
        )

    def test_isinstance_inheritance(self, assert_compiles):
        assert_compiles(
            "class A:\n    pass\n"
            "class B(A):\n    pass\n"
            "b = B()\n"
            "print(isinstance(b, B))\nprint(isinstance(b, A))"
        )

    def test_bigint_pow(self, assert_compiles):
        assert_compiles("print(2 ** 100)")

    def test_bigint_add(self, assert_compiles):
        assert_compiles("print(10 ** 20 + 1)")

    def test_set_operations(self, assert_compiles):
        assert_compiles(
            "a = {1, 2, 3}\nb = {2, 3, 4}\n"
            "print(sorted(a | b))\n"
            "print(sorted(a & b))\n"
            "print(sorted(a - b))"
        )

    def test_dict_iteration(self, assert_compiles):
        assert_compiles(
            "d = {'x': 10, 'y': 20}\n"
            "for key in sorted(d.keys()):\n"
            "    print(f'{key}: {d[key]}')"
        )

    def test_ne_auto_derive(self, assert_compiles):
        """__ne__ auto-derived from __eq__."""
        assert_compiles(
            "class Pt:\n"
            "    def __init__(self, x):\n        self.x = x\n"
            "    def __eq__(self, other):\n        return self.x == other.x\n"
            "a, b, c = Pt(1), Pt(1), Pt(2)\n"
            "print(a == b)\nprint(a != b)\nprint(a != c)"
        )

    def test_neg_dunder(self, assert_compiles):
        """__neg__ on user objects."""
        assert_compiles(
            "class N:\n"
            "    def __init__(self, v):\n        self.v = v\n"
            "    def __neg__(self):\n        return N(-self.v)\n"
            "    def __repr__(self):\n        return f'N({self.v})'\n"
            "x = N(5)\ny = -x\nprint(repr(y))"
        )

    def test_getitem_int(self, assert_compiles):
        """__getitem__ returning int."""
        assert_compiles(
            "class M:\n"
            "    def __init__(self):\n        self.data = [10, 20, 30]\n"
            "    def __getitem__(self, i):\n        return self.data[i]\n"
            "m = M()\nprint(m[1])"
        )

    def test_getitem_list(self, assert_compiles):
        """__getitem__ returning sublist from list-of-lists."""
        assert_compiles(
            "class M:\n"
            "    def __init__(self):\n"
            "        self.data = [[1, 2, 3], [4, 5, 6]]\n"
            "    def __getitem__(self, i):\n        return self.data[i]\n"
            "m = M()\nprint(m[0])\nprint(m[1])"
        )

    def test_getitem_str(self, assert_compiles):
        """__getitem__ returning string."""
        assert_compiles(
            "class Named:\n"
            "    def __init__(self, name):\n        self.name = name\n"
            "    def __getitem__(self, i):\n        return self.name\n"
            "n = Named('hello')\nprint(n[0])"
        )

    def test_setitem_getitem_contains(self, assert_compiles):
        """__setitem__, __getitem__, __contains__ on user class."""
        assert_compiles(
            "class D:\n"
            "    def __init__(self):\n        self.store = {}\n"
            "    def __setitem__(self, k, v):\n        self.store[k] = v\n"
            "    def __getitem__(self, k):\n        return self.store[k]\n"
            "    def __contains__(self, k):\n        return k in self.store\n"
            "d = D()\nd['a'] = 1\nd['b'] = 2\n"
            "print(d['a'])\nprint(d['b'])\n"
            "print('a' in d)\nprint('c' in d)"
        )

    def test_starred_unpack(self, assert_compiles):
        assert_compiles(
            "first, *rest = [10, 20, 30, 40]\n"
            "print(first)\nprint(rest)"
        )

    def test_enumerate_zip(self, assert_compiles):
        assert_compiles(
            "names = ['a', 'b', 'c']\n"
            "for i, (n,) in enumerate([[x] for x in names]):\n"
            "    print(f'{i}: {n}')"
        )

    def test_try_raise_custom(self, assert_compiles):
        assert_compiles(
            "def safe_div(a, b):\n"
            "    if b == 0:\n"
            "        raise ValueError('division by zero')\n"
            "    return a // b\n"
            "try:\n    result = safe_div(10, 0)\n    print(result)\n"
            "except ValueError as e:\n    print(e)"
        )

    def test_nested_comprehension(self, assert_compiles):
        assert_compiles(
            "print([[i*j for j in range(3)] for i in range(3)])"
        )

    def test_multiple_return(self, assert_compiles):
        assert_compiles(
            "def divmod2(a, b):\n    return a // b, a % b\n"
            "q, r = divmod2(17, 5)\nprint(q, r)"
        )

    def test_global_variable(self, assert_compiles):
        assert_compiles(
            "count = 0\n"
            "def inc():\n"
            "    global count\n"
            "    count += 1\n"
            "    return count\n"
            "print(inc(), inc(), inc())"
        )

    def test_string_iteration(self, assert_compiles):
        assert_compiles(
            "vowels = 0\n"
            "for ch in 'hello':\n"
            "    if ch == 'e' or ch == 'o':\n"
            "        vowels += 1\n"
            "print(vowels)"
        )

    def test_string_comparison(self, assert_compiles):
        assert_compiles(
            "print('abc' == 'abc')\n"
            "print('abc' == 'def')\n"
            "print('x' != 'y')"
        )

    def test_ternary_string(self, assert_compiles):
        assert_compiles(
            "x = 5\nprint('big' if x > 3 else 'small')"
        )

    def test_negative_index(self, assert_compiles):
        assert_compiles(
            "lst = [10, 20, 30, 40, 50]\nprint(lst[-1])\nprint(lst[-2])"
        )

    def test_list_return_from_func(self, assert_compiles):
        assert_compiles(
            "def make_list(n):\n"
            "    result = []\n"
            "    for i in range(n):\n"
            "        result.append(i * i)\n"
            "    return result\n"
            "print(make_list(5))"
        )

    def test_float_return_from_func(self, assert_compiles):
        assert_compiles(
            "def average(a, b):\n"
            "    total = a + b\n"
            "    result = total / 2.0\n"
            "    return result\n"
            "print(average(3, 7))"
        )

    def test_list_concat(self, assert_compiles):
        assert_compiles("print([1, 2] + [3, 4])")

    def test_global_increment(self, assert_compiles):
        assert_compiles(
            "x = 10\n"
            "def add(n):\n"
            "    global x\n"
            "    x += n\n"
            "add(5)\nadd(3)\nprint(x)"
        )

    def test_string_iter_count(self, assert_compiles):
        assert_compiles(
            "count = 0\n"
            "for c in 'abcabc':\n"
            "    if c == 'a':\n"
            "        count += 1\n"
            "print(count)"
        )

    def test_str_upper(self, assert_compiles):
        assert_compiles("print('hello'.upper())")

    def test_str_strip(self, assert_compiles):
        assert_compiles("print('  hello  '.strip())")

    def test_str_replace(self, assert_compiles):
        assert_compiles("print('hello world'.replace('world', 'python'))")

    def test_str_startswith(self, assert_compiles):
        assert_compiles("print('hello'.startswith('hel'))")

    def test_str_endswith(self, assert_compiles):
        assert_compiles("print('hello'.endswith('llo'))")

    def test_str_in(self, assert_compiles):
        assert_compiles("print('lo' in 'hello')\nprint('xyz' in 'hello')")

    def test_list_pop(self, assert_compiles):
        assert_compiles("lst = [1, 2, 3]\nprint(lst.pop())\nprint(lst)")

    def test_list_index(self, assert_compiles):
        assert_compiles("print([10, 20, 30].index(20))")

    def test_list_count(self, assert_compiles):
        assert_compiles("print([1, 2, 1, 3, 1].count(1))")

    def test_dict_get(self, assert_compiles):
        assert_compiles(
            "d = {'a': 1, 'b': 2}\n"
            "print(d.get('a', 'none'))\n"
            "print(d.get('c', 'none'))"
        )

    def test_dict_in(self, assert_compiles):
        assert_compiles(
            "d = {'a': 1, 'b': 2}\n"
            "print('a' in d)\nprint('c' in d)"
        )

    def test_dict_len(self, assert_compiles):
        assert_compiles("print(len({'a': 1, 'b': 2, 'c': 3}))")

    def test_any_all(self, assert_compiles):
        assert_compiles(
            "print(any([0, 0, 1]))\nprint(any([0, 0, 0]))\n"
            "print(all([1, 1, 1]))\nprint(all([1, 0, 1]))"
        )

    def test_list_subscript_assign(self, assert_compiles):
        assert_compiles("lst = [1, 2, 3]\nlst[1] = 99\nprint(lst)")

    def test_dict_subscript_assign(self, assert_compiles):
        assert_compiles("d = {'a': 1}\nd['b'] = 2\nprint(d)")

    def test_list_sort_inplace(self, assert_compiles):
        assert_compiles("lst = [3, 1, 2]\nlst.sort()\nprint(lst)")

    def test_list_reverse_inplace(self, assert_compiles):
        assert_compiles("lst = [1, 2, 3]\nlst.reverse()\nprint(lst)")

    def test_list_extend(self, assert_compiles):
        assert_compiles("a = [1, 2]\na.extend([3, 4])\nprint(a)")

    def test_str_find(self, assert_compiles):
        assert_compiles("print('hello world'.find('world'))\nprint('hello'.find('xyz'))")

    def test_str_count(self, assert_compiles):
        assert_compiles("print('abcabc'.count('abc'))")

    def test_bool_builtin(self, assert_compiles):
        assert_compiles("print(bool(0))\nprint(bool(1))")

    def test_float_builtin(self, assert_compiles):
        assert_compiles("print(float(42))")

    def test_true_division_return(self, assert_compiles):
        assert_compiles(
            "def half(n):\n    return n / 2\nprint(half(10))"
        )

    def test_list_sort_inplace(self, assert_compiles):
        assert_compiles("lst = [3, 1, 2]\nlst.sort()\nprint(lst)")

    def test_list_reverse_inplace(self, assert_compiles):
        assert_compiles("lst = [1, 2, 3]\nlst.reverse()\nprint(lst)")

    def test_list_extend(self, assert_compiles):
        assert_compiles("a = [1, 2]\na.extend([3, 4])\nprint(a)")

    def test_str_find(self, assert_compiles):
        assert_compiles("print('hello world'.find('world'))\nprint('hello'.find('xyz'))")

    def test_str_count_method(self, assert_compiles):
        assert_compiles("print('abcabc'.count('abc'))")

    def test_collatz(self, assert_compiles):
        assert_compiles(
            "n = 6\nseq = [n]\n"
            "while n != 1:\n"
            "    if n % 2 == 0:\n        n = n // 2\n"
            "    else:\n        n = 3 * n + 1\n"
            "    seq.append(n)\n"
            "print(seq)"
        )

    def test_fast_power(self, assert_compiles):
        assert_compiles(
            "def power(b, e):\n"
            "    r = 1\n"
            "    while e > 0:\n"
            "        if e % 2 == 1:\n            r *= b\n"
            "        b *= b\n        e = e // 2\n"
            "    return r\n"
            "print(power(2, 10))"
        )

    # --- Bug #133: type(obj).__name__ for user-class objects ---
    def test_type_name_user_class(self, assert_compiles):
        assert_compiles(
            "class Foo:\n    pass\n"
            "x = Foo()\nprint(type(x).__name__)"
        )

    def test_type_repr_user_class(self, assert_compiles):
        assert_compiles(
            "class Cat:\n    def __init__(self, n):\n        self.n = n\n"
            "c = Cat('mimi')\nprint(type(c))"
        )

    # --- Bug #134: starred targets in for-loop ---
    def test_for_star_unpack(self, assert_compiles):
        assert_compiles(
            "for a, *b in [[1, 2, 3], [4, 5, 6]]:\n    print(a, b)"
        )

    def test_for_star_unpack_prefix(self, assert_compiles):
        assert_compiles(
            "for *init, last in [[1,2,3],[4,5]]:\n    print(init, last)"
        )

    # --- Bug #135: enumerate on strings ---
    def test_enumerate_string(self, assert_compiles):
        assert_compiles(
            "for i, c in enumerate('abc'):\n    print(i, c)"
        )

    def test_enumerate_string_start(self, assert_compiles):
        assert_compiles(
            "for i, c in enumerate('xy', start=10):\n    print(i, c)"
        )

    # --- Bug #136: list.sort(key=func) ---
    def test_sort_key_len(self, assert_compiles):
        assert_compiles(
            "a = ['cc', 'a', 'bbb']\na.sort(key=len)\nprint(a)"
        )

    def test_sort_key_abs(self, assert_compiles):
        assert_compiles(
            "a = [3, -1, 2, -5]\na.sort(key=abs)\nprint(a)"
        )

    def test_sort_key_lambda(self, assert_compiles):
        assert_compiles(
            "a = ['bbb', 'a', 'cc']\n"
            "a.sort(key=lambda s: len(s))\nprint(a)"
        )

    def test_sort_key_reverse(self, assert_compiles):
        assert_compiles(
            "a = ['banana', 'apple', 'cherry']\n"
            "a.sort(key=len, reverse=True)\nprint(a)"
        )

    # --- Bug #137: print(sep=variable) ---
    def test_print_sep_variable(self, assert_compiles):
        assert_compiles(
            "sep_char = ', '\nprint(1, 2, 3, sep=sep_char)"
        )

    def test_print_end_variable(self, assert_compiles):
        assert_compiles(
            "s = '!'\nprint('hello', end=s)\nprint(' world')"
        )

    # --- Bug #138: triple+ nested comprehensions ---
    def test_triple_comprehension(self, assert_compiles):
        assert_compiles(
            "result = [x + y + z for x in range(2) for y in range(2) for z in range(2)]\n"
            "print(result)"
        )

    def test_quad_comprehension(self, assert_compiles):
        assert_compiles(
            "r = [a+b+c+d for a in range(2) for b in range(2) "
            "for c in range(2) for d in range(2)]\nprint(r)"
        )

    # --- Bug #139: with/as when __enter__ returns non-self ---
    def test_with_as_int(self, assert_compiles):
        assert_compiles(
            "class CM:\n"
            "    def __enter__(self):\n        return 42\n"
            "    def __exit__(self, *a):\n        print('exit')\n"
            "with CM() as v:\n    print(v)"
        )

    # --- Bug #140: mixed float/int return types ---
    def test_mixed_float_int_return(self, assert_compiles):
        assert_compiles(
            "def f(x):\n"
            "    try:\n        return 1/x\n"
            "    except ZeroDivisionError:\n        return -1\n"
            "print(f(0))\nprint(f(2))"
        )

    # --- Bug #141: tuple methods and operations ---
    def test_tuple_count(self, assert_compiles):
        assert_compiles("t = (1, 2, 3, 2, 1)\nprint(t.count(2))")

    def test_tuple_index(self, assert_compiles):
        assert_compiles("t = (1, 2, 3)\nprint(t.index(2))")

    def test_tuple_concat(self, assert_compiles):
        assert_compiles("print((1, 2) + (3, 4))")

    def test_tuple_repeat(self, assert_compiles):
        assert_compiles("print((1, 2) * 3)")

    # --- Bug #142: sorted() with __lt__ on user classes ---
    def test_sorted_with_lt(self, assert_compiles):
        assert_compiles(
            "class N:\n"
            "    def __init__(self, v):\n        self.v = v\n"
            "    def __lt__(self, o):\n        return self.v < o.v\n"
            "    def __repr__(self):\n        return f'N({self.v})'\n"
            "a = [N(5), N(2), N(8), N(1)]\nprint(sorted(a))"
        )

    def test_min_max_obj_lt(self, assert_compiles):
        """Bug #143: min/max on list of objects with __lt__."""
        assert_compiles(
            "class N:\n"
            "    def __init__(self, v):\n        self.v = v\n"
            "    def __lt__(self, o):\n        return self.v < o.v\n"
            "    def __repr__(self):\n"
            "        return 'N(' + str(self.v) + ')'\n"
            "items = [N(5), N(2), N(8), N(1), N(3)]\n"
            "print(repr(min(items)))\n"
            "print(repr(max(items)))\n"
            "x = min(items)\nprint(x.v)\n"
            "y = max(items)\nprint(y.v)"
        )

    # --- Bug #144: dict comp tuple-unpack key type dispatch ---
    def test_dict_comp_enumerate_key(self, assert_compiles):
        """Bug #144: dict comp with enumerate uses int keys → dict_set_int_fv."""
        assert_compiles(
            "items = ['a', 'b', 'c']\n"
            "d = {i: v for i, v in enumerate(items)}\n"
            "print(d)"
        )

    # --- Bug #145: dict comp over string iteration ---
    def test_dict_comp_string_iter(self, assert_compiles):
        """Bug #145: dict comp iterating over string characters."""
        assert_compiles(
            "d = {c: i for i, c in enumerate('hello')}\n"
            "print(d)"
        )

    # --- Bug #146: diamond MRO resolution ---
    def test_diamond_mro(self, assert_compiles):
        """Bug #146: diamond inheritance — D(B,C) with C overriding A.greet."""
        assert_compiles(
            "class A:\n"
            "    def greet(self):\n        return 'A'\n"
            "class B(A):\n    pass\n"
            "class C(A):\n"
            "    def greet(self):\n        return 'C'\n"
            "class D(B, C):\n    pass\n"
            "d = D()\nprint(d.greet())"
        )

    def test_diamond_mro_deeper(self, assert_compiles):
        """Diamond MRO with method defined at intermediate level."""
        assert_compiles(
            "class A:\n"
            "    def who(self):\n        return 'A'\n"
            "class B(A):\n"
            "    def who(self):\n        return 'B'\n"
            "class C(A):\n"
            "    def who(self):\n        return 'C'\n"
            "class D(B, C):\n    pass\n"
            "print(D().who())"
        )

    # --- Bug #147: closure with *args crashed or returned 0 ---
    def test_closure_varargs_return(self, assert_compiles):
        """Bug #147: closure with *args returning args[0] or len(args)."""
        assert_compiles(
            "def make():\n"
            "    def inner(*args):\n"
            "        return len(args)\n"
            "    return inner\n"
            "f = make()\nprint(f(1, 2, 3))"
        )

    def test_closure_varargs_capture(self, assert_compiles):
        """Closure with *args and captured variable."""
        assert_compiles(
            "def make_adder(n):\n"
            "    def adder(*args):\n"
            "        return n + sum(args)\n"
            "    return adder\n"
            "f = make_adder(10)\nprint(f(1, 2, 3))"
        )

    def test_closure_varargs_subscript(self, assert_compiles):
        """Closure with *args accessing args[0]."""
        assert_compiles(
            "def make():\n"
            "    def inner(*args):\n"
            "        return args[0]\n"
            "    return inner\n"
            "f = make()\nprint(f(42))"
        )

    # --- Bug #148: list(obj) with __iter__/__next__ ---
    def test_list_from_iterator(self, assert_compiles):
        """Bug #148: list(obj) on objects implementing __iter__/__next__."""
        assert_compiles(
            "class R:\n"
            "    def __init__(self, n):\n"
            "        self.n = n\n"
            "    def __iter__(self):\n"
            "        self.i = 0\n"
            "        return self\n"
            "    def __next__(self):\n"
            "        if self.i >= self.n:\n"
            "            raise StopIteration\n"
            "        self.i = self.i + 1\n"
            "        return self.i\n"
            "print(list(R(5)))"
        )
