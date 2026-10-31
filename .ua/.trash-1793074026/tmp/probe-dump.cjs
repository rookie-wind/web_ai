// 打印 probe 提取结果的关键字段，定位 server.py 提取为空的根因。
const r = require(process.argv[2] + '/.ua/tmp/probe-out.json');
for (const f of r.results) {
  console.log('---', f.path, 'lines=' + f.totalLines, 'keys=' + Object.keys(f).join(','));
  console.log('  functions=' + JSON.stringify(f.functions));
  console.log('  classes=' + JSON.stringify((f.classes || []).map((c) => c.name)));
  console.log('  metrics=' + JSON.stringify(f.metrics));
  if (f.parseError) console.log('  parseError=' + JSON.stringify(f.parseError));
  if (f.error) console.log('  error=' + JSON.stringify(f.error));
}
console.log('skipped=' + JSON.stringify(r.filesSkipped));
console.log('unreadable=' + JSON.stringify(r.filesUnreadable));
