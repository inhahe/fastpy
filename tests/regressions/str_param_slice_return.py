def reverse(s):
    return s[::-1]

def first3(s):
    return s[:3]

def last3(s):
    return s[-3:]

def middle(s):
    return s[1:-1]

print(reverse("hello"))
print(first3("abcdef"))
print(last3("abcdef"))
print(middle("abcdef"))
