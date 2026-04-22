# Regression test for complex number support

# Basic complex literals
c1 = 3 + 4j
c2 = 1 - 2j
print(c1)           # (3+4j)
print(c2)           # (1-2j)

# Complex arithmetic
print(c1 + c2)      # (4+2j)
print(c1 - c2)      # (2+6j)
print(c1 * c2)      # (11-2j)

# abs of complex
print(abs(3 + 4j))  # 5.0

# Pure imaginary
print(2j)           # 2j
print(-3j)          # (-0-3j)

# Complex with zero real
c3 = 0 + 5j
print(c3)           # 5j
