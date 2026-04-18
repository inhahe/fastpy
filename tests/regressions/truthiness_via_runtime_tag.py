empty_list = []
nonempty_list = [1]
empty_dict = {}
nonempty_dict = {"a": 1}
empty_str = ""
nonempty_str = "x"

values = [empty_list, nonempty_list, empty_dict, nonempty_dict, empty_str, nonempty_str]
labels = ["empty_list", "nonempty_list", "empty_dict", "nonempty_dict", "empty_str", "nonempty_str"]

for i in range(len(values)):
    if values[i]:
        print(labels[i], "truthy")
    else:
        print(labels[i], "falsy")
