# Regression: dict.setdefault() and dict.pop() with integer keys
# Previously crashed (ACCESS_VIOLATION) because runtime functions
# only accepted const char* keys.

# setdefault with int key
d = {}
d.setdefault(5, 'default')
print(d)

# setdefault with int key and list default
d2 = {}
d2.setdefault(5, []).append('hello')
d2.setdefault(5, []).append('world')
d2.setdefault(2, []).append('hi')
print(sorted(d2.items()))

# pop with int key
d3 = {1: 'a', 2: 'b', 3: 'c'}
val = d3.pop(2)
print(val)
print(d3)

# pop with int key and default
d4 = {1: 'hello'}
val2 = d4.pop(2, 'missing')
print(val2)
val3 = d4.pop(1, 'missing')
print(val3)

# groupby pattern with int keys
words = ['hello', 'world', 'hi', 'hey']
by_len = {}
for w in words:
    by_len.setdefault(len(w), []).append(w)
for k in sorted(by_len):
    print(k, by_len[k])
