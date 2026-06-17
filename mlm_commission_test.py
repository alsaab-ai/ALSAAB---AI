import sys
sys.path.insert(0, "backend")

import level_engine

checks = {
    1: 25.0,
    2: 5.0,
    3: 4.0,
    4: 3.0,
    5: 2.0,
}

ok = True
lines = []

for depth, expected in checks.items():
    actual = level_engine.get_commission_rate_for_depth(depth)
    lines.append(f"depth {depth}: {actual}")
    if actual != expected:
        ok = False

for level in range(1, 6):
    eligible = level_engine.is_partner_eligible_for_commission_depth(level, level, "active")
    lines.append(f"level {level} eligible depth {level}: {eligible}")
    if not eligible:
        ok = False

print("\n".join(lines))
print("MLM_COMMISSION_OK" if ok else "MLM_COMMISSION_FAILED")
