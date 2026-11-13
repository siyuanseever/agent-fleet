# -*- coding: utf-8 -*-
"""路由闲着时，有同事消息在等就叫它一下。全部造数据，不碰 data/。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dtcc  # noqa: E402

A = {"id": "m1", "time": "2026-11-12 15:01:00", "sender": "同事甲", "conv": "某需求群", "single": False,
     "text": "@你 看下这个"}
B = {"id": "m2", "time": "2026-11-12 15:02:00", "sender": "同事乙", "single": True, "text": "在吗\n有个事"}


class Nudge(unittest.TestCase):
    def test_有待路由就叫_一行(self):
        text, ids = dtcc.router_nudge([A, B], {}, 1000.0)
        self.assertEqual(ids, ["m1", "m2"])
        self.assertIn("2 条", text)
        self.assertIn("同事甲@某需求群", text)
        self.assertNotIn("\n", text, "fleet wake 敲的是一行，换行会提前回车")

    def test_没有就不叫(self):
        self.assertEqual(dtcc.router_nudge([], {}, 1000.0), ("", []))

    def test_刚叫过的不重复叫(self):
        self.assertEqual(dtcc.router_nudge([A], {"m1": 900.0}, 1000.0, repeat_s=900), ("", []))

    def test_过了间隔再叫_只算新的(self):
        text, ids = dtcc.router_nudge([A, B], {"m1": 900.0}, 1000.0, repeat_s=900)
        self.assertEqual(ids, ["m2"])
        text, ids = dtcc.router_nudge([A], {"m1": 0.0}, 1000.0, repeat_s=900)
        self.assertEqual(ids, ["m1"])

    def test_多了只列三条(self):
        many = [dict(A, id="m%d" % i) for i in range(5)]
        text, ids = dtcc.router_nudge(many, {}, 1000.0)
        self.assertEqual(len(ids), 5)
        self.assertIn("另有 2 条", text)


if __name__ == "__main__":
    unittest.main()
