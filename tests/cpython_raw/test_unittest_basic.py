import unittest

class TestBisect(unittest.TestCase):
    def test_bisect_right_basic(self):
        from bisect import bisect_right
        data = [1, 3, 5, 7, 9]
        self.assertEqual(bisect_right(data, 0), 0)
        self.assertEqual(bisect_right(data, 1), 1)
        self.assertEqual(bisect_right(data, 5), 3)
        self.assertEqual(bisect_right(data, 10), 5)

    def test_bisect_left_basic(self):
        from bisect import bisect_left
        data = [1, 3, 5, 7, 9]
        self.assertEqual(bisect_left(data, 0), 0)
        self.assertEqual(bisect_left(data, 1), 0)
        self.assertEqual(bisect_left(data, 5), 2)
        self.assertEqual(bisect_left(data, 10), 5)

    def test_insort(self):
        from bisect import insort
        lst = []
        for x in [5, 2, 8, 1, 9, 3]:
            insort(lst, x)
        self.assertEqual(lst, [1, 2, 3, 5, 8, 9])

class TestMath(unittest.TestCase):
    def test_basics(self):
        import math
        self.assertEqual(math.floor(3.7), 3)
        self.assertEqual(math.ceil(3.2), 4)
        self.assertAlmostEqual(math.sqrt(4), 2.0)
        self.assertAlmostEqual(math.pi, 3.14159265, places=5)

    def test_trig(self):
        import math
        self.assertAlmostEqual(math.sin(0), 0.0)
        self.assertAlmostEqual(math.cos(0), 1.0)
        self.assertAlmostEqual(math.sin(math.pi / 2), 1.0, places=10)

if __name__ == '__main__':
    unittest.main()
