# Regression: sorted() with string-returning key functions
# Bug 1: key=lambda s: s.lower() wasn't detected as returning str,
# so list_sorted_by_key_int was used (compares string pointers as
# integers → random order).
# Bug 2: key=str on string lists used the int_to_str shim, which
# interpreted string pointers as integer values → wrong sort keys.
# Fix: extended key_returns_str detection for method calls and
# str() calls; key=str on string lists skips the key function
# (str on str is identity).

# Case 1: sorted with key=lambda x: x.lower()
words = ["Banana", "apple", "Cherry"]
result = sorted(words, key=lambda x: x.lower())
print(result)

# Case 2: sorted with key=lambda x: x.upper()
result2 = sorted(words, key=lambda x: x.upper())
print(result2)

# Case 3: sorted with key=str on strings (identity)
names = ["charlie", "alice", "bob"]
result3 = sorted(names, key=str)
print(result3)

# Case 4: sorted with key=str on integers
nums = [3, 1, 2, 10]
result4 = sorted(nums, key=str)
print(result4)

# Case 5: sorted with key=lambda x: x (identity on strings)
result5 = sorted(names, key=lambda x: x)
print(result5)

# Case 6: sorted with key=lambda x: x.strip()
padded = ["  c", " a", "   b"]
result6 = sorted(padded, key=lambda x: x.strip())
print(result6)

# Case 7: sorted with reverse=True and string key
result7 = sorted(names, key=lambda x: x, reverse=True)
print(result7)

# Case 8: sorted list of tuples by string element
pairs = [(1, "b"), (3, "a"), (2, "c")]
result8 = sorted(pairs, key=lambda x: x[1])
print(result8)

# Case 9: sorted objects by string attribute
class Student:
    def __init__(self, name, grade):
        self.name = name
        self.grade = grade

students = [Student("Charlie", 78), Student("Alice", 92), Student("Bob", 85)]
by_name = sorted(students, key=lambda s: s.name)
for s in by_name:
    print(s.name, s.grade)

# Case 10: .sort() with string key
words2 = ["Banana", "apple", "Cherry"]
words2.sort(key=lambda x: x.lower())
print(words2)

# Case 11: sorted by tuple key (multi-criteria)
data = [("Alice", 85), ("Bob", 85), ("Charlie", 92), ("David", 78)]
result11 = sorted(data, key=lambda x: (-x[1], x[0]))
for name, score in result11:
    print(name, score)
