#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_parity.py —— Python 引擎 与 JS 引擎 的一致性对拍。

为什么这个测试比别的测试都重要：
    项目有两套实现（CLI 的 `scripts/question_doctor.py` 和 Web 的 `web/engine.js`），
    它们共用同一份 `references/rules.json`，但**代码是分别写的**。
    一旦两边口径漂移，用户会遇到「网页说 90 分、命令行说 60 分」——
    那比没有工具更糟：他会开始怀疑所有分数。

    所以判据必须被自动对拍，而不是靠人工比对截图。

用法：
    python tests/test_parity.py            # 需要本机有 node
    python tests/test_parity.py -v

若本机没有 node，本测试会**跳过并明确说明**（而不是假装通过）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_SCRIPT = ROOT / "scripts" / "question_doctor.py"
JS_CLI = ROOT / "tests" / "engine_cli.js"
NODE = shutil.which("node")

# 对拍语料：覆盖「差的 / 好的 / 边界」三类，不只用漂亮例子
CASES = [
    "我的代码报错了，大佬们帮我看看",
    "",                                                    # 空（跳过，见下）
    "+1",
    "顶",
    "🙂🙂",
    "报错了",
    "请问这个怎么解决？我试过了没结果",
    (
        "【背景】Windows 11 / Python 3.13，我在做课程资料抓取，目标是把 31 个页面转成 Markdown。\n"
        "【现象】13 篇正常，18 篇输出 0 字符，浏览器打开正文是正常的。\n"
        "【已尝试】试过换编码 → 无异常，已排除；试过核对选择器 → article 确实存在，已排除。\n"
        "【卡点】我怀疑是 drop_depth 计数器一旦涨上去就没回到 0。\n"
        "【最小复现】\n```python\ndepth += 1\n```\n"
        "【我的候选改法】换成显式标签栈。\n"
        "【想请教】嵌套同名标签有没有更稳的判据？\n"
    ),
    "我在做 X，用的是 Y，已经试过 A，结果报错。卡在 B，想请教有没有别的思路。",
    "<!-- type: feedback -->\n汇总一下上次讨论的结论：三条清单，可以直接照着做。",
]


@unittest.skipUnless(NODE, "本机没有 node —— 无法对拍 JS 引擎（跳过，不算通过）")
class TestParity(unittest.TestCase):
    def _py(self, text: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write(text)
            p = f.name
        try:
            out = subprocess.run(
                [sys.executable, str(PY_SCRIPT), "--json", p],
                capture_output=True, text=True, encoding="utf-8",
            )
            # 退出码 1 = 不通过，这是正常结果，JSON 仍然有效
            return json.loads(out.stdout)
        finally:
            Path(p).unlink(missing_ok=True)

    def _js(self, text: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write(text)
            p = f.name
        try:
            out = subprocess.run(
                [NODE, str(JS_CLI), p],
                capture_output=True, text=True, encoding="utf-8",
            )
            if out.returncode != 0:
                self.fail(f"node 引擎执行失败：{out.stderr}")
            return json.loads(out.stdout)
        finally:
            Path(p).unlink(missing_ok=True)

    def test_scores_match(self):
        for i, case in enumerate(CASES):
            if not case.strip():
                continue          # 空输入两边都是退出码 2，不产出 JSON
            with self.subTest(case=i, preview=case[:26]):
                a, b = self._py(case), self._js(case)
                self.assertEqual(a["type"], b["type"], "类型识别不一致")
                self.assertAlmostEqual(float(a["score"]), float(b["score"]), places=1,
                                       msg="分数不一致 —— Python 与 JS 口径漂移了")
                self.assertEqual(a["hard_missing"], b["hard_missing"], "硬门槛缺口不一致")
                self.assertEqual(a["missing"], b["missing"], "缺失要素不一致")
                self.assertEqual(a["penalty"], b["penalty"], "负面扣分不一致")
                self.assertEqual(a["medium"]["chars"], b["medium"]["chars"], "字数不一致")
                self.assertEqual(a["passed"], b["passed"], "结论不一致")

    def test_rules_json_is_shared(self):
        """两边必须读同一份规则，而不是各自内嵌一份副本。"""
        rules = json.loads((ROOT / "references" / "rules.json").read_text(encoding="utf-8"))
        js = (ROOT / "web" / "rules.js").read_text(encoding="utf-8")
        # web/rules.js 是构建产物：应当完整包含 rules.json 的全部要素 id
        for t, spec in rules["types"].items():
            for e in spec["elements"]:
                self.assertIn(e["id"], js, f"web/rules.js 缺少 {t}.{e['id']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
