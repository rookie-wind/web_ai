// Phase 7 step 2：准备指纹基线输入（全部已分析文件，含非代码文件）。
const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const commit = process.argv[3];
const scan = JSON.parse(fs.readFileSync(path.join(root, '.ua/intermediate/scan-result.json'), 'utf8'));

const input = {
  projectRoot: root,
  filePaths: scan.files.map((f) => f.path),
  gitCommitHash: commit,
};

fs.writeFileSync(path.join(root, '.ua/intermediate/fingerprint-input.json'), JSON.stringify(input, null, 2));
console.log('fingerprint input: files=' + input.filePaths.length + ' commit=' + commit);
