# Regression: class method parameters not typed from call-site analysis
# Before fix: _analyze_call_sites only handled ast.Name calls (direct function
# calls) and skipped ast.Attribute calls (method calls like obj.method(args)).
# Additionally, _emit_method_body didn't consult _call_site_param_types at all.
# This caused method string parameters to be typed as i64 (int) instead of
# i8* (str), so string values were printed as raw addresses.
# Fix: _analyze_call_sites now handles Attribute calls, and _emit_method_body
# uses call-site types for parameter tag inference.

class Inventory:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

inv = Inventory()
inv.add("sword")
inv.add("shield")
inv.add("potion")
print(inv.items)

# Method with int param — same method name "add" on a different class.
# This tests that call-site analysis qualifies by class to avoid conflicts.
class Counter:
    def __init__(self):
        self.count = 0

    def add(self, n):
        self.count = self.count + n

c = Counter()
c.add(5)
c.add(3)
print(c.count)
