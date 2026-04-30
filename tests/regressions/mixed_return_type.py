# Function returns float from try, string from except
def classify(x):
    try:
        if x < 0:
            raise ValueError("negative")
        return 100 / x
    except ValueError as e:
        return f"ValueError: {e}"

print(classify(-1))
print(classify(5))
print(classify(10))
