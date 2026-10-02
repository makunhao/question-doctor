#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_skill.py —— 把仓库打包成可安装的 `.skill` 文件。

`.skill` 就是一个 tar.gz（Claude Skill 的安装包格式）。本脚本负责三件事：

1. **只装该装的**：SKILL.md + scripts/ + references/ + examples/ + LICENSE。
   `web/`、`tests/`、`docs/` 不进包——技能包是给人安装的，
   塞进一个网页应用只会让包变大、让人困惑。
   （网页版是独立交付物，它的位置是仓库的 `web/`，不是技能包里。）

2. **做一次发布前自检**：SKILL.md 必须存在、必须有 frontmatter，
   规则文件必须能解析且权重合计为 100。**自检不过就不出包**——
   一个装上去才发现坏了的技能包，比没有更糟。

3. **可复现**：固定 gzip mtime，同一个源目录打出来的包字节一致，
   便于用 sha256 比对"这个包到底是从哪一版打出来的"。

用法：
    python scripts/build_skill.py                    # 输出到 dist/
    python scripts/build_skill.py -o /path/x.skill   # 指定输出
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "question-doctor"

# 进包的白名单（目录会被递归收录）
INCLUDE = ["SKILL.md", "scripts", "references", "examples", "LICENSE"]
# 明确排除的（即使落在白名单目录里）
EXCLUDE_PATTERNS = [r"__pycache__", r"\.pyc$", r"\.DS_Store$", r"\.git"]


def preflight() -> list[str]:
    """发布前自检。返回错误列表，空表示可以出包。"""
    errs = []

    skill_md = ROOT / "SKILL.md"
    if not skill_md.exists():
        errs.append("缺少 SKILL.md —— 技能包的主指令文件不能缺")
        return errs

    head = skill_md.read_text(encoding="utf-8")
    if not head.startswith("---"):
        errs.append("SKILL.md 没有以 YAML frontmatter（---）开头，技能不会被正确触发")
    else:
        # ⚠️ 不能用 head.split("---")：description 是块标量（`description: >`），
        # 首 600 字里可能只有一个 `---`（开头那个），会把 frontmatter 解析成空串，
        # 于是**任何** SKILL.md 都报"缺 name / 缺 description"——一条假红灯。
        # 正确做法：按行找第二行的分隔符。
        lines = head.splitlines()
        end = next((i for i, ln in enumerate(lines[1:], start=1)
                    if ln.strip() == "---"), None)
        if end is None:
            errs.append("SKILL.md 的 frontmatter 没有找到结束标记 `---`")
            fm = ""
        else:
            fm = "\n".join(lines[1:end])
        if not re.search(r"^name\s*:", fm, re.M):
            errs.append("SKILL.md frontmatter 缺少 name")
        if not re.search(r"^description\s*:", fm, re.M):
            errs.append("SKILL.md frontmatter 缺少 description")

    rules_path = ROOT / "references" / "rules.json"
    if not rules_path.exists():
        errs.append("缺少 references/rules.json —— 引擎会直接退出")
    else:
        try:
            rules = json.loads(rules_path.read_text(encoding="utf-8"))
            for name, spec in rules["types"].items():
                total = sum(e["weight"] for e in spec["elements"])
                if total != 100:
                    errs.append(f"{name} 的要素权重合计 {total}，应为 100")
        except Exception as e:                                   # noqa: BLE001
            errs.append(f"rules.json 解析失败：{e}")

    if not (ROOT / "scripts" / "question_doctor.py").exists():
        errs.append("缺少 scripts/question_doctor.py")

    return errs


def collect() -> list[Path]:
    out: list[Path] = []
    for item in INCLUDE:
        p = ROOT / item
        if not p.exists():
            continue
        if p.is_file():
            out.append(p)
        else:
            out.extend(sorted(f for f in p.rglob("*") if f.is_file()))
    keep = []
    for f in out:
        rel = f.relative_to(ROOT).as_posix()
        if any(re.search(pat, rel) for pat in EXCLUDE_PATTERNS):
            continue
        keep.append(f)
    return keep


def build(out_path: Path) -> tuple[Path, str, int]:
    files = collect()

    buf = io.BytesIO()
    # mtime=0 + 固定 uid/gid → 可复现构建
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            info = tar.gettarinfo(str(f), arcname=f"{SKILL_NAME}/{rel}")
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mode = 0o755 if f.suffix == ".py" else 0o644
            with f.open("rb") as fh:
                tar.addfile(info, fh)

    raw = buf.getvalue()
    packed = gzip.compress(raw, compresslevel=9, mtime=0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(packed)
    sha = hashlib.sha256(packed).hexdigest()
    return out_path, sha, len(files)


def main() -> int:
    ap = argparse.ArgumentParser(description="把仓库打包成 .skill")
    ap.add_argument("-o", "--output", help="输出路径（默认 dist/<name>.skill）")
    args = ap.parse_args()

    errs = preflight()
    if errs:
        print("[build_skill] 发布前自检未通过：", file=sys.stderr)
        for e in errs:
            print(f"  × {e}", file=sys.stderr)
        return 1

    out = Path(args.output) if args.output else ROOT / "dist" / f"{SKILL_NAME}.skill"
    path, sha, n = build(out)

    print(f"[build_skill] 自检通过")
    print(f"  文件数：{n}")
    print(f"  输出：{path}")
    print(f"  大小：{path.stat().st_size} 字节")
    print(f"  SHA-256：{sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
