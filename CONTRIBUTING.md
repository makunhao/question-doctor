# 贡献指南（CONTRIBUTING）

感谢你愿意花时间。这个项目的**最有价值的贡献不是代码，而是"我觉得这个判定不对"**。

原因很直接：本工具的全部判据都来自真实踩坑（见 `references/rules.json` 的 `inherited_fixes`）。
**你的场景我没踩过，所以我一定漏了。**

---

## 一、先看看你可以贡献什么

| 类型 | 举例 | 需要写代码吗 |
|---|---|---|
| 🥇 **反馈判定不对** | "我这条明明写清了卡点，为什么判缺失？" | ❌ 不需要 |
| 🥇 **补一条关键词** | "我们行业里管这个叫 XX，词表里没有" | ❌ 只改 JSON |
| 🥈 补一个反例测试 | 一条曾骗过本工具的输入 | 一点点 |
| 🥈 补一个示例 | 一个"改写前 / 改写后"的真实对照 | ❌ 不需要 |
| 🥉 修 bug / 加功能 | —— | ✅ 需要 |

**只要你手上有「本工具判错了」的原文，那就是最高价值的 Issue。**
没有原文的"好像不太准"，我这边无法复现，也没法改。

---

## 二、改规则（最常见，不用写代码）

**所有判据都在 `references/rules.json` 里。改它，不要改代码。**

```jsonc
{
  "id": "具体卡点",
  "weight": 16,
  "note": "把问题收窄到「卡在哪个环节」，而不是「就是不 work」",
  "patterns": ["卡在", "根因", "我怀疑"],     // 命中任一即算"有"
  "confirm": ["结果", "报错", "无效"]         // 可选：还要求同时命中，否则只给一半分
}
```

改完**必须**跑这两条：

```bash
python scripts/build_web_rules.py            # 同步到网页版；会校验权重是否仍合计 100
python -m unittest discover -s tests         # 24 个测试
```

> 第一条会**拒绝构建**如果某个类型的权重合计不等于 100。
> 这不是洁癖：**权重乱掉之后，分数就不可比了**，而分数不可比的工具是没用的。

---

## 三、改代码

### 环境

**不需要安装任何东西。** Python ≥ 3.9 就够——"零依赖"是本项目的功能之一，
请不要为了便利引入第一个第三方库（除非有非常强的理由，且请在 Issue 里先讨论）。

```bash
git clone https://github.com/makunhao/question-doctor.git
cd question-doctor
python -m unittest discover -s tests -v
```

### 一条硬规矩：改判据，必须两边一起改

项目有两套实现：

| 位置 | 语言 | 用途 |
|---|---|---|
| `scripts/question_doctor.py` | Python | 命令行 |
| `web/engine.js` | JavaScript | 网页版 |

**改了其中一个而没改另一个，是明确不接受**——因为 `tests/test_parity.py` 会失败，
而它失败意味着用户会看到"网页说 90 分、命令行说 60 分"，
**那比没有这个工具更糟：他会开始怀疑所有分数。**

对拍测试就是为了让"忘了改另一边"变成一件**跑一次就知道**的事。

### 提 PR 之前

```bash
python scripts/build_web_rules.py
python -m unittest discover -s tests
python scripts/question_doctor.py examples/01-bad-question.md   # 应失败（退出码 1）
python scripts/question_doctor.py examples/02-good-question.md  # 应通过（退出码 0）
```

请在本机**真的跑过**再提交，不要凭感觉说"应该没问题"。

---

## 四、加测试

**特别欢迎"反例测试"。** 本项目有一条历史上最贵的教训：

> 早期版本用 `"无" in cell` 判断"无回应"，
> 把「你是不是**没有**在群里发」这条**真实回复**判成了"没人回"。
> **一个子串包含，毁掉了一条证据。**

现在有专门的回归测试（`test_no_false_positive_on_real_content`）钉住它。
**如果你能想出一条"看起来违规、其实完全正常"的输入，请务必提 Issue 或 PR。**

写测试的地方：

- `tests/test_question_doctor.py` —— 单元测试（标准库 `unittest`）
- `tests/test_parity.py` —— 跨语言对拍（改 JS 或 Python 判据时，这里会自动覆盖）

---

## 五、提交规范

- **commit message**：`<类型>: <一句话>`，类型用 `feat` / `fix` / `docs` / `test` / `rules` / `chore`
  - 例：`rules: 补入「无异常 / 已排除」等结果词`
  - 例：`fix: JS 侧字数改按码点计，修正 emoji 长度不一致`
- **一个 commit 只做一件事**。判据改动和文档改动请分开。
- **改了判据**：请在 PR 描述里贴出——改前 / 改后的分数对比，以及对两个示例文件的影响。

---

## 六、行为准则

参与本项目即视为同意 [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)。
简单说：**对人友好，对事实苛刻。**
