# Regression: multi-generator dict comp with string keys + sorted iteration
d = {str(i)+str(j): i*j for i in range(3) for j in range(3)}
for k in sorted(d.keys()):
    print(k, d[k])
