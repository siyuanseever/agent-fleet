# -*- coding: utf-8 -*-
"""tidy.py 的判据。全部造数据，不碰 data/，不读真实记忆。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tidy  # noqa: E402


class Links(unittest.TestCase):
    def test_按文件名或name都算找得到_下划线连字符同名(self):
        files = {"a_b.md": "---\nname: x-y\n---\n", "c.md": "见 [[a-b]] 和 [[x_y]] 和 (a_b.md)"}
        self.assertEqual(tidy.broken_links(files), [])

    def test_找不到的报出来(self):
        files = {"c.md": "见 [[gone]] 和 [g](gone.md)"}
        self.assertEqual(tidy.broken_links(files), [("c.md", "[[gone]]"), ("c.md", "(gone.md)")])

    def test_正则和带空格的不当链接(self):
        # 11-12 实查：collab_two_sessions 里的 [[0-9a-f]] 是正则；[[找不到 ≠ 不存在]] 是一句话
        files = {"c.md": "匹配 [[0-9a-f]]{8}，另见 [[找不到 ≠ 不存在]]"}
        self.assertEqual(tidy.broken_links(files), [])


class Index(unittest.TestCase):
    def test_索引指向不存在和没进索引(self):
        files = {"MEMORY.md": "- [a](a.md)\n- [gone](gone.md)", "a.md": "", "b.md": "", "_旧索引.md": ""}
        self.assertEqual(tidy.index_problems(files), (["gone.md"], ["b.md"]))

    def test_没有索引就不判(self):
        self.assertEqual(tidy.index_problems({"a.md": ""}), ([], []))


class Claims(unittest.TestCase):
    def test_只挑自称做了的近期回信(self):
        routes = [{"id": "r-1", "decision": "forward", "to_label": "news:fix"},
                  {"ts": "2026-11-12T10:00:00+08:00", "re": "r-1", "text": "已提交并推到 test"},
                  {"ts": "2026-11-12T10:00:00+08:00", "re": "r-1", "text": "看过了，不用改"},
                  {"ts": "2026-11-01T10:00:00+08:00", "re": "r-1", "text": "已推"}]
        out = tidy.claims_to_check(routes, "2026-11-05")
        self.assertEqual([c["text"] for c in out], ["已提交并推到 test"])
        self.assertEqual(out[0]["to_label"], "news:fix")


if __name__ == "__main__":
    unittest.main()
