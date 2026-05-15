"""
patch_health_score_lists.py
Run from repo root: python patch_health_score_lists.py
"""

path = "correlators/health_score.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    "if pg_snap.blocked_queries > 0:",
    "if len(pg_snap.blocked_queries) > 0:"
).replace(
    "reasons.append(f\"blocked_queries({pg_snap.blocked_queries}) -10\")",
    "reasons.append(f\"blocked_queries({len(pg_snap.blocked_queries)}) -10\")"
).replace(
    "if pg_snap.long_running_queries > 0:",
    "if len(pg_snap.long_running_queries) > 0:"
).replace(
    "reasons.append(f\"long_queries({pg_snap.long_running_queries}) -5\")",
    "reasons.append(f\"long_queries({len(pg_snap.long_running_queries)}) -5\")"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done")
