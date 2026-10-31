// 诊断 Node 侧不同读取路径返回的内容是否一致（仅诊断用）。
const fs = require('fs');
const crypto = require('crypto');
const { execFileSync, spawnSync } = require('child_process');

const p = 'mcp_server/server.py';
const h = (b) => crypto.createHash('sha1').update(b).digest('hex').slice(0, 12);

const a = fs.readFileSync(p);
console.log('readFileSync(buffer) bytes=' + a.length + ' sha=' + h(a));

const b = fs.readFileSync(p, 'utf8');
console.log('readFileSync(utf8) chars=' + b.length +
  ' bytes=' + Buffer.byteLength(b) + ' sha=' + h(Buffer.from(b)));

const c = fs.readFileSync(p, { encoding: 'utf8', flag: 'r' });
console.log('explicit flag chars=' + c.length + ' sha=' + h(Buffer.from(c)));

const d = execFileSync('cmd.exe', ['/c', 'type', p], { maxBuffer: 64 * 1024 * 1024 });
console.log('cmd type bytes=' + d.length + ' sha=' + h(d));

const e = spawnSync('python', ['-c', 'import sys;sys.stdout.buffer.write(open(sys.argv[1],"rb").read())', p],
  { encoding: 'buffer', maxBuffer: 64 * 1024 * 1024 }).stdout;
console.log('python pipe bytes=' + e.length + ' sha=' + h(e));

const fd = fs.openSync(p, fs.constants.O_RDONLY | (fs.constants.O_DIRECT || 0));
const buf = Buffer.alloc(122640);
const n = fs.readSync(fd, buf, 0, buf.length, 0);
fs.closeSync(fd);
console.log('fd readSync bytes=' + n + ' sha=' + h(buf.slice(0, n)));
