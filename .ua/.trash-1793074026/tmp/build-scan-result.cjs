// 由 /understand Phase 1 使用：合并 scan-project 与 extract-import-map
// 两份确定性输出，补入 LLM 叙述字段，写出 scan-result.json。
const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const ua = path.join(root, '.ua');
const scan = JSON.parse(fs.readFileSync(path.join(ua, 'tmp', 'ua-scan-files.json'), 'utf8'));
const imports = JSON.parse(fs.readFileSync(path.join(ua, 'tmp', 'ua-import-map-output.json'), 'utf8'));

const result = {
  name: 'pca-mcp-server',
  description:
    '协议转换平台 MCP Server：以 FastMCP/ASGI 网关对外暴露设备建档、协议转换配置生成、' +
    '品牌型号管理与边缘联通召测等工具，并托管 Agent 技能资源包的打包与分发。',
  languages: Object.keys(scan.stats.byLanguage).sort(),
  frameworks: ['FastMCP', 'uvicorn', 'httpx', 'pytest'],
  files: scan.files,
  totalFiles: scan.totalFiles,
  filteredByIgnore: scan.filteredByIgnore,
  estimatedComplexity: scan.estimatedComplexity,
  importMap: imports.importMap,
};

if (result.totalFiles !== result.files.length) {
  throw new Error('totalFiles mismatch: ' + result.totalFiles + ' vs ' + result.files.length);
}

fs.writeFileSync(path.join(ua, 'intermediate', 'scan-result.json'), JSON.stringify(result, null, 2));
console.log(
  'scan-result.json written: totalFiles=' + result.totalFiles +
  ' importEntries=' + Object.keys(result.importMap).length
);
