nums = [10, 20, 30]
print("direct len:", len(nums))

result = nums if nums is not None else []
print("ternary len:", len(result))

# Can we iterate over the result?
print("iterating:")
for x in result:
    print(" item:", x)

# What is result[0]?
print("result[0]:", result[0])
