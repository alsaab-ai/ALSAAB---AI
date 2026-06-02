from pathlib import Path

p = Path("backend/main.py")
t = p.read_text(encoding="utf-8")

old = '''        # ===== ALSAAB_PARTNER_RANK_UI_V2 START =====
        def _rank_level_number(value):'''

new = '''        # ===== ALSAAB_PARTNER_RANK_UI_V2 START =====
        is_ar = True

        def _rank_level_number(value):'''

if old not in t:
    raise SystemExit("TARGET_NOT_FOUND")

p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("PATCH_OK")
