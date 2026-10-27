// 汇总各批次结构提取结果，并按 file-analyzer 的显著性过滤规则预估节点数。
// 显著性：函数/方法 >=10 行，或类 >=2 方法 / >=20 行，或被导出。
import { readFileSync } from "node:fs";

const root = "e:/codeGIT/pca-mcp-server";
let totFiles = 0, totFn = 0, totCls = 0, totSig = 0;
const rows = [];

for (let i = 1; i <= 10; i++) {
  const r = JSON.parse(
    readFileSync(`${root}/.ua/tmp/ua-file-extract-results-${i}.json`, "utf8"),
  );
  let sigFn = 0, sigCls = 0;
  for (const f of r.results) {
    const exported = new Set((f.exports || []).map((e) => e.name));
    for (const fn of f.functions || []) {
      totFn++;
      const lines = (fn.endLine || 0) - (fn.startLine || 0) + 1;
      if (lines >= 10 || exported.has(fn.name)) sigFn++;
    }
    for (const c of f.classes || []) {
      totCls++;
      const lines = (c.endLine || 0) - (c.startLine || 0) + 1;
      if ((c.methods || []).length >= 2 || lines >= 20 || exported.has(c.name)) {
        sigCls++;
      }
    }
  }
  totFiles += r.results.length;
  totSig += sigFn + sigCls;
  const cats = {};
  for (const f of r.results) cats[f.fileCategory] = (cats[f.fileCategory] || 0) + 1;
  rows.push(
    `batch ${i}: files=${r.results.length} fn=${(r.results.reduce((a, f) => a + (f.functions || []).length, 0))} cls=${(r.results.reduce((a, f) => a + (f.classes || []).length, 0))} significant=${sigFn + sigCls} cats=${JSON.stringify(cats)} skipped=${(r.filesSkipped || []).length} unreadable=${(r.filesUnreadable || []).length}`,
  );
}

console.log(rows.join("\n"));
console.log(
  `\nTOTAL files=${totFiles} functions=${totFn} classes=${totCls} significantSymbols=${totSig}`,
);
console.log(
  `预估节点数 = 文件节点 ${totFiles} + 显著符号 ${totSig} = ${totFiles + totSig}`,
);
