// 交叉核对：Node 读取 vs CPython 读取，定位本机 Node 文件读取返回未初始化内存的文件。
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = process.argv[2];
const scan = JSON.parse(fs.readFileSync(path.join(root, '.ua', 'intermediate', 'scan-result.json'), 'utf8'));
const files = scan.files.map((f) => f.path);

// CPython 侧真实字节数
const py = spawnSync('python', ['-c',
  'import os,sys,json;' +
  'print(json.dumps({p: os.path.getsize(p) for p in sys.argv[1:]}))',
  ...files], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
if (py.status !== 0) {
  console.error('python failed: ' + py.stderr);
  process.exit(1);
}
const real = JSON.parse(py.stdout.trim());

const bad = [];
for (const p of files) {
  const n = fs.statSync(path.join(root, p)).size;
  if (n !== real[p]) bad.push({ path: p, nodeBytes: n, realBytes: real[p] });
}
console.log('files=' + files.length + ' mismatched=' + bad.length);
for (const b of bad) console.log('  ' + b.path + ' node=' + b.nodeBytes + ' real=' + b.realBytes);
fs.writeFileSync(path.join(root, '.ua', 'tmp', 'read-mismatch.json'), JSON.stringify(bad, null, 2));
