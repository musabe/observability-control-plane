---
title: Markdown Style Guide
category: standards
status: stable
owner: vorsa
last_updated: 2026-05-16
---

# Vorsa Markdown Style Guide

> Unified documentation standard for all Vorsa platform repositories.

---

## Purpose

This guide defines the structural, visual, and tonal standards for all Markdown
documentation produced within the Vorsa platform ecosystem. Consistent documentation
reinforces operational credibility and reduces cognitive overhead during incident response.

---

## Document Structure

All Vorsa Markdown documents follow this structural hierarchy. Not every section
is required in every document — use what is applicable, maintain the order.

```
# Document Title
> One-line operational summary.
---
## Purpose
## Scope
## Architecture Context
## Operational Flow
## Detection Signals        (telemetry docs)
## Incident Example         (runbooks, scenarios)
## Remediation Guidance     (runbooks)
## Related Components
## Status
```

---

## Heading Hierarchy

| Level | Usage |
|---|---|
| `#` H1 | Document title only — one per file |
| `##` H2 | Major sections |
| `###` H3 | Subsections within a major section |
| `####` H4 | Rarely used — inline detail only |

Never skip heading levels. Never use H1 for section headings.

---

## Frontmatter

All major documents include YAML frontmatter:

```yaml
---
title: Document Title
category: architecture | incident | runbook | scenario | standard
severity: critical | warning | info       (incident/scenario docs only)
status: stable | draft | deprecated
owner: vorsa
last_updated: YYYY-MM-DD
---
```

---

## Callout Blocks

Use GitHub-compatible callout syntax consistently:

```markdown
> [!NOTE]
> Operational context or supplementary information.

> [!WARNING]
> Critical production behaviour. Operators must read before proceeding.

> [!TIP]
> Recommended remediation workflow or best practice.

> [!IMPORTANT]
> Required configuration or prerequisite.
```

**Usage rules:**
- `NOTE` — context that aids understanding but is not critical path
- `WARNING` — behaviour that could cause data loss, outage, or misdiagnosis
- `TIP` — recommended operational shortcuts or preferred approaches
- `IMPORTANT` — prerequisites, required config, non-optional steps

---

## Tables

Use tables for structured data. Always include a header row and alignment.

```markdown
| Column | Column | Column |
|---|---|---|
| Value | Value | Value |
```

For signal/telemetry tables, always include severity column:

```markdown
| Source | Signal | Value | Severity |
|---|---|---|---|
| POSTGRES | connection_pct | 82% | warning |
```

---

## Code Blocks

Always specify the language for syntax highlighting:

````markdown
```yaml
environments:
  - name: northvale-council
```

```python
result.connections_by_db = {
    r["datname"]: int(r["jdbc_connections"]) for r in rows
}
```

```sql
SELECT pid, query, state FROM pg_stat_activity WHERE state != 'idle';
```

```powershell
Get-Service -Name "*qmatic*" | Select-Object Name, Status
```
````

For operational output / log lines, use plain code blocks:

````markdown
```
2026-05-16 15:21:03  WARNING  [northvale-council] INCIDENT: JVM memory pressure
```
````

---

## Operational Diagrams

Use ASCII diagrams for topology, signal chains, and flow diagrams.
Keep them compact and operationally relevant.

```
PostgreSQL unavailable
      │
      ├── JDBC connections → 0  (all databases)
      ├── HTTP endpoint → timeout
      └── Qmatic services → stopped (cascade)
```

---

## Metadata / Status Tables

End operational documents with a status table:

```markdown
| Field | Value |
|---|---|
| **Component** | component name |
| **Status** | stable / draft |
| **Last tested** | YYYY-MM-DD |
| **Vorsa version** | 2.0 |
| **Related runbook** | [link](path) |
```

---

## Separators

Use `---` horizontal rules to separate major sections. Do not use `***` or `___`.

---

## Lists

Use `-` for unordered lists. Use `1.` for ordered/sequential steps.
Keep list items parallel in structure — all start with a verb or noun, not mixed.

**Good:**
```markdown
- Verify PostgreSQL service state
- Check Windows Event Log for crash details
- Restart service if safe to do so
```

**Bad:**
```markdown
- The PostgreSQL service
- Check event log
- you should restart
```

---

## Inline Formatting

| Format | Usage |
|---|---|
| `backticks` | Signal names, field names, values, commands, file paths |
| **bold** | Critical warnings, key terms on first use |
| *italic* | Rarely used — document titles in references only |
| ~~strikethrough~~ | Deprecated terminology only |

---

## File Naming

```
docs/architecture/overview.md
docs/scenarios/scenario-a-postgres-outage.md
docs/standards/markdown-style-guide.md
incidents/INC-2026-0514-001-db-unavailable.md
runbooks/postgres-outage.md
```

- Lowercase with hyphens
- No spaces
- Descriptive, not generic (`postgres-outage.md` not `runbook1.md`)
- Incident files prefixed with `INC-YYYY-MMDD-NNN`
