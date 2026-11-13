# -*- coding: utf-8 -*-
"""扫表情写回 triage 时不能冲掉别人在这期间 mark 的条目（2026-11-13 丢过两条）。全部造数据，不碰 data/。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dtwatch as dw  # noqa: E402


class MergeTriage(unittest.TestCase):
    def test_期间别人标的保留(self):
        current = {"m1": {"status": "done", "note": "路由转走"}}       # 扫描期间路由标的
        updates = {"m2": {"status": "done", "note": "他贴了 OK"}}     # 扫描得到的
        out = dw.merge_triage(current, updates)
        self.assertEqual(set(out), {"m1", "m2"})

    def test_已有的不被表情结论覆盖(self):
        current = {"m1": {"status": "ignored", "note": "人标的"}}
        out = dw.merge_triage(current, {"m1": {"status": "done", "note": "他贴了 OK"}})
        self.assertEqual(out["m1"]["note"], "人标的")

    def test_不改传入的字典(self):
        current = {}
        dw.merge_triage(current, {"m2": {"status": "done"}})
        self.assertEqual(current, {})


if __name__ == "__main__":
    unittest.main()
