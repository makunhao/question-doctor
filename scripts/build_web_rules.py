#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_web_rules.py —— 把 references/rules.json 同步成 web/rules.js

为什么要这一步（而不是让网页去 fetch rules.json）：

1. **单一事实来源**：CLI 和 Web 用同一份规则。改规则只改 `references/rules.json`，
   跑一次本脚本，两边同时生效——不会出现「网页改好了、脚本没改」的漂移。
2. **file:// 也能跑**：直接双击 `web/index.html` 预览时，`fetch('rules.json')` 会被
   浏览器的 CORS 策略挡掉；编译成 `.js` 全局变量就没有这个问题。
3. **可校验**：本脚本会把权重合计校验一遍，不等于 100 就直接失败——
   把「规则改错」挡在构建期，而不是等用户看到分数不对。

用法：
    python scripts/build_web_rules.py
    python scripts/build_web_rules.py --check     # 只校验，不写文件（CI 用）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "references" / "rules.json"
DST = ROOT / "web" / "rules.js"


def validate(rules: dict) -> list[str]:
    errs = []
    for name, spec in rules["types"].items():
        total = sum(e["weight"] for e in spec["elements"])
        if total != 100:
            errs.append(f"{name} 的要素权重合计 {total}，应为 100")
        ids = {e["id"] for e in spec["elements"]}
        for g in spec["hard_gates"]:
            if g not in ids:
                errs.append(f"{name} 的硬门槛 '{g}' 不是有效要素 id")
    for t in ("question", "share", "feedback"):
        if t not in rules["types"]:
            errs.append(f"缺少类型定义：{t}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="把 rules.json 同步成 web/rules.js")
    ap.add_argument("--check", action="store_true",
                    help="只校验规则，不写文件（适合放进 CI）")
    args = ap.parse_args()

    with SRC.open(encoding="utf-8") as f:
        rules = json.load(f)

    errs = validate(rules)
    if errs:
        print("[build_web_rules] 规则校验失败：", file=sys.stderr)
        for e in errs:
            print(f"  × {e}", file=sys.stderr)
        return 1

    if args.check:
        print(f"[build_web_rules] 规则校验通过（{len(rules['types'])} 种类型，"
              f"{sum(len(t['elements']) for t in rules['types'].values())} 个要素）")
        return 0

    DST.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rules, ensure_ascii=False, indent=2)
    banner = (
        "/* 本文件由 scripts/build_web_rules.py 自动生成，请勿手改。\n"
        " * 规则源头：references/rules.json\n"
        " * 重新生成：python scripts/build_web_rules.py\n"
        " */\n"
    )
    DST.write_text(f"{banner}window.QUESTION_DOCTOR_RULES = {payload};\n",
                   encoding="utf-8")
    print(f"[build_web_rules] 已写入 {DST.relative_to(ROOT)} "
          f"({DST.stat().st_size} 字节)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
