"""Test integer format spec: binary, hex, octal, zero-pad, sign, alternate form."""

# Binary
print(f"{255:08b}")       # 11111111
print(f"{10:b}")          # 1010
print(f"{0:b}")           # 0
print(f"{10:#b}")         # 0b1010
print(f"{10:#010b}")      # 0b00001010

# Hex
print(f"{255:x}")         # ff
print(f"{255:X}")         # FF
print(f"{255:#06x}")      # 0x00ff
print(f"{255:#06X}")      # 0X00FF
print(f"{16:04x}")        # 0010

# Octal
print(f"{8:o}")           # 10
print(f"{255:#o}")        # 0o377

# Sign
print(f"{42:+d}")         # +42
print(f"{-42:d}")         # -42
print(f"{42: d}")         #  42

# Width and alignment
print(f"{42:<10d}")       # 42--------  (8 trailing spaces)
print(f"{42:>10d}")       #         42  (8 leading spaces)
print(f"{42:^10d}")       #     42      (centered)
print(f"{42:*>10d}")      # ********42
print(f"{42:*<10d}")      # 42********

# Zero-pad with sign
print(f"{-42:08d}")       # -0000042

# Comma grouping
print(f"{1000000:,}")     # 1,000,000

print("format spec int tests passed!")
