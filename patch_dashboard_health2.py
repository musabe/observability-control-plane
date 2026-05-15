"""
patch_dashboard_health2.py
Run from repo root: python patch_dashboard_health2.py
"""

path = "dashboard/index.html"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find and print the current renderEnv section around score/scoreClass
start = content.find("function renderEnv")
chunk = content[start:start+800]
print("Current renderEnv start:")
print(chunk)
print("---")

# Fix: replace the broken _hs pattern with clean version
# Remove any partial _hs references and rewrite cleanly

import re

# Replace the whole score/scoreClass/sevLabel block
old_block = re.search(
    r'const _hs=healthScore\(env\);\s*\n\s*const scoreClass[^\n]+\n\s*.*\n\s*const sevLabel[^\n]+',
    content
)

if old_block:
    print("Found broken block:", old_block.group())
    new_block = """const score=healthScore(env);
  const scoreClass=score>=90?'ok':score>=60?'warning':'critical';
  const sevLabel=healthLabel(env);"""
    content = content[:old_block.start()] + new_block + content[old_block.end():]
    print("Fixed score/scoreClass/sevLabel block")
else:
    print("Block not found via regex — doing manual replacement")
    # Try to find and fix line by line
    lines = content.split('\n')
    new_lines = []
    skip_next = False
    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        if '_hs=healthScore(env)' in line:
            new_lines.append("  const score=healthScore(env);")
            skip_next = False
        elif 'scoreClass=_hs>=' in line or "scoreClass=env.overall_severity" in line:
            new_lines.append("  const scoreClass=score>=90?'ok':score>=60?'warning':'critical';")
        elif 'const score=_hs' in line or line.strip() == 'const score=_hs;':
            pass  # skip
        else:
            new_lines.append(line)
    content = '\n'.join(new_lines)
    print("Applied line-by-line fix")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done — restart HTTP server and hard refresh")
