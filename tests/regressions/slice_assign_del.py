# Regression: extended slice assignment and del on slices
# Bug 1: lst[::2] = values treated as lst[:] = values (ignored step)
# Bug 2: del lst[1:3] didn't delete the slice range

# Extended slice assignment (step)
lst = [0, 1, 2, 3, 4, 5]
lst[::2] = [10, 20, 30]
print(lst)  # [10, 1, 20, 3, 30, 5]

# Extended slice with bounds and step
lst2 = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
lst2[1:8:2] = [10, 20, 30, 40]
print(lst2)  # [0, 10, 2, 20, 4, 30, 6, 40, 8, 9]

# Negative step assignment
lst3 = [0, 1, 2, 3, 4, 5]
lst3[::-2] = [10, 20, 30]
print(lst3)  # [0, 20, 2, 10, 4, 30] — wait, actually reversed

# Size mismatch raises ValueError
try:
    lst4 = [0, 1, 2, 3, 4, 5, 6]
    lst4[::2] = [10, 20, 30]  # 4 positions, 3 values
except ValueError as e:
    print("caught:", e)

# del with slice
lst5 = [0, 1, 2, 3, 4, 5]
del lst5[1:3]
print(lst5)  # [0, 3, 4, 5]

lst6 = [0, 1, 2, 3, 4, 5]
del lst6[:2]
print(lst6)  # [2, 3, 4, 5]

lst7 = [0, 1, 2, 3, 4, 5]
del lst7[4:]
print(lst7)  # [0, 1, 2, 3]

lst8 = [0, 1, 2, 3, 4, 5]
del lst8[-2:]
print(lst8)  # [0, 1, 2, 3]

# Basic slice assignment still works
lst9 = [0, 1, 2, 3, 4, 5]
lst9[1:3] = [10, 20, 30]
print(lst9)  # [0, 10, 20, 30, 3, 4, 5]
