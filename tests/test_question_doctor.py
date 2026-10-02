#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
question-doctor 的测试。零依赖，直接用标准库 unittest：

    python -m unittest discover -s tests -v
    # 或
    python tests/test_question_doctor.py

测试里**故意包含反例**（bad case）——上一版工具最容易犯的错就是「只测好例子」，
然后在真实使用中被一条「@某人」的短消息骗过。
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import question_doctor as qd  # noqa: E402

RULES = qd.load_rules()

BAD = "我的代码报错了，大佬们帮我看看"

GOOD = """【背景】Windows 11 / Python 3.13，我在做课程资料抓取，目标是把 31 个页面转成 Markdown。
【现象】13 篇正常，18 篇输出 0 字符，浏览器打开正文是正常的。
【已尝试】试过换编码 → 无异常，已排除；试过核对选择器 → article 确实存在，已排除。
【卡点】我怀疑是 drop_depth 计数器一旦涨上去就没回到 0。
【最小复现】
```python
depth += 1
```
【我的候选改法】换成显式标签栈。
【想请教】嵌套同名标签有没有更稳的判据？


"""


class TestTypeDetection(unittest.TestCase):
    def test_explicit_type_wins(self):
        text = "这是一段完全中性的文字\n<!-- type: question -->"
        t, why = qd.detect_type(text, RULES)
        self.assertEqual(t, "question")
        self.assertIn("显式", why)

    def test_heuristic_question(self):
        for s in ["请问这个怎么解决？", "我的代码出错了", "跑不通了", "这个到底怎么回事"]:
            t, _ = qd.detect_type(s, RULES)
            self.assertEqual(t, "question", s)

    def test_default_is_last_type(self):
        t, why = qd.detect_type("今天天气不错", RULES)
        self.assertEqual(t, "share")
        self.assertIn("默认", why)

    def test_every_type_has_heuristic(self):
        """回归测试：曾因 HEURISTIC 字典缺 'share' 键而 KeyError。

        那类 bug 只在"输入没命中任何关键词"时出现——也就是最普通的输入上。
        """
        for t, spec in RULES["types"].items():
            self.assertIn("heuristic", spec, f"类型 {t} 缺少 heuristic")
            self.assertTrue(spec["heuristic"], f"类型 {t} 的 heuristic 是空的")
            _ = qd.detect_type("随便一段话 " + " ".join(spec["heuristic"]), RULES)

    def test_heuristic_lives_in_rules_not_code(self):
        """类型关键词必须在规则表里——否则"改规则不用动代码"是句空话。

        之前启发式写死在 py/js 两处代码里，用户改了 rules.json 却发现
        自己加的触发词不生效。这个测试钉住"单一事实来源"。
        """
        src_py = (ROOT / "scripts" / "question_doctor.py").read_text(encoding="utf-8")
        src_js = (ROOT / "web" / "engine.js").read_text(encoding="utf-8")
        for t, spec in RULES["types"].items():
            probe = spec["heuristic"][0]
            # 关键词本身不应再出现在代码里（注释除外，这里只做粗筛）
            for src, name in ((src_py, "python"), (src_js, "js")):
                code = "\n".join(ln for ln in src.splitlines()
                                 if not ln.strip().startswith(("#", "//", "*")))
                self.assertNotIn(f'"{probe}"', code,
                                 f"{name} 里仍硬编码了启发式关键词 {probe}")


class TestElements(unittest.TestCase):
    def test_bad_question_scores_zero_and_fails(self):
        r = qd.diagnose(BAD, RULES)
        self.assertEqual(r["score"], 0)
        self.assertFalse(r["passed"])
        self.assertIn("上下文", r["missing"])

    def test_bad_question_flags_shrug_signal(self):
        r = qd.diagnose(BAD, RULES)
        ids = [n["id"] for n in r["negatives"]]
        self.assertIn("甩手式求助", ids)

    def test_good_question_scores_high_and_passes(self):
        r = qd.diagnose(GOOD, RULES, forced_type="question")
        self.assertGreaterEqual(r["score"], 70)
        self.assertTrue(r["passed"])
        self.assertTrue(r["hard_ok"])

    def test_partial_credit_for_tried_without_result(self):
        """「试过了」但没说结果 → 只给一半分，并标记 partial。"""
        text = "背景：Windows 11，我在做 X，目标是 Y。\n我试过换编码。\n卡在编码这一步。"
        r = qd.diagnose(text, RULES, forced_type="question")
        tried = next(d for d in r["elements"] if d["id"] == "已尝试")
        self.assertTrue(tried["hit"])
        self.assertTrue(tried["partial"])
        self.assertEqual(tried["earned"], tried["weight"] * 0.5)
        self.assertIn("已尝试", r["partial"])

    def test_weights_sum_to_100_for_every_type(self):
        """权重必须合计 100——否则评分不可比。"""
        for name, spec in RULES["types"].items():
            total = sum(e["weight"] for e in spec["elements"])
            self.assertEqual(total, 100, f"{name} 权重合计 {total} != 100")

    def test_hard_gates_are_real_element_ids(self):
        for name, spec in RULES["types"].items():
            ids = {e["id"] for e in spec["elements"]}
            for g in spec["hard_gates"]:
                self.assertIn(g, ids, f"{name} 的硬门槛 {g} 不在要素表里")


class TestNegativeSignals(unittest.TestCase):
    def test_pure_emoji_is_caught(self):
        r = qd.diagnose("🙂🙂🙂", RULES, forced_type="question")
        self.assertTrue(any(n["id"] == "纯表情" for n in r["negatives"]))

    def test_water_reply_is_caught(self):
        for s in ["+1", "顶", "同上", "路过"]:
            r = qd.diagnose(s, RULES, forced_type="question")
            self.assertTrue(any(n["id"] == "灌水" for n in r["negatives"]), s)

    def test_bare_error_is_caught(self):
        r = qd.diagnose("报错了", RULES, forced_type="question")
        self.assertTrue(any(n["id"] == "无信息求助" for n in r["negatives"]))

    def test_no_false_positive_on_real_content(self):
        """反例：正文里出现「没有」「不行」不等于灌水/无信息。

        这是上一版踩过的坑——用子串包含判断会误伤真实内容。
        """
        text = ("背景：我在做 X，目标是 Y。已尝试 A → 报错；已排除 B。"
                "卡在 C，目前没有找到合适的方案。我的候选改法是 D。")
        r = qd.diagnose(text, RULES, forced_type="question")
        self.assertEqual(r["negatives"], [], "真实内容被误判为负面信号")


class TestMediumFit(unittest.TestCase):
    def test_short_text_is_ok(self):
        m = qd.check_medium("短消息", RULES)
        self.assertEqual(m["level"], "ok")

    def test_long_text_is_flagged(self):
        m = qd.check_medium("字" * 1200, RULES)
        self.assertEqual(m["level"], "bad")
        self.assertGreater(m["screens"], 1)

    def test_code_block_excluded_from_screen_count(self):
        """代码块不该被算进「占几屏」——群里可折叠，长代码不是主要阅读负担。"""
        short = "看看这个\n```python\n" + "x = 1\n" * 200 + "```\n"
        m = qd.check_medium(short, RULES)
        self.assertLess(m["chars"], 50)


class TestCLI(unittest.TestCase):
    def _run(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "question_doctor.py"), *args],
            capture_output=True, text=True, input=stdin, encoding="utf-8",
        )

    def test_exit_code_1_when_failing(self):
        p = self._run("--quiet", str(ROOT / "examples" / "01-bad-question.md"))
        self.assertEqual(p.returncode, 1)

    def test_exit_code_0_when_passing(self):
        p = self._run("--quiet", str(ROOT / "examples" / "02-good-question.md"))
        self.assertEqual(p.returncode, 0)

    def test_json_output_is_valid(self):
        p = self._run("--json", str(ROOT / "examples" / "02-good-question.md"))
        data = json.loads(p.stdout)
        self.assertEqual(data["tool"], "question-doctor")
        self.assertIn("score", data)

    def test_stdin_works(self):
        p = self._run("-", stdin="请问这个怎么解决？我试过了没结果")
        self.assertIn("提问诊断报告", p.stdout)
        # 这条输入确实是低分的，退出码 1 是**正确行为**（可接进 CI 当门禁）
        self.assertEqual(p.returncode, 1)

    def test_empty_input_returns_2(self):
        p = self._run("-", stdin="   \n  ")
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
