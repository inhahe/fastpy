# Regression: truediv in method return types

class Temperature:
    def __init__(self, celsius):
        self._celsius = celsius
    
    @property
    def fahrenheit(self):
        return self._celsius * 9 / 5 + 32
    
    def to_fahrenheit(self):
        return self._celsius * 9 / 5 + 32

t = Temperature(100)
print(t.fahrenheit)     # 212.0
print(t.to_fahrenheit())  # 212.0

t2 = Temperature(0)
print(t2.fahrenheit)    # 32.0
print(t2.to_fahrenheit())  # 32.0

# Module-level truediv (was always correct)
print(100 * 9 / 5 + 32)  # 212.0
