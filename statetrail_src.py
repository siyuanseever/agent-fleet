"""会话状态的唯一来源：`statetrail-tmux list --json`。

2026-11-11 起 fleet / console / fleet_up / watch_done 都从这里读，和 route.py 同一份。
以前它们读 claude-tmux-sessions 的 `~/.claude/tmux-claude-status.json`，route.py 读 statetrail，
两份各自判状态：11-09 同一个会话一边报「在跑」、一边报「静默 6 小时」。

statetrail 的 `state`（和 tmux 状态栏圆点同一份，字段见 statetrail 的 tmux/README「给别的程序用」）：

| state | 意思 | 能不能往里敲字 |
|---|---|---|
| `run`  | 在跑 | 不能：会打断它（`--force` 才插队） |
| `wait` | 停在权限框 / 选择框上等人点头 | **绝不能**：敲的字会被当成按键，替人点了头。`--force` 也不放 |
| `done` | 做完了，人还没看 | 可以 |
| `read` | 做完了，人看过 | 可以 |

判据（`parse_list` / `fleet_state` / `typing_guard`）是纯函数；IO 只在 `TrailSource` 里，
测试用 `FakeTrail`。
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess

STATETRAIL = "statetrail-tmux"

# statetrail state → fleet 会话表里的 state。fleet 下游一直用 idle/busy/blocked 这三个词。
FLEET_STATE = {"run": "busy", "wait": "blocked", "done": "idle", "read": "idle"}


def _epoch(iso) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def parse_list(items, pane_index=None) -> dict:
    """`statetrail-tmux list --json` 的输出 → `{pane: 记录}`。**纯函数。**

    记录字段：pane / session / window（窗口序号，字符串）/ window_name / pane_index / cwd /
    state（statetrail 原样）/ since（进入这个状态的 epoch 秒，读不出是 None）/ sid / mate / config_dir。

    `pane_index`：`{pane: 格内序号}`。statetrail 不给这个，坐标 `会话:窗口.格` 要用，
    由 IO 那边一次 `tmux list-panes` 补；没有就空串。
    没有 sid 的条目跳过 —— 没 sid 就对不上会话。
    """
    pane_index = pane_index or {}
    out = {}
    for x in items if isinstance(items, list) else []:
        if not isinstance(x, dict):
            continue
        pane, sid = (x.get("pane") or "").strip(), (x.get("sid") or "").strip()
        if not pane or not sid:
            continue
        w = x.get("window") if isinstance(x.get("window"), dict) else {}
        out[pane] = {
            "pane": pane,
            "session": x.get("session") or "",
            "window": "" if w.get("index") is None else str(w.get("index")),
            "window_name": (w.get("name") or "").strip(),
            "pane_index": str(pane_index.get(pane, "")),
            "cwd": x.get("cwd") or "",
            "state": x.get("state") or "",
            "since": _epoch(x.get("state_since")),
            "sid": sid,
            "mate": bool(x.get("mate")),
            "config_dir": x.get("config_dir") or "",
        }
    return out


def fleet_state(state: str) -> str:
    """statetrail state → fleet 的 idle/busy/blocked。认不出的原样返回（下游当未知处理）。"""
    return FLEET_STATE.get(state, state or "?")


def typing_guard(rec: dict, force: bool = False):
    """能不能往这个会话的输入框敲字。返回 `(能, 状态词, 原因)`。**纯函数。**

    `blocked`（statetrail 的 wait）**`force` 也不放**：停在权限框上时敲字等于替人点头，
    这是红线不是体验。比 tmux_probe 抓屏认选择框（awaiting_choice）更早拦 ——
    抓屏那道还留着，管 statetrail 没认出来的选择框。
    """
    st = rec.get("state")
    if st == "blocked":
        return False, "blocked", ("它停在权限框 / 选择框上等人点头，现在敲字会被当成按键、替人做了决定；"
                                  "去那个窗格自己处理，--force 也不放")
    if st == "busy" and not force:
        return False, "busy", "它正在跑，现在打字会打断它；真要插队加 --force"
    return True, st or "", ""


class TrailSource:
    """真实现：问 statetrail-tmux，再一次 tmux list-panes 补格内序号。
    任何一步失败都返回空 —— 下游按「状态未知」处理（fleet 靠 sidecar 的 last_seen 认回来），
    不当成会话全关了。"""

    def __init__(self, timeout: float = 20):
        self.timeout = timeout

    def panes(self) -> dict:
        try:
            r = subprocess.run([STATETRAIL, "list", "--json", "--turns", "0"],
                               capture_output=True, text=True, timeout=self.timeout)
            items = json.loads(r.stdout or "[]") if r.returncode == 0 else []
        except (OSError, subprocess.SubprocessError, ValueError):
            items = []
        idx = {}
        try:
            r = subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_id}\t#{pane_index}"],
                               capture_output=True, text=True, timeout=5)
            for line in (r.stdout or "").splitlines():
                p, _, i = line.partition("\t")
                idx[p] = i
        except (OSError, subprocess.SubprocessError):
            pass
        return parse_list(items, idx)


class FakeTrail:
    """假实现：喂 statetrail list 的原始条目（或已经 parse 过的字典）。"""

    def __init__(self, items=None, pane_index=None):
        self.items, self.pane_index = items or [], pane_index or {}

    def panes(self) -> dict:
        return parse_list(self.items, self.pane_index)


_SOURCE = TrailSource()


def panes() -> dict:
    return _SOURCE.panes()
