// 交叉核对 Node 与 CPython 对同一文件的读取摘要，并生成干净副本供结构提取使用。
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');

const root = process.argv[2];
const ua = path.join(root, '.ua');
const scan = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'scan-result.json'), 'utf8'));
const rels = scan.files.map((f) => f.path);

const pySrc = String.raw`
import hashlib, json, os, sys
out = {}
for p in sys.argv[1:]:
    with open(p, "rb") as fh:
        b = fh.read()
    out[os.path.relpath(p, sys.argv[0][1:][0]) if False else p] = [len(b), hashlib.sha1(b).hexdigest()]
print(json.dumps(out))
`;

const res = spawnSync('python', ['-c', pySrc, ...rels.map((r) => path.join(root, r))],
  { encoding: 'utf8', maxBuffer: 128 * 1024 * 1024 });
if (res.status !== 0) {
  console.error('python failed: ' + res.stderr);
  process.exit(1);
}
const py = JSON.parse(res.stdout.trim());

const mismatch = [];
for (const rel of rels) {
  const buf = fs.readFileSync(path.join(root, rel));
  const digest = crypto.createHash('sha1').update(buf).digest('hex');
  const real = py[path.join(root, rel)];
  if (!real || real[1] !== digest) mismatch.push({ path: rel, nodeBytes: buf.length, realBytes: real ? real[0] : -1 });
}

const clean = path.join(ua, 'tmp', 'clean');
for (const m of mismatch) {
  const dest = path.join(clean, m.path);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  spawnSync('python', ['-c',
    'import sys; open(sys.argv[2], "wb").write(open(sys.argv[1], "rb").read())',
    path.join(root, m.path), dest]);
  // 用 Python 自身回读校验副本内容与真实内容一致
  const verify = spawnSync('python', ['-c',
    'import sys,hashlib; sys.stdout.write(hashlib.sha1(open(sys.argv[1], "rb").read()).hexdigest())', dest],
  { encoding: 'utf8' });
  m.copyVerified = verify.stdout.trim() === py[path.join(root, m.path)][1];
}

fs.writeFileSync(path.join(ua, 'tmp', 'read-mismatch.json'), JSON.stringify(mismatch, null, 2));
console.log('files=' + rels.length + ' mismatched=' + mismatch.length);
for (const m of mismatch) console.log('  ' + m.path + ' node=' + m.nodeBytes + ' real=' + m.realBytes + ' verified=' + m.copyVerified);
