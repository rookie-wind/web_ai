// 把主会话撰写的语义表（sem-<i>.json）与结构提取结果合成为 batch-<i>.json。
// 机械规则由本脚本保证：ID 前缀、必填字段、contains/exports/imports 边、
// imports 1:1 自检、节点/边阈值分片（>60 节点或 >120 边）。
import { readFileSync, writeFileSync } from "node:fs";

const root = "e:/codeGIT/pca-mcp-server";
const idx = process.argv[2];
if (!idx) {
  console.error("usage: build-batch.mjs <batchIndex>");
  process.exit(1);
}

const extract = JSON.parse(
  readFileSync(`${root}/.ua/tmp/ua-file-extract-results-${idx}.json`, "utf8"),
);
const input = JSON.parse(
  readFileSync(`${root}/.ua/tmp/ua-file-analyzer-input-${idx}.json`, "utf8"),
);
const sem = JSON.parse(
  readFileSync(`${root}/.ua/tmp/sem-${idx}.json`, "utf8"),
);

const CATEGORY_NODE_TYPE = {
  code: "file",
  script: "file",
  markup: "file",
  config: "config",
  docs: "document",
};

function baseName(p) {
  return p.split(/[\\/]/).pop();
}

function fileIdOf(path, category) {
  const t = CATEGORY_NODE_TYPE[category] || "file";
  return `${t}:${path}`;
}

function complexityFromLines(nonEmpty) {
  if (nonEmpty < 50) return "simple";
  if (nonEmpty <= 200) return "moderate";
  return "complex";
}

const resByPath = new Map(extract.results.map((f) => [f.path, f]));
const errors = [];
const nodes = [];
const edges = [];
const seenIds = new Set();

function pushNode(n) {
  if (seenIds.has(n.id)) {
    errors.push(`duplicate node id: ${n.id}`);
    return;
  }
  seenIds.add(n.id);
  if (!n.summary) errors.push(`empty summary: ${n.id}`);
  if (!n.tags || n.tags.length < 3) errors.push(`tags <3: ${n.id}`);
  nodes.push(n);
}

function pushEdge(source, target, type, weight) {
  if (source === target) {
    errors.push(`self edge dropped: ${source} ${type}`);
    return;
  }
  edges.push({ source, target, type, direction: "forward", weight });
}

// --- 1. 每个批次文件必须有节点 ---
for (const f of input.batchFiles) {
  const res = resByPath.get(f.path);
  const s = sem.files[f.path];
  if (!s) {
    errors.push(`missing semantic entry for file: ${f.path}`);
    continue;
  }
  const nonEmpty = res ? res.nonEmptyLines : f.sizeLines;
  const node = {
    id: fileIdOf(f.path, f.fileCategory),
    type: CATEGORY_NODE_TYPE[f.fileCategory] || "file",
    name: baseName(f.path),
    filePath: f.path,
    summary: s.summary,
    tags: s.tags,
    complexity: s.complexity || complexityFromLines(nonEmpty),
  };
  if (s.languageNotes) node.languageNotes = s.languageNotes;
  pushNode(node);
}

// --- 2. 显著符号节点 ---
const sigSet = new Set();
for (const res of extract.results) {
  const exported = new Set((res.exports || []).map((e) => e.name));
  const kinds = [];
  for (const fn of res.functions || []) {
    const lines = (fn.endLine || 0) - (fn.startLine || 0) + 1;
    if (lines >= 10 || exported.has(fn.name)) {
      kinds.push({ name: fn.name, type: "function", node: fn, isExported: exported.has(fn.name) });
    }
  }
  for (const c of res.classes || []) {
    const lines = (c.endLine || 0) - (c.startLine || 0) + 1;
    if ((c.methods || []).length >= 2 || lines >= 20 || exported.has(c.name)) {
      kinds.push({ name: c.name, type: "class", node: c, isExported: exported.has(c.name) });
    }
  }
  for (const k of kinds) {
    const key = `${res.path}::${k.name}`;
    sigSet.add(key);
    const s = sem.symbols[key];
    if (!s) {
      errors.push(`missing semantic entry for symbol: ${key}`);
      continue;
    }
    const id = `${k.type}:${res.path}:${k.name}`;
    const lines = (k.node.endLine || 0) - (k.node.startLine || 0) + 1;
    pushNode({
      id,
      type: k.type,
      name: k.name,
      lineRange: [k.node.startLine, k.node.endLine],
      summary: s.summary,
      tags: s.tags,
      complexity: s.complexity || complexityFromLines(lines),
      filePath: res.path,
    });
    const parentId = fileIdOf(res.path, res.fileCategory);
    pushEdge(parentId, id, "contains", 1.0);
    if (k.isExported) pushEdge(parentId, id, "exports", 0.8);
  }
}

// 语义表里多余（不再显著）的条目视为错误，避免静默产出无依据节点
for (const key of Object.keys(sem.symbols)) {
  if (!sigSet.has(key)) errors.push(`sem entry not in significant set: ${key}`);
}

// --- 3. imports 边 1:1 全量发射 ---
let expectedImports = 0;
for (const [srcPath, targets] of Object.entries(input.batchImportData || {})) {
  const srcFile = input.batchFiles.find((f) => f.path === srcPath);
  if (!srcFile) continue;
  const srcId = fileIdOf(srcPath, srcFile.fileCategory);
  for (const t of targets) {
    expectedImports++;
    pushEdge(srcId, `file:${t}`, "imports", 0.7);
  }
}
const emittedImports = edges.filter((e) => e.type === "imports").length;
if (emittedImports !== expectedImports) {
  errors.push(`imports mismatch: emitted=${emittedImports} expected=${expectedImports}`);
}

// --- 4. 语义表声明的额外边（inherits / calls / depends_on 等） ---
for (const e of sem.edges || []) {
  pushEdge(e.source, e.target, e.type, e.weight);
}

if (errors.length) {
  console.error(`BUILD FAILED for batch ${idx}:`);
  console.error(errors.map((x) => `  - ${x}`).join("\n"));
  process.exit(1);
}

// --- 5. 阈值分片：nodes>60 或 edges>120 ---
const parts = Math.max(1, Math.ceil(Math.max(nodes.length / 60, edges.length / 120)));
const sortedFiles = [...input.batchFiles].map((f) => f.path).sort();
const nodeIdsByPart = [];

if (parts === 1) {
  writeFileSync(
    `${root}/.ua/intermediate/batch-${idx}.json`,
    JSON.stringify({ nodes, edges }, null, 2),
    "utf8",
  );
  nodeIdsByPart.push(new Set(nodes.map((n) => n.id)));
  console.log(`wrote batch-${idx}.json nodes=${nodes.length} edges=${edges.length}`);
} else {
  const nodesById = new Map(nodes.map((n) => [n.id, n]));
  const fileOf = (n) => n.filePath;
  const per = Math.ceil(sortedFiles.length / parts);
  for (let k = 0; k < parts; k++) {
    const group = new Set(sortedFiles.slice(k * per, (k + 1) * per));
    const pNodes = nodes.filter((n) => group.has(fileOf(n)));
    const ids = new Set(pNodes.map((n) => n.id));
    const pEdges = edges.filter((e) => ids.has(e.source));
    if (!pNodes.length && !pEdges.length) continue;
    writeFileSync(
      `${root}/.ua/intermediate/batch-${idx}-part-${k + 1}.json`,
      JSON.stringify({ nodes: pNodes, edges: pEdges }, null, 2),
      "utf8",
    );
    nodeIdsByPart.push(ids);
    console.log(`wrote batch-${idx}-part-${k + 1}.json nodes=${pNodes.length} edges=${pEdges.length}`);
  }
  void nodesById;
}
console.log(
  `batch ${idx} summary: fileNodes=${input.batchFiles.length} symbolNodes=${sigSet.size} nodes=${nodes.length} edges=${edges.length} imports=${emittedImports}/${expectedImports}`,
);
