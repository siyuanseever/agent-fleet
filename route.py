# -*- coding: utf-8 -*-
"""路由记录与回信。真相是 data/route.ndjson，一行一条，只追加。

三个子命令：

  add '<json>'                 路由会话记一次判断。补上 id / ts / router，打印 id。
  reply <id> done|blocked "一句话"
                               被转到的会话办完（或卡住）回一句。先写进 route.ndjson，
                               再尽量用 fleet.py wake 叫一下路由会话；路由在忙就不叫，
                               它下次 open 会看到。
  open [--json]                还没回信的 forward：对方现在什么状态、转出去多久了。

为什么回信要落文件、叫醒只是顺带：fleet.py wake 遇到对方在跑会拒绝（打字会打断它），
而路由会话大部分时间都在跑。只靠叫醒，回信会丢。

路由会话是谁不在这里写死：读 config.json 的 cc.main_window（如 OS:xiaoding），
再用 statetrail-tmux list 对到 sid。换了路由会话只改那一处。
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROUTES = pathlib.Path(os.environ.get("ROUTE_FILE", HERE / "data" / "route.ndjson"))
CONFIG = HERE / "config.json"
REPLY_KINDS = ("done", "blocked")


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load(path=ROUTES):
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def append(rec, path=ROUTES):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def rid_of(r):
    """id 字段是 11-10 才加的；之前的行用 ts 当 id。"""
    return r.get("id") or r.get("ts", "")


def new_id(ts, existing):
    base = "r-" + ts[2:4] + ts[5:7] + ts[8:10] + "-" + ts[11:13] + ts[14:16]
    rid, n = base, 1
    while rid in existing:
        n += 1
        rid = "%s-%d" % (base, n)
    return rid


# ---------------------------------------------------------------- 直达行
#
# 有两类消息不经路由会话判断，直接到了某个会话手里：
#   - 手机指令引用了某条播报（quote）、或文字里点了会话标签（named）—— dtcc 直接派；
#   - 同事的回信被「在等回信」的登记认领（awaiting）—— dtwatch for-session 直接投。
# 路由会话看不到这些，所以也记一行 decision=direct，格式跟判断行同一份。
# direct 不进 open_items：它不是转出，没人欠回信。

DIRECT_REASONS = ("quote", "named", "awaiting")


def direct_rec(source, item, to, reason, evidence, ts, to_pane="", to_label=""):
    """拼一行直达记录。**纯函数**；id 由 log_direct 落盘时补。"""
    if reason not in DIRECT_REASONS:
        raise ValueError("direct 的 reason 只能是 %s：%r" % ("/".join(DIRECT_REASONS), reason))
    return {"ts": ts, "router": "", "source": source,
            "item": " ".join(str(item or "").split())[:80],
            "decision": "direct", "to": to, "to_pane": to_pane or "", "to_label": to_label or "",
            "reason": reason, "evidence": evidence or ""}


def log_direct(rows, path=None):
    """把直达行追加进 route.ndjson，逐行补 id。IO。"""
    if not rows:
        return []
    path = pathlib.Path(path) if path else ROUTES
    existing = {rid_of(r) for r in load(path)}
    out = []
    for r in rows:
        r = dict(r)
        r["id"] = new_id(r["ts"], existing)
        existing.add(r["id"])
        append(r, path)
        out.append(r)
    return out


# ---------------------------------------------------------------- 纯判断（有测试）

def open_items(routes, nodes):
    """没回信的 forward，配上对方此刻的状态。

    对方按 sid 找；sid 不在了再按 to_pane 找 —— 同一个窗格里会话换了 id
    （/clear、压缩后续上）很常见，2026-11-10 journal 窗格 %4 就从 1dfc 换成了 6e44。
    这时标 moved，不当成关掉了。
    """
    replied = {r.get("re") for r in routes if r.get("re")}
    by_sid = {n.get("sid"): n for n in nodes}
    by_pane = {n.get("pane"): n for n in nodes if n.get("pane")}
    out = []
    for r in routes:
        if r.get("re") or r.get("decision") != "forward":
            continue
        rid = rid_of(r)
        if rid in replied:
            continue
        n = by_sid.get(r.get("to"))
        where = "same"
        if n is None:
            n = by_pane.get(r.get("to_pane"))
            where = "moved" if n else "gone"
        out.append({
            "id": rid, "ts": r.get("ts"), "item": r.get("item"),
            "to": r.get("to"), "to_label": r.get("to_label"), "to_pane": r.get("to_pane"),
            "where": where,
            "now_sid": n.get("sid") if n else None,
            "state": n.get("state") if n else None,
            "chapter": n.get("chapter") if n else None,
        })
    return out


def _bare(name):
    """窗口名前面常挂着状态符号（「✳ xiaoding」），比较前去掉。"""
    name = (name or "").strip()
    while name and not (name[0].isalnum() or name[0] in "_-"):
        name = name[1:].lstrip()
    return name


def router_pane(nodes, main_window):
    """statetrail 的 window 是 {"index", "name"}，name 带状态符号。"""
    sess, _, name = (main_window or "").partition(":")
    if not name:
        return None
    for n in nodes:
        w = n.get("window") or {}
        wname = w.get("name") if isinstance(w, dict) else str(w)
        if n.get("session") == sess and _bare(wname) == _bare(name) and not n.get("mate"):
            return n
    return None


# ---------------------------------------------------------------- IO

def nodes():
    try:
        out = subprocess.run(["statetrail-tmux", "list", "--json", "--turns", "0"],
                             capture_output=True, text=True, timeout=30).stdout
        return json.loads(out)
    except Exception:
        return []


def main_window():
    try:
        return (json.loads(CONFIG.read_text(encoding="utf-8")).get("cc") or {}).get("main_window", "")
    except (OSError, ValueError):
        return ""


def my_sid(ns):
    pane = os.environ.get("TMUX_PANE", "")
    for n in ns:
        if pane and n.get("pane") == pane:
            return n.get("sid")
    return None


def cmd_add(a):
    rec = json.loads(a.json)
    routes = load()
    ns = nodes()
    rec.setdefault("ts", now_iso())
    rec["id"] = new_id(rec["ts"], {rid_of(r) for r in routes})
    if not rec.get("router"):
        rec["router"] = my_sid(ns) or ""
    append(rec)
    print(rec["id"])
    return 0


def cmd_reply(a):
    routes = load()
    target = [r for r in routes if rid_of(r) == a.id and not r.get("re")]
    if not target:
        print(json.dumps({"ok": False, "error": "route.ndjson 里没有这个 id：%s" % a.id}, ensure_ascii=False))
        return 1
    ns = nodes()
    rec = {"ts": now_iso(), "re": a.id, "decision": a.kind, "by": my_sid(ns) or a.by or "",
           "text": a.text}
    append(rec)
    res = {"ok": True, "logged": True, "woke_router": False}
    rp = router_pane(ns, main_window())
    if rp and rp.get("sid") != rec["by"] and not a.no_wake:
        task = "【回信 %s · %s】%s" % (a.id, "办完" if a.kind == "done" else "卡住", a.text.replace("\n", " "))
        p = subprocess.run([sys.executable, str(HERE / "fleet.py"), "wake", rp["sid"][:8], "--task", task],
                           capture_output=True, text=True, timeout=60)
        res["woke_router"] = p.returncode == 0
        if p.returncode != 0:
            res["note"] = "路由会话在忙，没叫它；回信已记在 route.ndjson，它查 open 时会看到"
    print(json.dumps(res, ensure_ascii=False))
    return 0


def cmd_open(a):
    items = open_items(load(), nodes())
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0
    if not items:
        print("没有待回信的转出")
    for it in items:
        tag = {"same": "", "moved": "（窗格里换了会话 %s）" % (it["now_sid"] or "")[:8],
               "gone": "（会话已关）"}[it["where"]]
        print("%s  %s  → %s %s %s%s  %s" % (it["id"], (it["ts"] or "")[:16], it["to_label"], it["to_pane"],
                                         it["state"] or "-", tag, it["item"]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="路由记录与回信")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add", help="记一次路由判断，打印 id")
    p.add_argument("json")
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("reply", help="被转到的会话回一句")
    p.add_argument("id")
    p.add_argument("kind", choices=REPLY_KINDS)
    p.add_argument("text")
    p.add_argument("--by", default="", help="认不出自己的 sid 时手填")
    p.add_argument("--no-wake", action="store_true", help="只记文件，不叫路由会话")
    p.set_defaults(fn=cmd_reply)
    p = sub.add_parser("open", help="还没回信的转出")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_open)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
