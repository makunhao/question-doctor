#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
question-doctor —— 发到群里之前，先给问题做个体检。

    输入：一段你准备发到群里的文字（提问 / 分享 / 回馈结论）
    输出：一份诊断报告 —— 要素完备度评分 + 缺口清单 + 媒介适配 + 改写建议

用法
----
    # 直接读一个文件
    python question_doctor.py draft.md

    # 从管道读（推荐）
    echo "我的代码报错了" | python question_doctor.py -
    pbpaste | python question_doctor.py -            # macOS
    Get-Clipboard | python question_doctor.py -      # Windows PowerShell
    xclip -o | python question_doctor.py -           # Linux

    # 输出 JSON（给别的程序用）
    python question_doctor.py --json draft.md

    # 手动指定类型（跳过自动识别）
    python question_doctor.py --type question draft.md

设计原则（每条都来自一次真实踩坑，见 references/rules.json 的 inherited_fixes）
------------------------------------------------------------------------------
1. **类型感知** —— 不同类型需要的要素不同。对所有文本套用「提问」门槛，
   会把分享帖误判为不合格，进而诱导作者为了过检查而做无意义的工作（目标被度量劫持）。
2. **显式优先** —— 能读到 <!-- type: question --> 就用它；读不到才退化为启发式。
3. **词组边界，不用子串** —— 「没有」里含「无」字。判断「无回应」不能写成 `"无" in text`，
   本工具所有关键词匹配都走词组/正则，不走子串包含。
4. **部分给分** —— 「说了试过什么」和「说了结果」是两件事，后者才是别人需要的。
   只做到前者给一半分，并明确告诉你差在哪。
5. **零第三方依赖** —— 只有标准库。别人 clone 下来就能跑，不需要 pip install。

License: MIT
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

__version__ = "2.0.0"

# --------------------------------------------------------------------------
# 规则加载：优先读 references/rules.json（便于别人改规则而不用动代码）
# --------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
DEFAULT_RULES_PATH = HERE.parent / "references" / "rules.json"


def load_rules(path: Path | None = None) -> dict:
    """加载规则表。找不到就直接报错——因为静默用默认值会让人以为改规则没生效。"""
    p = path or DEFAULT_RULES_PATH
    if not p.exists():
        raise SystemExit(
            f"[question-doctor] 找不到规则文件：{p}\n"
            f"  · 如果你是从 .skill 包里直接跑的，请确认 references/rules.json 一起被解出来了；\n"
            f"  · 也可以用 --rules <路径> 手动指定。"
        )
    with p.open(encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# 类型识别
# --------------------------------------------------------------------------
# ⚠️ 启发式关键词**不在代码里**，而是在 references/rules.json 的每个类型下（`heuristic`）。
# 之前写死在代码里，结果违反了 README 的承诺（"改规则不用动代码"）——
# 用户改了 rules.json 却发现自己加的触发词不生效，会以为工具坏了。
# 现在两边都从规则表读，一份数据一个来源。

def _type_order(rules: dict) -> list[str]:
    """类型判定优先级：命中的信号数相同时，排在前面的胜出。

    放在规则表里而不是代码里，是为了让"调整优先级"也变成改配置。
    """
    order = rules.get("meta", {}).get("type_detection_order")
    return list(order) if order else list(rules["types"].keys())


def detect_type(text: str, rules: dict) -> tuple[str, str]:
    """返回 (类型, 判定依据说明)。

    优先级：显式元数据 > 关键词启发式 > 默认（规则表里排最后的那个类型）。
    """
    m = re.search(r"<!--\s*type\s*:\s*(question|share|feedback)\s*-->", text)
    if m:
        return m.group(1), "显式声明 <!-- type: ... -->"

    order = _type_order(rules)
    scores = {
        t: sum(1 for p in rules["types"][t].get("heuristic", [])
               if re.search(p, text, re.MULTILINE))
        for t in order
    }
    best = max(order, key=lambda t: scores[t])
    if scores[best] > 0:
        return best, f"关键词启发式（命中 {scores[best]} 个信号）"
    return order[-1], "无信号，默认为最后一种类型"


# --------------------------------------------------------------------------
# 要素检测
# --------------------------------------------------------------------------
def _any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.MULTILINE) for p in patterns)


def check_element(text: str, spec: dict) -> dict:
    """检测单个要素。返回 {'hit': bool, 'partial': bool, 'credit': float}。

    `confirm` 是「加分条件」：主体命中但 confirm 未命中 → 只给一半分。
    这是本工具相对朴素关键词匹配的唯一升级，但它解决的是最实际的问题：
    很多人写了「我试过了」但没写结果，对方读了等于没读。
    """
    hit = _any(text, spec.get("patterns", []))
    partial = False
    credit = 1.0

    if hit and spec.get("confirm"):
        if not _any(text, spec["confirm"]):
            partial = True
            credit = 0.5

    return {"hit": hit, "partial": partial, "credit": credit if hit else 0.0}


def check_negative(text: str, rules: dict) -> list[dict]:
    """负面信号。命中即扣分（红线相关，见 C3：纯表情灌水 → 内容实质 ≤5）。"""
    hits = []
    stripped = text.strip()

    for item in rules["negative"]:
        if _any(text, item["patterns"]):
            hits.append({"id": item["id"], "reason": item["reason"],
                         "penalty": item["penalty"]})
            continue
        # 兜底：整段去空白后只剩 emoji / 符号 → 视为纯表情
        if item["id"] == "纯表情" and stripped:
            core = re.sub(r"[\s\W_]", "", stripped)
            if not core:
                hits.append({"id": item["id"], "reason": item["reason"],
                             "penalty": item["penalty"]})
    return hits


# --------------------------------------------------------------------------
# 媒介适配：群聊单屏约 200–400 字
# --------------------------------------------------------------------------
def check_medium(text: str, rules: dict) -> dict:
    m = rules["medium"]
    body = re.sub(r"```.*?```", "", text, flags=re.S)      # 代码块不计入「屏数」
    chars = len(re.sub(r"\s", "", body))
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    longest = max((len(re.sub(r"\s", "", p)) for p in paras), default=chars)
    screens = max(1, round(chars / m["chars_per_screen"]))

    if chars <= m["comment_ok"]:
        level, verdict = "ok", "适合直接发群"
    elif chars <= m["comment_limit"]:
        level, verdict = "warn", "偏长，会被划过去"
    else:
        level, verdict = "bad", "太长，基本没人读完"

    advice = {
        "ok": "",
        "warn": f"建议砍到 {m['comment_ok']} 字以内：先发一句钩子（现象 + 卡点），有人接话再展开细节。",
        "bad": (f"{chars} 字 ≈ {screens} 屏。{m['note']} "
                f"做法：把「已尝试/已排除」压成 3 行列表，把代码移到「有人问再发」的附件里。"),
    }[level]

    return {"chars": chars, "screens": screens, "paragraphs": len(paras),
            "longest_paragraph": longest, "level": level,
            "verdict": verdict, "advice": advice}


# --------------------------------------------------------------------------
# 综合诊断
# --------------------------------------------------------------------------
def diagnose(text: str, rules: dict, forced_type: str | None = None) -> dict:
    if forced_type:
        ptype, why = forced_type, "命令行手动指定 --type"
    else:
        ptype, why = detect_type(text, rules)

    spec = rules["types"][ptype]

    details, got, total = [], 0.0, 0
    for el in spec["elements"]:
        r = check_element(text, el)
        total += el["weight"]
        got += el["weight"] * r["credit"]
        details.append({
            "id": el["id"], "weight": el["weight"], "note": el["note"],
            "hit": r["hit"], "partial": r["partial"],
            "earned": round(el["weight"] * r["credit"], 1),
        })

    negatives = check_negative(text, rules)
    penalty = sum(n["penalty"] for n in negatives)

    raw = (got / total * 100) if total else 0.0
    score = max(0.0, min(100.0, raw - penalty))

    missing = [d["id"] for d in details if not d["hit"]]
    partials = [d["id"] for d in details if d["partial"]]
    hard_missing = [g for g in spec["hard_gates"] if g in missing]

    if score >= 85:
        grade = "A"
    elif score >= 70:
        grade = "B"
    elif score >= 50:
        grade = "C"
    else:
        grade = "D"

    medium = check_medium(text, rules)

    return {
        "tool": "question-doctor",
        "version": __version__,
        "type": ptype,
        "type_label": spec["label"],
        "type_reason": why,
        "score": round(score, 1),
        "raw_score": round(raw, 1),
        "grade": grade,
        "elements": details,
        "missing": missing,
        "partial": partials,
        "hard_gates": spec["hard_gates"],
        "hard_missing": hard_missing,
        "hard_ok": not hard_missing,
        "negatives": negatives,
        "penalty": penalty,
        "medium": medium,
        "passed": (not hard_missing) and score >= 70,
    }


# --------------------------------------------------------------------------
# 渲染 Markdown 报告
# --------------------------------------------------------------------------
def render(result: dict, rules: dict) -> str:
    L = []
    a = L.append
    a(f"# 提问诊断报告  ·  {result['score']:.0f}/100  ({result['grade']} 级)\n")
    a(f"**识别类型**：{result['type_label']}（`{result['type']}`）— {result['type_reason']}")
    if result["penalty"]:
        a(f"**负面信号扣分**：-{result['penalty']}")
    a("")

    a("## 一、要素检查\n")
    a("| 要素 | 结果 | 得分 | 说明 |")
    a("|---|---|---|---|")
    for d in result["elements"]:
        if not d["hit"]:
            mark = "❌ 缺失"
        elif d["partial"]:
            mark = "⚠️ 不完整"
        else:
            mark = "✅ 完整"
        a(f"| {d['id']} | {mark} | {d['earned']:.0f}/{d['weight']} | {d['note']} |")
    a("")

    gate = " / ".join(result["hard_gates"])
    if result["hard_ok"]:
        a(f"**硬门槛（{gate}）**：✅ 通过")
    else:
        a(f"**硬门槛（{gate}）**：❌ 不通过 — 缺：**{'、'.join(result['hard_missing'])}**")
    a("")

    if result["missing"] or result["partial"]:
        a("## 二、优先要补的\n")
        i = 1
        for mid in result["hard_missing"] + [m for m in result["missing"] if m not in result["hard_missing"]]:
            a(f"{i}. **{mid}**（{next(d['weight'] for d in result['elements'] if d['id'] == mid)} 分）"
              f" — {rules['advice']['missing'].get(mid, '')}")
            i += 1
        for pid in result["partial"]:
            a(f"{i}. **{pid}（不完整）** — {rules['advice']['partial'].get(pid, '')}")
            i += 1
        a("")

    m = result["medium"]
    a("## 三、媒介适配（群聊）\n")
    a(f"- 正文字数（不含代码块与空白）：**{m['chars']} 字** ≈ **{m['screens']} 屏**")
    a(f"- 段落数：{m['paragraphs']}；最长段落：{m['longest_paragraph']} 字")
    a(f"- 判定：**{m['verdict']}**")
    if m["advice"]:
        a(f"- 建议：{m['advice']}")
    a("")

    if result["negatives"]:
        a("## 四、负面信号\n")
        for n in result["negatives"]:
            a(f"- ❌ **{n['id']}**（-{n['penalty']}）：{n['reason']}")
        a("")

    a("## 五、一句话自检\n")
    a("你的问题能不能压缩成这一句？")
    a("")
    a("> 我在做 ____（目标），用的是 ____（环境），已经试过 ____（结果 ____），")
    a("> 现在卡在 ____，我怀疑是 ____，想要的是 ____（解法/方案对比/指出盲区）。")
    a("")
    a("**填不满的地方，就是对方会反问你的地方。**")
    a("")

    verdict = "✅ 可以发" if result["passed"] else "⚠️ 建议先按上面改一轮再发"
    a(f"---\n\n**结论：{verdict}**")
    return "\n".join(L)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def read_input(target: str) -> str:
    if target == "-":
        return sys.stdin.read()
    p = Path(target)
    if not p.exists():
        raise SystemExit(f"[question-doctor] 文件不存在：{target}")
    return p.read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="question_doctor",
        description="发到群里之前，先给问题做个体检。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python question_doctor.py draft.md\n"
               "  cat draft.md | python question_doctor.py -\n"
               "  python question_doctor.py --json --type question draft.md\n",
    )
    ap.add_argument("input", nargs="?", default="-",
                    help="输入文件路径，或 - 表示从标准输入读（默认）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认输出 Markdown）")
    ap.add_argument("--type", choices=["question", "share", "feedback"],
                    help="手动指定文本类型，跳过自动识别")
    ap.add_argument("--rules", help="自定义规则文件路径（默认 references/rules.json）")
    ap.add_argument("--quiet", action="store_true", help="只输出评分，不输出完整报告")
    args = ap.parse_args(argv)

    rules = load_rules(Path(args.rules) if args.rules else None)
    text = read_input(args.input)

    if not text.strip():
        print("[question-doctor] 输入是空的——贴一段你准备发到群里的文字再试。",
              file=sys.stderr)
        return 2

    result = diagnose(text, rules, forced_type=args.type)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.quiet:
        print(f"{result['score']:.0f}/100 ({result['grade']}) "
              f"[{result['type_label']}] "
              f"{'通过' if result['passed'] else '未通过'}")
    else:
        print(render(result, rules))

    # 退出码：0 = 通过；1 = 不通过（便于接进 CI / git hook）
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
