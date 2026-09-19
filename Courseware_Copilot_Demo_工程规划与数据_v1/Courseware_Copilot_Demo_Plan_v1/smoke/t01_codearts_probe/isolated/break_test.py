"""故意失败用例：验证断言真的在把关（T01验收要求'失败测试真实修复'）。"""
import unittest

from evidence_counter import EvidenceCounter


class TestBreakThenFix(unittest.TestCase):
    def test_overflow_limit_enforced(self):
        counter = EvidenceCounter(max_claims=2)
        counter.add_located("c01")
        counter.add_located("c02")
        # 第3条应抛OverflowError——当前实现是否真的有这个行为？
        with self.assertRaises(OverflowError):
            counter.add_located("c03")


if __name__ == "__main__":
    unittest.main()
