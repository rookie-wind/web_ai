// 为每个批次生成 file-analyzer 输入 JSON。
// batchFiles 逐字取自 batches.json 的 files[]，batchImportData 直接透传。
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";

const root = "e:/codeGIT/pca-mcp-server";
const data = JSON.parse(readFileSync(`${root}/.ua/intermediate/batches.json`, "utf8"));

console.log("batch keys:", Object.keys(data.batches[0]).join(", "));

let totalImports = 0;
for (const b of data.batches) {
  const files = b.files.map((f) => ({
    path: f.path,
    language: f.language,
    sizeLines: f.sizeLines,
    fileCategory: f.fileCategory,
  }));
  const importData = b.batchImportData || {};
  const sum = Object.values(importData).reduce((a, v) => a + v.length, 0);
  totalImports += sum;

  mkdirSync(`${root}/.ua/tmp`, { recursive: true });
  writeFileSync(
    `${root}/.ua/tmp/ua-file-analyzer-input-${b.batchIndex}.json`,
    JSON.stringify(
      {
        projectRoot: root.replace(/\\/g, "/"),
        batchFiles: files,
        batchImportData: importData,
      },
      null,
      2,
    ),
    "utf8",
  );
  console.log(
    `batch ${b.batchIndex}: files=${files.length} importEdges=${sum} neighborMap=${Object.keys(b.neighborMap || {}).length}`,
  );
}
console.log(`TOTAL imports edges expected = ${totalImports}`);
