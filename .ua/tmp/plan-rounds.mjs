// 按批次列出待分析的每个文件及其显著符号数，用于规划分轮执行。
import { readFileSync, readdirSync } from "node:fs";

const root = "e:/codeGIT/pca-mcp-server";
const batches = JSON.parse(
  readFileSync(`${root}/.ua/intermediate/batches.json`, "utf8"),
);

let totFile = 0, totSig = 0;
for (const b of batches.batches) {
  const r = JSON.parse(
    readFileSync(`${root}/.ua/tmp/ua-file-extract-results-${b.batchIndex}.json`, "utf8"),
  );
  const byPath = new Map(r.results.map((f) => [f.path, f]));
  let batchSig = 0;
  const lines = [];
  for (const f of b.files) {
    const res = byPath.get(f.path);
    let sig = 0;
    if (res) {
      const exported = new Set((res.exports || []).map((e) => e.name));
      for (const fn of res.functions || []) {
        const n = (fn.endLine || 0) - (fn.startLine || 0) + 1;
        if (n >= 10 || exported.has(fn.name)) sig++;
      }
      for (const c of res.classes || []) {
        const n = (c.endLine || 0) - (c.startLine || 0) + 1;
        if ((c.methods || []).length >= 2 || n >= 20 || exported.has(c.name)) sig++;
      }
    }
    batchSig += sig;
    totSig += sig;
    totFile++;
    lines.push(
      `    ${String(sig).padStart(3)}  ${f.path} (${f.sizeLines}L, ${f.fileCategory})${res ? "" : "  <<SKIPPED-no-parser>>"}`,
    );
  }
  console.log(
    `BATCH ${b.batchIndex}: files=${b.files.length} significantSymbols=${batchSig} imports=${Object.values(b.batchImportData || {}).reduce((a, v) => a + v.length, 0)}`,
  );
  console.log(lines.join("\n"));
}
console.log(`\nTOTAL fileNodes=${totFile} symbolNodes=${totSig} => ${totFile + totSig} nodes`);
