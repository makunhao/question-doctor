【背景】Windows 11 / Python 3.13，我在做课程资料抓取，目标是把 31 个课程页面转成 Markdown 再送去翻译。

【现象】第一版跑完，31 篇里 13 篇正常，**18 篇输出 0 字符**。用浏览器打开这 18 篇，正文明明在。

【已尝试】
- 怀疑编码 → 确认 `response.content` 解码 UTF-8 无异常，**已排除**
- 怀疑选择器 → 手工 grep 了其中一个页面，`<article>` 标签确实存在，**已排除**
- 打印 `drop_depth` 后发现真正原因：它一旦涨上去就再也没回到 0

【卡点】真实网页有大量**不闭合标签**，`html.parser` 是流式回调、不做配对修复；
我的 `drop_depth` 是全局计数器，只要页面里有个 `<div>` 欠一个 `</div>`，这个 +1 就永远抵消不掉。

【最小复现】
```python
drop_depth = 0
def handle_starttag(tag, attrs):
    global drop_depth
    if tag in DROP_TAGS: drop_depth += 1
def handle_endtag(tag):
    global drop_depth
    if tag in DROP_TAGS: drop_depth -= 1     # 欠闭合一次，就永久 > 0
```

【我的候选改法】把「深度计数器」换成**显式标签栈**：出标签时从栈顶向上找最近的同名帧，
把它以上的全部弹出。已在 31 篇上跑出 13/31 → 28/31。

【想请教】这个栈方案在**嵌套同名标签**的场景下，有没有更稳的判据？
我想要的是方案对比，不是教程。
<!-- type: question -->
