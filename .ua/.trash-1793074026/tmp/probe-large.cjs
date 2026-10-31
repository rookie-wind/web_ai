// 探测 extract-structure.mjs 对大 Python 文件的提取结果（仅诊断用）。
const path = require('path');
const root = process.argv[2];
for (let i = 1; i <= 11; i++) {
  const r = require(path.join(root, '.ua', 'tmp', 'ua-file-extract-results-' + i + '.json'));
  for (const f of r.results) {
    if (['mcp_server/server.py', 'mcp_server/api_client.py', 'mcp_server/session.py',
      'mcp_server/edge_client.py', 'mcp_server/permissions.py', 'mcp_server/edge_tools.py'].includes(f.path)) {
      console.log(f.path, 'totalLines=' + f.totalLines, 'nonEmpty=' + f.nonEmptyLines,
        'functions=' + (f.functions || []).length, 'classes=' + (f.classes || []).length,
        'classMethods=' + (f.classes || []).reduce((a, c) => a + (c.methods || []).length, 0),
        'callGraph=' + (f.callGraph || []).length, 'error=' + (f.error || '-'));
    }
  }
}
