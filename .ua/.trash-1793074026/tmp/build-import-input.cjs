// 由 /understand Phase 1 Step C 使用：把 scan-project.mjs 的文件清单
// 原样转交为 extract-import-map.mjs 的输入。
const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const scan = JSON.parse(fs.readFileSync(path.join(root, '.ua', 'tmp', 'ua-scan-files.json'), 'utf8'));

const input = {
  projectRoot: root,
  files: scan.files.map((f) => ({ path: f.path, language: f.language, fileCategory: f.fileCategory })),
};

fs.writeFileSync(path.join(root, '.ua', 'tmp', 'ua-import-map-input.json'), JSON.stringify(input, null, 2));
console.log('import-map input written: files=' + input.files.length);
