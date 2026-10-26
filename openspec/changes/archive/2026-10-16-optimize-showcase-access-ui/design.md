## Context

`showcase.html` and `access.html` are static HTML pages served by `mcp_server/server.py`. The existing routing serves `/` and `/showcase` as the showcase page and `/access` as the connection tool page. The backend APIs used by these pages are already available and this change does not add server endpoints.

The current showcase page uses a dark neon theme and a six-part narrative. The current access page uses a light administrative form theme, causing a visual break after the showcase CTA. The current architecture diagram is embedded in the hero right column and is visually too small; its text becomes hard to read and it does not clearly communicate the AI-driven delivery loop.

One implementation attempt began before this proposal workflow and partially changed `showcase.html` CSS for the hero/architecture area. The apply phase must inspect the current file state first and reconcile those partial edits rather than assuming a clean pre-change file.

## Goals / Non-Goals

**Goals:**
- Keep the showcase page as a finished product showcase, not a decision-making proposal page.
- Keep the `同一件事，两种做法` title and make only the requested subtitle copy change.
- Use hero layout option 2: left copy + metrics, right enlarged terminal session.
- Move the architecture diagram out of the hero and redesign it as a large, meaningful data-flow/delivery-loop diagram.
- Express AI agent value through a simple path from protocol document request to generated/tested/packaged delivery.
- Make `access.html` visually coherent with the showcase dark neon theme.
- Add Qoder to both the showcase compatibility view and access target platforms.
- Preserve existing backend API behavior, token assignment, IP binding, copy, download, and generated config semantics.

**Non-Goals:**
- Do not expand all 48 MCP tools in the architecture diagram.
- Do not create a 48-tool point matrix.
- Do not add demo mode.
- Do not add a global runtime dashboard/status strip.
- Do not rewrite the closing line wording beyond changing the client count from 7 to 8.
- Do not change MCP authentication, `/api/access-info`, or Skills export endpoints.

## Decisions

### Decision 1: Keep the hero as two columns, but replace the right-side diagram with a terminal

Use the hero layout requested by the user:
- Left column: eyebrow, title, subtitle, and 2x2 core metrics.
- Right column: enlarged terminal-style AI agent execution session.

Rationale:
- The terminal already has strong “AI is doing work now” affordance through the typewriter interaction.
- The current small architecture diagram loses meaning in the hero right column.
- Moving the diagram out allows both hero and architecture sections to have a clear visual center.

Alternatives considered:
- Single-column hero with centered terminal: lower risk but visually less balanced.
- Keep the small diagram in the hero: preserves current structure but does not solve the user’s core complaint.

### Decision 2: Redesign architecture as a delivery-loop diagram, not a tool inventory

The architecture diagram should show the path:
`用户需求 → AI 智能体理解意图 → 协议识别与技能路由 → MCP 工具网关 → 配置生成 / 测试验证 / 打包分发 / 上线运行`.

It should mention 48 atomic tools only as a capability label on the MCP gateway, not as 48 separate visual elements.

Rationale:
- The next capability matrix section already explains tool count and tool groups.
- The diagram’s purpose is to explain meaning and flow, not enumerate implementation details.
- Fewer larger nodes improve readability and make the diagram feel intentional.

Alternatives considered:
- 48-tool point matrix: rejected because the user clarified that the problem is not lack of tool expansion.
- Existing five-layer small SVG: rejected because text size and visual importance are insufficient.

### Decision 3: Use dark-neon styling inline in access.html

Keep `access.html` self-contained and inline its CSS instead of introducing shared CSS files.

Rationale:
- Current server routing sends unrecognized static paths to MCP auth, so a new `/theme.css` would require backend route work.
- This change is intended to improve UI only and should not expand the static routing or auth surface.
- Two HTML files can tolerate duplicated design tokens.

Alternatives considered:
- Shared CSS route: cleaner long-term but changes backend routing/security boundaries.
- Minimal recolor of existing access page: lower effort but would not deliver the requested “炫” product-console feel.

### Decision 4: Convert platform selection to cards while preserving a hidden platform value

Use 8 platform cards for selection and maintain an element with `id="platform"` holding the current selected platform value. Existing generation logic should continue to read the selected platform value from this id, or be minimally adapted to an equivalent helper.

Rationale:
- Cards align visually with the showcase page and make Qoder addition feel intentional.
- A hidden value avoids large changes to `generateText()` semantics.

Alternatives considered:
- Keep `<select>` and only restyle it: insufficient visual impact.
- Fully rebuild platform state management: unnecessary for a static page.

### Decision 5: Code-editor preview uses a display layer plus raw text source

Replace the visible `textarea` with a code-editor-like preview. Store the generated raw Markdown in a separate variable or hidden form field. Copy and download must use the raw text, not the rendered preview DOM.

Rationale:
- `pre/code` enables line numbers and syntax-like styling that a textarea cannot provide well.
- Raw source separation prevents copying line numbers or HTML markup.

Alternatives considered:
- Keep textarea and style it: safer but does not satisfy the confirmed requirement to “连 7 一起做”.
- Use a third-party highlighter: rejected to keep the page dependency-free.

### Decision 6: Qoder uses url + headers without type

Qoder generated config should use:

```json
{
  "mcpServers": {
    "protocol-converter": {
      "url": "http://<host>:8765/mcp",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

Rationale:
- User explicitly selected this format.
- It matches Qoder’s `mcpServers` root and relies on automatic remote transport recognition.

Alternatives considered:
- Explicit `type: "streamable-http"`: not selected by the user.

## Risks / Trade-offs

- [Risk] Static HTML refactor can break copy/download behavior in `access.html` → Mitigation: keep raw generated text separate from preview markup and verify copy/download manually in browser.
- [Risk] Architecture SVG can look correct in code but cramped in browser → Mitigation: verify actual desktop viewport rendering and ensure diagram labels remain readable.
- [Risk] Existing partial `showcase.html` edits may leave duplicated or inconsistent CSS → Mitigation: apply phase must inspect current CSS/HTML before editing and reconcile partial work into a coherent final structure.
- [Risk] Qoder remote MCP format may vary by product version → Mitigation: generate the user-selected `url + headers` format and document that browser/Qoder connection should be tested after implementation.
- [Risk] Access page dark theme may reduce readability of long installation notes → Mitigation: use card separation, smaller note sections, and code-like hierarchy rather than dense paragraphs.

## Migration Plan

1. Implement changes in `showcase.html` and `access.html` only.
2. Do not change `server.py` routes or backend API behavior.
3. Restart the MCP server because static HTML is read during server startup.
4. Browser-test `/`, `/showcase`, and `/access`.
5. Verify platform switching, Qoder config output, copy, download, and console errors.
6. Rollback by reverting the two static HTML files if visual or interaction regressions are found.
