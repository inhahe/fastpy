# Test str.removeprefix, str.removesuffix, str.partition, str.rpartition

s = "hello world"

# removeprefix
print(s.removeprefix("hello "))   # world
print(s.removeprefix("world"))    # hello world (no match)
print(s.removeprefix(""))         # hello world

# removesuffix
print(s.removesuffix(" world"))   # hello
print(s.removesuffix("hello"))    # hello world (no match)
print(s.removesuffix(""))         # hello world

# partition
print(s.partition(" "))           # ('hello', ' ', 'world')
print(s.partition("xyz"))         # ('hello world', '', '')
print(s.partition("o"))           # ('hell', 'o', ' world')

# rpartition
print(s.rpartition(" "))          # ('hello', ' ', 'world')
print(s.rpartition("xyz"))        # ('', '', 'hello world')
print(s.rpartition("o"))          # ('hello w', 'o', 'rld')

# edge: partition on empty string raises ValueError in CPython
# (skip that edge case here)

t = "aabbcc"
print(t.removeprefix("aa"))       # bbcc
print(t.removesuffix("cc"))       # aabb
print(t.partition("bb"))          # ('aa', 'bb', 'cc')
print(t.rpartition("bb"))         # ('aa', 'bb', 'cc')
