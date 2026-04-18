class Node:
    def __init__(self, value):
        self.value = value
        self.next = None

def build_list(values):
    head = None
    for v in reversed(values):
        n = Node(v)
        n.next = head
        head = n
    return head

def print_list(head):
    items = []
    cur = head
    while cur is not None:
        items.append(str(cur.value))
        cur = cur.next
    print(" -> ".join(items))

lst = build_list([1, 2, 3, 4, 5])
print_list(lst)
