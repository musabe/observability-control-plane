"""
patch_windows_collector.py
Run from repo root: python patch_windows_collector.py
"""

# ── Patch config/loader.py — add windows config to EnvironmentConfig ──────────

path = "config/loader.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

if "windows_host" not in content:
    # Add windows_host field to EnvironmentConfig dataclass
    old = "    postgres: Optional[PostgresConfig]"
    new = "    windows_host: Optional[str]\n    windows_user: str\n    postgres: Optional[PostgresConfig]"
    content = content.replace(old, new)

    # Add windows_host extraction in load_environments
    old = "        environments.append(EnvironmentConfig("
    new = (
        "        windows_host = entry.get('windows', {}).get('host', None)\n"
        "        windows_user = entry.get('windows', {}).get('username', 'Administrator')\n\n"
        "        environments.append(EnvironmentConfig("
    )
    content = content.replace(old, new)

    # Add windows_host and windows_user to the EnvironmentConfig constructor
    old = "            postgres=pg_cfg,"
    new = "            windows_host=windows_host,\n            windows_user=windows_user,\n            postgres=pg_cfg,"
    content = content.replace(old, new)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Patched config/loader.py")
else:
    print("config/loader.py already patched")

# ── Patch control_plane.py — add windows collection ──────────────────────────

path2 = "control_plane.py"
with open(path2, "r", encoding="utf-8") as f:
    content2 = f.read()

if "WindowsCollector" not in content2:
    # Add import
    old = "from collectors.http_collector import HttpCollector"
    new = "from collectors.http_collector import HttpCollector\nfrom collectors.windows_collector import WindowsCollector"
    content2 = content2.replace(old, new)

    # Add windows collection block after http collection
    old = "    # ── 3. Qmatic DB checks"
    new = """    # ── 2b. Windows memory + service checks ─────────────────────────────
    if env.windows_host:
        try:
            win_collector = WindowsCollector(env.name, env.windows_host)
            win_snap = win_collector.collect()
            env_state["windows"] = {
                "available": win_snap.available,
                "severity": win_snap.severity,
                "total_memory_mb": win_snap.total_memory_mb,
                "free_memory_mb": win_snap.free_memory_mb,
                "used_memory_mb": win_snap.used_memory_mb,
                "memory_used_pct": win_snap.memory_used_pct,
                "qmatic_total_memory_mb": win_snap.qmatic_total_memory_mb,
                "services": [
                    {
                        "name": s.name,
                        "display_name": s.display_name,
                        "state": s.state,
                        "memory_mb": s.memory_mb,
                    }
                    for s in win_snap.services
                ],
                "error": win_snap.error,
            }
        except Exception as exc:
            logger.error("[%s] Windows collection error: %s", env.name, exc)

    # ── 3. Qmatic DB checks"""
    content2 = content2.replace(old, new)

    with open(path2, "w", encoding="utf-8") as f:
        f.write(content2)
    print("Patched control_plane.py")
else:
    print("control_plane.py already patched")

print("\nDone. Now update config/environments.yaml to add:")
print("""
    windows:
      host: 192.168.68.114
      username: Administrator
""")
print("And set env vars:")
print("  OBS_WMI_USER_CXM_TEST_LOCAL=Administrator")
print("  OBS_WMI_PASSWORD_CXM_TEST_LOCAL=yourpassword")
print("\nThen run: python control_plane.py --once")
