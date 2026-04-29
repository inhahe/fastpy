# Regression: __format__ for f-strings

class Temp:
    def __init__(self, celsius):
        self.celsius = celsius

    def __format__(self, spec):
        if spec == "f":
            fahrenheit = self.celsius * 9 / 5 + 32
            return str(fahrenheit) + "F"
        return str(self.celsius) + "C"

    def __str__(self):
        return str(self.celsius) + "C"

t = Temp(100)
print(f"{t}")       # 100C (uses __str__ when no spec)
print(f"{t:f}")     # 212.0F (uses __format__ with spec "f")

t2 = Temp(0)
print(f"{t2:f}")    # 32.0F

# __format__ returning empty spec → default representation
print(f"{t2}")      # 0C
