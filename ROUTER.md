# 路由会话 · 架构说明

> 一句话：手机发来的指令先落到一个固定的 Claude 会话（路由会话）。它查清这件事归哪个会话，
> 转过去，记一行；对方办完回一句，也记一行。所有判断和回信都在一份文件里，
> 换一个会话来当路由也能接着干。
>
> 总纲见 [SYSTEM.md](SYSTEM.md)，手机遥控见 [DTCC.md](DTCC.md)。这份只讲「路由」这一层。

---

## 1. 一条指令走一圈

```
手机自聊 ──dtcc──▶ 路由会话（config.json 的 cc.main_window）
                     │
                     ├─ 看：statetrail-tmux search / list --json，再读对方的会话记录
                     ├─ 判：skip 已有人在做 / forward 转过去 / ask 交给人定 / manual 送不进
                     ├─ 记：route.py add  ──▶ data/route.ndjson（得到一个 id）
                     └─ 送：同账号 SendMessage；跨账号 fleet.py wake（tmux）
                                   │
                          目标会话办事
                                   │
                     route.py reply <id> done|blocked "一句话"
                       ├─ 写进 data/route.ndjson（这是真相）
                       └─ 顺带 fleet.py wake 叫一下路由会话（它在忙就不叫）
                                   │
              路由会话 route.py open：还有哪些转出没回信、对方现在什么状态
                                   │
              用量面板「连接」页把这份文件画成图（另一个仓库，只读）
```

## 2. 部件

| 环节 | 用什么 | 在哪 |
|---|---|---|
| 入口 | `dtcc.py`：没引用播报、没点名的手机指令送到 `cc.main_window` | 本仓库 |
| 看 | `statetrail-tmux list --json`（谁在、什么状态、最近几轮）、`search --json`（这事在哪说过） | statetrail（公开仓库） |
| 判 | skill `route-to-session`：四步只读查证，再决定 | `~/.claude/skills/route-to-session/` |
| 送 · 同账号 | Claude Code 自带 `SendMessage`，进对方信箱，不打断 | 内置 |
| 送 · 跨账号 | `fleet.py wake <sid> --task "<一行>"`，按 pane id 敲进去，有护栏 | 本仓库 |
| 记 / 收 / 查 | `route.py add / reply / open` | 本仓库 |
| 看板 | 用量面板「连接」页读 `route.ndjson` + `events.ndjson` + statetrail | usage-monitor |

## 3. 数据：`data/route.ndjson`

一行一条，只追加，不改旧行。判错了也照记，后面补一行更正。

**判断行**（路由会话写，`route.py add` 补 `id` / `ts` / `router`）：

```json
{"id":"r-261110-1813","ts":"2026-11-10T18:13:00+08:00","router":"<路由 sid>",
 "source":"phone|user|session:<sid>","item":"一句话说是什么事",
 "checked":["<查过的 sid>"],"decision":"skip|forward|ask|manual",
 "to":"<目标 sid>","to_pane":"%1","to_label":"窗口名",
 "reason":"为什么是它","evidence":"凭什么这么判"}
```

**回信行**（目标会话写，`route.py reply`）：

```json
{"ts":"…","re":"r-261110-1813","decision":"done|blocked","by":"<回信的 sid>","text":"一句话"}
```

- 2026-11-10 之前的判断行没有 `id`，用 `ts` 当 id。
- 「还没回信」= 有 `decision: forward` 的判断行，没有 `re` 指向它的回信行。
- 对方的 sid 找不到时按 `to_pane` 找：同一窗格里会话换 id（`/clear`、压缩后续上）很常见，
  这不算关掉。真找不到才算关掉。

## 4. 几条规矩，和它们为什么在

- **回信以文件为准，叫醒只是顺带。** `fleet.py wake` 遇到对方在跑会拒绝，路由会话大部分时间在跑。
  只靠叫醒，回信会丢。
- **路由会话是谁只写在一处**：`config.json` 的 `cc.main_window`。路由的判断规则写在 skill 里，
  路由的记忆写在 `route.ndjson` 里，都不靠某个会话的上下文。会话压缩了、换了，照样接得上。
- **跨账号投递只在对方 `read` / `done` 时发。** `run` 就等；`wait`（停在权限框上）绝不发，
  敲进去的字会被当成对权限框的回答。不加 `--force`。
- **正文一行。** 换行会提前回车。开头写明从哪个会话来，对方看不到发件人。
- **转之前先读对方的会话记录**，读到它对这件事的结论再判。只看窗口最后几行会误判。
- **转话里的事实也要核。** 路径、时间写错了，对方会照着错的去找。

## 5. 还没做到的

- 样本少：到 2026-11-10 一共 7 次判断，判错过 1 次（凭窗口名认会话）。
- 看板还不会把回信行挂到原来那条线上（已转给面板的维护会话）。
- 判断规则在 skill 里，不在本仓库；要抽成框架时，skill、本仓库的投递和记录、statetrail
  三样要一起打包。
- 路由会话只有一个。它的窗口关了，手机指令就没人接。
