# Regression: linked list with default=None parameter
# The `next` attribute receives either an object (Node) or None.
# When default=None, the compiler must tag the param as nullable
# so `while current is not None` terminates correctly.

class Node:
    def __init__(self, val, next_node=None):
        self.val = val
        self.next = next_node

    def prepend(self, val):
        return Node(val, self)

def list_to_str(node):
    parts = []
    current = node
    while current is not None:
        parts.append(str(current.val))
        current = current.next
    return " -> ".join(parts)

def sum_list(node):
    total = 0
    current = node
    while current is not None:
        total = total + current.val
        current = current.next
    return total

def list_len(node):
    count = 0
    current = node
    while current is not None:
        count = count + 1
        current = current.next
    return count

# Build list: 3 -> 2 -> 1
head = Node(1)
head = head.prepend(2)
head = head.prepend(3)
print(list_to_str(head))
print(sum_list(head))
print(list_len(head))

# Single node
single = Node(42)
print(list_to_str(single))
print(sum_list(single))
print(list_len(single))
