# -*- coding: utf-8 -*-
"""路由会话兜底 + 直达记账（2026-11-12）。

两件事：
  1. 同事消息点名他（at_me）或催办（urgent），没被登记 / 静态表认领时，投给路由会话；
     只投 `router_since` 之后采进来的、且不超过 24 小时的。
  2. 绕过路由直达的两类（手机引用 / 点名、回信被登记认领）往 route.ndjson 记 decision=direct；
     `route.open_items` 只看 forward，direct 不会变成「待回信」。

全部造数据：名字、群名、cid、sid 都是编的。不碰 data/。
"""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dtcc  # noqa: E402
import dtwatch as dw  # noqa: E402
import route  # noqa: E402

ROUTER = "aaaa0000-1111-2222-3333-444455556666"
PROJ = "bbbb0000-1111-2222-3333-444455556666"
WAITER = "cccc0000-1111-2222-3333-444455556666"
CID = "cidFAKEfake0000000000000000000000000000000="
CID2 = "cidFAKEfake0000000000000000000000000000001="

NOW = dt.datetime(2026, 11, 12, 15, 0, 0)
SINCE = "2026-11-12 14:00:00"
RT = {"sid": ROUTER, "since": SINCE}


def ago(minutes):
    return dw.ts(NOW - dt.timedelta(minutes=minutes))


def rec(rid="m1", flags=("at_me",), collected=None, level="high", single=False,
        conv="某项目群", sender="张三", cid=CID, time=None):
    collected = collected or ago(5)
    return {"id": rid, "cid": cid, "conv": conv, "single": single, "sender": sender,
            "time": time or collected, "collected_at": collected, "text": "帮我看下这个",
            "level": level, "flags": list(flags)}


def claim(sid=WAITER, cid=CID, until_min=60):
    return {"cid": cid, "sid": sid, "label": "等张三", "until": dw.ts(NOW + dt.timedelta(minutes=until_min))}


class 判据_该不该兜底(unittest.TestCase):
    def test_点名和催办都算(self):
        self.assertEqual(dw.router_hit(rec(flags=["at_me"])), "点名")
        self.assertEqual(dw.router_hit(rec(flags=["urgent", "urgent:会议"])), "催办")
        self.assertEqual(dw.router_hit(rec(flags=["urgent:截止"])), "催办")

    def test_真人私聊算(self):
        """2026-11-12 漏过一条：私聊里没写他名字，没有 at_me，路由收不到。"""
        self.assertEqual(dw.router_hit(rec(flags=["dm", "kw:排期"], single=True)), "私聊")

    def test_私聊收尾话不算(self):
        for t in ["好的", "收到。谢谢！", "ok", "1", "对", "Hello", "好啊", "感谢"]:
            self.assertEqual(dw.router_hit(dict(rec(flags=["dm"], single=True), text=t)), "", t)
        for t in ["好的，那哪天能上？", "你在负责那个小程序开发吗？", "可以了", "审核通过了", "我现在可以"]:
            self.assertEqual(dw.router_hit(dict(rec(flags=["dm"], single=True), text=t)), "私聊", t)

    def test_机器人私聊和压低的私聊不算(self):
        self.assertEqual(dw.router_hit(rec(flags=["dm"], single=True, level="normal")), "")
        self.assertEqual(dw.router_hit(rec(flags=["dm", "acked:OK"], single=True, level="low")), "")

    def test_他贴过表情的私聊不投(self):
        r = rec(flags=["dm", "acked:OK"], single=True, level="high")
        self.assertEqual(dw.match_router(r, RT, NOW), ("", ""))

    def test_普通消息不算(self):
        self.assertEqual(dw.router_hit(rec(flags=["kw:排期"])), "")
        self.assertEqual(dw.router_hit(rec(flags=[])), "")
        # 前缀像但不是：别让 urgent_xxx 之类的标记混进来
        self.assertEqual(dw.router_hit(rec(flags=["urgently"])), "")

    def test_没配路由或起点就不兜底(self):
        self.assertEqual(dw.match_router(rec(), None, NOW), ("", ""))
        self.assertEqual(dw.match_router(rec(), {"sid": ROUTER}, NOW), ("", ""))
        self.assertEqual(dw.match_router(rec(), {"sid": "", "since": SINCE}, NOW), ("", ""))

    def test_起点之前采进来的不投(self):
        """上线时 inbox 里已有上千条历史 at_me，不能一次灌给路由。"""
        self.assertEqual(dw.match_router(rec(collected="2026-11-12 13:59:59"), RT, NOW), ("", ""))

    def test_正好在起点算新的(self):
        self.assertEqual(dw.match_router(rec(collected=SINCE), RT, NOW), (ROUTER, "路由·点名"))

    def test_起点之后的投(self):
        self.assertEqual(dw.match_router(rec(), RT, NOW), (ROUTER, "路由·点名"))

    def test_超过24小时的不投_即使起点更早(self):
        old = {"sid": ROUTER, "since": "2026-11-01 00:00:00"}
        self.assertEqual(dw.match_router(rec(collected=ago(24 * 60 + 1)), old, NOW), ("", ""))
        self.assertEqual(dw.match_router(rec(collected=ago(24 * 60 - 1)), old, NOW)[0], ROUTER)

    def test_起点认采集时刻不认发送时刻(self):
        """隔夜补采的旧消息 time 很早，但对路由是刚到的。"""
        r = rec(collected=ago(5), time="2026-11-11 20:00:00")
        self.assertEqual(dw.match_router(r, RT, NOW)[0], ROUTER)

    def test_没有采集时刻退回发送时刻(self):
        r = rec()
        r.pop("collected_at")
        r["time"] = ago(5)
        self.assertEqual(dw.match_router(r, RT, NOW)[0], ROUTER)
        r["time"] = "2026-11-12 13:00:00"
        self.assertEqual(dw.match_router(r, RT, NOW), ("", ""))

    def test_他贴过表情的不投(self):
        self.assertEqual(dw.match_router(rec(flags=["at_me", "acked:OK"]), RT, NOW), ("", ""))

    def test_私聊里他之后回过话的不投_群里不算(self):
        dm = rec(flags=["at_me", "replied_after"], single=True)
        grp = rec(flags=["at_me", "replied_after"], single=False)
        self.assertEqual(dw.match_router(dm, RT, NOW), ("", ""))
        self.assertEqual(dw.match_router(grp, RT, NOW)[0], ROUTER)


class 顺序_登记和静态表在前(unittest.TestCase):
    def test_登记认领的不给路由(self):
        self.assertEqual(dw.route_why(rec(), {}, [claim()], NOW, RT), (WAITER, "等张三", "awaiting"))

    def test_静态表命中的不给路由(self):
        cfg = {"route": {"某项目群": PROJ}}
        self.assertEqual(dw.route_why(rec(), cfg, None, NOW, RT), (PROJ, "某项目群", "static"))

    def test_都没认领才给路由(self):
        self.assertEqual(dw.route_why(rec(), {}, [claim(cid=CID2)], NOW, RT),
                         (ROUTER, "路由·点名", "router"))

    def test_不是点名催办的都没人认就留着(self):
        self.assertEqual(dw.route_why(rec(flags=["kw:排期"]), {}, None, NOW, RT), ("", "", ""))

    def test_给了router不给at当场抛错(self):
        with self.assertRaises(ValueError):
            dw.route_why(rec(), {}, None, None, RT)

    def test_route_of不受影响(self):
        """route_of 没有 router 参数，at_me 照旧是 ("","")。"""
        self.assertEqual(dw.route_of(rec(), {}), ("", ""))
        self.assertEqual(dw.route_of(rec(), {}, [claim()], NOW), (WAITER, "等张三"))


class 投递_接进_select_for_session(unittest.TestCase):
    def pick(self, records, session=ROUTER, router=RT, claims=None, cfg=None, ledger=None,
             triage=None, level="normal", at=NOW):
        return dw.select_for_session(records, cfg or {}, session, level, triage or {},
                                     ledger if ledger is not None else {}, at, claims, router)

    def test_路由会话拿到点名(self):
        got = self.pick([rec("m1"), rec("m2", flags=["kw:排期"], level="normal")])
        self.assertEqual([(r["id"], label) for r, label, _ in got], [("m1", "路由·点名")])

    def test_别的会话拿不到(self):
        self.assertEqual(self.pick([rec()], session=PROJ), [])

    def test_router为None跟以前一样(self):
        self.assertEqual(self.pick([rec()], router=None), [])

    def test_已mark的不投(self):
        self.assertEqual(self.pick([rec()], triage={"m1": {"status": "done"}}), [])

    def test_记账之后不重复投_15分钟后重投必达(self):
        ledger = {}
        first = self.pick([rec()], ledger=ledger)
        dw.stamp_delivered(ledger, [r for r, _, _ in first], NOW)
        self.assertEqual(self.pick([rec()], ledger=ledger), [])
        later = NOW + dt.timedelta(minutes=16)
        again = self.pick([rec()], ledger=ledger, at=later)
        self.assertEqual(len(again), 1)
        self.assertTrue(again[0][2], "重投要带上次的时间")

    def test_级别过滤照旧(self):
        self.assertEqual(self.pick([rec(level="low")]), [])


class 直达记账_for_session(unittest.TestCase):
    STAMP = "2026-11-12T15:00:00+08:00"

    def test_登记认领的首投记一行(self):
        picked = [(rec("m1"), "等张三", "")]
        rows = dw.direct_rows(picked, {}, [claim()], NOW, self.STAMP)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["decision"], r["reason"], r["to"], r["source"], r["evidence"], r["router"]),
                         ("direct", "awaiting", WAITER, "dingtalk", "m1", ""))
        self.assertEqual(r["ts"], self.STAMP)

    def test_重投不再记(self):
        picked = [(rec("m1"), "等张三", ago(20))]
        self.assertEqual(dw.direct_rows(picked, {}, [claim()], NOW, self.STAMP), [])

    def test_静态表和路由兜底不记(self):
        cfg = {"route": {"某项目群": PROJ}}
        self.assertEqual(dw.direct_rows([(rec("m1"), "x", "")], cfg, None, NOW, self.STAMP), [])
        self.assertEqual(dw.direct_rows([(rec("m1"), "x", "")], {}, None, NOW, self.STAMP), [])


class 直达行格式与open(unittest.TestCase):
    def test_直达行字段齐(self):
        r = route.direct_rec("phone", "把 demo\n推一下", PROJ, "quote", "msg-1",
                             "2026-11-12T15:00:00+08:00", "%7", "proj/bbbb")
        self.assertEqual(set(r), {"ts", "router", "source", "item", "decision", "to", "to_pane",
                                  "to_label", "reason", "evidence"})
        self.assertEqual(r["item"], "把 demo 推一下")          # 一行
        self.assertEqual(r["decision"], "direct")

    def test_理由只认三种(self):
        with self.assertRaises(ValueError):
            route.direct_rec("phone", "x", PROJ, "default", "m", "t")

    def test_落盘补id_且不进open(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "route.ndjson")
            ts = "2026-11-12T15:00:00+08:00"
            route.append({"id": "r-261112-1500", "ts": ts, "decision": "forward", "to": PROJ,
                          "to_pane": "%7", "item": "转出去的"}, p)
            got = route.log_direct([route.direct_rec("phone", "a", PROJ, "quote", "m1", ts),
                                    route.direct_rec("dingtalk", "b", WAITER, "awaiting", "m2", ts)], p)
            ids = [r["id"] for r in got]
            self.assertEqual(len(set(ids + ["r-261112-1500"])), 3, "id 不许撞")
            rows = route.load(__import__("pathlib").Path(p))
            self.assertEqual(len(rows), 3)
            opened = route.open_items(rows, [])
            self.assertEqual([o["id"] for o in opened], ["r-261112-1500"],
                             "direct 不是转出，不该变成待回信")

    def test_空批不碰文件(self):
        self.assertEqual(route.log_direct([], "/nonexistent/dir/route.ndjson"), [])


class 直达记账_手机指令(unittest.TestCase):
    def test_判据(self):
        self.assertEqual(dtcc.direct_reason("quote", PROJ, ROUTER), "quote")
        self.assertEqual(dtcc.direct_reason("named", PROJ, ROUTER), "named")
        self.assertEqual(dtcc.direct_reason("mine(quote)", PROJ, ROUTER), "quote")
        self.assertEqual(dtcc.direct_reason("mine(named)", PROJ, ROUTER), "named")

    def test_默认给路由的不算直达(self):
        self.assertEqual(dtcc.direct_reason("default→main", ROUTER, ROUTER), "")
        self.assertEqual(dtcc.direct_reason("mine(default→main)", ROUTER, ROUTER), "")

    def test_引用的就是路由自己的播报也不算(self):
        self.assertEqual(dtcc.direct_reason("mine(quote)", ROUTER, ROUTER), "")

    def test_没目标不算(self):
        self.assertEqual(dtcc.direct_reason("quote", "", ROUTER), "")

    def _note(self, why, sid):
        rows = []
        saved = (route.log_direct, route.now_iso, dtcc.logline)
        route.log_direct = lambda rs, path=None: rows.extend(rs)
        route.now_iso = lambda: "2026-11-12T15:00:00+08:00"
        dtcc.logline = lambda *a, **k: None
        try:
            src = dtcc.FakeRoutes(sessions={
                ROUTER: {"pane": "%1", "tmux": "OS:hub.0", "window_name": "✳ hub"},
                PROJ: {"pane": "%7", "tmux": "OS:proj.0", "window_name": "proj", "project": "项目A"},
            })
            dtcc.note_direct({"cc": {"main_window": "OS:hub"}},
                             {"id": "msg-9", "text": "这个先停"}, sid, why, src)
        finally:
            route.log_direct, route.now_iso, dtcc.logline = saved
        return rows

    def test_引用直达记一行(self):
        rows = self._note("quote", PROJ)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["reason"], rows[0]["to"], rows[0]["to_pane"], rows[0]["evidence"],
                          rows[0]["source"]), ("quote", PROJ, "%7", "msg-9", "phone"))

    def test_默认给路由不记(self):
        self.assertEqual(self._note("default→main", ROUTER), [])
        self.assertEqual(self._note("mine(quote)", ROUTER), [])


if __name__ == "__main__":
    unittest.main()


class SameWindow(unittest.TestCase):
    """Stop hook 每轮都走：不是路由窗口的会话，用一次 tmux 就排除，不查整张会话表。"""

    def test_状态符号不算窗口名(self):
        self.assertTrue(dw.same_window("OS:✳ hub", "OS:hub"))

    def test_别的窗口(self):
        self.assertFalse(dw.same_window("OS:✳ journal", "OS:hub"))
        self.assertFalse(dw.same_window("work:hub", "OS:hub"))

    def test_没配不算(self):
        self.assertFalse(dw.same_window("OS:hub", ""))
