# UTF-8 code-point-based string indexing and slicing
# Tests that str[i], str[a:b], str[::step], list(str), enumerate(str)
# all work correctly with multi-byte characters.

# --- str[i] indexing ---
s = "café"
assert s[0] == "c"
assert s[1] == "a"
assert s[2] == "f"
assert s[3] == "é"
assert s[-1] == "é"
assert s[-2] == "f"
assert len(s) == 4
print("index ok")

# --- str[a:b] slicing ---
assert s[1:3] == "af"
assert s[2:] == "fé"
assert s[:2] == "ca"
assert s[-2:] == "fé"
assert s[:-1] == "caf"
assert s[:] == "café"
print("slice ok")

# --- str[::step] step slicing ---
assert s[::2] == "cf"
assert s[::-1] == "éfac"
assert s[3::-1] == "éfac"
assert s[1::2] == "aé"
print("step ok")

# --- list(str) ---
chars = list(s)
assert chars == ["c", "a", "f", "é"]
print("list ok")

# --- enumerate(str) ---
pairs = list(enumerate(s))
assert pairs == [(0, "c"), (1, "a"), (2, "f"), (3, "é")]
print("enumerate ok")

# --- 3-byte characters (CJK) ---
t = "日本語"
assert len(t) == 3
assert t[0] == "日"
assert t[1] == "本"
assert t[2] == "語"
assert t[-1] == "語"
assert t[1:] == "本語"
assert t[::-1] == "語本日"
assert list(t) == ["日", "本", "語"]
print("cjk ok")

# --- 4-byte characters (emoji) ---
u = "A🐍B"
assert len(u) == 3
assert u[0] == "A"
assert u[1] == "🐍"
assert u[2] == "B"
assert u[-2] == "🐍"
assert u[1:3] == "🐍B"
assert u[::-1] == "B🐍A"
assert list(u) == ["A", "🐍", "B"]
print("emoji ok")

# --- mixed multi-byte ---
v = "aéb日c🐍d"
assert len(v) == 7
assert v[0] == "a"
assert v[1] == "é"
assert v[3] == "日"
assert v[5] == "🐍"
assert v[6] == "d"
assert v[1:4] == "éb日"
assert v[::3] == "a日d"
print("mixed ok")

# --- for-loop iteration ---
out = []
for ch in "café":
    out.append(ch)
assert out == ["c", "a", "f", "é"]
print("for ok")

# --- str.find / str.rfind ---
assert s.find("é") == 3
assert s.find("f") == 2
assert s.find("z") == -1
assert s.rfind("é") == 3
assert s.rfind("a") == 1
t2 = "aéaé"
assert t2.find("é") == 1
assert t2.rfind("é") == 3
print("find ok")

# --- str.index ---
assert s.index("é") == 3
assert s.index("caf") == 0
print("index_sub ok")

# --- str.count ---
assert t2.count("é") == 2
assert t2.count("a") == 2
assert "日本日本".count("日") == 2
print("count ok")

# --- str.center / ljust / rjust ---
assert "café".center(8) == "  café  "
assert "café".ljust(8) == "café    "
assert "café".rjust(8) == "    café"
assert len("café".center(8)) == 8
assert "日本".center(6) == "  日本  "
print("justify ok")

# --- str.zfill ---
assert "café".zfill(8) == "0000café"
print("zfill ok")
