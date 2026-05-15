# Regression: bracket matching algorithm using dict with string values
# and list of strings. Tests that string comparison works correctly when
# list elements come from dict subscript (d[k] produces string, appended
# to list, then compared with == / !=).

def is_balanced(s):
    stack = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    for c in s:
        if c in pairs:
            stack.append(pairs[c])
        elif c in (")", "]", "}"):
            if not stack or stack[-1] != c:
                return False
            stack.pop()
    return len(stack) == 0

print(is_balanced("()[]{}"))
print(is_balanced("([{}])"))
print(is_balanced("([)]"))
print(is_balanced("((()"))
