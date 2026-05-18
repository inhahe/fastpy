nums = [10, 20, 30]

result = nums if nums is not None else []
print("ternary len:", len(result))

# Try to access result[0] as a list
inner = result[0]
print("inner type?")
# Try len of inner
n2 = len(inner)
print("inner len:", n2)
# iterate inner
for x in inner:
    print(" inner item:", x)
