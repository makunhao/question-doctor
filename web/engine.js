/* question-doctor · web 规则引擎（纯函数，无 DOM、无网络）
 *
 * 与 scripts/question_doctor.py 是**同一套判据的两个实现**，共用 references/rules.json。
 * 两边的一致性由 tests/test_parity.py 对拍（同一批输入，比对分数必须相等）。
 *
 * 之所以做成独立模块：纯函数才可测。把判据和 DOM 揉在一起，
 * 就只能靠点页面来验证——那不叫测试，叫试。
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.QuestionDoctorEngine = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ⚠️ 类型识别关键词**不在代码里**，而在 references/rules.json 每个类型的 `heuristic` 下。
  // 两边（Python / JS）都从规则表读，保证"改规则不用动代码"这句话是真的。
  // 之前写死在代码里，用户改了 rules.json 却发现加的触发词不生效，会以为工具坏了。

  const anyMatch = (text, patterns) =>
    patterns.some((p) => new RegExp(p, 'm').test(text));

  /**
   * 按「码点」长度计字数，而不是 JS 默认的 UTF-16 编码单元数。
   *
   * 这行是为了对齐 Python：Python 的 len() 按码点算，
   * 而 JS 的 '🙂'.length === 2（代理对），'字'.length === 1。
   * 不对齐的话，「🙂🙂」在网页上显示 4 字、在命令行显示 2 字，
   * 屏数估算就会跟着错 —— 这类偏差正是 tests/test_parity.py 存在的意义。
   */
  const cpLen = (s) => [...s].length;

  const typeOrder = (rules) =>
    (rules.meta && rules.meta.type_detection_order) || Object.keys(rules.types);

  function detectType(text, rules) {
    const m = text.match(/<!--\s*type\s*:\s*(question|share|feedback)\s*-->/);
    if (m) return { type: m[1], why: '显式声明 <!-- type: ... -->' };

    const order = typeOrder(rules);
    const scores = {};
    for (const t of order) {
      scores[t] = (rules.types[t].heuristic || [])
        .filter((p) => new RegExp(p, 'm').test(text)).length;
    }
    const best = order.reduce((a, b) => (scores[b] > scores[a] ? b : a));
    if (scores[best] > 0) return { type: best, why: `关键词启发式（命中 ${scores[best]} 个信号）` };
    return { type: order[order.length - 1], why: '无信号，默认为最后一种类型' };
  }

  function checkElement(text, spec) {
    const hit = anyMatch(text, spec.patterns || []);
    let partial = false;
    if (hit && spec.confirm && !anyMatch(text, spec.confirm)) partial = true;
    return { hit, partial, credit: hit ? (partial ? 0.5 : 1) : 0 };
  }

  function checkNegative(text, rules) {
    const out = [];
    const stripped = text.trim();
    for (const item of rules.negative) {
      if (anyMatch(text, item.patterns)) {
        out.push({ id: item.id, reason: item.reason, penalty: item.penalty });
        continue;
      }
      // 兜底：整段只剩符号 / emoji（不含任何字母或数字）
      if (item.id === '纯表情' && stripped && !/[\p{L}\p{N}]/u.test(stripped)) {
        out.push({ id: item.id, reason: item.reason, penalty: item.penalty });
      }
    }
    return out;
  }

  function checkMedium(text, rules) {
    const m = rules.medium;
    const body = text.replace(/```[\s\S]*?```/g, '');
    const chars = cpLen(body.replace(/\s/g, ''));
    const paras = text.split(/\n\s*\n/).filter((p) => p.trim());
    const longest = paras.reduce((a, p) => Math.max(a, cpLen(p.replace(/\s/g, ''))), 0);
    const screens = Math.max(1, Math.round(chars / m.chars_per_screen));

    let level;
    if (chars <= m.comment_ok) level = 'ok';
    else if (chars <= m.comment_limit) level = 'warn';
    else level = 'bad';

    const verdict = { ok: '适合直接发群', warn: '偏长，会被划过去', bad: '太长，基本没人读完' }[level];
    const advice = {
      ok: '',
      warn: `建议砍到 ${m.comment_ok} 字以内：先发一句钩子（现象 + 卡点），有人接话再展开细节。`,
      bad: `${chars} 字 ≈ ${screens} 屏。做法：把「已尝试 / 已排除」压成 3 行列表，把代码移到「有人问再发」的附件里。`,
    }[level];

    return { chars, screens, paragraphs: paras.length, longest, level, verdict, advice,
             ratio: Math.min(1, chars / m.comment_limit) };
  }

  function diagnose(text, rules, forcedType) {
    const det = forcedType ? { type: forcedType, why: '手动指定' } : detectType(text, rules);
    const spec = rules.types[det.type];

    const elements = [];
    let got = 0, total = 0;
    for (const el of spec.elements) {
      const r = checkElement(text, el);
      total += el.weight;
      got += el.weight * r.credit;
      elements.push(Object.assign({}, el, r, { earned: el.weight * r.credit }));
    }

    const negatives = checkNegative(text, rules);
    const penalty = negatives.reduce((a, n) => a + n.penalty, 0);
    const raw = total ? (got / total) * 100 : 0;
    const score = Math.max(0, Math.min(100, raw - penalty));

    const missing = elements.filter((e) => !e.hit).map((e) => e.id);
    const partial = elements.filter((e) => e.partial).map((e) => e.id);
    const hardMissing = spec.hard_gates.filter((g) => missing.includes(g));
    const grade = score >= 85 ? 'A' : score >= 70 ? 'B' : score >= 50 ? 'C' : 'D';

    const medium = checkMedium(text, rules);
    // 「要素维度通过」与「现在就能发出去」是两件事，必须分开表达：
    // 八要素齐全但占 4 屏的稿子，要素满分，可群里大概率没人读完。
    // 只给一个布尔值，用户会看到「可以发」然后把 4 屏发出去。
    const passed = hardMissing.length === 0 && score >= 70;

    return { type: det.type, typeLabel: spec.label, typeReason: det.why,
             elements, missing, partial, hardGates: spec.hard_gates, hardMissing,
             hardOk: hardMissing.length === 0, negatives, penalty,
             score: Math.round(score * 10) / 10, raw, grade,
             medium,
             passed,
             readyToSend: passed && medium.level !== 'bad' };
  }

  function toMarkdown(r, draft, rules) {
    const L = [];
    L.push(`# 提问诊断报告  ·  ${r.score.toFixed(0)}/100  (${r.grade} 级)`, '');
    L.push(`- 识别类型：${r.typeLabel}（\`${r.type}\`）— ${r.typeReason}`);
    if (r.penalty) L.push(`- 负面信号扣分：-${r.penalty}`);
    L.push('', '## 一、要素检查', '');
    L.push('| 要素 | 结果 | 得分 | 说明 |', '|---|---|---|---|');
    for (const e of r.elements) {
      const f = !e.hit ? '❌ 缺失' : e.partial ? '⚠️ 不完整' : '✅ 完整';
      L.push(`| ${e.id} | ${f} | ${e.earned}/${e.weight} | ${e.note} |`);
    }
    L.push('');
    L.push(`**硬门槛（${r.hardGates.join(' / ')}）**：` +
      (r.hardOk ? '✅ 通过' : `❌ 不通过 — 缺：${r.hardMissing.join('、')}`));

    const todos = [];
    for (const id of r.hardMissing) todos.push(`${id}（硬门槛）— ${rules.advice.missing[id] || ''}`);
    for (const id of r.missing.filter((m) => !r.hardMissing.includes(m))) {
      todos.push(`${id} — ${rules.advice.missing[id] || ''}`);
    }
    for (const id of r.partial) todos.push(`${id}（不完整）— ${rules.advice.partial[id] || ''}`);
    if (todos.length) {
      L.push('', '## 二、优先要补的', '');
      todos.forEach((t, i) => L.push(`${i + 1}. ${t}`));
    }

    const m = r.medium;
    L.push('', '## 三、媒介适配（群聊）', '');
    L.push(`- 正文字数（不含代码块）：**${m.chars} 字** ≈ **${m.screens} 屏**`);
    L.push(`- 段落 ${m.paragraphs} 个，最长段落 ${m.longest} 字`);
    L.push(`- 判定：**${m.verdict}**`);
    if (m.advice) L.push(`- 建议：${m.advice}`);

    if (r.negatives.length) {
      L.push('', '## 四、负面信号', '');
      for (const n of r.negatives) L.push(`- ❌ **${n.id}**（-${n.penalty}）：${n.reason}`);
    }

    L.push('', '## 五、一句话自检', '');
    L.push('> 我在做 ____（目标），用的是 ____（环境），已经试过 ____（结果 ____），');
    L.push('> 现在卡在 ____，我怀疑是 ____，想要的是 ____（解法/方案对比/指出盲区）。');
    // 结论要分开讲：要素过关 ≠ 现在就该按原样发出去
    let verdict;
    if (r.readyToSend) {
      verdict = '✅ 可以发';
    } else if (r.passed && m.level === 'bad') {
      verdict = `⚠️ **要素过关，但先别按原样发**——这条 ${m.chars} 字 ≈ ${m.screens} 屏，` +
                '群里大概率没人读完。先把「已尝试/已排除」压成几行、代码挪到附件，再发。';
    } else {
      verdict = '⚠️ 建议先改一轮再发';
    }
    L.push('', '---', '', `**结论：${verdict}**`);
    L.push('', '<details><summary>被诊断的原文</summary>', '', '```', draft, '```', '', '</details>');
    return L.join('\n');
  }

  return { detectType, checkElement, checkNegative, checkMedium, diagnose, toMarkdown, cpLen };
});
