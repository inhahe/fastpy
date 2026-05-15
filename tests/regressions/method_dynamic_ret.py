# Regression: method return type preserved through set_ret_tag
# Previously, methods returning dynamic types (e.g. list.pop()
# returns string but method signature is i64) lost type info
# and printed as integers.

class Stack:
    def __init__(self):
        self.items = []

    def push(self, item):
        self.items.append(item)

    def pop(self):
        return self.items.pop()

    def peek(self):
        return self.items[-1]

    def is_empty(self):
        return len(self.items) == 0

s = Stack()
s.push("hello")
s.push("world")
print(s.pop())
print(s.peek())
print(s.is_empty())
