from pathlib import Path

p = Path("backend/main.py")
t = p.read_text(encoding="utf-8")

replacements = {
    'current_level_num = _rank_level_number(level.get("current_level") or level.get("partner_rank"))': 'current_level_num = _rank_level_number(search_level.get("current_level") or search_level.get("partner_rank"))',
    'completed_sales_count = _safe_int(level.get("completed_sales") or customers.get("active_direct_paid_count") or 0)': 'completed_sales_count = _safe_int(search_level.get("completed_sales") or search_customers.get("active_direct_paid_count") or 0)',
    'package_value = str(level.get("current_package") or "").lower()': 'package_value = str(search_level.get("current_package") or "").lower()',
    '"current_package": level.get("current_package") or "-",': '"current_package": search_level.get("current_package") or "-",',
    '"subscription_status": level.get("subscription_status") or "-",': '"subscription_status": search_level.get("subscription_status") or "-",',
    '"commission_eligible": level.get("commission_eligible") or "-",': '"commission_eligible": search_level.get("commission_eligible") or "-",',
}

changed = 0
for old, new in replacements.items():
    if old in t:
        t = t.replace(old, new, 1)
        changed += 1

if changed == 0:
    raise SystemExit("NO_CHANGES_MADE")

p.write_text(t, encoding="utf-8")
print(f"PATCH_OK changed={changed}")
