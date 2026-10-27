// 组装 Phase 1 最终 scan-result.json：
// files / importMap 逐字取自两个内置脚本输出，仅叙事字段由主会话提供。
import { readFileSync, writeFileSync } from "node:fs";

const root = "e:/codeGIT/pca-mcp-server";
const scan = JSON.parse(readFileSync(`${root}/.ua/tmp/ua-scan-files.json`, "utf8"));
const imp = JSON.parse(readFileSync(`${root}/.ua/tmp/ua-import-map-output.json`, "utf8"));

const narrative = JSON.parse(
  readFileSync(`${root}/.ua/tmp/ua-narrative.json`, "utf8"),
);

// 规范要求：files 数组逐字保留、importMap 逐字相等、剥离 scriptCompleted/stats
const final = {
  name: narrative.name,
  description: narrative.description,
  languages: narrative.languages,
  frameworks: narrative.frameworks,
  files: scan.files,
  totalFiles: scan.totalFiles,
  filteredByIgnore: scan.filteredByIgnore,
  estimatedComplexity: scan.estimatedComplexity,
  importMap: imp.importMap,
};

// 约束校验：totalFiles 必须与 files 长度一致；importMap 键数必须覆盖全部文件
if (final.totalFiles !== final.files.length) {
  console.error(
    `FAIL: totalFiles=${final.totalFiles} != files.length=${final.files.length}`,
  );
  process.exit(1);
}
const filePaths = new Set(final.files.map((f) => f.path));
const mapKeys = new Set(Object.keys(final.importMap));
const missing = [...filePaths].filter((p) => !mapKeys.has(p));
const extra = [...mapKeys].filter((p) => !filePaths.has(p));
console.log(`files=${final.files.length} importMapKeys=${mapKeys.size}`);
console.log(`filesWithoutImportEntry=${missing.length} extraEntries=${extra.length}`);
if (missing.length || extra.length) {
  console.error("FAIL: importMap 与 files 清单不一致");
  console.error(" missing:", JSON.stringify(missing.slice(0, 10)));
  console.error(" extra:", JSON.stringify(extra.slice(0, 10)));
  process.exit(1);
}

writeFileSync(
  `${root}/.ua/intermediate/scan-result.json`,
  JSON.stringify(final, null, 2),
  "utf8",
);
console.log("OK: wrote .ua/intermediate/scan-result.json");
