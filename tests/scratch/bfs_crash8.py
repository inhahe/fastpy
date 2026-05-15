# Compare: dict subscript with pop(0) vs pop()
queue1 = ["A", "B"]
node1 = queue1.pop(0)  # pop with index
d = {"A": 10, "B": 20}
print("pop(0):", d[node1])

queue2 = ["A", "B"]
node2 = queue2.pop()  # pop without index
print("pop():", d[node2])

# Also check .pop(0) on list of ints
nums = [1, 2, 3]
x = nums.pop(0)
d2 = {1: "one", 2: "two"}
print("int pop(0):", d2[x])
