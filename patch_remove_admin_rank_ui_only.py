from pathlib import Path

p = Path("backend/main.py")
t = p.read_text(encoding="utf-8")

admin_start = t.find('def admin_dashboard_view')
start_marker = "# ===== ALSAAB_PARTNER_RANK_UI_V2 START ====="
end_marker = "# ===== ALSAAB_PARTNER_RANK_UI_V2 END ====="

start = t.find(start_marker, admin_start)
end = t.find(end_marker, start)

if admin_start == -1 or start == -1 or end == -1:
    raise SystemExit("TARGET_NOT_FOUND")

end = end + len(end_marker)

t = t[:start] + '''        rank_ui = {}\n        # Admin Dashboard: partner rank UI block removed from admin scope safely.\n''' + t[end:]

p.write_text(t, encoding="utf-8")
print("PATCH_OK_ADMIN_ONLY")
