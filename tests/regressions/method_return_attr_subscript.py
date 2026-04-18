# Regression: method returning self.<list_attr>[i] had wrong return type
# Before fix: _declare_class's return type detection only recognized literal
# constants, f-strings, and collection literals as string/pointer returns.
# `return self.items[i]` (subscript on a list attribute) wasn't detected, so
# the method was declared as returning i64. The string pointer was returned as
# an integer and printed as a raw address.
# Fix: added detection for `return self.<list_attr>[i]` (checks list attribute
# element type via call-site analysis of append calls) and
# `return self.<attr>` (list/dict attributes return pointers).

class NameList:
    def __init__(self):
        self.names = []

    def add(self, name):
        self.names.append(name)

    def get(self, index):
        return self.names[index]

    def count(self):
        return len(self.names)

nl = NameList()
nl.add("Alice")
nl.add("Bob")
nl.add("Charlie")
print(nl.get(0))
print(nl.get(1))
print(nl.get(2))
print(nl.count())
