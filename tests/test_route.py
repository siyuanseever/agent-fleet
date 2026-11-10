# -*- coding: utf-8 -*-
"""route.py 的判据。全部造数据，不碰 data/。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import route  # noqa: E402

A = "aaaaaaaa-0000-0000-0000-000000000001"
A2 = "aaaaaaaa-0000-0000-0000-000000000002"
B = "bbbbbbbb-0000-0000-0000-000000000001"


def fwd(ts, to, pane, rid=None):
    r = {"ts": ts, "decision": "forward", "to": to, "to_pane": pane, "to_label": "x", "item": "事"}
    if rid:
        r["id"] = rid
    return r


class OpenItems(unittest.TestCase):
    def test_回过信的不再列出(self):
        routes = [fwd("2026-11-10T10:00+08:00", A, "%4", "r-1"), {"re": "r-1", "decision": "done"}]
        self.assertEqual(route.open_items(routes, [{"sid": A, "pane": "%4", "state": "read"}]), [])

    def test_没有id的旧行用ts对回信(self):
        ts = "2026-11-09T17:56:00+08:00"
        routes = [fwd(ts, A, "%4"), {"re": ts, "decision": "done"}]
        self.assertEqual(route.open_items(routes, []), [])

    def test_只看forward(self):
        routes = [{"ts": "t", "decision": "skip", "to": A}, {"ts": "t2", "decision": "manual", "to": A}]
        self.assertEqual(route.open_items(routes, []), [])

    def test_窗格里换了会话标moved不标gone(self):
        # 11-10 journal 窗格 %4 从 1dfc 换成 6e44，监控页把它画成了已关闭
        out = route.open_items([fwd("t", A, "%4", "r-1")], [{"sid": A2, "pane": "%4", "state": "read"}])
        self.assertEqual(out[0]["where"], "moved")
        self.assertEqual(out[0]["now_sid"], A2)

    def test_真关了标gone(self):
        out = route.open_items([fwd("t", A, "%4", "r-1")], [{"sid": B, "pane": "%9"}])
        self.assertEqual(out[0]["where"], "gone")

    def test_回信本身不算待回(self):
        out = route.open_items([{"re": "r-x", "decision": "forward", "to": A}], [])
        self.assertEqual(out, [])


class Ids(unittest.TestCase):
    def test_同一分钟不撞号(self):
        ts = "2026-11-10T18:30:00+08:00"
        self.assertEqual(route.new_id(ts, set()), "r-261110-1830")
        self.assertEqual(route.new_id(ts, {"r-261110-1830"}), "r-261110-1830-2")


class RouterPane(unittest.TestCase):
    def test_按session和窗口名认路由(self):
        # window 的形状照 statetrail-tmux list --json 实抓：对象，name 前面挂状态符号
        ns = [{"session": "OS", "window": {"index": 1, "name": "✳ journal"}, "sid": B},
              {"session": "OS", "window": {"index": 2, "name": "✳ xiaoding"}, "sid": A},
              {"session": "OS", "window": {"index": 2, "name": "xiaoding"}, "sid": B, "mate": True}]
        self.assertEqual(route.router_pane(ns, "OS:xiaoding")["sid"], A)

    def test_没配就没有(self):
        self.assertIsNone(route.router_pane([{"session": "OS", "window": {"index": 1, "name": "x"}}], ""))


if __name__ == "__main__":
    unittest.main()
