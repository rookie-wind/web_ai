// 诊断：Node 直读 / 重复读 / 经 CPython 管道读，三者内容是否一致（仅诊断用）。
const fs = require('fs');
const crypto = require('crypto');
const { spawnSync } = require('child_process');

const p = process.argv[2] + '/mcp_server/server.py';
const h = (b) => crypto.createHash('sha1').update(b).digest('hex').slice(0, 12);

for (let i = 0; i < 3; i++) {
  const b = fs.readFileSync(p);
  console.log('node read#' + i + ' bytes=' + b.length + ' sha=' + h(b));
}

const py = spawnSync('python', ['-c',
  'import sys; sys.stdout.buffer.write(open(sys.argv[1], "rb").read())', p],
{ encoding: 'buffer', maxBuffer: 64 * 1024 * 1024 });
console.log('via python pipe bytes=' + py.stdout.length + ' sha=' + h(py.stdout));

const out = process.argv[2] + '/.ua/tmp/server-clean.py';
const cp = spawnSync('python', ['-c',
  'import sys; open(sys.argv[2], "wb").write(open(sys.argv[1], "rb").read())', p, out],
  { encoding: 'utf8' });
console.log('python copy status=' + cp.status + ' ' + (cp.stderr || '').trim());
console.log('clean copy bytes=' + fs.statSync(out).size);
