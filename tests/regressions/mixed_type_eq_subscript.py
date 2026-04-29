# Regression: mixed-type function with string subscript return value

def grade(score, breakpoints, grades):
    # bisect_right inlined for simplicity
    lo = 0
    hi = len(breakpoints)
    while lo < hi:
        mid = (lo + hi) // 2
        if score < breakpoints[mid]:
            hi = mid
        else:
            lo = mid + 1
    return grades[lo]

def check_eq(actual, expected, msg):
    if actual == expected:
        print("PASS:", msg)
    else:
        print("FAIL:", msg, "got", actual, "expected", expected)

breakpoints = [60, 70, 80, 90]
grades = "FDCBA"

# int comparisons
check_eq(1, 1, "int")
check_eq(1, 2, "int diff")

# string comparison via grade function
check_eq(grade(33, breakpoints, grades), "F", "grade 33")
check_eq(grade(99, breakpoints, grades), "A", "grade 99")
check_eq(grade(77, breakpoints, grades), "C", "grade 77")
