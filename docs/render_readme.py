#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_readme.py —— 把 README.md 渲染成一张接近 GitHub 观感的 HTML，
用于生成 C5 要求的「README 截图」。

为什么不直接调 GitHub 的 /markdown API：
    交付物不应该依赖"截图那一刻网络通不通"。
    这里用一个只覆盖 README 实际用到语法的极简渲染器，
    离线、可复现、结果稳定（同一个 README 永远渲染出同一张图）。

支持的语法（刚好是 README 里出现过的那些）：
    标题、段落、围栏代码块、行内代码、粗体、链接、图片、
    无序/有序列表、引用块、表格、水平线、
    以及 shields.io 徽章的降级（网络不通时显示为文字，不让整页崩掉）。

用法：
    python docs/render_readme.py            # 生成 docs/readme-render.html
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "README.md"
DST = ROOT / "docs" / "readme-render.html"

CSS = """
:root { --fg:#1f2328; --muted:#59636e; --border:#d1d9e0; --bg:#ffffff;
        --code-bg:#f6f8fa; --link:#0969da; }
* { box-sizing:border-box; }
body { margin:0; background:#f6f8fa; color:var(--fg);
       font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,
       "PingFang SC","Microsoft YaHei",sans-serif; }
.gh { max-width:1012px; margin:24px auto; background:var(--bg);
      border:1px solid var(--border); border-radius:6px; padding:32px 40px 48px; }
h1 { font-size:2em; border-bottom:1px solid var(--border); padding-bottom:.3em; margin:0 0 16px; }
h2 { font-size:1.5em; border-bottom:1px solid var(--border); padding-bottom:.3em;
     margin:24px 0 16px; }
h3 { font-size:1.25em; margin:24px 0 16px; }
p { margin:0 0 16px; }
a { color:var(--link); text-decoration:none; }
a:hover { text-decoration:underline; }
code { background:var(--code-bg); padding:.2em .4em; border-radius:6px;
       font:85%/1.45 ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace; }
pre { background:var(--code-bg); border-radius:6px; padding:16px; overflow:auto; margin:0 0 16px; }
pre code { background:none; padding:0; font-size:85%; }
blockquote { margin:0 0 16px; padding:0 1em; color:var(--muted);
             border-left:.25em solid var(--border); }
table { border-collapse:collapse; width:100%; margin:0 0 16px; display:block; overflow:auto; }
th,td { border:1px solid var(--border); padding:6px 13px; }
th { background:var(--code-bg); font-weight:600; }
tr:nth-child(2n) td { background:#f6f8fa55; }
ul,ol { padding-left:2em; margin:0 0 16px; }
li { margin:.25em 0; }
hr { border:0; border-bottom:1px solid var(--border); margin:24px 0; }
img { max-width:100%; }
.badges p { margin:0 0 16px; }
"""


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def inline(s: str) -> str:
    """行内元素。顺序重要：先处理 code，避免 code 里的 * 被当成粗体。"""
    codes: list[str] = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`]+)`", stash, s)
    s = esc(s)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
               r'<img alt="\1" src="\2">', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{esc(codes[int(m.group(1))])}</code>", s)
    return s


def render(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]

        # 围栏代码块
        if ln.startswith("```"):
            lang = ln[3:].strip()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{esc(chr(10).join(buf))}</code></pre>")
            continue

        # 表格
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            body = []
            while i < len(lines) and lines[i].startswith("|"):
                body.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" +
                       "".join(f"<th>{inline(c)}</th>" for c in head) +
                       "</tr></thead><tbody>" +
                       "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                               for r in body) +
                       "</tbody></table>")
            continue

        # 原样透传 HTML 块（README 里有 <p>…</p> 包着徽章的那种写法）
        if re.match(r"^\s*</?[a-zA-Z][^>]*>\s*$", ln):
            out.append(ln.strip())
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        if re.match(r"^\s*(---|\*\*\*)\s*$", ln):
            out.append("<hr>")
            i += 1
            continue

        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + "<br>".join(inline(b) for b in buf) + "</blockquote>")
            continue

        if re.match(r"^\s*[-*]\s+", ln):
            buf = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                buf.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(b)}</li>" for b in buf) + "</ul>")
            continue

        if re.match(r"^\s*\d+\.\s+", ln):
            buf = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                buf.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(b)}</li>" for b in buf) + "</ol>")
            continue

        if not ln.strip():
            i += 1
            continue

        # 段落
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|```|\||>|\s*[-*]\s|\s*\d+\.\s|(\s*(---|\*\*\*)\s*$))", lines[i]):
            buf.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(buf))}</p>")

    return "\n".join(out)


def main() -> int:
    body = render(SRC.read_text(encoding="utf-8"))
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(
        f"<!DOCTYPE html>\n<html lang=\"zh-CN\"><head><meta charset=\"UTF-8\">"
        f"<title>README · question-doctor</title><style>{CSS}</style></head>"
        f"<body><div class=\"gh\">{body}</div></body></html>",
        encoding="utf-8",
    )
    print(f"[render_readme] 已生成 {DST.relative_to(ROOT)} ({DST.stat().st_size} 字节)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
