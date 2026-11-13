# -*- coding: utf-8 -*-
"""定期整理的第一步：只读体检，出一份清单给人看，不改任何东西。

查三样：
  1. 记忆里的断链：[[name]] 或 (xxx.md) 指向不存在的记忆。
  2. MEMORY.md 索引行指向不存在的文件；以及没进索引的记忆文件。
  3. 回信抽查：最近 N 天的回信里自称「已做」的（已提交/已推/已告诉/已删……），
     列出来让路由去对方记录或仓库里核。2026-11-11、11-12 各有一条回信说做了其实没做全。

为什么只出清单不动手：改记忆要判断（过时？还是只是旧出处？），这一步留给会话和人。
来由见 ROUTER.md「还没做到的 · 没有离线整理」。

用法：
  python3 tidy.py                 # 打印清单（Markdown）
  python3 tidy.py --days 7 --out data/tidy/2026-11-12.md
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
MEM_ROOT = pathlib.Path(os.environ.get("TIDY_MEM_ROOT", pathlib.Path.home() / ".claude" / "projects"))
ROUTES = pathlib.Path(os.environ.get("ROUTE_FILE", HERE / "data" / "route.ndjson"))

WIKI = re.compile(r"\[\[([^\]\n]+)\]\]")
MDLINK = re.compile(r"\]\(([^)\s]+\.md)\)")
CLAIM = re.compile(r"已(经)?(提交|推|推送|告诉|讲|发|删|改好|部署|合并|上线)|给了(用户|他)|commit|pushed", re.I)
SKIP_FILES = {"MEMORY.md"}


# ---------------------------------------------------------------- 纯判断（有测试）

def names_of(files):
    """一个记忆能被叫到的名字：文件名去 .md，加 frontmatter 里的 name。下划线和连字符视为同一个。"""
    out = set()
    for fn, text in files.items():
        out.add(_norm(fn[:-3] if fn.endswith(".md") else fn))
        m = re.search(r"^name:\s*(.+)$", text, re.M)
        if m:
            out.add(_norm(m.group(1).strip().strip("\"'")))
    return out


def _norm(s):
    return s.strip().lower().replace("_", "-")


def broken_links(files):
    """[(文件, 链接)]。只看像记忆名的 [[…]]：含空格、正则符号的不算（[[0-9a-f]] 是正则不是链接）。"""
    known = names_of(files)
    out = []
    for fn, text in sorted(files.items()):
        for m in WIKI.finditer(text):
            name = m.group(1).split("|")[0].strip()
            if not re.fullmatch(r"[\w\-一-鿿.]+", name) or re.fullmatch(r"(\w-\w)+", name):
                continue  # 后一个是 [[0-9a-f]] 这类字符区间
            if _norm(name) not in known:
                out.append((fn, "[[%s]]" % name))
        for m in MDLINK.finditer(text):
            target = m.group(1)
            if "/" in target or target.startswith("http"):
                continue
            if target not in files:
                out.append((fn, "(%s)" % target))
    return out


def index_problems(files):
    """(索引里指向不存在的文件, 没进索引的文件)。没有 MEMORY.md 的目录返回两个空表。"""
    idx = files.get("MEMORY.md")
    if idx is None:
        return [], []
    linked = set(MDLINK.findall(idx))
    missing = sorted(t for t in linked if "/" not in t and t not in files)
    orphans = sorted(fn for fn in files if fn.endswith(".md") and fn not in SKIP_FILES
                     and not fn.startswith("_") and fn not in linked)
    return missing, orphans


def claims_to_check(routes, since):
    """最近的回信里自称做了某事的。since 是 ISO 字符串，按字符串比较（同一时区写的）。"""
    by_id = {r.get("id") or r.get("ts"): r for r in routes if not r.get("re")}
    out = []
    for r in routes:
        if not r.get("re") or (r.get("ts") or "") < since:
            continue
        if CLAIM.search(r.get("text") or ""):
            fwd = by_id.get(r["re"], {})
            out.append({"re": r["re"], "ts": r.get("ts"), "by": r.get("by"),
                        "to_label": fwd.get("to_label"), "text": r.get("text")})
    return out


# ---------------------------------------------------------------- IO

def load_dir(d):
    files = {}
    for p in d.glob("*.md"):
        try:
            files[p.name] = p.read_text(encoding="utf-8")
        except OSError:
            pass
    return files


def load_routes():
    out = []
    try:
        for line in ROUTES.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def report(days):
    since = (dt.datetime.now().astimezone() - dt.timedelta(days=days)).isoformat(timespec="seconds")
    lines = ["# 整理清单 · %s" % dt.date.today().isoformat(), "",
             "只读体检的结果，没有改任何东西。每一条要不要改，由会话判断、用户点头。", ""]
    dirs = sorted(p for p in MEM_ROOT.glob("*/memory") if p.is_dir() and not p.is_symlink())
    n_broken = n_missing = n_orphan = 0
    sec = []
    for d in dirs:
        files = load_dir(d)
        if not files:
            continue
        b = broken_links(files)
        miss, orph = index_problems(files)
        n_broken += len(b); n_missing += len(miss); n_orphan += len(orph)
        if not (b or miss or orph):
            continue
        sec.append("### %s" % d.parent.name)
        sec += ["- 断链：%s 里的 %s" % (fn, l) for fn, l in b]
        sec += ["- 索引指向不存在：%s" % t for t in miss]
        if orph:
            sec.append("- 没进索引（%d 个）：%s" % (len(orph), "、".join(orph[:15]) + ("……" if len(orph) > 15 else "")))
        sec.append("")
    cl = claims_to_check(load_routes(), since)
    lines += ["## 总数", "",
              "- 记忆断链 %d 条，索引指向不存在 %d 条，没进索引 %d 个" % (n_broken, n_missing, n_orphan),
              "- 最近 %d 天自称「已做」的回信 %d 条，要去对方记录或仓库核" % (days, len(cl)), ""]
    lines += ["## 回信抽查", ""]
    lines += ["- %s → %s：%s" % (c["re"], c["to_label"] or (c["by"] or "")[:8], c["text"]) for c in cl] or ["- 没有"]
    lines += ["", "## 记忆", ""] + (sec or ["- 没有问题", ""])
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="定期整理：只读体检，出清单")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    text = report(a.days)
    if a.out:
        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
