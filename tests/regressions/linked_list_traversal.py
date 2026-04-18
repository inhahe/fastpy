class Node:
    def __init__(self, value):
        self.value = value
        self.next = None

def walk(head):
    cur = head
    while cur is not None:
        print(cur.value)
        cur = cur.next

n1 = Node(1)
n2 = Node(2)
n1.next = n2
walk(n1)
