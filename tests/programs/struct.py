"""Test native struct module."""
import struct

# calcsize
print(struct.calcsize(">I"))     # 4 (big-endian unsigned int)
print(struct.calcsize("<HHI"))   # 8 (2+2+4)
print(struct.calcsize("!BHI"))   # 7 (1+2+4)

# pack and unpack — big-endian unsigned int
packed = struct.pack(">I", 0x12345678)
vals = struct.unpack(">I", packed)
print(vals[0] == 0x12345678)     # True

# pack multiple values — little-endian
packed2 = struct.pack("<HH", 1000, 2000)
vals2 = struct.unpack("<HH", packed2)
print(vals2[0])                  # 1000
print(vals2[1])                  # 2000

# Pack signed values
packed3 = struct.pack("<i", -42)
vals3 = struct.unpack("<i", packed3)
print(vals3[0])                  # -42

# 64-bit values
packed4 = struct.pack(">q", 123456789012345)
vals4 = struct.unpack(">q", packed4)
print(vals4[0])                  # 123456789012345

print("struct tests passed!")
