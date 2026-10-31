// 用 CPython ast 提取器替换 tree-sitter 对 Python 文件的提取结果，
// 并回填被 Node 读取缺陷（中文名文件）漏掉的 markdown 文档条目。
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = process.argv[2];
const ua = path.join(root, '.ua');
const tmp = path.join(ua, 'tmp');

const batches = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'batches.json'), 'utf8'));
const scan = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'scan-result.json'), 'utf8'));

// 1) 汇总全部 python / c 文件，单次调用 CPython 提取器
const targetFiles = [];
for (const b of batches.batches) {
  for (const f of b.files) {
    if (['python', 'c'].includes(f.language)) targetFiles.push(f);
  }
}
const specPath = path.join(tmp, 'ua-py-extract-input.json');
fs.writeFileSync(specPath, JSON.stringify({ projectRoot: root, batchFiles: targetFiles }, null, 2));

const outPath = path.join(tmp, 'ua-py-extract-results.json');
const run = spawnSync('python', [path.join(tmp, 'ua-py-extract.py'), root, specPath, outPath],
  { encoding: 'utf8' });
console.log('extractor: ' + (run.stdout || '').trim() + (run.stderr ? ' stderr=' + run.stderr.trim() : ''));
if (run.status !== 0) process.exit(1);
const extracted = JSON.parse(fs.readFileSync(outPath, 'utf8'));
const byPath = new Map(extracted.results.map((r) => [r.path.replace(/\\/g, '/'), r]));
const skippedExtract = extracted.filesSkipped || [];

// 2) 逐批合并：python/c 文件用 CPython 结果替换，其余文件保留 tree-sitter 结果
let replaced = 0;
let kept = 0;
for (const b of batches.batches) {
  // 剔除 docx 二进制原件（同名 .md 文本已纳入，避免重复节点）
  b.files = b.files.filter((f) => !/\.docx$/i.test(f.path));
  const file = path.join(tmp, 'ua-file-extract-results-' + b.batchIndex + '.json');
  const prev = JSON.parse(fs.readFileSync(file, 'utf8'));
  const results = [];
  for (const r of prev.results) {
    if (['python', 'c'].includes(r.language) && byPath.has(r.path)) {
      results.push(byPath.get(r.path));
      replaced += 1;
    } else if (/\.docx$/i.test(r.path)) {
      continue;
    } else {
      results.push(r);
      kept += 1;
    }
  }
  // 补齐 tree-sitter 因 Node 读取缺陷而漏掉的中文名 markdown 文档
  for (const f of b.files) {
    if (results.some((r) => r.path === f.path)) continue;
    results.push({
      path: f.path,
      language: f.language,
      fileCategory: f.fileCategory,
      totalLines: f.sizeLines,
      nonEmptyLines: f.sizeLines,
      metrics: {},
      recovered: 'no-parser-stale-read',
    });
  }
  const skipped = (prev.filesSkipped || [])
    .filter((p) => !results.some((r) => r.path === p))
    .filter((p) => !/\.docx$/i.test(p));
  const out = {
    scriptCompleted: true,
    extractorNote: 'python/c via cpython; docx excluded (binary source, .md text twin retained)',
    filesAnalyzed: results.length,
    filesSkipped: skipped,
    filesUnreadable: prev.filesUnreadable || [],
    results,
  };
  fs.writeFileSync(file, JSON.stringify(out, null, 2));
}

// 2.5) 同步收缩 scan-result 与 batches：剔除 docx 原件，刷新计数
scan.files = scan.files.filter((f) => !/\.docx$/i.test(f.path));
scan.totalFiles = scan.files.length;
if (scan.importMap) {
  for (const p of Object.keys(scan.importMap)) {
    if (/\.docx$/i.test(p)) delete scan.importMap[p];
  }
}
fs.writeFileSync(path.join(ua, 'intermediate', 'scan-result.json'), JSON.stringify(scan, null, 2));
batches.batches.forEach((b) => { b.files = b.files.filter((f) => !/\.docx$/i.test(f.path)); });
if (typeof batches.totalFiles === 'number') batches.totalFiles = scan.totalFiles;
fs.writeFileSync(path.join(ua, 'intermediate', 'batches.json'), JSON.stringify(batches, null, 2));

// 3) 校验覆盖度
const allPaths = new Set(scan.files.map((f) => f.path));
const covered = new Set();
for (const b of batches.batches) {
  const r = JSON.parse(fs.readFileSync(path.join(tmp, 'ua-file-extract-results-' + b.batchIndex + '.json'), 'utf8'));
  r.results.forEach((x) => covered.add(x.path));
}
console.log('pyReplaced=' + replaced + ' kept=' + kept +
  ' batchPaths=' + covered.size + ' scanPaths=' + allPaths.size +
  ' extractSkipped=' + skippedExtract.length);
console.log('uncovered=' + JSON.stringify([...allPaths].filter((p) => !covered.has(p))));
if (skippedExtract.length) console.log('extract errors=' + JSON.stringify(skippedExtract));
