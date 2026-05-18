nums = [10, 20, 30]
print("nums direct:", nums[0], nums[1], nums[2], len(nums))

result = nums if nums is not None else []
print("result len:", len(result))
print("result is nums:", result is nums)
print("result[0] is nums:", result[0] is nums)
print("result[0] is result:", result[0] is result)
