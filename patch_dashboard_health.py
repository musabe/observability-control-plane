"""
patch_dashboard_health.py
Run from repo root: python patch_dashboard_health.py
"""

path = "dashboard/index.html"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ── Replace random health score function with real data ───────────────────────
old_score = """function healthScore(env){
  if(env.overall_severity==='critical')return Math.floor(25+Math.random()*20);
  if(env.overall_severity==='warning')return Math.floor(60+Math.random()*20);
  return Math.floor(94+Math.random()*5);
}"""

new_score = """function healthScore(env){
  return env.health_score !== undefined && env.health_score !== null
    ? env.health_score
    : (env.overall_severity==='critical' ? 35 : env.overall_severity==='warning' ? 70 : 97);
}

function healthLabel(env){
  return env.health_label || (env.overall_severity==='critical' ? 'CRITICAL' : env.overall_severity==='warning' ? 'DEGRADED' : 'HEALTHY');
}"""

if old_score in content:
    content = content.replace(old_score, new_score)
    print("Replaced healthScore function")
else:
    print("WARNING: healthScore function not found")

# ── Replace sevLabel to use healthLabel ───────────────────────────────────────
old_sevlabel = "  const sevLabel={'ok':'HEALTHY','warning':'DEGRADED','critical':'INCIDENT'}[env.overall_severity]||env.overall_severity.toUpperCase();"
new_sevlabel = "  const sevLabel=healthLabel(env);"

if old_sevlabel in content:
    content = content.replace(old_sevlabel, new_sevlabel)
    print("Updated sevLabel to use healthLabel()")
else:
    print("WARNING: sevLabel line not found")

# ── Replace scoreClass to map from health_score ───────────────────────────────
old_scoreclass = "  const scoreClass=env.overall_severity==='ok'?'ok':env.overall_severity==='warning'?'warning':'critical';"
new_scoreclass = """  const _hs=healthScore(env);
  const scoreClass=_hs>=90?'ok':_hs>=60?'warning':'critical';"""

if old_scoreclass in content:
    content = content.replace(old_scoreclass, new_scoreclass)
    print("Updated scoreClass from health_score")
else:
    print("WARNING: scoreClass line not found")

# ── Replace score variable usage ──────────────────────────────────────────────
old_scorevar = "  const score=healthScore(env);"
new_scorevar = "  const score=_hs;"

# Only replace if scoreClass was updated (which defines _hs)
if old_scorevar in content and "_hs=healthScore" in content:
    content = content.replace(old_scorevar, new_scorevar)
    print("Updated score variable")
else:
    # scoreClass patch already uses _hs, just remove the old score line
    content = content.replace(old_scorevar, "")
    print("Removed redundant score variable")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done — hard refresh browser to see changes")
