# Minimal groupby: dict built via setdefault with int keys and list values
by_len = {}
by_len.setdefault(2, []).append('hi')
by_len.setdefault(5, []).append('hello')
by_len.setdefault(2, []).append('ok')
print(by_len)
for k in sorted(by_len):
    print(k, by_len[k])
