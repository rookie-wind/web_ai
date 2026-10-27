// 重跑确定性阶段链：scan → importMap → scan-result → batches → batch inputs → extract-structure
// 把内置脚本调用集中在一个驱动里，避免多轮 shell 往返。
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

const root = "e:/codeGIT/pca-mcp-server";
const skill = `${root}/.qoder/skills/understand`;

function run(label, script, args) {
  const r = spawnSync(process.execPath, [script, ...args], {
    encoding: "utf8",
    cwd: root,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (r.status !== 0) {
    console.error(`FAIL ${label}: status=${r.status}`);
    console.error(r.stderr);
    process.exit(1);
  }
  const warns = (r.stderr || "")
    .split("\n")
    .filter((l) => l.startsWith("Warning:") || l.startsWith("Info:") || /filesScanned|Wrote/.test(l));
  console.log(`[${label}] ${warns.join(" | ") || "ok"}`);
  return r;
}

// 1. scan
run("scan-project", `${skill}/scan-project.mjs`, [
  root,
  `${root}/.ua/tmp/ua-scan-files.json`,
]);

// 2. import map input (BOM-free)
const scan = JSON.parse(readFileSync(`${root}/.ua/tmp/ua-scan-files.json`, "utf8"));
const payload = {
  projectRoot: root,
  files: scan.files.map((f) => ({
    path: f.path,
    language: f.language,
    fileCategory: f.fileCategory,
  })),
};
writeFileSync(
  `${root}/.ua/tmp/ua-import-map-input.json`,
  JSON.stringify(payload),
  "utf8",
);

// 3. import map
run("extract-import-map", `${skill}/extract-import-map.mjs`, [
  `${root}/.ua/tmp/ua-import-map-input.json`,
  `${root}/.ua/tmp/ua-import-map-output.json`,
]);

// 4. compose scan-result（含 totalFiles / importMap 一致性校验）
run("compose-scan", `${root}/.ua/tmp/compose-scan.mjs`, []);

// 5. batches
run("compute-batches", `${skill}/compute-batches.mjs`, [root]);

// 6. per-batch analyzer inputs
run("gen-batch-inputs", `${root}/.ua/tmp/gen-batch-inputs.mjs`, []);

// 7. structural extraction for every batch
const batches = JSON.parse(
  readFileSync(`${root}/.ua/intermediate/batches.json`, "utf8"),
);
for (const b of batches.batches) {
  run(`extract-structure-${b.batchIndex}`, `${skill}/extract-structure.mjs`, [
    `${root}/.ua/tmp/ua-file-analyzer-input-${b.batchIndex}.json`,
    `${root}/.ua/tmp/ua-file-extract-results-${b.batchIndex}.json`,
  ]);
}

console.log(`\nTOTAL batches=${batches.totalBatches} files=${batches.totalFiles}`);
