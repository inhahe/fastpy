# Regression: match/case MatchMapping with **rest captures remaining keys

d = {"name": "alice", "age": 30, "city": "nyc"}

match d:
    case {"name": name, **rest}:
        print(name)
        print(len(rest))
        print(rest["age"])
        print(rest["city"])
    case _:
        print("no match")
