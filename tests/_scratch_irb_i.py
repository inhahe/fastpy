# Minimal: self.attr access where attr has default=None
class Item:
    def __init__(self, value=None):
        self.value = value

    def show(self):
        if self.value:
            print("has value:", self.value)
        else:
            print("no value")

i1 = Item("hello")
i1.show()
i2 = Item()
i2.show()
