# Regression test for MatchSingleton patterns (case None, case True, case False)

def check_none(x):
    match x:
        case None:
            return "none"
        case _:
            return "not none"

print(check_none(None))    # none
print(check_none(0))       # not none
print(check_none(False))   # not none
print(check_none(""))      # not none

def check_bool(x):
    match x:
        case True:
            return "true"
        case False:
            return "false"
        case None:
            return "none"
        case _:
            return "other"

print(check_bool(True))    # true
print(check_bool(False))   # false
print(check_bool(None))    # none
print(check_bool(1))       # other  (1 is int, not bool True)
print(check_bool(0))       # other  (0 is int, not bool False)

# Test: singleton patterns mixed with literal patterns
def classify(x):
    match x:
        case None:
            return "null"
        case True:
            return "yes"
        case False:
            return "no"
        case 0:
            return "zero"
        case 1:
            return "one"
        case _:
            return "other"

print(classify(None))    # null
print(classify(True))    # yes
print(classify(False))   # no
print(classify(0))       # zero
print(classify(1))       # one
print(classify(42))      # other

# Test: None in sequence pattern
def check_pair(pair):
    match pair:
        case (None, x):
            return "first is None, second=" + str(x)
        case (x, None):
            return "first=" + str(x) + ", second is None"
        case (x, y):
            return str(x) + "," + str(y)

print(check_pair((None, 5)))    # first is None, second=5
print(check_pair((3, None)))    # first=3, second is None
print(check_pair((1, 2)))       # 1,2
