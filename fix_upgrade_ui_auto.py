from pathlib import Path
import re

path = Path("backend/upgrade_routes.py")
text = path.read_text(encoding="utf-8")
path.with_suffix(".py.bak_upgrade_ui_auto_fix").write_text(text, encoding="utf-8")

current_select = """<select name="current_plan" required>
      <option value="">اختر الباقة الحالية</option>
      <option value="entry">الدخول / Entry — 99 AED</option>
      <option value="starter">البداية / Starter — 299 AED</option>
      <option value="growth">النمو / Growth — 599 AED</option>
      <option value="elite">النخبة / Elite — 1199 AED</option>
      <option value="diamond">الماسية / Diamond — 2399 AED</option>
    </select>"""

target_select = """<select name="target_plan" required>
      <option value="">اختر الباقة الجديدة</option>
      <option value="starter">البداية / Starter — 299 AED</option>
      <option value="growth">النمو / Growth — 599 AED</option>
      <option value="elite">النخبة / Elite — 1199 AED</option>
      <option value="diamond">الماسية / Diamond — 2399 AED</option>
    </select>"""

text = re.sub(
    r'<select name="current_plan" required>.*?</select>',
    current_select,
    text,
    count=1,
    flags=re.S
)

text = re.sub(
    r'<select name="target_plan" required>.*?</select>',
    target_select,
    text,
    count=1,
    flags=re.S
)

text = text.replace(
    'UPGRADE_PLAN_ORDER = ["entry", "starter", "growth", "elite"]',
    'UPGRADE_PLAN_ORDER = ["entry", "starter", "growth", "elite", "diamond"]'
)

path.write_text(text, encoding="utf-8")
