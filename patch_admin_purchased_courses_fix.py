from pathlib import Path

p = Path("backend/main.py")
t = p.read_text(encoding="utf-8")

start_marker = "# ===== ALSAAB_PARTNER_RANK_UI_V2 START ====="
end_marker = "# ===== ALSAAB_PARTNER_RANK_UI_V2 END ====="

start = t.find(start_marker, t.find("def admin_dashboard_view"))
end = t.find(end_marker, start)

if start == -1 or end == -1:
    raise SystemExit("MARKERS_NOT_FOUND")

block = t[start:end]
block2 = block.replace("purchased_courses", "search_purchased_courses")

if block2 == block:
    raise SystemExit("NO_CHANGES_MADE")

t = t[:start] + block2 + t[end:]
p.write_text(t, encoding="utf-8")
print("PATCH_OK")
