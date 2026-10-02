#!/usr/bin/env node
/* engine_cli.js —— 在 Node 里跑 web/engine.js，用于与 Python 版对拍。
 *
 * 用法：node tests/engine_cli.js <输入文件>
 * 输出：diagnose() 的 JSON（与 Python 的 --json 同结构子集）
 *
 * 为什么需要它：Web 版和 CLI 版是同一套判据的两个实现。
 * 两边口径一旦漂移，用户会看到「网页说 90 分、脚本说 60 分」——比没有工具更糟。
 * 所以必须有一条自动化的对拍，而不是靠肉眼对比截图。
 */

const fs = require('fs');
const path = require('path');

// rules.js 是给浏览器写的（挂在 window 上）。给它一个 window 就能在 Node 里复用。
global.window = global;

require(path.join(__dirname, '..', 'web', 'rules.js'));
const ENG = require(path.join(__dirname, '..', 'web', 'engine.js'));

const RULES = global.QUESTION_DOCTOR_RULES;
if (!RULES) {
  console.error('[engine_cli] rules.js 未加载出 QUESTION_DOCTOR_RULES');
  process.exit(2);
}

const file = process.argv[2];
if (!file) {
  console.error('用法：node tests/engine_cli.js <输入文件>');
  process.exit(2);
}

const text = fs.readFileSync(file, 'utf8');
const r = ENG.diagnose(text, RULES);

console.log(JSON.stringify({
  type: r.type,
  type_label: r.typeLabel,
  score: r.score,
  grade: r.grade,
  hard_ok: r.hardOk,
  hard_missing: r.hardMissing,
  missing: r.missing,
  partial: r.partial,
  penalty: r.penalty,
  passed: r.passed,
  medium: { chars: r.medium.chars, screens: r.medium.screens, level: r.medium.level },
}, null, 2));
