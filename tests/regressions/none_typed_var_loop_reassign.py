# Regression: variables initialized to None and reassigned inside a loop must
# load their actual runtime value, not a compile-time constant 0.
#
# _unwrap_fv_for_tag returned ir.Constant(i64, 0) for VKind.NONE, which is
# correct for single-assignment variables but wrong inside loops where the
# variable is reassigned to a different type (e.g. OBJ).  The generated IR
# hard-coded 0 for every load of the variable, silently discarding the runtime
# pointer stored by the previous iteration.

class Node:
    def __init__(self, val, nxt):
        self.val = val
        self.nxt = nxt

# Build linked list in a loop — head starts as None, becomes OBJ.
head = None
i = 0
while i < 5:
    head = Node(i + 1, head)
    i = i + 1

# Traverse — every node must be reachable (the chain was actually linked).
total = 0
cur = head
while cur is not None:
    total = total + cur.val
    cur = cur.nxt

print(total)  # 5+4+3+2+1 = 15

# Also verify that direct .nxt access works (was a segfault before the fix)
print(head.val)      # 5
print(head.nxt.val)  # 4
