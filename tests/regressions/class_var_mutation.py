# Regression: class-level variable mutation (counting instances, etc.)

class Counter:
    count = 0
    def __init__(self):
        Counter.count = Counter.count + 1

c1 = Counter()
c2 = Counter()
c3 = Counter()
print(Counter.count)   # 3

# Multiple class vars, conditional update
class Scoreboard:
    total = 0
    max_score = 0

    def __init__(self, s):
        self.score = s
        Scoreboard.total = Scoreboard.total + s
        if s > Scoreboard.max_score:
            Scoreboard.max_score = s

p1 = Scoreboard(10)
p2 = Scoreboard(25)
p3 = Scoreboard(15)
print(Scoreboard.total)      # 50
print(Scoreboard.max_score)  # 25

# Float class var
class Physics:
    gravity = 9.8
    def __init__(self, g):
        Physics.gravity = g

Physics(9.81)
print(Physics.gravity)  # 9.81
