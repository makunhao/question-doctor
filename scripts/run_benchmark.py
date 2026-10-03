#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_benchmark.py —— 用黄金测试集量化引擎的准确率。

    输入：benchmark/golden_set.json（人工标注的期望值）
    输出：误报率 / 漏报率 / 类型准确率 / 负面信号准确率 / 通过判定一致率 / 媒介适配一致率
    退出码：0 = 没有新回归；1 = 出现了已知缺口之外的新错误（可直接接进 CI）

为什么要有这个东西
------------------
本项目之前的测试只有「单元测试」——它验证的是**代码有没有按我设想的方式运行**。
但真正该被验证的是另一件事：**判定本身准不准**。
这两者完全不同：一个 bug 完全可能让 25 个单元测试全绿，同时让误报率翻倍。

为什么要有「已知缺口」这个概念
------------------------------
黄金集里有一部分是**故意留着的**已知缺陷（例如英文场景、纯代码块）。
如果 CI 一跑就红，人就会习惯性忽略红灯——那这个测试等于没有。
所以：已知缺口记进 baseline，**CI 只对「新出现的错误」报红**。
灯的语义必须是"有东西变了"，而不是"这里一直有问题"。

口径说明（误报 / 漏报的方向，别搞反）
--------------------------------------
    误报 = 引擎判「缺失」，但标注是「存在」  → 冤枉用户，会把人诱导去改好稿子
    漏报 = 引擎判「存在」，但标注是「缺失」  → 放过问题，用户以为万事大吉
两者伤害不对称：误报会催生"为了凑要素而堆内容"的行为，所以它单独统计。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import question_doctor as qd  # noqa: E402

GOLDEN = ROOT / "benchmark" / "golden_set.json"
BASELINE = ROOT / "benchmark" / "baseline.json"

C_OK, C_BAD, C_WARN, C_DIM, C_END = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"


def load_gaps() -> set[tuple]:
    """已知缺口：(用例 id, 类别, 标识, 方向)。这些不计入"新回归"。"""
    p = ROOT / "benchmark" / "known_gaps.json"
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {(g["case"], g.get("kind", "element"), g["id"], g.get("direction", ""))
            for g in data.get("gaps", [])}


def run_case(case: dict, rules: dict, gaps: set[tuple]) -> dict:
    r = qd.diagnose(case["input"], rules)
    applicable = [e["id"] for e in rules["types"][r["type"]]["elements"]]
    expected_partial = set(case.get("expect_partial", []))
    # ⚠️ expect_partial 里的要素**也是"应当被判为存在"**的（只是表达不完整）。
    # 第一版忘了并集，导致 G08 被同时报成「漏报」和「未部分给分」——自相矛盾。
    expected_present = set(case["expect_present"]) | expected_partial
    expected_negative = set(case.get("expect_negative", []))

    issues: list[dict] = []

    # ── 类型判定 ──
    type_ok = None
    if case.get("expect_type") is not None:
        type_ok = (r["type"] == case["expect_type"])
        if not type_ok:
            issues.append({"kind": "type", "id": f"{case['expect_type']}→{r['type']}",
                           "direction": "类型误判"})

    # ── 要素判定（只在该用例期望类型的适用要素上统计）──
    cells = 0
    for eid in applicable:
        got = next((d for d in r["elements"] if d["id"] == eid), None)
        if got is None:
            continue
        # 若用例期望类型与引擎判定类型不同，两边要素集不可比，跳过
        if case.get("expect_type") is not None and r["type"] != case["expect_type"]:
            continue
        cells += 1
        exp_present = eid in expected_present
        if exp_present and not got["hit"]:
            k = (case["id"], "element", eid, "误报")
            issues.append({"kind": "element", "id": eid, "direction": "误报",
                           "note": "标注存在，引擎判缺失", "known": k in gaps})
        elif (not exp_present) and got["hit"]:
            k = (case["id"], "element", eid, "漏报")
            issues.append({"kind": "element", "id": eid, "direction": "漏报",
                           "note": "标注缺失，引擎判存在", "known": k in gaps})
        # 部分给分一致率
        if eid in expected_partial and not got["partial"]:
            k = (case["id"], "element", eid, "未部分给分")
            issues.append({"kind": "partial", "id": eid, "direction": "未部分给分",
                           "note": "应只给一半分", "known": k in gaps})

    # ── 负面信号 ──
    got_neg = {n["id"] for n in r["negatives"]}
    for nid in got_neg - expected_negative:
        k = (case["id"], "negative", nid, "负面误报")
        issues.append({"kind": "negative", "id": nid, "direction": "负面误报",
                       "note": "不该报却报了", "known": k in gaps})
    for nid in expected_negative - got_neg:
        k = (case["id"], "negative", nid, "负面漏报")
        issues.append({"kind": "negative", "id": nid, "direction": "负面漏报",
                       "note": "该报却没报", "known": k in gaps})

    # ── 通过与否 ──
    pass_ok = (r["passed"] == case["expect_pass"])
    if not pass_ok:
        k = (case["id"], "pass", "passed", "判定不一致")
        issues.append({"kind": "pass", "id": "passed", "direction": "判定不一致",
                       "note": f"标注 {case['expect_pass']}，引擎 {r['passed']}",
                       "known": k in gaps})

    # ── 媒介适配 ──
    med_ok = None
    if case.get("expect_medium_level"):
        med_ok = (r["medium"]["level"] == case["expect_medium_level"])
        if not med_ok:
            k = (case["id"], "medium", "level", "判定不一致")
            issues.append({"kind": "medium", "id": "level", "direction": "判定不一致",
                           "note": f"标注 {case['expect_medium_level']}，"
                                   f"引擎 {r['medium']['level']}", "known": k in gaps})

    # ── 「能不能直接发」：要素过关 ≠ 现在就该按原样发 ──
    if "expect_ready_to_send" in case:
        rts_ok = (r["ready_to_send"] == case["expect_ready_to_send"])
        if not rts_ok:
            k = (case["id"], "ready", "ready_to_send", "判定不一致")
            issues.append({"kind": "ready", "id": "ready_to_send", "direction": "判定不一致",
                           "note": f"标注 {case['expect_ready_to_send']}，"
                                   f"引擎 {r['ready_to_send']}", "known": k in gaps})

    return {"case": case, "result": r, "issues": issues, "cells": cells,
            "type_ok": type_ok, "pass_ok": pass_ok, "med_ok": med_ok}


def main() -> int:
    ap = argparse.ArgumentParser(description="跑黄金测试集，量化误报率/漏报率")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--all", action="store_true", help="列出所有不一致（默认只列新回归）")
    args = ap.parse_args()

    rules = qd.load_rules()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    gaps = load_gaps()

    rows = [run_case(c, rules, gaps) for c in golden["cases"]]

    cells = sum(r["cells"] for r in rows)
    all_issues = [i for r in rows for i in r["issues"]]
    new_issues = [i for i in all_issues if not i.get("known")]

    # 误报/漏报只统计要素维度的
    el = [i for i in all_issues if i["kind"] == "element"]
    fp = [i for i in el if i["direction"] == "误报"]
    fn = [i for i in el if i["direction"] == "漏报"]
    n_fp = len(fp); n_fn = len(fn)

    type_rows = [r for r in rows if r["type_ok"] is not None]
    type_acc = (sum(1 for r in type_rows if r["type_ok"]) / len(type_rows) * 100
                if type_rows else 0.0)
    pass_acc = sum(1 for r in rows if r["pass_ok"]) / len(rows) * 100
    med_rows = [r for r in rows if r["med_ok"] is not None]
    med_acc = (sum(1 for r in med_rows if r["med_ok"]) / len(med_rows) * 100
               if med_rows else 100.0)
    neg_issues = [i for i in all_issues if i["kind"] == "negative"]

    summary = {
        "cases": len(rows),
        "element_cells": cells,
        "false_positive": n_fp,
        "false_negative": n_fn,
        "fp_rate": round(n_fp / cells * 100, 2) if cells else 0.0,
        "fn_rate": round(n_fn / cells * 100, 2) if cells else 0.0,
        "type_accuracy": round(type_acc, 1),
        "pass_accuracy": round(pass_acc, 1),
        "medium_accuracy": round(med_acc, 1),
        "negative_errors": len(neg_issues),
        "known_gaps": len(all_issues) - len(new_issues),
        "new_failures": len(new_issues),
    }

    if args.json:
        print(json.dumps({"summary": summary, "new_issues": new_issues,
                          "all_issues": all_issues}, ensure_ascii=False, indent=2))
        return 1 if new_issues else 0

    print("=" * 72)
    print(f"黄金测试集 · {summary['cases']} 条用例 · "
          f"{summary['element_cells']} 个要素判定单元格")
    print("-" * 72)
    print(f"  类型判定准确率    ：{summary['type_accuracy']:>5.1f}%"
          f"  {C_DIM}({len(type_rows)} 条有明确标注){C_END}")
    print(f"  通过/不通过一致率 ：{summary['pass_accuracy']:>5.1f}%")
    print(f"  媒介适配一致率    ：{summary['medium_accuracy']:>5.1f}%")
    print(f"  要素·误报率       ：{summary['fp_rate']:>5.2f}%  ({n_fp}/{cells})"
          f"  {C_DIM}← 冤枉用户，最该避免{C_END}")
    print(f"  要素·漏报率       ：{summary['fn_rate']:>5.2f}%  ({n_fn}/{cells})"
          f"  {C_DIM}← 放过问题{C_END}")
    print(f"  负面信号错误数    ：{summary['negative_errors']}")
    print("-" * 72)

    def dump(title: str, items: list[dict], mark: str):
        if not items:
            return
        print(f"{title}")
        for i in items:
            print(f"  {mark} {i['direction']:<8} {i['id']:<10} {i.get('note','')}")

    if args.all:
        by_case: dict[str, list[dict]] = {}
        for r in rows:
            if r["issues"]:
                by_case[r["case"]["id"]] = r["issues"]
        for cid, lst in by_case.items():
            case = next(c for c in golden["cases"] if c["id"] == cid)
            flag = C_OK if all(i.get("known") for i in lst) else C_BAD
            print(f"{flag}{cid}{C_END} {case['title']}")
            for i in lst:
                tag = f"{C_DIM}已知{C_END}" if i.get("known") else f"{C_BAD}新{C_END}"
                print(f"    [{tag}] {i['direction']:<8} {i['id']:<10} {i.get('note','')}")
        print("-" * 72)

    if new_issues:
        print(f"{C_BAD}✗ 出现 {len(new_issues)} 处新的判定错误（已知缺口之外的）{C_END}")
        dump("新错误明细：", new_issues, "×")
        print(f"{C_WARN}  这些需要被修掉，或被显式写进 benchmark/known_gaps.json "
              f"并说明理由。{C_END}")
        print("=" * 72)
        return 1

    print(f"{C_OK}✓ 没有新的判定错误{C_END}  "
          f"{C_DIM}（已知缺口 {summary['known_gaps']} 处，见 known_gaps.json）{C_END}")

    # 基线对比：只比"有没有变差"
    if BASELINE.exists():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))["summary"]
        worse = []
        for key in ("false_positive", "false_negative", "negative_errors"):
            if summary[key] > base[key]:
                worse.append(f"{key}: {base[key]} → {summary[key]}")
        for key in ("type_accuracy", "pass_accuracy", "medium_accuracy"):
            if summary[key] < base[key] - 0.05:
                worse.append(f"{key}: {base[key]} → {summary[key]}")
        if worse:
            print(f"{C_BAD}✗ 相比基线变差：{'; '.join(worse)}{C_END}")
            print("=" * 72)
            return 1
        print(f"{C_DIM}  与基线一致（误报 {base['false_positive']} / "
              f"漏报 {base['false_negative']} / 负面错误 {base['negative_errors']}）{C_END}")
    else:
        print(f"{C_WARN}  未找到 benchmark/baseline.json —— 用 "
              f"`--json > baseline.json` 记录当前水平作为基线{C_END}")

    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
