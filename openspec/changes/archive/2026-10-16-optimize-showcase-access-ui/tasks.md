## 1. Preflight and Current State Reconciliation

- [x] 1.1 Inspect `mcp_server/static/showcase.html` for partial hero/architecture CSS edits from the interrupted implementation attempt, and verify the final file has one coherent set of hero, terminal, metrics, and pipeline styles with no duplicate conflicting rules.
- [x] 1.2 Inspect `mcp_server/static/access.html` current DOM ids and JavaScript functions, and verify the implementation plan preserves access info loading, platform selection, config generation, copy, and download behavior.
- [x] 1.3 Confirm no backend route changes are needed by verifying `/`, `/showcase`, `/access`, `/api/access-info`, and export endpoints already exist and remain in scope.

## 2. Showcase Page Narrative and Platform Data

- [x] 2.1 Update the Before/After subtitle to “左边是接入一个新设备协议的手工全过程，右边交给 AI 智能体，一句话跑完全程。” and verify the section title remains “同一件事，两种做法”.
- [x] 2.2 Fix the typo `重复 查看文档` to `重复查看文档` and verify no other Before/After copy is rewritten.
- [x] 2.3 Update showcase compatibility counts from 7 to 8 where they refer to client/platform compatibility, and verify the closing sub-line wording remains otherwise unchanged.
- [x] 2.4 Add Qoder to the showcase platform list with `by: '阿里巴巴'`, `k: 'mcpServers'`, and `i: 'Q'`, then verify the ecosystem card list renders 8 platforms.

## 3. Showcase Hero and Architecture Redesign

- [x] 3.1 Rework the hero to the option-2 layout: left column contains eyebrow, title, subtitle, and 2x2 metrics; right column contains the enlarged terminal; verify all existing hero ids still render through `SHOWCASE_DATA`.
- [x] 3.2 Update the hero terminal command to use the semantic request “请帮我分析这份协议文档” and verify the typewriter animation still runs.
- [x] 3.3 Move the architecture diagram out of the hero and into an independent `#architecture` section placed before the capability matrix; verify the top navigation links to it.
- [x] 3.4 Redesign the architecture diagram as a large delivery-loop flow showing user demand, AI intent understanding, protocol identification/routing, MCP gateway, config generation, test validation, packaging, and online operation; verify it does not expand 48 individual tools.
- [x] 3.5 Verify the architecture diagram labels are readable in a desktop browser viewport and that SVG paths, nodes, highlights, and animations do not overlap.
- [x] 3.6 Update responsive CSS so the hero, terminal, metrics, and architecture diagram remain usable below 1000px and 680px widths.

## 4. Access Page Visual Redesign and Navigation

- [x] 4.1 Replace the light access page theme with the same dark neon design language used by the showcase page, and verify text contrast remains readable.
- [x] 4.2 Add an icon-only return path from `access.html` to the showcase page, and verify it is visually discoverable without adding text.
- [x] 4.3 Convert the target platform selector into 8 platform cards while preserving an `id="platform"` selected value or equivalent getter used by generation logic; verify clicking each card updates the selected platform.
- [x] 4.4 Redesign server address, Token, access level, source IP, and Token safety information as product-style status panels; verify the values still update after `/api/access-info` returns.
- [x] 4.5 Change the primary CTA label to “生成专属接入配置” and verify existing generate behavior still executes.
- [x] 4.6 Add dynamic generated-status text such as “已为 <platform> 生成接入配置” and verify it updates after initial generation and after platform switching.

## 5. Access Page Code Preview and Qoder Support

- [x] 5.1 Replace the visible textarea preview with a code-editor-style preview that includes line-number or equivalent code reading affordances, and verify the generated content is visible and scrollable.
- [x] 5.2 Store the generated raw Markdown separately from the rendered preview and verify copy-to-clipboard uses the raw text without line numbers or HTML.
- [x] 5.3 Verify download uses the same raw Markdown source and produces `mcp-access.md` with the expected content.
- [x] 5.4 Add Qoder to `PLATFORMS` using `mcpServers` root, `url`, and `headers.Authorization`, with no `type` field; verify generated Qoder JSON matches the selected format.
- [x] 5.5 Update access page error text to point users to `http://服务器IP:8765/access` and verify the old root-path hint is removed.
- [x] 5.6 Ensure existing Trae, Cursor, VS Code Copilot, Claude Desktop, Windsurf, Cline, and Kimi Code config output formats remain unchanged except for visual presentation.

## 6. Validation

- [x] 6.1 Run a static syntax/content check over both HTML files and verify there are no unclosed script/style tags or malformed JSON snippets in embedded data.
- [x] 6.2 Restart the MCP server or run a temporary test port and verify `/`, `/showcase`, `/access`, and `/api/access-info` return expected status codes.
- [x] 6.3 Browser-test `showcase.html`: verify hero metrics animate to 48/8/8/3, terminal typewriter works, architecture section appears as a large meaningful delivery-loop diagram, and Console has no errors.
- [x] 6.4 Browser-test `access.html`: verify access info loads, all 8 platform cards can be selected, Qoder output is correct, copy works, download works, return icon navigates to showcase, and Console has no errors.
- [x] 6.5 Verify no demo mode, no global runtime dashboard/status strip, and no 48-tool expansion/point matrix were introduced.
