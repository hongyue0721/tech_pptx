"""T01 smoke：先故意失败，验证施工AI真实修复而非删断言。"""
import unittest

from evidence_counter import EvidenceCounter


class TestEvidenceCounter(unittest.TestCase):
    def test_add_and_count(self):
        counter = EvidenceCounter()
        counter.add_located("c01")
        counter.add_located("c02")
        self.assertEqual(counter.located_count, 2)

    def test_duplicate_rejected(self):
        counter = EvidenceCounter()
        counter.add_located("c01")
        with self.assertRaises(ValueError):
            counter.add_located("c01")

    def test_empty_rejected(self):
        counter = EvidenceCounter()
        with self.assertRaises(ValueError):
            counter.add_located("")


if __name__ == "__main__":
    unittest.main()
