## Context

See proposal.md for motivation. Current MCP Server already exposes `list_mcp_tools`, `login`, 14 read tools and 32 write tools. `server.py` already has `/api/access-info`, Skills ZIP export, IPv4 filtering in `_get_server_ips()`, and system/user permission separation. The `/pca` Skill is still aligned with older 3000-port and older tool names in several sections, and it has no explicit business Token cache or Skills update workflow. The MODBUS Skill already defines MCP-first lookup, local references fallback and two-stage platform sync, but the recent F3000X test exposed gaps in output structure, field semantics and ambiguity handling.

## Goals / Non-Goals

**Goals:**
- Make `/pca` entry behavior predictable: connection probe, permission summary, local business Token reuse, login prompt only when missing or invalid.
- Add an explicit user-confirmed full Skills update flow with backup before overwrite.
- Ensure user-visible connection URLs and generated configuration snippets use IPv4 or localhost, not IPv6.
- Improve MODBUS conversion outputs so they are usable as professional handoff records: summary, stages, precise field provenance, enhanced point tables, ambiguity confirmations, smoke tests and unverified items.

**Non-Goals:**
- Do not change the backend authentication protocol itself.
- Do not make business Token storage a secure credential vault in this change; use a local cache with clear lifecycle and invalidation behavior.
- Do not reject IPv6 requests at the server layer; only avoid exposing IPv6 in user-facing configuration and output.
- Do not implement HTTP/MQTT conversion workflow refactors in this change.
- Do not automatically write platform data or sync protocol files without existing confirmation rules.

## Decisions

### Decision 1: Business Token is a local reusable cache, not MCP auth
`/pca` should check for a cached backend business Token before prompting. If present, it attempts read-only platform calls with it; if an API returns `AUTH_ERROR`, the cache is treated as invalid and login is requested again. The cached Token is never written to MCP configuration and never used as `Authorization: Bearer`.

Alternatives considered:
- Prompt every run: safe but noisy and contradicts the user requirement.
- Never cache: simple but poor user experience.
- Store inside MCP server memory: does not survive process/client boundaries and does not address local Skill usage.

### Decision 2: Skills update is full-package overwrite with backup
The update flow should download the server-exported Skills ZIP, backup the existing `.trae/skills` directory, then overwrite all Skills after explicit user confirmation. This matches the user's chosen scope: update all modifications, allow overwrite, and keep a fallback.

Alternatives considered:
- Per-Skill diff update: more precise but requires manifest/version diff and conflict UI.
- Silent auto-update: risky because it can replace local custom edits and may not affect the current loaded Skill immediately.

### Decision 3: IPv4-only applies to user-facing generated addresses
`_get_server_ips()` already excludes IPv6 for server IP lists. The design should extend that principle to access page copy text, Skill instructions and `/pca` output. Auth middleware may continue treating `::1` as localhost for compatibility.

Alternatives considered:
- Disable IPv6 entirely: unnecessary and could break local environments.
- Keep IPv6 in generated configs: conflicts with user requirement and is less friendly in Windows/client setup.

### Decision 4: Skill specification controls local JSON data_type
When protocol documents or platform records expose ambiguous or legacy type names, the local JSON must use Skill-defined data types such as `[FLOAT32]`. Platform legacy differences like `[FLOAT]` are recorded as differences or validation risks rather than silently copied.

Alternatives considered:
- Follow platform historical scripts: improves similarity but can conflict with the C engine JSON contract.
- Always follow protocol wording: protocol PDFs may use generic words like Float that need normalization.

### Decision 5: Ambiguity is surfaced before generation
For `func_code`, units, labels, address variants, accumulation precision, field naming and platform gaps, the flow should present explicit options and wait for user confirmation when the choice affects output behavior. If the protocol document is explicit, it is the default source; if it is absent or conflicting, no final JSON should be generated until confirmed.

## Risks / Trade-offs

- [Risk] Cached business Token may become invalid or stale → Mitigation: treat `AUTH_ERROR`/40100 as invalidation and prompt login again.
- [Risk] Local Token cache introduces sensitive file handling → Mitigation: document location, avoid logs, do not commit, and provide deletion/refresh guidance.
- [Risk] Full Skills overwrite may remove local user edits → Mitigation: mandatory backup before overwrite and explicit confirmation.
- [Risk] Updated Skills may not affect the currently running conversation → Mitigation: after update, always instruct the user to reload `/pca` or restart the client.
- [Risk] Existing docs still mention port 3000 → Mitigation: tasks must update user-facing PCA/access texts to 8765/IPv4 where relevant.
- [Risk] Output template changes can become verbose → Mitigation: keep final answer summary concise while preserving complete handoff sections when writing records.

## Migration Plan

1. Update `/pca` Skill documentation to define preflight, Token cache, Skills update, IPv4 and user-facing summary behavior.
2. Update `modbus-conversion` Skill documentation to refine func_code/data_type decisions, ambiguity confirmation, enhanced output table and final record template.
3. Add or adjust MCP/access endpoints only as needed for version manifest or IPv4-safe Skills download links.
4. Validate with static checks plus a real `/pca` flow: no cached Token path, cached Token path, invalid Token path, update declined path, update confirmed path, and MODBUS conversion summary output.
5. Rollback by restoring the backed-up `.trae/skills` directory and reverting the change if validation fails.
