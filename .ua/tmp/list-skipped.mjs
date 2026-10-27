// 列出结构提取中被跳过的文件，以及各批次文件节点规模，用于判断 Phase 2 成本。
import { readFileSync } from "node:fs";

const root = "e:/codeGIT/pca-mcp-server";
const skipped = [];
const big = [];

for (let i = 1; i <= 10; i++) {
  const inp = JSON.parse(
    readFileSync(`${root}/.ua/tmp/ua-file-analyzer-input-${i}.json`, "utf8"),
  );
  const r = JSON.parse(
    readFileSync(`${root}/.ua/tmp/ua-file-extract-results-${i}.json`, "utf8"),
  );
  const got = new Set(r.results.map((f) => f.path));
  for (const f of inp.batchFiles) {
    if (!got.has(f.path)) {
      skipped.push(`batch ${i}  ${f.path}  [${f.fileCategory}/${f.language}] ${f.sizeLines}L`);
    }
  }
  for (const f of r.results) {
    const ne = f.nonEmptyLines || 0;
    if (ne > 200) big.push(`batch ${i}  ${f.path}  nonEmpty=${ne}  fn=${(f.functions || []).length} cls=${(f.classes || []).length}`);
  }
}

console.log(`=== SKIPPED (${skipped.length}) ===`);
console.log(skipped.join("\n") || "(none)");
console.log(`\n=== 超过 200 非空行的复杂文件 (${big.length}) ===`);
console.log(big.sort().join("\n") || "(none)");
