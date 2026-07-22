# Regression: f-string format spec with variable width/precision
# Previously dynamic format specs (containing variables) were silently ignored.

# Variable width
width = 20
print(f'{"hello":>{width}}')

# Variable width with int
n = 42
w = 10
print(f'{n:>{w}}')

# Variable precision for float
pi = 3.14159265
prec = 3
print(f'{pi:.{prec}f}')

# Variable fill and width
x = 'test'
fill = '*'
fw = 15
print(f'{x:{fill}^{fw}}')
