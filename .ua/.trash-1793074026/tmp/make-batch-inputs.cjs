// 由 /understand Phase 2 使用：为每个批次生成 extract-structure.mjs 输入，
// 并打印批次概览（文件清单 + 导入边数量），供语义分析参照。
const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const ua = path.join(root, '.ua');
const batches = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'batches.json'), 'utf8'));

const lines = [];
for (const b of batches.batches) {
  const input = {
    projectRoot: root,
    batchFiles: b.files,
    batchImportData: b.batchImportData || {},
  };
  fs.writeFileSync(
    path.join(ua, 'tmp', 'ua-file-analyzer-input-' + b.batchIndex + '.json'),
    JSON.stringify(input, null, 2),
  );

  const impEdges = Object.values(b.batchImportData || {})
    .reduce((acc, v) => acc + v.length, 0);
  lines.push('=== batch ' + b.batchIndex + ' | files=' + b.files.length +
    ' | importsEdges=' + impEdges +
    ' | neighborFiles=' + Object.keys(b.neighborMap || {}).length);
  for (const f of b.files) {
    lines.push('  ' + f.path + ' [' + f.language + '/' + f.fileCategory + '] ' + f.sizeLines + 'L');
  }
}
fs.writeFileSync(path.join(ua, 'tmp', 'batch-overview.txt'), lines.join('\n') + '\n');
console.log('batches=' + batches.batches.length + ' overview written');
