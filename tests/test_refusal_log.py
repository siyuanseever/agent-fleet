"""往窗格敲字被护栏拒绝时记一行 wake-refused（2026-11-11）。

全部打桩：resolve_target / pane_alive / 抓屏 / append_event 都换成内存假货，不问 tmux、不碰 data/。
"""
import argparse
import datetime as dt
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dtcc    # noqa: E402
import fleet   # noqa: E402

AT = dt.datetime(2026, 11, 11, 14, 0, 0)
SID = "abcd1234-0000-0000-0000-000000000000"


def rec(state="idle"):
    return {"sid": SID, "pane": "%7", "tmux": "w:1.1", "window_name": "proj", "project": "proj",
            "state": state, "known": "live"}


class 纯函数(unittest.TestCase):
    def test_原因码(self):
        self.assertEqual(fleet.refuse_reason("blocked"), "wait")
        self.assertEqual(fleet.refuse_reason("busy"), "busy")

    def test_一行的字段(self):
        e = fleet.refusal_event("wake", SID, rec("busy"), "busy", "feedbeef", AT)
        self.assertEqual({k: e[k] for k in ("kind", "path", "sid", "pane", "reason", "by", "when")},
                         {"kind": "wake-refused", "path": "wake", "sid": SID, "pane": "%7",
                          "reason": "busy", "by": "feedbeef", "when": "2026-11-11 14:00:00"})
        self.assertIn("在跑", e["what"])

    def test_没给调用方记cli(self):
        self.assertEqual(fleet.refusal_event("wake", SID, rec(), "busy", "", AT)["by"], "cli")


class 打桩(unittest.TestCase):
    """把 cmd_wake / cmd_compact 用到的 IO 全换掉，看每种拒绝各记了什么。"""

    NAMES = ("resolve_target", "pane_alive", "awaiting_choice", "pending_input_stable",
             "append_event", "now", "env_sid", "tmux_send")

    def setUp(self):
        self._orig = {k: getattr(fleet, k) for k in self.NAMES}
        self.events = []
        self.state, self.alive, self.choice, self.pending = "idle", True, False, ""
        fleet.resolve_target = lambda t: (SID, rec(self.state))
        fleet.pane_alive = lambda p: self.alive
        fleet.awaiting_choice = lambda p: self.choice
        fleet.pending_input_stable = lambda p: self.pending
        fleet.append_event = self.events.append
        fleet.now = lambda: AT
        fleet.env_sid = lambda: "feedbeef-ffff"
        fleet.tmux_send = lambda p, t: self.fail("不该真敲字")

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(fleet, k, v)

    def run_cmd(self, fn, **kw):
        a = dict(target="proj", task="x", force=False, dry_run=False, timeout=1)
        a.update(kw)
        with redirect_stdout(io.StringIO()):
            return fn(argparse.Namespace(**a))

    def reasons(self):
        return [(e["path"], e["reason"], e["by"]) for e in self.events]

    def test_wake_每种拒绝各记一行(self):
        cases = [(dict(state="busy"), "busy"), (dict(state="blocked"), "wait"),
                 (dict(alive=False), "pane-gone"), (dict(choice=True), "awaiting-choice"),
                 (dict(pending="半句话"), "pending-input")]
        for setup, want in cases:
            self.events.clear()
            self.state, self.alive, self.choice, self.pending = "idle", True, False, ""
            for k, v in setup.items():
                setattr(self, k, v)
            self.assertEqual(self.run_cmd(fleet.cmd_wake), 1)
            self.assertEqual(self.reasons(), [("wake", want, "feedbeef")], setup)

    def test_compact_也记(self):
        self.state = "blocked"
        self.assertEqual(self.run_cmd(fleet.cmd_compact), 1)
        self.assertEqual(self.reasons(), [("compact", "wait", "feedbeef")])

    def test_autocompact借道时记成autocompact(self):
        self.state = "busy"
        self.run_cmd(fleet.cmd_compact, via="autocompact")
        self.assertEqual(self.reasons(), [("compact", "busy", "autocompact")])

    def test_dry_run不记(self):
        self.state = "busy"
        self.assertEqual(self.run_cmd(fleet.cmd_wake, dry_run=True), 1)
        self.assertEqual(self.events, [])

    def test_没被拒就不记拒绝(self):
        fleet.tmux_send = lambda p, t: False      # 走到真敲字那步（假的失败），说明护栏都过了
        self.run_cmd(fleet.cmd_wake)
        self.assertEqual([e for e in self.events if e.get("kind") == "wake-refused"], [])

    def test_force插队busy不记_但wait照拒照记(self):
        self.state = "busy"
        fleet.tmux_send = lambda p, t: False
        self.run_cmd(fleet.cmd_wake, force=True)
        self.assertEqual(self.events, [])
        self.state = "blocked"
        self.assertEqual(self.run_cmd(fleet.cmd_wake, force=True), 1)
        self.assertEqual(self.reasons(), [("wake", "wait", "feedbeef")])


class 手机投递的原因码(unittest.TestCase):
    def setUp(self):
        self._fm = dtcc.fleet_mod

    def tearDown(self):
        dtcc.fleet_mod = self._fm

    def fake(self, state, alive=True):
        class F:
            refuse_reason = staticmethod(fleet.refuse_reason)

            def sessions(self_):
                return {SID: rec(state)}

            def pane_alive(self_, p):
                return alive

            def sh(self_, *a, **k):
                raise AssertionError("不该真敲字")
        dtcc.fleet_mod = lambda: F()

    def test_wake_session返回原因(self):
        cmd = {"text": "看一下"}
        self.fake("busy")
        self.assertEqual(dtcc.wake_session({}, SID, cmd), (False, "busy"))
        self.fake("blocked")
        self.assertEqual(dtcc.wake_session({}, SID, cmd), (False, "wait"))
        self.fake("idle", alive=False)
        self.assertEqual(dtcc.wake_session({}, SID, cmd), (False, "pane-gone"))


if __name__ == "__main__":
    unittest.main()
