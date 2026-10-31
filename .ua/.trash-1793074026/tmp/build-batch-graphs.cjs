// 由 /understand Phase 2 使用：把逐批撰写的人工语义（ua-semantics-<i>.json）
// 与确定性提取结果、batchImportData 合成标准 batch-<i>.json 输出，
// 自动派生 contains / imports / exports 边并按规定阈值分片。
const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const ua = path.join(root, '.ua');
const tmp = path.join(ua, 'tmp');
const inter = path.join(ua, 'intermediate');

const batches = JSON.parse(fs.readFileSync(path.join(inter, 'batches.json'), 'utf8'));
const scanAll = JSON.parse(fs.readFileSync(path.join(inter, 'scan-result.json'), 'utf8'));
const categoryOf = new Map(scanAll.files.map((f) => [f.path, f.fileCategory]));
// 调试时可传 UA_BATCHES=1,2 只构建指定批次
const only = (process.env.UA_BATCHES || '').split(',').filter(Boolean).map(Number);
const PREFIX = {
  code: 'file', script: 'file', markup: 'file',
  config: 'config', docs: 'document', infra: 'service', data: 'table',
};
const NODE_TYPE = {
  code: 'file', script: 'file', markup: 'file',
  config: 'config', docs: 'document', infra: 'service', data: 'table',
};

const complexityFrom = (lines) => (lines < 50 ? 'simple' : lines <= 200 ? 'moderate' : 'complex');

let totalNodes = 0;
let totalEdges = 0;
const report = [];

for (const b of batches.batches) {
  if (only.length && !only.includes(b.batchIndex)) continue;
  const sem = JSON.parse(fs.readFileSync(path.join(tmp, 'ua-semantics-' + b.batchIndex + '.json'), 'utf8'));
  const extract = JSON.parse(fs.readFileSync(path.join(tmp, 'ua-file-extract-results-' + b.batchIndex + '.json'), 'utf8'));
  const byPath = new Map(extract.results.map((r) => [r.path, r]));
  const semFiles = new Map(sem.files.map((f) => [f.path, f]));

  const nodes = [];
  const edges = [];
  const nodeIds = new Set();
  const addNode = (n) => {
    if (nodeIds.has(n.id)) throw new Error('duplicate node id ' + n.id);
    nodeIds.add(n.id);
    nodes.push(n);
  };
  const addEdge = (source, target, type, weight) => {
    if (source === target) return;
    edges.push({ source, target, type, direction: 'forward', weight });
  };

  // 文件节点：批次内每个文件都必须有一个
  for (const f of b.files) {
    const s = semFiles.get(f.path);
    if (!s) throw new Error('batch ' + b.batchIndex + ' missing semantics for file ' + f.path);
    const id = (PREFIX[f.fileCategory] || 'file') + ':' + f.path;
    addNode({
      id,
      type: NODE_TYPE[f.fileCategory] || 'file',
      name: path.basename(f.path),
      filePath: f.path,
      summary: s.summary,
      tags: s.tags,
      complexity: s.complexity || complexityFrom(f.sizeLines),
      ...(s.languageNotes ? { languageNotes: s.languageNotes } : {}),
    });

    // 子节点（函数 / 类）
    const ex = byPath.get(f.path);
    const declared = new Map();
    for (const c of (ex && ex.classes) || []) declared.set('class:' + c.name, c);
    for (const fn of (ex && ex.functions) || []) declared.set('function:' + fn.name, fn);

    for (const sub of s.subs || []) {
      const key = sub.kind + ':' + sub.name;
      const d = declared.get(key);
      if (!d) {
        throw new Error('batch ' + b.batchIndex + ' ' + f.path + ' 声明中找不到 ' + key);
      }
      const subId = sub.kind + ':' + f.path + ':' + sub.name;
      addNode({
        id: subId,
        type: sub.kind,
        name: sub.name,
        filePath: f.path,
        lineRange: [d.startLine, d.endLine],
        summary: sub.summary,
        tags: sub.tags,
        complexity: sub.complexity || complexityFrom(d.endLine - d.startLine + 1),
        ...(sub.languageNotes ? { languageNotes: sub.languageNotes } : {}),
      });
      addEdge(id, subId, 'contains', 1.0);
    }

    // 类继承等语义关系统一由人工语义边（sem.edges）表达，保证可溯源
  }

  // imports 边：严格 1:1 使用 batchImportData
  const imp = b.batchImportData || {};
  let impCount = 0;
  for (const [src, targets] of Object.entries(imp)) {
    const srcNode = nodes.find((n) => n.filePath === src);
    if (!srcNode) continue;
    for (const t of targets) {
      const tPrefix = PREFIX[categoryOf.get(t) || 'code'] || 'file';
      addEdge(srcNode.id, tPrefix + ':' + t, 'imports', 0.7);
      impCount += 1;
    }
  }

  // 人工撰写的语义边
  let extra = 0;
  for (const e of sem.edges || []) {
    if (e.type === 'tested_by') {
      // 撰写方向：test -> production，统一规范化为 production -> test
      addEdge(e.target, e.source, 'tested_by', 0.5);
    } else {
      addEdge(e.source, e.target, e.type, e.weight);
    }
    extra += 1;
  }

  // 去重（source+target+type）
  const seen = new Set();
  const deduped = edges.filter((e) => {
    const k = e.source + '\u0000' + e.target + '\u0000' + e.type;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });

  // 分片：nodes>60 或 edges>120 时按文件字母序切分
  const parts = Math.max(1, Math.ceil(Math.max(nodes.length / 60, deduped.length / 120)));
  const filesSorted = [...b.files].sort((a, c) => a.path.localeCompare(c.path));
  const chunk = Math.ceil(filesSorted.length / parts);
  const written = [];
  if (parts === 1) {
    fs.writeFileSync(path.join(inter, 'batch-' + b.batchIndex + '.json'),
      JSON.stringify({ nodes, edges: deduped }, null, 2));
    written.push('batch-' + b.batchIndex + '.json');
  } else {
    for (let k = 0; k < parts; k++) {
      const own = new Set(filesSorted.slice(k * chunk, (k + 1) * chunk).map((f) => f.path));
      const pNodes = nodes.filter((n) => own.has(n.filePath));
      const pIds = new Set(pNodes.map((n) => n.id));
      const pEdges = deduped.filter((e) => pIds.has(e.source));
      const name = 'batch-' + b.batchIndex + '-part-' + (k + 1) + '.json';
      fs.writeFileSync(path.join(inter, name), JSON.stringify({ nodes: pNodes, edges: pEdges }, null, 2));
      written.push(name);
    }
  }
  totalNodes += nodes.length;
  totalEdges += deduped.length;
  report.push('batch ' + b.batchIndex + ': nodes=' + nodes.length + ' edges=' + deduped.length +
    ' (imports=' + impCount + ', extra=' + extra + ') parts=' + written.join(','));
}

console.log(report.join('\n'));
console.log('TOTAL nodes=' + totalNodes + ' edges=' + totalEdges);
