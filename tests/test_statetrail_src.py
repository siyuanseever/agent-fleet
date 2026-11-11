"""会话状态只认 statetrail（2026-11-11）：解析、状态口径、敲字闸、以及「别处不许再读老状态文件」。

全部喂内存数据，不跑 statetrail-tmux、不问 tmux、不碰 data/。
"""
import datetime as dt
import os
import pathlib
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fleet            # noqa: E402
import statetrail_src   # noqa: E402
import watch_done       # noqa: E402

AT = dt.datetime(2026, 11, 11, 13, 0, 0)


def item(pane, sid, state="read", session="OS", win=1, name="✳ journal", since=None, mate=False):
    return {"pane": pane, "sid": sid, "state": state, "session": session,
            "window": {"index": win, "name": name}, "cwd": "/tmp/x", "mate": mate,
            "config_dir": "/tmp/.claude", "chapter": None, "turns": [],
            "state_since": (since or AT - dt.timedelta(seconds=60)).isoformat()}


class 解析(unittest.TestCase):
    def test_字段对得上(self):
        out = statetrail_src.parse_list([item("%4", "s1", "run")], {"%4": "2"})
        r = out["%4"]
        self.assertEqual((r["sid"], r["session"], r["window"], r["window_name"], r["pane_index"], r["state"]),
                         ("s1", "OS", "1", "✳ journal", "2", "run"))
        self.assertEqual(r["since"], (AT - dt.timedelta(seconds=60)).timestamp())

    def test_没sid或没pane的跳过(self):
        out = statetrail_src.parse_list([item("%4", ""), item("", "s2"), "坏条目", None])
        self.assertEqual(out, {})

    def test_不是列表就是空(self):
        for bad in (None, {}, "x", 3):
            self.assertEqual(statetrail_src.parse_list(bad), {})

    def test_时间读不出是None不是0(self):
        it = item("%4", "s1")
        it["state_since"] = "昨天"
        self.assertIsNone(statetrail_src.parse_list([it])["%4"]["since"])

    def test_假实现(self):
        src = statetrail_src.FakeTrail([item("%4", "s1", "wait")], {"%4": "1"})
        self.assertEqual(src.panes()["%4"]["state"], "wait")


class 状态口径(unittest.TestCase):
    def test_四种状态(self):
        self.assertEqual({k: statetrail_src.fleet_state(k) for k in ("run", "wait", "done", "read")},
                         {"run": "busy", "wait": "blocked", "done": "idle", "read": "idle"})

    def test_会话表里wait是blocked(self):
        raw = statetrail_src.parse_list([item("%4", "s1", "wait"), item("%5", "s2", "done"),
                                         item("%6", "s3", "read"), item("%7", "s4", "run")])
        out, _ = fleet.build_sessions(raw, {}, {"%4", "%5", "%6", "%7"}, AT)
        self.assertEqual({k: v["state"] for k, v in out.items()},
                         {"s1": "blocked", "s2": "idle", "s3": "idle", "s4": "busy"})
        self.assertEqual(out["s1"]["age"], 60)

    def test_pane不在了就是closed(self):
        raw = statetrail_src.parse_list([item("%4", "s1", "run")])
        out, _ = fleet.build_sessions(raw, {}, set(), AT)
        self.assertEqual(out["s1"]["state"], "closed")


class 敲字闸(unittest.TestCase):
    def g(self, state, force=False):
        return statetrail_src.typing_guard({"state": state}, force)[0]

    def test_停在权限框上加force也不敲(self):
        self.assertFalse(self.g("blocked"))
        self.assertFalse(self.g("blocked", force=True))

    def test_在跑的要force才插队(self):
        self.assertFalse(self.g("busy"))
        self.assertTrue(self.g("busy", force=True))

    def test_闲着能敲(self):
        self.assertTrue(self.g("idle"))

    def test_wake和compact都走这道闸(self):
        src = pathlib.Path(ROOT, "fleet.py").read_text(encoding="utf-8")
        for fn in ("def cmd_wake", "def cmd_compact"):
            body = src.split(fn, 1)[1].split("\ndef ", 1)[0]
            self.assertIn("statetrail_src.typing_guard(", body, fn)


class watch_done只报没看过的(unittest.TestCase):
    def test_done报read不报(self):
        raw = statetrail_src.parse_list([item("%4", "aaaaaaaa1", "done"), item("%5", "bbbbbbbb2", "read"),
                                         item("%6", "cccccccc3", "run")])
        self.assertEqual([sid for sid, _ in watch_done.done_records(raw)], ["aaaaaaaa1"])


class 只认一个来源(unittest.TestCase):
    def test_代码里不再读老状态文件(self):
        """11-09 两套来源各判各的：同一个会话一边「在跑」一边「静默 6 小时」。
        老文件名只许出现在注释里讲历史，不许出现在会被执行的字符串里。"""
        bad = []
        for f in ("fleet.py", "console.py", "fleet_up.py", "watch_done.py", "dtcc.py", "route.py"):
            for n, line in enumerate(pathlib.Path(ROOT, f).read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if "tmux-claude-status" in code and not code.strip().startswith(('"', "'", "`")):
                    bad.append(f"{f}:{n}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
