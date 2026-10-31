// 生成 Phase 2 语义分析所需的工作清单：按显著性筛选后的函数/类候选，
// 连同文件级元信息一起输出，供逐批撰写 summary/tags 使用。
const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const ua = path.join(root, '.ua');
const batches = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'batches.json'), 'utf8'));

// 显著性阈值：类（>=2 方法或 >=20 行）；函数（>=25 行）
const FN_MIN = 25;
const lines = [];
let fnKept = 0;
let fnTotal = 0;
let clsKept = 0;
let clsTotal = 0;

for (const b of batches.batches) {
  const r = JSON.parse(fs.readFileSync(path.join(ua, 'tmp', 'ua-file-extract-results-' + b.batchIndex + '.json'), 'utf8'));
  lines.push('##### BATCH ' + b.batchIndex + ' (files=' + b.files.length + ') #####');
  for (const f of r.results) {
    const fns = (f.functions || []).filter((x) => (x.endLine - x.startLine + 1) >= FN_MIN);
    fnKept += fns.length;
    fnTotal += (f.functions || []).length;
    const cls = (f.classes || []).filter((c) => (c.methods || []).length >= 2 || (c.endLine - c.startLine + 1) >= 20);
    clsKept += cls.length;
    clsTotal += (f.classes || []).length;
    lines.push('FILE ' + f.path + ' [' + f.language + '/' + f.fileCategory + '] lines=' + f.totalLines +
      ' nonEmpty=' + f.nonEmptyLines + ' classes=' + (f.classes || []).length + ' functions=' + (f.functions || []).length);
    for (const c of cls) {
      lines.push('  CLASS ' + c.name + ' [' + c.startLine + '-' + c.endLine + '] methods=' + (c.methods || []).length +
        (c.bases && c.bases.length ? ' bases=' + c.bases.join(',') : ''));
    }
    for (const fn of fns) {
      lines.push('  FN ' + fn.name + ' [' + fn.startLine + '-' + fn.endLine + '] params=' + (fn.params || []).join(','));
    }
    if (f.sections && f.sections.length) lines.push('  SECTIONS=' + f.sections.length);
    const imp = (b.batchImportData || {})[f.path];
    if (imp && imp.length) lines.push('  IMPORTS=' + imp.join(' | '));
  }
}
fs.writeFileSync(path.join(ua, 'tmp', 'worklist.txt'), lines.join('\n') + '\n');
console.log('fn kept=' + fnKept + '/' + fnTotal + ' cls kept=' + clsKept + '/' + clsTotal +
  ' => approx nodes=' + (fnKept + clsKept + 130) + ' lines=' + lines.length);
